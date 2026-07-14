#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Sayeh Ava Pazouki
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileComment: Additional terms apply; see ADDITIONAL_TERMS.md.

set -euo pipefail

REPOSITORY="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
VARIANT="all"
OUTPUT_DIR="${PRINTBRIDGE_RELEASE_DIR:-$REPOSITORY/build}"
OUTPUT_DIR_ARGUMENT_SET=0
SELECT_OUTPUT_DIR=0

if [[ $# -gt 0 && "$1" != --* ]]; then
    case "$1" in
        Native|native) VARIANT="native" ;;
        PyInstaller|pyinstaller) VARIANT="pyinstaller" ;;
        All|all) VARIANT="all" ;;
        *) VARIANT="$1" ;;
    esac
    shift
fi
while [[ $# -gt 0 ]]; do
    case "$1" in
        --output-dir)
            if [[ $# -lt 2 ]]; then
                echo "--output-dir requires a path." >&2
                exit 2
            fi
            OUTPUT_DIR="$2"
            OUTPUT_DIR_ARGUMENT_SET=1
            shift 2
            ;;
        --output-dir=*)
            OUTPUT_DIR="${1#*=}"
            OUTPUT_DIR_ARGUMENT_SET=1
            shift
            ;;
        --select-output-dir)
            SELECT_OUTPUT_DIR=1
            shift
            ;;
        *)
            echo "Unknown argument: $1" >&2
            exit 2
            ;;
    esac
done
if [[ "$VARIANT" != "native" && "$VARIANT" != "pyinstaller" && "$VARIANT" != "all" ]]; then
    echo "Variant must be native, pyinstaller, or all." >&2
    exit 2
fi
if [[ "$SELECT_OUTPUT_DIR" -eq 1 && "$OUTPUT_DIR_ARGUMENT_SET" -eq 1 ]]; then
    echo "Use either --output-dir or --select-output-dir, not both." >&2
    exit 2
fi
if [[ "$SELECT_OUTPUT_DIR" -eq 1 ]]; then
    if [[ "$(uname -s)" != "Darwin" ]]; then
        echo "The output folder selector is available only on macOS." >&2
        exit 2
    fi
    if ! OUTPUT_DIR="$(osascript -e 'POSIX path of (choose folder with prompt "Choose where Pridge Client release packages will be saved.")')"; then
        echo "Output directory selection was cancelled." >&2
        exit 2
    fi
fi

mkdir -p "$OUTPUT_DIR"
OUTPUT_DIR="$(cd "$OUTPUT_DIR" && pwd -P)"

INITIAL_GIT_STATUS="$(git -C "$REPOSITORY" status --porcelain --untracked-files=all)"
TEMP_BASE="${RUNNER_TEMP:-${TMPDIR:-/tmp}}"
TEMP_ROOT="$(mktemp -d "$TEMP_BASE/Pridge-Client-macOS.XXXXXX")"
LOG_PATH="$OUTPUT_DIR/build-macos-$VARIANT.log"

cleanup() {
    local result=$?
    rm -rf "$TEMP_ROOT"
    local final_status
    final_status="$(git -C "$REPOSITORY" status --porcelain --untracked-files=all)"
    if [[ "$final_status" != "$INITIAL_GIT_STATUS" ]]; then
        echo "The build changed the source repository:" >&2
        echo "$final_status" >&2
        exit 1
    fi
    exit "$result"
}
trap cleanup EXIT
if [[ -n "${PRINTBRIDGE_BUILD_LOG_ONLY:-}" ]]; then
    exec > "$LOG_PATH" 2>&1
else
    exec > >(tee "$LOG_PATH") 2>&1
fi

if [[ "$(uname -s)" != "Darwin" ]]; then
    echo "macOS builds must run natively on macOS." >&2
    exit 1
fi

MACHINE="$(uname -m)"
case "$MACHINE" in
    arm64) ARCH="arm64" ;;
    x86_64) ARCH="x86_64" ;;
    *) echo "Unsupported macOS architecture: $MACHINE" >&2; exit 1 ;;
esac
export PYTHONPATH="$REPOSITORY/src"
export PYINSTALLER_CONFIG_DIR="$TEMP_ROOT/pyinstaller-config"
export PYTHONPYCACHEPREFIX="$TEMP_ROOT/python-cache"
export NUITKA_CACHE_DIR="$TEMP_ROOT/nuitka-cache"
export CCACHE_DIR="$TEMP_ROOT/ccache"

context_value() {
    python3 -c 'import json, sys; print(json.load(open(sys.argv[1], encoding="utf-8"))[sys.argv[2]])' "$1" "$2"
}

prepare_context() {
    local build_variant="$1"
    local context_dir="$TEMP_ROOT/context-$build_variant"
    python3 "$REPOSITORY/scripts/prepare_build.py" --work-dir "$context_dir" --variant "$build_variant" --arch "$ARCH"
}

finalize_app() {
    local app="$1"
    local context="$2"
    python3 "$REPOSITORY/scripts/finalize_macos_app.py" --app "$app" --context "$context"
    local executable
    executable="$(/usr/libexec/PlistBuddy -c 'Print :CFBundleExecutable' "$app/Contents/Info.plist")"
    "$app/Contents/MacOS/$executable" --version
    local architectures
    architectures="$(lipo -archs "$app/Contents/MacOS/$executable")"
    if [[ " $architectures " != *" $ARCH "* ]]; then
        echo "The app executable does not contain the required $ARCH architecture." >&2
        exit 1
    fi
}

sign_app() {
    local app="$1"
    if [[ -n "${PRINTBRIDGE_MACOS_SIGNING_IDENTITY:-}" ]]; then
        codesign --force --deep --options runtime --timestamp --sign "$PRINTBRIDGE_MACOS_SIGNING_IDENTITY" "$app"
    else
        codesign --force --deep --sign - "$app"
    fi
    codesign --verify --deep --strict --verbose=2 "$app"
}

notarize_dmg() {
    local dmg="$1"
    if [[ -z "${PRINTBRIDGE_MACOS_SIGNING_IDENTITY:-}" ]]; then
        if [[ -n "${PRINTBRIDGE_NOTARY_KEY_BASE64:-}${PRINTBRIDGE_NOTARY_APPLE_ID:-}" ]]; then
            echo "A Developer ID signing identity is required for notarization." >&2
            exit 1
        fi
        return
    fi
    codesign --force --timestamp --sign "$PRINTBRIDGE_MACOS_SIGNING_IDENTITY" "$dmg"
    if [[ -n "${PRINTBRIDGE_NOTARY_KEY_BASE64:-}" ]]; then
        if [[ -z "${PRINTBRIDGE_NOTARY_KEY_ID:-}" || -z "${PRINTBRIDGE_NOTARY_ISSUER_ID:-}" ]]; then
            echo "Notary key ID and issuer ID are required with an API key." >&2
            exit 1
        fi
        local key_path="$TEMP_ROOT/AuthKey_${PRINTBRIDGE_NOTARY_KEY_ID}.p8"
        python3 -c 'import base64, pathlib, sys; pathlib.Path(sys.argv[2]).write_bytes(base64.b64decode(sys.argv[1]))' "$PRINTBRIDGE_NOTARY_KEY_BASE64" "$key_path"
        xcrun notarytool submit "$dmg" --key "$key_path" --key-id "$PRINTBRIDGE_NOTARY_KEY_ID" --issuer "$PRINTBRIDGE_NOTARY_ISSUER_ID" --wait
        xcrun stapler staple "$dmg"
    elif [[ -n "${PRINTBRIDGE_NOTARY_APPLE_ID:-}" ]]; then
        if [[ -z "${PRINTBRIDGE_NOTARY_TEAM_ID:-}" || -z "${PRINTBRIDGE_NOTARY_PASSWORD:-}" ]]; then
            echo "Notary team ID and app-specific password are required with an Apple ID." >&2
            exit 1
        fi
        xcrun notarytool submit "$dmg" --apple-id "$PRINTBRIDGE_NOTARY_APPLE_ID" --team-id "$PRINTBRIDGE_NOTARY_TEAM_ID" --password "$PRINTBRIDGE_NOTARY_PASSWORD" --wait
        xcrun stapler staple "$dmg"
    fi
}

create_dmg() {
    local app="$1"
    local context="$2"
    local package_name
    package_name="$(context_value "$context" macos_package)"
    local build_variant
    build_variant="$(context_value "$context" variant)"
    local version
    version="$(context_value "$context" version)"
    local stage="$TEMP_ROOT/dmg-$build_variant"
    mkdir -p "$stage"
    cp -R "$app" "$stage/Pridge Client.app"
    cp "$REPOSITORY/LICENSE" "$stage/LICENSE"
    cp "$REPOSITORY/ADDITIONAL_TERMS.md" "$stage/ADDITIONAL_TERMS.md"
    cp "$(context_value "$context" icon_icns)" "$stage/.VolumeIcon.icns"
    ln -s /Applications "$stage/Applications"
    xcrun SetFile -a V "$stage/.VolumeIcon.icns"
    xcrun SetFile -a C "$stage"
    local volume_variant="$build_variant"
    if [[ "$build_variant" == "PyInstaller" ]]; then volume_variant="PyInstaller"; fi
    local destination="$OUTPUT_DIR/$package_name"
    rm -f "$destination"
    hdiutil create -volname "PB Client $volume_variant $version" -srcfolder "$stage" -format UDZO -imagekey zlib-level=9 -ov "$destination"
    hdiutil verify "$destination"
    notarize_dmg "$destination"
}

build_native() {
    local context
    context="$(prepare_context Native)"
    local compile_root="$TEMP_ROOT/native"
    mkdir -p "$compile_root"
    python3 -m nuitka \
        --standalone \
        --macos-create-app-bundle \
        --assume-yes-for-downloads \
        --output-dir="$compile_root" \
        --output-filename="Pridge Client" \
        --macos-app-icon="$(context_value "$context" icon_icns)" \
        --macos-app-version="$(context_value "$context" version)" \
        --company-name="$(context_value "$context" company_name)" \
        --product-name="$(context_value "$context" app_name)" \
        --file-description="$(context_value "$context" description)" \
        --copyright="$(context_value "$context" copyright)" \
        --file-version="$(context_value "$context" numeric_file_version)" \
        --product-version="$(context_value "$context" numeric_file_version)" \
        --include-data-dir="$REPOSITORY/src/printbridge_client/webui=printbridge_client/webui" \
        --include-data-files="$REPOSITORY/LICENSE=LICENSE" \
        --include-data-files="$REPOSITORY/ADDITIONAL_TERMS.md=ADDITIONAL_TERMS.md" \
        --include-data-files="$(context_value "$context" metadata)=printbridge_client/_build.json" \
        --include-package-data=webview \
        --include-module=pystray._darwin \
        --include-package=keyring \
        --nofollow-import-to=PIL.ImageTk \
        --nofollow-import-to=PIL._tkinter_finder \
        --nofollow-import-to=tkinter \
        --nofollow-import-to=_tkinter \
        --report="$OUTPUT_DIR/native-macos-$ARCH-compilation-report.xml" \
        "$REPOSITORY/src/printbridge_client/__main__.py"
    local app
    app="$(find "$compile_root" -maxdepth 3 -type d -name '*.app' -print -quit)"
    if [[ -z "$app" ]]; then echo "Could not find the Nuitka app bundle." >&2; exit 1; fi
    finalize_app "$app" "$context"
    sign_app "$app"
    create_dmg "$app" "$context"
}

build_pyinstaller() {
    local context
    context="$(prepare_context PyInstaller)"
    local compile_root="$TEMP_ROOT/pyinstaller"
    export PRINTBRIDGE_BUILD_CONTEXT="$context"
    python3 -m PyInstaller --noconfirm --clean \
        --distpath "$compile_root/dist" \
        --workpath "$compile_root/work" \
        "$REPOSITORY/packaging/pyinstaller/Pridge-Client.spec"
    local app="$compile_root/dist/Pridge Client.app"
    if [[ ! -d "$app" ]]; then echo "Could not find the PyInstaller app bundle." >&2; exit 1; fi
    finalize_app "$app" "$context"
    sign_app "$app"
    create_dmg "$app" "$context"
}

if [[ "$VARIANT" == "native" || "$VARIANT" == "all" ]]; then build_native; fi
if [[ "$VARIANT" == "pyinstaller" || "$VARIANT" == "all" ]]; then build_pyinstaller; fi
python3 "$REPOSITORY/scripts/generate_release_notes.py" --output-dir "$OUTPUT_DIR"
python3 "$REPOSITORY/scripts/generate_checksums.py" --output-dir "$OUTPUT_DIR"
