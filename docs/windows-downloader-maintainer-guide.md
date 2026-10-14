# AutoTAF Windows Downloader: Maintainer Guide

## Release contents and runtime

The Windows app is a PyInstaller one-file executable built from
`autotaf_windows.py`. `packaging/windows/autotaf_downloader.spec` includes the
Task Scheduler PowerShell helper. `packaging/windows/AutoTAF-Downloader.iss`
wraps the executable as `AutoTAF-Downloader-Setup.exe` with Inno Setup. The
release installer is built once and sent to users; the website does not build
or serve it at request time.

At runtime the UI stores the user-entered website URL and output path in
`%LOCALAPPDATA%\AutoTAF\VABBDownloader\config.json`. The scheduled task
launches the executable with `--run`. It uses the existing `/` form and
`POST /generate` endpoint, including hidden inputs and session cookies. It
does not require login credentials or browser JavaScript. The existing
browser-side jsPDF button is independent and remains in `templates/index.html`.

The Python downloader currently writes a small PDF 1.4 itself with A4,
Courier 12 point, 10 mm margins, and wrapped text modeled on the existing
browser export. The browser's jsPDF implementation is client-side, so it
cannot be invoked from a standalone Windows process. No new PDF endpoint was
added to Flask.

## Build a release

Build on a Windows x64 machine with Python 3.9 or newer, PyInstaller, and Inno
Setup 6. Install the pinned build tool in an isolated environment:

```powershell
python -m venv .venv-build
.\.venv-build\Scripts\python.exe -m pip install -r packaging\windows\build-requirements.txt
```

Install Inno Setup 6 from [jrsoftware.org/isinfo.php](https://jrsoftware.org/isinfo.php).
Then build both files:

```powershell
.\packaging\windows\build_windows_release.ps1 -PythonExe .\.venv-build\Scripts\python.exe
```

To pass an explicit compiler path:

```powershell
.\packaging\windows\build_windows_release.ps1 `
  -PythonExe .\.venv-build\Scripts\python.exe `
  -InnoCompiler "C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
```

The script writes the executable and installer under `release\`. If Inno
Setup is missing, it can still build the executable but stops with an explicit
message; it does not claim to have built the installer. No runtime Python or
Git is required on recipient PCs.

Inno Setup 6.7.3 prints “Non-commercial use only” during compilation. Its
publisher asks commercial users to purchase a license and expects at least a
single-user license for automated compiler use. Confirm the project’s use
category and obtain any required license before future commercial releases.

## Test and verify release artifacts

Run the repository's automated tests from the project root:

```powershell
python -m unittest discover -s tests -v
```

Build checks and mocked tests do not prove that the deployed website is
reachable or that Task Scheduler works on a recipient PC. Verify each release
on a clean Windows 10/11 x64 test account without Python or Git:

1. Install the generated setup EXE.
2. Enter the deployed Auto-TAF website URL and choose an output folder.
3. Test the site and enable the task.
4. Run one download immediately; inspect the PDF and application log.
5. Inspect the task triggers and settings in Task Scheduler.
6. Disable, enable, and uninstall; verify the task is removed and downloaded
   PDFs remain.

## Hashing and code signing

After a successful installer build, calculate a checksum:

```powershell
Get-FileHash .\release\AutoTAF-Downloader-Setup.exe -Algorithm SHA256
```

Keep the checksum beside the release record. A checksum delivered through the
same email as the installer does not independently protect against a sender
or channel that can alter both files.

If an approved Authenticode certificate is available in the Windows
certificate store and the Windows SDK signing tool is installed, build with:

```powershell
.\packaging\windows\build_windows_release.ps1 `
  -PythonExe .\.venv-build\Scripts\python.exe `
  -SigningCertificateThumbprint "CERTIFICATE_THUMBPRINT"
```

The build script signs the installer and timestamps the signature. The
executable inside it is not separately signed by this option. Without signing,
Windows SmartScreen or endpoint protection may warn users about an unknown
publisher. Do not distribute the EXE by email until a clean-machine test and
organizational security review are complete.

## Website production secret

`app.py` now uses `FLASK_SECRET_KEY` from the environment. Local development
uses a random per-process fallback unless `AUTO_TAF_ENV=production` is set.
Production must set both `AUTO_TAF_ENV=production` and a stable,
high-entropy `FLASK_SECRET_KEY` through the hosting platform's secret manager.
The repository's Dockerfile marks its container as production, so a deployment
using that Dockerfile must supply `FLASK_SECRET_KEY` before startup. Never put
the secret in Git or in the downloader configuration.

`/generate` supplies `X-AutoTAF-IMD-Source` and
`X-AutoTAF-IMD-Issue-UTC`. The latter comes from the exact IMD file just
downloaded and read by `IMDScraper`; the downloader rejects missing issue
metadata, cache fallback, future timestamps, and model input older than 18
hours. If the app source changes, deploy that backend before distributing a
downloader release that depends on the issue-time header.

## HTTP and release limitations

The downloader supports the internal HTTP deployment, but HTTP does not
authenticate the server or protect response contents in transit. It blocks
redirects outside the configured origin and stores no credentials. HTTPS
requests use the normal Python certificate validation. Do not move users to an
untrusted network with HTTP access to the site.

The scheduled task uses the installing user's interactive Windows identity.
It runs only while that user is signed in. `StartWhenAvailable` asks Windows
to run a missed occurrence after startup or resume, and `WakeToRun` requests
wake behavior when hardware and power settings support it. A powered-off
machine cannot run a task; missed intervals can be coalesced.
