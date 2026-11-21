import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from test_catalog import make_entry
from preflight_production import BASE, listing, reconcile
from validate_catalog import InvalidCatalog


class PreflightTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        directory = make_entry(self.root, source={'catalog_url': BASE, 'id': '1'})
        self.metadata = json.loads((directory / 'metadata.json').read_text())
        self.content = (directory / 'workflow.json').read_bytes()
        (self.root / 'migration').mkdir()
        (self.root / 'migration/initial-import.json').write_text(json.dumps({'entries': [
            {'source_id': '1', 'workflow_sha256': hashlib.sha256(self.content).hexdigest()}]}))
        self.summaries = [{'id': '1', 'revision': 1}]
        self.details = dict(self.metadata, id='1', revision=1, workflow=json.loads(self.content))

    def report(self):
        return reconcile(self.root, lambda: (self.summaries, {item['id']: item['revision'] for item in self.summaries}),
                         lambda path: {'entry': self.details}, lambda path: self.content)

    def test_match(self):
        self.assertTrue(self.report()['ready_for_exact_adoption'])

    def test_metadata_difference_never_echoes_content(self):
        self.details['description'] = 'new production text'
        report = self.report()
        self.assertFalse(report['ready_for_exact_adoption'])
        self.assertEqual(report['entries'][0]['different_metadata_fields'], ['description'])
        self.assertNotIn('new production text', json.dumps(report))

    def test_exact_download_difference(self):
        self.content += b'\n'
        row = self.report()['entries'][0]
        self.assertTrue(row['different_download_bytes'])
        self.assertTrue(row['production_bytes_changed_since_initial_import'])

    def test_numeric_identity_conflict_is_not_guessed_from_name(self):
        self.details['workflow_name'] = 'Unrelated replacement'
        self.assertEqual(self.report()['entries'][0]['status'], 'conflict')

    def test_production_only_and_missing_git_ids(self):
        self.summaries = [{'id': '2', 'revision': 1}]
        self.details['id'] = '2'
        report = self.report()
        self.assertEqual(report['entries'][0]['status'], 'production-only')
        self.assertEqual(report['git_source_ids_missing_in_production'], ['1'])

    def test_new_git_entry_is_reported(self):
        make_entry(self.root, 'new')
        self.assertEqual(self.report()['new_git_entries'], ['new/1.0.0'])

    def test_api_download_inconsistency_fails(self):
        self.details['workflow'] = {}
        with self.assertRaises(InvalidCatalog):
            self.report()

    def test_changed_final_listing_fails(self):
        with self.assertRaises(InvalidCatalog):
            reconcile(self.root, list_catalog=iter([(self.summaries, {'1': 1}), (self.summaries, {'1': 2})]).__next__,
                      get_api=lambda path: {'entry': self.details}, get_bytes=lambda path: self.content)

    def test_pagination_and_duplicates(self):
        first = {'total': 13, 'pages': 2, 'page_size': 12, 'page': 1,
                 'entries': [{'id': str(i), 'revision': 1} for i in range(1, 13)]}
        second = dict(first, page=2, entries=[{'id': '13', 'revision': 1}])
        with patch('preflight_production.api', side_effect=[first, second]):
            self.assertEqual(len(listing()[0]), 13)
        for change in [{'page': 1}, {'total': 14}, {'entries': [{'id': '1', 'revision': 1}]}, {'entries': []}]:
            with patch('preflight_production.api', side_effect=[first, dict(second, **change)]):
                with self.assertRaises(InvalidCatalog):
                    listing()

    def test_malformed_and_network_responses_fail(self):
        for value in [None, [], b'not-json']:
            with self.subTest(value=value), self.assertRaises((TypeError, KeyError)):
                reconcile(self.root, lambda: (self.summaries, {'1': 1}), lambda path: value, lambda path: self.content)
        with patch('preflight_production.api', side_effect=OSError('network failed')):
            with self.assertRaises(OSError):
                listing()


if __name__ == '__main__':
    unittest.main()