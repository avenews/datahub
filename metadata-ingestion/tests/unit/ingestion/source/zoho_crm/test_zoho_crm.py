"""Unit tests for the Zoho CRM ingestion source."""

from typing import Any, Dict, List
from unittest.mock import patch

import pytest
from pydantic import SecretStr, ValidationError

from datahub.ingestion.api.common import PipelineContext
from datahub.ingestion.source.zoho_crm.zoho_crm_config import (
    REGION_TO_ACCOUNTS_DOMAIN,
    REGION_TO_API_DOMAIN,
    ZohoCRMSourceConfig,
    ZohoRegion,
)
from datahub.ingestion.source.zoho_crm.zoho_crm_source import ZohoCRMSource


def _build_config(**overrides: Any) -> ZohoCRMSourceConfig:
    base: Dict[str, Any] = {
        "client_id": "1000.ABCDEF",
        "client_secret": SecretStr("secret-client"),
        "refresh_token": SecretStr("secret-refresh"),
    }
    base.update(overrides)
    return ZohoCRMSourceConfig(**base)


# ---------- Config -----------------------------------------------------------


def test_config_defaults():
    config = _build_config()
    assert config.platform == "zoho-crm"
    assert config.region is ZohoRegion.US
    assert config.include_record_counts is True
    assert config.include_deprecated_modules is False
    assert config.modules_pattern.allowed("Leads") is True


def test_config_rejects_unknown_region():
    with pytest.raises(ValidationError):
        _build_config(region="MARS")


def test_region_maps_cover_all_regions():
    for region in ZohoRegion:
        assert region in REGION_TO_API_DOMAIN
        assert region in REGION_TO_ACCOUNTS_DOMAIN


def test_config_requires_credentials():
    with pytest.raises(ValidationError):
        ZohoCRMSourceConfig(  # type: ignore[call-arg]
            client_secret=SecretStr("x"), refresh_token=SecretStr("y")
        )


# ---------- Source -----------------------------------------------------------


def _new_source(**overrides: Any) -> ZohoCRMSource:
    return ZohoCRMSource(
        PipelineContext(run_id="zoho-test"), _build_config(**overrides)
    )


def test_to_schema_field_maps_known_types():
    source = _new_source()
    field = source._to_schema_field(
        {"api_name": "Email", "data_type": "email", "field_label": "Email"}
    )
    assert field.fieldPath == "Email"
    assert field.nativeDataType == "email"
    assert field.type.type.__class__.__name__ == "StringTypeClass"


def test_to_schema_field_falls_back_to_null_type():
    source = _new_source()
    field = source._to_schema_field(
        {
            "api_name": "Custom_Field",
            "data_type": "something-new",
            "field_label": "Custom",
        }
    )
    assert field.nativeDataType == "something-new"
    assert field.type.type.__class__.__name__ == "NullTypeClass"


def test_to_schema_field_marks_mandatory_as_non_nullable():
    source = _new_source()
    field = source._to_schema_field(
        {
            "api_name": "Last_Name",
            "data_type": "text",
            "system_mandatory": True,
            "field_label": "Last Name",
        }
    )
    assert field.nullable is False


def _captured_module_workunits(
    source: ZohoCRMSource,
    modules_payload: Dict[str, Any],
    fields_payload: Dict[str, Any],
) -> List[Any]:
    def fake_api_get(path: str, params: Dict[str, Any] = None):  # type: ignore[assignment]
        if path == "/crm/v2/settings/modules":
            return modules_payload
        if path == "/crm/v2/settings/fields":
            return fields_payload
        return {}

    with (
        patch.object(source, "_api_get", side_effect=fake_api_get),
        patch.object(source, "_fetch_record_count", return_value=None),
    ):
        return list(source.get_workunits_internal())


def test_modules_pattern_filters_modules():
    source = _new_source(
        modules_pattern={"allow": ["^Leads$"]},
        include_record_counts=False,
    )
    work_units = _captured_module_workunits(
        source,
        modules_payload={
            "modules": [
                {"api_name": "Leads", "plural_label": "Leads"},
                {"api_name": "Contacts", "plural_label": "Contacts"},
            ]
        },
        fields_payload={
            "fields": [
                {
                    "api_name": "Last_Name",
                    "data_type": "text",
                    "field_label": "Last Name",
                }
            ]
        },
    )

    assert source.report.modules_scanned == 1
    assert source.report.modules_skipped_by_pattern == ["Contacts"]
    # Properties + SubTypes + Schema for the single included module
    assert len(work_units) == 3


def test_deprecated_modules_skipped_by_default():
    source = _new_source(include_record_counts=False)
    _captured_module_workunits(
        source,
        modules_payload={
            "modules": [
                {"api_name": "Leads", "plural_label": "Leads"},
                {
                    "api_name": "Old_Module",
                    "plural_label": "Old",
                    "deprecated": True,
                },
            ]
        },
        fields_payload={"fields": []},
    )
    assert source.report.modules_skipped_deprecated == ["Old_Module"]
    assert source.report.modules_scanned == 1


def test_record_count_emitted_when_available():
    source = _new_source()

    def fake_api_get(path: str, params: Dict[str, Any] = None):  # type: ignore[assignment]
        if path == "/crm/v2/settings/modules":
            return {"modules": [{"api_name": "Leads", "plural_label": "Leads"}]}
        if path == "/crm/v2/settings/fields":
            return {
                "fields": [
                    {
                        "api_name": "Last_Name",
                        "data_type": "text",
                        "field_label": "Last Name",
                    }
                ]
            }
        return {}

    with (
        patch.object(source, "_api_get", side_effect=fake_api_get),
        patch.object(source, "_fetch_record_count", return_value=42),
    ):
        units = list(source.get_workunits_internal())

    profile_units = [
        u
        for u in units
        if u.metadata.aspect.__class__.__name__ == "DatasetProfileClass"
    ]
    assert len(profile_units) == 1
    assert profile_units[0].metadata.aspect.rowCount == 42
