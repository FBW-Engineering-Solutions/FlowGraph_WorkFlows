#!/usr/bin/env python3
"""Read-only production reconciliation against Git and the original import baseline."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
from urllib.error import URLError

from import_public_catalog import BASE, api, fetch
from validate_catalog import ROOT, MAX_BYTES, read_json, require, validate_catalog, InvalidCatalog


FIELDS = ('workflow_name', 'author', 'company', 'version', 'description', 'uploaded_at', 'json_filename')


def listing():
    first = api('api.php?page=1')
    total, pages = first.get('total'), first.get('pages')
    require(type(total) is int and 0 <= total <= 12000 and type(pages) is int
            and pages == max(1, (total + 11) // 12), 'invalid production pagination')
    entries = []
    for page in range(1, pages + 1):
        result = first if page == 1 else api(f'api.php?page={page}')
        require(result.get('page') == page and result.get('total') == total
                and result.get('pages') == pages and result.get('page_size') == 12
                and isinstance(result.get('entries'), list), 'production pagination changed')
        require(len(result['entries']) == min(12, max(0, total - (page - 1) * 12)), 'incomplete production page')
        entries.extend(result['entries'])
    revisions = {}
    for entry in entries:
        identity = entry.get('id')
        require(isinstance(identity, str) and identity.isascii() and identity.isdigit()
                and 1 <= len(identity) <= 19 and not identity.startswith('0')
                and identity not in revisions and type(entry.get('revision')) is int
                and 0 <= entry['revision'] < 2**48, 'invalid or duplicate production identity')
        revisions[identity] = entry['revision']
    return entries, revisions


def inventory(root):
    validate_catalog(root)
    entries = {}
    new = []
    for path in sorted((root / 'workflows').glob('*/*/metadata.json')):
        metadata = read_json(path)
        content = path.with_name('workflow.json').read_bytes()
        entry = {'metadata': metadata, 'sha256': hashlib.sha256(content).hexdigest()}
        if metadata['source'] is None:
            new.append(metadata['catalog_key'])
        else:
            entries[metadata['source']['id']] = entry
    return entries, new


def baseline_metadata(root, revision, key):
    if revision is None:
        return None
    require(len(revision) == 40 and all(c in '0123456789abcdef' for c in revision), 'invalid baseline commit')
    raw = subprocess.check_output(['git', '-C', str(root), 'show',
                                   revision + ':workflows/' + key + '/metadata.json'], stderr=subprocess.DEVNULL)
    return json.loads(raw)


def reconcile(root, list_catalog=listing, get_api=api, get_bytes=fetch, baseline=None):
    local, new = inventory(root)
    summaries, revisions = list_catalog()
    manifest = read_json(root / 'migration/initial-import.json')
    originals = {entry['source_id']: entry for entry in manifest['entries']}
    results = []
    observed = set()
    for summary in sorted(summaries, key=lambda entry: int(entry['id'])):
        identity = summary['id']
        observed.add(identity)
        remote = get_api('api.php?id=' + identity)['entry']
        require(isinstance(remote, dict), 'invalid production detail')
        require(remote['id'] == identity and remote['revision'] == revisions[identity],
                'production changed while collecting details')
        content = get_bytes('download.php?id=' + identity)
        require(len(content) <= MAX_BYTES and json.loads(content) == remote['workflow'],
                'production download/API mismatch')
        digest = hashlib.sha256(content).hexdigest()
        entry = local.get(identity)
        if entry is None:
            results.append({'source_id': identity, 'status': 'production-only', 'workflow_sha256': digest})
            continue
        require(all(isinstance(remote.get(field), str) for field in FIELDS), 'invalid production metadata')
        changed = [field for field in FIELDS if remote[field] != entry['metadata'][field]]
        byte_change = digest != entry['sha256']
        original = originals.get(identity)
        old_metadata = baseline_metadata(root, baseline, entry['metadata']['catalog_key'])
        remote_fields = [] if old_metadata is None else [field for field in FIELDS if remote[field] != old_metadata[field]]
        results.append({'source_id': identity, 'catalog_key': entry['metadata']['catalog_key'],
                        'status': 'match' if not changed and not byte_change else 'conflict',
                        'different_metadata_fields': changed, 'different_download_bytes': byte_change,
                        'production_bytes_changed_since_initial_import': original is None or digest != original['workflow_sha256'],
                        'production_metadata_changed_since_baseline': remote_fields if old_metadata is not None else None,
                        'workflow_sha256': digest})
    _, final_revisions = list_catalog()
    require(revisions == final_revisions, 'production changed during preflight; repeat after publishing freeze')
    missing = sorted(set(local) - observed, key=int)
    return {'schema_version': 1, 'source_catalog': BASE,
            'checked_at': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
            'entries': results, 'git_source_ids_missing_in_production': missing,
            'new_git_entries': new,
            'ready_for_exact_adoption': not missing and all(row['status'] == 'match' for row in results),
            'notice': 'Point-in-time public-content comparison only; no SQL, credentials, server configuration or ownership inspected.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--output', type=Path, required=True, help='New local JSON report, outside the checkout')
    parser.add_argument('--baseline-commit', help='Full original import commit for metadata comparison')
    args = parser.parse_args()
    try:
        root = args.root.resolve()
        commit = subprocess.check_output(['git', '-C', str(root), 'rev-parse', 'HEAD'], text=True).strip()
        dirty = bool(subprocess.check_output(['git', '-C', str(root), 'status', '--porcelain', '--untracked-files=all']).strip())
        destination = args.output.resolve()
        require(not destination.exists() and not destination.is_symlink(), 'report already exists')
        require(not destination.is_relative_to(root), 'save reports outside the checkout')
        report = reconcile(root, baseline=args.baseline_commit)
        report['git_commit'] = commit
        report['git_worktree_dirty'] = dirty
        with destination.open('x', encoding='utf-8') as stream:
            json.dump(report, stream, indent=2, ensure_ascii=False)
            stream.write('\n')
        print(f'Production preflight saved: {destination}. Server unchanged.')
        for row in report['entries']:
            print(f"ID {row['source_id']}: {row['status']} {','.join(row.get('different_metadata_fields', []))}")
        if not report['ready_for_exact_adoption']:
            parser.exit(2, 'Reconciliation required before initial production adoption. No production data changed.\n')
    except (InvalidCatalog, OSError, ValueError, KeyError, TypeError, AttributeError, URLError, subprocess.SubprocessError):
        parser.exit(1, 'Production preflight failed; report is not cutover approval. Server unchanged.\n')


if __name__ == '__main__':
    main()