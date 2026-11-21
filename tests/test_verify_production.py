from contextlib import redirect_stdout
from email.message import Message
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from test_catalog import make_entry
from validate_catalog import InvalidCatalog
from verify_production import verify


class ProductionVerificationTests(unittest.TestCase):
    def test_new_entry_uses_receipt_id_and_exact_download_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            directory = make_entry(root)
            metadata = json.loads((directory / 'metadata.json').read_text())
            content = (directory / 'workflow.json').read_bytes()
            receipt = {'entries': [{'catalog_key': metadata['catalog_key'], 'workflow_id': 123}]}
            headers = Message()
            headers['Content-Type'] = 'application/json'
            headers['Content-Disposition'] = 'attachment; filename="' + metadata['json_filename'] + '"'
            def request(endpoint):
                if endpoint == 'api.php?page=1':
                    return headers, json.dumps({'format': 'flowgraph-workflow-catalog', 'schema_version': 1,
                                                'pages': 1, 'page': 1, 'total': 1,
                                                'entries': [{'id': '123'}]}).encode()
                if endpoint == 'api.php?id=123':
                    return headers, json.dumps({'entry': {**metadata, 'id': '123', 'workflow': json.loads(content)}}).encode()
                self.assertEqual(endpoint, 'download.php?id=123')
                return headers, content
            with redirect_stdout(io.StringIO()):
                verify(root, receipt, request)
            def corrupt(endpoint):
                header, raw = request(endpoint)
                return header, raw + b' ' if endpoint.startswith('download') else raw
            with self.assertRaises(InvalidCatalog):
                verify(root, receipt, corrupt)
            with self.assertRaises(InvalidCatalog):
                verify(root, {'entries': []}, request)


if __name__ == '__main__':
    unittest.main()