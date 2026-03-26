"""
Concrete workflow stages for the scraping pipeline.

Pipeline:
    Fetch (page-level) → Extract → Download → Store
                         ───────────────────────────
                         These 3 run per-document via WorkflowEngine

Fetch is handled outside the engine (it produces the batch).
Extract, Download, Store are the pipeline stages.
"""

from concurrent.futures import ThreadPoolExecutor, as_completed

from workflow.engine import Stage
from workflow.models import WorkflowItem, StageStatus
from sources.base import BaseSource
from tools.state_manager import StateManager
from tools.http_client import HttpClient
from tools.pdf_downloader import download_pdfs_for_document


# ── Stage 1: Extract ─────────────────────────────────────────────────────────

class ExtractStage(Stage):
    """
    Extract metadata and PDF asset URLs from raw document dicts.

    Input:  item.raw_doc (dict from API)
    Output: item.metadata (DocumentMetadata) + item.pdf_assets (list[PdfAsset])
    """

    @property
    def name(self) -> str:
        return "extract"

    def __init__(self, source: BaseSource):
        self.source = source

    def process(self, item: WorkflowItem) -> WorkflowItem:
        item.metadata = self.source.extract_metadata(item.raw_doc)
        item.pdf_assets = self.source.get_pdf_assets(item.raw_doc)

        # Display document info
        meta = item.metadata
        print(f"\n    [{item.index}] {meta.title_primary}")
        if meta.title_secondary:
            print(f"          {meta.title_secondary}")
        print(
            f"          num={meta.number} | date={meta.date}"
            f" | {meta.category} | {meta.status}"
        )

        return item


# ── Stage 2: Download ────────────────────────────────────────────────────────

class DownloadStage(Stage):
    """
    Download PDFs for each document. Supports parallel downloads.

    Input:  item.pdf_assets (list[PdfAsset])
    Output: item.pdf_results (dict[str, bool])
    """

    @property
    def name(self) -> str:
        return "download"

    def __init__(
        self,
        source: BaseSource,
        client: HttpClient,
        state_mgr: StateManager,
        enabled: bool = True,
        max_workers: int = 3,
    ):
        self.source = source
        self.client = client
        self.state_mgr = state_mgr
        self.enabled = enabled
        self.max_workers = max_workers

    @staticmethod
    def _safe_dirname(text: str, max_len: int = 80) -> str:
        for ch in r'/\\:*?"<>|':
            text = text.replace(ch, "_")
        return text.strip()[:max_len].rstrip(" .")

    def _download_item(self, item: WorkflowItem) -> WorkflowItem:
        """Download all PDFs for one item."""
        if not item.pdf_assets:
            item.pdf_results = {}
            return item

        meta = item.metadata
        label = meta.title_secondary or meta.title_primary or f"doc_{item.index}"
        has_latin = any(c.isascii() and c.isalpha() for c in label)
        if not has_latin:
            label = (
                f"doc_{meta.number}".replace("/", "_")
                if meta.number
                else f"doc_{item.index}"
            )

        doc_dir = str(
            self.state_mgr.pdf_dir
            / f"{item.index:05d}_{self._safe_dirname(label)}"
        )
        item.pdf_results = download_pdfs_for_document(
            item.pdf_assets, doc_dir, self.source, self.client
        )

        if not any(item.pdf_results.values()):
            self.state_mgr.log_failure(
                meta.source_id,
                meta.title_primary or meta.title_secondary,
                "no PDFs available",
            )

        return item

    def process(self, item: WorkflowItem) -> WorkflowItem:
        return self._download_item(item)

    def process_batch(self, items: list[WorkflowItem]) -> list[WorkflowItem]:
        """Download PDFs — in parallel if max_workers > 1."""

        # If downloads are disabled, skip everything
        if not self.enabled:
            for item in items:
                if not item.failed:
                    item.pdf_results = {}
                    item.current_stage = self.name
                    item.status = StageStatus.COMPLETED
                    item.stages_completed.append(self.name)
            return items

        # Separate active vs. already-failed items
        active = [i for i in items if not i.failed]
        if not active:
            return items

        # Sequential mode
        if self.max_workers <= 1:
            return super().process_batch(items)

        # Parallel mode
        with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
            futures = {}
            for item in active:
                item.current_stage = self.name
                item.status = StageStatus.PROCESSING
                futures[pool.submit(self._download_item, item)] = item

            for future in as_completed(futures):
                item = futures[future]
                try:
                    future.result()
                    item.status = StageStatus.COMPLETED
                    item.stages_completed.append(self.name)
                except Exception as exc:
                    item.status = StageStatus.FAILED
                    item.error = f"[{self.name}] {exc}"
                    print(f"      ✗ [{self.name}] {exc}")

        return items


# ── Stage 3: Store ───────────────────────────────────────────────────────────

class StoreStage(Stage):
    """
    Persist metadata JSON and append a row to the CSV.

    Input:  item.raw_doc + item.metadata + item.pdf_results
    Output: files written to disk
    """

    @property
    def name(self) -> str:
        return "store"

    def __init__(self, source: BaseSource, state_mgr: StateManager):
        self.source = source
        self.state_mgr = state_mgr

    def process(self, item: WorkflowItem) -> WorkflowItem:
        # Save raw API response as JSON
        self.state_mgr.save_metadata_json(item.raw_doc, item.index)

        # Build CSV row and append
        csv_row = self.source.metadata_to_csv_row(
            item.metadata, item.pdf_results or {}, item.index
        )
        self.state_mgr.append_csv(csv_row, self.source.get_csv_headers())

        return item
