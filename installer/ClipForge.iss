#ifndef AppVersion
  #define AppVersion "1.3.0"
#endif
#ifndef AppExe
  #define AppExe "..\dist\ClipForge.exe"
#endif
[Setup]
AppId={{D55FBE93-2E0D-48BC-999B-85D619AE80E5}
AppName=ClipForge
AppVersion={#AppVersion}
AppPublisher=hichamhr.com
AppPublisherURL=https://hichamhr.com
DefaultDirName={localappdata}\Programs\ClipForge
DefaultGroupName=ClipForge
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist\installer
OutputBaseFilename=ClipForge-Setup-{#AppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\ClipForge.exe
CloseApplications=yes

[Tasks]
Name: desktopicon; Description: "Create a desktop shortcut"; Flags: unchecked

[Files]
Source: "{#AppExe}"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\ClipForge"; Filename: "{app}\ClipForge.exe"
Name: "{autodesktop}\ClipForge"; Filename: "{app}\ClipForge.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\ClipForge.exe"; Description: "Open ClipForge"; Flags: nowait postinstall skipifsilent

; Settings, recordings and the outbox are deliberately preserved on uninstall.
