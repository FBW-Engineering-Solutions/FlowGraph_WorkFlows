#!/usr/bin/env python3
"""Build a deterministic staging catalog bundle. Never connects to the server."""

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tempfile

from validate_catalog import ROOT, InvalidCatalog, read_json, require, validate_catalog


MAX_RELEASE_BYTES = 16 * 1024 * 1024


def build_release(root, output, previous_release, source_commit):
    require(re.fullmatch(r'[0-9a-f]{40}', source_commit), 'source commit must be a full Git SHA')
    require(previous_release is None or re.fullmatch(r'[0-9a-f]{64}', previous_release),
            'previous release must be a SHA-256 release ID')
    require(not output.exists() and not output.is_symlink(), 'output already exists')
    count = validate_catalog(root)
    require(count <= 1000, 'release supports at most 1000 entries')
    entries = []
    for path in sorted((root / 'workflows').glob('*/*/metadata.json')):
        raw = path.with_name('workflow.json').read_bytes()
        entries.append({'metadata': read_json(path), 'workflow_json': raw.decode('utf-8'),
                        'workflow_sha256': hashlib.sha256(raw).hexdigest()})
    payload = {'format': 'flowgraph-catalog-release', 'schema_version': 1,
               'source_commit': source_commit, 'previous_release': previous_release,
               'entries': entries}
    raw = (json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(',', ':'),
                      allow_nan=False) + '\n').encode('utf-8')
    require(len(raw) <= MAX_RELEASE_BYTES, 'release exceeds 16 MiB')
    release_id = hashlib.sha256(raw).hexdigest()
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.release-', dir=output.parent) as temporary:
        stage = Path(temporary) / 'bundle'
        stage.mkdir()
        (stage / 'catalog.json').write_bytes(raw)
        (stage / 'READY').write_text(release_id + '\n', encoding='ascii')
        stage.rename(output)
    return release_id


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--output', type=Path, required=True)
    parent = parser.add_mutually_exclusive_group(required=True)
    parent.add_argument('--initial', action='store_true', help='only for first deployment')
    parent.add_argument('--previous-release', help='current server release ID')
    args = parser.parse_args()
    try:
        root = args.root.resolve()
        # Include staged, unstaged and untracked content: a release must describe its commit.
        require(not subprocess.check_output(
            ['git', '-C', str(root), 'status', '--porcelain', '--untracked-files=all']).strip(),
            'commit changes before building a release')
        commit = subprocess.check_output(['git', '-C', str(root), 'rev-parse', 'HEAD'], text=True).strip()
        release_id = build_release(root, args.output.absolute(), args.previous_release, commit)
        print(f'Release {release_id}\nBundle: {args.output.absolute()}\nUpload catalog.json first, READY last.')
    except (InvalidCatalog, OSError, subprocess.CalledProcessError) as exc:
        parser.exit(1, f'Release build failed: {exc}\n')


if __name__ == '__main__':
    main()