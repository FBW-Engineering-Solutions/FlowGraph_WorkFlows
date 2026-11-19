# Maintainer notes

Contributors only need the README and CONTRIBUTING.md. This document collects
the implementation and migration details separately.

## Validation and CI

Run from the checkout root with Python 3.12; no dependencies are required:

```sh
python3 tools/validate_catalog.py
python3 -m unittest discover -s tests -v
```

Checks cover UTF-8 JSON, duplicate keys, finite numbers, 2 MiB file limits,
metadata, directory/key consistency, unique source IDs, graph endpoints, cycles,
incoming connections, boundary references, and nested workflow structure.
Only the two JSON files are accepted inside each workflow version folder.

The validator does not check node registration, port existence or compatibility,
runtime dependencies, execution results, or credentials. Legacy composites may
need runtime migration. Do not describe these checks as runtime verification.

CI runs on every push and PR, using a read-only token and pinned actions. It never
executes workflow code, contacts production, or uses deployment secrets. Do not
switch to `pull_request_target` to run contributed code. Review changes to CI,
tools, and tests carefully: a PR can change its own validator.

Dependabot proposes action updates. Keep those updates separate from catalog
changes. After publication, protect the default branch: require a PR and the
GitHub Actions **Catalog integrity** check, block force-pushes and deletion.
Zero required approvals allows a solo maintainer to merge their own PRs.
Branch protection must be configured in GitHub; these files do not enable it.

## Initial import

The 12 initial examples came from the current public Laravel catalog, not the
separate legacy PHP catalog. Workflow download bytes and metadata are preserved.
`migration/initial-import.json` records their source IDs, revisions and checksums.
Those checksums describe the original snapshot, not a lock against future edits.
Do not regenerate the manifest when changing a workflow.

`tools/import_public_catalog.py` is a one-time read-only exporter. It stages and
validates content, checks API revisions before/after import, respects rate limits,
and refuses to overwrite an existing workflow tree. For an isolated rehearsal:

```sh
python3 tools/import_public_catalog.py --root /absolute/path/to/existing-empty-directory
```

Do not use the exporter for recurring synchronization once Git is authoritative.
Source IDs are public catalog identifiers, not credentials; retain them to preserve
numeric IDs and download URLs at cutover.

## Publication review

Review all branches, tags, Git history, PRs, releases, Actions logs, and artifacts
before switching visibility. A clean current tree does not prove clean history.
Use a full-history secret scanner (for example Gitleaks) and human review. A scan
has limitations; any exposed credential needs revocation even after cleanup.

The pre-publication review found no secret-scanner findings in the three reachable
commits (initial import and two Dependabot branches), or in the working files.
The eight then-existing Actions run logs had no matches in the targeted credential
and private-path scan. No release, tag, or Actions artifact was present. These are
point-in-time findings, not a guarantee for later changes.

The initial commit includes the maintainer's personal email address in author and
committer metadata. This has been flagged to the owner; keep the repository private
until the owner chooses to retain it or authorizes a coordinated history rewrite.
Do not rewrite published history or force-push without that decision. A rewrite
would also need to account for the Dependabot branches and existing PR references.

Imported `/tmp/flowgraph-user-data` paths are documented editor demo paths, not
personal home directories. No datasets or binaries are included. The embedded
Python example calculates rectangle area and perimeter. Workflow authorship was
confirmed by the owner before applying BSD-3-Clause to all repository content.
Dependencies and externally supplied datasets retain their own license terms.

## Service cutover — not implemented

The website is still independently editable. Do not claim Git is the live service's
only writer yet. Avoid simultaneous website/repository editing; reconcile a final
snapshot before cutover.

1. Confirm a supported server import trigger. SFTP uploads alone cannot execute PHP;
   investigate hosting-scheduled tasks or another narrowly scoped mechanism.
2. Build versioned releases and a transactional, revalidating importer. Preserve
   workflow IDs, accounts and unrelated state. Serialize imports, reject stale
   releases, and support explicit retirement and rollback.
3. Test failures, recovery, and API/download smoke checks on staging.
4. Disable website publishing during final reconciliation. Keep Git-managed entries
   read-only afterward, then enable production synchronization.

No production configuration, task, deployment, or visibility change is made by
these repository files.
