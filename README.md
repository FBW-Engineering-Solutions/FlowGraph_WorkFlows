# FlowGraph Workflows

A collection of example workflows for FlowGraph: meshes, images, datasets, and
simple Python functions. Browse `workflows/` to find an example.

## Try a workflow

1. Open an example's version folder under `workflows/`.
2. Download **workflow.json** (use GitHub's **Download raw file** button).
3. Open it in FlowGraph and read the annotations and `metadata.json` description.
4. Review its code and file paths before running. Some examples require sample
   files, optional dependencies, or a local Python backend.

The JSON file is the workflow; `metadata.json` provides its title, description,
author, and catalog version. Demo paths under `/tmp/flowgraph-user-data` refer to
temporary files in the editor, not files included in this repository.

## Contribute

Each version needs just two files:

```text
workflows/my-workflow/1.0.0/
  metadata.json
  workflow.json
```

Copy an existing example, export your workflow from FlowGraph, update the metadata
(use `"source": null` for a new entry), and open a pull request.
See **CONTRIBUTING.md** for the short checklist and metadata example.

To check your changes locally with Python 3.12 (no extra packages needed):

```sh
python3 tools/validate_catalog.py
```

GitHub checks every workflow automatically. These checks catch structural mistakes;
they do **not** execute workflows or guarantee that they are safe or run correctly.

## License

The workflows, descriptions, documentation, and repository tools are licensed under
**BSD-3-Clause**; see **LICENSE**. FlowGraph and any external libraries, datasets,
and tools have their own licenses. Referenced sample files are not distributed here.

## Publish an approved change (maintainers)

After the PR is merged, run `make release-production` from a clean `master`
checkout. It tests, uploads, waits for the private scheduled importer and verifies
the live catalog. It prompts for the hosting password; no per-release settings
or cron changes are needed after the one-time setup.

See **docs/RELEASING.md** for the short instructions and troubleshooting.
Hosting setup, migration history and CI details are in **docs/MAINTAINERS.md**.
