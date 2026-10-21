#!/usr/bin/env bash
# Downloads the AIoT gateway course code and runs the one-command setup, so
# a student can go from nothing to a working environment with one line:
#
#   curl -fsSL <raw-url-of-this-file> | bash
#
# To pass extra flags through to start_installation.py (e.g. --with-pptx):
#
#   curl -fsSL <raw-url-of-this-file> | bash -s -- --with-pptx
#
# NOTE: REPO_ZIP_URL below points at a branch. Update it to point at `main`
# once feature/onboarding-scripts merges.
set -u

REPO_ZIP_URL="https://github.com/sriram-rs/IEEE-BLP-AIoT-Stack/archive/refs/heads/feature/onboarding-scripts.zip"
DEST_DIR="$(pwd)/IEEE-BLP-AIoT-Stack"

echo "== Downloading the AIoT Gateway course code =="

# The real, careful Python-version check happens later in setup.sh, once
# it's downloaded - here we just need any Python 3 to run
# start_installation.py and to extract the zip (via its stdlib zipfile
# module, so this doesn't depend on the external "unzip" tool existing).
PY=""
if command -v python3 >/dev/null 2>&1; then
    PY=python3
elif command -v python >/dev/null 2>&1; then
    PY=python
fi

if [ -z "$PY" ]; then
    echo "No Python installation was found on this machine."
    echo "Install Python 3.10 or newer, then run this command again:"
    echo "  macOS:  https://www.python.org/downloads/macos/  (or: brew install python3)"
    echo "  Linux:  use your distro's package manager, e.g. sudo apt install python3"
    echo ""
    echo "If this is a school/managed laptop and you cannot install software,"
    echo "ask your instructor for help."
    exit 1
fi

TMP_ZIP="$(mktemp -t aiot-stack.XXXXXX.zip 2>/dev/null || mktemp)"
DOWNLOAD_OK=1
if command -v curl >/dev/null 2>&1; then
    curl -fsSL "$REPO_ZIP_URL" -o "$TMP_ZIP" || DOWNLOAD_OK=0
elif command -v wget >/dev/null 2>&1; then
    wget -q "$REPO_ZIP_URL" -O "$TMP_ZIP" || DOWNLOAD_OK=0
else
    echo "Neither curl nor wget was found, so the code can't be downloaded automatically."
    echo "Ask your instructor for help, or download the ZIP manually from GitHub."
    rm -f "$TMP_ZIP"
    exit 2
fi

if [ "$DOWNLOAD_OK" -ne 1 ]; then
    echo "Could not download the code. Check your internet connection and try again."
    rm -f "$TMP_ZIP"
    exit 3
fi

EXTRACT_DIR="$(mktemp -d -t aiot-stack-extract.XXXXXX 2>/dev/null || mktemp -d)"
"$PY" -m zipfile -e "$TMP_ZIP" "$EXTRACT_DIR"
rm -f "$TMP_ZIP"

SRC_DIR="$(find "$EXTRACT_DIR" -mindepth 1 -maxdepth 1 -type d | head -n 1)"
if [ -z "$SRC_DIR" ]; then
    echo "Downloaded the code but couldn't find it after extracting."
    echo "Ask your instructor for help."
    exit 4
fi

if [ -e "$DEST_DIR" ]; then
    echo "Folder $DEST_DIR already exists - using it as-is instead of overwriting."
else
    mv "$SRC_DIR" "$DEST_DIR"
fi
rm -rf "$EXTRACT_DIR"

echo "Code is in: $DEST_DIR"
cd "$DEST_DIR"
echo "Running setup..."
exec "$PY" start_installation.py "$@"
