"""
Source registry — import and register all available scraping sources here.

To add a new source:
    1. Create your source class in sources/your_source.py (copy _template.py)
    2. Import it below
    3. Add it to the SOURCES dict
    4. Run: python agent.py --source your_source
"""

from sources.ncar import NcarSource

# ── Registry ─────────────────────────────────────────────────────────────────
# Add new sources here. The key is the CLI name (--source <key>).
SOURCES: dict[str, type] = {
    "ncar": NcarSource,
    # "boe":  BoeSource,       # Bureau of Experts — coming soon
    # "moj":  MojSource,       # Ministry of Justice — coming soon
}


def get_source(name: str):
    """Instantiate and return a source by its registry name."""
    cls = SOURCES.get(name)
    if cls is None:
        available = ", ".join(sorted(SOURCES.keys()))
        raise ValueError(f"Unknown source '{name}'. Available sources: {available}")
    return cls()


def list_sources() -> list[tuple[str, str]]:
    """Return a list of (name, display_name) for all registered sources."""
    return [(name, cls().display_name) for name, cls in SOURCES.items()]
