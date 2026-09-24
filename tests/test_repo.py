"""Pin the repository's own decisions: one version, the supported Pythons, a stdlib-only core, and the gate."""

import json
import re
import subprocess
import sys
import tomllib
import unittest
from pathlib import Path

import onus

ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
MAKEFILE = (ROOT / "Makefile").read_text(encoding="utf-8")
CHECK_YML = (ROOT / ".github" / "workflows" / "check.yml").read_text(encoding="utf-8")


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

    def test_the_interpreter_pin_is_an_exact_patch_inside_the_supported_range(self):
        pin = (ROOT / ".python-version").read_text(encoding="utf-8").strip()
        self.assertRegex(pin, r"^\d+\.\d+\.\d+$", "a bare minor lets pyenv and uv resolve different interpreters")
        self.assertIn(minor(pin), [minor(version) for version in classifier_pythons()])

    def test_the_tool_targets_match_the_floor(self):
        tools = PYPROJECT["tool"]
        self.assertEqual(tools["ruff"]["target-version"], "py311")
        self.assertEqual(tools["black"]["target-version"], ["py311"])
        self.assertEqual(tools["mypy"]["python_version"], "3.11")


class StdlibOnlyTest(unittest.TestCase):
    def test_nothing_is_required_at_runtime(self):
        self.assertEqual(PYPROJECT["project"]["dependencies"], [])
        self.assertEqual(PYPROJECT["project"]["optional-dependencies"], {"invariants": ["hypothesis>=6.168.1,<7"]})

    def test_the_package_imports_with_hypothesis_unavailable(self):
        blocked = "import sys; sys.modules['hypothesis'] = None; import onus; print(onus.__version__)"
        result = subprocess.run([sys.executable, "-B", "-c", blocked], cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), onus.__version__)

    def test_the_type_marker_ships(self):
        self.assertTrue((ROOT / "onus" / "py.typed").is_file())
        self.assertEqual(PYPROJECT["tool"]["setuptools"]["package-data"], {"onus": ["py.typed"]})


class GateRecipeTest(unittest.TestCase):
    def test_check_runs_every_stage_in_order(self):
        recipe = re.search(r"^check: (.*)$", MAKEFILE, re.MULTILINE)
        assert recipe is not None
        self.assertEqual(recipe.group(1).split(), ["format", "lint", "types", "coverage", "test", "compat", "mutants"])

    def test_hypothesis_never_writes_into_the_checkout(self):
        # Hypothesis 6.168.1 writes .hypothesis/ into the working directory even with database=None.
        self.assertRegex(
            MAKEFILE, r"(?m)^export HYPOTHESIS_STORAGE_DIRECTORY \?= \$\(or \$\(TMPDIR\),/tmp\)/onus-hypothesis$"
        )

    def test_the_floor_check_runs_on_pyenvs_exact_floor_patch(self):
        pin = re.search(r"(?m)^COMPAT_PIN := (\S+)$", MAKEFILE)
        assert pin is not None
        self.assertRegex(pin.group(1), r"^\d+\.\d+\.\d+$")
        self.assertEqual(minor(pin.group(1)), minor(PYPROJECT["project"]["requires-python"].removeprefix(">=")))
        self.assertRegex(
            MAKEFILE, r"(?m)^COMPAT_PY \?= \$\(shell pyenv prefix \$\(COMPAT_PIN\) 2>/dev/null\)/bin/python3$"
        )

    def test_no_bytecode_is_written(self):
        self.assertRegex(MAKEFILE, r"(?m)^export PYTHONDONTWRITEBYTECODE := 1$")

    def test_uv_never_picks_its_own_python(self):
        self.assertRegex(MAKEFILE, r"(?m)^export UV_PYTHON_DOWNLOADS \?= never$")
        self.assertRegex(MAKEFILE, r"(?m)^PY \?= \$\(shell pyenv prefix \$\(PIN\) 2>/dev/null\)/bin/python3$")

    def test_every_phony_target_has_a_recipe_and_the_help_names_it(self):
        phony = re.search(r"^\.PHONY: (.*)$", MAKEFILE, re.MULTILINE)
        assert phony is not None
        for target in phony.group(1).split():
            with self.subTest(target=target):
                self.assertRegex(MAKEFILE, rf"(?m)^{target}:")
                if target != "help":
                    self.assertIn(f"make {target} ", MAKEFILE)


class GitignoreTest(unittest.TestCase):
    def test_caches_the_gate_can_create_are_ignored(self):
        ignored = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
        for entry in (".hypothesis/", ".coverage", "__pycache__/", ".mypy_cache/"):
            with self.subTest(entry=entry):
                self.assertIn(entry, ignored)


class RulesetsTest(unittest.TestCase):
    def test_main_requires_the_check_that_ci_emits(self):
        main = json.loads((ROOT / ".github" / "rulesets" / "main.json").read_text(encoding="utf-8"))
        required = [rule for rule in main["rules"] if rule["type"] == "required_status_checks"]
        self.assertEqual(len(required), 1)
        contexts = [check["context"] for check in required[0]["parameters"]["required_status_checks"]]
        self.assertEqual(contexts, ["all checks passed"])
        self.assertRegex(CHECK_YML, r"(?m)^    name: all checks passed$")

    def test_release_tags_never_move(self):
        tags = json.loads((ROOT / ".github" / "rulesets" / "release-tags.json").read_text(encoding="utf-8"))
        self.assertEqual(tags["conditions"]["ref_name"]["include"], ["refs/tags/v*"])
        self.assertEqual({rule["type"] for rule in tags["rules"]}, {"deletion", "non_fast_forward", "update"})


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

    def test_the_noop_spec_holds_exactly_one_behaviour_preserving_mutant(self):
        noop = tomllib.loads((ROOT / "mutt_check.noop.toml").read_text(encoding="utf-8"))
        self.assertEqual(len(noop["mutant"]), 1)


if __name__ == "__main__":
    unittest.main()
