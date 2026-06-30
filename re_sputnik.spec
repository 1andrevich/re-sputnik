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


# Single source of truth for the version: src/re_sputnik/__init__.py. Read it here
# (don't import the package — its deps may be unavailable in the build env) so the
# exe's file-properties version always matches what the UI shows.
def _read_app_version():
    import re
    with open(os.path.join(SRC, "__init__.py"), encoding="utf-8") as _f:
        _m = re.search(r'__version__\s*=\s*["\']([^"\']+)["\']', _f.read())
    return _m.group(1) if _m else "0.0.0"


APP_VERSION = _read_app_version()

datas = []
binaries = []
hiddenimports = []

# customtkinter ships themes/assets that must travel with the build.
ck_datas, ck_binaries, ck_hidden = collect_all("customtkinter")
datas += ck_datas
binaries += ck_binaries
hiddenimports += ck_hidden

# Pillow's Tk bridge: ImageTk.PhotoImage (used by every CTkImage + the window
# icon) imports PIL._tkinter_finder DYNAMICALLY, so PyInstaller's PIL hook misses
# it and the freeze raises "No module named 'PIL._tkinter_finder'" the moment a
# logo renders (e.g. the mode picker right after the disclaimer gate). Windows happened
# to resolve it; Linux did not. Force it in.
hiddenimports += ["PIL._tkinter_finder"]

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

# App data: the whole resources/ + assets/ trees, plus the legal files the About
# screen / disclaimer prompt read (bundled into resources so their lookup finds them
# in the freeze). The GPLv3 LICENSE and the THIRD_PARTY_LICENSES texts must ship with
# the binary so users can read the license and dependency licenses offline.
datas += [
    (os.path.join(SRC, "resources"), "re_sputnik/resources"),
    (os.path.join(SRC, "assets"), "re_sputnik/assets"),
    (os.path.join(PROJ, "NOTICE"), "re_sputnik/resources"),
    (os.path.join(PROJ, "LICENSE"), "re_sputnik/resources"),
    (os.path.join(PROJ, "THIRD_PARTY_LICENSES"), "re_sputnik/resources/THIRD_PARTY_LICENSES"),
]

# Compiled gettext catalogs (.mo) for the UI languages. i18n._locale_dir() looks
# under _MEIPASS/re_sputnik/locale in the freeze, so mirror that layout. Only the
# .mo files are needed at runtime; the .po sources can stay out of the bundle.
_locale = os.path.join(SRC, "locale")
if os.path.isdir(_locale):
    datas += [(_locale, "re_sputnik/locale")]

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

# Windows version resource (shown in the exe's Properties → Details), derived from
# APP_VERSION so it can never drift from the in-app version.
version_info = None
if IS_WIN:
    from PyInstaller.utils.win32.versioninfo import (
        VSVersionInfo, FixedFileInfo, StringFileInfo, StringTable, StringStruct,
        VarFileInfo, VarStruct)
    _nums = [int(p) for p in APP_VERSION.split(".") if p.isdigit()]
    _vt = tuple((_nums + [0, 0, 0, 0])[:4])  # (major, minor, patch, build)
    version_info = VSVersionInfo(
        ffi=FixedFileInfo(filevers=_vt, prodvers=_vt, mask=0x3F, flags=0x0,
                          OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
        kids=[
            StringFileInfo([StringTable("040904B0", [
                StringStruct("CompanyName", "1andrevich"),
                StringStruct("FileDescription", "Re:Sputnik"),
                StringStruct("FileVersion", APP_VERSION),
                StringStruct("InternalName", "Re-Sputnik"),
                StringStruct("LegalCopyright", "Copyright (c) 2026 1andrevich"),
                StringStruct("OriginalFilename", "Re-Sputnik.exe"),
                StringStruct("ProductName", "Re:Sputnik"),
                StringStruct("ProductVersion", APP_VERSION),
            ])]),
            VarFileInfo([VarStruct("Translation", [0x0409, 1200])]),
        ])

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
    version=version_info,      # Windows file-properties version (None on mac/Linux)
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
            "CFBundleShortVersionString": APP_VERSION,
            "CFBundleVersion": APP_VERSION,
            "NSHighResolutionCapable": True,
            "LSMinimumSystemVersion": "11.0",
            "NSHumanReadableCopyright": "© 2026 1andrevich. Licensed under the GNU GPLv3.",
        },
    )
