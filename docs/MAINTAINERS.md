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

## Staging release bundles

After committing and reviewing changes, build outside the working tree:

```sh
python3 tools/build_release.py --initial --output /tmp/flowgraph-release
# Subsequent releases require the release ID currently deployed on staging:
python3 tools/build_release.py --previous-release CURRENT_64_CHARACTER_RELEASE_ID --output /tmp/flowgraph-next-release
```

The builder refuses dirty trees and existing destinations. Bundles contain a
deterministic `catalog.json` with source commit, schema version, parent release,
metadata, original workflow text and per-workflow SHA-256 checksums. `READY`
contains the SHA-256 of the exact payload bytes. JSON escaping does not alter the
download bytes recovered by the importer. Limits: 1,000 entries, 16 MiB total,
2 MiB per workflow. Build from the reviewed merge commit, not a local PR head.

Upload into the staging application's **private**
`storage/app/private/catalog-inbox/pending` directory, never its public directory.
Remove old `READY` first, upload `catalog.json`, then upload `READY` **last**.
Do not mutate a ready bundle during an import. The CLI-only staging importer
uses filesystem and database locks, validates before mutation and commits data,
entry mappings and release history together. Check cron logs for the resulting
release ID before preparing the next release. Checksums detect corruption, not
authenticity: SFTP credentials and reviewed source access remain trust boundaries.

## Manual GitHub Actions staging deployment

`Upload staging catalog` is an explicit `workflow_dispatch` workflow, never a push
or PR deployment. It only accepts `master`, validates/tests the checked-out commit,
builds a child bundle outside the checkout, and uploads catalog content only.
No application code, SQL, `.env`, or production files are uploaded. The Actions
result confirms **upload**, not database import. Keep the staging importer cron
enabled for import and confirm its logs and downloads after each deployment.

Before enabling it, create a GitHub environment named `staging` with deployment
branches restricted to **master only** (not tags), required maintainer review, and
admin protection bypass disabled. For a sole maintainer, self-review must remain
allowed so a manually initiated deployment can be approved. Environment restrictions
are mandatory: the workflow branch guard alone is not a credential boundary.

Configure only these **environment secrets**, never repository-wide secrets:

| Secret | Value |
|---|---|
| `STAGING_SFTP_USERNAME` | Dedicated least-privilege SFTP username |
| `STAGING_SFTP_PASSWORD` | That account's SFTP password, not a database password |
| `STAGING_SFTP_KNOWN_HOSTS` | Verified OpenSSH known_hosts line(s) for `ftp.cluster129.hosting.ovh.net` |

Verify the host key against the fingerprint already trusted in FileZilla or an
independent trusted hosting source. Do not trust `ssh-keyscan` output without
independent fingerprint verification. Strict host-key checking is never disabled.
Passwords are passed via SSH_ASKPASS, not command arguments, batch files or logs.

**Do not put a shared hosting credential with production access into Actions.**
The uploader hardcodes staging paths, but credentials themselves must be scoped
by the server. A compromised runner could ignore client-side path checks. Confirm
the account's visible SFTP filesystem has no production access. The current
uploader expects the verified SFTP-visible path:
`/home/fbwescj/catalog-staging/storage/app/private/catalog-inbox/pending`.
If a restricted account changes its visible root, adjust and review the uploader's
fixed path before using it; never widen the account's access to make it work.
No secrets are provisioned by repository files or the coding agent.

Run from Actions → Upload staging catalog → Run workflow, branch **master**:

- `previous_release`: the ID confirmed in `catalog_release_state`, not merely the
  previous Actions upload result. Confirm that release's cron import succeeded.
- `confirmation`: exactly `upload-staging`.
- Approve the environment deployment after reviewing source and input values.

Only one Actions deployment runs at a time; an SFTP `upload.lock` directory also
blocks concurrent uploaders. The remote pending marker must match the supplied
parent or the exact same release (retry). This does **not** query SQL: the importer
remains authoritative for stale-parent rejection. Wait for a successful import
before starting any child upload. Do not upload manually while Actions runs.

The payload is uploaded as `catalog.json.uploading`, downloaded for SHA-256
verification, and a temporary marker is staged. Only then is old READY removed,
the payload replaced, and the new marker renamed into place last. The importer
may safely reject temporary extra files during transfer; an in-flight importer
may finish the previous release. SQL locking and parent checks still apply.
Transient cron validation failures during upload are not deployment confirmation.

On an interrupted upload, the remote `upload.lock` intentionally remains. Pause
the importer cron, ensure no uploader is running, and inspect the private inbox.
If old READY/catalog are intact, remove only temporary `.uploading` files and the
empty `upload.lock`, then retry with the same confirmed parent. If the final pair
is incomplete, remove READY, restore a complete verified pair manually (READY
last), clean temporary files, and remove the empty lock. If the new final pair is
already intact, clean temporary files and the lock, resume cron, and confirm import
before dispatching again. Never delete release history or reset SQL release state.
Use `rmdir`/delete-empty-directory for the lock, never recursive application cleanup.

Automated upload requires its first hosted rehearsal. Production deployment remains
unsupported. After each successful import, run the website repository's read-only
verifier against the exact bundle and check repeat-import safety.

## Production service cutover — not implemented

The website is still independently editable. Do not claim Git is the live service's
only writer yet. Avoid simultaneous website/repository editing; reconcile a final
snapshot before cutover.

1. PHP 8.5 scheduled tasks have been verified on staging. Disable the diagnostic
   cron before setting up the importer cron; SFTP alone does not execute PHP.
2. The staging release builder and transactional importer are implemented. Rehearse
   deployment using the website repository's staging instructions. No automatic
   deletion or production importer is enabled; retirement needs explicit design.
3. Complete hosted staging failure/recovery and API/download smoke checks.
4. Disable website publishing during final reconciliation. Keep Git-managed entries
   read-only afterward, then enable production synchronization.

No production configuration, task, deployment, or visibility change is made by
these repository files.
