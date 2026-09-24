"""Pin the repository's own decisions: packaging, the gate, CI, releases, and the mutation specs.

Where the thing that acts can be asked, the tests ask it: make's dry run, the environment make exports and the
makefiles it read, a fresh interpreter importing the package, tools/check_dist.py run on sdists and wheels
shaped like real ones. The real artifacts are built by the gate's dist stage, not by a test. Where only text
can be read, as for the GitHub workflows, the lines that carry a guard are compared whole rather than searched
for a fragment, and ApprovedFilesTest pins the files that define the gate and the release byte for byte,
since a guard can be switched off without changing any line another test reads.

Pinned here: one version source; the supported Pythons, the floor, and CI's matrix agreeing; a core that
imports with the standard library alone; the type marker declared as package data, and the manifest pruning
tests/; the gate's stages, the interpreters they get, the environment they run with, and the one makefile make
reads; the tool settings in pyproject.toml; the CI and release workflows' guards and refusals; the artifact
checks in tools/check_dist.py; the ruleset records; the ignored caches; the make targets AGENTS.md names; and
the mutation specs.
"""

import ast
import difflib
import io
import json
import os
import re
import shlex
import stat
import subprocess
import sys
import tarfile
import tempfile
import tomllib
import unittest
import zipfile
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from typing import Any
from unittest import mock

import onus
from tools import check_dist

ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
MAKEFILE = (ROOT / "Makefile").read_text(encoding="utf-8")
CHECK_YML = (ROOT / ".github" / "workflows" / "check.yml").read_text(encoding="utf-8")
RELEASE_YML = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
APPROVED = ROOT / "tests" / "approved"
# Each file that defines the gate or the release, and its reviewed copy under tests/approved/.
GUARDED = {
    "Makefile": "Makefile.approved",
    "pyproject.toml": "pyproject.toml.approved",
    "MANIFEST.in": "MANIFEST.in.approved",
    ".github/workflows/check.yml": "check.yml.approved",
    ".github/workflows/release.yml": "release.yml.approved",
}
# Settings a parent make or the caller's shell would otherwise leak into the make runs below: a parent
# `make check PY=...` passes its command-line variables down through MAKEFLAGS.
LEAKY = {"MAKEFLAGS", "MFLAGS", "MAKELEVEL", "MAKEOVERRIDES", "MAKEFILES", "PY", "COMPAT_PY", "PIN", "COMPAT_PIN"}
LEAKY |= {"UV_PYTHON_DOWNLOADS", "HYPOTHESIS_STORAGE_DIRECTORY", "PYTHONDONTWRITEBYTECODE"}
# Files read instead of the Makefile (by make) or of pyproject.toml's tool tables (by ruff, mypy, coverage).
SIBLINGS = ["GNUmakefile", "makefile", "ruff.toml", ".ruff.toml", "mypy.ini", ".mypy.ini", ".coveragerc"]
SIBLINGS += ["setup.cfg", "tox.ini"]


def minor(version: str) -> tuple[int, int]:
    """Return the (major, minor) pair of a version string such as ``3.13`` or ``3.13.12``."""
    major, minor_part = version.split(".")[:2]
    return int(major), int(minor_part)


def classifier_pythons() -> list[str]:
    """Return every ``Programming Language :: Python :: 3.N`` classifier's version, in order."""
    prefix = "Programming Language :: Python :: "
    return [
        c.removeprefix(prefix)
        for c in PYPROJECT["project"]["classifiers"]
        if re.fullmatch(r"3\.\d+", c.removeprefix(prefix))
    ]


def run_make(*args: str, path_prefix: Path | None = None, cwd: Path = ROOT) -> subprocess.CompletedProcess[str]:
    """Run make in the repository, or ``cwd``, with none of the caller's make variables or gate settings inherited."""
    env = {key: value for key, value in os.environ.items() if key not in LEAKY}
    if path_prefix is not None:
        env["PATH"] = f"{path_prefix}{os.pathsep}{env.get('PATH', '')}"
    return subprocess.run(["make", *args], cwd=cwd, env=env, capture_output=True, text=True)


def fake_pyenv(directory: Path, installed: dict[str, str]) -> Path:
    """Write a stand-in ``pyenv`` into ``directory`` and return ``directory``, to put first on PATH.

    It answers ``pyenv prefix <version>`` with the prefix ``installed`` gives that version, and fails with
    pyenv's "not installed" message for any other. Each call overwrites the script, so a test can call it again
    on the same directory to change what is installed.
    """
    cases = "".join(f'  "{version}") echo "{prefix}" ;;\n' for version, prefix in installed.items())
    script = directory / "pyenv"
    script.write_text(
        f'#!/bin/sh\n[ "$1" = prefix ] || exit 2\ncase "$2" in\n{cases}'
        '  *) echo "pyenv: version $2 not installed" >&2; exit 1 ;;\nesac\n',
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    return directory


BUILD_SYSTEM = '[build-system]\nrequires = ["setuptools>=77"]\nbuild-backend = "setuptools.build_meta"\n'


def fake_runner(untracked: str = "", failing: list[str] | None = None, stderr: str = "") -> check_dist.Runner:
    """Return a stand-in for ``subprocess.run`` in ``check_dist.build``.

    git lists ``onus/__init__.py``, ``README.md``, and ``pyproject.toml`` as tracked, and ``untracked``
    (NUL-separated) as neither tracked nor ignored. A command that starts with ``failing`` exits 1 with
    ``stderr``; any other succeeds.
    """

    def runner(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        if failing is not None and command[: len(failing)] == failing:
            return subprocess.CompletedProcess(command, 1, "", stderr)
        if command[:2] == ["git", "ls-files"]:
            listing = untracked if "--others" in command else "onus/__init__.py\0README.md\0pyproject.toml\0"
            return subprocess.CompletedProcess(command, 0, listing, "")
        return subprocess.CompletedProcess(command, 0, "", "")

    return runner


def job_block(workflow: str, job: str) -> str:
    """Return one top-level job of a workflow file, from its key to the next job's key; comments stay inside."""
    match = re.search(rf"(?ms)^  {re.escape(job)}:\n(.*?)(?=^  [\w-]+:\s*$|\Z)", workflow)
    assert match is not None, job
    return match.group(1)


def run_lines(block: str) -> list[str]:
    """Return the commands of every ``run:`` in a job, one-line or block, without comments or indentation."""
    lines, commands, inside = block.splitlines(), [], None
    for line in lines:
        stripped = line.strip()
        if inside is not None and (not stripped or len(line) - len(line.lstrip()) > inside):
            if stripped and not stripped.startswith("#"):
                commands.append(stripped)
            continue
        inside = None
        match = re.match(r"^(\s*)(?:- )?run: (.*)$", line)
        if match and match.group(2) == "|":
            inside = len(match.group(1))
        elif match:
            commands.append(match.group(2))
    return commands


class VersionTest(unittest.TestCase):
    def test_the_package_attribute_is_the_only_version_source(self):
        self.assertEqual(PYPROJECT["project"]["dynamic"], ["version"])
        self.assertNotIn("version", PYPROJECT["project"])
        self.assertEqual(PYPROJECT["tool"]["setuptools"]["dynamic"]["version"], {"attr": "onus.__version__"})
        self.assertRegex(onus.__version__, r"^\d+\.\d+\.\d+$")
        self.assertEqual(check_dist.source_version(), onus.__version__)


class VersionSupportTest(unittest.TestCase):
    def test_the_floor_classifiers_and_ci_matrix_agree(self):
        floor = PYPROJECT["project"]["requires-python"]
        self.assertEqual(floor, ">=3.11")
        classified = classifier_pythons()
        self.assertEqual(classified[0], floor.removeprefix(">="))
        matrix = re.findall(r"(?m)^        python: \[([^\]]*)\]$", job_block(CHECK_YML, "check"))
        self.assertEqual(len(matrix), 1)
        self.assertEqual([item.strip().strip('"') for item in matrix[0].split(",")], classified)

    def test_the_interpreter_pins_are_exact_patches_inside_the_supported_range(self):
        pin = (ROOT / ".python-version").read_text(encoding="utf-8").strip()
        floor_pin = re.search(r"(?m)^COMPAT_PIN := (\S+)$", MAKEFILE)
        assert floor_pin is not None
        for version in (pin, floor_pin.group(1)):
            with self.subTest(version=version):
                self.assertRegex(version, r"^\d+\.\d+\.\d+$", "a bare minor lets pyenv and uv disagree")
                self.assertIn(minor(version), [minor(v) for v in classifier_pythons()])
        self.assertEqual(minor(floor_pin.group(1)), minor(classifier_pythons()[0]))

    def test_the_tool_targets_match_the_floor(self):
        tools = PYPROJECT["tool"]
        self.assertEqual(tools["ruff"]["target-version"], "py311")
        self.assertEqual(tools["black"]["target-version"], ["py311"])
        self.assertEqual(tools["mypy"]["python_version"], "3.11")


class StdlibOnlyTest(unittest.TestCase):
    def test_nothing_is_required_at_runtime(self):
        self.assertEqual(PYPROJECT["project"]["dependencies"], [])
        self.assertEqual(PYPROJECT["project"]["optional-dependencies"], {"invariants": ["hypothesis>=6.168.1,<7"]})

    def test_every_core_module_imports_with_the_standard_library_alone(self):
        # -I -S: no site-packages at all, so any third-party import in the core fails here, not after release.
        # Every module under onus/ is imported, not only what onus/__init__.py pulls in; onus.invariants is
        # the one subpackage allowed to need hypothesis.
        probe = (
            "import importlib, pathlib, sys; root = pathlib.Path(sys.argv[1]); sys.path.insert(0, str(root)); "
            "names = sorted('.'.join(p.relative_to(root).with_suffix('').parts).removesuffix('.__init__') "
            "for p in (root / 'onus').rglob('*.py')); "
            "core = [n for n in names if n != 'onus.invariants' and not n.startswith('onus.invariants.')]; "
            "[importlib.import_module(n) for n in core]; print(' '.join(core))"
        )
        result = subprocess.run(
            [sys.executable, "-I", "-S", "-B", "-c", probe, str(ROOT)], capture_output=True, text=True
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        package = ROOT / "onus"
        core = [path for path in package.rglob("*.py") if path.relative_to(package).parts[0] != "invariants"]
        core = [path for path in core if path.relative_to(package).parts[0] != "invariants.py"]
        self.assertIn("onus", result.stdout.split())
        self.assertEqual(len(result.stdout.split()), len(core), "a core module was not imported")

    def test_the_type_marker_is_declared_as_package_data(self):
        self.assertTrue((ROOT / "onus" / "py.typed").is_file())
        self.assertEqual(PYPROJECT["tool"]["setuptools"]["package-data"], {"onus": ["py.typed"]})

    def test_the_manifest_prunes_tests(self):
        # tests/ reads the Makefile, workflows, and rulesets, none of which an sdist carries. Whether the built
        # sdist leaves tests/ out is checked by the dist stage; ApprovedFilesTest pins every MANIFEST.in line.
        manifest = (ROOT / "MANIFEST.in").read_text(encoding="utf-8").splitlines()
        self.assertIn("prune tests", manifest)


class DistCheckTest(unittest.TestCase):
    """tools/check_dist.py, which the gate and the release both run on the built sdist and wheel."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dist = Path(self.tmp.name)

    def artifacts(self, wheel_files=None, sdist_files=None):
        wheel_files = {"onus/__init__.py": '__version__ = "1.2.3"\n', "onus/py.typed": ""} | (wheel_files or {})
        sdist_files = {"onus-1.2.3/onus/__init__.py": "", "onus-1.2.3/pyproject.toml": ""} | (sdist_files or {})
        with zipfile.ZipFile(self.dist / "onus-1.2.3-py3-none-any.whl", "w") as wheel:
            for name, text in wheel_files.items():
                if text is not None:
                    wheel.writestr(name, text)
        with tarfile.open(self.dist / "onus-1.2.3.tar.gz", "w:gz") as sdist:
            for name, text in sdist_files.items():
                data = text.encode()
                info = tarfile.TarInfo(name)
                info.size = len(data)
                sdist.addfile(info, io.BytesIO(data))

    def test_good_artifacts_pass(self):
        self.artifacts()
        self.assertEqual(check_dist.problems(self.dist, "1.2.3"), [])

    def test_each_defect_is_named(self):
        cases = {
            "the wheel has no onus/py.typed": ({"onus/py.typed": None}, None),
            "the sdist carries tests/": (None, {"onus-1.2.3/tests/test_repo.py": ""}),
            "does not import with the standard library alone": (
                {"onus/__init__.py": 'import hypothesis\n__version__ = "1.2.3"\n'},
                None,
            ),
            "reports version 1.2.4, not 1.2.3": ({"onus/__init__.py": '__version__ = "1.2.4"\n'}, None),
        }
        for message, (wheel_files, sdist_files) in cases.items():
            with self.subTest(message=message):
                for path in self.dist.iterdir():
                    path.unlink()
                self.artifacts(wheel_files, sdist_files)
                found = check_dist.problems(self.dist, "1.2.3")
                self.assertEqual(len(found), 1, found)
                self.assertIn(message, found[0])

    def test_the_type_marker_defect_names_every_cause_whole(self):
        self.artifacts(wheel_files={"onus/py.typed": None})
        self.assertEqual(
            check_dist.problems(self.dist, "1.2.3"),
            [
                "the wheel has no onus/py.typed: it must exist and be listed under [tool.setuptools.package-data], "
                "and neither [tool.setuptools.exclude-package-data] nor a MANIFEST.in exclude may drop it (the wheel "
                "is built from the sdist)"
            ],
        )

    def test_the_sdist_defect_names_its_remedy_whole(self):
        self.artifacts(sdist_files={"onus-1.2.3/tests/test_repo.py": ""})
        self.assertEqual(
            check_dist.problems(self.dist, "1.2.3"),
            ["the sdist carries tests/: MANIFEST.in must prune tests, and no line after it may add them back"],
        )

    def test_exactly_one_wheel_and_one_sdist(self):
        self.assertIn("found []", check_dist.problems(self.dist, "1.2.3")[0])
        self.artifacts()
        (self.dist / "onus-1.2.2-py3-none-any.whl").write_bytes(
            (self.dist / "onus-1.2.3-py3-none-any.whl").read_bytes()
        )
        self.assertIn("exactly one wheel", check_dist.problems(self.dist, "1.2.3")[0])

    def test_a_relative_dist_folder_is_checked_like_an_absolute_one(self):
        # The release passes `dist`, relative to the checkout.
        self.artifacts()
        here = Path.cwd()
        os.chdir(self.dist.parent)
        self.addCleanup(os.chdir, here)
        self.assertEqual(check_dist.problems(Path(self.dist.name), "1.2.3"), [])

    def source(self, *untracked):
        source = self.dist / "source"
        (source / "onus").mkdir(parents=True)
        for name in ("onus/__init__.py", "README.md", *untracked):
            (source / name).write_text("", encoding="utf-8")
        (source / "pyproject.toml").write_text(BUILD_SYSTEM, encoding="utf-8")
        return source

    def test_the_build_copies_only_tracked_files_and_builds_outside_the_checkout(self):
        source = self.source("untracked.txt")
        calls = []

        def runner(command, **kwargs):
            calls.append(command)
            if command[:2] == ["git", "ls-files"]:
                listing = "" if "--others" in command else "onus/__init__.py\0README.md\0pyproject.toml\0"
                return subprocess.CompletedProcess(command, 0, listing, "")
            scratch = Path(command[-1])
            copied = sorted(p.relative_to(scratch).as_posix() for p in scratch.rglob("*") if p.is_file())
            if command[:2] == ["uv", "build"]:
                self.assertEqual(copied, ["README.md", "onus/__init__.py", "pyproject.toml"])
            return subprocess.CompletedProcess(command, 0, "", "")

        check_dist.build(source, self.dist / "out", "/py/bin/python3", run=runner)
        uv = calls[4]
        self.assertEqual(uv[:2], ["uv", "build"])
        self.assertEqual(uv[uv.index("--out-dir") + 1], str((self.dist / "out").resolve()))
        self.assertNotEqual(Path(uv[-1]).resolve(), source.resolve())

    def test_the_backend_is_fetched_first_then_builds_with_no_network_of_its_own(self):
        # Fetching the backend can fail for reasons a re-run clears; the build that follows installs nothing,
        # so when it fails, the backend refused the tracked files as committed.
        self.source()
        calls = []
        runner = fake_runner()

        def recording(command, **kwargs):
            calls.append(command)
            return runner(command, **kwargs)

        check_dist.build(self.dist / "source", self.dist / "out", "/py/bin/python3", run=recording)
        venv, install, build = calls[2:]
        env = Path(venv[-1])
        self.assertEqual(venv, ["uv", "venv", "--quiet", "--python", "/py/bin/python3", str(env)])
        self.assertEqual(
            install, ["uv", "pip", "install", "--quiet", "--python", str(env / "bin" / "python"), "setuptools>=77"]
        )
        self.assertEqual(
            build[: build.index("--out-dir")],
            ["uv", "build", "--quiet", "--python", str(env / "bin" / "python"), "--no-build-isolation"],
        )

    def test_a_build_the_backend_refuses_is_a_defect_and_a_failed_fetch_is_not(self):
        self.source()
        cases = {
            ("uv", "venv"): check_dist.BuildError,
            ("uv", "pip"): check_dist.BuildError,
            ("uv", "build"): check_dist.UnbuildableError,
        }
        for failing, error in cases.items():
            with self.subTest(failing=failing):
                runner = fake_runner(failing=list(failing), stderr="refused")
                with self.assertRaisesRegex(error, f"^{' '.join(failing)} exited 1: refused"):
                    check_dist.build(self.dist / "source", self.dist / "out", "/py", run=runner)
        err = io.StringIO()
        with redirect_stderr(err), mock.patch.object(check_dist, "build", side_effect=check_dist.UnbuildableError("x")):
            self.assertEqual(check_dist.main(["--build", str(self.dist)]), check_dist.DEFECTIVE)
        self.assertIn(
            "the tracked files do not build, so this commit cannot be released as it stands: x", err.getvalue()
        )

    def test_a_pyproject_that_names_no_backend_is_a_defect(self):
        source = self.source()
        for text in ("[build-system\n", "[project]\n", '[build-system]\nrequires = "setuptools"\n'):
            with self.subTest(text=text):
                (source / "pyproject.toml").write_text(text, encoding="utf-8")
                with self.assertRaisesRegex(check_dist.UnbuildableError, "^pyproject.toml"):
                    check_dist.build(source, self.dist / "out", "/py", run=fake_runner())

    def test_a_build_that_cannot_run_says_why(self):
        self.source()
        cases = {
            "git ls-files failed in": fake_runner(failing=["git", "ls-files", "-z"], stderr="not a git repository"),
            "git ls-files --others failed in": fake_runner(failing=["git", "ls-files", "-z", "--others"]),
            "uv pip exited 1: no network": fake_runner(failing=["uv", "pip"], stderr="no network"),
        }
        for message, runner in cases.items():
            with self.subTest(message=message):
                with self.assertRaisesRegex(check_dist.BuildError, message):
                    check_dist.build(self.dist / "source", self.dist / "out", "/py", run=runner)
        with self.assertRaisesRegex(check_dist.BuildError, r"not tracked by git.*onus/stray\.py.*git add"):
            check_dist.build(self.dist / "source", self.dist / "out", "/py", run=fake_runner("onus/stray.py\0"))
        (self.dist / "source" / "README.md").unlink()
        with self.assertRaisesRegex(check_dist.BuildError, r"missing from the working tree.*README\.md.*git rm"):
            check_dist.build(self.dist / "source", self.dist / "out", "/py", run=fake_runner())

    def test_only_an_importable_module_git_neither_tracks_nor_ignores_is_stray(self):
        # A real git repository, since whether a path is ignored is git's to say.
        source = self.dist / "source"
        (source / "onus" / "not-a-package").mkdir(parents=True)
        (source / ".gitignore").write_text("onus/generated.py\n", encoding="utf-8")
        (source / "pyproject.toml").write_text(BUILD_SYSTEM, encoding="utf-8")
        for name in ("__init__.py", "new.py", "._new.py", ".#new.py", "generated.py", "not-a-package/x.py"):
            (source / "onus" / name).write_text("", encoding="utf-8")
        for command in (["git", "init", "-q"], ["git", "add", ".gitignore", "pyproject.toml", "onus/__init__.py"]):
            subprocess.run(command, cwd=source, check=True, capture_output=True)

        def runner(command, **kwargs):
            if command[0] == "git":
                return subprocess.run(command, **kwargs)
            return subprocess.CompletedProcess(command, 0, "", "")

        with self.assertRaisesRegex(check_dist.BuildError, r"^not tracked by git.*\['onus/new\.py'\]; `git add`"):
            check_dist.build(source, self.dist / "out", "/py", run=runner)
        (source / "onus" / "new.py").unlink()
        check_dist.build(source, self.dist / "out", "/py", run=runner)

    def test_the_command_line_checks_builds_and_refuses(self):
        self.artifacts()
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            self.assertEqual(check_dist.main([str(self.dist), "--version", "1.2.3"]), 0)
            self.assertEqual(check_dist.main([str(self.dist), "--version", "9.9.9"]), check_dist.DEFECTIVE)
            with mock.patch.object(check_dist, "build") as build:
                self.assertEqual(check_dist.main(["--build", str(self.dist), "--version", "1.2.3"]), 0)
                self.assertEqual(
                    check_dist.main(["--build", str(self.dist), "--version", "9.9.9"]), check_dist.DEFECTIVE
                )
            with mock.patch.object(check_dist, "build", side_effect=check_dist.BuildError("uv pip exited 2")):
                self.assertEqual(
                    check_dist.main(["--build", str(self.dist), "--version", "1.2.3"]), check_dist.NOT_BUILT
                )
            with self.assertRaises(SystemExit):
                check_dist.main([])
        build.assert_called_with(check_dist.ROOT, self.dist, sys.executable)
        self.assertIn("onus 1.2.3", out.getvalue())
        self.assertIn("not 9.9.9", err.getvalue())
        self.assertIn("nothing was checked, because the build could not run: uv pip exited 2", err.getvalue())

    def test_no_verdict_shares_an_exit_code_with_a_crash_or_a_usage_error(self):
        # Python exits 1 on an uncaught exception and argparse exits 2 on bad arguments; the release reads the
        # exit code to say whether the tag is spent, so neither may look like a verdict.
        self.assertEqual(len({0, 1, 2, check_dist.DEFECTIVE, check_dist.NOT_BUILT}), 5)

    def test_a_tool_that_cannot_be_run_means_nothing_was_built(self):
        self.source()
        for tool, failing in (("uv", ["uv"]), ("git", ["git", "ls-files", "-z", "--others"])):
            runner = fake_runner(failing=failing)

            def missing(command, _runner=runner, **kwargs):
                if _runner(command, **kwargs).returncode:
                    raise FileNotFoundError(2, "No such file or directory", command[0])
                return _runner(command, **kwargs)

            with self.subTest(tool=tool):
                with self.assertRaisesRegex(check_dist.BuildError, r"^could not run (git|uv): .*No such file"):
                    check_dist.build(self.dist / "source", self.dist / "out", "/py", run=missing)

    def test_a_copy_that_fails_means_nothing_was_built(self):
        self.source()
        with mock.patch("tools.check_dist.shutil.copy2", side_effect=PermissionError(13, "Permission denied")):
            with self.assertRaisesRegex(check_dist.BuildError, r"^could not copy the tracked files.*Permission denied"):
                check_dist.build(self.dist / "source", self.dist / "out", "/py", run=fake_runner())

    def test_the_script_run_without_git_exits_not_built(self):
        # As the release runs it, in a fresh interpreter, where an escaped OSError would exit 1.
        script = ROOT / "tools" / "check_dist.py"
        result = subprocess.run(
            [sys.executable, "-B", str(script), "--build", str(self.dist)],
            env={"PATH": str(self.dist)},
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, check_dist.NOT_BUILT, result.stderr)
        self.assertIn("nothing was checked, because the build could not run: could not run git", result.stderr)

    def test_the_source_version_needs_a_string_assignment(self):
        (self.dist / "onus").mkdir()
        (self.dist / "onus" / "__init__.py").write_text("__version__ = 3\n", encoding="utf-8")
        with self.assertRaises(ValueError):
            check_dist.source_version(self.dist)


class GateStagesTest(unittest.TestCase):
    """What `make check` runs, and with what, read from make's own dry run."""

    def setUp(self):
        result = run_make("-n", "check", "PY=/opt/pinned/bin/python3", "COMPAT_PY=/opt/floor/bin/python3")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.lines = [line for line in result.stdout.splitlines() if line.strip()]

    def test_every_stage_runs_in_order(self):
        expected = [
            "black==",
            "ruff==",
            "mypy==",
            "coverage run --rcfile=pyproject.toml -m unittest discover -s tests -t .",
            "coverage report --rcfile=pyproject.toml",
            "python -B -m unittest discover -s tests -t .",
            "compile(p.read_bytes()",
            "tools/check_dist.py --build",
            "mutt_check mutt_check.toml",
            "mutt_check mutt_check.noop.toml",
        ]
        # A stage counts only on a line that starts by running uv (`: uv ...` or `echo ... uv ...` does not); a
        # marker inside a shell comment on such a line would still count, and ApprovedFilesTest sees that edit.
        runs = [(i, line) for i, line in enumerate(self.lines) if line.startswith(("uv ", "uvx ", "out="))]
        found = [next((i for i, line in runs if marker in line), -1) for marker in expected]
        self.assertNotIn(-1, found, dict(zip(expected, found, strict=True)))
        self.assertEqual(found, sorted(found))

    def test_both_interpreters_are_resolved_before_the_first_stage(self):
        self.assertEqual(self.lines[0], ': "/opt/pinned/bin/python3" "/opt/floor/bin/python3"')

    def test_sibling_configs_are_refused_before_the_first_stage(self):
        refusal = run_make("-n", "siblings")
        self.assertEqual(refusal.returncode, 0, refusal.stderr)
        recipe = [line for line in refusal.stdout.splitlines() if line.strip()]
        self.assertTrue(recipe)
        self.assertEqual(self.lines[1 : 1 + len(recipe)], recipe)

    def test_each_tool_is_handed_pyproject_toml_rather_than_finding_a_config(self):
        # ruff also reads a ruff.toml in any folder below the root for the files in it, so a refusal by name at
        # the root alone would not close that; an explicit config does.
        flags = {
            "black==": "--config pyproject.toml",
            "ruff==": "--config pyproject.toml",
            "mypy==": "--config-file pyproject.toml",
            "coverage run": "--rcfile=pyproject.toml",
            "coverage report": "--rcfile=pyproject.toml",
        }
        for marker, flag in flags.items():
            with self.subTest(tool=marker):
                line = next(line for line in self.lines if marker in line and line.startswith(("uv ", "uvx ")))
                self.assertEqual(line.count(flag), 1, line)

    def test_each_stage_is_handed_its_interpreter_by_path(self):
        for line in self.lines:
            if not line.startswith(("uv ", "uvx ", "out=")):
                continue
            with self.subTest(line=line[:60]):
                wanted = "/opt/floor/bin/python3" if "compile(p.read_bytes()" in line else "/opt/pinned/bin/python3"
                self.assertIn(f'--python "{wanted}"', line)
                self.assertEqual(line.count("--python"), 1)

    def test_the_floor_check_writes_no_bytecode(self):
        compat = next(line for line in self.lines if "compile(p.read_bytes()" in line)
        self.assertNotIn("compileall", compat)
        self.assertIn("python -B -c", compat)

    def test_the_noop_spec_must_survive_exactly_once(self):
        noop = " ".join(self.lines[next(i for i, line in enumerate(self.lines) if "mutt_check.noop.toml" in line) :])
        self.assertIn("test $rc -eq 1", noop)
        self.assertIn('grep -q "1 survived"', noop)

    def test_the_mutation_harness_is_pinned_by_commit(self):
        harness = [line for line in self.lines if "mutt_check mutt_check" in line]
        self.assertEqual(len(harness), 2)
        for line in harness:
            with self.subTest(line=line[:60]):
                self.assertRegex(line, r'--with "mutt_check @ git\+https://\S+@[0-9a-f]{40}"')


class GateSiblingsTest(unittest.TestCase):
    """The files make or a tool would read instead of the Makefile or pyproject.toml, refused by name."""

    def refuse(self, *names: str) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory() as tmp:
            # The Makefile under another name, so that planting `makefile` cannot overwrite it on a
            # case-insensitive disk.
            (Path(tmp) / "gate.mk").write_text(MAKEFILE, encoding="utf-8")
            for name in names:
                (Path(tmp) / name).write_text("", encoding="utf-8")
            return run_make("-s", "-f", "gate.mk", "siblings", cwd=Path(tmp))

    def test_each_is_refused_by_name(self):
        for name in SIBLINGS:
            with self.subTest(name=name):
                result = self.refuse(name)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(f"the gate refuses {name} beside the Makefile", result.stderr)

    def test_a_name_that_only_resembles_one_is_not_refused(self):
        result = self.refuse("pyproject.toml", "ruff.toml.orig", "old-setup.cfg", "GNUmakefile.bak")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_the_checkout_has_none(self):
        result = run_make("-s", "siblings")
        self.assertEqual(result.returncode, 0, result.stderr)


class ToolConfigTest(unittest.TestCase):
    """The settings coverage and mypy read from pyproject.toml; ApprovedFilesTest pins the rest of the file."""

    def test_coverage_floor_branch_coverage_and_strict_types_are_on(self):
        tools = PYPROJECT["tool"]
        self.assertEqual(tools["coverage"]["report"]["fail_under"], 95)
        self.assertIs(tools["coverage"]["run"]["branch"], True)
        self.assertEqual(tools["coverage"]["run"]["source"], ["onus", "tools"])
        self.assertIs(tools["mypy"]["strict"], True)
        self.assertEqual(tools["mypy"]["files"], ["onus", "tests", "tools"])


class GateInterpreterTest(unittest.TestCase):
    """How the gate finds its interpreters when no path is passed, with a stand-in pyenv on PATH."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.pin = (ROOT / ".python-version").read_text(encoding="utf-8").strip()
        floor = re.search(r"(?m)^COMPAT_PIN := (\S+)$", MAKEFILE)
        assert floor is not None
        self.floor = floor.group(1)

    def test_pyenvs_exact_patches_are_used_when_installed(self):
        bin_dir = fake_pyenv(Path(self.tmp.name), {self.pin: "/pyenv/pinned", self.floor: "/pyenv/floor"})
        result = run_make("-n", "test", "compat", path_prefix=bin_dir)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('--python "/pyenv/pinned/bin/python3"', result.stdout)
        self.assertIn('--python "/pyenv/floor/bin/python3"', result.stdout)

    def test_a_missing_patch_stops_the_gate_and_names_the_install(self):
        bin_dir = fake_pyenv(Path(self.tmp.name), {self.pin: "/pyenv/pinned"})
        result = run_make("-n", "compat", path_prefix=bin_dir)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(f"pyenv install {self.floor}", result.stderr)
        self.assertNotIn("/bin/python3", result.stdout)
        bin_dir = fake_pyenv(Path(self.tmp.name), {self.floor: "/pyenv/floor"})
        result = run_make("-n", "test", path_prefix=bin_dir)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(f"pyenv install {self.pin}", result.stderr)

    def test_one_stop_names_every_missing_patch_and_none_an_override_replaces(self):
        bin_dir = fake_pyenv(Path(self.tmp.name), {})
        result = run_make("-n", "check", path_prefix=bin_dir)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(f"`pyenv install {self.pin}` and `pyenv install {self.floor}`", result.stderr)
        result = run_make("-n", "check", "PY=/given/bin/python3", path_prefix=bin_dir)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(f"pyenv install {self.floor}", result.stderr)
        self.assertNotIn(f"pyenv install {self.pin}", result.stderr)
        result = run_make("-n", "check", "COMPAT_PY=/given/bin/python3", path_prefix=bin_dir)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(f"pyenv install {self.pin}", result.stderr)
        self.assertNotIn(f"pyenv install {self.floor}", result.stderr)

    def test_a_missing_floor_patch_stops_the_gate_before_its_first_stage(self):
        bin_dir = fake_pyenv(Path(self.tmp.name), {self.pin: "/pyenv/pinned"})
        result = run_make("-n", "check", path_prefix=bin_dir)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(f"pyenv install {self.floor}", result.stderr)
        self.assertEqual(result.stdout, "")

    def test_help_needs_no_interpreter(self):
        result = run_make("-s", "help", path_prefix=fake_pyenv(Path(self.tmp.name), {}))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("make check", result.stdout)


class GateEnvironmentTest(unittest.TestCase):
    """The settings make exports to every recipe, as the gate-env recipe's shell sees them, and the files make read.

    A target-specific override in the Makefile would not show here; ApprovedFilesTest catches one. One in a
    GNUmakefile or makefile, which make reads instead of the Makefile, shows up as the file make read, beside the
    Makefile when it includes it.
    """

    def setUp(self):
        result = run_make("-s", "gate-env")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.env = dict(line.split("=", 1) for line in result.stdout.splitlines())

    def test_uv_never_downloads_its_own_python(self):
        self.assertEqual(self.env["UV_PYTHON_DOWNLOADS"], "never")

    def test_hypothesis_caches_outside_the_checkout(self):
        storage = Path(self.env["HYPOTHESIS_STORAGE_DIRECTORY"])
        self.assertTrue(storage.is_absolute())
        self.assertFalse(storage.resolve().is_relative_to(ROOT.resolve()))

    def test_no_bytecode_is_written(self):
        self.assertEqual(self.env["PYTHONDONTWRITEBYTECODE"], "1")

    def test_make_reads_the_makefile_alone(self):
        self.assertEqual(self.env["MAKEFILE_LIST"].split(), ["Makefile"])

    def test_a_makefile_read_before_it_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "Makefile").write_text(MAKEFILE, encoding="utf-8")
            (Path(tmp) / "GNUmakefile").write_text("include Makefile\n.IGNORE:\n", encoding="utf-8")
            result = run_make("-s", "gate-env", cwd=Path(tmp))
        self.assertEqual(result.returncode, 0, result.stderr)
        read = dict(line.split("=", 1) for line in result.stdout.splitlines())["MAKEFILE_LIST"]
        self.assertEqual(read.split(), ["GNUmakefile", "Makefile"])


class CheckWorkflowTest(unittest.TestCase):
    """The CI guards that make the one required check mean something."""

    def test_each_matrix_job_runs_the_whole_gate_on_its_own_python(self):
        check = job_block(CHECK_YML, "check")
        self.assertIn("          python-version: ${{ matrix.python }}\n", check)
        self.assertEqual(
            run_lines(check), ['make -f Makefile check PY="$(command -v python)" COMPAT_PY="$(command -v python)"']
        )
        for escape in ("exclude:", "include:", "continue-on-error", "if:"):
            with self.subTest(escape=escape):
                self.assertNotIn(escape, check)
        self.assertNotIn("UV_PYTHON_DOWNLOADS", CHECK_YML)

    def test_ci_reads_the_makefile_whatever_sits_beside_it(self):
        # make reads a GNUmakefile instead of the Makefile, and one holding `include Makefile` and `.IGNORE:`
        # would turn CI green; the tests that forbid it run inside that same make. CI's own make options, taken
        # from the workflow, must make it read the Makefile alone.
        command = shlex.split(run_lines(job_block(CHECK_YML, "check"))[0])
        self.assertEqual(command[0], "make")
        options = command[1 : command.index("check")]
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "Makefile").write_text(MAKEFILE, encoding="utf-8")
            (Path(tmp) / "GNUmakefile").write_text("include Makefile\n.IGNORE:\n", encoding="utf-8")
            result = run_make(*options, "-s", "gate-env", cwd=Path(tmp))
        self.assertEqual(result.returncode, 0, result.stderr)
        read = dict(line.split("=", 1) for line in result.stdout.splitlines())["MAKEFILE_LIST"]
        self.assertEqual(read.split(), ["Makefile"])

    def test_the_required_check_fails_whenever_any_matrix_job_did_not_succeed(self):
        gate = job_block(CHECK_YML, "all-checks")
        for line in ("    name: all checks passed\n", "    if: always()\n", "    needs: [check]\n"):
            with self.subTest(line=line.strip()):
                self.assertIn(line, gate)
        self.assertEqual(run_lines(gate), ['test "${{ needs.check.result }}" = "success"'])

    def test_job_block_keeps_a_comment_inside_its_job(self):
        workflow = "jobs:\n  first:\n    steps: []\n  # a comment at the job's indent\n    x: 1\n  second:\n    y: 2\n"
        self.assertEqual(job_block(workflow, "first"), "    steps: []\n  # a comment at the job's indent\n    x: 1\n")


class ReleaseWorkflowTest(unittest.TestCase):
    """Nothing is released that did not pass the gate, is not on main, does not match its version, or fails checks.

    Every refusal the release job makes says whether the tag is spent, and what releases the next version or
    clears it; a failed gate skips the release job, and AGENTS.md says when that spends the tag.
    """

    def test_every_permanent_tag_triggers_it_and_the_gate_runs_first(self):
        trigger = re.findall(r"(?m)^    tags: \[\"([^\"]+)\"\]$", RELEASE_YML)
        ruleset = json.loads((ROOT / ".github" / "rulesets" / "release-tags.json").read_text(encoding="utf-8"))
        self.assertEqual(["refs/tags/" + pattern for pattern in trigger], ruleset["conditions"]["ref_name"]["include"])
        self.assertEqual(job_block(RELEASE_YML, "checks"), "    uses: ./.github/workflows/check.yml\n\n")
        release = job_block(RELEASE_YML, "release")
        self.assertTrue(release.startswith("    needs: checks\n    runs-on: ubuntu-latest\n"))
        self.assertNotIn("if:", release)
        self.assertNotIn("continue-on-error", release)

    def test_each_refusal_runs_and_names_the_remedy(self):
        commands = run_lines(job_block(RELEASE_YML, "release"))
        self.assertIn('git merge-base --is-ancestor "$GITHUB_SHA" FETCH_HEAD \\', commands)
        self.assertIn('test "v$version" = "$GITHUB_REF_NAME" \\', commands)
        self.assertIn('if [ "$on_main$matches" != 11 ]; then', commands)
        spent = [command for command in commands if "is spent" in command and "not spent" not in command]
        self.assertEqual(len(spent), 3)
        for remedy in spent:
            with self.subTest(remedy=remedy[:50]):
                self.assertIn("set onus.__version__ to the next unused version", remedy)
                self.assertIn("tag that merge commit", remedy)
        self.assertEqual(sum("is not spent" in command and "re-run this job" in command for command in commands), 2)
        self.assertTrue(any("tag this same commit v$version" in command for command in commands))

    def test_the_artifacts_are_checked_by_the_gates_own_script_before_publishing(self):
        commands = run_lines(job_block(RELEASE_YML, "release"))
        check = commands.index('python tools/check_dist.py --build --version "${GITHUB_REF_NAME#v}" dist || status=$?')
        # The release reads check_dist's own exit codes: a defect spends the tag, a build that could not run
        # does not, and any other exit (a crash) is re-run once before it is called either.
        branches = [command for command in commands[check + 1 :] if command.startswith(("if [", "elif [", "fi"))]
        self.assertEqual(
            branches[:4],
            [
                f'if [ "$status" -eq {check_dist.DEFECTIVE} ]; then',
                f'elif [ "$status" -eq {check_dist.NOT_BUILT} ]; then',
                'elif [ "$status" -ne 0 ]; then',
                "fi",
            ],
        )
        publish = next(i for i, command in enumerate(commands) if command.startswith("gh release create"))
        self.assertLess(check, publish)
        for upload in ("twine", "pypi-publish", "pypi.org"):
            self.assertNotIn(upload, RELEASE_YML)


class ApprovedFilesTest(unittest.TestCase):
    """The files that define the gate and the release, byte for byte against reviewed copies in tests/approved/.

    The tests above say why each guard exists. A guard can still be switched off without changing what they
    read: a `-` recipe prefix (make's dry run prints recipes without it), `|| true` or `exit 0` in a recipe or a
    step, a target-specific override, an emptied rule list in pyproject.toml's tool tables. Listing every such
    escape would be a catch-all negative, so these files are pinned whole, and every workflow must be one of
    them. Changing one means copying it over its approved copy in the same commit, where the diff puts the
    change in front of the reviewer.
    """

    def test_each_guarded_file_matches_its_approved_copy(self):
        for name, approved in GUARDED.items():
            with self.subTest(file=name):
                current = (ROOT / name).read_bytes()
                expected = (APPROVED / approved).read_bytes()
                if current != expected:
                    diff = "".join(
                        difflib.unified_diff(
                            expected.decode("utf-8", "replace").splitlines(keepends=True),
                            current.decode("utf-8", "replace").splitlines(keepends=True),
                            f"tests/approved/{approved}",
                            name,
                        )
                    )
                    self.fail(
                        f"{name} differs from tests/approved/{approved}. If the change is intended, copy {name} "
                        f"over tests/approved/{approved} in the same commit.\n{diff}"
                    )

    def test_every_approved_copy_guards_a_file(self):
        self.assertEqual(sorted(path.name for path in APPROVED.iterdir()), sorted(GUARDED.values()))

    def test_every_workflow_is_guarded(self):
        workflows = {path.relative_to(ROOT).as_posix() for path in (ROOT / ".github" / "workflows").iterdir()}
        self.assertLessEqual(workflows, set(GUARDED))

    def test_no_other_makefile_sits_beside_the_makefile(self):
        # make reads a GNUmakefile or makefile instead of the Makefile, and either could override a pinned recipe.
        # On a case-insensitive disk `makefile` is the Makefile itself, so the names are listed, not probed.
        names = {path.name for path in ROOT.iterdir()}
        self.assertEqual(names & {"GNUmakefile", "makefile"}, set())


class RulesetRecordTest(unittest.TestCase):
    """The committed JSON records of the live rulesets; AGENTS.md says how to apply and compare them."""

    def load(self, name: str) -> dict[str, Any]:
        record: dict[str, Any] = json.loads((ROOT / ".github" / "rulesets" / name).read_text(encoding="utf-8"))
        return record

    def test_the_main_record_protects_the_default_branch_and_requires_the_ci_check(self):
        main = self.load("main.json")
        self.assertEqual((main["target"], main["enforcement"], main["bypass_actors"]), ("branch", "active", []))
        self.assertEqual(main["conditions"], {"ref_name": {"include": ["~DEFAULT_BRANCH"], "exclude": []}})
        rules = {rule["type"]: rule.get("parameters", {}) for rule in main["rules"]}
        self.assertEqual(
            set(rules),
            {"deletion", "non_fast_forward", "required_linear_history", "pull_request", "required_status_checks"},
        )
        contexts = [check["context"] for check in rules["required_status_checks"]["required_status_checks"]]
        self.assertEqual(contexts, ["all checks passed"])
        self.assertIn("    name: all checks passed\n", job_block(CHECK_YML, "all-checks"))

    def test_the_release_tag_record_makes_version_tags_permanent(self):
        tags = self.load("release-tags.json")
        self.assertEqual((tags["target"], tags["enforcement"], tags["bypass_actors"]), ("tag", "active", []))
        self.assertEqual(tags["conditions"], {"ref_name": {"include": ["refs/tags/v*"], "exclude": []}})
        self.assertEqual(tags["rules"], [{"type": "deletion"}, {"type": "non_fast_forward"}, {"type": "update"}])


class GitignoreTest(unittest.TestCase):
    def test_caches_the_gate_can_create_are_ignored(self):
        ignored = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
        for entry in (".coverage", ".mypy_cache/", ".ruff_cache/", "__pycache__/", ".hypothesis/"):
            with self.subTest(entry=entry):
                self.assertIn(entry, ignored)


class AgentsFileTest(unittest.TestCase):
    def test_every_make_target_it_names_exists(self):
        agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
        named = set(re.findall(r"`make ([\w-]+)`", agents))
        self.assertIn("gate-env", named)
        phony = re.search(r"^\.PHONY: (.*)$", MAKEFILE, re.MULTILINE)
        assert phony is not None
        self.assertLessEqual(named, set(phony.group(1).split()))


def prose(name: str) -> str:
    """Return a file's words with comment markers and line wrapping removed, so a claim reads as one sentence."""
    text = (ROOT / name).read_text(encoding="utf-8")
    return " ".join(re.sub(r"(?m)^\s*# ?", "", text).split())


class DocumentedClaimsTest(unittest.TestCase):
    """Claims the docs make about how make, the gate, and the release behave, each pinned as a whole sentence.

    Each once said something false or left out a case. Where the behaviour can be asked, the test asks it too.
    """

    def test_make_reads_the_first_makefile_it_finds_and_no_other(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "Makefile").write_text(MAKEFILE, encoding="utf-8")
            (Path(tmp) / "GNUmakefile").write_text(
                "gate-env:\n\t@echo MAKEFILE_LIST=$(MAKEFILE_LIST)\n", encoding="utf-8"
            )
            result = run_make("-s", "gate-env", cwd=Path(tmp))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.split(), ["MAKEFILE_LIST=GNUmakefile"])
        claims = {
            "Makefile": (
                "make reads only the first of GNUmakefile, makefile, and Makefile that it finds, so a GNUmakefile or "
                "makefile beside this file would be read instead of it, and could include it with its failures "
                "switched off: `make siblings` refuses both, CI runs `make -f Makefile`, and `make gate-env` shows "
                "which files make read."
            ),
            "AGENTS.md": (
                "make reads only the first of `GNUmakefile`, `makefile`, and `Makefile` that it finds, so either "
                "of the others beside it would be read instead, and could `include` it with its failures switched "
                "off. `make siblings` refuses both, and CI runs `make -f Makefile check`, which reads the Makefile "
                "whatever else is there."
            ),
        }
        for name, claim in claims.items():
            with self.subTest(file=name):
                self.assertIn(claim, prose(name))

    def test_a_failed_gate_spends_the_tag_only_when_the_failure_is_the_commits_own(self):
        # A gate run fails for the network or a lost runner as well as for the commit; re-running the failed
        # jobs of the same run tests the same commit again, so only a failure that repeats spends the tag.
        claim = (
            "A tag whose gate fails skips the release job. When the failure is the commit's own (a test, lint, "
            "types, or the dist check failing on its files), the tag is spent the same way; when it is not (the "
            "network, a lost runner, a tool that could not be fetched), re-running the failed jobs clears it, so "
            "re-run them once before calling the tag spent."
        )
        self.assertIn(claim, prose("AGENTS.md"))
        self.assertNotIn("a tag whose gate fails skips the release job and is spent the same way", prose("AGENTS.md"))


class MutationSpecTest(unittest.TestCase):
    def test_every_mutant_names_real_suites_and_an_anchor_found_exactly_once(self):
        for spec_name in ("mutt_check.toml", "mutt_check.noop.toml"):
            spec = tomllib.loads((ROOT / spec_name).read_text(encoding="utf-8"))
            self.assertTrue(spec["mutant"], spec_name)
            for mutant in spec["mutant"]:
                with self.subTest(spec=spec_name, mutant=mutant["name"]):
                    text = (ROOT / mutant["file"]).read_text(encoding="utf-8")
                    self.assertEqual(text.count(mutant["find"]), 1)
                    for suite in mutant.get("suites", spec["run"]["suites"]):
                        module, _, cls = suite.rpartition(".") if suite.count(".") > 1 else (suite, "", "")
                        path = ROOT / (module.replace(".", "/") + ".py")
                        self.assertTrue(path.is_file(), suite)
                        if cls:
                            self.assertIn(f"class {cls}(", path.read_text(encoding="utf-8"), suite)

    def test_the_noop_rewrite_changes_nothing_it_could_be_asked(self):
        noop = tomllib.loads((ROOT / "mutt_check.noop.toml").read_text(encoding="utf-8"))
        self.assertEqual(len(noop["mutant"]), 1)
        mutant = noop["mutant"][0]
        before, after = (ast.parse(mutant[key].strip()) for key in ("find", "replace"))
        self.assertNotEqual(ast.dump(before), ast.dump(after))
        for version in ("3.11", "3.13.12", "10.0.1", "3", "", "a.b.c.d"):
            with self.subTest(version=version):
                ours: dict[str, object] = {"version": version}
                theirs: dict[str, object] = {"version": version}
                for statement, namespace in ((mutant["find"], ours), (mutant["replace"], theirs)):
                    try:
                        exec(statement.strip(), {}, namespace)
                    except ValueError as error:
                        namespace["raised"] = type(error)
                self.assertEqual(ours, theirs)


if __name__ == "__main__":
    unittest.main()
