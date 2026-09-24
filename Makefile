# `make check` is the whole gate: black, ruff, strict mypy, the unittest suite under branch coverage with a
# 95% floor, the suite again on the pinned interpreter, a compile check on the oldest supported Python, then
# mutt_check proving the suite catches each curated mutant and does not count a behaviour-preserving rewrite
# as caught. No tool enters a project environment: each runs through uvx or `uv run --no-project`, pinned
# below. Offline once uv has cached the pinned tools. Inside the checkout it writes only gitignored caches
# (.coverage, .mypy_cache, .ruff_cache), so `git status` stays clean and a worktree stays cleanable.
#
# The interpreter comes from pyenv at the exact patch in .python-version, and uv is always handed its path,
# never left to discover one: PATH here puts Homebrew's python ahead of the pyenv shims. CI has no pyenv and
# overrides PY and COMPAT_PY with its own interpreter.

PIN := $(shell cat .python-version)
PY ?= $(shell pyenv prefix $(PIN) 2>/dev/null)/bin/python3
# The floor check runs on pyenv's exact 3.11 patch too, never on an interpreter uv finds for itself.
COMPAT_PIN := 3.11.14
COMPAT_PY ?= $(shell pyenv prefix $(COMPAT_PIN) 2>/dev/null)/bin/python3
# uv may not fetch its own CPython behind pyenv's back.
export UV_PYTHON_DOWNLOADS ?= never
# Hypothesis writes a charmap and constants cache into the working directory even with database=None
# (measured 2026-09-23 on 6.168.1). Kept outside the checkout, so a worktree that ran the gate stays clean.
export HYPOTHESIS_STORAGE_DIRECTORY ?= $(or $(TMPDIR),/tmp)/onus-hypothesis
# No bytecode: a stale .pyc beside a mutated source has let a mutant survive before.
export PYTHONDONTWRITEBYTECODE := 1

BLACK := black==26.5.1
RUFF := ruff==0.16.8
MYPY := mypy==2.3.1
COVERAGE := coverage[toml]==7.16.1
HYPOTHESIS := hypothesis==6.168.1
MUTT_CHECK := mutt_check @ git+https://github.com/nlmundis/mutt_check@v0.0.2

RUN := uv run --no-project --python "$(PY)" --with "$(HYPOTHESIS)"

.PHONY: help check format lint types coverage test compat mutants

help:
	@echo "make check     the whole gate, as below, in this order"
	@echo "make format    black, check only"
	@echo "make lint      ruff"
	@echo "make types     strict mypy"
	@echo "make coverage  the suite under branch coverage, 95% floor"
	@echo "make test      the suite on the pinned interpreter"
	@echo "make compat    compile the package on the oldest supported Python"
	@echo "make mutants   mutt_check: every curated mutant caught, the no-op rewrite not"

check: format lint types coverage test compat mutants

format:
	uvx --python "$(PY)" $(BLACK) --check --diff .

lint:
	uvx --python "$(PY)" $(RUFF) check .

types:
	uvx --python "$(PY)" --with "$(HYPOTHESIS)" $(MYPY)

coverage:
	$(RUN) --with "$(COVERAGE)" coverage run -m unittest discover -s tests -t .
	$(RUN) --with "$(COVERAGE)" coverage report

test:
	$(RUN) python -B -m unittest discover -s tests -t .

compat:
	uv run --no-project --python "$(COMPAT_PY)" python -m compileall -q onus

# The no-op spec must come back with exactly its one mutant surviving (exit 1): a harness that counted any
# failure as caught would report it caught.
mutants:
	$(RUN) --with "$(MUTT_CHECK)" mutt_check mutt_check.toml
	@out="$$($(RUN) --with "$(MUTT_CHECK)" mutt_check mutt_check.noop.toml 2>&1)"; rc=$$?; echo "$$out"; \
	  test $$rc -eq 1 || { echo "no-op spec: expected exit 1 (survived), got $$rc"; exit 1; }; \
	  echo "$$out" | grep -q "1 survived" || { echo "no-op spec: expected exactly 1 survived"; exit 1; }
