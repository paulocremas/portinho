; Instalador do Portinho para Windows (Inno Setup 6)
; Compile com:  iscc /DMyVersion=1.0.0 packaging\installer.iss
#ifndef MyVersion
  #define MyVersion "1.0.0"
#endif

[Setup]
AppId={{6B0C7E52-4A1E-4C55-9C3F-5D2A1C0F9A11}
AppName=Portinho
AppVersion={#MyVersion}
AppPublisher=Paulo Cremasco
DefaultDirName={autopf}\Portinho
DefaultGroupName=Portinho
DisableProgramGroupPage=yes
; instala só para o usuário atual: não pede senha de administrador
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=..\dist
OutputBaseFilename=Portinho-Setup-{#MyVersion}
SetupIconFile=..\assets\icon.ico
UninstallDisplayIcon={app}\Portinho.exe
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
WizardImageFile=..\assets\wizard.bmp
WizardSmallImageFile=..\assets\wizard_small.bmp
; fecha o Portinho aberto antes de trocar os arquivos (usado na atualização automática)
CloseApplications=force
RestartApplications=no
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "pt"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"
Name: "en"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "..\dist\Portinho\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\Portinho"; Filename: "{app}\Portinho.exe"
Name: "{group}\{cm:UninstallProgram,Portinho}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\Portinho"; Filename: "{app}\Portinho.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\Portinho.exe"; Description: "{cm:LaunchProgram,Portinho}"; Flags: nowait postinstall skipifsilent
; atualização automática (/SILENT): reabre o Portinho sozinho no final
Filename: "{app}\Portinho.exe"; Flags: nowait skipifnotsilent
