# Multi-Source Document Scraping Agent

You are a document scraping agent that downloads documents and PDFs from multiple Saudi government sources.

## Architecture

This is a **plugin-based** scraper. Each website is a "source" that implements a standard interface.

### Key Files
- `agent.py` — Main orchestration loop (source-agnostic)
- `sources/base.py` — Abstract base class (`BaseSource`) that all sources implement
- `sources/ncar.py` — NCAR source plugin (ncar.gov.sa)
- `sources/__init__.py` — Source registry
- `sources/_template.py` — Template for adding new sources
- `tools/http_client.py` — Shared HTTP client with retries & rate-limit handling
- `tools/pdf_downloader.py` — Generic PDF downloader (uses PdfAsset objects)
- `tools/state_manager.py` — Per-source state management (resume, CSV, failures)

### Source Plugin Interface
Every source must implement:
- `fetch_page(page, per_page)` → `DocumentPage` with documents list and total count
- `get_pdf_assets(doc)` → list of `PdfAsset(label, url, filename)`
- `extract_metadata(doc)` → `DocumentMetadata` (normalized fields)
- `get_csv_headers()` → list of column names
- `metadata_to_csv_row(meta, pdf_results, index)` → dict for CSV

## Currently Registered Sources

### NCAR (ncar.gov.sa)
- **Name:** `ncar`
- **Documents:** ~6631
- **API List:** GET `https://ncar.gov.sa/api/index.php/api/documents/list/{page}/{per_page}/approveDate/ASC`
- **API PDF:** GET `https://ncar.gov.sa/api/index.php/api/resource/{encrypted_id}/Documents/{type}`
  - Types: `OriginalAttachPath`, `TranslatedAttachPath`, `PrintedAttachPath`
- **Geo-restricted:** Must run from Saudi Arabia IP

## How to Run

```bash
# List available sources
python agent.py --list-sources

# Scrape a specific source
python agent.py --source ncar

# Scrape all registered sources
python agent.py --source all

# Options
python agent.py --source ncar --start-page 50    # resume from page
python agent.py --source ncar --no-pdf            # metadata only
python agent.py --source ncar --test              # 2 pages only
python agent.py --source ncar --retry-failed      # retry failures
```

## How to Add a New Source

1. Copy `sources/_template.py` → `sources/new_source.py`
2. Implement the 5 abstract methods
3. Register in `sources/__init__.py`:
   ```python
   from sources.new_source import NewSource
   SOURCES["new_source"] = NewSource
   ```
4. Test: `python agent.py --source new_source --test`

## Output Structure

Each source gets its own directory under `output/`:

```
output/
├── ncar/
│   ├── documents.csv
│   ├── state/
│   │   ├── state.json
│   │   └── failed.json
│   ├── metadata/
│   │   └── 00001_eyJpdii6Ikx3.json
│   └── pdfs/
│       └── 00001_Law_of_Roads_1941/
│           ├── original.pdf
│           ├── translated.pdf
│           └── printed.pdf
└── other_source/
    └── ...
```

## Behavior Rules

### Starting Up
1. Load state for the source — resume from last completed page
2. Probe the API for total document count
3. Print startup summary

### Main Loop (per source)
For each page:
1. Call `source.fetch_page(page, per_page)`
2. If fetch fails: log failure, skip page
3. For each document:
   - Extract metadata
   - Download PDFs (if enabled)
   - Save metadata JSON + append CSV row
4. Update state after each page
5. Respect delay settings between docs/pages

### Error Handling
| Situation | Action |
|-----------|--------|
| HTTP 429 (rate limit) | Sleep 30s × attempt, retry |
| HTTP 403 | Log and skip — restricted document |
| HTTP 404 | Skip — PDF type not available |
| Invalid PDF (not %PDF) | Delete file, log failure |
| Network timeout | Retry up to 3× with backoff |
| API bad status | Retry once after 5s, then skip |

### Progress Reporting
After every ~50 documents:
```
── Progress: {n}/{total} ({pct}%) | {pdfs} PDFs | {fails} failures | ETA: {eta}
```

## Important Notes
- Always use UTF-8 encoding — titles may be in Arabic
- NCAR encrypted IDs are base64 Laravel payloads — never modify them
- PDF validation: check first 4 bytes == `%PDF`
- Be respectful: honour each source's delay settings
- NCAR is geo-restricted to Saudi Arabia
