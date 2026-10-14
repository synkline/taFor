# AutoTAF Downloader for Windows

## What it does

AutoTAF Downloader asks the existing Auto-TAF website to generate VABB Long
TAF and Short TAF through its `/generate` form. It checks the website's IMD
download status and model issue time, creates one combined PDF, validates the
PDF structure, and saves it to your PC. It does not use browser automation or
download an official TAF bulletin.

## Install and configure

1. Open `AutoTAF-Downloader-Setup.exe` and complete setup. No Git or Python
   installation is needed. The installer is per-user and does not need
   administrator rights.
2. Leave **Launch AutoTAF Downloader** selected at the end of setup.
3. Enter the Auto-TAF website URL provided by your administrator. Use the full
   site address, for example `http://your-internal-autotaf-host`. Do not add a
   username, password, query string, or secret to the URL.
4. Choose the folder where PDFs should be saved. The suggested folder is
   `D:\AutoTAF\AutoPDF\VABB`. Choose a different folder if the D: drive is
   unavailable or you prefer another location.
5. Select **Test site and enable schedule**. The app checks that the website
   exposes the existing generation form, saves your settings, and registers
   the task. A successful site check validates the form connection; it does
   not itself generate a PDF.
6. Select **Run download now** to create and verify the first PDF immediately.
   Check the selected output folder for a file beginning with
   `VABB_Combined_TAF_`.

The website address and output folder are saved in your Windows profile under
`%LOCALAPPDATA%\AutoTAF\VABBDownloader\config.json`. This configuration has no
credentials. Logs and the last-run status are kept in that folder as well.

## Controls

Open **Start Menu → AutoTAF Downloader** to change the website URL or output
folder, run a download, enable or disable the schedule, and open recent logs.
Use **Save settings** after editing a value. Use **Test site and enable
schedule** to validate the site and register or update the task.

Windows Task Scheduler runs the downloader at 00:00, 06:00, 12:00, and 18:00
local time. The task runs as your Windows account while you are signed in. It
does not store your Windows password and does not run while you are signed
out. Other users on the PC do not receive access to your task by default.

When the PC is asleep, Windows may wake it for a scheduled run if its power
settings and hardware allow that. When a run was missed while the PC was
unavailable, Task Scheduler is set to start a missed run when the PC becomes
available. A powered-off PC cannot download at the scheduled time; Windows can
attempt a catch-up run after it starts. Several missed intervals may be
coalesced into a catch-up run rather than producing one PDF for every missed
time.

Each run retries temporary network errors up to three times. Task Scheduler
also retries a failed process up to three times. Overlapping runs are ignored,
and the downloader uses an additional per-user lock. A repeated issue time is
saved with a numeric suffix, so a prior PDF is not replaced. An interrupted
PDF is written to a temporary file and is not exposed under the final `.pdf`
name until validation succeeds.

## Network security

The downloader allows HTTP because the internal website uses it. HTTP traffic
can be read or changed by someone with access to the network. Do not enter
passwords or reusable secrets, and do not put credentials in the website URL.
The downloader follows redirects only when they stay on the configured
website origin. If your administrator later provides HTTPS, the downloader
uses Python's normal certificate validation.

## Troubleshooting

- **Website URL was not accepted:** copy the website address exactly; include
  `http://` or `https://`, and omit credentials and extra query text.
- **Site check failed:** confirm that the website is reachable from this PC
  and that its `/` page still has the form that posts to `/generate`.
- **No PDF was saved:** open the app and select **Open recent logs**. The app
  rejects missing VABB TAFs, `NIL` forecasts, cache fallback, missing model
  issue time, stale model input older than 18 hours, and invalid PDF output.
- **Task says it is disabled or missing:** open the app and select **Test site
  and enable schedule** again. Task Scheduler may also be opened from the
  Windows Start menu to inspect the task's last result.
- **Task ran while the PC was off:** no process can download while the PC is
  off. After startup, Task Scheduler can attempt the queued missed run.

## Uninstall

Use **Settings → Apps → Installed apps → AutoTAF VABB Downloader → Uninstall**
or the Start Menu uninstall shortcut. The uninstaller removes the scheduled
task and application files. It does not delete PDFs in your chosen output
folder. Your per-user settings and logs remain under `%LOCALAPPDATA%` so they
can be inspected or deleted separately.
