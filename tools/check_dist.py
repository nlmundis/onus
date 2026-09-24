"""Build onus's sdist and wheel from the tracked files, and check them the way a release would.

A release tag is permanent (the release-tags ruleset), so a packaging mistake that only the release workflow
finds spends a version number. ``make check`` runs this with ``--build`` on every change, before any tag
exists; the release workflow runs the same checks on the artifacts it is about to publish.

The build happens in a scratch copy of the files git tracks, because building writes ``onus.egg-info`` into
its source tree, and the gate writes nothing into the checkout but gitignored caches.

Exit status: 0 when the artifacts may be released; 3 (``DEFECTIVE``) when they may not, a packaging defect a
re-run cannot fix; 4 (``NOT_BUILT``) when nothing could be checked, because the build itself could not run (a
missing tool, the network, a file that could not be copied, a tracked file missing from the working tree),
which a re-run after fixing the cause can. Any other status is not a verdict: 1 is what Python exits with on an
uncaught exception, and 2 is argparse's usage error.
"""

import argparse
import ast
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from collections.abc import Callable, Iterable, Sequence
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parent.parent
Runner = Callable[..., subprocess.CompletedProcess[str]]
# Neither 1 (an uncaught exception) nor 2 (argparse's usage error), so a crash never reads as a verdict.
DEFECTIVE, NOT_BUILT = 3, 4


class BuildError(Exception):
    """The build could not run, so nothing was checked; the message says why and what clears it."""


def source_version(root: Path = ROOT) -> str:
    """Return ``__version__`` as ``onus/__init__.py`` assigns it, without importing the package."""
    tree = ast.parse((root / "onus" / "__init__.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == "__version__" for t in node.targets):
            if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                return node.value.value
    raise ValueError("onus/__init__.py assigns no string __version__")


def problems(dist: Path, version: str) -> list[str]:
    """Return what stops the artifacts in ``dist`` from being released as ``version``; empty when nothing does.

    Checks that there is exactly one wheel and one sdist, that the wheel carries the ``py.typed`` marker, that
    the sdist leaves out the repository's own tests, and that the wheel imports with the standard library
    alone (``-I -S``, straight from the zip, from outside any checkout) and reports ``version``. ``dist`` may
    be relative to the current directory.
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


def run_tool(runner: Runner, command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
    """Run ``command`` with ``runner``, turning a tool that cannot be started into a ``BuildError``."""
    try:
        return runner(command, **kwargs)
    except OSError as error:
        raise BuildError(f"could not run {command[0]}: {error}") from error


def build(root: Path, out: Path, python: str, run: Runner | None = None) -> None:
    """Build the sdist and wheel into ``out`` with uv, from a scratch copy of the files git tracks in ``root``.

    Raises:
        BuildError: git or uv could not be started, or failed, whose own error output the message carries; a
            module under ``onus/`` is not tracked; a tracked file is missing from the working tree; or the
            tracked files could not be copied into the scratch folder.
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
        try:
            for name in tracked:
                target = Path(scratch) / name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(root / name, target)
        except OSError as error:
            raise BuildError(f"could not copy the tracked files into a scratch folder: {error}") from error
        command = ["uv", "build", "--python", python, "--quiet", "--out-dir", str(out.resolve()), scratch]
        result = run_tool(runner, command, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            raise BuildError(f"uv build exited {result.returncode}: {result.stderr.strip()}")


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
        found = problems(dist, version)
    for problem in found:
        print(problem, file=sys.stderr)
    if not found:
        print(f"one wheel and one sdist of onus {version}: type marker shipped, tests left out, imports alone")
    return DEFECTIVE if found else 0


if __name__ == "__main__":
    sys.exit(main())
