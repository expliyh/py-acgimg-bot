#!/usr/bin/env bash

set -euo pipefail

if ! command -v poetry >/dev/null 2>&1; then
  echo "Poetry is not installed; skipping the update."
  exit 0
fi

poetry_command="$(command -v poetry)"
poetry_executable="$(readlink -f "$poetry_command" 2>/dev/null || printf '%s' "$poetry_command")"

# Version managers expose a shim rather than the real console script. Ask the
# manager for the selected executable before detecting the installation type.
case "$poetry_executable" in
  */.pyenv/shims/poetry)
    poetry_executable="$(pyenv which poetry)"
    ;;
  */.asdf/shims/poetry)
    poetry_executable="$(asdf which poetry)"
    ;;
  */mise/shims/poetry|*/.local/share/mise/shims/poetry)
    poetry_executable="$(mise which poetry)"
    ;;
esac
poetry_executable="$(readlink -f "$poetry_executable" 2>/dev/null || printf '%s' "$poetry_executable")"

# uv also keeps tools isolated; let it preserve the tool environment.
if command -v uv >/dev/null 2>&1 && [[ "$poetry_executable" == */uv/tools/poetry/* ]]; then
  echo "Updating Poetry with uv..."
  uv tool upgrade poetry
  poetry --version
  exit 0
fi

# pipx owns isolated environments below its venv directory. Prefer pipx itself so
# its metadata and injected packages remain intact.
if command -v pipx >/dev/null 2>&1; then
  pipx_home="$(pipx environment --value PIPX_LOCAL_VENVS 2>/dev/null || true)"
  if [[ -n "$pipx_home" && "$poetry_executable" == "$pipx_home/poetry/"* ]]; then
    echo "Updating Poetry with pipx..."
    pipx upgrade poetry
    poetry --version
    exit 0
  fi
fi

if command -v brew >/dev/null 2>&1 &&
  brew_prefix="$(brew --prefix poetry 2>/dev/null)" &&
  [[ "$poetry_executable" == "$brew_prefix/"* ]]; then
  echo "Updating Poetry with Homebrew..."
  brew upgrade poetry || brew reinstall poetry
  poetry --version
  exit 0
fi

# Avoid invoking pip against an externally managed distro Python.
if command -v dpkg-query >/dev/null 2>&1 &&
  poetry_package="$(dpkg-query --search "$poetry_executable" 2>/dev/null | head -n 1 | cut -d: -f1)" &&
  [[ -n "$poetry_package" ]]; then
  echo "Updating Poetry package $poetry_package with apt..."
  if [[ "$(id -u)" -eq 0 ]]; then
    apt-get update
    apt-get install --only-upgrade -y "$poetry_package"
  else
    sudo apt-get update
    sudo apt-get install --only-upgrade -y "$poetry_package"
  fi
  poetry --version
  exit 0
fi

# Poetry's official installer creates this dedicated virtual environment and
# supports `self update`; using pip inside it is not supported.
if [[ "$poetry_executable" == */pypoetry/venv/* ]]; then
  echo "Updating Poetry installed by the official installer..."
  poetry self update
  poetry --version
  exit 0
fi

# A pip-installed console script records the Python interpreter that owns it in
# its shebang. Updating through that interpreter avoids modifying another Python
# installation when several versions are present.
shebang="$(head -n 1 "$poetry_executable" 2>/dev/null || true)"
if [[ "$shebang" =~ ^\#!([^[:space:]]+/python[^[:space:]]*)([[:space:]].*)?$ ]]; then
  poetry_python="${BASH_REMATCH[1]}"
  echo "Updating Poetry with pip using $poetry_python..."
  "$poetry_python" -m pip install --upgrade poetry
  poetry --version
  exit 0
fi

cat >&2 <<EOF_ERROR
Unable to determine how Poetry was installed.
Poetry command: $poetry_command
Resolved executable: $poetry_executable
Update Poetry manually, or install it with pipx, pip, or the official installer.
EOF_ERROR
exit 1
