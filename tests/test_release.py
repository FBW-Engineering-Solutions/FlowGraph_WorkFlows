import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from build_release import build_release
from validate_catalog import InvalidCatalog
from test_catalog import make_entry


class ReleaseTests(unittest.TestCase):
    def test_deterministic_bundle_preserves_download_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            entry = make_entry(root)
            first = root / 'first'
            second = root / 'second'
            identity = build_release(root, first, None, 'a' * 40)
            self.assertEqual(identity, build_release(root, second, None, 'a' * 40))
            raw = (first / 'catalog.json').read_bytes()
            self.assertEqual(raw, (second / 'catalog.json').read_bytes())
            self.assertEqual(identity, hashlib.sha256(raw).hexdigest())
            self.assertEqual((first / 'READY').read_text(), identity + '\n')
            payload = json.loads(raw)
            self.assertEqual(payload['entries'][0]['workflow_json'].encode(),
                             (entry / 'workflow.json').read_bytes())

    def test_parent_changes_release_identity(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            make_entry(root)
            first = build_release(root, root / 'first', None, 'a' * 40)
            second = build_release(root, root / 'second', first, 'a' * 40)
            self.assertNotEqual(first, second)
            self.assertEqual(json.loads((root / 'second/catalog.json').read_text())['previous_release'], first)

    def test_refuses_overwrite_and_invalid_commit_or_parent(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            make_entry(root)
            for previous, commit in [('bad', 'a' * 40), (None, 'HEAD')]:
                with self.assertRaises(InvalidCatalog):
                    build_release(root, root / 'output', previous, commit)
            build_release(root, root / 'output', None, 'a' * 40)
            with self.assertRaises(InvalidCatalog):
                build_release(root, root / 'output', None, 'a' * 40)

    def test_malformed_workflow_produces_no_partial_bundle(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            entry = make_entry(root)
            (entry / 'workflow.json').write_text('{invalid')
            with self.assertRaises(InvalidCatalog):
                build_release(root, root / 'output', None, 'a' * 40)
            self.assertFalse((root / 'output').exists())


if __name__ == '__main__':
    unittest.main()