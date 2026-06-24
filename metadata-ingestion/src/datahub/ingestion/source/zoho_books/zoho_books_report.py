from dataclasses import dataclass, field
from typing import List

from datahub.ingestion.source.state.stale_entity_removal_handler import (
    StaleEntityRemovalSourceReport,
)


@dataclass
class ZohoBooksSourceReport(StaleEntityRemovalSourceReport):
    modules_scanned: int = 0
    modules_skipped_by_pattern: List[str] = field(default_factory=list)
    modules_failed: List[str] = field(default_factory=list)
    record_count_failed: List[str] = field(default_factory=list)
    schema_sample_failed: List[str] = field(default_factory=list)
