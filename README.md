# Multi-Source Document Scraping Agent

Downloads documents and PDFs from multiple Saudi government sources using a plugin-based architecture.

> ⚠️ Some sources (e.g. NCAR) are geo-restricted to Saudi Arabia.

## Setup

```bash
pip install -r requirements.txt
```

## Quick Start

```bash
# List all available sources
python agent.py --list-sources

# Scrape NCAR (all ~6631 documents)
python agent.py --source ncar

# Scrape all registered sources
python agent.py --source all
```

## Usage

```bash
# Full run for a source
python agent.py --source ncar

# Metadata only, skip PDFs
python agent.py --source ncar --no-pdf

# Resume from a specific page
python agent.py --source ncar --start-page 50

# Test mode — first 2 pages only
python agent.py --source ncar --test

# Retry previously failed downloads
python agent.py --source ncar --retry-failed

# Scrape every registered source
python agent.py --source all
```

### With Claude Code (recommended for intelligent orchestration)

```bash
npm install -g @anthropic-ai/claude-code
claude
```

Claude Code will read `CLAUDE.md`, understand the plugin architecture, and operate the agent.

## Output Structure

Each source gets its own directory under `output/`:

```
output/
├── ncar/
│   ├── documents.csv              ← All metadata (UTF-8 with BOM for Excel)
│   ├── state/
│   │   ├── state.json             ← Resume state (last page, count)
│   │   └── failed.json            ← Failed downloads with reasons
│   ├── metadata/
│   │   ├── 00001_eyJpdii6Ikx3.json
│   │   └── ...
│   └── pdfs/
│       ├── 00001_Law_of_Roads_1941/
│       │   ├── original.pdf
│       │   ├── translated.pdf
│       │   └── printed.pdf
│       └── ...
└── other_source/
    └── ...
```

## Available Sources

| Source | Name | Documents | Website |
|--------|------|-----------|---------|
| NCAR | `ncar` | ~6631 | [ncar.gov.sa](https://ncar.gov.sa/rules-regulations) |

## Adding a New Source

Adding a new website takes ~50 lines of code:

1. **Copy the template:**
   ```bash
   cp sources/_template.py sources/my_source.py
   ```

2. **Implement 5 methods** in `sources/my_source.py`:
   - `fetch_page()` — call the source's API
   - `get_pdf_assets()` — return download URLs
   - `extract_metadata()` — normalize fields
   - `get_csv_headers()` — column names
   - `metadata_to_csv_row()` — build CSV row

3. **Register** in `sources/__init__.py`:
   ```python
   from sources.my_source import MySource
   SOURCES["my_source"] = MySource
   ```

4. **Test:**
   ```bash
   python agent.py --source my_source --test
   ```

## Architecture

```
agent.py                     ← Source-agnostic orchestration loop
├── sources/
│   ├── base.py              ← BaseSource abstract class
│   ├── __init__.py          ← Source registry
│   ├── _template.py         ← Template for new sources
│   └── ncar.py              ← NCAR plugin
└── tools/
    ├── http_client.py       ← Shared HTTP with retries & rate-limits
    ├── pdf_downloader.py    ← Generic PDF downloader
    └── state_manager.py     ← Per-source state, CSV, failures
```

### How It Works

1. `agent.py` gets the source plugin by name from the registry
2. Calls `source.fetch_page()` in a loop to get documents
3. For each document:
   - `source.extract_metadata()` → normalized metadata
   - `source.get_pdf_assets()` → list of download URLs
   - `pdf_downloader` downloads each asset using `http_client`
   - `state_manager` saves metadata JSON, appends CSV, tracks progress
4. State is saved after every page — restart auto-resumes

## CSV Columns (NCAR)

| Column | Description |
|--------|-------------|
| index | Sequential number |
| encrypted_id | API document ID (base64) |
| number | Official document number |
| title_ar | Arabic title |
| title_en | English title |
| approve_type | Royal Decree / Royal Order / etc. |
| approve_date | Hijri date |
| is_valid | سارية (active) or غير سارية (inactive) |
| marker | valid / valid-modified / superseded |
| has_original | 1 if original PDF downloaded |
| has_translated | 1 if translated PDF downloaded |
| has_printed | 1 if print PDF downloaded |

## Estimated Time

| Mode | NCAR (~6631 docs) |
|------|-------------------|
| Metadata only (`--no-pdf`) | ~20 minutes |
| With PDFs | 2–4 hours |

## Resuming

The agent automatically saves progress after every page. If interrupted, just run again:

```bash
python agent.py --source ncar   # auto-resumes from last page
```

## Requirements

- Python 3.10+
- `requests` library
- Network access to the source website
