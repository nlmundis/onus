#!/bin/bash
# SessionStart hook for Claude Code on the web: gives a cloud session the two interpreters the gate needs.
#
# The gate takes its interpreters from pyenv at exact patches, the one in .python-version and COMPAT_PIN in the
# Makefile, and a cloud container has neither. python.org is out of reach there, so `pyenv install` cannot
# fetch a source tarball; each missing patch is built from its tag in CPython's git repository instead. A
# local session (CLAUDE_CODE_REMOTE unset) is left alone. When both patches are present the hook only checks
# them, so a resumed or cached container starts at once.
set -euo pipefail

if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

root="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "$0")/../.." && pwd)}"
export PYENV_ROOT="$HOME/.pyenv"
export PATH="$PYENV_ROOT/bin:$PATH"

pin="$(tr -d '[:space:]' < "$root/.python-version")"
compat="$(sed -n 's/^COMPAT_PIN := *\([^ ]*\) *$/\1/p' "$root/Makefile")"
for v in "$pin" "$compat"; do
  if ! [[ "$v" =~ ^3\.[0-9]+\.[0-9]+$ ]]; then
    echo "session-start: '$v' is not an exact CPython patch (read from .python-version and COMPAT_PIN)" >&2
    exit 1
  fi
done

logs="$(mktemp -d "${TMPDIR:-/tmp}/onus-session-start.XXXXXX")"

if [ ! -x "$PYENV_ROOT/bin/pyenv" ]; then
  git clone --quiet --depth 1 https://github.com/pyenv/pyenv "$logs/pyenv"
  mkdir -p "$PYENV_ROOT"
  cp -a "$logs/pyenv/." "$PYENV_ROOT/"
  echo "session-start: installed pyenv in $PYENV_ROOT"
fi

# A patch counts as present only when its python3 runs and reports that exact version.
present() {
  [ "$("$PYENV_ROOT/versions/$1/bin/python3" -c 'import platform; print(platform.python_version())' 2>/dev/null)" = "$1" ]
}

build() {
  local v="$1" prefix="$PYENV_ROOT/versions/$1" src="$logs/cpython-$1"
  git -c advice.detachedHead=false clone --quiet --depth 1 --branch "v$v" https://github.com/python/cpython "$src"
  (
    cd "$src"
    ./configure --prefix="$prefix"
    make -j"$(nproc)"
    make install
  ) > "$logs/build-$v.log" 2>&1
}

for v in "$pin" "$compat"; do
  if present "$v"; then
    continue
  fi
  echo "session-start: building Python $v from CPython's v$v tag (log in $logs/build-$v.log)"
  # A failed or partial build leaves no prefix behind, so the next start builds it again.
  if ! build "$v" || ! present "$v"; then
    rm -rf "$PYENV_ROOT/versions/$v"
    echo "session-start: building Python $v failed; the last lines of its log:" >&2
    tail -n 40 "$logs/build-$v.log" >&2 || true
    exit 1
  fi
  rm -rf "$logs/cpython-$v"
  echo "session-start: built Python $v in $PYENV_ROOT/versions/$v"
done

if [ -n "${CLAUDE_ENV_FILE:-}" ]; then
  {
    echo "export PYENV_ROOT=\"$PYENV_ROOT\""
    echo "export PATH=\"$PYENV_ROOT/bin:\$PATH\""
  } >> "$CLAUDE_ENV_FILE"
fi

rmdir "$logs" 2>/dev/null || true
echo "session-start: pyenv has Python $pin and $compat"
