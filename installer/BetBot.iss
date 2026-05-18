; BetBot Inno Setup Script
; Creates a per-user installer — no UAC prompt required.
; Installs to %LOCALAPPDATA%\BetBot\
;
; Requirements:
;   - Run "pyinstaller bet-bot.spec" first to produce dist\BetBot\
;   - Download Inno Setup 6 from https://jrsoftware.org/isdl.php
;   - Open this file in Inno Setup and click Compile (or run iscc BetBot.iss)

#define AppName     "BetBot"
#define AppVersion  "1.0.0"
#define AppPublisher "BetBot"
#define AppExeName  "BetBot.exe"
#define SourceDir   "..\dist\BetBot"

[Setup]
AppId={{A3F2B1C4-7E8D-4F9A-B2C3-D4E5F6A7B8C9}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
AppContact=support@betbot.app
DefaultDirName={localappdata}\{#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist\installer
OutputBaseFilename=BetBot-Setup-v{#AppVersion}
SetupIconFile=..\assets\icon.ico
WizardStyle=modern
Compression=lzma2/ultra64
SolidCompression=yes
DisableWelcomePage=no
WizardSmallImageFile=..\assets\wizard_small.bmp
; Require Windows 10 or later
MinVersion=10.0

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional icons:"
Name: "startmenuicon"; Description: "Create a &Start Menu shortcut"; GroupDescription: "Additional icons:"; Flags: checked

[Files]
; All files from PyInstaller output
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
; Desktop shortcut
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; \
      IconFilename: "{app}\{#AppExeName}"; Tasks: desktopicon

; Start Menu shortcut
Name: "{autoprograms}\{#AppName}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: startmenuicon
Name: "{autoprograms}\{#AppName}\Uninstall {#AppName}"; Filename: "{uninstallexe}"

[Run]
; Offer to launch after install
Filename: "{app}\{#AppExeName}"; Description: "Launch {#AppName}"; \
          Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Remove user data folder on uninstall (optional — comment out to keep data)
; Type: filesandordirs; Name: "{app}\data"

[Code]
// Show a "What's new" message on first install
procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then begin
    // Nothing extra needed — app handles first-run setup wizard
  end;
end;
