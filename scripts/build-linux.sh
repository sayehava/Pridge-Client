#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Sayeh Ava Pazouki
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileComment: Additional terms apply; see ADDITIONAL_TERMS.md.

set -euo pipefail

REPOSITORY="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
VARIANT="${1:-All}"
if [[ $# -gt 0 ]]; then shift; fi
OUTPUT_DIR="${PRINTBRIDGE_RELEASE_DIR:-$REPOSITORY/build}"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --output-dir)
            [[ $# -ge 2 ]] || { echo "--output-dir requires a path." >&2; exit 2; }
            OUTPUT_DIR="$2"
            shift 2
            ;;
        --output-dir=*) OUTPUT_DIR="${1#*=}"; shift ;;
        *) echo "Unknown argument: $1" >&2; exit 2 ;;
    esac
done

case "$VARIANT" in
    Native|native) VARIANT="native" ;;
    PyInstaller|pyinstaller) VARIANT="pyinstaller" ;;
    All|all) VARIANT="all" ;;
    *) echo "Variant must be Native, PyInstaller, or All." >&2; exit 2 ;;
esac

if [[ "$(uname -s)" != "Linux" ]]; then
    echo "Linux builds must run natively on Linux." >&2
    exit 1
fi
if [[ "$(uname -m)" != "x86_64" ]]; then
    echo "Only Linux x86_64 release builds are currently supported." >&2
    exit 1
fi

mkdir -p "$OUTPUT_DIR"
OUTPUT_DIR="$(cd "$OUTPUT_DIR" && pwd -P)"
INITIAL_GIT_STATUS="$(git -C "$REPOSITORY" status --porcelain --untracked-files=all)"
TEMP_BASE="${RUNNER_TEMP:-${TMPDIR:-/tmp}}"
TEMP_ROOT="$(mktemp -d "$TEMP_BASE/Pridge-Client-Linux.XXXXXX")"
LOG_PATH="$OUTPUT_DIR/build-linux-$VARIANT.log"

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
exec > >(tee "$LOG_PATH") 2>&1

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
    python3 "$REPOSITORY/scripts/prepare_build.py" \
        --work-dir "$TEMP_ROOT/context-$build_variant" \
        --variant "$build_variant" \
        --arch x86_64
}

test_gui() {
    local executable="$1"
    local smoke_home="$TEMP_ROOT/gui-smoke-$(date +%s%N)"
    mkdir -p "$smoke_home"
    if [[ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ]]; then
        HOME="$smoke_home" timeout 45s "$executable" --gui-smoke-test
    elif command -v xvfb-run >/dev/null 2>&1; then
        HOME="$smoke_home" timeout 45s xvfb-run -a "$executable" --gui-smoke-test
    else
        echo "A desktop display or xvfb-run is required for the packaged GUI smoke test." >&2
        exit 1
    fi
}

add_legal_files() {
    local distribution="$1"
    cp "$REPOSITORY/LICENSE" "$distribution/LICENSE"
    cp "$REPOSITORY/ADDITIONAL_TERMS.md" "$distribution/ADDITIONAL_TERMS.md"
}

create_archive() {
    local distribution="$1"
    local context="$2"
    local package_name
    package_name="$(context_value "$context" linux_package)"
    local stage="$TEMP_ROOT/archive-$(context_value "$context" variant)"
    mkdir -p "$stage/Pridge Client"
    cp -R "$distribution/." "$stage/Pridge Client/"
    tar -C "$stage" -czf "$OUTPUT_DIR/$package_name" "Pridge Client"
}

validate_distribution() {
    local distribution="$1"
    local context="$2"
    local executable="$distribution/$(context_value "$context" executable_name)"
    [[ -x "$executable" ]] || { echo "Packaged executable was not created." >&2; exit 1; }
    add_legal_files "$distribution"
    "$executable" --version
    test_gui "$executable"
    create_archive "$distribution" "$context"
}

build_native() {
    local context
    context="$(prepare_context Native)"
    local compile_root="$TEMP_ROOT/native"
    mkdir -p "$compile_root"
    python3 -m nuitka \
        --standalone \
        --assume-yes-for-downloads \
        --output-dir="$compile_root" \
        --output-filename="$(context_value "$context" executable_name)" \
        --enable-plugin=pyqt6 \
        --include-data-dir="$REPOSITORY/src/printbridge_client/webui=printbridge_client/webui" \
        --include-data-files="$REPOSITORY/LICENSE=LICENSE" \
        --include-data-files="$REPOSITORY/ADDITIONAL_TERMS.md=ADDITIONAL_TERMS.md" \
        --include-data-files="$(context_value "$context" metadata)=printbridge_client/_build.json" \
        --include-package-data=webview \
        --include-module=webview.platforms.qt \
        --include-package=qtpy \
        --include-package=keyring \
        --include-module=pystray._xorg \
        --nofollow-import-to=PIL.ImageTk \
        --nofollow-import-to=PIL._tkinter_finder \
        --nofollow-import-to=tkinter \
        --nofollow-import-to=_tkinter \
        --report="$OUTPUT_DIR/native-linux-x86_64-compilation-report.xml" \
        "$REPOSITORY/src/printbridge_client/__main__.py"
    local distribution
    distribution="$(find "$compile_root" -maxdepth 2 -type d -name '*.dist' -print -quit)"
    [[ -n "$distribution" ]] || { echo "Could not find the Nuitka standalone directory." >&2; exit 1; }
    validate_distribution "$distribution" "$context"
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
    local distribution="$compile_root/dist/Pridge Client"
    [[ -d "$distribution" ]] || { echo "Could not find the PyInstaller onedir application." >&2; exit 1; }
    validate_distribution "$distribution" "$context"
}

if [[ "$VARIANT" == "native" || "$VARIANT" == "all" ]]; then build_native; fi
if [[ "$VARIANT" == "pyinstaller" || "$VARIANT" == "all" ]]; then build_pyinstaller; fi
python3 "$REPOSITORY/scripts/generate_release_notes.py" --output-dir "$OUTPUT_DIR"
python3 "$REPOSITORY/scripts/generate_checksums.py" --output-dir "$OUTPUT_DIR"
