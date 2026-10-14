import datetime
import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BUILT_EXECUTABLE = PROJECT_ROOT / "release" / "AutoTAF-Downloader.exe"


class MockAutoTafHandler(BaseHTTPRequestHandler):
    issue_time = None

    def do_GET(self):
        if self.path != "/":
            self.send_error(404)
            return
        body = (
            '<form action="/generate" method="POST">'
            '<input type="hidden" name="csrf_token" value="mock-token">'
            '</form>'
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        self.rfile.read(length)
        if self.path != "/generate":
            self.send_error(404)
            return
        body = (
            '<div id="long-taf">TAF VABB 141200Z 1412/1518 24008KT 9999 NSC=</div>'
            '<div id="short-taf">TAF VABB 141200Z 1412/1500 24008KT 9999 NSC=</div>'
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("X-AutoTAF-IMD-Source", "downloaded")
        self.send_header("X-AutoTAF-IMD-Issue-UTC", self.issue_time)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format_string, *args):
        return


@unittest.skipUnless(BUILT_EXECUTABLE.is_file(), "PyInstaller release executable has not been built")
class BuiltWindowsExecutableTests(unittest.TestCase):
    def test_executable_downloads_and_saves_valid_pdf_from_mock_server(self):
        now = datetime.datetime.now(datetime.timezone.utc)
        MockAutoTafHandler.issue_time = now.replace(minute=0, second=0, microsecond=0).isoformat().replace("+00:00", "Z")
        try:
            server = ThreadingHTTPServer(("127.0.0.1", 0), MockAutoTafHandler)
        except OSError as exc:
            if getattr(exc, "winerror", None) == 10013:
                self.skipTest("The current sandbox does not permit loopback sockets.")
            raise
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()

        try:
            with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as directory:
                root = Path(directory)
                output_directory = root / "pdfs"
                state_directory = root / "state"
                config_path = root / "config.json"
                config_path.write_text(json.dumps({
                    "base_url": f"http://127.0.0.1:{server.server_port}",
                    "output_dir": str(output_directory),
                    "max_source_age_hours": 18,
                    "attempts": 1,
                    "timeout_seconds": 30,
                }), encoding="utf-8")
                environment = os.environ.copy()
                environment["LOCALAPPDATA"] = str(state_directory)

                result = subprocess.run(
                    [str(BUILT_EXECUTABLE), "--run", "--config", str(config_path)],
                    capture_output=True,
                    text=True,
                    timeout=120,
                    env=environment,
                    check=False,
                )

                if result.returncode != 0 and "WinError 10013" in result.stderr:
                    self.skipTest("The current sandbox does not permit the packaged process to use loopback sockets.")
                self.assertEqual(result.returncode, 0, msg=result.stderr)
                pdf_files = list(output_directory.glob("*.pdf"))
                self.assertEqual(len(pdf_files), 1)
                pdf = pdf_files[0].read_bytes()
                self.assertTrue(pdf.startswith(b"%PDF-1.4"))
                self.assertTrue(pdf.rstrip().endswith(b"%%EOF"))
                self.assertIn(b"Long TAF:", pdf)
                self.assertIn(b"Short TAF:", pdf)
                app_state_directory = state_directory / "AutoTAF" / "VABBDownloader"
                status = json.loads((app_state_directory / "last_run.json").read_text(encoding="utf-8"))
                self.assertEqual(status["status"], "success")
        finally:
            server.shutdown()
            server.server_close()
            server_thread.join(timeout=5)


if __name__ == "__main__":
    unittest.main()
