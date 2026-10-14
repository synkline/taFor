import unittest
from pathlib import Path
import sys
import tempfile
import types
from unittest.mock import patch

try:
    import bs4  # noqa: F401
except ModuleNotFoundError:
    # These tests exercise only cache-path selection and timestamp metadata;
    # HTML parsing is outside their scope and is supplied by the website extra.
    bs4_stub = types.ModuleType("bs4")
    bs4_stub.BeautifulSoup = object
    sys.modules["bs4"] = bs4_stub

from scraper import IMDScraper


class ImdFreshnessTests(unittest.TestCase):
    def test_repeat_download_for_same_model_issue_atomically_refreshes_cache_file(self):
        scraper = IMDScraper()
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as directory:
            with patch("scraper.os.getcwd", return_value=directory):
                old_path = scraper._save_with_versioning(
                    b"BASED ON 12 UTC of 20261014\nold payload", "VABB"
                )
                new_path = scraper._save_with_versioning(
                    b"BASED ON 12 UTC of 20261014\nrefreshed payload", "VABB"
                )

            self.assertEqual(old_path, new_path)
            self.assertEqual(Path(new_path).read_bytes(), b"BASED ON 12 UTC of 20261014\nrefreshed payload")
            self.assertEqual(list(Path(new_path).parent.glob("*.tmp")), [])

    def test_downloaded_model_file_is_the_file_parsed_and_issue_time_is_returned(self):
        scraper = IMDScraper()
        downloaded = Path("VABB_20261014_12UTC.txt")
        parsed = {"forecast_rows": [1]}

        with patch.object(scraper, "download_data", return_value={"success": True, "path": str(downloaded)}), \
                patch.object(scraper, "_read_data_file", return_value=parsed) as read_download, \
                patch.object(scraper, "read_from_cache") as read_cache:
            result = scraper.fetch_data("VABB")

        read_download.assert_called_once_with(str(downloaded))
        read_cache.assert_not_called()
        self.assertEqual(result["_imd_download_status"], "downloaded")
        self.assertEqual(result["_imd_downloaded_file"], downloaded.name)
        self.assertEqual(result["_imd_model_issue_utc"], "2026-10-14T12:00:00Z")

    def test_cache_fallback_does_not_claim_an_issue_time(self):
        scraper = IMDScraper()
        with patch.object(scraper, "download_data", return_value={"error": "offline"}), \
                patch.object(scraper, "read_from_cache", return_value={"forecast_rows": [1]}):
            result = scraper.fetch_data("VABB")

        self.assertEqual(result["_imd_download_status"], "cache_fallback")
        self.assertNotIn("_imd_model_issue_utc", result)


if __name__ == "__main__":
    unittest.main()
