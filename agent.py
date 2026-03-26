#!/usr/bin/env python3
"""
Multi-Source Document Scraping Agent
=====================================
Scrapes documents and PDFs from multiple Saudi government sources.
Each source is a plugin — see sources/ directory.

Usage:
    python agent.py --source ncar                    # scrape NCAR
    python agent.py --source ncar --start-page 50    # resume from page 50
    python agent.py --source ncar --no-pdf           # metadata + CSV only
    python agent.py --source ncar --test             # test mode (2 pages)
    python agent.py --source ncar --retry-failed     # retry failed downloads
    python agent.py --source all                     # scrape ALL registered sources
    python agent.py --list-sources                   # show available sources
"""

import sys
import os
import time
import argparse
from datetime import datetime, timezone
from pathlib import Path

# Force UTF-8 output on Windows
os.environ["PYTHONUTF8"] = "1"
os.environ["PYTHONIOENCODING"] = "utf-8"
if sys.stdout.encoding != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Ensure project root is on the path
sys.path.insert(0, str(Path(__file__).parent))

from sources import get_source, list_sources, SOURCES
from sources.base import BaseSource
from tools.state_manager import StateManager
from tools.http_client import HttpClient
from tools.pdf_downloader import download_pdfs_for_document


# ── helpers ──────────────────────────────────────────────────────────────────

def safe_dirname(text: str, max_len: int = 80) -> str:
    """Convert a title to a filesystem-safe directory name."""
    for ch in r'/\:*?"<>|':
        text = text.replace(ch, "_")
    # Strip, truncate, then strip again (truncation can leave trailing spaces)
    # Also remove trailing dots — Windows doesn't allow those either
    return text.strip()[:max_len].rstrip(" .")


# ── core scraping loop ──────────────────────────────────────────────────────

def run_source(
    source: BaseSource,
    start_page: int | None = None,
    download_pdf: bool = True,
    test_mode: bool = False,
) -> None:
    """Run the full scraping loop for one source."""

    state_mgr = StateManager(source.name)
    client = HttpClient(verify_ssl=source.verify_ssl)

    print("╔══════════════════════════════════════════════╗")
    print(f"║  Scraping: {source.display_name:<34}║")
    print("╚══════════════════════════════════════════════╝\n")

    # ── load state & probe API ───────────────────────────────────────────
    state       = state_mgr.load_state()
    resume_page = start_page or (state["last_page"] + 1)
    processed   = state["processed_count"]
    start_time  = datetime.now(timezone.utc)
    fail_count  = len(state_mgr.get_failures())
    per_page    = source.default_per_page

    print("\n▶ Probing API…")
    probe = source.fetch_page(page=1, per_page=1)
    if not probe:
        print(f"✗ Cannot reach {source.display_name}. Check your connection.")
        return

    total_docs  = probe.total_count
    total_pages = (total_docs + per_page - 1) // per_page

    if test_mode:
        total_pages = min(total_pages, resume_page + 1)
        print("  [test mode] limiting to 2 pages")

    print(f"▶ Total documents : {total_docs}")
    print(f"▶ Total pages     : {total_pages} ({per_page}/page)")
    print(f"▶ Resuming from   : page {resume_page}")
    print(f"▶ Already done    : {processed} documents")
    print(f"▶ PDF download    : {'yes' if download_pdf else 'no (metadata only)'}")
    print(f"▶ Output dir      : {state_mgr.output_dir}/")

    # Count existing PDFs
    pdf_count = sum(1 for _ in state_mgr.pdf_dir.glob("**/*.pdf")) if state_mgr.pdf_dir.exists() else 0

    # ── main loop ────────────────────────────────────────────────────────
    for page in range(resume_page, total_pages + 1):
        print(f"\n{'─' * 50}")
        print(f"Page {page} / {total_pages}  (docs {(page - 1) * per_page + 1}–{min(page * per_page, total_docs)})")
        print(f"{'─' * 50}")

        page_data = source.fetch_page(page=page, per_page=per_page)
        if not page_data or not page_data.status_ok:
            print(f"  ✗ Failed to fetch page {page} — skipping")
            state_mgr.log_failure("page", f"page {page}", "API fetch failed after retries")
            fail_count += 1
            continue

        if not page_data.documents:
            print("  ⚠ Empty page — may have reached end")
            break

        for doc in page_data.documents:
            processed += 1
            meta = source.extract_metadata(doc)

            print(f"\n  [{processed}] {meta.title_primary}")
            if meta.title_secondary:
                print(f"        {meta.title_secondary}")
            print(f"        num={meta.number} | date={meta.date} | {meta.category} | {meta.status}")

            # Download PDFs
            pdf_results: dict[str, bool] = {}
            if download_pdf:
                assets = source.get_pdf_assets(doc)
                if assets:
                    label = meta.title_secondary or meta.title_primary or f"doc_{processed}"
                    has_latin = any(c.isascii() and c.isalpha() for c in label)
                    if not has_latin:
                        label = f"doc_{meta.number}".replace("/", "_") if meta.number else f"doc_{processed}"
                    doc_dir = str(state_mgr.pdf_dir / f"{processed:05d}_{safe_dirname(label)}")
                    pdf_results = download_pdfs_for_document(assets, doc_dir, source, client)
                    pdf_count += sum(1 for v in pdf_results.values() if v)

                    if not any(pdf_results.values()):
                        state_mgr.log_failure(
                            meta.source_id,
                            meta.title_primary or meta.title_secondary,
                            "no PDFs available",
                        )

            # Save metadata JSON + CSV row
            state_mgr.save_metadata_json(doc, processed)
            csv_row = source.metadata_to_csv_row(meta, pdf_results, processed)
            state_mgr.append_csv(csv_row, source.get_csv_headers())

            time.sleep(source.delay_between_docs)

        # Persist state after each page
        state_mgr.update_state(page, processed, total_docs)

        # Progress report every ~50 docs
        if processed % 50 < per_page:
            state_mgr.print_progress(processed, total_docs, pdf_count, fail_count, start_time)

        time.sleep(source.delay_between_pages)

    # ── final summary ────────────────────────────────────────────────────
    elapsed = (datetime.now(timezone.utc) - start_time).total_seconds()
    print(f"\n{'═' * 50}")
    print(f"✅  {source.display_name} — DONE")
    print(f"{'═' * 50}")
    print(f"  Documents processed : {processed}")
    print(f"  PDFs downloaded     : {pdf_count}")
    print(f"  Failures            : {fail_count}")
    print(f"  Time elapsed        : {int(elapsed // 3600)}h {int((elapsed % 3600) // 60)}m")
    print(f"  CSV index           : {state_mgr.csv_file}")

    failures = state_mgr.get_failures()
    if failures:
        print(f"\n  ⚠ {len(failures)} failures logged in {state_mgr.failed_file}")
        print("  Run with --retry-failed to attempt re-download")


# ── retry failed ─────────────────────────────────────────────────────────────

def retry_failed(source: BaseSource) -> None:
    """Retry all previously failed downloads for a source."""
    state_mgr = StateManager(source.name)
    client = HttpClient(verify_ssl=source.verify_ssl)
    failures = state_mgr.get_failures()

    if not failures:
        print(f"No failures to retry for {source.display_name}.")
        return

    # Only retry document-level failures (not page-level)
    doc_failures = [f for f in failures if f.get("id", "") != "page"]
    if not doc_failures:
        print("Only page-level failures exist — re-run the scraper to retry those.")
        return

    print(f"Retrying {len(doc_failures)} failed documents for {source.display_name}…\n")

    recovered = 0
    for i, failure in enumerate(doc_failures, 1):
        doc_id = failure["id"]
        title = failure.get("title", "unknown")
        print(f"[{i}/{len(doc_failures)}] {title}")

        # Build fake doc dict to get assets
        fake_doc = {"id": doc_id}
        assets = source.get_pdf_assets(fake_doc)
        if not assets:
            print("  ✗ no PDF assets to download")
            continue

        label = safe_dirname(title) or f"retry_{i:04d}"
        doc_dir = str(state_mgr.pdf_dir / f"retry_{i:04d}_{label}")
        results = download_pdfs_for_document(assets, doc_dir, source, client)

        if any(results.values()):
            print("  ✓ recovered")
            recovered += 1
        else:
            print("  ✗ still failing")

        time.sleep(source.delay_between_docs)

    print(f"\nRecovered {recovered}/{len(doc_failures)} documents.")


# ── CLI ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Multi-Source Document Scraping Agent",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
Examples:
  python agent.py --list-sources
  python agent.py --source ncar
  python agent.py --source ncar --start-page 50
  python agent.py --source ncar --no-pdf --test
  python agent.py --source all
  python agent.py --source ncar --retry-failed
""",
    )
    parser.add_argument(
        "--source", type=str, default=None,
        help="Source name (e.g. 'ncar') or 'all' for every registered source",
    )
    parser.add_argument(
        "--list-sources", action="store_true",
        help="List all available sources and exit",
    )
    parser.add_argument(
        "--start-page", type=int, default=None,
        help="Resume from a specific page number",
    )
    parser.add_argument(
        "--no-pdf", action="store_true",
        help="Skip PDF downloads (metadata + CSV only)",
    )
    parser.add_argument(
        "--retry-failed", action="store_true",
        help="Retry previously failed downloads",
    )
    parser.add_argument(
        "--test", action="store_true",
        help="Test mode — process only 2 pages",
    )

    args = parser.parse_args()

    # ── list sources ─────────────────────────────────────────────────────
    if args.list_sources:
        print("Available sources:\n")
        for sname, display in list_sources():
            print(f"  {sname:15s}  {display}")
        print(f"\nUsage: python agent.py --source <name>")
        sys.exit(0)

    # ── validate ─────────────────────────────────────────────────────────
    if not args.source:
        parser.print_help()
        sys.exit(1)

    # ── run all sources ──────────────────────────────────────────────────
    if args.source == "all":
        for sname in SOURCES:
            source = get_source(sname)
            if args.retry_failed:
                retry_failed(source)
            else:
                run_source(
                    source,
                    download_pdf=not args.no_pdf,
                    test_mode=args.test,
                )
        return

    # ── run single source ────────────────────────────────────────────────
    source = get_source(args.source)

    if args.retry_failed:
        retry_failed(source)
    else:
        run_source(
            source,
            start_page=args.start_page,
            download_pdf=not args.no_pdf,
            test_mode=args.test,
        )


if __name__ == "__main__":
    main()
