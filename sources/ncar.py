"""
Source: NCAR — Saudi National Center for Archives and Records
Website: https://ncar.gov.sa/rules-regulations
Total documents: ~6631 (as of 2025)

API endpoints:
    List:    GET /api/index.php/api/documents/list/{page}/{per_page}/approveDate/ASC
    PDF:     GET /api/index.php/api/resource/{encrypted_id}/Documents/{type}
    Detail:  GET /api/index.php/api/resource/{encrypted_id}
"""

import sys
import os
from typing import Optional

# Ensure tools/ is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sources.base import BaseSource, DocumentPage, PdfAsset, DocumentMetadata
from tools.http_client import HttpClient


class NcarSource(BaseSource):
    """NCAR document scraping source."""

    # ── identity ────────────────────────────────────────────────────────────

    @property
    def name(self) -> str:
        return "ncar"

    @property
    def display_name(self) -> str:
        return "NCAR — ncar.gov.sa"

    @property
    def base_url(self) -> str:
        return "https://ncar.gov.sa"

    # ── tunables ────────────────────────────────────────────────────────────

    @property
    def default_per_page(self) -> int:
        return 10

    @property
    def delay_between_docs(self) -> float:
        return 0.3

    @property
    def delay_between_pages(self) -> float:
        return 0.5

    # ── internals ───────────────────────────────────────────────────────────

    API_BASE = "https://ncar.gov.sa/api/index.php/api"

    EXTRA_HEADERS = {
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "ar,en;q=0.9",
        "Referer": "https://ncar.gov.sa/rules-regulations",
    }

    PDF_TYPES = {
        "OriginalAttachPath":   ("original",   "original.pdf"),
        "TranslatedAttachPath": ("translated", "translated.pdf"),
        "PrintedAttachPath":    ("printed",    "printed.pdf"),
    }

    def __init__(self):
        self._client = HttpClient()

    # ── fetch_page ──────────────────────────────────────────────────────────

    def fetch_page(self, page: int, per_page: int = 10) -> Optional[DocumentPage]:
        url = f"{self.API_BASE}/documents/list/{page}/{per_page}/approveDate/ASC"

        data = self._client.get_json(url, headers=self.EXTRA_HEADERS, retries=3)
        if data is None:
            return None

        if data.get("status") != 1:
            # Retry once
            print(f"  [NCAR] status={data.get('status')} — retrying…")
            import time
            time.sleep(5)
            data = self._client.get_json(url, headers=self.EXTRA_HEADERS, retries=1)
            if data is None or data.get("status") != 1:
                return None

        return DocumentPage(
            documents=data.get("data", []),
            total_count=data.get("dataLength", 0),
            page=page,
            per_page=per_page,
            status_ok=True,
        )

    # ── get_pdf_assets ──────────────────────────────────────────────────────

    def get_pdf_assets(self, doc: dict) -> list[PdfAsset]:
        enc_id = doc.get("id", "")
        if not enc_id:
            return []

        assets = []
        for api_type, (label, filename) in self.PDF_TYPES.items():
            url = f"{self.API_BASE}/resource/{enc_id}/Documents/{api_type}"
            assets.append(PdfAsset(label=label, url=url, filename=filename))
        return assets

    # ── extract_metadata ────────────────────────────────────────────────────

    def extract_metadata(self, doc: dict) -> DocumentMetadata:
        approves = doc.get("Approves", [])
        approve_type = approves[0].get("name_en", "") if approves else ""
        marker_en = doc.get("marker", {}).get("title_en", "") if isinstance(doc.get("marker"), dict) else ""

        return DocumentMetadata(
            source_id=doc.get("id", ""),
            title_primary=doc.get("title_ar", ""),
            title_secondary=doc.get("title_en", ""),
            number=doc.get("number", ""),
            date=doc.get("approve_date", ""),
            status=doc.get("is_valid", ""),
            category=approve_type,
            extra={"marker": marker_en},
        )

    # ── CSV ─────────────────────────────────────────────────────────────────

    def get_csv_headers(self) -> list[str]:
        return [
            "index", "encrypted_id", "number", "title_ar", "title_en",
            "approve_type", "approve_date", "is_valid", "marker",
            "has_original", "has_translated", "has_printed",
        ]

    def metadata_to_csv_row(
        self,
        meta: DocumentMetadata,
        pdf_results: dict[str, bool],
        index: int,
    ) -> dict:
        return {
            "index":          index,
            "encrypted_id":   meta.source_id,
            "number":         meta.number,
            "title_ar":       meta.title_primary,
            "title_en":       meta.title_secondary,
            "approve_type":   meta.category,
            "approve_date":   meta.date,
            "is_valid":       meta.status,
            "marker":         meta.extra.get("marker", ""),
            "has_original":   int(pdf_results.get("original", False)),
            "has_translated": int(pdf_results.get("translated", False)),
            "has_printed":    int(pdf_results.get("printed", False)),
        }
