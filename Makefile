# `make check` is the whole gate: black, ruff, strict mypy, the unittest suite under branch coverage with a
# 95% floor, the suite again on the pinned interpreter, a compile check on the oldest supported Python, the
# sdist and wheel built and checked as a release would check them, then mutt_check proving the suite catches
# each curated mutant and does not count a behaviour-preserving rewrite as caught. No tool enters a project environment: each runs through uvx or `uv run --no-project`, pinned
# below. The dist stage builds with whatever setuptools>=77 uv resolves for pyproject's build-system, the same
# backend a release and any install from the sdist use. uv needs the network to resolve the pinned tools and
# that backend the first time; after that, `UV_OFFLINE=1 make check` runs offline. Inside the checkout the
# gate writes only gitignored caches (.coverage, .mypy_cache, .ruff_cache), so `git status` stays clean and a
# worktree stays cleanable. make reads only the first of GNUmakefile, makefile, and Makefile that it finds, so a
# GNUmakefile or makefile beside this file would be read instead of it, and could include it with its failures
# switched off: `make siblings` refuses both, CI runs `make -f Makefile`, and `make gate-env` shows which files
# make read.
#
# The interpreters come from pyenv at exact patches (.python-version, and COMPAT_PIN for the floor), and uv is
# always handed their paths, never left to discover one: PATH may put another python, such as Homebrew's,
# ahead of the pyenv shims. When pyenv lacks a pinned patch the gate stops before its first stage and names
# the `pyenv install` command, rather than falling back to whatever python3 the system has. CI has no pyenv and passes PY and
# COMPAT_PY as paths to its own interpreter.

PIN := $(shell cat .python-version)
COMPAT_PIN := 3.11.14
# Whether the caller passed an interpreter, so a missing pyenv patch it replaces is not asked for.
PY_GIVEN := $(filter-out undefined,$(origin PY))
COMPAT_GIVEN := $(filter-out undefined,$(origin COMPAT_PY))
PIN_HOME = $(shell pyenv prefix $(PIN) 2>/dev/null)
COMPAT_HOME = $(shell pyenv prefix $(COMPAT_PIN) 2>/dev/null)
# Every pinned patch pyenv lacks that no override replaces, so one stop names all of them.
MISSING = $(strip $(if $(PY_GIVEN)$(PIN_HOME),,$(PIN)) $(if $(COMPAT_GIVEN)$(COMPAT_HOME),,$(COMPAT_PIN)))
STOP = $(error pyenv lacks Python $(MISSING): run $(subst ` `,` and `,$(foreach v,$(MISSING),`pyenv install $(v)`)), or pass PY= and COMPAT_PY= as paths to python3)
PY ?= $(or $(PIN_HOME),$(STOP))/bin/python3
COMPAT_PY ?= $(or $(COMPAT_HOME),$(STOP))/bin/python3
# uv may not fetch its own CPython behind pyenv's back, even when an override asks for a version, not a path.
export UV_PYTHON_DOWNLOADS ?= never
# uv reads a uv.toml here, in any parent folder, or in the user's config, and one could change the index every
# --with package comes from; the gate uses none of them. (The siblings stage also refuses a uv.toml at the root.)
export UV_NO_CONFIG := 1
# Keeps Hypothesis's cache (a charmap and constants, written even with database=None on 6.168.1) out of the
# checkout, so the first Hypothesis test inherits a gate that writes nothing into the tree.
export HYPOTHESIS_STORAGE_DIRECTORY ?= $(or $(TMPDIR),/tmp)/onus-hypothesis
# No bytecode: without this, the coverage run and every tool that imports the tests write __pycache__ into the
# checkout. (The test stage passes -B as well.)
export PYTHONDONTWRITEBYTECODE := 1

BLACK := black==26.5.1
RUFF := ruff==0.16.8
MYPY := mypy==2.3.1
COVERAGE := coverage[toml]==7.16.1
HYPOTHESIS := hypothesis==6.168.1
# v0.0.2, pinned by commit: a tag can move and would change the tool that decides caught and survived.
MUTT_CHECK := mutt_check @ git+https://github.com/nlmundis/mutt_check@8a89dfc4c93357e294cbc51d1b723b27078c5481

# Recursive, so PY is resolved only by the targets that use it and `make help` works without pyenv.
RUN = uv run --no-project --python "$(PY)" --with "$(HYPOTHESIS)"

.PHONY: help check interpreters siblings format lint types coverage test compat dist mutants gate-env

help:
	@echo "make check        the whole gate, as below, in this order"
	@echo "make interpreters stop now if pyenv lacks either pinned patch"
	@echo "make siblings     refuse a file make or a tool would read instead of the Makefile or pyproject.toml"
	@echo "make format       black, check only"
	@echo "make lint         ruff"
	@echo "make types        strict mypy"
	@echo "make coverage     the suite under branch coverage, 95% floor"
	@echo "make test         the suite on the pinned interpreter"
	@echo "make compat       compile every module on the oldest supported Python, writing no bytecode"
	@echo "make dist         build the sdist and wheel from the tracked files and check them as a release would"
	@echo "make mutants      mutt_check: every curated mutant caught, the no-op rewrite not"
	@echo "make gate-env     print the settings make exports to every stage, and the makefiles it read"

check: interpreters siblings format lint types coverage test compat dist mutants

# Expands both interpreters before any stage runs, so a missing patch stops the gate at once.
interpreters:
	@: "$(PY)" "$(COMPAT_PY)"

# make reads a GNUmakefile or makefile instead of this file, and ruff, mypy, coverage, and uv each read their own
# file before pyproject.toml's tables; any of them could switch a stage off with this file unchanged. Each is
# refused by name, as `ls` spells it and in any case, since on a case-insensitive disk make's probe for
# GNUmakefile opens a GNUMakefile; only this Makefile itself is let through.
# Every tool is also handed pyproject.toml, since ruff reads a ruff.toml in any folder for the files below it.
SIBLINGS := GNUmakefile makefile ruff.toml .ruff.toml mypy.ini .mypy.ini .coveragerc setup.cfg tox.ini uv.toml

siblings:
	@found="$$(ls -A | grep -vx Makefile | grep -Fxi $(foreach name,$(SIBLINGS),-e $(name)))"; test -z "$$found" || { \
	  echo "the gate refuses" $$found "beside the Makefile: make or a tool would read it instead of the" \
	    "Makefile or pyproject.toml. Move its settings into those, and delete it." >&2; exit 1; }

format:
	uvx --python "$(PY)" $(BLACK) --config pyproject.toml --check --diff .

lint:
	uvx --python "$(PY)" $(RUFF) check --config pyproject.toml .

types:
	uvx --python "$(PY)" --with "$(HYPOTHESIS)" $(MYPY) --config-file pyproject.toml

coverage:
	$(RUN) --with "$(COVERAGE)" coverage run --rcfile=pyproject.toml -m unittest discover -s tests -t .
	$(RUN) --with "$(COVERAGE)" coverage report --rcfile=pyproject.toml

test:
	$(RUN) python -B -m unittest discover -s tests -t .

# compile() checks every module against the floor's grammar and writes nothing; compileall would write .pyc.
compat:
	uv run --no-project --python "$(COMPAT_PY)" python -B -c "import pathlib; [compile(p.read_bytes(), str(p), 'exec', dont_inherit=True) for p in sorted(pathlib.Path('onus').rglob('*.py'))]"

# Builds in a scratch copy of the tracked files, so that only they reach the artifacts: in the checkout,
# setuptools would read back the file list of an onus.egg-info left by an earlier build.
dist:
	uv run --no-project --python "$(PY)" python -B tools/check_dist.py --build

# The no-op spec must come back with exactly its one mutant surviving (exit 1). That catches a harness that
# counts any edit as caught, or that runs [run] suites instead of a mutant's own; it cannot catch one that
# counts a crashing suite as caught, since the no-op's suites never crash.
mutants:
	$(RUN) --with "$(MUTT_CHECK)" mutt_check mutt_check.toml
	@out="$$($(RUN) --with "$(MUTT_CHECK)" mutt_check mutt_check.noop.toml 2>&1)"; rc=$$?; echo "$$out"; \
	  test $$rc -eq 1 || { echo "no-op spec: expected exit 1 (survived), got $$rc"; exit 1; }; \
	  echo "$$out" | grep -q "1 survived" || { echo "no-op spec: expected exactly 1 survived"; exit 1; }

gate-env:
	@echo "MAKEFILE_LIST=$(strip $(MAKEFILE_LIST))"
	@echo "UV_PYTHON_DOWNLOADS=$$UV_PYTHON_DOWNLOADS"
	@echo "UV_NO_CONFIG=$$UV_NO_CONFIG"
	@echo "HYPOTHESIS_STORAGE_DIRECTORY=$$HYPOTHESIS_STORAGE_DIRECTORY"
	@echo "PYTHONDONTWRITEBYTECODE=$$PYTHONDONTWRITEBYTECODE"
