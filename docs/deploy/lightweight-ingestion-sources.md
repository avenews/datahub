# Curating the "Create Source" Picker

The list of connectors shown in the **Create Source** wizard in the UI is driven by two static JSON
files in the frontend. To keep our deployment lightweight and reduce choice fatigue we hide most
connector cards by default. **No connector is removed from DataHub** — every hidden source is still
fully installed in the ingestion executor image and can be used at any time via the **Other**
(custom YAML) card, the `datahub ingest` CLI, or by un-hiding the entry as described below.

## Currently visible sources

| Connector           | Available in v1 picker | Available in v2 picker |
| ------------------- | :--------------------: | :--------------------: |
| Confluence          |           ✓            |           ✓            |
| CSV                 |           ✓            |           ✓            |
| dbt                 |           ✓            |           ✓            |
| dbt Cloud           |           ✓            |           ✓            |
| Grafana             |           ✓            |           ✓            |
| MongoDB             |           ✓            |           ✓            |
| Snowflake           |           ✓            |           ✓            |
| PostHog             |           —            |           ✓            |
| S3                  |           —            |           ✓            |
| SageMaker           |           —            |           ✓            |
| Zoho Books          |           —            |           ✓            |
| Zoho CRM            |           —            |           ✓            |
| Other (custom YAML) |           ✓            |           ✓            |

Connectors in the "v2 only" rows do not have native cards in the legacy v1 builder upstream;
they are reached there via the **Other** card.

## Restoring a hidden connector

Hiding is controlled by a single `"hidden": true` line on each entry in the picker config. To
re-enable a connector for users, delete (or flip to `false`) that one line in **both** files:

- [datahub-web-react/src/app/ingest/source/builder/sources.json](../../datahub-web-react/src/app/ingest/source/builder/sources.json) — legacy ingestion UI
- [datahub-web-react/src/app/ingestV2/source/builder/sources.json](../../datahub-web-react/src/app/ingestV2/source/builder/sources.json) — current ingestion UI

Example — restoring BigQuery:

```diff
 {
     "urn": "urn:li:dataPlatform:bigquery",
     "name": "bigquery",
-    "hidden": true,
     "displayName": "BigQuery",
     ...
 }
```

Then rebuild the frontend container:

```bash
scripts/dev/datahub-dev.sh rebuild --wait
```

## How the hiding works

Three small filters in the picker components skip entries whose `hidden` flag is set:

- [datahub-web-react/src/app/ingest/source/builder/SelectTemplateStep.tsx](../../datahub-web-react/src/app/ingest/source/builder/SelectTemplateStep.tsx) — legacy modal picker
- [datahub-web-react/src/app/ingestV2/source/builder/SelectTemplateStep.tsx](../../datahub-web-react/src/app/ingestV2/source/builder/SelectTemplateStep.tsx) — v2 "Connect Data Source" modal picker
- [datahub-web-react/src/app/ingestV2/source/multiStepBuilder/steps/step1SelectSource/SelectSourceStep.tsx](../../datahub-web-react/src/app/ingestV2/source/multiStepBuilder/steps/step1SelectSource/SelectSourceStep.tsx) — v2 standalone create-source page picker

The `useIngestionSources` hook and downstream lookups intentionally keep returning the _full_ list
(including hidden entries) so that **existing ingestion sources continue to render and stay
editable** even if their connector type has since been hidden from the picker.

## Using a hidden connector without un-hiding it

Either of these works for any connector — visible or not:

1. **From the UI**: pick **Other** in the Create Source wizard and paste the YAML recipe from
   the connector's docs page on [docs.datahub.com](https://docs.datahub.com/docs/metadata-ingestion).
2. **From the CLI**: `datahub ingest -c recipe.yml` (the executor image already has all
   connector extras installed).

## Why we did this

- Reduces visual clutter in the source picker so users see only the platforms we actually run.
- Zero runtime cost difference — the connectors live in the ingestion executor image, not in the
  frontend bundle. This change is a UX curation, not a deployment slimming.
- Fully reversible without code changes beyond toggling a single boolean per entry.
