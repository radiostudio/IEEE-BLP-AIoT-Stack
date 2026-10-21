#!/usr/bin/env bash
# Full gateway setup for macOS/Linux. Safe to run more than once.
# Options: --recreate (rebuild the environment from scratch)
#          --with-anthropic (also install the extra package for BYOK students)
#          --with-pptx (also install python-pptx, needed only to regenerate
#                       slides from sensor_decks/ via tools/md2pptx.py -
#                       instructors/content authors only, not needed by students)
set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

RECREATE=0
WITH_ANTHROPIC=0
WITH_PPTX=0
for arg in "$@"; do
    case "$arg" in
        --recreate) RECREATE=1 ;;
        --with-anthropic) WITH_ANTHROPIC=1 ;;
        --with-pptx) WITH_PPTX=1 ;;
    esac
done

echo "== AIoT Gateway setup (macOS/Linux) =="
echo ""

# 1. Find a Python 3 interpreter.
find_python() {
    for candidate in python3 python; do
        if command -v "$candidate" >/dev/null 2>&1; then
            if "$candidate" -c 'import sys; sys.exit(0 if sys.version_info[0] == 3 else 1)' >/dev/null 2>&1; then
                echo "$candidate"
                return 0
            fi
        fi
    done
    return 1
}

PY="$(find_python)" || {
    echo "No Python 3 installation was found on this machine."
    echo "Install Python 3.10 or newer, then re-run this script:"
    echo "  macOS:  https://www.python.org/downloads/macos/  (or: brew install python3)"
    echo "  Linux:  use your distro's package manager, e.g. sudo apt install python3"
    echo ""
    echo "If this is a school/managed laptop and you cannot install software,"
    echo "ask your instructor for help."
    exit 1
}

# 2. Check the version is at least 3.10.
if ! "$PY" -c 'import sys; sys.exit(0 if sys.version_info[:2] >= (3, 10) else 1)'; then
    DETECTED="$("$PY" -c 'import platform; print(platform.python_version())')"
    echo "Detected Python $DETECTED, but the gateway needs Python 3.10 or newer."
    echo "Install a newer Python: https://www.python.org/downloads/"
    exit 2
fi

# 3. Create or reuse the virtual environment.
VENV_DIR="$SCRIPT_DIR/.venv-gateway"
VENV_PY="$VENV_DIR/bin/python3"

venv_is_valid() {
    [ -x "$VENV_PY" ] && "$VENV_PY" -c "import sys" >/dev/null 2>&1
}

if [ "$RECREATE" -eq 1 ] && [ -d "$VENV_DIR" ]; then
    echo "Removing existing .venv-gateway (--recreate was passed)..."
    rm -rf "$VENV_DIR"
fi

if venv_is_valid; then
    echo "Reusing existing .venv-gateway."
else
    if [ -d "$VENV_DIR" ]; then
        echo "Existing .venv-gateway looks broken, rebuilding it..."
        rm -rf "$VENV_DIR"
    fi
    echo "Creating .venv-gateway..."
    if ! "$PY" -m venv "$VENV_DIR"; then
        echo ""
        echo "Could not create a virtual environment."
        echo "On Debian/Ubuntu this is often fixed with: sudo apt install python3-venv"
        echo "If you don't have permission to install software, ask your instructor for help."
        exit 3
    fi
fi

# 4. Upgrade pip (best-effort, never fatal).
"$VENV_PY" -m pip install --upgrade pip >/dev/null 2>&1 || \
    echo "Warning: could not upgrade pip, continuing anyway."

# 5. Install dependencies.
echo "Installing gateway dependencies..."
if ! "$VENV_PY" -m pip install -r "$SCRIPT_DIR/gateway/requirements.txt"; then
    echo ""
    echo "Could not install the required packages."
    echo "Check your Wi-Fi connection (captive portal login pages are a common cause)"
    echo "and that you have free disk space, then try this command by hand:"
    echo "  $VENV_PY -m pip install -r gateway/requirements.txt"
    exit 4
fi

if [ "$WITH_ANTHROPIC" -eq 1 ]; then
    echo "Installing the anthropic package (--with-anthropic)..."
    "$VENV_PY" -m pip install "anthropic>=0.40" || \
        echo "Warning: could not install anthropic, you can retry later by hand."
fi

if [ "$WITH_PPTX" -eq 1 ]; then
    echo "Installing python-pptx (--with-pptx)..."
    "$VENV_PY" -m pip install "python-pptx>=0.6" || \
        echo "Warning: could not install python-pptx, you can retry later by hand."
fi

# 6. Run the existing pass/fail test.
echo ""
echo "Running the gateway self-test (python -m gateway smoke)..."
"$VENV_PY" -m gateway smoke
SMOKE_STATUS=$?

if [ "$SMOKE_STATUS" -ne 0 ]; then
    echo ""
    echo "Setup finished, but the self-test failed."
    echo "Copy the output above and show it to your instructor."
    exit "$SMOKE_STATUS"
fi

# 7. Linux only: try to fix the Bluetooth permission automatically.
if [ "$(uname -s)" = "Linux" ]; then
    if id -nG "$USER" 2>/dev/null | tr ' ' '\n' | grep -qx "bluetooth"; then
        : # already has permission, nothing to do
    elif command -v sudo >/dev/null 2>&1; then
        echo ""
        echo "Setting up Bluetooth permissions for live sensor scanning..."
        if sudo usermod -aG bluetooth "$USER"; then
            echo "Done. Log out and back in once before the workshop for this to take effect."
        else
            echo "Could not set this up automatically. Before the workshop, run:"
            echo "  sudo usermod -aG bluetooth $USER"
            echo "then log out and back in."
        fi
    else
        echo ""
        echo "Note: for live Bluetooth scanning, your account may need one extra"
        echo "permission. Before the workshop, ask your instructor to run:"
        echo "  sudo usermod -aG bluetooth $USER"
        echo "then log out and back in."
    fi
fi

# 8. Success.
echo ""
echo "Setup complete! Try:"
echo "  bash gateway.sh simulate"
echo ""
echo "Before you use the gateway for real (python -m gateway run), take a"
echo "look at PREREQUISITES.md - it covers a couple of one-time,"
echo "one-per-machine things this script can't do for you (like turning"
echo "Bluetooth on)."
exit 0
