; Installer di Audio Extractor — Inno Setup 6 (https://jrsoftware.org/isinfo.php)
; Non compilare a mano: lo fa build.py, che passa la versione con /DAppVersion=...

#ifndef AppVersion
  #define AppVersion "2.2.1"
#endif
#define AppName "Audio Extractor"
#define AppExe "AudioExtractor.exe"
#define AppPublisher "Cesa028"
#ifndef SrcDir
  #define SrcDir "..\build\package"
#endif

[Setup]
AppId={{5B7E2C41-9A3D-4F6B-8E21-AE7D0C3F9B12}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppCopyright=© 2026 {#AppPublisher} — Licenza MIT
VersionInfoVersion={#AppVersion}
VersionInfoDescription={#AppName} Setup
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
; installazione senza permessi di amministratore (solo per l'utente),
; con possibilità di scegliere "per tutti gli utenti"
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
LicenseFile=license-page.txt
SetupIconFile=..\build\icon.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
WizardStyle=modern
WizardSizePercent=110
Compression=lzma2/ultra64
SolidCompression=yes
CloseApplications=yes
RestartApplications=no
OutputDir=..\dist
OutputBaseFilename=AudioExtractor-Setup-{#AppVersion}

[Languages]
Name: "italian"; MessagesFile: "compiler:Languages\Italian.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "{#SrcDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Registry]
; alla disinstallazione rimuove anche le impostazioni salvate dal programma
Root: HKCU; Subkey: "Software\AudioExtractor"; Flags: uninsdeletekey dontcreatekey

[UninstallDelete]
; alla disinstallazione rimuove anche il log del programma
Type: filesandordirs; Name: "{userappdata}\AudioExtractor"

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent
