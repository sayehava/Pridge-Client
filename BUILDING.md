# Building Pridge Client Releases

Pridge Client has two independent desktop release targets:

- **Native** uses Nuitka standalone compilation.
- **PyInstaller** uses PyInstaller onedir application bundles.

Neither target uses onefile mode. Both include Python, application dependencies, pywebview runtime files, frontend HTML/CSS/JavaScript, icons, assets, `LICENSE`, and `ADDITIONAL_TERMS.md`. A destination computer does not need Python, pip, or installed Python packages.

The About window identifies the running package:

```text
Build variant: Native
Build system: Nuitka
```

or:

```text
Build variant: PyInstaller
Build system: PyInstaller
```

## Output and temporary directories

Local builds write final packages, checksums, release notes, compiler reports, and logs to the repository's `build` directory by default on Windows, macOS, and Linux. The directory is present in a fresh checkout and is created automatically if it is missing. Generated files inside it are ignored by Git; [build/README.md](build/README.md) remains tracked to explain its purpose.

To choose another location interactively, use the platform folder selector:

Windows PowerShell:

```powershell
./scripts/build-windows.ps1 -Variant All -SelectOutputDir
```

macOS:

```bash
bash scripts/build-macos.sh All --select-output-dir
```

Linux has no graphical build-output selector. Pass `--output-dir` or set `PRINTBRIDGE_RELEASE_DIR`.

The selector opens before compilation begins. Cancelling it stops the build without producing packages. For automated or repeatable builds, set `PRINTBRIDGE_RELEASE_DIR` or pass an explicit output path instead.

Windows PowerShell:

```powershell
$env:PRINTBRIDGE_RELEASE_DIR = "D:\Pridge Builds"
```

macOS:

```bash
export PRINTBRIDGE_RELEASE_DIR="$HOME/Pridge Builds"
```

All intermediate compiler output, PyInstaller work/dist files, Nuitka output, Python bytecode, compiler caches, installer staging, signing credentials, and DMG staging use a unique operating-system temporary directory. The build scripts delete their temporary directory on exit and fail if tracked or non-ignored repository state changes during a build. Only final release files and build logs are copied into `build`.

GitHub Actions uses `${{ runner.temp }}` for compilation and staging, then collects final packages in `${{ github.workspace }}/build`. Only selected final packages and diagnostic logs are uploaded as workflow artifacts.

## Shared prerequisites

Use a native CPython 3.12 installation for the build machine. Python is a build-time dependency only.

Create the virtual environment outside the repository. Install the build tools from [requirements-release.txt](requirements-release.txt) and install Pridge Client with the platform extras.

Do not build from a general-purpose Python environment containing unrelated GUI frameworks. Pywebview discovers installed renderers dynamically, so a clean release environment keeps each package reliable and small.

Release environments use pywebview `6.2.1`. Windows pins pythonnet `3.0.5` and explicitly bundles the WinForms, Edge Chromium, CLR, and WebView2 interop components. Linux uses the Qt 6 WebEngine renderer. These versions and backends are deliberate release inputs; update them only with packaged GUI smoke tests on every platform.

## Windows prerequisites

Windows x64 builds require:

- Windows 10 or Windows 11 x64
- native CPython 3.12 x64
- Visual Studio 2022 Build Tools with the Desktop development with C++ workload
- Inno Setup 6
- internet access while building, to retrieve the official Microsoft WebView2 Evergreen bootstrapper
- Windows SDK `signtool.exe` only when code signing is enabled

Prepare an external virtual environment from PowerShell:

```powershell
py -3.12 -m venv "$env:TEMP\printbridge-release-venv"
& "$env:TEMP\printbridge-release-venv\Scripts\Activate.ps1"
python -m pip install --upgrade pip
python -m pip install -r requirements-release.txt -e ".[windows,secure,tray]"
python -B -m unittest discover -s tests
```

### Windows Native build

```powershell
./scripts/build-windows.ps1 -Variant Native
```

This command uses Nuitka `--standalone` and disables the console window. It creates:

- `Pridge-Client-Native-Setup-x64.exe`
- `Pridge-Client-Native-Windows-x64-Portable.zip`

### Windows PyInstaller build

```powershell
./scripts/build-windows.ps1 -Variant PyInstaller
```

This command uses the reusable [Pridge-Client.spec](packaging/pyinstaller/Pridge-Client.spec), onedir mode, and a windowed executable. It creates:

- `Pridge-Client-PyInstaller-Setup-x64.exe`
- `Pridge-Client-PyInstaller-Windows-x64-Portable.zip`

### Build all Windows variants

```powershell
./scripts/build-windows.ps1 -Variant All
```

To provide an explicit output directory for one command:

```powershell
./scripts/build-windows.ps1 -Variant All -OutputDir "D:\Pridge Builds"
```

Both setup packages use the shared Inno Setup definition at [Pridge-Client.iss](packaging/windows/Pridge-Client.iss). The installer checks Microsoft's WebView2 Runtime `pv` registry value for both per-machine and per-user installations. It runs the embedded official Evergreen bootstrapper with `/silent /install` only when a valid runtime is missing. The portable packages require the Microsoft WebView2 Runtime already provided by or installed on Windows; they never require Python.

Each Windows build also runs the packaged executable with its private GUI smoke mode. A build succeeds only when WebView2 renders the frontend, React obtains state through the Python bridge, and the application closes cleanly with exit code zero.

## macOS prerequisites

Each macOS architecture must be built natively on matching hardware:

- Apple silicon for `arm64`
- Intel macOS for `x86_64`

Required tools:

- native CPython 3.12 from python.org, Homebrew, or GitHub Actions
- Xcode Command Line Tools (`xcode-select --install`)
- `hdiutil`, `codesign`, `xcrun`, and `SetFile`

Do not use Apple's `/usr/bin/python3` for Nuitka standalone releases. Nuitka identifies it as Apple Python and does not support it as a distributable standalone runtime.

Prepare an external virtual environment:

```bash
python3.12 -m venv /tmp/printbridge-release-venv
source /tmp/printbridge-release-venv/bin/activate
python3 -m pip install --upgrade pip
python3 -m pip install -r requirements-release.txt -e ".[secure,tray]"
python3 -B -m unittest discover -s tests
```

### macOS Native build

```bash
bash scripts/build-macos.sh Native
```

This command uses Nuitka standalone mode to create a native `.app`, applies application metadata and icons, signs the bundle, and places it in a compressed DMG. The filename is selected from the current native architecture:

- `Pridge-Client-Native-macOS-arm64.dmg`
- `Pridge-Client-Native-macOS-x86_64.dmg`

### macOS PyInstaller build

```bash
bash scripts/build-macos.sh PyInstaller
```

This command uses the reusable PyInstaller spec to create a windowed onedir `.app`, applies application metadata and icons, signs the bundle, and places it in a compressed DMG. The filename is selected from the current native architecture:

- `Pridge-Client-PyInstaller-macOS-arm64.dmg`
- `Pridge-Client-PyInstaller-macOS-x86_64.dmg`

### Build all macOS variants for the current architecture

```bash
bash scripts/build-macos.sh All
```

To provide an explicit output directory for one command:

```bash
bash scripts/build-macos.sh All --output-dir "$HOME/Pridge Builds"
```

The DMG contains the `.app`, an `/Applications` shortcut, the GPL license, and the additional attribution terms. A custom volume icon, application name, version, identifier, author, copyright, description, build variant, and build system are embedded during packaging.

Each macOS build and mounted-DMG validation runs the same rendered-GUI smoke mode against the packaged executable.

## Linux desktop prerequisites

Linux x86_64 releases use Qt 6 and Qt WebEngine so the packaged renderer is deterministic and does not depend on a distribution-provided GTK WebKit version. Build on a native GNU/Linux x86_64 system with CPython 3.12, CUPS development headers, and the X11/Qt runtime libraries required by Qt WebEngine.

On Ubuntu 24.04, prepare the system packages with:

```bash
sudo apt-get update
sudo apt-get install --yes libcups2-dev libegl1 libgbm1 libgl1 libnss3 \
  libxcomposite1 libxdamage1 libxkbcommon-x11-0 libxrandr2 \
  libxcb-cursor0 xauth xvfb
```

Prepare an external virtual environment:

```bash
python3.12 -m venv /tmp/pridge-release-venv
source /tmp/pridge-release-venv/bin/activate
python3 -m pip install --upgrade pip
python3 -m pip install -r requirements-release.txt -e ".[linux,secure,tray]"
python3 -B -m unittest discover -s tests
```

Build either package or both:

```bash
bash scripts/build-linux.sh Native
bash scripts/build-linux.sh PyInstaller
bash scripts/build-linux.sh All --output-dir "$HOME/Pridge Builds"
```

The outputs are:

- `Pridge-Client-Native-Linux-x86_64.tar.gz`
- `Pridge-Client-PyInstaller-Linux-x86_64.tar.gz`

The build runs the packaged frontend under the current desktop display or `xvfb-run`. It fails if the Qt window, React application, or Python bridge does not become ready.

## Optional Windows code signing

Windows signing is disabled when signing variables are absent. To sign the primary executables and setup packages, set:

```text
PRINTBRIDGE_WINDOWS_CERTIFICATE_BASE64
PRINTBRIDGE_WINDOWS_CERTIFICATE_PASSWORD
PRINTBRIDGE_WINDOWS_TIMESTAMP_URL (optional)
```

The certificate value is a Base64-encoded PFX/PKCS#12 file. The timestamp URL defaults to DigiCert's timestamp service.

The GitHub Actions secret names are:

```text
WINDOWS_CERTIFICATE_BASE64
WINDOWS_CERTIFICATE_PASSWORD
WINDOWS_TIMESTAMP_URL
```

## Optional macOS Developer ID signing and notarization

Without a Developer ID secret, app bundles receive an ad-hoc signature so they remain structurally valid. Trusted distribution signing is enabled with:

```text
PRINTBRIDGE_MACOS_SIGNING_IDENTITY
```

GitHub Actions imports the signing certificate from:

```text
MACOS_CERTIFICATE_BASE64
MACOS_CERTIFICATE_PASSWORD
MACOS_SIGNING_IDENTITY
```

The certificate is a Base64-encoded P12/PKCS#12 file. The identity should normally be a `Developer ID Application` identity.

Notarization is optional and runs only when credentials are present. App Store Connect API key authentication uses:

```text
NOTARY_KEY_BASE64
NOTARY_KEY_ID
NOTARY_ISSUER_ID
```

Apple ID authentication uses:

```text
NOTARY_APPLE_ID
NOTARY_TEAM_ID
NOTARY_PASSWORD
```

The corresponding local environment variables add the `PRINTBRIDGE_` prefix, for example `PRINTBRIDGE_NOTARY_KEY_ID`. A Developer ID signing identity is required before notarization. Successful notarization is stapled to the DMG.

## Native and PyInstaller package differences

The packages expose the same application behavior and resources. They differ only in the compiler/packager and internal layout:

- **Native** compiles Python modules with Nuitka and distributes a standalone directory or app bundle. User-facing package names use `Native`; package filenames never use `Nuitka`.
- **PyInstaller** freezes modules with PyInstaller and distributes an onedir directory or app bundle. It uses the maintained spec file shared by Windows, macOS, and Linux.

Keeping both targets provides an independent packaging fallback and makes runtime issues easier to isolate. Neither target currently uses onefile extraction.

## Validation and clean-system testing

Every local build performs an executable version smoke check before packaging. The GitHub workflows add clean-runner tests:

- Windows requires the packaged WebView2 GUI and JavaScript-Python bridge to become ready before either package is accepted.
- macOS runs the rendered-GUI smoke mode before creating each DMG, then repeats it from the mounted final DMG.
- Linux runs each Qt WebEngine package under Xvfb and requires the rendered GUI bridge to complete.

The frozen application is launched directly from its package. It does not use the build environment's Python interpreter or installed Python packages. Test signed production packages on the oldest supported clean Windows, macOS, and Linux versions before broad deployment, especially after changing pywebview, Python, signing, or operating-system targets.

## Release notes and checksums

Platform builds create `SHA256SUMS.txt` for every final package currently present in the output directory. The tag workflow downloads all ten packages and regenerates the canonical file with `--require-all`.

`scripts/generate_release_notes.py` creates `Pridge-Client-Release-Notes.txt` and a Markdown rendering used as the GitHub Release description. It reads non-merge commits since the previous `v*` tag, or all relevant history when no previous tag exists. It filters common dependency, formatting, merge, and generated-file noise and groups entries into features, fixes, improvements, documentation, build and packaging, and internal changes.

Manual commands:

```bash
python3 -B scripts/generate_release_notes.py --tag v1.0.0
python3 -B scripts/generate_checksums.py
```

Both commands honor `PRINTBRIDGE_RELEASE_DIR` and default to the repository's `build` directory.

## GitHub tag release process

The platform workflows can be started manually from GitHub Actions to validate packaging without publishing a release:

- `Build Windows packages`
- `Build macOS packages`
- `Build Linux packages`

To publish a release:

1. Make sure the intended application version is committed.
2. Run the test suite.
3. Create an annotated tag matching `v*`.
4. Push the tag.

Example:

```bash
git tag -a v1.0.0 -m "Release Pridge Client 1.0.0"
git push origin v1.0.0
```

The `Build and publish release` workflow calls all three platform workflows, embeds the tag version, builds eight runner jobs, verifies each package, collects final output in the checked-out repository's ignored `build` directory, generates release notes and checksums, uploads the complete set as a GitHub Actions artifact, and creates the GitHub Release. The plain-text release notes are uploaded as a release asset, and the Markdown rendering of the same content becomes the release description.

## Expected final filenames

```text
Pridge-Client-Native-Setup-x64.exe
Pridge-Client-Native-Windows-x64-Portable.zip
Pridge-Client-Native-macOS-arm64.dmg
Pridge-Client-Native-macOS-x86_64.dmg
Pridge-Client-PyInstaller-Setup-x64.exe
Pridge-Client-PyInstaller-Windows-x64-Portable.zip
Pridge-Client-PyInstaller-macOS-arm64.dmg
Pridge-Client-PyInstaller-macOS-x86_64.dmg
Pridge-Client-Native-Linux-x86_64.tar.gz
Pridge-Client-PyInstaller-Linux-x86_64.tar.gz
SHA256SUMS.txt
Pridge-Client-Release-Notes.txt
```

Every application About/Legal Notices view retains:

```text
Original author: Sayeh Ava Pazouki
Copyright © 2026 Sayeh Ava Pazouki
License: GPL-3.0-or-later
```
