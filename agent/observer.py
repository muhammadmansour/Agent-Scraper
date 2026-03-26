"""
Observer — gathers a structured snapshot of the current scraping state.

The observation is formatted into a human-readable string that gets sent
to the LLM each turn so it can make informed decisions.
"""

from datetime import datetime, timezone

from sources import SOURCES
from tools.state_manager import StateManager


class Observer:
    """Collects observations about all sources and formats them for the LLM."""

    def __init__(self):
        self._state_managers: dict[str, StateManager] = {}

    def _get_state_mgr(self, name: str) -> StateManager:
        if name not in self._state_managers:
            self._state_managers[name] = StateManager(name)
        return self._state_managers[name]

    def observe(self, extra_context: str = "") -> str:
        """
        Build a complete observation string for the LLM.

        Returns a formatted text block with:
        - Timestamp
        - Available sources and their current state
        - Per-source progress
        - Recent failures
        - Extra context (e.g., from last action result)
        """
        lines = []
        lines.append(f"=== OBSERVATION at {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')} ===\n")

        lines.append(f"Registered sources: {', '.join(SOURCES.keys())}\n")

        for name in SOURCES:
            state_mgr = self._get_state_mgr(name)
            state = state_mgr.load_state()
            failures = state_mgr.get_failures()

            total = state.get("total_docs", 0)
            done = state.get("processed_count", 0)
            last_page = state.get("last_page", 0)
            per_page = 10  # default
            total_pages = (total + per_page - 1) // per_page if total > 0 else 0
            remaining = max(0, total - done)
            pct = round(done / total * 100, 1) if total > 0 else 0

            pdf_count = (
                sum(1 for _ in state_mgr.pdf_dir.glob("**/*.pdf"))
                if state_mgr.pdf_dir.exists()
                else 0
            )

            lines.append(f"── Source: {name} ──")
            if total == 0 and last_page == 0:
                lines.append("  Status: NOT STARTED (no data fetched yet)")
                lines.append("  → You should check_source_health first, then start scraping from page 1")
            else:
                lines.append(f"  Progress: {done}/{total} docs ({pct}%)")
                lines.append(f"  Pages: {last_page}/{total_pages} completed")
                lines.append(f"  PDFs on disk: {pdf_count}")
                lines.append(f"  Failures: {len(failures)}")
                lines.append(f"  Remaining: {remaining} docs")
                if last_page < total_pages:
                    lines.append(f"  → Next page to scrape: {last_page + 1}")
                else:
                    lines.append("  → ALL PAGES COMPLETED ✓")
                if failures:
                    lines.append(f"  → Recent failures: {', '.join(f['reason'] for f in failures[-3:])}")
            lines.append("")

        if extra_context:
            lines.append(f"── Last Action Result ──")
            lines.append(extra_context)
            lines.append("")

        lines.append("What should we do next? Use a tool to take action.")
        return "\n".join(lines)
