#!/usr/bin/env python
"""Detects your operating system and runs the matching gateway setup script.

Run this with:  python3 start_installation.py   (macOS/Linux)
                 python start_installation.py    (Windows)

This file does not do any setup work itself - it just figures out whether
you're on Windows, macOS, or Linux, and hands off to setup.bat or setup.sh,
which do the real work. Any extra options you pass (e.g. --recreate) are
passed straight through.

Written in a plain, old-fashioned style on purpose, so that even a very old
or unusual Python install is more likely to print a clear error message here
instead of crashing with a wall of red text.
"""

import os
import subprocess
import sys


def main():
    repo_root = os.path.dirname(os.path.abspath(__file__))
    os.chdir(repo_root)
    extra_args = sys.argv[1:]

    if sys.platform.startswith("win"):
        script_path = os.path.join(repo_root, "setup.bat")
        command = ["cmd", "/c", script_path] + extra_args
    elif sys.platform.startswith("darwin") or sys.platform.startswith("linux"):
        script_path = os.path.join(repo_root, "setup.sh")
        command = ["bash", script_path] + extra_args
    else:
        sys.stderr.write(
            "Could not tell what operating system this is (detected: %s).\n"
            "This tool only knows how to set up Windows, macOS, and Linux.\n"
            "Please ask your instructor for help.\n" % sys.platform
        )
        sys.exit(1)
        return

    exit_code = subprocess.call(command)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
