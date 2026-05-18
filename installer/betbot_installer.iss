[Setup]
AppName=BetBot
AppVersion=1.0.3
AppPublisher=teoxtrm
AppSupportURL=https://github.com/teoxtrm/bet-bot
DefaultDirName={autopf}\BetBot
DefaultGroupName=BetBot
OutputDir=.
OutputBaseFilename=BetBot_Setup_v1.0.3
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional icons:"

[Files]
Source: "..\dist\BetBot\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\BetBot"; Filename: "{app}\BetBot.exe"; WorkingDir: "{app}"
Name: "{group}\Uninstall BetBot"; Filename: "{uninstallexe}"
Name: "{autodesktop}\BetBot"; Filename: "{app}\BetBot.exe"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\BetBot.exe"; Description: "&Launch BetBot now"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}\data"
