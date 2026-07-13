# SPDX-FileCopyrightText: 2026 Sayeh Ava Pazouki
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileComment: Additional terms apply; see ADDITIONAL_TERMS.md.

[CmdletBinding()]
param(
    [ValidateSet("Native", "PyInstaller", "All")]
    [string]$Variant = "All",
    [string]$OutputDir = ""
)

$ErrorActionPreference = "Stop"
$Repository = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$InitialGitStatus = (& git -C $Repository status --porcelain --untracked-files=all) -join "`n"

if (-not $OutputDir) {
    $OutputDir = $env:PRINTBRIDGE_RELEASE_DIR
}
if (-not $OutputDir) {
    $OutputDir = Join-Path $Repository "build"
}
$OutputDir = [IO.Path]::GetFullPath($OutputDir)
New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null

$TemporaryBase = if ($env:RUNNER_TEMP) { $env:RUNNER_TEMP } else { [IO.Path]::GetTempPath() }
$TemporaryRoot = Join-Path $TemporaryBase ("PrintBridge-Client-Windows-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $TemporaryRoot -Force | Out-Null
$LogPath = Join-Path $OutputDir ("build-windows-{0}.log" -f $Variant.ToLowerInvariant())
$TranscriptStarted = $false

function Get-InnoCompiler {
    $Command = Get-Command ISCC.exe -ErrorAction SilentlyContinue
    if ($Command) { return $Command.Source }
    $Candidates = @(
        (Join-Path ${env:ProgramFiles(x86)} "Inno Setup 6\ISCC.exe"),
        (Join-Path $env:ProgramFiles "Inno Setup 6\ISCC.exe")
    )
    foreach ($Candidate in $Candidates) {
        if ($Candidate -and (Test-Path $Candidate)) { return $Candidate }
    }
    throw "Inno Setup 6 (ISCC.exe) is required."
}

function Invoke-CheckedCommand {
    param([string]$Command, [string[]]$Arguments)
    & $Command @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$Command failed with exit code $LASTEXITCODE."
    }
}

function Invoke-CodeSign {
    param([string]$Path)
    if (-not $env:PRINTBRIDGE_WINDOWS_CERTIFICATE_BASE64) { return }
    if (-not $env:PRINTBRIDGE_WINDOWS_CERTIFICATE_PASSWORD) {
        throw "PRINTBRIDGE_WINDOWS_CERTIFICATE_PASSWORD is required when Windows signing is enabled."
    }
    $SignTool = (Get-Command signtool.exe -ErrorAction Stop).Source
    $Certificate = Join-Path $TemporaryRoot "windows-signing-certificate.pfx"
    [IO.File]::WriteAllBytes($Certificate, [Convert]::FromBase64String($env:PRINTBRIDGE_WINDOWS_CERTIFICATE_BASE64))
    $TimestampUrl = if ($env:PRINTBRIDGE_WINDOWS_TIMESTAMP_URL) { $env:PRINTBRIDGE_WINDOWS_TIMESTAMP_URL } else { "http://timestamp.digicert.com" }
    Invoke-CheckedCommand $SignTool @(
        "sign", "/fd", "SHA256", "/td", "SHA256", "/tr", $TimestampUrl,
        "/f", $Certificate, "/p", $env:PRINTBRIDGE_WINDOWS_CERTIFICATE_PASSWORD, $Path
    )
}

function New-BuildContext {
    param([string]$BuildVariant)
    $ContextDir = Join-Path $TemporaryRoot ("context-" + $BuildVariant)
    $ContextPath = & python (Join-Path $Repository "scripts\prepare_build.py") --work-dir $ContextDir --variant $BuildVariant --arch x64
    if ($LASTEXITCODE -ne 0) { throw "Could not prepare build metadata." }
    return Get-Content -Raw $ContextPath | ConvertFrom-Json
}

function Add-LegalFiles {
    param([string]$Distribution)
    Copy-Item (Join-Path $Repository "LICENSE") (Join-Path $Distribution "LICENSE") -Force
    Copy-Item (Join-Path $Repository "ADDITIONAL_TERMS.md") (Join-Path $Distribution "ADDITIONAL_TERMS.md") -Force
}

function Test-FrozenExecutable {
    param([string]$Executable)
    $Process = Start-Process -FilePath $Executable -ArgumentList "--version" -Wait -PassThru
    if ($Process.ExitCode -ne 0) {
        throw "Packaged executable smoke test failed with exit code $($Process.ExitCode)."
    }
}

function New-PortableArchive {
    param([string]$Distribution, [string]$Destination)
    $PortableRoot = Join-Path $TemporaryRoot ("portable-" + [guid]::NewGuid().ToString("N"))
    $PortableApp = Join-Path $PortableRoot "PrintBridge Client"
    New-Item -ItemType Directory -Path $PortableApp -Force | Out-Null
    Copy-Item (Join-Path $Distribution "*") $PortableApp -Recurse -Force
    if (Test-Path $Destination) { Remove-Item $Destination -Force }
    Compress-Archive -Path $PortableApp -DestinationPath $Destination -CompressionLevel Optimal
}

function New-Installer {
    param([object]$Context, [string]$Distribution, [string]$InstallerName, [string]$Bootstrapper)
    $Compiler = Get-InnoCompiler
    $OutputBase = [IO.Path]::GetFileNameWithoutExtension($InstallerName)
    Invoke-CheckedCommand $Compiler @(
        "/DAppVersion=$($Context.version)",
        "/DSourceDir=$Distribution",
        "/DOutputDir=$OutputDir",
        "/DOutputBaseFilename=$OutputBase",
        "/DIconFile=$($Context.icon_ico)",
        "/DLicenseFile=$(Join-Path $Repository 'LICENSE')",
        "/DWebView2Bootstrapper=$Bootstrapper",
        (Join-Path $Repository "packaging\windows\PrintBridge-Client.iss")
    )
    $InstallerPath = Join-Path $OutputDir $InstallerName
    if (-not (Test-Path $InstallerPath)) { throw "Inno Setup did not create $InstallerName." }
    Invoke-CodeSign $InstallerPath
}

function Build-Native {
    param([string]$Bootstrapper)
    $Context = New-BuildContext "Native"
    $CompileRoot = Join-Path $TemporaryRoot "nuitka"
    New-Item -ItemType Directory -Path $CompileRoot -Force | Out-Null
    $Arguments = @(
        "-m", "nuitka", "--standalone", "--assume-yes-for-downloads", "--msvc=latest",
        "--windows-console-mode=disable", "--output-dir=$CompileRoot",
        "--output-filename=$($Context.executable_name).exe",
        "--windows-icon-from-ico=$($Context.icon_ico)",
        "--company-name=$($Context.company_name)", "--product-name=$($Context.app_name)",
        "--file-description=$($Context.description)", "--copyright=$($Context.copyright)",
        "--file-version=$($Context.numeric_file_version)", "--product-version=$($Context.numeric_file_version)",
        "--include-data-dir=$(Join-Path $Repository 'src\printbridge_client\webui')=printbridge_client/webui",
        "--include-data-files=$(Join-Path $Repository 'LICENSE')=LICENSE",
        "--include-data-files=$(Join-Path $Repository 'ADDITIONAL_TERMS.md')=ADDITIONAL_TERMS.md",
        "--include-data-files=$($Context.metadata)=printbridge_client/_build.json",
        "--include-package=webview", "--include-package-data=webview",
        "--include-package=pystray", "--include-package=PIL", "--include-package=keyring",
        "--include-package=clr_loader", "--include-module=clr", "--include-package=win32com",
        "--report=$(Join-Path $OutputDir 'native-windows-compilation-report.xml')",
        (Join-Path $Repository "src\printbridge_client\__main__.py")
    )
    Invoke-CheckedCommand python $Arguments
    $Distribution = Get-ChildItem $CompileRoot -Directory -Recurse | Where-Object {
        $_.Name.EndsWith(".dist") -and (Test-Path (Join-Path $_.FullName "$($Context.executable_name).exe"))
    } | Select-Object -First 1
    if (-not $Distribution) { throw "Could not find the Nuitka standalone directory." }
    Add-LegalFiles $Distribution.FullName
    $Executable = Join-Path $Distribution.FullName "$($Context.executable_name).exe"
    Test-FrozenExecutable $Executable
    Invoke-CodeSign $Executable
    New-PortableArchive $Distribution.FullName (Join-Path $OutputDir $Context.windows_packages[1])
    New-Installer $Context $Distribution.FullName $Context.windows_packages[0] $Bootstrapper
}

function Build-PyInstaller {
    param([string]$Bootstrapper)
    $Context = New-BuildContext "PyInstaller"
    $CompileRoot = Join-Path $TemporaryRoot "pyinstaller"
    $env:PRINTBRIDGE_BUILD_CONTEXT = Join-Path (Split-Path $Context.metadata -Parent) "build-context.json"
    Invoke-CheckedCommand python @(
        "-m", "PyInstaller", "--noconfirm", "--clean",
        "--distpath", (Join-Path $CompileRoot "dist"),
        "--workpath", (Join-Path $CompileRoot "work"),
        (Join-Path $Repository "packaging\pyinstaller\PrintBridge-Client.spec")
    )
    $Distribution = Join-Path $CompileRoot "dist\PrintBridge Client"
    $Executable = Join-Path $Distribution "$($Context.executable_name).exe"
    if (-not (Test-Path $Executable)) { throw "Could not find the PyInstaller onedir executable." }
    Add-LegalFiles $Distribution
    Test-FrozenExecutable $Executable
    Invoke-CodeSign $Executable
    New-PortableArchive $Distribution (Join-Path $OutputDir $Context.windows_packages[1])
    New-Installer $Context $Distribution $Context.windows_packages[0] $Bootstrapper
}

try {
    Start-Transcript -Path $LogPath -Force | Out-Null
    $TranscriptStarted = $true
    if (-not (Get-Command python -ErrorAction SilentlyContinue)) { throw "Python is required on the build machine." }
    $env:PYTHONPATH = Join-Path $Repository "src"
    $env:PYINSTALLER_CONFIG_DIR = Join-Path $TemporaryRoot "pyinstaller-config"
    $env:PYTHONPYCACHEPREFIX = Join-Path $TemporaryRoot "python-cache"
    $env:NUITKA_CACHE_DIR = Join-Path $TemporaryRoot "nuitka-cache"
    $env:CCACHE_DIR = Join-Path $TemporaryRoot "ccache"
    $Bootstrapper = Join-Path $TemporaryRoot "MicrosoftEdgeWebview2Setup.exe"
    Invoke-WebRequest -Uri "https://go.microsoft.com/fwlink/p/?LinkId=2124703" -OutFile $Bootstrapper
    if ($Variant -in @("Native", "All")) { Build-Native $Bootstrapper }
    if ($Variant -in @("PyInstaller", "All")) { Build-PyInstaller $Bootstrapper }
    $env:PRINTBRIDGE_RELEASE_DIR = $OutputDir
    Invoke-CheckedCommand python @((Join-Path $Repository "scripts\generate_release_notes.py"), "--output-dir", $OutputDir)
    Invoke-CheckedCommand python @((Join-Path $Repository "scripts\generate_checksums.py"), "--output-dir", $OutputDir)
}
finally {
    if ($TranscriptStarted) { Stop-Transcript | Out-Null }
    if (Test-Path $TemporaryRoot) { Remove-Item $TemporaryRoot -Recurse -Force }
    $FinalGitStatus = (& git -C $Repository status --porcelain --untracked-files=all) -join "`n"
    if ($FinalGitStatus -ne $InitialGitStatus) {
        throw "The build changed the source repository.`n$FinalGitStatus"
    }
}
