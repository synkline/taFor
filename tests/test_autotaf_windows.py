import json
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import autotaf_windows
from taf_downloader import DownloadError


class WindowsDownloaderAppTests(unittest.TestCase):
    def test_configuration_is_saved_and_reloaded_per_user(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as directory:
            config_path = Path(directory) / "config.json"
            output_path = Path(directory) / "pdf output"
            saved_path = autotaf_windows.save_config({
                "base_url": "http://internal-autotaf.example/",
                "output_dir": str(output_path),
                "max_source_age_hours": 12,
            }, config_path)

            self.assertEqual(saved_path, config_path)
            loaded = autotaf_windows.load_config(config_path)
            self.assertEqual(loaded["base_url"], "http://internal-autotaf.example")
            self.assertEqual(loaded["output_dir"], str(output_path))
            self.assertEqual(loaded["max_source_age_hours"], 12)
            self.assertNotIn("password", config_path.read_text(encoding="utf-8").lower())

    def test_configuration_rejects_url_credentials_and_relative_output(self):
        with self.assertRaises(DownloadError):
            autotaf_windows.normalize_config(
                "http://user:secret@internal.example", r"D:\AutoTAF\PDF"
            )
        with self.assertRaisesRegex(DownloadError, "absolute path"):
            autotaf_windows.normalize_config("http://internal.example", "relative-pdfs")

    def test_output_folder_is_created_and_write_checked_before_scheduling(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as directory:
            output = Path(directory) / "nested" / "pdfs"
            validated = autotaf_windows.validate_output_directory(output)
            self.assertEqual(validated, output)
            self.assertTrue(output.is_dir())
            self.assertEqual(list(output.iterdir()), [])

    def test_registration_calls_task_helper_and_uses_saved_configuration(self):
        calls = []

        def fake_runner(command, **kwargs):
            calls.append((command, kwargs))
            return SimpleNamespace(returncode=0, stdout="registered", stderr="")

        config_path = Path(__file__).resolve().parent / "sample-config.json"
        result = autotaf_windows.manage_scheduled_task(
            "register", config_path, runner=fake_runner
        )

        self.assertEqual(result, "registered")
        command, kwargs = calls[0]
        self.assertIn("-Action", command)
        self.assertIn("Register", command)
        self.assertIn("windows_task_scheduler.ps1", " ".join(command))
        self.assertIn("--run", " ".join(command))
        self.assertIn(str(config_path), " ".join(command))
        self.assertTrue(kwargs["capture_output"])
        self.assertEqual(kwargs["timeout"], 45)

    def test_task_definition_has_fixed_times_catch_up_retry_and_overlap_controls(self):
        script_path = Path(__file__).resolve().parents[1] / "windows_task_scheduler.ps1"
        script = script_path.read_text(encoding="utf-8")
        for expected in (
            "@(0, 6, 12, 18)",
            "-StartWhenAvailable",
            "-WakeToRun",
            "-MultipleInstances IgnoreNew",
            "-RestartCount 3",
            "-Force",
            "-LogonType Interactive",
            "Unregister-ScheduledTask",
        ):
            self.assertIn(expected, script)

    def test_uninstaller_removes_the_task_without_targeting_pdf_directories(self):
        installer_path = Path(__file__).resolve().parents[1] / "packaging" / "windows" / "AutoTAF-Downloader.iss"
        installer = installer_path.read_text(encoding="utf-8")
        self.assertIn('Parameters: "--remove-task"', installer)
        self.assertNotIn("D:\\AutoTAF\\AutoPDF", installer)
        self.assertNotIn("Remove-Item", installer)

    def test_scheduled_run_records_last_success(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as directory:
            state_directory = Path(directory) / "state"
            config_path = Path(directory) / "config.json"
            output_path = Path(directory) / "out"
            autotaf_windows.save_config({
                "base_url": "http://internal-autotaf.example",
                "output_dir": str(output_path),
            }, config_path)
            expected_pdf = output_path / "VABB.pdf"

            with patch.object(autotaf_windows, "application_data_directory", return_value=state_directory), \
                    patch.object(autotaf_windows, "TafDownloader") as downloader_class:
                downloader_class.return_value.download_once.return_value = expected_pdf
                result = autotaf_windows.run_download(config_path)

            self.assertEqual(result, expected_pdf)
            last_run = json.loads((state_directory / "last_run.json").read_text(encoding="utf-8"))
            self.assertEqual(last_run["status"], "success")
            self.assertEqual(last_run["pdf_path"], str(expected_pdf))


if __name__ == "__main__":
    unittest.main()
