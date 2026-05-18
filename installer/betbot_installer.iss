[Setup]
AppName=BetBot
AppVersion=1.0.6
AppPublisher=teoxtrm
AppSupportURL=https://github.com/teoxtrm/bet-bot
DefaultDirName={autopf}\BetBot
DefaultGroupName=BetBot
OutputDir=.
OutputBaseFilename=BetBot_Setup_v1.0.6
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
UninstallDisplayName=BetBot

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
Type: filesandordirs; Name: "{app}\__pycache__"
Type: filesandordirs; Name: "{app}\app\__pycache__"
Type: filesandordirs; Name: "{app}\app\models\__pycache__"
Type: filesandordirs; Name: "{app}\app\scrapers\__pycache__"
Type: filesandordirs; Name: "{app}\app\utils\__pycache__"
Type: dirifempty; Name: "{app}"

[Code]
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  EnvPath: String;
  BackupPath: String;
begin
  if CurUninstallStep = usUninstall then
  begin
    EnvPath := ExpandConstant('{app}\.env');
    if FileExists(EnvPath) then
    begin
      if MsgBox(
        'BetBot found your saved API keys (.env).' + #13#10 + #13#10 +
        'Do you want to KEEP them?' + #13#10 +
        '(Useful if you plan to reinstall - the setup wizard will be skipped)',
        mbConfirmation, MB_YESNO) = IDYES then
      begin
        // Keep - do nothing
      end
      else
      begin
        if MsgBox(
          'Do you want to EXPORT your keys to the Desktop first?' + #13#10 +
          '(Saves them as BetBot_keys_backup.txt before deleting)',
          mbConfirmation, MB_YESNO) = IDYES then
        begin
          BackupPath := ExpandConstant('{userdesktop}\BetBot_keys_backup.txt');
          FileCopy(EnvPath, BackupPath, False);
          MsgBox('Keys exported to:' + #13#10 + BackupPath, mbInformation, MB_OK);
        end;
        DeleteFile(EnvPath);
      end;
    end;
  end;
end;
