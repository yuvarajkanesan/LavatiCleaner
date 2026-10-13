; Inno Setup script - run build.bat first (it produces dist\LavatiCleaner\).
#define AppName "Lavati Cleaner"
#define AppVersion "1.0"
#define AppExe "LavatiCleaner.exe"

[Setup]
AppId={{3B1D7E52-91A4-4F0C-8C63-5E2A7D9B4C10}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=Lavati Softwares
AppCopyright=Copyright (C) Lavati Softwares
VersionInfoCompany=Lavati Softwares
VersionInfoDescription=Lavati Cleaner Setup
VersionInfoProductName=Lavati Cleaner
VersionInfoVersion={#AppVersion}
WizardSizePercent=115
DisableProgramGroupPage=yes
AllowNoIcons=yes
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
SetupIconFile=assets\lavati.ico
OutputDir=dist
OutputBaseFilename=LavatiCleaner-Setup
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
WizardImageFile=installer\wizard-large.bmp
WizardSmallImageFile=installer\wizard-small.bmp
LicenseFile=LICENSE.txt
InfoBeforeFile=installer\welcome.txt
DisableWelcomePage=no
DisableReadyPage=no
ShowLanguageDialog=no
SetupMutex=LavatiCleanerSetupMutex
CloseApplications=yes
RestartApplications=no
UsePreviousAppDir=yes
DirExistsWarning=no
UsePreviousTasks=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesInstallIn64BitMode=x64compatible

[Messages]
WelcomeLabel1=Welcome to Lavati Cleaner
WelcomeLabel2=This will install Lavati Cleaner {#AppVersion} on your computer.%n%nIt is recommended that you close other applications before continuing.
FinishedHeadingLabel=Lavati Cleaner is ready
FinishedLabel=Setup has finished installing Lavati Cleaner. Start it from the Start menu or the desktop shortcut. Your first clean starts as a dry run, so nothing is removed until you choose.

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Shortcuts:"

[Files]
Source: "dist\LavatiCleaner\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion
Source: "LICENSE.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "PRIVACY.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "SECURITY.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "THIRD_PARTY_NOTICES.txt"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[InstallDelete]
; a clean update: remove files of the previous version that the new one no longer ships
Type: filesandordirs; Name: "{app}\_internal"

[UninstallDelete]
Type: filesandordirs; Name: "{app}\_internal"

[Run]
Filename: "{app}\{#AppExe}"; Description: "Launch {#AppName}"; Flags: nowait postinstall skipifsilent

[Code]
var
  KeepData: Boolean;

procedure DeleteTree(const Path: String);
begin
  if DirExists(Path) then DelTree(Path, True, True, True);
end;

function HasParam(const Name: String): Boolean;
var
  i: Integer;
begin
  Result := False;
  for i := 1 to ParamCount do
    if CompareText(ParamStr(i), Name) = 0 then Result := True;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Code: Integer;
begin
  if CurUninstallStep = usUninstall then
    { a running copy keeps its files locked, which would leave the folder behind }
    Exec(ExpandConstant('{sys}\taskkill.exe'), '/F /IM {#AppExe}', '', SW_HIDE, ewWaitUntilTerminated, Code);
  if CurUninstallStep = usPostUninstall then
  begin
    if not KeepData then
    begin
      { settings, history and the quarantine (files waiting for their 7 days are gone for good) }
      DeleteTree(ExpandConstant('{localappdata}\LavatiCleaner'));
    end;
    { the uninstaller lives inside the install folder, so remove it a moment after it exits;
      rmdir without /s only removes the folder when empty, so a shared folder is never wiped }
    Exec(ExpandConstant('{cmd}'), '/c ping 127.0.0.1 -n 3 >nul & del /q "' + ExpandConstant('{app}') + '\unins*.*" & rmdir "' + ExpandConstant('{app}') + '"', '', SW_HIDE, ewNoWait, Code);
  end;
end;

{ close a running copy before an update or uninstall touches its files }
function InitializeUninstall(): Boolean;
var
  Code: Integer;
begin
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/F /IM {#AppExe}', '', SW_HIDE, ewWaitUntilTerminated, Code);
  { silent uninstalls wipe everything unless started with /KEEPDATA; interactive ones ask (default: keep) }
  if UninstallSilent then
    KeepData := HasParam('/KEEPDATA')
  else
    KeepData := MsgBox('Keep your history, settings and quarantined files?' + #13#10 + #13#10 +
      'Choose Yes to keep them for a future install (you can still restore quarantined files then), or No to ' +
      'remove all Lavati Cleaner data. Quarantined files will be deleted permanently.',
      mbConfirmation, MB_YESNO) = IDYES;
  Result := True;
end;

const
  UninstKey = 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{3B1D7E52-91A4-4F0C-8C63-5E2A7D9B4C10}_is1';

{ If a copy is already installed (per-user or all-users), say so and ask before upgrading it. }
function InitializeSetup(): Boolean;
var
  Ver, Msg: String;
begin
  Result := True;
  Ver := '';
  if not RegQueryStringValue(HKCU, UninstKey, 'DisplayVersion', Ver) then
    if not RegQueryStringValue(HKLM, UninstKey, 'DisplayVersion', Ver) then
      Ver := '';
  if (Ver <> '') and not WizardSilent then
  begin
    if CompareText(Ver, '{#AppVersion}') = 0 then
      Msg := '{#AppName} ' + Ver + ' is already installed on this computer.' + #13#10 + #13#10 +
             'Reinstall it? Your settings and history are kept.'
    else
      Msg := '{#AppName} ' + Ver + ' is already installed on this computer.' + #13#10 + #13#10 +
             'Upgrade it to version {#AppVersion}? Your settings and history are kept.';
    Result := MsgBox(Msg, mbConfirmation, MB_YESNO) = IDYES;
  end;
end;
