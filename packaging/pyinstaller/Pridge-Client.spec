# -*- mode: python ; coding: utf-8 -*-
# SPDX-FileCopyrightText: 2026 Sayeh Ava Pazouki
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileComment: Additional terms apply; see ADDITIONAL_TERMS.md.

import json
import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules


context_path = os.environ.get("PRINTBRIDGE_BUILD_CONTEXT")
if not context_path:
    raise RuntimeError("PRINTBRIDGE_BUILD_CONTEXT must point to a generated build-context.json file")
context = json.loads(Path(context_path).read_text(encoding="utf-8"))
root = Path(context["root"])
source_root = root / "src"
package_root = source_root / "printbridge_client"

datas = [
    (str(package_root / "webui"), "printbridge_client/webui"),
    (str(root / "LICENSE"), "."),
    (str(root / "ADDITIONAL_TERMS.md"), "."),
    (context["metadata"], "printbridge_client"),
]
binaries = []
hiddenimports = []
for package in ("webview", "keyring", "pystray", "PIL"):
    package_datas, package_binaries, package_hiddenimports = collect_all(package)
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_hiddenimports

hiddenimports += collect_submodules("printbridge_client")
if sys.platform == "win32":
    for package in ("pythonnet", "clr_loader"):
        package_datas, package_binaries, package_hiddenimports = collect_all(package)
        datas += package_datas
        binaries += package_binaries
        hiddenimports += package_hiddenimports
    hiddenimports += [
        "webview.platforms.winforms",
        "webview.platforms.edgechromium",
        "webview.platforms.win32",
        "clr",
        "pythoncom",
        "pywintypes",
        "win32print",
    ]
elif sys.platform == "darwin":
    hiddenimports += ["webview.platforms.cocoa", "AppKit", "Foundation", "WebKit"]
elif sys.platform.startswith("linux"):
    hiddenimports += [
        "webview.platforms.qt",
        "qtpy",
        "PyQt6.QtWebChannel",
        "PyQt6.QtWebEngineCore",
        "PyQt6.QtWebEngineWidgets",
    ]

excluded_gui_packages = ["PyQt5", "PySide2", "PySide6", "gtk"]
if not sys.platform.startswith("linux"):
    excluded_gui_packages += ["PyQt6", "qtpy"]

analysis = Analysis(
    [str(package_root / "__main__.py")],
    pathex=[str(source_root)],
    binaries=binaries,
    datas=datas,
    hiddenimports=sorted(set(hiddenimports)),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excluded_gui_packages,
    noarchive=False,
    optimize=0,
)
pyz = PYZ(analysis.pure)
exe = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name=context["executable_name"],
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=context["arch"] if sys.platform == "darwin" else None,
    codesign_identity=None,
    entitlements_file=None,
    icon=(
        context["icon_ico"]
        if sys.platform == "win32"
        else context["icon_icns"] if sys.platform == "darwin" else None
    ),
    version=context["windows_version_file"] if sys.platform == "win32" else None,
)
collection = COLLECT(
    exe,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name=context["app_name"],
)
if sys.platform == "darwin":
    app = BUNDLE(
        collection,
        name=f"{context['app_name']}.app",
        icon=context["icon_icns"],
        bundle_identifier=context["identifier"],
        version=context["version"],
        info_plist={
            "CFBundleDisplayName": context["app_name"],
            "CFBundleName": context["app_name"],
            "CFBundleShortVersionString": context["version"],
            "CFBundleVersion": context["numeric_file_version"],
            "NSHumanReadableCopyright": context["copyright"],
            "LSMinimumSystemVersion": "11.0",
            "NSHighResolutionCapable": True,
        },
    )
