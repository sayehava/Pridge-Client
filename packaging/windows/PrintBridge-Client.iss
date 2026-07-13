; SPDX-FileCopyrightText: 2026 Sayeh Ava Pazouki
; SPDX-License-Identifier: GPL-3.0-or-later
; SPDX-FileComment: Additional terms apply; see ADDITIONAL_TERMS.md.

#ifndef AppVersion
  #error AppVersion is required
#endif
#ifndef SourceDir
  #error SourceDir is required
#endif
#ifndef OutputDir
  #error OutputDir is required
#endif
#ifndef OutputBaseFilename
  #error OutputBaseFilename is required
#endif
#ifndef IconFile
  #error IconFile is required
#endif
#ifndef LicenseFile
  #error LicenseFile is required
#endif
#ifndef WebView2Bootstrapper
  #error WebView2Bootstrapper is required
#endif

#define WebView2ClientId "{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"

[Setup]
AppId={{7DDA97B0-0C07-48E8-98A0-D11AFC8FE3B7}
AppName=PrintBridge Client
AppVersion={#AppVersion}
AppVerName=PrintBridge Client {#AppVersion}
AppPublisher=Sayeh Ava Pazouki
AppCopyright=Copyright © 2026 Sayeh Ava Pazouki
AppPublisherURL=https://github.com/sayehava/PrintBridge-Client
AppSupportURL=https://github.com/sayehava/PrintBridge-Client/issues
AppUpdatesURL=https://github.com/sayehava/PrintBridge-Client/releases
DefaultDirName={localappdata}\Programs\PrintBridge Client
DefaultGroupName=PrintBridge Client
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
SetupIconFile={#IconFile}
UninstallDisplayIcon={app}\PrintBridge Client.exe
LicenseFile={#LicenseFile}
OutputDir={#OutputDir}
OutputBaseFilename={#OutputBaseFilename}
VersionInfoVersion={#AppVersion}
VersionInfoCompany=Sayeh Ava Pazouki
VersionInfoDescription=PrintBridge Client Setup
VersionInfoCopyright=Copyright © 2026 Sayeh Ava Pazouki
VersionInfoProductName=PrintBridge Client
VersionInfoProductVersion={#AppVersion}

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#WebView2Bootstrapper}"; DestDir: "{tmp}"; DestName: "MicrosoftEdgeWebview2Setup.exe"; Flags: deleteafterinstall

[Icons]
Name: "{autoprograms}\PrintBridge Client"; Filename: "{app}\PrintBridge Client.exe"; WorkingDir: "{app}"
Name: "{autodesktop}\PrintBridge Client"; Filename: "{app}\PrintBridge Client.exe"; WorkingDir: "{app}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"

[Run]
Filename: "{tmp}\MicrosoftEdgeWebview2Setup.exe"; Parameters: "/silent /install"; StatusMsg: "Installing Microsoft WebView2 Runtime..."; Flags: waituntilterminated; Check: not WebView2RuntimeInstalled
Filename: "{app}\PrintBridge Client.exe"; Description: "Launch PrintBridge Client"; Flags: nowait postinstall skipifsilent

[Code]
function ValidWebViewVersion(const Version: String): Boolean;
begin
  Result := (Version <> '') and (Version <> '0.0.0.0');
end;

function WebView2RuntimeInstalled: Boolean;
var
  Version: String;
  MachineKey: String;
  UserKey: String;
begin
  MachineKey := 'SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\' + '{#WebView2ClientId}';
  UserKey := 'Software\Microsoft\EdgeUpdate\Clients\' + '{#WebView2ClientId}';
  Result :=
    (RegQueryStringValue(HKLM64, MachineKey, 'pv', Version) and ValidWebViewVersion(Version)) or
    (RegQueryStringValue(HKCU, UserKey, 'pv', Version) and ValidWebViewVersion(Version));
end;
