"""Unit tests for the PostHog ingestion source."""

from typing import Any, Dict, List
from unittest.mock import patch

import pytest
from pydantic import SecretStr, ValidationError

from datahub.ingestion.api.common import PipelineContext
from datahub.ingestion.source.posthog.posthog_config import PostHogSourceConfig
from datahub.ingestion.source.posthog.posthog_source import PostHogSource


def _build_config(**overrides: Any) -> PostHogSourceConfig:
    base: Dict[str, Any] = {"api_token": SecretStr("phx_test")}
    base.update(overrides)
    return PostHogSourceConfig(**base)


# ---------- Config -----------------------------------------------------------


def test_config_defaults():
    config = _build_config()
    assert config.platform == "posthog"
    assert config.host == "https://us.posthog.com"
    assert config.include_event_volume is True
    assert config.events_pattern.allowed("$pageview") is True


def test_config_accepts_custom_host():
    config = _build_config(host="https://eu.posthog.com")
    assert config.host == "https://eu.posthog.com"


def test_config_requires_api_token():
    with pytest.raises(ValidationError):
        PostHogSourceConfig()  # type: ignore[call-arg]


# ---------- Source -----------------------------------------------------------


def _new_source(**overrides: Any) -> PostHogSource:
    return PostHogSource(
        PipelineContext(run_id="posthog-test"), _build_config(**overrides)
    )


def test_to_schema_field_maps_known_types():
    source = _new_source()
    field = source._to_schema_field(
        {"name": "$revenue", "property_type": "Numeric", "description": "Revenue"}
    )
    assert field.fieldPath == "$revenue"
    assert field.nativeDataType == "numeric"
    assert field.type.type.__class__.__name__ == "NumberTypeClass"


def test_to_schema_field_falls_back_to_null_type():
    source = _new_source()
    field = source._to_schema_field({"name": "weird_prop", "property_type": None})
    assert field.nativeDataType == "unknown"
    assert field.type.type.__class__.__name__ == "NullTypeClass"


def _captured_workunits(
    source: PostHogSource,
    projects: List[Dict[str, Any]],
    events_by_project: Dict[int, List[Dict[str, Any]]],
    properties_by_event: Dict[str, List[Dict[str, Any]]],
) -> List[Any]:
    def fake_paginate(path: str, params: Dict[str, Any] = None):  # type: ignore[assignment]
        if path == "/api/projects/":
            return iter(projects)
        if path.startswith("/api/projects/") and path.endswith("/event_definitions/"):
            project_id = int(path.split("/")[3])
            return iter(events_by_project.get(project_id, []))
        if path.startswith("/api/projects/") and path.endswith(
            "/property_definitions/"
        ):
            event_names = params.get("event_names") if params else None
            key = event_names or ""
            return iter(properties_by_event.get(key, []))
        return iter([])

    with patch.object(source, "_paginate", side_effect=fake_paginate):
        return list(source.get_workunits_internal())


def test_projects_pattern_filters_projects():
    source = _new_source(
        projects_pattern={"allow": ["^Production$"]},
        include_event_volume=False,
    )
    _captured_workunits(
        source,
        projects=[
            {"id": 1, "name": "Production"},
            {"id": 2, "name": "Staging"},
        ],
        events_by_project={1: [], 2: []},
        properties_by_event={},
    )
    assert source.report.projects_scanned == 1
    assert source.report.projects_skipped_by_pattern == ["Staging"]


def test_events_pattern_filters_events():
    source = _new_source(
        events_pattern={"allow": ["^signup_completed$"]},
        include_event_volume=False,
    )
    _captured_workunits(
        source,
        projects=[{"id": 1, "name": "Prod"}],
        events_by_project={
            1: [
                {"name": "signup_completed"},
                {"name": "$pageview"},
            ]
        },
        properties_by_event={'["signup_completed"]': []},
    )
    assert source.report.events_scanned == 1
    assert source.report.events_skipped_by_pattern == ["$pageview"]


def test_event_volume_emitted_when_available():
    source = _new_source()
    units = _captured_workunits(
        source,
        projects=[{"id": 7, "name": "Prod"}],
        events_by_project={
            7: [
                {
                    "name": "signup_completed",
                    "description": "User finished signup",
                    "volume_30_day": 1234,
                }
            ]
        },
        properties_by_event={
            '["signup_completed"]': [
                {"name": "$revenue", "property_type": "Numeric"},
                {"name": "plan", "property_type": "String"},
            ]
        },
    )
    profile_units = [
        u
        for u in units
        if u.metadata.aspect.__class__.__name__ == "DatasetProfileClass"
    ]
    assert len(profile_units) == 1
    assert profile_units[0].metadata.aspect.rowCount == 1234
    assert profile_units[0].metadata.aspect.columnCount == 2


def test_dataset_name_sanitizes_project():
    source = _new_source(include_event_volume=False)
    units = _captured_workunits(
        source,
        projects=[{"id": 9, "name": "My Project / 2024"}],
        events_by_project={9: [{"name": "$pageview"}]},
        properties_by_event={'["$pageview"]': []},
    )
    properties_unit = next(
        u
        for u in units
        if u.metadata.aspect.__class__.__name__ == "DatasetPropertiesClass"
    )
    # Spaces and `/` are collapsed to `_`, then joined to the event name.
    assert properties_unit.metadata.aspect.qualifiedName == "My_Project_2024.$pageview"
