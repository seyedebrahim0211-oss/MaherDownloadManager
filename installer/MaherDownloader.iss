#define MyAppName "Maher Download Manager"
#define MyAppVersion "2.1.0"
#define MyAppExeName "MaherDownloader.exe"
[Setup]
AppId={{36C975CC-DAF1-42A7-BDCB-4675031D3900}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher=Maher Studio
DefaultDirName={localappdata}\Programs\MaherDownloader
DefaultGroupName=Maher Download Manager
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
OutputDir=..\dist\installer
OutputBaseFilename=MaherDownloader-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
SetupIconFile=..\assets\maher.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
CloseApplications=yes
RestartApplications=no
DisableProgramGroupPage=yes
[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked
[Files]
Source: "..\dist\MaherDownloader\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
[Icons]
Name: "{autoprograms}\Maher Download Manager"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\Maher Download Manager"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon
[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch Maher Download Manager"; Flags: nowait postinstall skipifsilent
