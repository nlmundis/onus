"""Build onus's sdist and wheel from the tracked files, and check them the way a release would.

A release tag is permanent (the release-tags ruleset), so a packaging mistake that only the release workflow
finds spends a version number. ``make check`` runs this with ``--build`` on every change, before any tag
exists; the release workflow runs the same checks on the artifacts it is about to publish.

The build happens in a scratch copy of the files git tracks, because building writes ``onus.egg-info`` into
its source tree, and the gate writes nothing into the checkout.
"""

import argparse
import ast
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from collections.abc import Callable, Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
Runner = Callable[..., subprocess.CompletedProcess[str]]


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
    alone (``-I -S``, straight from the zip) and reports ``version``.
    """
    wheels, sdists = sorted(dist.glob("*.whl")), sorted(dist.glob("*.tar.gz"))
    if len(wheels) != 1 or len(sdists) != 1:
        found = [path.name for path in wheels + sdists]
        return [f"expected exactly one wheel and one sdist in {dist}, found {found}"]
    found_problems = []
    with zipfile.ZipFile(wheels[0]) as wheel:
        if "onus/py.typed" not in wheel.namelist():
            found_problems.append("the wheel has no onus/py.typed: declare it in [tool.setuptools.package-data]")
    with tarfile.open(sdists[0]) as sdist:
        if any(Path(name).parts[1:2] == ("tests",) for name in sdist.getnames()):
            found_problems.append("the sdist carries tests/: keep `prune tests` in MANIFEST.in")
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


def build(root: Path, out: Path, python: str, run: Runner | None = None) -> None:
    """Build the sdist and wheel into ``out`` with uv, from a scratch copy of the files git tracks in ``root``.

    Raises:
        subprocess.CalledProcessError: git or uv failed.
    """
    runner = subprocess.run if run is None else run
    tracked = runner(["git", "ls-files", "-z"], cwd=root, capture_output=True, text=True, check=True).stdout
    with tempfile.TemporaryDirectory(prefix="onus-dist-") as scratch:
        for name in filter(None, tracked.split("\0")):
            target = Path(scratch) / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(root / name, target)
        command = ["uv", "build", "--python", python, "--quiet", "--out-dir", str(out), scratch]
        runner(command, capture_output=True, text=True, check=True)


def main(argv: Sequence[str] | None = None) -> int:
    """Check a folder of built artifacts, building them first with ``--build``; exit 1 when anything is wrong."""
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
            build(ROOT, dist, sys.executable)
        found = problems(dist, version)
    for problem in found:
        print(problem, file=sys.stderr)
    if not found:
        print(f"one wheel and one sdist of onus {version}: type marker shipped, tests left out, imports alone")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
