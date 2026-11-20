#!/usr/bin/env python3
"""One-time import of public Laravel catalog content; no login or database access."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import tempfile
import time
import unicodedata
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, Request, build_opener

from validate_catalog import MAX_BYTES, ROOT, InvalidCatalog, require, validate_catalog


BASE = 'https://flowgraph-catalog.fbw-es.com/workflows/'


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def fetch(endpoint):
    require(re.fullmatch(r'(?:api|download)\.php\?(?:page|id)=[1-9][0-9]*', endpoint), 'unsafe public endpoint')
    # Respect the public service's rate limits instead of issuing a burst of reads.
    for attempt in range(5):
        time.sleep(2)
        try:
            request = Request(BASE + endpoint, headers={'Accept-Encoding': 'identity'}, method='GET')
            with build_opener(NoRedirect()).open(request, timeout=30) as response:
                require(response.status == 200 and response.headers.get_content_type() == 'application/json',
                        'unexpected public response status or content type')
                data = response.read(8 * MAX_BYTES + 1)
                require(len(data) <= 8 * MAX_BYTES, 'catalog response is too large')
                return data
        except HTTPError as exc:
            if exc.code != 429 or attempt == 4:
                raise
            retry = exc.headers.get('Retry-After', '')
            delay = max(60, min(int(retry), 300)) if retry.isdigit() else 60 * (attempt + 1)
            print(f'Public catalog rate limit; waiting {delay}s before retrying.', flush=True)
            exc.close()
            time.sleep(delay)


def api(endpoint):
    payload = json.loads(fetch(endpoint))
    require(isinstance(payload, dict) and payload.get('format') == 'flowgraph-workflow-catalog'
            and payload.get('schema_version') == 1, 'unsupported public API response')
    return payload


def listing():
    first = api('api.php?page=1')
    require(type(first.get('pages')) is int and 1 <= first['pages'] <= 1000,
            'invalid pagination')
    entries = list(first['entries'])
    for page in range(2, first['pages'] + 1):
        current = api(f'api.php?page={page}')
        require(current['total'] == first['total'] and current['pages'] == first['pages'],
                'catalog changed during pagination; retry')
        entries.extend(current['entries'])
    require(len(entries) == first['total'] and entries, 'incomplete or empty catalog')
    identities = {}
    for entry in entries:
        require(isinstance(entry.get('id'), str)
                and re.fullmatch(r'[1-9][0-9]{0,18}', entry['id']), 'unsafe API ID')
        require(entry['id'] not in identities, 'duplicate API ID; retry')
        identities[entry['id']] = entry['revision']
    return entries, identities


def slugify(name):
    ascii_name = unicodedata.normalize('NFKD', name).encode('ascii', 'ignore').decode()
    slug = re.sub(r'[^a-z0-9]+', '-', ascii_name.lower()).strip('-')
    require(bool(slug), 'workflow name cannot be converted to a stable slug')
    return slug


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')


def import_catalog(root):
    require(not (root / 'workflows').exists(), 'workflows already exists; refusing to overwrite')
    require(not (root / 'migration' / 'initial-import.json').exists(),
            'initial-import.json already exists; refusing to overwrite')
    entries, revisions = listing()
    records = []
    with tempfile.TemporaryDirectory(prefix='.catalog-import-', dir=root) as temporary:
        stage = Path(temporary)
        for summary in sorted(entries, key=lambda entry: int(entry['id'])):
            entry = api('api.php?id=' + summary['id'])['entry']
            require(entry['id'] == summary['id'] and entry['revision'] == summary['revision'],
                    'catalog changed during import; retry')
            original = fetch('download.php?id=' + entry['id'])
            require(len(original) <= MAX_BYTES, 'workflow exceeds catalog size limit')
            require(json.loads(original) == entry['workflow'], 'download and API content differ')
            slug = slugify(entry['workflow_name'])
            version = entry['version']
            require(isinstance(version, str)
                    and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,79}', version),
                    'unsafe version directory')
            directory = stage / 'workflows' / slug / version
            require(not directory.exists(), 'duplicate workflow name/version; assign slugs manually')
            directory.mkdir(parents=True)
            metadata = {'schema_version': 1, 'catalog_key': f'{slug}/{version}'}
            for key in ('workflow_name', 'author', 'company', 'version', 'description',
                        'uploaded_at', 'json_filename'):
                metadata[key] = entry[key]
            metadata['source'] = {'catalog_url': BASE, 'id': entry['id']}
            write_json(directory / 'metadata.json', metadata)
            (directory / 'workflow.json').write_bytes(original)
            records.append({'catalog_key': metadata['catalog_key'], 'source_id': entry['id'],
                            'source_revision': entry['revision'],
                            'workflow_sha256': hashlib.sha256(original).hexdigest(),
                            'metadata_sha256': hashlib.sha256(
                                (directory / 'metadata.json').read_bytes()).hexdigest()})
        _, final_revisions = listing()
        require(revisions == final_revisions, 'catalog changed during import; retry')
        count = validate_catalog(stage)
        manifest = {'schema_version': 1, 'source_catalog': BASE,
                    'imported_at': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
                    'workflow_count': count, 'entries': records}
        (root / 'migration').mkdir(exist_ok=True)
        (stage / 'workflows').rename(root / 'workflows')
        write_json(root / 'migration' / 'initial-import.json', manifest)
    return count


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    args = parser.parse_args()
    try:
        print(f'Imported {import_catalog(args.root.resolve())} public workflows; server unchanged.')
    except (InvalidCatalog, OSError, ValueError, KeyError) as exc:
        parser.exit(1, f'Import failed: {exc}\n')


if __name__ == '__main__':
    main()