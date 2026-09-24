"""Pin the repository's own decisions by what they do, not by how their lines read.

One version source; the supported Pythons, the floor, and CI's matrix agreeing; a core that imports with only
the standard library; the gate's stages, the interpreters they get, and the environment they run with, read
from make itself; the CI and release workflows' guards; the ruleset records; the ignored caches; the make
targets AGENTS.md names; and the mutation specs.
"""

import ast
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path

import onus

ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
MAKEFILE = (ROOT / "Makefile").read_text(encoding="utf-8")
CHECK_YML = (ROOT / ".github" / "workflows" / "check.yml").read_text(encoding="utf-8")
RELEASE_YML = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
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
    """Write a ``pyenv`` that answers ``prefix <version>`` from ``installed`` and fails for anything else."""
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
    """Return the text of one top-level job in a workflow file, from its key to the next job's key."""
    match = re.search(rf"(?ms)^  {re.escape(job)}:\n(.*?)(?=^  \S|\Z)", workflow)
    assert match is not None, job
    return match.group(1)


class VersionTest(unittest.TestCase):
    def test_the_package_attribute_is_the_only_version_source(self):
        self.assertEqual(PYPROJECT["project"]["dynamic"], ["version"])
        self.assertNotIn("version", PYPROJECT["project"])
        self.assertEqual(PYPROJECT["tool"]["setuptools"]["dynamic"]["version"], {"attr": "onus.__version__"})
        self.assertRegex(onus.__version__, r"^\d+\.\d+\.\d+$")


class VersionSupportTest(unittest.TestCase):
    def test_the_floor_classifiers_and_ci_matrix_agree(self):
        floor = PYPROJECT["project"]["requires-python"]
        self.assertEqual(floor, ">=3.11")
        classified = classifier_pythons()
        self.assertEqual(classified[0], floor.removeprefix(">="))
        matrix = re.search(r"python: \[([^\]]*)\]", CHECK_YML)
        assert matrix is not None
        self.assertEqual([item.strip().strip('"') for item in matrix.group(1).split(",")], classified)

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

    def test_the_package_imports_with_the_standard_library_alone(self):
        # -I -S: no site-packages at all, so any third-party import in the core fails here, not after release.
        probe = f"import sys; sys.path.insert(0, {str(ROOT)!r}); import onus; print(onus.__version__)"
        result = subprocess.run([sys.executable, "-I", "-S", "-B", "-c", probe], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), onus.__version__)

    def test_the_type_marker_is_declared_as_package_data(self):
        self.assertTrue((ROOT / "onus" / "py.typed").is_file())
        self.assertEqual(PYPROJECT["tool"]["setuptools"]["package-data"], {"onus": ["py.typed"]})

    def test_the_sdist_leaves_out_the_repository_tests(self):
        # tests/ reads the Makefile, workflows, and rulesets, none of which an sdist carries.
        manifest = (ROOT / "MANIFEST.in").read_text(encoding="utf-8").splitlines()
        self.assertIn("prune tests", manifest)


class GateStagesTest(unittest.TestCase):
    """What `make check` runs, read from make's own dry run rather than from the recipe text."""

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
            "mutt_check mutt_check.toml",
            "mutt_check mutt_check.noop.toml",
        ]
        # A stage counts only on a line that runs it: `: uv ...` or `echo ... uv ...` does not.
        runs = [(i, line) for i, line in enumerate(self.lines) if line.startswith(("uv ", "uvx ", "out="))]
        found = [next((i for i, line in runs if marker in line), -1) for marker in expected]
        self.assertNotIn(-1, found, dict(zip(expected, found, strict=True)))
        self.assertEqual(found, sorted(found))

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
        self.assertRegex(MAKEFILE, r"(?m)^MUTT_CHECK := mutt_check @ git\+https://\S+@[0-9a-f]{40}$")

    def test_coverage_floor_branch_coverage_and_strict_types_are_on(self):
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

    def test_help_needs_no_interpreter(self):
        result = run_make("-s", "help", path_prefix=fake_pyenv(Path(self.tmp.name), {}))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("make check", result.stdout)


class GateEnvironmentTest(unittest.TestCase):
    """The settings every stage actually runs with, as a recipe's shell sees them."""

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
        self.assertIn("python-version: ${{ matrix.python }}", check)
        self.assertIn('make check PY="$(command -v python)" COMPAT_PY="$(command -v python)"', check)
        for escape in ("exclude:", "include:", "continue-on-error", "if:", "UV_PYTHON_DOWNLOADS"):
            with self.subTest(escape=escape):
                self.assertNotIn(escape, check)

    def test_the_required_check_fails_whenever_any_matrix_job_did_not_succeed(self):
        gate = job_block(CHECK_YML, "all-checks")
        self.assertIn("name: all checks passed", gate)
        self.assertIn("if: always()", gate)
        self.assertIn("needs: [check]", gate)
        self.assertIn('test "${{ needs.check.result }}" = "success"', gate)


class ReleaseWorkflowTest(unittest.TestCase):
    """Nothing is released that did not pass the gate, is not on main, or does not match its version."""

    def test_only_version_tags_trigger_it_and_the_gate_runs_first(self):
        self.assertIn('tags: ["v[0-9]+.[0-9]+.[0-9]+"]', RELEASE_YML)
        self.assertIn("uses: ./.github/workflows/check.yml", job_block(RELEASE_YML, "checks"))
        self.assertIn("needs: checks", job_block(RELEASE_YML, "release"))

    def test_each_refusal_is_there_and_names_what_to_do(self):
        release = job_block(RELEASE_YML, "release")
        self.assertIn('git merge-base --is-ancestor "$GITHUB_SHA" FETCH_HEAD', release)
        self.assertIn('test "v$version" = "$GITHUB_REF_NAME"', release)
        self.assertEqual(release.count("tag the next version"), 2)

    def test_the_built_artifacts_are_checked_before_publishing(self):
        release = job_block(RELEASE_YML, "release")
        publish = release.index("gh release create")
        for guard in ("onus/py.typed", "/tests/", "import onus"):
            with self.subTest(guard=guard):
                self.assertLess(release.index(guard), publish)
        for upload in ("twine", "pypi-publish", "pypi.org"):
            self.assertNotIn(upload, RELEASE_YML)


class RulesetRecordTest(unittest.TestCase):
    """The committed JSON records of the live rulesets; AGENTS.md says how to apply and compare them."""

    def load(self, name):
        return json.loads((ROOT / ".github" / "rulesets" / name).read_text(encoding="utf-8"))

    def test_the_main_record_protects_the_default_branch_and_requires_the_ci_check(self):
        main = self.load("main.json")
        self.assertEqual((main["target"], main["enforcement"], main["bypass_actors"]), ("branch", "active", []))
        self.assertEqual(main["conditions"]["ref_name"], {"include": ["~DEFAULT_BRANCH"], "exclude": []})
        rules = {rule["type"]: rule.get("parameters", {}) for rule in main["rules"]}
        self.assertEqual(
            set(rules),
            {"deletion", "non_fast_forward", "required_linear_history", "pull_request", "required_status_checks"},
        )
        contexts = [check["context"] for check in rules["required_status_checks"]["required_status_checks"]]
        self.assertEqual(contexts, ["all checks passed"])
        self.assertIn("name: all checks passed", job_block(CHECK_YML, "all-checks"))

    def test_the_release_tag_record_makes_version_tags_permanent(self):
        tags = self.load("release-tags.json")
        self.assertEqual((tags["target"], tags["enforcement"], tags["bypass_actors"]), ("tag", "active", []))
        self.assertEqual(tags["conditions"]["ref_name"], {"include": ["refs/tags/v*"], "exclude": []})
        self.assertEqual({rule["type"] for rule in tags["rules"]}, {"deletion", "non_fast_forward", "update"})


class GitignoreTest(unittest.TestCase):
    def test_caches_the_gate_can_create_are_ignored(self):
        ignored = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
        for entry in (".coverage", ".mypy_cache/", ".ruff_cache/", "__pycache__/", ".hypothesis/"):
            with self.subTest(entry=entry):
                self.assertIn(entry, ignored)


class AgentsFileTest(unittest.TestCase):
    def test_every_make_target_it_names_exists(self):
        agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
        named = set(re.findall(r"`make (\w+)`", agents))
        self.assertTrue(named)
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
