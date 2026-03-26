"""
Base class for all scraping sources.
Each new website source must subclass this and implement all abstract methods.

To add a new source:
    1. Copy sources/_template.py → sources/your_source.py
    2. Implement the abstract methods
    3. Register in sources/__init__.py
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class DocumentPage:
    """Standardized response from fetching a page of documents."""
    documents: list[dict]       # list of raw document dicts from the source API
    total_count: int            # total documents available on this source
    page: int
    per_page: int
    status_ok: bool             # whether the API returned a healthy response


@dataclass
class PdfAsset:
    """One downloadable PDF (or file) associated with a document."""
    label: str          # e.g. "original", "translated", "printed"
    url: str            # full download URL
    filename: str       # e.g. "original.pdf"


@dataclass
class DocumentMetadata:
    """Normalized metadata extracted from a source-specific document dict."""
    source_id: str              # unique ID from the source (e.g. encrypted_id)
    title_primary: str          # primary title (Arabic for NCAR)
    title_secondary: str = ""   # secondary title (English for NCAR)
    number: str = ""
    date: str = ""
    status: str = ""            # e.g. "active", "inactive", "سارية"
    category: str = ""          # e.g. "Royal Decree"
    extra: dict = field(default_factory=dict)  # source-specific extra fields


class BaseSource(ABC):
    """
    Abstract base class for scraping sources.

    Every new source plugin must subclass this and implement all @abstractmethod
    members. The agent loop calls these methods generically — no source-specific
    logic leaks into agent.py.
    """

    # ── identity ────────────────────────────────────────────────────────────

    @property
    @abstractmethod
    def name(self) -> str:
        """Short machine-friendly name, e.g. 'ncar'. Used for output dirs and state files."""
        ...

    @property
    @abstractmethod
    def display_name(self) -> str:
        """Human-readable name, e.g. 'NCAR (ncar.gov.sa)'."""
        ...

    @property
    @abstractmethod
    def base_url(self) -> str:
        """Base URL of the source website."""
        ...

    # ── tunables (override to customise) ────────────────────────────────────

    @property
    def default_per_page(self) -> int:
        """How many documents per API page (default 10)."""
        return 10

    @property
    def delay_between_docs(self) -> float:
        """Seconds to wait between processing each document (default 0.3)."""
        return 0.3

    @property
    def delay_between_pages(self) -> float:
        """Seconds to wait between fetching pages (default 0.5)."""
        return 0.5

    # ── abstract methods every source must implement ────────────────────────

    @abstractmethod
    def fetch_page(self, page: int, per_page: int = 10) -> Optional[DocumentPage]:
        """
        Fetch one page of documents from the source API.

        Args:
            page:     1-based page number
            per_page: items per page

        Returns:
            DocumentPage on success, None if all retries fail.
        """
        ...

    @abstractmethod
    def get_pdf_assets(self, doc: dict) -> list[PdfAsset]:
        """
        Given a raw document dict, return the list of downloadable PDF assets.
        Return an empty list if no PDFs are available for this document.
        """
        ...

    @abstractmethod
    def extract_metadata(self, doc: dict) -> DocumentMetadata:
        """
        Extract and normalize metadata from a raw source-specific document dict.
        """
        ...

    @abstractmethod
    def get_csv_headers(self) -> list[str]:
        """Return the ordered list of CSV column headers for this source."""
        ...

    @abstractmethod
    def metadata_to_csv_row(
        self,
        meta: DocumentMetadata,
        pdf_results: dict[str, bool],
        index: int,
    ) -> dict:
        """
        Convert a DocumentMetadata + PDF download results into a CSV row dict.
        Keys must match the list returned by get_csv_headers().
        """
        ...

    # ── optional hooks (override if needed) ─────────────────────────────────

    def validate_pdf(self, header_bytes: bytes) -> bool:
        """
        Validate that a downloaded file is actually a PDF.
        Override if the source serves files with non-standard magic bytes.
        Default: checks for %PDF magic.
        """
        return header_bytes[:4] == b"%PDF"
