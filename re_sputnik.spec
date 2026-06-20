# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for Re:Sputnik. Build: pyinstaller re_sputnik.spec
# Cross-platform: produces Re-Sputnik.exe on Windows and Re-Sputnik.app on macOS.
import os
import sys

from PyInstaller.utils.hooks import collect_all, collect_submodules, copy_metadata

# Project root = the spec's OWN directory (PyInstaller injects SPECPATH), not the
# working dir pyinstaller was invoked from. getcwd() would silently drop the
# repo-root NOTICE if a build ran from elsewhere — PyInstaller only warns on a
# missing datas source, so the .app would build fine but without the NOTICE.
PROJ = os.path.abspath(globals().get("SPECPATH", os.getcwd()))
SRC = os.path.join(PROJ, "src", "re_sputnik")
IS_MAC = sys.platform == "darwin"
IS_WIN = sys.platform.startswith("win")
# anything else (Linux) gets the Secret Service keyring backend + no icon embed.

datas = []
binaries = []
hiddenimports = []

# customtkinter ships themes/assets that must travel with the build.
ck_datas, ck_binaries, ck_hidden = collect_all("customtkinter")
datas += ck_datas
binaries += ck_binaries
hiddenimports += ck_hidden

# keyring discovers its OS backend via entry-point metadata at runtime. Pull in
# the backend for THIS platform (Windows Credential Locker / macOS Keychain).
hiddenimports += collect_submodules("keyring")
datas += copy_metadata("keyring")
if IS_MAC:
    # module name changed across keyring versions: macOS (new) / OS_X (old).
    for mod in ("keyring.backends.macOS", "keyring.backends.OS_X"):
        try:
            __import__(mod)
            hiddenimports += [mod]
        except Exception:
            pass
elif IS_WIN:
    hiddenimports += ["keyring.backends.Windows"]
    try:  # the Windows backend leans on pywin32-ctypes
        hiddenimports += collect_submodules("win32ctypes")
    except Exception:
        pass
else:  # Linux: keyring talks to the Secret Service (GNOME Keyring/KWallet) over D-Bus
    hiddenimports += ["keyring.backends.SecretService"]
    for mod in ("secretstorage", "jeepney"):
        try:
            hiddenimports += collect_submodules(mod)
        except Exception:
            pass

# paramiko + cryptography submodules (SSH transport).
hiddenimports += collect_submodules("paramiko")

# certifi CA bundle — pin TLS trust so HTTPS to GitHub verifies even when the
# OS cert store isn't reachable from the freeze (CERTIFICATE_VERIFY_FAILED fix).
ce_datas, ce_binaries, ce_hidden = collect_all("certifi")
datas += ce_datas
binaries += ce_binaries
hiddenimports += ce_hidden

# App data: the whole resources/ + assets/ trees, plus the NOTICE the About
# screen reads (bundled into resources so its lookup finds it in the freeze).
datas += [
    (os.path.join(SRC, "resources"), "re_sputnik/resources"),
    (os.path.join(SRC, "assets"), "re_sputnik/assets"),
    (os.path.join(PROJ, "NOTICE"), "re_sputnik/resources"),
]

# Window/app icon: .icns for the macOS bundle, .ico for the Windows exe. Either
# may be absent (CI generates the .icns) → fall back to None so the build still
# succeeds (the app also sets its icon at runtime via iconphoto).
_icns = os.path.join(SRC, "resources", "branding", "icon.icns")
_ico = os.path.join(SRC, "resources", "branding", "icon.ico")
icon_path = _icns if IS_MAC else (_ico if IS_WIN else None)  # Linux: PyInstaller ignores icon anyway
if not (icon_path and os.path.exists(icon_path)):
    icon_path = None

a = Analysis(
    ["launcher.py"],
    pathex=["src"],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter.test", "test", "pytest"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="Re-Sputnik",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,                 # no UPX dependency; avoids AV false-positives
    runtime_tmpdir=None,
    console=False,             # GUI app: no console window
    disable_windowed_traceback=False,
    icon=icon_path,
)

# On macOS, wrap the executable in a proper .app bundle.
if IS_MAC:
    app = BUNDLE(
        exe,
        name="Re-Sputnik.app",
        icon=icon_path,
        bundle_identifier="com.resputnik.app",
        info_plist={
            "CFBundleName": "Re-Sputnik",
            "CFBundleDisplayName": "Re:Sputnik",
            "CFBundleShortVersionString": "0.1.0",
            "CFBundleVersion": "0.1.0",
            "NSHighResolutionCapable": True,
            "LSMinimumSystemVersion": "11.0",
            "NSHumanReadableCopyright": "© 1andrevich. GPL-2.0-only.",
        },
    )
