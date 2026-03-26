#!/usr/bin/env python3
"""
Multi-Source Document Scraping Agent
=====================================
Supports two modes:

1. **Workflow mode** (default) — scripted pipeline per source:
       Fetch → Extract → Download (parallel) → Store

2. **Agent mode** (--agent) — LLM-powered autonomous scraping:
       Observe → Reason (Gemini) → Act (tools) → Learn → Repeat

Usage:
    python agent.py --source ncar                      # scripted workflow
    python agent.py --source ncar --start-page 50      # resume from page 50
    python agent.py --source ncar --no-pdf             # metadata + CSV only
    python agent.py --source ncar --workers 5          # 5 parallel PDF downloads
    python agent.py --source ncar --test               # test mode (2 pages)
    python agent.py --source ncar --retry-failed       # retry failed downloads
    python agent.py --source all                       # scrape ALL sources
    python agent.py --list-sources                     # show available sources
    python agent.py --agent                            # LLM autonomous mode
    python agent.py --agent --goal "scrape all ncar"   # with a specific goal
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
from workflow.engine import WorkflowEngine
from workflow.models import WorkflowItem
from workflow.stages import ExtractStage, DownloadStage, StoreStage


# ── helpers ──────────────────────────────────────────────────────────────────

def safe_dirname(text: str, max_len: int = 80) -> str:
    """Convert a title to a filesystem-safe directory name."""
    for ch in r'/\:*?"<>|':
        text = text.replace(ch, "_")
    return text.strip()[:max_len].rstrip(" .")


# ── core workflow ────────────────────────────────────────────────────────────

def run_source(
    source: BaseSource,
    start_page: int | None = None,
    download_pdf: bool = True,
    test_mode: bool = False,
    max_workers: int = 3,
) -> None:
    """Run the full scraping workflow for one source."""

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

    # ── build pipeline ───────────────────────────────────────────────────
    pipeline = WorkflowEngine(stages=[
        ExtractStage(source),
        DownloadStage(
            source, client, state_mgr,
            enabled=download_pdf,
            max_workers=max_workers,
        ),
        StoreStage(source, state_mgr),
    ])

    print(f"▶ Total documents : {total_docs}")
    print(f"▶ Total pages     : {total_pages} ({per_page}/page)")
    print(f"▶ Resuming from   : page {resume_page}")
    print(f"▶ Already done    : {processed} documents")
    print(f"▶ PDF download    : {'yes' if download_pdf else 'no (metadata only)'}")
    print(f"▶ Parallel workers: {max_workers}")
    print(f"▶ Pipeline        : {' → '.join(pipeline.stage_names)}")
    print(f"▶ Output dir      : {state_mgr.output_dir}/")

    # Count existing PDFs
    pdf_count = (
        sum(1 for _ in state_mgr.pdf_dir.glob("**/*.pdf"))
        if state_mgr.pdf_dir.exists()
        else 0
    )

    # ── main loop: fetch pages → run pipeline per batch ──────────────────
    for page in range(resume_page, total_pages + 1):
        print(f"\n{'━' * 60}")
        print(
            f"  Page {page} / {total_pages}"
            f"  (docs {(page - 1) * per_page + 1}"
            f"–{min(page * per_page, total_docs)})"
        )
        print(f"{'━' * 60}")

        # ── FETCH (page-level) ───────────────────────────────────────
        page_data = source.fetch_page(page=page, per_page=per_page)
        if not page_data or not page_data.status_ok:
            print(f"  ✗ Failed to fetch page {page} — skipping")
            state_mgr.log_failure("page", f"page {page}", "fetch failed")
            fail_count += 1
            continue

        if not page_data.documents:
            print("  ⚠ Empty page — may have reached end")
            break

        # ── BUILD BATCH ──────────────────────────────────────────────
        items = []
        for doc in page_data.documents:
            processed += 1
            items.append(WorkflowItem(index=processed, raw_doc=doc))

        # ── RUN PIPELINE: Extract → Download → Store ─────────────────
        results = pipeline.run_batch(items)

        # ── TALLY RESULTS ────────────────────────────────────────────
        for item in results:
            pdf_count += item.pdf_count
            if item.failed:
                fail_count += 1

        batch_ok = sum(1 for i in results if i.completed)
        batch_fail = sum(1 for i in results if i.failed)
        print(f"\n  ✓ Batch: {batch_ok} ok, {batch_fail} failed")

        # Persist state after each page
        state_mgr.update_state(page, processed, total_docs)

        # Progress report every ~50 docs
        if processed % 50 < per_page:
            state_mgr.print_progress(
                processed, total_docs, pdf_count, fail_count, start_time
            )

        time.sleep(source.delay_between_pages)

    # ── final summary ────────────────────────────────────────────────────
    elapsed = (datetime.now(timezone.utc) - start_time).total_seconds()
    print(f"\n{'═' * 60}")
    print(f"  ✅  {source.display_name} — DONE")
    print(f"{'═' * 60}")
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

def retry_failed(source: BaseSource, max_workers: int = 3) -> None:
    """Retry all previously failed downloads for a source."""
    state_mgr = StateManager(source.name)
    client = HttpClient(verify_ssl=source.verify_ssl)
    failures = state_mgr.get_failures()

    if not failures:
        print(f"No failures to retry for {source.display_name}.")
        return

    doc_failures = [f for f in failures if f.get("id", "") != "page"]
    if not doc_failures:
        print("Only page-level failures — re-run the scraper to retry those.")
        return

    print(f"Retrying {len(doc_failures)} failed documents for {source.display_name}…\n")

    recovered = 0
    for i, failure in enumerate(doc_failures, 1):
        doc_id = failure["id"]
        title = failure.get("title", "unknown")
        print(f"[{i}/{len(doc_failures)}] {title}")

        fake_doc = {"id": doc_id}
        assets = source.get_pdf_assets(fake_doc)
        if not assets:
            print("  ✗ no PDF assets")
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
Examples (workflow mode):
  python agent.py --list-sources
  python agent.py --source ncar
  python agent.py --source ncar --start-page 50
  python agent.py --source ncar --no-pdf --test
  python agent.py --source ncar --workers 5
  python agent.py --source all
  python agent.py --source ncar --retry-failed

Examples (agent mode — LLM-powered):
  python agent.py --agent
  python agent.py --agent --goal "scrape all NCAR documents"
  python agent.py --agent --no-pdf --workers 1
""",
    )

    # ── shared arguments ─────────────────────────────────────────────────
    parser.add_argument(
        "--source", type=str, default=None,
        help="Source name (e.g. 'ncar') or 'all' (workflow mode)",
    )
    parser.add_argument(
        "--list-sources", action="store_true",
        help="List all available sources and exit",
    )
    parser.add_argument(
        "--start-page", type=int, default=None,
        help="Resume from a specific page number (workflow mode)",
    )
    parser.add_argument(
        "--no-pdf", action="store_true",
        help="Skip PDF downloads (metadata + CSV only)",
    )
    parser.add_argument(
        "--retry-failed", action="store_true",
        help="Retry previously failed downloads (workflow mode)",
    )
    parser.add_argument(
        "--test", action="store_true",
        help="Test mode — process only 2 pages (workflow mode)",
    )
    parser.add_argument(
        "--workers", type=int, default=3,
        help="Number of parallel PDF download workers (default: 3)",
    )

    # ── agent mode arguments ─────────────────────────────────────────────
    parser.add_argument(
        "--agent", action="store_true",
        help="Run in autonomous agent mode (LLM-powered with Gemini)",
    )
    parser.add_argument(
        "--goal", type=str, default="",
        help="High-level goal for the agent (e.g. 'scrape all NCAR')",
    )
    parser.add_argument(
        "--gemini-key", type=str, default=None,
        help="Gemini API key (or set GEMINI_API_KEY env var)",
    )
    parser.add_argument(
        "--model", type=str, default="gemini-2.5-pro",
        help="Gemini model name (default: gemini-2.5-pro)",
    )

    args = parser.parse_args()

    # ── list sources ─────────────────────────────────────────────────────
    if args.list_sources:
        print("Available sources:\n")
        for sname, display in list_sources():
            print(f"  {sname:15s}  {display}")
        print(f"\nUsage: python agent.py --source <name>")
        print(f"       python agent.py --agent")
        sys.exit(0)

    # ── agent mode ───────────────────────────────────────────────────────
    if args.agent:
        from agent.loop import AgentLoop

        goal = args.goal or "Scrape all documents from all registered sources."
        loop = AgentLoop(
            api_key=args.gemini_key,
            model_name=args.model,
            download_pdf=not args.no_pdf,
            max_workers=args.workers,
        )
        loop.run(goal=goal)
        return

    # ── validate ─────────────────────────────────────────────────────────
    if not args.source:
        parser.print_help()
        sys.exit(1)

    # ── run all sources ──────────────────────────────────────────────────
    if args.source == "all":
        for sname in SOURCES:
            source = get_source(sname)
            if args.retry_failed:
                retry_failed(source, max_workers=args.workers)
            else:
                run_source(
                    source,
                    download_pdf=not args.no_pdf,
                    test_mode=args.test,
                    max_workers=args.workers,
                )
        return

    # ── run single source ────────────────────────────────────────────────
    source = get_source(args.source)

    if args.retry_failed:
        retry_failed(source, max_workers=args.workers)
    else:
        run_source(
            source,
            start_page=args.start_page,
            download_pdf=not args.no_pdf,
            test_mode=args.test,
            max_workers=args.workers,
        )


if __name__ == "__main__":
    main()
