"""Paced public verification using database-assigned IDs from a private receipt."""

import json
import time
from urllib.request import Request, build_opener

from import_public_catalog import BASE, NoRedirect
from validate_catalog import read_json, require


def fetch(endpoint):
    time.sleep(4)
    request = Request(BASE + endpoint, headers={'Accept-Encoding': 'identity'}, method='GET')
    with build_opener(NoRedirect()).open(request, timeout=30) as response:
        require(response.status == 200, 'unexpected public status')
        raw = response.read(16777217)
        require(len(raw) <= 16777216, 'oversized public response')
        return response.headers, raw


def verify(root, receipt, request=fetch):
    mapping = {}
    for entry in receipt['entries']:
        key, identity = entry['catalog_key'], str(entry['workflow_id'])
        require(key not in mapping and identity.isascii() and identity.isdigit()
                and 0 < int(identity) < 10**19, 'invalid receipt mapping')
        mapping[key] = identity
    expected = {}
    for path in sorted((root / 'workflows').glob('*/*/metadata.json')):
        metadata = read_json(path)
        key = metadata['catalog_key']
        require(key in mapping, 'receipt missing workflow mapping')
        identity = mapping[key]
        require(identity not in expected, 'duplicate receipt workflow ID')
        expected[identity] = (metadata, path.with_name('workflow.json').read_bytes())
    headers, raw = request('api.php?page=1')
    first = json.loads(raw)
    require(first.get('format') == 'flowgraph-workflow-catalog' and first.get('schema_version') == 1,
            'invalid public listing')
    pages = first.get('pages')
    require(type(pages) is int and 1 <= pages <= 1000, 'invalid listing pagination')
    listed = []
    for page in range(1, pages + 1):
        result = first if page == 1 else json.loads(request(f'api.php?page={page}')[1])
        require(result.get('page') == page and result.get('pages') == pages
                and result.get('total') == len(expected), 'public catalog count or pagination mismatch')
        listed.extend(item['id'] for item in result['entries'])
    require(len(listed) == len(expected) and set(listed) == set(expected), 'public IDs differ from release')
    for identity, (metadata, content) in expected.items():
        detail = json.loads(request(f'api.php?id={identity}')[1])['entry']
        require(detail['id'] == identity, 'public detail ID mismatch')
        for field in ('workflow_name', 'author', 'company', 'version', 'uploaded_at', 'description', 'json_filename'):
            require(detail.get(field) == metadata[field], f'ID {identity}: {field} differs')
        require(detail.get('workflow') == json.loads(content), 'public workflow differs')
        headers, raw = request(f'download.php?id={identity}')
        require(headers.get_content_type() == 'application/json'
                and headers.get_content_disposition() == 'attachment'
                and headers.get_filename() == metadata['json_filename'], 'download headers differ')
        require(raw == content, 'download bytes differ')
        print(f'OK ID {identity}: metadata, filename and exact download bytes', flush=True)