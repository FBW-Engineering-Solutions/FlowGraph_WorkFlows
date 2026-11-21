#!/usr/bin/env python3
"""Local one-command production release using a permanently scheduled private importer."""

import argparse
import getpass
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

from build_release import build_release
from production_transport import connect, validate_connection
from upload_staging import PRODUCTION_INBOX, publish, quote, validate_bundle
from validate_catalog import ROOT, InvalidCatalog, require
from verify_production import verify

CONFIG = ROOT / '.local/production-release.json'


def git(root, *arguments):
    return subprocess.check_output(['git', '-C', str(root), *arguments], text=True).strip()


def check_source(root):
    require(not git(root, 'status', '--porcelain', '--untracked-files=all'),
            'release requires a clean checkout, including untracked files')
    require(git(root, 'branch', '--show-current') == 'master', 'switch to merged master before releasing')
    subprocess.run(['git', '-C', str(root), 'fetch', 'origin',
                    'refs/heads/master:refs/remotes/origin/master'], check=True)
    subprocess.run(['git', '-C', str(root), 'merge', '--ff-only', 'origin/master'], check=True)
    commit = git(root, 'rev-parse', 'HEAD')
    require(commit == git(root, 'rev-parse', 'origin/master'),
            'local master must equal fetched origin/master; unpublished local commits cannot be deployed')
    return commit


def load_settings(path):
    require(path.is_file() and not path.is_symlink(), 'run make setup-production once to save local settings')
    settings = json.loads(path.read_text())
    require(set(settings) == {'username', 'known_hosts', 'wait_seconds'}, 'unexpected local settings; never save passwords')
    require(type(settings['wait_seconds']) is int and 60 <= settings['wait_seconds'] <= 172800,
            'wait_seconds must be between 60 and 172800')
    validate_connection(settings['username'], settings['known_hosts'])
    return settings


def setup():
    require(sys.stdin.isatty(), 'setup requires a local terminal')
    require(not CONFIG.exists(), 'settings already exist; edit the private local file if needed')
    username = input('Production SFTP username (not a database username): ').strip()
    key = input('Verified known_hosts path [~/.ssh/flowgraph-staging-known_hosts]: ').strip()
    key = str(Path(key or '~/.ssh/flowgraph-staging-known_hosts').expanduser().resolve())
    validate_connection(username, key)
    CONFIG.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with CONFIG.open('x') as stream:
        CONFIG.chmod(0o600)
        json.dump({'username': username, 'known_hosts': key, 'wait_seconds': 90000}, stream, indent=2)
        stream.write('\n')
    print('Saved non-secret local settings. No password saved. Hosting scheduled-sync setup is required once.')


def receipt(session, work):
    local = work / 'receipt.json'
    local.unlink(missing_ok=True)
    session(['get ' + quote(PRODUCTION_INBOX + '/current-release.json') + ' ' + quote(str(local))])
    require(local.stat().st_size <= 1048576, 'oversized receipt')
    value = json.loads(local.read_text())
    require(value.get('format') == 'flowgraph-production-receipt' and value.get('schema_version') == 1
            and re.fullmatch(r'[a-f0-9]{64}', value.get('release_id', ''))
            and re.fullmatch(r'[a-f0-9]{40}', value.get('source_commit', ''))
            and isinstance(value.get('entries'), list), 'invalid production receipt')
    return value


def approve(identity, session, work):
    marker = work / 'APPROVED'
    marker.write_text(identity + '\n', encoding='ascii')
    session(['cd ' + quote(PRODUCTION_INBOX), 'put ' + quote(str(marker)) + ' APPROVED.uploading',
             'get APPROVED.uploading ' + quote(str(work / 'approval-roundtrip'))])
    require((work / 'approval-roundtrip').read_bytes() == marker.read_bytes(), 'approval round-trip mismatch')
    session(['cd ' + quote(PRODUCTION_INBOX), '-rm APPROVED', 'rename APPROVED.uploading APPROVED'])


def deploy(root, settings, session, work, commit, dry_run=False):
    current = receipt(session, work)
    require(subprocess.run(['git', '-C', str(root), 'merge-base', '--is-ancestor',
                            current['source_commit'], commit]).returncode == 0,
            'deployed source is not an ancestor of this master')
    changed = git(root, 'diff', current['source_commit'], commit, '--', 'workflows')
    if not changed:
        print('No catalog changes since the deployed source. Verifying current public catalog.', flush=True)
        if not dry_run:
            verify(root, current)
        return
    previous = current['release_id']
    bundle = root / '.local/releases' / (commit + '-' + previous) / 'bundle'
    if bundle.exists():
        identity = validate_bundle(bundle, previous)
        require(json.loads((bundle / 'catalog.json').read_text())['source_commit'] == commit, 'saved bundle source mismatch')
    else:
        identity = build_release(root, bundle, previous, commit)
    print(f'Release: {identity}\nParent: {previous}\nRetained bundle: {bundle}', flush=True)
    if dry_run:
        print('Dry run: private receipt read only; no bundle uploaded or approved.')
        return
    publish(bundle, previous, session, work, PRODUCTION_INBOX)
    approve(identity, session, work)
    print('Uploaded and approved. Waiting for the private scheduled importer; do not re-upload.', flush=True)
    deadline = time.monotonic() + settings['wait_seconds']
    while time.monotonic() < deadline:
        latest = receipt(session, work)
        if latest['release_id'] == identity:
            require(latest['source_commit'] == commit, 'receipt source mismatch')
            verify(root, latest)
            print('PASS: production import receipt and exact public catalog verified.', flush=True)
            return
        require(latest['release_id'] == previous, 'another release was deployed; inspect private state')
        time.sleep(60)
    raise InvalidCatalog('timed out waiting for cron; bundle remains approved and MAY import later; inspect logs, do not blindly retry')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--setup', action='store_true')
    parser.add_argument('--dry-run', action='store_true', help='reads private receipt over SFTP but never uploads or approves')
    args = parser.parse_args()
    try:
        require(not os.environ.get('CI') and not os.environ.get('GITHUB_ACTIONS'), 'local releases only')
        if args.setup:
            setup()
            return
        settings = load_settings(CONFIG)
        commit = check_source(ROOT)
        subprocess.run([sys.executable, '-m', 'unittest', 'discover', '-s', 'tests', '-v'], cwd=ROOT, check=True)
        subprocess.run([sys.executable, str(ROOT / 'tools/validate_catalog.py')], cwd=ROOT, check=True)
        require(not git(ROOT, 'status', '--porcelain', '--untracked-files=all')
                and git(ROOT, 'rev-parse', 'HEAD') == commit, 'checkout changed during tests')
        require(sys.stdin.isatty(), 'run from a trusted local terminal')
        print('Production target: flowgraph-catalog.fbw-es.com. This command authorizes the merged catalog.', flush=True)
        password = getpass.getpass('Hosting SFTP password (not saved): ')
        with connect(settings['username'], settings['known_hosts'], password) as (session, work):
            deploy(ROOT, settings, session, work, commit, args.dry_run)
    except (InvalidCatalog, OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as exc:
        parser.exit(1, f'Release stopped: {exc}\nImport success is not confirmed. Preserve bundles and inspect private logs/locks before retrying.\n')


if __name__ == '__main__':
    main()