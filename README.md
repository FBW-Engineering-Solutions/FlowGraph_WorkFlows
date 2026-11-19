# FlowGraph Workflows

Reviewable source files for the public FlowGraph workflow catalog.

**Current milestone: workflow sources and CI validation only.** This repository does
not yet update the website or its database. Production publishing has not been
disabled by this change. Until the later cutover, avoid simultaneous website edits
and repository edits: the initial import is a snapshot, not a live synchronization.

## Layout

```text
workflows/<workflow-slug>/<version>/metadata.json
workflows/<workflow-slug>/<version>/workflow.json
migration/initial-import.json
tools/validate_catalog.py
tests/test_catalog.py
.github/workflows/validate.yml
```

The initial content comes from the **current Laravel catalog**, not the separate
legacy PHP catalog. Original workflow download bytes, descriptions, filenames,
author attribution, versions, and upload timestamps are preserved. The import
record contains original source IDs and SHA-256 checksums for migration auditing.
It is historical provenance: do not regenerate it when editing workflows.

## Validate locally

Python 3.12 is used in CI. No third-party packages are needed.

```sh
python3 tools/validate_catalog.py
python3 -m unittest discover -s tests -v
```

Commands above are relative to your checkout. CI runs both on every pull request
and push, and can also be started manually. It does not contact production, execute
workflow code, use deployment credentials, or modify a database.

### Checks included

- UTF-8 JSON, duplicate JSON keys, non-finite numbers, and 2 MiB file limits.
- Required metadata, field lengths, safe paths/download filenames, UTC timestamps.
- Directory/key/version consistency and unique original database IDs.
- Supported FlowGraph envelope versions 1–3, node IDs, parameter objects, positions.
- Edge endpoints, duplicate incoming connections, cycles, boundary references.
- Recursively nested workflows and Python source-line representation.
- Unexpected files and symlinks inside the workflow tree.

### Limits

These are **static structural checks**, not an official FlowGraph runtime load or
execution test. They do not verify registered node definitions, port existence or
type compatibility, data files, external services, backend capabilities, or runtime
results. Older composite formats can need runtime migration beyond these checks.
Paths embedded in imported workflows are preserved and may need adapting locally.
Workflow Python and external-tool parameters must receive human security review.
Do not assume a green check means a workflow is safe to execute.

## Add or change a workflow

1. Create a branch and add/edit the two JSON files in a workflow version directory.
2. Use a lowercase hyphen-separated slug. Keep slugs and `catalog_key` stable.
3. For a new version, copy the directory and update `version` and `catalog_key`.
4. For a **new catalog entry**, use `"source": null`. Never copy another entry's
   `source` ID. Existing imported entries keep their source mapping unchanged.
5. Export the workflow from FlowGraph, then validate the whole repository locally.
6. Open a pull request describing behavior, capabilities, required files, and tests.
7. Merge only after CI passes and the workflow source has been reviewed.

Metadata schema version 1 has exactly these fields:

```json
{
  "schema_version": 1,
  "catalog_key": "my-workflow/1.0.0",
  "workflow_name": "My Workflow",
  "author": "Author name",
  "company": "",
  "version": "1.0.0",
  "description": "What this workflow does and how to use it.",
  "uploaded_at": "2026-11-20T00:00:00Z",
  "json_filename": "my-workflow.json",
  "source": null
}
```

`uploaded_at` is the publication timestamp in UTC; the example is not an automatic
default. The workflow JSON's own `version` is its **file format version**, separate
from the metadata's catalog version. Descriptions can contain Markdown; both JSON
files remain the authoritative content (no duplicated README description per entry).

## GitHub setup after the first push

The local repository was initialized on `master`; CI supports any branch name.
Choose the default branch deliberately when publishing. No remote is configured
by these files, and no commit or push is performed automatically.

In the GitHub repository settings:

- Enable Actions and protect the default branch with a ruleset/branch protection.
- Require pull requests and the **Catalog integrity** status check before merging.
- Disallow force-pushes and deletion of the default branch.
- Require review, especially for changes under `tools/`, `tests/`, and `.github/`.
- Enable secret scanning/push protection if available for your repository/plan.
- Add CODEOWNERS once the correct GitHub maintainer/team is known.

Actions are pinned to full commit hashes; Dependabot proposes action updates.
The validation job has only `contents: read` and checkout does not persist credentials.
Branch protection and reviews are GitHub settings, not automatically enabled by
adding this workflow. A PR can change its own validator, so review those changes.

## Initial import and provenance

`tools/import_public_catalog.py` is a one-time, read-only public API exporter. It
refuses to overwrite an existing workflow tree. All content is staged and validated
before installation, and API revisions are compared before/after downloading.
To rehearse into a separate **existing empty directory**, use:

```sh
python3 tools/import_public_catalog.py --root /absolute/path/to/empty-directory
```

It requires public network access but no passwords. Do not use it as a recurring
sync once Git becomes authoritative. Initial hashes document the original bytes;
normal reviewed updates will intentionally differ from those historical hashes.

No new license grant is inferred from public download availability. Preserve
existing attribution; the owner must choose/confirm workflow licensing before
accepting contributions or advertising broader reuse rights.

## Later milestones (not implemented)

1. Confirm an import mechanism supported by the hosting plan: SFTP uploads alone
   cannot execute a database import; investigate scheduled PHP tasks separately.
2. Build versioned release bundles and a revalidating, transactional catalog importer
   that preserves numeric IDs, accounts and unrelated state, rejects stale releases,
   serializes deployment, and supports rollback and explicit retirement.
3. Rehearse on staging, including failure recovery and API/download smoke tests.
4. Disable website publishing during the final snapshot/cutover, reconcile changes,
   then keep Git-managed entries read-only on the website.
5. Enable production deployment only after these safeguards are verified.

No server credentials belong in this repository or in pull-request checks.