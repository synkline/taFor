"""Fetch TAFs from the existing Auto-TAF web workflow and save a combined PDF.

This standalone client deliberately uses only Python's standard library. Its PDF
layout mirrors the browser's jsPDF settings in templates/index.html: A4 portrait,
Courier/monospace 12 pt, 180 mm text width, and the same combined text headings.
"""

import argparse
import datetime
import http.cookiejar
import logging
from logging.handlers import RotatingFileHandler
from html.parser import HTMLParser
import os
from pathlib import Path
import re
import socket
import sys
import textwrap
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urljoin, urlsplit
from urllib.request import HTTPCookieProcessor, Request, build_opener


DEFAULT_BASE_URL = "http://127.0.0.1:5000"
DEFAULT_OUTPUT_DIR = Path(r"D:\AutoTAF\AutoPDF\VABB")
FRESHNESS_HEADER = "X-AutoTAF-IMD-Source"
ISSUE_RE = re.compile(r"\bTAF\s+VABB\s+(\d{6})Z\b", re.IGNORECASE)
TRANSIENT_HTTP_CODES = {408, 425, 429, 500, 502, 503, 504}
VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}


class DownloadError(RuntimeError):
    """A permanent error that prevents a reliable PDF from being saved."""


class TemporaryDownloadError(DownloadError):
    """A network or server condition that is reasonable to retry."""


class AlreadyRunningError(DownloadError):
    """Another downloader process currently owns the output-directory lock."""


class GenerationPageParser(HTMLParser):
    """Extract the existing form fields and TAF elements without a browser."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.forms = []
        self._active_form = None
        self.tafs = {"long-taf": [], "short-taf": []}
        self.error_text = []
        self._capture = None
        self._capture_stack = []

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        attributes = {key.lower(): value or "" for key, value in attrs}

        if self._capture is not None:
            if tag == "br":
                self._capture.append("\n")
            elif tag not in VOID_TAGS:
                if self._capture is self.error_text:
                    self._capture.append(" ")
                self._capture_stack.append(tag)
            return

        if tag == "form":
            self._active_form = {"action": attributes.get("action", ""), "fields": {}}
            self.forms.append(self._active_form)
        elif tag == "input" and self._active_form:
            if attributes.get("type", "").lower() == "hidden" and attributes.get("name"):
                self._active_form["fields"][attributes["name"]] = attributes.get("value", "")

        element_id = attributes.get("id", "")
        classes = set(attributes.get("class", "").split())
        if tag in {"div", "pre", "span"} and element_id in self.tafs:
            self._capture = self.tafs[element_id]
            self._capture_stack = [tag]
        elif tag in {"div", "section"} and "error-box" in classes:
            self._capture = self.error_text
            self._capture_stack = [tag]

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag.lower() not in VOID_TAGS:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        tag = tag.lower()
        if self._capture is not None:
            if tag in VOID_TAGS:
                return
            for index in range(len(self._capture_stack) - 1, -1, -1):
                if self._capture_stack[index] == tag:
                    del self._capture_stack[index:]
                    break
            if not self._capture_stack:
                self._capture = None
            return

        if tag == "form":
            self._active_form = None

    def handle_data(self, data):
        if self._capture is not None:
            self._capture.append(data)


def _decode_response(body, headers):
    charset = None
    if hasattr(headers, "get_content_charset"):
        charset = headers.get_content_charset()
    if not charset and hasattr(headers, "get"):
        content_type = headers.get("Content-Type", "")
        match = re.search(r"charset\s*=\s*['\"]?([^; '\"]+)", content_type, re.IGNORECASE)
        if match:
            charset = match.group(1)
    return body.decode(charset or "utf-8", errors="replace")


def _header(headers, name):
    if hasattr(headers, "get"):
        value = headers.get(name)
        if value is not None:
            return str(value)
    if hasattr(headers, "items"):
        for key, value in headers.items():
            if str(key).lower() == name.lower():
                return str(value)
    return ""


def parse_tafs(html_text):
    parser = GenerationPageParser()
    parser.feed(html_text)
    parser.close()
    long_taf = "".join(parser.tafs["long-taf"]).strip()
    short_taf = "".join(parser.tafs["short-taf"]).strip()
    error = " ".join("".join(parser.error_text).split())
    return parser, long_taf, short_taf, error


def resolve_issue_time(long_taf, generated_at=None):
    """Resolve the TAF's DDHHMMZ issue group to its nearest full UTC datetime."""
    match = ISSUE_RE.search(long_taf)
    if not match:
        return None

    if generated_at is None:
        generated_at = datetime.datetime.now(datetime.timezone.utc)
    elif generated_at.tzinfo is None:
        generated_at = generated_at.replace(tzinfo=datetime.timezone.utc)
    else:
        generated_at = generated_at.astimezone(datetime.timezone.utc)

    day = int(match.group(1)[:2])
    hour = int(match.group(1)[2:4])
    minute = int(match.group(1)[4:6])
    candidates = []
    for day_offset in range(-3, 4):
        candidate_date = (generated_at + datetime.timedelta(days=day_offset)).date()
        if candidate_date.day != day:
            continue
        try:
            candidates.append(datetime.datetime(
                candidate_date.year, candidate_date.month, candidate_date.day,
                hour, minute, tzinfo=datetime.timezone.utc
            ))
        except ValueError:
            continue
    if not candidates:
        return None
    return min(candidates, key=lambda candidate: abs(candidate - generated_at))


def _pdf_escape(text):
    encoded = text.encode("cp1252", errors="replace")
    escaped = bytearray()
    for byte in encoded:
        if byte in (ord("("), ord(")"), ord("\\")):
            escaped.extend(b"\\" + bytes((byte,)))
        elif byte < 32 or byte > 126:
            escaped.extend(("\\%03o" % byte).encode("ascii"))
        else:
            escaped.append(byte)
    return bytes(escaped)


def build_combined_pdf(long_taf, short_taf):
    """Build a simple PDF matching the current jsPDF export's content and style."""
    combined = "Long TAF:\n" + long_taf + "\n\nShort TAF:\n" + short_taf
    # A4 width minus the existing jsPDF 10 mm margins on both sides, using
    # standard Courier's 0.6-em glyph width at 12 pt (about 70 characters).
    wrapped_lines = []
    for source_line in combined.splitlines():
        lines = textwrap.wrap(source_line, width=70, break_long_words=True, break_on_hyphens=False)
        wrapped_lines.extend(lines or [""])

    page_width = 595.2756
    page_height = 841.8898
    margin = 28.3465  # 10 mm
    line_height = 12 * 1.15  # jsPDF's default 1.15 line-height factor
    max_lines = max(1, int((page_height - 2 * margin) // line_height))
    pages = [wrapped_lines[index:index + max_lines] for index in range(0, len(wrapped_lines), max_lines)] or [[]]

    objects = [None] * (3 + 2 * len(pages))
    page_ids = [4 + 2 * index for index in range(len(pages))]
    objects[0] = b"<< /Type /Catalog /Pages 2 0 R >>"
    kids = " ".join(f"{page_id} 0 R" for page_id in page_ids)
    objects[1] = f"<< /Type /Pages /Kids [{kids}] /Count {len(pages)} >>".encode("ascii")
    objects[2] = b"<< /Type /Font /Subtype /Type1 /BaseFont /Courier /Encoding /WinAnsiEncoding >>"

    for page_index, lines in enumerate(pages):
        page_id = page_ids[page_index]
        content_id = page_id + 1
        commands = [b"BT", b"/F1 12 Tf", f"{margin:.4f} {page_height - margin:.4f} Td".encode("ascii")]
        for line_index, line in enumerate(lines):
            if line_index:
                commands.append(f"0 -{line_height:.4f} Td".encode("ascii"))
            commands.append(b"(" + _pdf_escape(line) + b") Tj")
        commands.append(b"ET")
        stream = b"\n".join(commands)
        objects[page_id - 1] = (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {page_width:.4f} {page_height:.4f}] "
            f"/Resources << /Font << /F1 3 0 R >> >> /Contents {content_id} 0 R >>"
        ).encode("ascii")
        objects[content_id - 1] = (
            f"<< /Length {len(stream)} >>\nstream\n".encode("ascii") + stream + b"\nendstream"
        )

    output = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for object_number, body in enumerate(objects, start=1):
        offsets.append(len(output))
        output.extend(f"{object_number} 0 obj\n".encode("ascii"))
        output.extend(body)
        output.extend(b"\nendobj\n")

    xref_offset = len(output)
    output.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    output.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    output.extend(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref_offset}\n%%EOF\n".encode("ascii")
    )
    return bytes(output)


def save_unique_pdf(output_dir, pdf_bytes, long_taf, generated_at=None):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    if generated_at is None:
        generated_at = datetime.datetime.now(datetime.timezone.utc)
    elif generated_at.tzinfo is None:
        generated_at = generated_at.replace(tzinfo=datetime.timezone.utc)
    else:
        generated_at = generated_at.astimezone(datetime.timezone.utc)

    issue_time = resolve_issue_time(long_taf, generated_at)
    if issue_time:
        stem = "VABB_Combined_TAF_ISSUE_" + issue_time.strftime("%Y%m%d_%H%MZ")
    else:
        stem = "VABB_Combined_TAF_GENERATED_" + generated_at.strftime("%Y%m%d_%H%M%SZ")

    suffix = 0
    while True:
        suffix_text = "" if suffix == 0 else f"_{suffix:02d}"
        destination = output_dir / f"{stem}{suffix_text}.pdf"
        try:
            with destination.open("xb") as output_file:
                output_file.write(pdf_bytes)
            return destination
        except FileExistsError:
            suffix += 1
        except Exception:
            try:
                destination.unlink()
            except OSError:
                pass
            raise


class SingleInstanceLock:
    """An OS-managed file lock, released automatically if the process exits."""

    def __init__(self, lock_path):
        self.lock_path = Path(lock_path)
        self.handle = None

    def __enter__(self):
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        self.handle = self.lock_path.open("a+b")
        try:
            self.handle.seek(0, os.SEEK_END)
            if self.handle.tell() == 0:
                self.handle.write(b"\0")
                self.handle.flush()
            self.handle.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (OSError, BlockingIOError) as exc:
            self.handle.close()
            self.handle = None
            raise AlreadyRunningError("Another Auto-TAF downloader process is already running.") from exc
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        if self.handle is None:
            return
        try:
            self.handle.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
        finally:
            self.handle.close()
            self.handle = None


class TafDownloader:
    def __init__(self, base_url=DEFAULT_BASE_URL, output_dir=DEFAULT_OUTPUT_DIR,
                 timeout=600, attempts=3, opener=None, sleep_fn=time.sleep,
                 logger=None):
        self.base_url = base_url.rstrip("/")
        self.output_dir = Path(output_dir)
        self.timeout = timeout
        self.attempts = attempts
        self.sleep_fn = sleep_fn
        self.logger = logger or logging.getLogger("taf_downloader")
        self.opener = opener or build_opener(HTTPCookieProcessor(http.cookiejar.CookieJar()))
        self._validate_base_url()

    def _validate_base_url(self):
        parsed = urlsplit(self.base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise DownloadError("Base URL must be an HTTP or HTTPS website URL.")
        if parsed.username or parsed.password:
            raise DownloadError("Do not put credentials in the base URL; the current app does not require them.")

    def _open(self, request):
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                status = response.getcode()
                body = response.read()
                headers = response.headers
        except HTTPError as exc:
            if exc.code in TRANSIENT_HTTP_CODES:
                raise TemporaryDownloadError(f"Temporary HTTP {exc.code} from the Auto-TAF server.") from exc
            raise DownloadError(f"Auto-TAF server returned HTTP {exc.code}.") from exc
        except (URLError, TimeoutError, socket.timeout, ConnectionError, OSError) as exc:
            raise TemporaryDownloadError(f"Temporary connection error: {exc.__class__.__name__}.") from exc

        if status in TRANSIENT_HTTP_CODES:
            raise TemporaryDownloadError(f"Temporary HTTP {status} from the Auto-TAF server.")
        if status < 200 or status >= 300:
            raise DownloadError(f"Auto-TAF server returned HTTP {status}.")
        return body, headers

    def _generate_from_endpoint(self):
        page_url = self.base_url + "/"
        get_request = Request(page_url, headers={"User-Agent": "AutoTAF-Windows-Downloader/1.0"})
        page_body, page_headers = self._open(get_request)
        page_html = _decode_response(page_body, page_headers)
        page_parser = GenerationPageParser()
        page_parser.feed(page_html)
        page_parser.close()

        generation_form = None
        for form in page_parser.forms:
            action = form["action"].strip()
            if action and urlsplit(urljoin(page_url, action)).path.rstrip("/").endswith("/generate"):
                generation_form = form
                break
        if generation_form is None:
            raise DownloadError("The website's GET / page did not expose the expected /generate form.")

        fields = dict(generation_form["fields"])
        fields["station"] = "VABB"
        post_url = urljoin(page_url, generation_form["action"])
        origin = f"{urlsplit(self.base_url).scheme}://{urlsplit(self.base_url).netloc}"
        post_request = Request(
            post_url,
            data=urlencode(fields).encode("ascii"),
            headers={
                "User-Agent": "AutoTAF-Windows-Downloader/1.0",
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "text/html",
                "Referer": page_url,
                "Origin": origin,
            },
            method="POST",
        )
        result_body, result_headers = self._open(post_request)
        result_html = _decode_response(result_body, result_headers)
        _, long_taf, short_taf, error_text = parse_tafs(result_html)

        if error_text:
            lowered = error_text.lower()
            if any(token in lowered for token in ("network", "timeout", "connection", "imd error", "ogimet error", "temporar")):
                raise TemporaryDownloadError(f"The application reported: {error_text}")
            raise DownloadError(f"The application reported: {error_text}")
        if not long_taf or not short_taf:
            raise DownloadError("The generation response did not contain both #long-taf and #short-taf.")
        for label, taf in (("Long", long_taf), ("Short", short_taf)):
            header = re.match(r"^TAF\s+(\w{4})\s+", taf, re.IGNORECASE)
            if not header or header.group(1).upper() != "VABB":
                raise DownloadError(f"The {label.lower()} TAF is missing the expected VABB TAF header.")
            if re.search(r"\bNIL\s*=?\s*$", taf, re.IGNORECASE):
                raise DownloadError(f"The {label.lower()} TAF contains NIL; no forecast PDF was saved.")

        source_status = _header(result_headers, FRESHNESS_HEADER).strip().lower()
        if source_status == "cache_fallback":
            raise TemporaryDownloadError("The app used cached IMD data after its live download failed; no PDF was saved.")
        if source_status != "downloaded":
            raise DownloadError(
                "The app did not confirm a successful IMD download. Deploy the updated app with its "
                f"{FRESHNESS_HEADER} response header before scheduling downloads."
            )
        return long_taf, short_taf

    def _generate_with_retries(self):
        if self.attempts < 1:
            raise DownloadError("Attempt count must be at least 1.")
        for attempt in range(1, self.attempts + 1):
            try:
                return self._generate_from_endpoint()
            except TemporaryDownloadError:
                if attempt >= self.attempts:
                    raise
                delay = min(5 * (2 ** (attempt - 1)), 60)
                self.logger.warning("Temporary generation failure (attempt %s/%s); retrying in %s seconds.", attempt, self.attempts, delay)
                self.sleep_fn(delay)
        raise DownloadError("No generation attempt completed.")

    def download_once(self):
        self.output_dir.mkdir(parents=True, exist_ok=True)
        lock_path = self.output_dir / ".autotaf_downloader.lock"
        with SingleInstanceLock(lock_path):
            self.logger.info("Requesting fresh VABB TAFs from %s", self.base_url)
            long_taf, short_taf = self._generate_with_retries()
            generated_at = datetime.datetime.now(datetime.timezone.utc)
            pdf_bytes = build_combined_pdf(long_taf, short_taf)
            destination = save_unique_pdf(self.output_dir, pdf_bytes, long_taf, generated_at)
            self.logger.info("Saved combined VABB TAF PDF to %s", destination)
            return destination


def configure_logging(output_dir):
    log_dir = Path(output_dir) / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("taf_downloader")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    handler = RotatingFileHandler(log_dir / "autotaf_downloader.log", maxBytes=1_000_000, backupCount=5, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s", datefmt="%Y-%m-%dT%H:%M:%S%z"))
    logger.addHandler(handler)
    console = logging.StreamHandler()
    console.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(console)
    return logger


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Save fresh VABB Long and Short TAFs as a combined PDF.")
    parser.add_argument("--base-url", default=os.environ.get("AUTO_TAF_BASE_URL", DEFAULT_BASE_URL),
                        help="Existing Auto-TAF site URL (HTTP is supported; default: %(default)s)")
    parser.add_argument("--output-dir", default=os.environ.get("AUTO_TAF_OUTPUT_DIR", str(DEFAULT_OUTPUT_DIR)),
                        help="Local PDF directory (default: %(default)s)")
    parser.add_argument("--timeout", type=int, default=int(os.environ.get("AUTO_TAF_TIMEOUT_SECONDS", "600")),
                        help="Per-request timeout in seconds (default: %(default)s)")
    parser.add_argument("--attempts", type=int, default=int(os.environ.get("AUTO_TAF_MAX_ATTEMPTS", "3")),
                        help="Total tries for temporary failures (default: %(default)s)")
    args = parser.parse_args(argv)
    if args.timeout < 1:
        parser.error("--timeout must be a positive number")
    if args.attempts < 1:
        parser.error("--attempts must be a positive number")
    return args


def main(argv=None):
    args = parse_args(argv)
    output_dir = Path(args.output_dir)
    logger = configure_logging(output_dir)
    try:
        downloader = TafDownloader(args.base_url, output_dir, args.timeout, args.attempts, logger=logger)
        path = downloader.download_once()
    except AlreadyRunningError as exc:
        logger.warning("%s", exc)
        return 0
    except Exception as exc:
        logger.exception("VABB TAF PDF download failed: %s", exc)
        return 1
    print(f"Saved PDF: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
