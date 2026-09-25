"""Build onus's sdist and wheel from the tracked files, and check them the way a release would.

A release tag is permanent (the release-tags ruleset), so a packaging mistake that only the release workflow
finds spends a version number. ``make check`` runs this with ``--build`` on every change, before any tag
exists; the release workflow runs the same checks on the artifacts it is about to publish.

The build happens in a scratch copy of the files git tracks, so that only they can reach the artifacts. Built
in the checkout, the sdist would also take in an untracked module under ``onus/``, through package discovery,
and every file listed in an ``onus.egg-info/SOURCES.txt`` left by an earlier build, since setuptools reads that
list back. Keeping ``git status`` clean is not the reason: ``*.egg-info/`` is gitignored.

Exit status: 0 when the artifacts may be released; 3 (``DEFECTIVE``) when they may not, a packaging defect a
re-run cannot fix, including tracked files the build backend refuses; 4 (``NOT_BUILT``) when nothing could be
checked, because the build itself could not run (a missing tool, the network while fetching the backend, a
file that could not be copied, a tracked file missing from the working tree), which a re-run after fixing the
cause can; a build requirement no index has exits 4 as well, so a 4 that repeats is the commit's own. Any
other status is not a verdict: 1 is what Python exits with on an uncaught exception, and 2 is argparse's usage
error.
"""

import argparse
import ast
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import tomllib
import zipfile
from collections.abc import Callable, Iterable, Sequence
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parent.parent
Runner = Callable[..., subprocess.CompletedProcess[str]]
# Neither 1 (an uncaught exception) nor 2 (argparse's usage error), so a crash never reads as a verdict.
DEFECTIVE, NOT_BUILT = 3, 4


class BuildError(Exception):
    """The build could not run, so nothing was checked; the message says why and what clears it."""


class UnbuildableError(Exception):
    """The build ran and the backend refused the tracked files, so they cannot be released as they stand."""


def source_version(root: Path = ROOT) -> str:
    """Return ``__version__`` as ``onus/__init__.py`` assigns it, without importing the package."""
    tree = ast.parse((root / "onus" / "__init__.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == "__version__" for t in node.targets):
            if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                return node.value.value
    raise ValueError("onus/__init__.py assigns no string __version__")


def metadata_version(text: str) -> str | None:
    """Return the ``Version:`` header of a METADATA or PKG-INFO text; the headers end at the first blank line."""
    for line in text.splitlines():
        if not line.strip():
            break
        if line.startswith("Version:"):
            return line.removeprefix("Version:").strip()
    return None


def version_problems(wheel: zipfile.ZipFile, sdist: tarfile.TarFile, names: tuple[str, str], version: str) -> list[str]:
    """Return how the artifacts' own names and metadata disagree with ``version``.

    The wheel prints ``onus.__version__`` on import, but a setup.py ``tag_build``, or a ``__version__`` that
    setuptools normalises, changes the version the files are named and described by without changing that.
    """
    found = []
    for name, expected in zip(names, (f"onus-{version}-py3-none-any.whl", f"onus-{version}.tar.gz"), strict=True):
        if name != expected:
            kind = "wheel" if name.endswith(".whl") else "sdist"
            found.append(f"the {kind} is named {name}, not {expected}")
    metadata = [name for name in wheel.namelist() if re.fullmatch(r"[^/]+\.dist-info/METADATA", name)]
    if len(metadata) != 1:
        found.append("the wheel has no .dist-info/METADATA")
    elif (said := metadata_version(wheel.read(metadata[0]).decode("utf-8"))) != version:
        found.append(f"the wheel's METADATA says Version {said}, not {version}")
    pkg_info = [member for member in sdist.getmembers() if re.fullmatch(r"[^/]+/PKG-INFO", member.name)]
    extracted = sdist.extractfile(pkg_info[0]) if len(pkg_info) == 1 else None
    if extracted is None:
        found.append("the sdist has no PKG-INFO")
    elif (said := metadata_version(extracted.read().decode("utf-8"))) != version:
        found.append(f"the sdist's PKG-INFO says Version {said}, not {version}")
    return found


def problems(dist: Path, version: str) -> list[str]:
    """Return what stops the artifacts in ``dist`` from being released as ``version``; empty when nothing does.

    Checks that there is exactly one wheel and one sdist, named and described (METADATA, PKG-INFO) as
    ``version``; that the wheel carries the ``py.typed`` marker; that the sdist leaves out the repository's own
    tests; and that the wheel imports with the standard library alone (``-I -S``, straight from the zip, from
    outside any checkout) and reports ``version``. ``dist`` may be relative to the current directory.
    """
    dist = dist.resolve()
    wheels, sdists = sorted(dist.glob("*.whl")), sorted(dist.glob("*.tar.gz"))
    if len(wheels) != 1 or len(sdists) != 1:
        found = [path.name for path in wheels + sdists]
        return [f"expected exactly one wheel and one sdist in {dist}, found {found}"]
    found_problems = []
    with zipfile.ZipFile(wheels[0]) as wheel:
        if "onus/py.typed" not in wheel.namelist():
            found_problems.append(
                "the wheel has no onus/py.typed: it must exist and be listed under [tool.setuptools.package-data], "
                "and neither [tool.setuptools.exclude-package-data] nor a MANIFEST.in exclude may drop it (the wheel "
                "is built from the sdist)"
            )
    with tarfile.open(sdists[0]) as sdist:
        if any(Path(name).parts[1:2] == ("tests",) for name in sdist.getnames()):
            found_problems.append(
                "the sdist carries tests/: MANIFEST.in must prune tests, and no line after it may add them back"
            )
        with zipfile.ZipFile(wheels[0]) as wheel:
            found_problems += version_problems(wheel, sdist, (wheels[0].name, sdists[0].name), version)
    probe = "import sys; sys.path.insert(0, sys.argv[1]); import onus; print(onus.__version__)"
    result = subprocess.run(
        [sys.executable, "-I", "-S", "-B", "-c", probe, str(wheels[0])],
        cwd=dist,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        last = result.stderr.strip().splitlines()[-1:] or ["no error output"]
        found_problems.append(f"the wheel does not import with the standard library alone: {last[0]}")
    elif result.stdout.strip() != version:
        found_problems.append(f"the wheel reports version {result.stdout.strip()}, not {version}")
    return found_problems


def stray_modules(untracked: Iterable[str]) -> list[str]:
    """Return the modules among ``untracked``, which a build from the tracked files would leave out.

    ``untracked`` is what git lists as neither tracked nor ignored. Of those, a module is a ``.py`` path whose
    every part is a Python identifier: an editor's lock file (``.#name.py``), macOS's AppleDouble ``._name.py``,
    or a file in a folder no import can name is not one, and an ignored file never reaches this list.
    """
    return sorted(
        name
        for name in untracked
        if name.endswith(".py") and all(part.isidentifier() for part in PurePosixPath(name).with_suffix("").parts)
    )


def build_requirements(source: Path) -> list[str]:
    """Return the ``[build-system]`` requirements ``source/pyproject.toml`` declares.

    Raises:
        UnbuildableError: the file does not parse, or declares no list of requirements.
    """
    try:
        requires = tomllib.loads((source / "pyproject.toml").read_text(encoding="utf-8"))["build-system"]["requires"]
    except (tomllib.TOMLDecodeError, KeyError) as error:
        raise UnbuildableError(f"pyproject.toml declares no [build-system] requires: {error!r}") from error
    if not isinstance(requires, list) or not all(isinstance(item, str) for item in requires):
        raise UnbuildableError(f"pyproject.toml's [build-system] requires is not a list of strings: {requires!r}")
    return requires


def run_tool(runner: Runner, command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
    """Run ``command`` with ``runner``, turning a tool that cannot be started into a ``BuildError``."""
    try:
        return runner(command, **kwargs)
    except OSError as error:
        raise BuildError(f"could not run {command[0]}: {error}") from error


def build(root: Path, out: Path, python: str, run: Runner | None = None) -> None:
    """Build the sdist and wheel into ``out`` with uv, from a scratch copy of the files git tracks in ``root``.

    The build backend is fetched first, into a scratch environment on ``python``; the build then runs in that
    environment without isolation, so it fetches nothing. A failure while fetching may clear on a re-run; a
    failure of the build itself is the backend refusing the tracked files, which a re-run does not change.

    Raises:
        BuildError: git or uv could not be started, or failed, whose own error output the message carries; a
            module under ``onus/`` is not tracked; a tracked file is missing from the working tree; or the
            tracked files could not be copied into the scratch folder; or the backend could not be fetched.
        UnbuildableError: pyproject.toml names no build requirements, or the backend refused the tracked files.
    """
    runner = subprocess.run if run is None else run
    listing = run_tool(runner, ["git", "ls-files", "-z"], cwd=root, capture_output=True, text=True, check=False)
    if listing.returncode != 0:
        raise BuildError(f"git ls-files failed in {root}: {listing.stderr.strip()}")
    tracked = set(filter(None, listing.stdout.split("\0")))
    others = ["git", "ls-files", "-z", "--others", "--exclude-standard", "--", "onus"]
    untracked = run_tool(runner, others, cwd=root, capture_output=True, text=True, check=False)
    if untracked.returncode != 0:
        raise BuildError(f"git ls-files --others failed in {root}: {untracked.stderr.strip()}")
    stray = stray_modules(filter(None, untracked.stdout.split("\0")))
    if stray:
        raise BuildError(f"not tracked by git, so the build would leave them out: {stray}; `git add` them")
    missing = sorted(name for name in tracked if not (root / name).is_file())
    if missing:
        raise BuildError(f"tracked but missing from the working tree: {missing}; restore them or `git rm` them")
    with tempfile.TemporaryDirectory(prefix="onus-dist-") as scratch:
        source, env = Path(scratch) / "source", Path(scratch) / "env"
        try:
            for name in tracked:
                target = source / name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(root / name, target)
        except OSError as error:
            raise BuildError(f"could not copy the tracked files into a scratch folder: {error}") from error
        requires = build_requirements(source)
        env_python = str(env / "bin" / "python")
        fetch = [
            ["uv", "venv", "--quiet", "--python", python, str(env)],
            ["uv", "pip", "install", "--quiet", "--python", env_python, *requires],
        ]
        for command in fetch:
            result = run_tool(runner, command, capture_output=True, text=True, check=False)
            if result.returncode != 0:
                raise BuildError(f"{' '.join(command[:2])} exited {result.returncode}: {result.stderr.strip()}")
        command = ["uv", "build", "--quiet", "--python", env_python, "--no-build-isolation"]
        command += ["--out-dir", str(out.resolve()), str(source)]
        result = run_tool(runner, command, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            raise UnbuildableError(f"uv build exited {result.returncode}: {result.stderr.strip()}")


def main(argv: Sequence[str] | None = None) -> int:
    """Check a folder of built artifacts, building them first with ``--build``; see the module for exit codes."""
    parser = argparse.ArgumentParser(description="Build and check onus's sdist and wheel as a release would.")
    parser.add_argument("dist", nargs="?", type=Path, help="folder of built artifacts; with --build, where to put them")
    parser.add_argument("--build", action="store_true", help="build from the tracked files first")
    parser.add_argument("--version", help="the version the artifacts must report; defaults to onus.__version__")
    args = parser.parse_args(argv)
    if not args.build and args.dist is None:
        parser.error("give a folder of built artifacts, or --build")
    version = args.version or source_version()
    with tempfile.TemporaryDirectory(prefix="onus-built-") as scratch:
        dist = args.dist if args.dist is not None else Path(scratch)
        if args.build:
            try:
                build(ROOT, dist, sys.executable)
            except BuildError as error:
                print(f"nothing was checked, because the build could not run: {error}", file=sys.stderr)
                return NOT_BUILT
            except UnbuildableError as error:
                print(
                    f"the tracked files do not build, so this commit cannot be released as it stands: {error}",
                    file=sys.stderr,
                )
                return DEFECTIVE
        found = problems(dist, version)
    for problem in found:
        print(problem, file=sys.stderr)
    if not found:
        print(f"one wheel and one sdist of onus {version}: type marker shipped, tests left out, imports alone")
    return DEFECTIVE if found else 0


if __name__ == "__main__":
    sys.exit(main())
