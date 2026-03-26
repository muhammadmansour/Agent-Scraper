# Agent Scraper — Architecture & Flow

## Project Structure

```
ncar_agent/
├── agent.py                  ← CLI entry point (--source or --agent mode)
│
├── agent/                    ← 🤖 Agentic Layer (LLM-powered)
│   ├── brain.py              │  Gemini client + function calling
│   ├── tools.py              │  7 tools the LLM can invoke
│   ├── observer.py           │  Gathers state for LLM context
│   ├── memory.py             │  Persistent decisions & patterns
│   ├── prompts.py            │  System prompt (strategy rules)
│   └── loop.py               │  Main agent loop
│
├── workflow/                 ← ⚙️ Pipeline Engine
│   ├── engine.py             │  Stage base class + WorkflowEngine
│   ├── stages.py             │  Extract → Download → Store
│   └── models.py             │  WorkflowItem data model
│
├── sources/                  ← 🔌 Source Plugins
│   ├── base.py               │  BaseSource ABC + data classes
│   ├── ncar.py               │  NCAR implementation
│   ├── _template.py          │  Template for new sources
│   └── __init__.py           │  Source registry
│
├── tools/                    ← 🔧 Shared Utilities
│   ├── http_client.py        │  HTTP + retries + rate limiting
│   ├── pdf_downloader.py     │  Generic PDF downloader
│   └── state_manager.py      │  State, CSV, failure logging
│
└── output/{source}/          ← 📁 Output (per source)
    ├── documents.csv
    ├── state/state.json
    ├── state/failed.json
    ├── metadata/*.json
    └── pdfs/{doc}/*.pdf
```

---

## Mode 1: Workflow Mode (`--source ncar`)

Scripted, deterministic pipeline. No LLM involved.

```
┌─────────────────────────────────────────────────────┐
│                    agent.py CLI                      │
│              python agent.py --source ncar           │
└──────────────────────┬──────────────────────────────┘
                       │
                       ▼
              ┌────────────────┐
              │  Load Source   │  sources/ncar.py
              │  Plugin        │  (implements BaseSource)
              └───────┬────────┘
                      │
                      ▼
              ┌────────────────┐
              │  Probe API     │  fetch_page(page=1, per_page=1)
              │  Get total     │  → total_docs, total_pages
              └───────┬────────┘
                      │
          ┌───────────┴───────────┐
          │   FOR EACH PAGE       │
          │   (resume-aware)      │
          └───────────┬───────────┘
                      │
                      ▼
         ┌────────────────────────┐
         │   FETCH (page-level)   │  source.fetch_page(page, per_page)
         │   → list of raw docs   │  → DocumentPage
         └────────────┬───────────┘
                      │
                      ▼
    ┌─────────────────────────────────────────┐
    │         PIPELINE  (per batch)           │
    │                                         │
    │  ┌──────────┐  ┌──────────┐  ┌───────┐ │
    │  │ Extract  │→ │ Download │→ │ Store │ │
    │  │          │  │(parallel)│  │       │ │
    │  └──────────┘  └──────────┘  └───────┘ │
    │                                         │
    │  Extract:  raw doc → metadata + assets  │
    │  Download: assets → PDFs on disk        │
    │  Store:    metadata → CSV + JSON        │
    └─────────────────────────────────────────┘
                      │
                      ▼
              ┌────────────────┐
              │  Update State  │  state_manager
              │  Next page...  │  → state.json, failed.json
              └────────────────┘
```

---

## Mode 2: Agent Mode (`--agent`)

LLM-powered autonomous loop. Gemini decides what to do.

```
┌──────────────────────────────────────────────────────────────────────┐
│                          agent.py CLI                                │
│         python agent.py --agent --goal "scrape all NCAR"            │
└────────────────────────────────┬─────────────────────────────────────┘
                                 │
                                 ▼
┌──────────────────────────────────────────────────────────────────────┐
│                         AgentLoop.run()                              │
│                                                                      │
│  ┌────────────┐    ┌─────────────────┐    ┌───────────────────┐     │
│  │   Memory    │    │    Observer      │    │   Gemini Brain    │     │
│  │  (persist)  │    │ (state snapshot) │    │  (LLM + tools)   │     │
│  └──────┬─────┘    └────────┬────────┘    └─────────┬─────────┘     │
│         │                   │                       │               │
│         ▼                   ▼                       │               │
│  ┌─────────────────────────────────────┐            │               │
│  │  1. OBSERVE                         │            │               │
│  │  Gather: progress, failures, health │            │               │
│  │  + memory (patterns, past decisions)│            │               │
│  └──────────────────┬──────────────────┘            │               │
│                     │                               │               │
│                     ▼                               │               │
│  ┌─────────────────────────────────────┐            │               │
│  │  2. REASON                          │◄───────────┘               │
│  │  Send observation → Gemini          │                            │
│  │  LLM analyzes state + picks tool    │                            │
│  └──────────────────┬──────────────────┘                            │
│                     │                                               │
│                     ▼                                               │
│  ┌─────────────────────────────────────┐                            │
│  │  3. ACT                             │                            │
│  │  Execute the tool Gemini chose:     │                            │
│  │                                     │                            │
│  │  ┌─────────────────────────────┐    │                            │
│  │  │ scrape_pages(ncar, 1, 50)   │    │   Uses the same            │
│  │  │ check_source_health(ncar)   │    │   workflow pipeline         │
│  │  │ get_progress()              │    │   (Extract→Download→Store)  │
│  │  │ get_failures(ncar)          │    │   under the hood            │
│  │  │ retry_failures(ncar)        │    │                            │
│  │  │ adjust_workers(5)           │    │                            │
│  │  │ finish("all done")          │    │                            │
│  │  └─────────────────────────────┘    │                            │
│  └──────────────────┬──────────────────┘                            │
│                     │                                               │
│                     ▼                                               │
│  ┌─────────────────────────────────────┐                            │
│  │  4. LEARN                           │                            │
│  │  Log decision to memory             │                            │
│  │  Detect patterns (high failure %)   │                            │
│  │  Feed result back to Gemini         │                            │
│  └──────────────────┬──────────────────┘                            │
│                     │                                               │
│                     ▼                                               │
│              ┌──────────────┐                                       │
│              │  Loop back   │                                       │
│              │  to OBSERVE  │──── until finish() or max turns       │
│              └──────────────┘                                       │
│                                                                      │
└──────────────────────────────────────────────────────────────────────┘
```

---

## Agent Decision Flow (single turn detail)

```
                    ┌──────────────────────────┐
                    │  Observer.observe()       │
                    │                          │
                    │  Source: ncar             │
                    │  Progress: 320/6640 (5%) │
                    │  Pages: 32/664           │
                    │  Failures: 3             │
                    │  Next page: 33           │
                    └────────────┬─────────────┘
                                 │
                                 ▼
                    ┌──────────────────────────┐
                    │  Gemini receives:        │
                    │                          │
                    │  • Goal from user        │
                    │  • Current observation   │
                    │  • Memory (patterns)     │
                    │  • Last action result    │
                    │  • System prompt rules   │
                    └────────────┬─────────────┘
                                 │
                    ┌────────────┴─────────────┐
                    │  Gemini THINKS:          │
                    │                          │
                    │  "NCAR is at 5%, healthy │
                    │   with only 3 failures.  │
                    │   I should scrape a big  │
                    │   batch: pages 33-82."   │
                    └────────────┬─────────────┘
                                 │
                                 ▼
                    ┌──────────────────────────┐
                    │  Gemini CALLS:           │
                    │                          │
                    │  scrape_pages(           │
                    │    source="ncar",        │
                    │    start_page=33,        │
                    │    end_page=82           │
                    │  )                       │
                    └────────────┬─────────────┘
                                 │
                                 ▼
              ┌──────────────────────────────────────┐
              │  Tool executes scrape_pages:          │
              │                                      │
              │  FOR page 33..82:                    │
              │    source.fetch_page(page)           │
              │    ┌──────────────────────────┐      │
              │    │ Extract → Download → Store│      │
              │    └──────────────────────────┘      │
              │    state_manager.update_state()      │
              │                                      │
              │  Returns:                            │
              │  {                                   │
              │    "documents_scraped": 500,          │
              │    "pdfs_downloaded": 487,            │
              │    "failures": 13,                   │
              │    "total_processed_so_far": 820     │
              │  }                                   │
              └──────────────────┬───────────────────┘
                                 │
                                 ▼
                    ┌──────────────────────────┐
                    │  Memory logs:            │
                    │  • Decision + result     │
                    │  • Pattern if >30% fail  │
                    └────────────┬─────────────┘
                                 │
                                 ▼
                        Back to OBSERVE
```

---

## How the Pipeline Works Inside `scrape_pages`

```
  Raw API Response             WorkflowItem              Disk
  ─────────────────           ──────────────            ──────
                        ┌─────────────────────┐
  { "id": "abc",   ───▶│  WorkflowItem       │
    "title": "...",     │  index: 321         │
    "number": "32",     │  raw_doc: {...}     │
    ... }               │                     │
                        └─────────┬───────────┘
                                  │
                    ┌─────────────▼──────────────┐
                    │     EXTRACT STAGE           │
                    │                            │
                    │  source.extract_metadata() │
                    │  source.get_pdf_assets()   │
                    │                            │
                    │  → metadata: DocumentMeta  │
                    │  → assets: [PdfAsset]      │
                    └─────────────┬──────────────┘
                                  │
                    ┌─────────────▼──────────────┐
                    │     DOWNLOAD STAGE          │
                    │     (parallel threads)      │
                    │                            │
                    │  http_client.download_file()│──▶  pdfs/00321_doc/
                    │  source.validate_pdf()      │     └── original.pdf
                    │                            │
                    │  → pdf_results:            │
                    │    {"original": true}       │
                    └─────────────┬──────────────┘
                                  │
                    ┌─────────────▼──────────────┐
                    │     STORE STAGE             │
                    │                            │
                    │  state_mgr.save_json()     │──▶  metadata/00321.json
                    │  state_mgr.append_csv()    │──▶  documents.csv (row)
                    └────────────────────────────┘
```

---

## Adding a New Source

```
  1. Copy sources/_template.py → sources/my_source.py
  2. Implement 5 methods:

     ┌────────────────────────────────────────────┐
     │  class MySource(BaseSource):                │
     │                                            │
     │    name           → "my_source"            │
     │    display_name   → "My Source — site.com" │
     │    fetch_page()   → call API, return docs  │
     │    extract_metadata() → normalize fields   │
     │    get_pdf_assets()   → list PDF URLs      │
     └────────────────────────────────────────────┘

  3. Register in sources/__init__.py:

     SOURCES = {
         "ncar":      NcarSource,
         "my_source": MySource,    ← add this
     }

  4. Run:
     python agent.py --source my_source
     python agent.py --agent  ← agent auto-discovers it
```
