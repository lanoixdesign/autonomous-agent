# PyInstaller spec for the unsigned desktop builds.
#   pyinstaller --noconfirm --clean packaging/autonomous-agent.spec
# Windows / Linux: one file (dist/AutonomousAgent[.exe]) with a console window (logs + Ctrl+C).
# macOS: dist/AutonomousAgent.app (onedir inside the bundle); the launcher reopens itself in Terminal.
# Target architecture on macOS = the machine's (build on arm64 and on Intel separately).
import os
import sys

from PyInstaller.utils.hooks import collect_submodules

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))
NAME = "AutonomousAgent"

datas = [
    (os.path.join(ROOT, "skills"), "skills"),                       # bundled skills (agent/cli.py REPO_SKILLS)
    (os.path.join(ROOT, "permissions.yaml"), "."),                  # copied to ~/AutonomousAgent on first run
    (os.path.join(ROOT, "providers.example.yaml"), "."),
    (os.path.join(ROOT, ".env.example"), "."),
    (os.path.join(ROOT, "LICENSE"), "."),
]
# The web pages and the EN/FR strings are Python modules (agent/harness_*.py, agent/i18n.py).
hiddenimports = collect_submodules("agent") + ["sqlite3"]

a = Analysis(
    [os.path.join(SPECPATH, "launcher.py")],
    pathex=[ROOT],
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["tkinter", "pytest", "yaml"],   # stdlib-only build (the built-in YAML subset parser is used)
    noarchive=False,
)
pyz = PYZ(a.pure)

if sys.platform == "darwin":
    exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name=NAME, console=True,
              argv_emulation=False, target_arch=None, codesign_identity=None)
    coll = COLLECT(exe, a.binaries, a.datas, name=NAME)
    app = BUNDLE(coll, name=f"{NAME}.app", bundle_identifier="io.github.lanoixdesign.autonomous-agent",
                 info_plist={"CFBundleShortVersionString": os.environ.get("APP_VERSION", "0.3.0"),
                             "CFBundleDisplayName": "Autonomous Agent", "LSMinimumSystemVersion": "11.0",
                             "NSHighResolutionCapable": True})
else:
    exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name=NAME, console=True, upx=False,
              runtime_tmpdir=None)
