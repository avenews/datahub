from dataclasses import dataclass, field
from typing import List

from datahub.ingestion.source.state.stale_entity_removal_handler import (
    StaleEntityRemovalSourceReport,
)


@dataclass
class PostHogSourceReport(StaleEntityRemovalSourceReport):
    projects_scanned: int = 0
    projects_skipped_by_pattern: List[str] = field(default_factory=list)
    events_scanned: int = 0
    events_skipped_by_pattern: List[str] = field(default_factory=list)
    events_failed: List[str] = field(default_factory=list)
    properties_skipped: List[str] = field(default_factory=list)
