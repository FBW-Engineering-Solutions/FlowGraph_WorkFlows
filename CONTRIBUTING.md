# Contributing

## Add or update an example

1. Create a branch (or fork) and copy a workflow version folder.
2. Replace `workflow.json` with your FlowGraph export.
3. Update `metadata.json`. For a new entry or version, set `source` to `null`.
4. Run `python3 tools/validate_catalog.py` from the checkout root.
5. Open a pull request describing how you tested it and any required files,
   dependencies, backend, network access, file writes, or embedded Python.

Keep existing folder names and catalog keys stable. For a new version, create a
new version folder; do not copy the previous version's source database ID.
Leave the source mapping on imported entries unchanged.

## Metadata example

```json
{
  "schema_version": 1,
  "catalog_key": "my-workflow/1.0.0",
  "workflow_name": "My Workflow",
  "author": "Your name",
  "company": "",
  "version": "1.0.0",
  "description": "What it does, what it needs, and how to run it.",
  "uploaded_at": "2026-11-20T12:00:00Z",
  "json_filename": "my-workflow.json",
  "source": null
}
```

Use a lowercase, hyphen-separated folder name and a filename without spaces or
path separators. `catalog_key` must match `<folder>/<version>`. Use your actual
publication time in UTC for `uploaded_at`; the timestamp above is only an example.
The workflow JSON's integer `version` is its file format, not this catalog version.
Descriptions can use Markdown. No separate README is needed inside an example.

## Before submitting

- Include only content you have the right to contribute under BSD-3-Clause.
  Unless explicitly agreed otherwise, contributions are under the repository's
  BSD-3-Clause license. Preserve author attribution and applicable notices.
- Do not include credentials, personal/private paths, private data, or datasets.
  Use documented demo paths or explain how users supply their own files.
- Test in FlowGraph when possible and report the version/backend used. Static
  validation is not a runtime or security test.
- For changes to tools or CI, also run
  `python3 -m unittest discover -s tests -v` and explain the change.
