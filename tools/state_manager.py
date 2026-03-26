"""
Per-source state management.
Each source gets its own output directory under output/{source_name}/.

Handles:
  - Resume state (last_page, processed_count)
  - CSV append with headers
  - Raw metadata JSON
  - Failure logging
  - Progress reporting
"""

import json
import csv
from pathlib import Path
from datetime import datetime
from typing import Optional


class StateManager:
    """
    Manages persistent state for one scraping source.

    All files are stored under:
        {base_output}/{source_name}/
            documents.csv
            state/state.json
            state/failed.json
            metadata/{index}_{id_prefix}.json
            pdfs/{index}_{label}/...
    """

    def __init__(self, source_name: str, base_output: str = "output"):
        self.source_name = source_name
        self.output_dir  = Path(base_output) / source_name
        self.state_file  = self.output_dir / "state" / "state.json"
        self.failed_file = self.output_dir / "state" / "failed.json"
        self.csv_file    = self.output_dir / "documents.csv"
        self.meta_dir    = self.output_dir / "metadata"
        self.pdf_dir     = self.output_dir / "pdfs"

        # Ensure directories exist
        for d in [self.output_dir / "state", self.meta_dir, self.pdf_dir]:
            d.mkdir(parents=True, exist_ok=True)

    # ── state ───────────────────────────────────────────────────────────────

    def load_state(self) -> dict:
        """
        Load current scraping progress from disk.

        Returns dict with:
            last_page (int):        last successfully completed page (0 = not started)
            processed_count (int):  total documents processed
            started_at (str):       ISO timestamp of first run
            last_updated (str):     ISO timestamp of last update
            total_docs (int):       total documents from API (0 = unknown)
        """
        if self.state_file.exists():
            with open(self.state_file, encoding="utf-8") as f:
                state = json.load(f)
            print(f"  [state] Resuming {self.source_name} from page {state.get('last_page', 0) + 1}")
            print(f"  [state] Already processed: {state.get('processed_count', 0)} documents")
            return state

        # Fresh start
        state = {
            "last_page": 0,
            "processed_count": 0,
            "started_at": datetime.utcnow().isoformat(),
            "last_updated": datetime.utcnow().isoformat(),
            "total_docs": 0,
        }
        print(f"  [state] Fresh start for {self.source_name} — no previous state found")
        return state

    def update_state(
        self,
        page: int,
        processed_count: int,
        total_docs: int = 0,
    ) -> None:
        """Persist progress after completing a page."""
        existing = {}
        if self.state_file.exists():
            with open(self.state_file, encoding="utf-8") as f:
                existing = json.load(f)

        state = {
            **existing,
            "last_page": page,
            "processed_count": processed_count,
            "last_updated": datetime.utcnow().isoformat(),
            "total_docs": total_docs or existing.get("total_docs", 0),
        }
        state.setdefault("started_at", datetime.utcnow().isoformat())

        with open(self.state_file, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)

    # ── metadata ────────────────────────────────────────────────────────────

    def save_metadata_json(self, doc: dict, index: int) -> None:
        """Save the raw API response for one document as JSON."""
        source_id = str(doc.get("id", "unknown"))
        safe_prefix = source_id[:20].replace("/", "_").replace("+", "_")
        path = self.meta_dir / f"{index:05d}_{safe_prefix}.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False, indent=2)

    # ── CSV ─────────────────────────────────────────────────────────────────

    def append_csv(self, row: dict, headers: list[str]) -> None:
        """Append one row to the documents CSV. Writes header on first call."""
        write_header = not self.csv_file.exists()
        with open(self.csv_file, "a", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=headers)
            if write_header:
                writer.writeheader()
            writer.writerow(row)

    # ── failures ────────────────────────────────────────────────────────────

    def log_failure(self, doc_id: str, title: str, reason: str) -> None:
        """Record a failed download/processing event."""
        failures = self.get_failures()
        failures.append({
            "id": doc_id,
            "title": title,
            "reason": reason,
            "timestamp": datetime.utcnow().isoformat(),
        })
        with open(self.failed_file, "w", encoding="utf-8") as f:
            json.dump(failures, f, ensure_ascii=False, indent=2)

    def get_failures(self) -> list:
        """Return list of all logged failures."""
        if not self.failed_file.exists():
            return []
        with open(self.failed_file, encoding="utf-8") as f:
            return json.load(f)

    # ── progress ────────────────────────────────────────────────────────────

    def print_progress(
        self,
        processed: int,
        total: int,
        pdf_count: int,
        fail_count: int,
        start_time: datetime,
    ) -> None:
        """Print a progress update line with ETA."""
        if total <= 0 or processed <= 0:
            print(f"  ── Progress: {processed} docs | {pdf_count} PDFs | {fail_count} failures")
            return

        elapsed = (datetime.utcnow() - start_time).total_seconds()
        rate = processed / elapsed if elapsed > 0 else 0
        remaining = total - processed
        eta_secs = int(remaining / rate) if rate > 0 else 0

        if eta_secs > 60:
            eta_str = f"{eta_secs // 3600}h {(eta_secs % 3600) // 60}m"
        else:
            eta_str = f"{eta_secs}s"

        pct = processed / total * 100
        print(
            f"  ── Progress: {processed}/{total} ({pct:.1f}%) "
            f"| {pdf_count} PDFs | {fail_count} failures | ETA: {eta_str}"
        )
