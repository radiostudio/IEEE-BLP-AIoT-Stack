# PyInstaller recipe for aiot-gateway.exe. Build with build_windows.bat
# (see BUILD.md); it runs, from the repository root:
#
#   pyinstaller --noconfirm --clean packaging\windows\aiot_gateway.spec
#
# A folder build (onedir): the .exe and an _internal folder next to it. Not
# a single file: the gateway saves faults.json (used by "inject") and the
# agents' evidence packs inside its own folder, which a single-file build
# recreates empty at every start.

import os
import sys

from PyInstaller.utils.hooks import collect_all, collect_submodules

ROOT = os.path.abspath(os.path.join(SPECPATH, "..", ".."))
GW = os.path.join(ROOT, "gateway")

# Files the gateway reads at run time, at the same place inside the bundle
datas = [
    (os.path.join(GW, "cards"), "gateway/cards"),
    (os.path.join(GW, "dashboard", "index.html"), "gateway/dashboard"),
    (os.path.join(GW, "mcp_server", "prompts"), "gateway/mcp_server/prompts"),
    (os.path.join(GW, "mcp_server", "resources"), "gateway/mcp_server/resources"),
    (os.path.join(GW, "agents", "recipes"), "gateway/agents/recipes"),
    (os.path.join(GW, "config.json"), "gateway"),
]
binaries = []

# The gateway imports most of its modules inside functions; take them all,
# except the self-tests
hiddenimports = []
for name in collect_submodules("gateway"):
    if not name.startswith("gateway.tests"):
        hiddenimports.append(name)

# Packages with data files, metadata or imports PyInstaller cannot see:
# mcp (and the web server under it), and bleak with, on Windows, the WinRT
# modules it uses for Bluetooth
packages = ["mcp", "uvicorn", "sse_starlette", "bleak"]
if sys.platform == "win32":
    packages += ["winrt"]


def wanted(module):
    # mcp.cli is the "mcp" command-line tool; it needs typer, which is not
    # installed, and exits when imported without it
    if module.startswith("mcp.cli"):
        return False
    # bleak's Bluetooth backends for the other operating systems
    if module.startswith("bleak.backends.corebluetooth"):
        return False
    if sys.platform == "win32" and module.startswith("bleak.backends.bluezdbus"):
        return False
    if sys.platform != "win32" and module.startswith("bleak.backends.winrt"):
        return False
    return True


for package in packages:
    package_datas, package_binaries, package_imports = collect_all(
        package, filter_submodules=wanted)
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_imports

a = Analysis(
    [os.path.join(SPECPATH, "entry.py")],
    pathex=[ROOT],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["tkinter", "matplotlib", "pandas", "numpy", "IPython"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="aiot-gateway",
    console=True,
)
coll = COLLECT(exe, a.binaries, a.datas, name="aiot-gateway")
