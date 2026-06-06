#define AppName "Codex History Manager"
#ifndef AppVersion
#define AppVersion "0.0.0"
#endif
#define AppPublisher "Alexd-star"
#define AppExeName "CodexHistoryManager.exe"

[Setup]
AppId={{B6B96929-423F-4F52-B099-4ED4E6622335}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL=https://github.com/Alexd-star/CodexHistoryManager
AppSupportURL=https://github.com/Alexd-star/CodexHistoryManager/issues
AppUpdatesURL=https://github.com/Alexd-star/CodexHistoryManager/releases
DefaultDirName={localappdata}\Programs\CodexHistoryManager
DefaultGroupName=Codex History Manager
DisableProgramGroupPage=yes
LicenseFile=..\LICENSE
OutputDir=..\dist
OutputBaseFilename=CodexHistoryManager-Setup-v{#AppVersion}
SetupIconFile=..\assets\codex_history_manager.ico
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\{#AppExeName}
VersionInfoVersion={#AppVersion}
VersionInfoCompany={#AppPublisher}
VersionInfoDescription=Codex local conversation history manager setup
VersionInfoProductName={#AppName}
VersionInfoProductVersion={#AppVersion}

[Languages]
Name: "chinesesimp"; MessagesFile: "languages\ChineseSimplified.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加快捷方式："; Flags: unchecked

[Files]
Source: "..\dist\{#AppExeName}"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\README.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\LICENSE"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\VERSION"; DestDir: "{app}"; Flags: ignoreversion
Source: "languages\Inno-Setup-Chinese-Simplified-Translation-LICENSE.txt"; DestDir: "{app}\licenses"; Flags: ignoreversion

[Icons]
Name: "{group}\Codex History Manager"; Filename: "{app}\{#AppExeName}"
Name: "{group}\打开用户数据目录"; Filename: "{sys}\explorer.exe"; Parameters: """{localappdata}\CodexHistoryManager"""
Name: "{group}\卸载 Codex History Manager"; Filename: "{uninstallexe}"
Name: "{autodesktop}\Codex History Manager"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExeName}"; Description: "启动 Codex History Manager"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: files; Name: "{app}\README.md"
Type: files; Name: "{app}\LICENSE"
Type: files; Name: "{app}\VERSION"
