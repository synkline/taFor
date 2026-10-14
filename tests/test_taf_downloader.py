import datetime
import logging
import tempfile
import unittest
from pathlib import Path
from urllib.error import URLError
from urllib.parse import parse_qs
from urllib.request import Request

from taf_downloader import (
    ConfiguredHostRedirectHandler,
    DownloadError,
    TemporaryDownloadError,
    TafDownloader,
    build_combined_pdf,
    parse_tafs,
    resolve_issue_time,
    save_unique_pdf,
    validate_base_url,
    validate_pdf_bytes,
)


LONG_TAF = "TAF VABB 121700Z 1218/1324 24008KT 9999 NSC="
SHORT_TAF = "TAF VABB 121700Z 1218/1303 24008KT 9999 NSC="

FORM_HTML = b'''<!doctype html><html><body>
<form action="/generate" method="POST">
  <input type="hidden" name="csrf_token" value="fixture-token">
  <select name="station"><option value="VABB">Mumbai</option></select>
</form></body></html>'''

RESULT_HTML = (
    '<!doctype html><html><body>'
    '<form action="/generate" method="POST"></form>'
    '<div id="long-taf">' + LONG_TAF + '</div>'
    '<div id="short-taf">' + SHORT_TAF + '</div>'
    '</body></html>'
).encode("utf-8")
TEST_NOW = datetime.datetime(2026, 10, 12, 17, 30, tzinfo=datetime.timezone.utc)


class FakeHeaders(dict):
    def get_content_charset(self):
        return None


class FakeResponse:
    def __init__(self, body, headers=None, status=200):
        self.body = body
        self.headers = FakeHeaders(headers or {})
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def read(self):
        return self.body

    def getcode(self):
        return self.status


class FakeOpener:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def open(self, request, timeout=None):
        self.requests.append((request, timeout))
        if not self.responses:
            raise AssertionError("Unexpected HTTP request")
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def successful_responses(source_status="downloaded"):
    return [
        FakeResponse(FORM_HTML),
        FakeResponse(RESULT_HTML, {
            "X-AutoTAF-IMD-Source": source_status,
            "X-AutoTAF-IMD-Issue-UTC": "2026-10-12T12:00:00Z",
        }),
    ]


class TafDownloaderTests(unittest.TestCase):
    def setUp(self):
        self.logger = logging.getLogger("taf_downloader_test")
        self.logger.addHandler(logging.NullHandler())

    def temp_directory(self):
        return tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent)

    def test_extracts_both_tafs_and_hidden_form_fields(self):
        opener = FakeOpener(successful_responses())
        downloader = TafDownloader(base_url="http://127.0.0.1:5000", opener=opener,
                                   logger=self.logger, sleep_fn=lambda _: None,
                                   now_fn=lambda: TEST_NOW)

        long_taf, short_taf = downloader._generate_from_endpoint()

        self.assertEqual(long_taf, LONG_TAF)
        self.assertEqual(short_taf, SHORT_TAF)
        request, timeout = opener.requests[1]
        self.assertEqual(request.full_url, "http://127.0.0.1:5000/generate")
        self.assertEqual(parse_qs(request.data.decode("ascii")), {
            "csrf_token": ["fixture-token"],
            "station": ["VABB"],
        })
        self.assertEqual(timeout, 600)

    def test_retries_temporary_network_errors(self):
        opener = FakeOpener([URLError("temporary offline")] + successful_responses())
        delays = []
        downloader = TafDownloader(base_url="http://127.0.0.1:5000", opener=opener,
                                   logger=self.logger, sleep_fn=delays.append,
                                   now_fn=lambda: TEST_NOW)

        self.assertEqual(downloader._generate_with_retries(), (LONG_TAF, SHORT_TAF))
        self.assertEqual(delays, [5])
        self.assertEqual(len(opener.requests), 3)

    def test_rejects_cache_fallback_and_does_not_save_pdf(self):
        opener = FakeOpener(successful_responses("cache_fallback"))
        with self.temp_directory() as temp_dir:
            downloader = TafDownloader(
                base_url="http://127.0.0.1:5000", output_dir=temp_dir, attempts=1, opener=opener,
                logger=self.logger, sleep_fn=lambda _: None, now_fn=lambda: TEST_NOW,
            )
            with self.assertRaisesRegex(DownloadError, "cached IMD data"):
                downloader.download_once()
            self.assertEqual(list(Path(temp_dir).glob("*.pdf")), [])

    def test_end_to_end_mocked_response_writes_the_combined_pdf_locally(self):
        opener = FakeOpener(successful_responses())
        with self.temp_directory() as temp_dir:
            downloader = TafDownloader(
                base_url="http://127.0.0.1:5000", output_dir=temp_dir, opener=opener,
                logger=self.logger, sleep_fn=lambda _: None, now_fn=lambda: TEST_NOW,
            )
            path = downloader.download_once()

            self.assertTrue(path.is_file())
            saved = path.read_bytes()
            self.assertTrue(saved.startswith(b"%PDF-1.4"))
            self.assertIn(b"Long TAF:", saved)
            self.assertIn(b"Short TAF:", saved)
            self.assertEqual(len(opener.requests), 2)

    def test_saves_valid_combined_pdf_and_never_overwrites(self):
        pdf = build_combined_pdf(LONG_TAF, SHORT_TAF)
        self.assertTrue(validate_pdf_bytes(pdf, LONG_TAF, SHORT_TAF))
        self.assertTrue(pdf.startswith(b"%PDF-1.4"))
        self.assertIn(b"/BaseFont /Courier", pdf)
        self.assertIn(b"Long TAF:", pdf)
        self.assertIn(b"Short TAF:", pdf)
        xref_offset = int(pdf.rsplit(b"startxref\n", 1)[1].splitlines()[0])
        self.assertEqual(pdf[xref_offset:xref_offset + 5], b"xref\n")

        generated_at = datetime.datetime(2026, 10, 12, 17, 30, tzinfo=datetime.timezone.utc)
        with self.temp_directory() as temp_dir:
            first = save_unique_pdf(temp_dir, pdf, LONG_TAF, generated_at)
            second = save_unique_pdf(temp_dir, pdf, LONG_TAF, generated_at)
            self.assertEqual(first.name, "VABB_Combined_TAF_ISSUE_20261012_1700Z.pdf")
            self.assertEqual(second.name, "VABB_Combined_TAF_ISSUE_20261012_1700Z_01.pdf")
            self.assertEqual(first.read_bytes(), pdf)
            self.assertEqual(second.read_bytes(), pdf)

    def test_falls_back_to_generation_timestamp_in_filename(self):
        generated_at = datetime.datetime(2026, 10, 12, 17, 30, 45, tzinfo=datetime.timezone.utc)
        with self.temp_directory() as temp_dir:
            long_taf = "TAF VABB issue time unavailable"
            pdf = build_combined_pdf(long_taf, "TAF VABB short issue time unavailable")
            path = save_unique_pdf(temp_dir, pdf, long_taf, generated_at)
            self.assertEqual(path.name, "VABB_Combined_TAF_GENERATED_20261012_173045Z.pdf")

    def test_resolves_issue_time_across_month_boundary(self):
        generated_at = datetime.datetime(2026, 11, 1, 0, 15, tzinfo=datetime.timezone.utc)
        issue_time = resolve_issue_time("TAF VABB 312300Z 0100/0206 ...", generated_at)
        self.assertEqual(issue_time, datetime.datetime(2026, 10, 31, 23, 0, tzinfo=datetime.timezone.utc))

    def test_parses_application_error_box(self):
        html = '<div class="card error-box"><h3>Error</h3><p>Ogimet Error: Network error</p></div>'
        _, long_taf, short_taf, error = parse_tafs(html)
        self.assertEqual((long_taf, short_taf), ("", ""))
        self.assertEqual(error, "Error Ogimet Error: Network error")

    def test_rejects_stale_model_issue_even_when_server_says_downloaded(self):
        responses = successful_responses()
        responses[1] = FakeResponse(RESULT_HTML, {
            "X-AutoTAF-IMD-Source": "downloaded",
            "X-AutoTAF-IMD-Issue-UTC": "2026-10-11T00:00:00Z",
        })
        downloader = TafDownloader(
            base_url="http://127.0.0.1:5000", attempts=1,
            opener=FakeOpener(responses), logger=self.logger,
            now_fn=lambda: TEST_NOW, sleep_fn=lambda _: None,
        )
        with self.assertRaisesRegex(TemporaryDownloadError, "hours old"):
            downloader._generate_with_retries()

    def test_blocks_requests_and_redirects_outside_configured_origin(self):
        downloader = TafDownloader(base_url="http://autotaf.example", opener=FakeOpener([]), logger=self.logger)
        with self.assertRaisesRegex(DownloadError, "left the configured"):
            downloader._open(Request("http://other.example/"))

        redirect_handler = ConfiguredHostRedirectHandler("http://autotaf.example")
        with self.assertRaisesRegex(DownloadError, "redirected outside"):
            redirect_handler.redirect_request(
                Request("http://autotaf.example/"), None, 302, "Found", {},
                "http://attacker.example/generate",
            )
        with self.assertRaisesRegex(DownloadError, "invalid redirect"):
            redirect_handler.redirect_request(
                Request("http://autotaf.example/"), None, 302, "Found", {},
                "http://user:secret@autotaf.example/generate",
            )

    def test_rejects_credentials_query_and_invalid_scheme_in_base_url(self):
        for url in (
            "http://user:password@autotaf.example",
            "http://autotaf.example/?token=secret",
            "ftp://autotaf.example",
        ):
            with self.subTest(url=url), self.assertRaises(DownloadError):
                validate_base_url(url)

    def test_rejects_corrupt_pdf_before_creating_final_file(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as temp_dir:
            with self.assertRaises(DownloadError):
                save_unique_pdf(temp_dir, b"%PDF-broken", LONG_TAF, TEST_NOW)
            self.assertEqual(list(Path(temp_dir).glob("*.pdf")), [])
            self.assertEqual(list(Path(temp_dir).glob(".autotaf-*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
