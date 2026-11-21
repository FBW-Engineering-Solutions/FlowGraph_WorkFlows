# Publish the catalog after a PR is merged

For the authorized maintainer only. Contributors do not need hosting access.
Merging a PR does not publish it: running the release command authorizes publication.

## Normal use

1. Open a terminal in your FlowGraph_Workflows checkout.
2. Make sure you are on `master` with no unfinished changes:

   ```sh
   git switch master
   git status --short
   ```

   If status lists changes, finish or save them before continuing. Do not discard
   work just to make the release command run.

3. Run:

   ```sh
   make release-production
   ```

4. Enter your hosting SFTP password when prompted. It is not saved.
5. Leave the terminal open. The command updates `master`, runs tests, uploads only
   if catalog content changed, waits for the server, and verifies the live catalog.

**No arguments, release checksum edits, `.env` edits or cron toggles are needed.**
With an hourly cron, a new release may wait about an hour for the next run, plus
verification time. Public verification deliberately waits between requests.

For a changed catalog, completion is reported as:

```text
PASS: production import receipt and exact public catalog verified.
```

If no catalog content changed, the command skips uploading and verifies the
existing live catalog instead. Documentation/tool-only PRs do not create releases.

## Preview without publishing

```sh
make release-production-dry-run
```

This still updates Git, runs tests, prompts for the SFTP password and reads the
private server receipt. It does not upload or approve a release.

## One-time setup on another computer

Install Python 3.12, Git, Make and OpenSSH's `sftp`. Clone the repository, then run:

```sh
make setup-production
```

Enter the SFTP username and the path to an independently verified host-key file.
Settings are saved only in ignored `.local/production-release.json`. Never commit
that file, passwords, host-key files, receipts, release artifacts or database exports.
The SFTP password is entered separately each time you publish.

The server must already have the scheduled-sync application installed, its import
gates enabled, publishing disabled, and its single sync cron enabled. The old
manual apply/dry-run jobs stay paused. Its first successful run creates the private
database receipt. See `MAINTAINERS.md` for hosting setup and recovery details.

## If something fails

- **Dirty checkout or wrong branch:** save your work and return to clean `master`.
- **Missing server receipt:** check the sync cron's private logs and configuration.
  Do not create a receipt manually or guess the parent checksum.
- **Upload failure or lock error:** stop and inspect the private inbox. Do not
  delete locks or keep retrying without checking what was uploaded.
- **Timeout or terminal closed after approval:** the server may still import the
  release later. Check private logs and the receipt before taking recovery action.
- **Public verification failure:** the database may already have been updated.
  This is not an automatic rollback; check the reported mismatch or rate limit.

Private bundles are retained in ignored `.local/releases/`. Keep database backups
separately: a release bundle or receipt is not a database backup. Never paste private
configuration, receipts, credentials or SQL dumps into public issues or PRs.