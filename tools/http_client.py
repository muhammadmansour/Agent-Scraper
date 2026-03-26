"""
Shared HTTP client with retry logic, rate-limit handling, and timeouts.
Used by all source plugins and the generic PDF downloader.
"""

import time
import requests
from pathlib import Path
from typing import Optional, Callable


DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


class HttpClient:
    """
    Thin wrapper around requests with:
      - Configurable timeouts
      - Automatic retries with backoff
      - Rate-limit (HTTP 429) handling
      - Streaming file downloads with optional validation
    """

    def __init__(self, timeout: int = 30, user_agent: str = DEFAULT_UA):
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers["User-Agent"] = user_agent

    # ── JSON GET ────────────────────────────────────────────────────────────

    def get_json(
        self,
        url: str,
        headers: Optional[dict] = None,
        retries: int = 3,
    ) -> Optional[dict]:
        """
        GET a JSON endpoint with retries and rate-limit handling.

        Returns:
            Parsed JSON dict on success, None if all retries fail.
        """
        for attempt in range(1, retries + 1):
            try:
                resp = self.session.get(url, headers=headers, timeout=self.timeout)

                if resp.status_code == 429:
                    wait = 30 * attempt
                    print(f"  [rate limit] sleeping {wait}s...")
                    time.sleep(wait)
                    continue

                if resp.status_code != 200:
                    print(f"  [HTTP {resp.status_code}] {url[:80]}… attempt {attempt}/{retries}")
                    if attempt < retries:
                        time.sleep(5)
                    continue

                return resp.json()

            except requests.exceptions.Timeout:
                print(f"  [timeout] attempt {attempt}/{retries}")
                if attempt < retries:
                    time.sleep(5 * attempt)

            except requests.exceptions.ConnectionError as exc:
                print(f"  [connection error] {exc}")
                if attempt < retries:
                    time.sleep(10)

            except Exception as exc:
                print(f"  [error] {exc}")
                if attempt < retries:
                    time.sleep(5)

        return None

    # ── file download ───────────────────────────────────────────────────────

    def download_file(
        self,
        url: str,
        output_path: str,
        headers: Optional[dict] = None,
        retries: int = 3,
        validator: Optional[Callable[[bytes], bool]] = None,
    ) -> bool:
        """
        Download a file with streaming, retries, and optional validation.

        Args:
            url:         Full download URL
            output_path: Where to save the file
            headers:     Extra HTTP headers
            retries:     Number of retry attempts
            validator:   callable(first_64_bytes) → bool; validates the file header

        Returns:
            True if the file was downloaded (or already existed) successfully.
        """
        out = Path(output_path)

        # Skip if already exists and valid
        if out.exists() and out.stat().st_size > 0:
            if validator is None:
                return True
            try:
                with open(out, "rb") as f:
                    header = f.read(64)
                if validator(header):
                    return True
            except Exception:
                pass

        out.parent.mkdir(parents=True, exist_ok=True)
        tmp = out.with_suffix(".tmp")

        for attempt in range(1, retries + 1):
            try:
                resp = self.session.get(
                    url, headers=headers, timeout=self.timeout, stream=True,
                )

                if resp.status_code == 429:
                    wait = 30 * attempt
                    print(f"      [rate limit] sleeping {wait}s...")
                    time.sleep(wait)
                    continue

                if resp.status_code in (403, 404):
                    # Not available — not an error for the caller
                    return False

                if resp.status_code != 200:
                    print(f"      [HTTP {resp.status_code}] attempt {attempt}/{retries}")
                    if attempt < retries:
                        time.sleep(5)
                    continue

                # Stream to temp file
                with open(tmp, "wb") as f:
                    for chunk in resp.iter_content(chunk_size=8192):
                        f.write(chunk)

                # Validate
                if validator is not None:
                    try:
                        with open(tmp, "rb") as f:
                            header = f.read(64)
                        if not validator(header):
                            tmp.unlink(missing_ok=True)
                            print(f"      [invalid file] attempt {attempt}/{retries}")
                            if attempt < retries:
                                time.sleep(3)
                            continue
                    except Exception:
                        tmp.unlink(missing_ok=True)
                        continue

                # Move to final path
                tmp.rename(out)
                return True

            except requests.exceptions.Timeout:
                print(f"      [timeout] attempt {attempt}/{retries}")
                if attempt < retries:
                    time.sleep(5 * attempt)

            except requests.exceptions.ConnectionError as exc:
                print(f"      [connection error] {exc}")
                if attempt < retries:
                    time.sleep(10)

            except Exception as exc:
                print(f"      [error] {exc}")
                if attempt < retries:
                    time.sleep(5)

        # Clean up
        tmp.unlink(missing_ok=True)
        out.unlink(missing_ok=True)
        return False
