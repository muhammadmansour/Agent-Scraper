"""
Workflow data models.

WorkflowItem is the unit that flows through the pipeline — one per document.
Each item accumulates data as it passes through stages.
"""

from dataclasses import dataclass, field
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from sources.base import DocumentMetadata, PdfAsset


class StageStatus:
    """Status of a WorkflowItem at any stage."""
    PENDING    = "pending"
    PROCESSING = "processing"
    COMPLETED  = "completed"
    FAILED     = "failed"
    SKIPPED    = "skipped"


@dataclass
class WorkflowItem:
    """
    A single document flowing through the workflow pipeline.

    Lifecycle:
        Stage 1 (fetch):    → raw_doc populated
        Stage 2 (extract):  → metadata + pdf_assets populated
        Stage 3 (download): → pdf_results populated
        Stage 4 (store):    → saved to CSV + JSON
    """
    index: int
    raw_doc: dict = field(default_factory=dict)
    metadata: Optional["DocumentMetadata"] = None
    pdf_assets: list["PdfAsset"] = field(default_factory=list)
    pdf_results: dict[str, bool] = field(default_factory=dict)

    # Stage tracking
    current_stage: str = ""
    status: str = StageStatus.PENDING
    error: str = ""
    stages_completed: list[str] = field(default_factory=list)

    @property
    def failed(self) -> bool:
        return self.status == StageStatus.FAILED

    @property
    def completed(self) -> bool:
        return self.status == StageStatus.COMPLETED

    @property
    def pdf_count(self) -> int:
        return sum(1 for v in self.pdf_results.values() if v)
