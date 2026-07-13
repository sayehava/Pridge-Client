# Building PrintBridge Client Releases

PrintBridge Client has two independent desktop release targets:

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

Local builds write final packages, checksums, release notes, compiler reports, and logs to the user's Desktop `Release` directory by default:

- Windows: `%USERPROFILE%\Desktop\Release`
- macOS: `~/Desktop/Release`

The directory is created automatically. Set `PRINTBRIDGE_RELEASE_DIR` or pass the platform script's output argument to use another location outside the repository.

Windows PowerShell:

```powershell
$env:PRINTBRIDGE_RELEASE_DIR = "D:\PrintBridge Releases"
```

macOS:

```bash
export PRINTBRIDGE_RELEASE_DIR="$HOME/PrintBridge Releases"
```

All compiler output, PyInstaller work/dist files, Nuitka output, Python bytecode, compiler caches, installer staging, signing credentials, and DMG staging use a unique operating-system temporary directory. The build scripts reject an output directory inside the source repository, delete their temporary directory on exit, and fail if `git status --porcelain` changes during a build. No `build`, `dist`, `output`, `release`, cache, or staging directory is created in the checkout.

GitHub Actions uses `${{ runner.temp }}` for compilation, staging, and final-package collection. Only selected final packages and diagnostic logs are uploaded as workflow artifacts.

## Shared prerequisites

Use a native CPython 3.12 installation for the build machine. Python is a build-time dependency only.

Create the virtual environment outside the repository. Install the build tools from [requirements-release.txt](requirements-release.txt) and install PrintBridge Client with the platform extras.

Do not build from a general-purpose Python environment containing unrelated GUI frameworks. Pywebview discovers installed renderers dynamically, so a clean release environment keeps each package reliable and small.

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
python -m unittest discover -s tests
```

### Windows Native build

```powershell
./scripts/build-windows.ps1 -Variant Native
```

This command uses Nuitka `--standalone` and disables the console window. It creates:

- `PrintBridge-Client-Native-Setup-x64.exe`
- `PrintBridge-Client-Native-Windows-x64-Portable.zip`

### Windows PyInstaller build

```powershell
./scripts/build-windows.ps1 -Variant PyInstaller
```

This command uses the reusable [PrintBridge-Client.spec](packaging/pyinstaller/PrintBridge-Client.spec), onedir mode, and a windowed executable. It creates:

- `PrintBridge-Client-PyInstaller-Setup-x64.exe`
- `PrintBridge-Client-PyInstaller-Windows-x64-Portable.zip`

### Build all Windows variants

```powershell
./scripts/build-windows.ps1 -Variant All
```

To override the output directory for one command:

```powershell
./scripts/build-windows.ps1 -Variant All -OutputDir "D:\PrintBridge Releases"
```

Both setup packages use the shared Inno Setup definition at [PrintBridge-Client.iss](packaging/windows/PrintBridge-Client.iss). The installer checks Microsoft's WebView2 Runtime `pv` registry value for both per-machine and per-user installations. It runs the embedded official Evergreen bootstrapper with `/silent /install` only when a valid runtime is missing. The portable packages require the Microsoft WebView2 Runtime already provided by or installed on Windows; they never require Python.

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
python3 -m unittest discover -s tests
```

### macOS Native build

```bash
bash scripts/build-macos.sh Native
```

This command uses Nuitka standalone mode to create a native `.app`, applies application metadata and icons, signs the bundle, and places it in a compressed DMG. The filename is selected from the current native architecture:

- `PrintBridge-Client-Native-macOS-arm64.dmg`
- `PrintBridge-Client-Native-macOS-x86_64.dmg`

### macOS PyInstaller build

```bash
bash scripts/build-macos.sh PyInstaller
```

This command uses the reusable PyInstaller spec to create a windowed onedir `.app`, applies application metadata and icons, signs the bundle, and places it in a compressed DMG. The filename is selected from the current native architecture:

- `PrintBridge-Client-PyInstaller-macOS-arm64.dmg`
- `PrintBridge-Client-PyInstaller-macOS-x86_64.dmg`

### Build all macOS variants for the current architecture

```bash
bash scripts/build-macos.sh All
```

To override the output directory for one command:

```bash
bash scripts/build-macos.sh All --output-dir "$HOME/PrintBridge Releases"
```

The DMG contains the `.app`, an `/Applications` shortcut, the GPL license, and the additional attribution terms. A custom volume icon, application name, version, identifier, author, copyright, description, build variant, and build system are embedded during packaging.

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
- **PyInstaller** freezes modules with PyInstaller and distributes an onedir directory or app bundle. It uses the maintained spec file shared by Windows and macOS.

Keeping both targets provides an independent packaging fallback and makes runtime issues easier to isolate. Neither target currently uses onefile extraction.

## Validation and clean-system testing

Every local build performs an executable version smoke check before packaging. The GitHub workflows add clean-runner tests:

- Windows expands each portable ZIP, launches the GUI, silently installs each Inno package into a temporary directory, and launches the installed GUI.
- macOS mounts each DMG read-only, verifies app metadata, architecture, code signature, frontend and legal files, and launches the GUI with a fresh temporary home directory.

The frozen application is launched directly from its package. It does not use the build environment's Python interpreter or installed Python packages. Test signed production packages on the oldest supported clean Windows and macOS versions before broad deployment, especially after changing pywebview, Python, signing, or operating-system targets.

## Release notes and checksums

Platform builds create `SHA256SUMS.txt` for every final package currently present in the output directory. The tag workflow downloads all eight packages and regenerates the canonical file with `--require-all`.

`scripts/generate_release_notes.py` creates `PrintBridge-Client-Release-Notes.txt` and a Markdown rendering used as the GitHub Release description. It reads non-merge commits since the previous `v*` tag, or all relevant history when no previous tag exists. It filters common dependency, formatting, merge, and generated-file noise and groups entries into features, fixes, improvements, documentation, build and packaging, and internal changes.

Manual commands:

```bash
python3 scripts/generate_release_notes.py --tag v1.0.0
python3 scripts/generate_checksums.py
```

Both commands honor `PRINTBRIDGE_RELEASE_DIR` and reject output inside the repository.

## GitHub tag release process

The platform workflows can be started manually from GitHub Actions to validate packaging without publishing a release:

- `Build Windows packages`
- `Build macOS packages`

To publish a release:

1. Make sure the intended application version is committed.
2. Run the test suite.
3. Create an annotated tag matching `v*`.
4. Push the tag.

Example:

```bash
git tag -a v1.0.0 -m "Release PrintBridge Client 1.0.0"
git push origin v1.0.0
```

The `Build and publish release` workflow calls both native platform workflows, embeds the tag version, builds six native runner jobs, verifies each package, collects all output in temporary runner storage, generates release notes and checksums, uploads the complete set as a GitHub Actions artifact, and creates the GitHub Release. The plain-text release notes are uploaded as a release asset, and the Markdown rendering of the same content becomes the release description.

## Expected final filenames

```text
PrintBridge-Client-Native-Setup-x64.exe
PrintBridge-Client-Native-Windows-x64-Portable.zip
PrintBridge-Client-Native-macOS-arm64.dmg
PrintBridge-Client-Native-macOS-x86_64.dmg
PrintBridge-Client-PyInstaller-Setup-x64.exe
PrintBridge-Client-PyInstaller-Windows-x64-Portable.zip
PrintBridge-Client-PyInstaller-macOS-arm64.dmg
PrintBridge-Client-PyInstaller-macOS-x86_64.dmg
SHA256SUMS.txt
PrintBridge-Client-Release-Notes.txt
```

Every application About/Legal Notices view retains:

```text
Original author: Sayeh Ava Pazouki
Copyright © 2026 Sayeh Ava Pazouki
License: GPL-3.0-or-later
```
