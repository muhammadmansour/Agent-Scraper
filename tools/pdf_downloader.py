"""
Generic PDF downloader — works with any source's PdfAsset list.
Source-agnostic: the source plugin provides the URLs and the validator.
"""

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sources.base import PdfAsset, BaseSource

from tools.http_client import HttpClient


def download_pdfs_for_document(
    assets: list["PdfAsset"],
    output_dir: str,
    source: "BaseSource",
    client: HttpClient | None = None,
) -> dict[str, bool]:
    """
    Download all PDF assets for a single document.

    Args:
        assets:     List of PdfAsset objects (from source.get_pdf_assets)
        output_dir: Directory to save PDFs into
        source:     The source instance (used for validate_pdf)
        client:     Shared HttpClient (creates one if not provided)

    Returns:
        dict mapping label → True/False
        e.g. {"original": True, "translated": False, "printed": True}
    """
    if client is None:
        client = HttpClient()

    out = Path(output_dir)
    results: dict[str, bool] = {}

    for asset in assets:
        out_path = out / asset.filename
        ok = client.download_file(
            url=asset.url,
            output_path=str(out_path),
            validator=lambda header_bytes: source.validate_pdf(header_bytes),
        )
        results[asset.label] = ok
        if ok:
            try:
                size_kb = out_path.stat().st_size // 1024
                print(f"      [{asset.label}] ✓ {size_kb} KB")
            except OSError:
                print(f"      [{asset.label}] ✓")

    return results
