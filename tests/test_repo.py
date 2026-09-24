"""Pin the repository's own decisions: packaging, the gate, CI, releases, and the mutation specs.

What each test reads, it reads from the thing that acts where it can: make's dry run and exported environment,
a built sdist and wheel, a fresh interpreter importing the package. Where only the text can be read, as for the
GitHub workflows, the lines that carry a guard are compared whole rather than searched for a fragment, and
ApprovedFilesTest pins the Makefile and both workflows byte for byte, since a guard can be switched off (a `-`
recipe prefix, `|| true`, `if: always()`) without changing any line another test reads.

Pinned here: one version source; the supported Pythons, the floor, and CI's matrix agreeing; a core that
imports with the standard library alone; the type marker declared as package data and the sdist leaving out
tests/; the gate's stages, the interpreters they get, and the environment they run with; the CI and release
workflows' guards and refusals; the artifact checks in tools/check_dist.py; the ruleset records; the ignored
caches; the make targets AGENTS.md names; and the mutation specs.
"""

import ast
import difflib
import io
import json
import os
import re
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
# Each file whose lines are guards, and its reviewed copy under tests/approved/.
GUARDED = {
    "Makefile": "Makefile.approved",
    ".github/workflows/check.yml": "check.yml.approved",
    ".github/workflows/release.yml": "release.yml.approved",
}
# Settings a parent make or the caller's shell would otherwise leak into the make runs below: a parent
# `make check PY=...` passes its command-line variables down through MAKEFLAGS.
LEAKY = {"MAKEFLAGS", "MFLAGS", "MAKELEVEL", "MAKEOVERRIDES", "PY", "COMPAT_PY", "PIN", "COMPAT_PIN"}
LEAKY |= {"UV_PYTHON_DOWNLOADS", "HYPOTHESIS_STORAGE_DIRECTORY", "PYTHONDONTWRITEBYTECODE"}


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


def run_make(*args: str, path_prefix: Path | None = None) -> subprocess.CompletedProcess[str]:
    """Run make in the repository with none of the caller's make variables or gate settings inherited."""
    env = {key: value for key, value in os.environ.items() if key not in LEAKY}
    if path_prefix is not None:
        env["PATH"] = f"{path_prefix}{os.pathsep}{env.get('PATH', '')}"
    return subprocess.run(["make", *args], cwd=ROOT, env=env, capture_output=True, text=True)


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

    def test_the_sdist_leaves_out_the_repository_tests(self):
        # tests/ reads the Makefile, workflows, and rulesets, none of which an sdist carries; the dist stage
        # checks the built sdist itself.
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

    def test_exactly_one_wheel_and_one_sdist(self):
        self.assertIn("found []", check_dist.problems(self.dist, "1.2.3")[0])
        self.artifacts()
        (self.dist / "onus-1.2.2-py3-none-any.whl").write_bytes(
            (self.dist / "onus-1.2.3-py3-none-any.whl").read_bytes()
        )
        self.assertIn("exactly one wheel", check_dist.problems(self.dist, "1.2.3")[0])

    def test_the_build_copies_only_tracked_files_and_builds_outside_the_checkout(self):
        source = self.dist / "source"
        (source / "onus").mkdir(parents=True)
        (source / "onus" / "__init__.py").write_text("", encoding="utf-8")
        (source / "untracked.txt").write_text("", encoding="utf-8")
        calls = []

        def runner(command, **kwargs):
            calls.append(command)
            if command[:2] == ["git", "ls-files"]:
                return subprocess.CompletedProcess(command, 0, "onus/__init__.py\0", "")
            scratch = Path(command[-1])
            self.assertEqual(sorted(p.name for p in scratch.rglob("*") if p.is_file()), ["__init__.py"])
            return subprocess.CompletedProcess(command, 0, "", "")

        check_dist.build(source, self.dist / "out", "/py/bin/python3", run=runner)
        uv = calls[1]
        self.assertEqual(uv[:4], ["uv", "build", "--python", "/py/bin/python3"])
        self.assertEqual(uv[uv.index("--out-dir") + 1], str(self.dist / "out"))
        self.assertNotEqual(Path(uv[-1]).resolve(), source.resolve())

    def test_the_command_line_checks_builds_and_refuses(self):
        self.artifacts()
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            self.assertEqual(check_dist.main([str(self.dist), "--version", "1.2.3"]), 0)
            self.assertEqual(check_dist.main([str(self.dist), "--version", "9.9.9"]), 1)
            with mock.patch.object(check_dist, "build") as build:
                self.assertEqual(check_dist.main(["--build", str(self.dist), "--version", "1.2.3"]), 0)
            with self.assertRaises(SystemExit):
                check_dist.main([])
        build.assert_called_once_with(check_dist.ROOT, self.dist, sys.executable)
        self.assertIn("onus 1.2.3", out.getvalue())
        self.assertIn("not 9.9.9", err.getvalue())

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
            "coverage run -m unittest discover -s tests -t .",
            "coverage report",
            "python -B -m unittest discover -s tests -t .",
            "compile(p.read_bytes()",
            "tools/check_dist.py --build",
            "mutt_check mutt_check.toml",
            "mutt_check mutt_check.noop.toml",
        ]
        # A stage counts only on a line that runs it: `: uv ...` or `echo ... uv ...` does not.
        runs = [(i, line) for i, line in enumerate(self.lines) if line.startswith(("uv ", "uvx ", "out="))]
        found = [next((i for i, line in runs if marker in line), -1) for marker in expected]
        self.assertNotIn(-1, found, dict(zip(expected, found, strict=True)))
        self.assertEqual(found, sorted(found))

    def test_both_interpreters_are_resolved_before_the_first_stage(self):
        self.assertEqual(self.lines[0], ': "/opt/pinned/bin/python3" "/opt/floor/bin/python3"')

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

    def test_coverage_floor_branch_coverage_and_strict_types_are_on(self):
        # Read from pyproject.toml, where coverage and mypy read them; ApprovedFilesTest pins the recipes.
        tools = PYPROJECT["tool"]
        self.assertEqual(tools["coverage"]["report"]["fail_under"], 95)
        self.assertIs(tools["coverage"]["run"]["branch"], True)
        self.assertIs(tools["mypy"]["strict"], True)


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
    """The settings make exports to every recipe, as the gate-env recipe's shell sees them.

    A target-specific override on another target would not show here; ApprovedFilesTest catches one.
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


class CheckWorkflowTest(unittest.TestCase):
    """The CI guards that make the one required check mean something."""

    def test_each_matrix_job_runs_the_whole_gate_on_its_own_python(self):
        check = job_block(CHECK_YML, "check")
        self.assertIn("          python-version: ${{ matrix.python }}\n", check)
        self.assertEqual(run_lines(check), ['make check PY="$(command -v python)" COMPAT_PY="$(command -v python)"'])
        for escape in ("exclude:", "include:", "continue-on-error", "if:"):
            with self.subTest(escape=escape):
                self.assertNotIn(escape, check)
        self.assertNotIn("UV_PYTHON_DOWNLOADS", CHECK_YML)

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

    Every refusal says the tag is spent and how to release the next version.
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
        self.assertIn('if [ "$refused" -ne 0 ]; then', commands)
        remedies = [command for command in commands if "is spent" in command]
        self.assertEqual(len(remedies), 2)
        for remedy in remedies:
            with self.subTest(remedy=remedy[:50]):
                self.assertIn("set onus.__version__ to the next unused version", remedy)
                self.assertIn("tag that merge commit", remedy)

    def test_the_artifacts_are_checked_by_the_gates_own_script_before_publishing(self):
        commands = run_lines(job_block(RELEASE_YML, "release"))
        check = commands.index('python tools/check_dist.py --build --version "${GITHUB_REF_NAME#v}" dist \\')
        publish = next(i for i, command in enumerate(commands) if command.startswith("gh release create"))
        self.assertLess(check, publish)
        for upload in ("twine", "pypi-publish", "pypi.org"):
            self.assertNotIn(upload, RELEASE_YML)


class ApprovedFilesTest(unittest.TestCase):
    """The Makefile and both workflows, byte for byte against reviewed copies in tests/approved/.

    The tests above say why each guard exists. A guard can still be switched off without changing what they
    read: a `-` recipe prefix (make's dry run prints recipes without it), `|| true`, `exit 0`, `if: always()`, a
    target-specific override. Listing every such escape would be a catch-all negative, so these files are also
    pinned whole. Changing one means copying it over its approved copy in the same commit, where the diff puts
    the change in front of the reviewer.
    """

    def test_each_guarded_file_matches_its_approved_copy(self):
        for name, approved in GUARDED.items():
            with self.subTest(file=name):
                current = (ROOT / name).read_text(encoding="utf-8")
                expected = (APPROVED / approved).read_text(encoding="utf-8")
                if current != expected:
                    diff = "".join(
                        difflib.unified_diff(
                            expected.splitlines(keepends=True),
                            current.splitlines(keepends=True),
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
