#define ProductName "AutoTAF VABB Downloader"
#define ProductVersion "1.0.0"
#define ProductPublisher "AutoTAF"

[Setup]
AppId={{B4DDB76B-03C2-4B2C-A1A5-AE6C5D8478E3}
AppName={#ProductName}
AppVersion={#ProductVersion}
AppPublisher={#ProductPublisher}
DefaultDirName={localappdata}\Programs\AutoTAF Downloader
DefaultGroupName={#ProductName}
PrivilegesRequired=lowest
Uninstallable=yes
OutputDir=..\..\release
OutputBaseFilename=AutoTAF-Downloader-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=no

[Files]
Source: "..\..\release\AutoTAF-Downloader.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\AutoTAF Downloader"; Filename: "{app}\AutoTAF-Downloader.exe"
Name: "{autoprograms}\AutoTAF Downloader\Uninstall"; Filename: "{uninstallexe}"

[Run]
Filename: "{app}\AutoTAF-Downloader.exe"; Description: "Configure AutoTAF Downloader"; Flags: postinstall nowait skipifsilent

[UninstallRun]
Filename: "{app}\AutoTAF-Downloader.exe"; Parameters: "--remove-task"; Flags: runhidden waituntilterminated; RunOnceId: "RemoveAutoTAFDownloaderTask"
