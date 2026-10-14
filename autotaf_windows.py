"""Windows configuration utility and scheduled entry point for Auto-TAF."""

import argparse
import datetime
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading

from taf_downloader import (
    DEFAULT_MAX_SOURCE_AGE_HOURS,
    DEFAULT_OUTPUT_DIR,
    DownloadError,
    TafDownloader,
    configure_logging,
    validate_base_url,
)


APP_NAME = "AutoTAF VABB Downloader"
TASK_NAME = "AutoTAF VABB PDF Downloader"
CONFIG_FILE_NAME = "config.json"


def application_data_directory():
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / "AutoTAF" / "VABBDownloader"
    return Path.home() / "AppData" / "Local" / "AutoTAF" / "VABBDownloader"


def default_config(config_path=None):
    return {
        "base_url": "",
        "output_dir": str(DEFAULT_OUTPUT_DIR),
        "max_source_age_hours": DEFAULT_MAX_SOURCE_AGE_HOURS,
        "attempts": 3,
        "timeout_seconds": 600,
    }


def load_config(config_path=None):
    path = Path(config_path) if config_path else application_data_directory() / CONFIG_FILE_NAME
    if not path.is_file():
        return default_config(path)
    try:
        stored = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DownloadError("The saved Auto-TAF configuration could not be read.") from exc
    config = default_config(path)
    config.update({key: stored[key] for key in config if key in stored})
    config["base_url"] = validate_base_url(config["base_url"]) if config["base_url"] else ""
    output_path = Path(config["output_dir"]).expanduser()
    if not output_path.is_absolute():
        raise DownloadError("The saved PDF output folder must be an absolute path.")
    config["output_dir"] = str(output_path)
    if not isinstance(config["max_source_age_hours"], (int, float)) or config["max_source_age_hours"] <= 0:
        raise DownloadError("The saved maximum IMD data age must be a positive number of hours.")
    if not isinstance(config["attempts"], int) or config["attempts"] < 1:
        raise DownloadError("The saved retry count must be a positive integer.")
    if not isinstance(config["timeout_seconds"], int) or config["timeout_seconds"] < 1:
        raise DownloadError("The saved request timeout must be a positive integer.")
    return config


def normalize_config(base_url, output_dir, max_source_age_hours=DEFAULT_MAX_SOURCE_AGE_HOURS):
    base_url = validate_base_url(base_url)
    output_path = Path(output_dir).expanduser()
    if not output_path.is_absolute():
        raise DownloadError("Choose an absolute path for the PDF output folder.")
    if max_source_age_hours <= 0:
        raise DownloadError("Maximum IMD model age must be a positive number of hours.")
    return {
        "base_url": base_url,
        "output_dir": str(output_path),
        "max_source_age_hours": float(max_source_age_hours),
        "attempts": 3,
        "timeout_seconds": 600,
    }


def validate_output_directory(output_dir):
    output_path = Path(output_dir).expanduser()
    if not output_path.is_absolute():
        raise DownloadError("Choose an absolute path for the PDF output folder.")
    try:
        output_path.mkdir(parents=True, exist_ok=True)
        fd, temporary_name = tempfile.mkstemp(prefix=".autotaf-check-", dir=str(output_path))
        os.close(fd)
        Path(temporary_name).unlink()
    except OSError as exc:
        raise DownloadError("The chosen PDF folder cannot be created or written to.") from exc
    return output_path


def save_config(config, config_path=None):
    path = Path(config_path) if config_path else application_data_directory() / CONFIG_FILE_NAME
    normalized = normalize_config(
        config.get("base_url", ""),
        config.get("output_dir", str(DEFAULT_OUTPUT_DIR)),
        config.get("max_source_age_hours", DEFAULT_MAX_SOURCE_AGE_HOURS),
    )
    normalized["attempts"] = int(config.get("attempts", 3))
    normalized["timeout_seconds"] = int(config.get("timeout_seconds", 600))
    if normalized["attempts"] < 1 or normalized["timeout_seconds"] < 1:
        raise DownloadError("Retry count and timeout must be positive integers.")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = None
    try:
        fd, temp_name = tempfile.mkstemp(prefix=".config-", suffix=".tmp", dir=str(path.parent))
        temporary_path = Path(temp_name)
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as config_file:
            json.dump(normalized, config_file, indent=2)
            config_file.write("\n")
            config_file.flush()
            os.fsync(config_file.fileno())
        os.replace(temporary_path, path)
    finally:
        if temporary_path:
            try:
                temporary_path.unlink()
            except FileNotFoundError:
                pass
    return path


def _resource_path(filename):
    bundle_directory = getattr(sys, "_MEIPASS", None)
    if bundle_directory:
        return Path(bundle_directory) / filename
    return Path(__file__).resolve().parent / filename


def scheduled_executable_and_arguments(config_path=None):
    config_path = Path(config_path) if config_path else application_data_directory() / CONFIG_FILE_NAME
    if getattr(sys, "frozen", False):
        executable = Path(sys.executable)
        arguments = f'--run --config "{config_path}"'
    else:
        executable = Path(sys.executable)
        script_path = Path(__file__).resolve()
        arguments = f'"{script_path}" --run --config "{config_path}"'
    return executable, arguments


def manage_scheduled_task(action, config_path=None, runner=subprocess.run):
    action = action.capitalize()
    if action not in {"Register", "Enable", "Disable", "Remove", "Status"}:
        raise DownloadError("Unsupported scheduled-task action.")
    script_path = _resource_path("windows_task_scheduler.ps1")
    if not script_path.is_file():
        raise DownloadError("The bundled Windows Task Scheduler helper is missing.")
    executable, arguments = scheduled_executable_and_arguments(config_path)
    if os.name == "nt":
        powershell_executable = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
        if not powershell_executable.is_file():
            raise DownloadError("Windows PowerShell could not be found.")
        powershell_command = str(powershell_executable)
    else:
        powershell_command = shutil.which("powershell.exe") or "powershell.exe"
    command = [
        powershell_command, "-NoLogo", "-NoProfile", "-NonInteractive",
        "-ExecutionPolicy", "Bypass", "-File", str(script_path),
        "-Action", action, "-TaskName", TASK_NAME,
        "-ExePath", str(executable), "-Arguments", arguments,
    ]
    result = runner(command, capture_output=True, text=True, timeout=45, check=False,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if result.returncode != 0:
        message = (result.stderr or result.stdout or "Task Scheduler operation failed.").strip()
        raise DownloadError(message[-1200:])
    return (result.stdout or "").strip()


def _write_last_run(status_path, result):
    status_path = Path(status_path)
    status_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = status_path.with_suffix(".tmp")
    temporary.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, status_path)


def run_download(config_path=None):
    state_directory = application_data_directory()
    status_path = state_directory / "last_run.json"
    started_at = datetime.datetime.now(datetime.timezone.utc)
    logger = configure_logging(state_directory)
    try:
        config = load_config(config_path)
        if not config["base_url"]:
            raise DownloadError("Configure the Auto-TAF website URL in the downloader first.")
        downloader = TafDownloader(
            config["base_url"],
            config["output_dir"],
            timeout=config["timeout_seconds"],
            attempts=config["attempts"],
            max_source_age_hours=config["max_source_age_hours"],
            lock_path=state_directory / "downloader.lock",
            logger=logger,
        )
        pdf_path = downloader.download_once()
        completed_at = datetime.datetime.now(datetime.timezone.utc)
        _write_last_run(status_path, {
            "status": "success",
            "started_at_utc": started_at.isoformat().replace("+00:00", "Z"),
            "completed_at_utc": completed_at.isoformat().replace("+00:00", "Z"),
            "pdf_path": str(pdf_path),
        })
        return pdf_path
    except Exception as exc:
        completed_at = datetime.datetime.now(datetime.timezone.utc)
        logger.exception("VABB TAF PDF download failed: %s", exc)
        _write_last_run(status_path, {
            "status": "failed",
            "started_at_utc": started_at.isoformat().replace("+00:00", "Z"),
            "completed_at_utc": completed_at.isoformat().replace("+00:00", "Z"),
            "error": str(exc)[:1200],
        })
        raise
    finally:
        for handler in list(logger.handlers):
            try:
                handler.flush()
                handler.close()
            finally:
                logger.removeHandler(handler)


def read_last_run():
    path = application_data_directory() / "last_run.json"
    if not path.is_file():
        return "No download has run yet."
    try:
        result = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "The previous run status file could not be read."
    completed = result.get("completed_at_utc", "unknown time")
    if result.get("status") == "success":
        return f"Last run succeeded at {completed}. PDF: {result.get('pdf_path', 'unknown location')}"
    return f"Last run failed at {completed}. {result.get('error', 'See the log for details.')}"


class DownloaderWindow:
    def __init__(self, root, config_path=None):
        import tkinter as tk
        from tkinter import filedialog, messagebox, ttk

        self.tk = tk
        self.filedialog = filedialog
        self.messagebox = messagebox
        self.ttk = ttk
        self.root = root
        self.config_path = Path(config_path) if config_path else application_data_directory() / CONFIG_FILE_NAME
        try:
            config = load_config(self.config_path)
        except DownloadError as exc:
            config = default_config()
            self.messagebox.showerror(APP_NAME, str(exc))

        self.root.title(APP_NAME)
        self.root.geometry("660x390")
        self.root.minsize(580, 350)
        self.base_url_var = tk.StringVar(value=config["base_url"])
        self.output_dir_var = tk.StringVar(value=config["output_dir"])
        self.status_var = tk.StringVar(value=read_last_run())
        self._build_ui()

    def _build_ui(self):
        tk = self.tk
        ttk = self.ttk
        frame = ttk.Frame(self.root, padding=18)
        frame.pack(fill="both", expand=True)
        frame.columnconfigure(1, weight=1)

        ttk.Label(frame, text="Auto-TAF website URL").grid(row=0, column=0, sticky="w", pady=6)
        ttk.Entry(frame, textvariable=self.base_url_var).grid(row=0, column=1, columnspan=2, sticky="ew", pady=6)
        ttk.Label(frame, text="PDF output folder").grid(row=1, column=0, sticky="w", pady=6)
        ttk.Entry(frame, textvariable=self.output_dir_var).grid(row=1, column=1, sticky="ew", pady=6)
        ttk.Button(frame, text="Browse…", command=self._browse).grid(row=1, column=2, padx=(8, 0), pady=6)

        ttk.Separator(frame).grid(row=2, column=0, columnspan=3, sticky="ew", pady=12)
        ttk.Button(frame, text="Save settings", command=self._save).grid(row=3, column=0, sticky="ew", padx=4, pady=5)
        ttk.Button(frame, text="Run download now", command=self._run_now).grid(row=3, column=1, sticky="ew", padx=4, pady=5)
        ttk.Button(frame, text="Test site and enable schedule", command=self._enable_schedule).grid(row=4, column=0, columnspan=2, sticky="ew", padx=4, pady=5)
        ttk.Button(frame, text="Disable schedule", command=self._disable_schedule).grid(row=4, column=2, sticky="ew", padx=4, pady=5)
        ttk.Button(frame, text="Open recent logs", command=self._open_logs).grid(row=5, column=0, sticky="ew", padx=4, pady=5)
        ttk.Button(frame, text="Refresh status", command=self._refresh_status).grid(row=5, column=1, sticky="ew", padx=4, pady=5)

        ttk.Label(frame, text="Downloads run at 00:00, 06:00, 12:00, and 18:00 local time. The task runs while you are signed in.", wraplength=610).grid(row=6, column=0, columnspan=3, sticky="w", pady=(16, 5))
        ttk.Label(frame, textvariable=self.status_var, wraplength=610).grid(row=7, column=0, columnspan=3, sticky="w", pady=5)
        ttk.Label(frame, text="HTTP traffic can be read or changed by others on the network. Do not use a URL containing credentials.", wraplength=610).grid(row=8, column=0, columnspan=3, sticky="w", pady=(10, 0))

    def _current_config(self):
        return normalize_config(self.base_url_var.get(), self.output_dir_var.get())

    def _save(self, show_message=True):
        try:
            config = self._current_config()
            validate_output_directory(config["output_dir"])
            path = save_config(config, self.config_path)
            if show_message:
                self.messagebox.showinfo(APP_NAME, f"Settings saved to {path}.")
            return config
        except (DownloadError, OSError) as exc:
            self.messagebox.showerror(APP_NAME, str(exc))
            return None

    def _browse(self):
        selected = self.filedialog.askdirectory(
            title="Choose where Auto-TAF PDFs will be saved",
            initialdir=self.output_dir_var.get() or str(DEFAULT_OUTPUT_DIR),
            mustexist=False,
        )
        if selected:
            self.output_dir_var.set(selected)

    def _enable_schedule(self):
        config = self._save(show_message=False)
        if not config:
            return
        self.status_var.set("Checking the website and registering the schedule…")
        self.root.update_idletasks()
        try:
            TafDownloader(config["base_url"], config["output_dir"], timeout=20).probe_site()
            manage_scheduled_task("Register", self.config_path)
            self.status_var.set("Schedule enabled for 00:00, 06:00, 12:00, and 18:00 local time.")
            self.messagebox.showinfo(APP_NAME, "The website was validated and the six-hour schedule is enabled.")
        except Exception as exc:
            self.status_var.set("Schedule was not changed.")
            self.messagebox.showerror(APP_NAME, f"Could not validate the website or register the task.\n\n{exc}")

    def _disable_schedule(self):
        try:
            manage_scheduled_task("Disable", self.config_path)
            self.status_var.set("Automatic downloads are disabled. Your saved PDFs are unchanged.")
        except Exception as exc:
            self.messagebox.showerror(APP_NAME, str(exc))

    def _run_now(self):
        config = self._save(show_message=False)
        if not config:
            return
        self.status_var.set("Generating and validating the VABB PDF…")
        self.root.update_idletasks()
        threading.Thread(target=self._run_in_background, daemon=True).start()

    def _run_in_background(self):
        try:
            path = run_download(self.config_path)
            self.root.after(0, lambda: self.status_var.set(f"Download complete: {path}"))
        except Exception as exc:
            self.root.after(0, lambda message=str(exc): self.status_var.set(f"Download failed: {message}"))

    def _open_logs(self):
        log_directory = application_data_directory() / "logs"
        log_directory.mkdir(parents=True, exist_ok=True)
        try:
            os.startfile(str(log_directory))
        except (AttributeError, OSError) as exc:
            self.messagebox.showerror(APP_NAME, f"Could not open the log folder: {exc}")

    def _refresh_status(self):
        self.status_var.set(read_last_run())


def run_gui(config_path=None):
    import tkinter as tk

    root = tk.Tk()
    DownloaderWindow(root, config_path)
    root.mainloop()


def parse_app_args(argv=None):
    parser = argparse.ArgumentParser(description=APP_NAME)
    parser.add_argument("--config", help="Path to the per-user configuration file.")
    parser.add_argument("--run", action="store_true", help="Run one scheduled/manual download and exit.")
    parser.add_argument("--remove-task", action="store_true", help="Remove the scheduled task during uninstall.")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_app_args(argv)
    try:
        if args.remove_task:
            manage_scheduled_task("Remove", args.config)
            return 0
        if args.run:
            run_download(args.config)
            return 0
        run_gui(args.config)
        return 0
    except Exception as exc:
        if args.run or args.remove_task:
            try:
                state_directory = application_data_directory()
                logger = configure_logging(state_directory)
                logger.error("Auto-TAF operation failed: %s", exc)
            except OSError:
                pass
            return 1
        import tkinter.messagebox
        tkinter.messagebox.showerror(APP_NAME, str(exc))
        return 1


if __name__ == "__main__":
    sys.exit(main())
