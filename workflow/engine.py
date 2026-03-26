"""
Workflow engine — runs documents through a pipeline of named stages.

Each stage processes a batch of WorkflowItems. Stages run in order.
Failed items are skipped by subsequent stages.
"""

from abc import ABC, abstractmethod

from workflow.models import WorkflowItem, StageStatus


class Stage(ABC):
    """
    Base class for a pipeline stage.

    Subclasses must implement:
        - name (property): short identifier like "extract", "download"
        - process(item): process a single WorkflowItem

    Override process_batch() for parallel execution (see DownloadStage).
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Short identifier for this stage."""
        ...

    @abstractmethod
    def process(self, item: WorkflowItem) -> WorkflowItem:
        """
        Process a single item. Modify and return the item.
        Raise an exception to mark the item as failed.
        """
        ...

    def process_batch(self, items: list[WorkflowItem]) -> list[WorkflowItem]:
        """
        Process a batch of items sequentially.
        Override this for parallel execution.
        """
        for item in items:
            if item.failed:
                continue  # skip items that failed in earlier stages

            try:
                item.current_stage = self.name
                item.status = StageStatus.PROCESSING
                self.process(item)
                item.status = StageStatus.COMPLETED
                item.stages_completed.append(self.name)
            except Exception as exc:
                item.status = StageStatus.FAILED
                item.error = f"[{self.name}] {exc}"
                print(f"      ✗ [{self.name}] {exc}")

        return items


class WorkflowEngine:
    """
    Runs batches of documents through an ordered pipeline of stages.

    Usage:
        engine = WorkflowEngine([ExtractStage(...), DownloadStage(...), StoreStage(...)])
        results = engine.run_batch(items)
    """

    def __init__(self, stages: list[Stage]):
        self.stages = stages

    def run_batch(self, items: list[WorkflowItem]) -> list[WorkflowItem]:
        """Run a batch of items through all stages in order."""
        for stage in self.stages:
            items = stage.process_batch(items)
        return items

    @property
    def stage_names(self) -> list[str]:
        return [s.name for s in self.stages]
