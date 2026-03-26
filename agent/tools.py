"""
Agent tools — actions the LLM can invoke.

Each tool is a method on AgentTools. The TOOL_DECLARATIONS list provides
the JSON schema that Gemini uses for function calling.
"""

import time
from datetime import datetime, timezone

from sources import get_source, SOURCES
from sources.base import BaseSource
from tools.state_manager import StateManager
from tools.http_client import HttpClient
from workflow.engine import WorkflowEngine
from workflow.models import WorkflowItem
from workflow.stages import ExtractStage, DownloadStage, StoreStage


# ── Tool Declarations (JSON schema for Gemini function calling) ──────────────

TOOL_DECLARATIONS = [
    {
        "name": "scrape_pages",
        "description": (
            "Scrape a range of pages from a source. Fetches documents, "
            "extracts metadata, downloads PDFs, and saves everything to disk. "
            "Returns a summary of what was scraped."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "source": {
                    "type": "string",
                    "description": "Source name (e.g. 'ncar')",
                },
                "start_page": {
                    "type": "integer",
                    "description": "First page to scrape (1-based)",
                },
                "end_page": {
                    "type": "integer",
                    "description": "Last page to scrape (inclusive)",
                },
            },
            "required": ["source", "start_page", "end_page"],
        },
    },
    {
        "name": "check_source_health",
        "description": (
            "Probe a source's API to check if it's reachable and responding. "
            "Returns status, total documents, and response time."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "source": {
                    "type": "string",
                    "description": "Source name to check",
                },
            },
            "required": ["source"],
        },
    },
    {
        "name": "get_progress",
        "description": (
            "Get current scraping progress across all sources. "
            "Returns per-source stats: pages done, docs processed, "
            "PDFs downloaded, failures, and estimated remaining."
        ),
        "parameters": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "get_failures",
        "description": (
            "Get the list of failed downloads for a source. "
            "Returns failure reasons and counts by type."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "source": {
                    "type": "string",
                    "description": "Source name",
                },
            },
            "required": ["source"],
        },
    },
    {
        "name": "retry_failures",
        "description": (
            "Retry all previously failed document downloads for a source. "
            "Returns how many were recovered."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "source": {
                    "type": "string",
                    "description": "Source name",
                },
            },
            "required": ["source"],
        },
    },
    {
        "name": "adjust_workers",
        "description": (
            "Change the number of parallel download workers. "
            "Use 1 for rate-limited sources, up to 5 for healthy ones."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "workers": {
                    "type": "integer",
                    "description": "Number of parallel workers (1-5)",
                },
            },
            "required": ["workers"],
        },
    },
    {
        "name": "finish",
        "description": (
            "Signal that the agent is done. Call this when all sources are "
            "fully scraped, or when no more progress can be made."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "reason": {
                    "type": "string",
                    "description": "Why the agent is stopping",
                },
            },
            "required": ["reason"],
        },
    },
]


# ── Tool Execution ───────────────────────────────────────────────────────────

class AgentTools:
    """
    Provides the tools that the LLM agent can invoke.

    Each tool method corresponds to a TOOL_DECLARATIONS entry.
    Call execute(name, args) to run a tool by name.
    """

    def __init__(self, download_pdf: bool = True, max_workers: int = 3):
        self.download_pdf = download_pdf
        self.max_workers = max_workers
        self._state_managers: dict[str, StateManager] = {}
        self._clients: dict[str, HttpClient] = {}
        self.finished = False
        self.finish_reason = ""

    def _get_source(self, name: str) -> BaseSource:
        return get_source(name)

    def _get_state_mgr(self, source_name: str) -> StateManager:
        if source_name not in self._state_managers:
            self._state_managers[source_name] = StateManager(source_name)
        return self._state_managers[source_name]

    def _get_client(self, source: BaseSource) -> HttpClient:
        if source.name not in self._clients:
            self._clients[source.name] = HttpClient(verify_ssl=source.verify_ssl)
        return self._clients[source.name]

    # ── dispatch ─────────────────────────────────────────────────────────

    def execute(self, tool_name: str, args: dict) -> dict:
        """Execute a tool by name. Returns a result dict."""
        method = getattr(self, tool_name, None)
        if method is None:
            return {"error": f"Unknown tool: {tool_name}"}
        try:
            return method(**args)
        except Exception as exc:
            return {"error": f"{tool_name} failed: {exc}"}

    # ── tools ────────────────────────────────────────────────────────────

    def scrape_pages(self, source: str, start_page: int, end_page: int) -> dict:
        """Scrape a range of pages from a source."""
        src = self._get_source(source)
        state_mgr = self._get_state_mgr(source)
        client = self._get_client(src)

        # Build pipeline
        pipeline = WorkflowEngine(stages=[
            ExtractStage(src),
            DownloadStage(
                src, client, state_mgr,
                enabled=self.download_pdf,
                max_workers=self.max_workers,
            ),
            StoreStage(src, state_mgr),
        ])

        state = state_mgr.load_state()
        processed = state["processed_count"]
        per_page = src.default_per_page
        total_docs_scraped = 0
        total_pdfs = 0
        total_failures = 0
        pages_done = 0

        for page in range(start_page, end_page + 1):
            print(f"\n{'━' * 50}")
            print(f"  Page {page} (source: {source})")
            print(f"{'━' * 50}")

            page_data = src.fetch_page(page=page, per_page=per_page)
            if not page_data or not page_data.status_ok:
                print(f"  ✗ Failed page {page}")
                state_mgr.log_failure("page", f"page {page}", "fetch failed")
                total_failures += 1
                continue

            if not page_data.documents:
                print("  ⚠ Empty page — reached end")
                break

            # Build batch
            items = []
            for doc in page_data.documents:
                processed += 1
                items.append(WorkflowItem(index=processed, raw_doc=doc))

            # Run pipeline
            results = pipeline.run_batch(items)

            # Tally
            for item in results:
                total_docs_scraped += 1
                total_pdfs += item.pdf_count
                if item.failed:
                    total_failures += 1

            pages_done += 1
            state_mgr.update_state(page, processed, page_data.total_count)

            time.sleep(src.delay_between_pages)

        return {
            "source": source,
            "pages_scraped": pages_done,
            "page_range": f"{start_page}-{end_page}",
            "documents_scraped": total_docs_scraped,
            "pdfs_downloaded": total_pdfs,
            "failures": total_failures,
            "total_processed_so_far": processed,
        }

    def check_source_health(self, source: str) -> dict:
        """Check if a source is reachable."""
        src = self._get_source(source)
        start = time.time()
        try:
            probe = src.fetch_page(page=1, per_page=1)
            elapsed = round(time.time() - start, 2)
            if probe and probe.status_ok:
                return {
                    "source": source,
                    "status": "healthy",
                    "total_documents": probe.total_count,
                    "response_time_seconds": elapsed,
                }
            else:
                return {
                    "source": source,
                    "status": "unhealthy",
                    "response_time_seconds": elapsed,
                    "detail": "API returned bad status or no data",
                }
        except Exception as exc:
            elapsed = round(time.time() - start, 2)
            return {
                "source": source,
                "status": "unreachable",
                "response_time_seconds": elapsed,
                "error": str(exc),
            }

    def get_progress(self) -> dict:
        """Get progress across all sources."""
        progress = {}
        for name in SOURCES:
            state_mgr = self._get_state_mgr(name)
            state = state_mgr.load_state()
            failures = state_mgr.get_failures()
            pdf_count = (
                sum(1 for _ in state_mgr.pdf_dir.glob("**/*.pdf"))
                if state_mgr.pdf_dir.exists()
                else 0
            )

            total = state.get("total_docs", 0)
            done = state.get("processed_count", 0)
            per_page = 10  # default
            total_pages = (total + per_page - 1) // per_page if total > 0 else 0

            progress[name] = {
                "last_page": state.get("last_page", 0),
                "total_pages": total_pages,
                "processed_count": done,
                "total_documents": total,
                "remaining": max(0, total - done),
                "pdfs_downloaded": pdf_count,
                "failures": len(failures),
                "percent_complete": round(done / total * 100, 1) if total > 0 else 0,
            }

        return {"sources": progress}

    def get_failures(self, source: str) -> dict:
        """Get failures for a source."""
        state_mgr = self._get_state_mgr(source)
        failures = state_mgr.get_failures()

        # Group by reason
        by_reason: dict[str, int] = {}
        for f in failures:
            reason = f.get("reason", "unknown")
            by_reason[reason] = by_reason.get(reason, 0) + 1

        return {
            "source": source,
            "total_failures": len(failures),
            "by_reason": by_reason,
            "recent_5": failures[-5:] if failures else [],
        }

    def retry_failures(self, source: str) -> dict:
        """Retry failed downloads for a source."""
        src = self._get_source(source)
        state_mgr = self._get_state_mgr(source)
        client = self._get_client(src)
        failures = state_mgr.get_failures()

        doc_failures = [f for f in failures if f.get("id", "") != "page"]
        if not doc_failures:
            return {"source": source, "message": "No document failures to retry"}

        from tools.pdf_downloader import download_pdfs_for_document

        recovered = 0
        still_failing = 0

        for failure in doc_failures:
            doc_id = failure["id"]
            fake_doc = {"id": doc_id}
            assets = src.get_pdf_assets(fake_doc)
            if not assets:
                still_failing += 1
                continue

            title = failure.get("title", "unknown")
            safe_title = title[:40].replace("/", "_").replace("\\", "_")
            doc_dir = str(state_mgr.pdf_dir / f"retry_{safe_title}")
            results = download_pdfs_for_document(assets, doc_dir, src, client)

            if any(results.values()):
                recovered += 1
            else:
                still_failing += 1

            time.sleep(src.delay_between_docs)

        return {
            "source": source,
            "total_retried": len(doc_failures),
            "recovered": recovered,
            "still_failing": still_failing,
        }

    def adjust_workers(self, workers: int) -> dict:
        """Adjust parallel download workers."""
        old = self.max_workers
        self.max_workers = max(1, min(workers, 5))
        return {
            "previous_workers": old,
            "new_workers": self.max_workers,
        }

    def finish(self, reason: str) -> dict:
        """Signal the agent is done."""
        self.finished = True
        self.finish_reason = reason
        return {"status": "finished", "reason": reason}
