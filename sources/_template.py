"""
Source: [YOUR SOURCE NAME]
Website: [URL]

Copy this file → sources/your_source.py and implement all methods.
Then register it in sources/__init__.py.

Steps:
    1. cp sources/_template.py sources/my_new_source.py
    2. Implement the 5 abstract methods + __init__
    3. In sources/__init__.py, add:
           from sources.my_new_source import MyNewSource
           SOURCES["my_new_source"] = MyNewSource
    4. Run:  python agent.py --source my_new_source --test
"""

from typing import Optional

from sources.base import BaseSource, DocumentPage, PdfAsset, DocumentMetadata
from tools.http_client import HttpClient


class TemplateSource(BaseSource):
    """Replace this docstring with a description of the source."""

    # ── identity ────────────────────────────────────────────────────────────

    @property
    def name(self) -> str:
        return "template"  # short, no spaces, used for directory names

    @property
    def display_name(self) -> str:
        return "Template Source (example.com)"

    @property
    def base_url(self) -> str:
        return "https://example.com"

    # ── tunables (optional overrides) ───────────────────────────────────────

    @property
    def default_per_page(self) -> int:
        return 10

    @property
    def delay_between_docs(self) -> float:
        return 0.3

    @property
    def delay_between_pages(self) -> float:
        return 0.5

    # ── constructor ─────────────────────────────────────────────────────────

    def __init__(self):
        self._client = HttpClient()

    # ── fetch_page ──────────────────────────────────────────────────────────

    def fetch_page(self, page: int, per_page: int = 10) -> Optional[DocumentPage]:
        """
        Fetch one page of documents from the source API.

        TODO: Replace with actual API call. Example:

            url = f"{self.base_url}/api/documents?page={page}&size={per_page}"
            data = self._client.get_json(url)
            if data is None:
                return None
            return DocumentPage(
                documents=data["items"],
                total_count=data["total"],
                page=page,
                per_page=per_page,
                status_ok=True,
            )
        """
        raise NotImplementedError("Implement fetch_page for your source")

    # ── get_pdf_assets ──────────────────────────────────────────────────────

    def get_pdf_assets(self, doc: dict) -> list[PdfAsset]:
        """
        Return downloadable file assets for one document.

        TODO: Replace with actual logic. Example:

            doc_id = doc["id"]
            return [
                PdfAsset(label="main", url=f"{self.base_url}/files/{doc_id}.pdf", filename="main.pdf"),
            ]
        """
        raise NotImplementedError("Implement get_pdf_assets for your source")

    # ── extract_metadata ────────────────────────────────────────────────────

    def extract_metadata(self, doc: dict) -> DocumentMetadata:
        """
        Normalize source-specific fields into DocumentMetadata.

        TODO: Replace with actual field mapping. Example:

            return DocumentMetadata(
                source_id=doc["id"],
                title_primary=doc["title"],
                number=doc.get("ref_number", ""),
                date=doc.get("publish_date", ""),
            )
        """
        raise NotImplementedError("Implement extract_metadata for your source")

    # ── CSV ─────────────────────────────────────────────────────────────────

    def get_csv_headers(self) -> list[str]:
        """
        Return ordered column names for the CSV output.

        TODO: Example:
            return ["index", "id", "title", "date", "has_pdf"]
        """
        raise NotImplementedError("Implement get_csv_headers for your source")

    def metadata_to_csv_row(
        self,
        meta: DocumentMetadata,
        pdf_results: dict[str, bool],
        index: int,
    ) -> dict:
        """
        Build a CSV row dict from metadata + PDF results.
        Keys must match get_csv_headers().

        TODO: Example:
            return {
                "index": index,
                "id": meta.source_id,
                "title": meta.title_primary,
                "date": meta.date,
                "has_pdf": int(pdf_results.get("main", False)),
            }
        """
        raise NotImplementedError("Implement metadata_to_csv_row for your source")
