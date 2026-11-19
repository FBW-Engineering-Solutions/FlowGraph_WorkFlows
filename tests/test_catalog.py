import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from validate_catalog import (  # noqa: E402
    InvalidCatalog, MAX_BYTES, read_json, validate_catalog, validate_metadata,
    validate_workflow,
)
from import_public_catalog import BASE, fetch, import_catalog, slugify  # noqa: E402


def workflow():
    return {
        'format': 'flowgraph-workflow', 'version': 3,
        'nodes': [
            {'id': 'a', 'definition_id': 'set-string', 'parameters': {'value': 'test'}},
            {'id': 'b', 'definition_id': 'show-value', 'parameters': {}},
        ],
        'edges': [{'source_node': 'a', 'source_port': 'value',
                   'target_node': 'b', 'target_port': 'value'}],
        'inputs': [], 'outputs': [{'name': 'result', 'node_id': 'a', 'node_port': 'value'}],
    }


def metadata():
    return {'schema_version': 1, 'catalog_key': 'example/1.0.0',
            'workflow_name': 'Example', 'author': 'Example Author', 'company': '',
            'version': '1.0.0', 'description': 'Example description.',
            'uploaded_at': '2026-11-20T12:00:00Z', 'json_filename': 'example.json',
            'source': None}


def make_entry(root, slug='example', source=None):
    directory = root / 'workflows' / slug / '1.0.0'
    directory.mkdir(parents=True)
    data = metadata()
    data['catalog_key'] = f'{slug}/1.0.0'
    data['source'] = source
    (directory / 'metadata.json').write_text(json.dumps(data))
    (directory / 'workflow.json').write_text(json.dumps(workflow()))
    return directory


class WorkflowTests(unittest.TestCase):
    def test_valid_and_legacy_envelopes(self):
        for version in (1, 2, 3):
            data = workflow()
            data['version'] = version
            validate_workflow(data)

    def test_invalid_envelopes(self):
        for field, value in [('version', True), ('version', 4), ('format', 'pickle'),
                             ('nodes', {}), ('edges', None)]:
            with self.subTest(field=field, value=value):
                data = workflow()
                data[field] = value
                with self.assertRaises(InvalidCatalog):
                    validate_workflow(data)

    def test_duplicate_node(self):
        data = workflow()
        data['nodes'].append(copy.deepcopy(data['nodes'][0]))
        with self.assertRaisesRegex(InvalidCatalog, 'duplicate node'):
            validate_workflow(data)

    def test_dangling_edge(self):
        for side in ('source', 'target'):
            data = workflow()
            data['edges'][0][f'{side}_node'] = 'missing'
            with self.assertRaisesRegex(InvalidCatalog, 'dangling'):
                validate_workflow(data)

    def test_duplicate_target(self):
        data = workflow()
        data['edges'].append(copy.deepcopy(data['edges'][0]))
        with self.assertRaisesRegex(InvalidCatalog, 'same input'):
            validate_workflow(data)

    def test_cycles(self):
        data = workflow()
        data['edges'].append({'source_node': 'b', 'source_port': 'out',
                              'target_node': 'a', 'target_port': 'in'})
        with self.assertRaisesRegex(InvalidCatalog, 'cycle'):
            validate_workflow(data)

    def test_boundaries(self):
        data = workflow()
        data['outputs'][0]['node_id'] = 'missing'
        with self.assertRaisesRegex(InvalidCatalog, 'dangling'):
            validate_workflow(data)
        data = workflow()
        data['outputs'].append(copy.deepcopy(data['outputs'][0]))
        with self.assertRaisesRegex(InvalidCatalog, 'duplicate outputs'):
            validate_workflow(data)

    def test_positions(self):
        for value in (True, float('inf'), float('nan'), '10', None):
            data = workflow()
            data['nodes'][0]['position'] = {'x': value, 'y': 0}
            with self.assertRaises(InvalidCatalog):
                validate_workflow(data)

    def test_nested_workflows(self):
        data = workflow()
        node = data['nodes'][0]
        node['definition_id'] = 'batch-workflow'
        node['subworkflows'] = {'default': workflow()}
        validate_workflow(data)
        node['subworkflows']['default']['edges'][0]['target_node'] = 'missing'
        with self.assertRaisesRegex(InvalidCatalog, 'dangling'):
            validate_workflow(data)

    def test_conditional_branches(self):
        data = workflow()
        node = data['nodes'][0]
        node['definition_id'] = 'conditional-workflow'
        node['subworkflows'] = {'false': workflow(), 'true': workflow()}
        validate_workflow(data)
        del node['subworkflows']['true']
        with self.assertRaisesRegex(InvalidCatalog, 'true and false'):
            validate_workflow(data)

    def test_legacy_child(self):
        data = workflow()
        data['version'] = 2
        data['nodes'][0]['subworkflow'] = workflow()
        validate_workflow(data)
        data['version'] = 3
        with self.assertRaisesRegex(InvalidCatalog, 'requires subworkflows'):
            validate_workflow(data)

    def test_code_representation_is_not_executed(self):
        data = workflow()
        node = data['nodes'][0]
        node['definition_id'] = 'user-function'
        for code in ('raise RuntimeError("must not run")', ['raise RuntimeError("must not run")']):
            node['parameters']['code'] = code
            validate_workflow(data)
        for code in ([], ['embedded\nnewline'], [42], None):
            node['parameters']['code'] = code
            with self.assertRaises(InvalidCatalog):
                validate_workflow(data)

    def test_nested_depth_limit(self):
        data = workflow()
        cursor = data
        for _ in range(34):
            child = workflow()
            cursor['nodes'][0]['subworkflows'] = {'default': child}
            cursor = child
        with self.assertRaisesRegex(InvalidCatalog, 'depth'):
            validate_workflow(data)


class MetadataTests(unittest.TestCase):
    def test_valid(self):
        validate_metadata(metadata(), 'example', '1.0.0')

    def test_invalid_fields(self):
        for field, value in [('schema_version', True), ('catalog_key', 'other/1.0.0'),
                             ('version', '2.0.0'), ('workflow_name', ''), ('author', 'a\0b'),
                             ('description', 'x' * 10001), ('json_filename', '../private.json'),
                             ('uploaded_at', '2026-02-30T00:00:00Z'),
                             ('uploaded_at', '2026-11-20T00:00:00+00:00'), ('source', {})]:
            with self.subTest(field=field, value=str(value)[:40]):
                data = metadata()
                data[field] = value
                with self.assertRaises(InvalidCatalog):
                    validate_metadata(data, 'example', '1.0.0')

    def test_unknown_fields(self):
        data = metadata()
        data['password'] = 'not allowed'
        with self.assertRaises(InvalidCatalog):
            validate_metadata(data, 'example', '1.0.0')


class FilesystemTests(unittest.TestCase):
    def test_repository_catalog(self):
        self.assertGreater(validate_catalog(ROOT), 0)

    def test_valid_tree(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            make_entry(root)
            self.assertEqual(validate_catalog(root), 1)

    def test_empty_catalog(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'workflows').mkdir()
            with self.assertRaises(InvalidCatalog):
                validate_catalog(root)

    def test_missing_and_unexpected_files(self):
        for name in ('metadata.json', 'workflow.json'):
            with tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                entry = make_entry(root)
                (entry / name).unlink()
                with self.assertRaises(InvalidCatalog):
                    validate_catalog(root)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            entry = make_entry(root)
            (entry / 'secret.env').write_text('private')
            with self.assertRaises(InvalidCatalog):
                validate_catalog(root)

    def test_symlink(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            entry = make_entry(root)
            (root / 'outside.json').write_text(json.dumps(workflow()))
            (entry / 'workflow.json').unlink()
            (entry / 'workflow.json').symlink_to(root / 'outside.json')
            with self.assertRaisesRegex(InvalidCatalog, 'symlink'):
                validate_catalog(root)

    def test_duplicate_source_id(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = {'catalog_url': 'https://flowgraph-catalog.fbw-es.com/workflows/', 'id': '1'}
            make_entry(root, 'first', source)
            make_entry(root, 'second', source)
            with self.assertRaisesRegex(InvalidCatalog, 'duplicate source'):
                validate_catalog(root)

    def test_bad_json(self):
        for content in ('{"x": 1, "x": 2}', '{"x": NaN}', '{"x": Infinity}', '{broken'):
            with tempfile.TemporaryDirectory() as temporary:
                path = Path(temporary) / 'test.json'
                path.write_text(content)
                with self.assertRaises(InvalidCatalog):
                    read_json(path)

    def test_size_limit(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'test.json'
            path.write_bytes(b' ' * (MAX_BYTES + 1))
            with self.assertRaisesRegex(InvalidCatalog, '2 MiB'):
                read_json(path)


class ImportTests(unittest.TestCase):
    def test_slug(self):
        self.assertEqual(slugify('# Scalar Inputs: Démo'), 'scalar-inputs-demo')

    def test_refuses_overwrite_before_network(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            make_entry(root)
            with patch('import_public_catalog.urlopen') as network:
                with self.assertRaisesRegex(InvalidCatalog, 'refusing to overwrite'):
                    import_catalog(root)
                network.assert_not_called()

    def test_mock_import_preserves_bytes(self):
        data = metadata()
        entry = {key: value for key, value in data.items()
                 if key not in ('schema_version', 'catalog_key', 'source')}
        entry.update(id='1', revision=123, workflow=workflow())
        raw = json.dumps(workflow(), indent=4).encode() + b'\n'
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with patch('import_public_catalog.listing', return_value=([entry], {'1': 123})), \
                 patch('import_public_catalog.api', return_value={'entry': entry}), \
                 patch('import_public_catalog.fetch', return_value=raw):
                self.assertEqual(import_catalog(root), 1)
            self.assertEqual((root / 'workflows/example/1.0.0/workflow.json').read_bytes(), raw)
            manifest = json.loads((root / 'migration/initial-import.json').read_text())
            self.assertEqual(manifest['entries'][0]['workflow_sha256'], hashlib.sha256(raw).hexdigest())

    def test_changing_catalog_leaves_no_partial_tree(self):
        data = metadata()
        entry = {key: value for key, value in data.items()
                 if key not in ('schema_version', 'catalog_key', 'source')}
        entry.update(id='1', revision=123, workflow=workflow())
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with patch('import_public_catalog.listing',
                       side_effect=[([entry], {'1': 123}), ([entry], {'1': 456})]), \
                 patch('import_public_catalog.api', return_value={'entry': entry}), \
                 patch('import_public_catalog.fetch', return_value=json.dumps(workflow()).encode()):
                with self.assertRaisesRegex(InvalidCatalog, 'changed during import'):
                    import_catalog(root)
            self.assertFalse((root / 'workflows').exists())
            self.assertFalse(list(root.glob('.catalog-import-*')))

    def test_rate_limit_respects_retry_after(self):
        error = HTTPError(BASE + 'api.php', 429, 'rate limit', {'Retry-After': '120'}, None)
        with patch('import_public_catalog.urlopen', side_effect=[error, RuntimeError('stop')]), \
             patch('import_public_catalog.time.sleep') as sleep, \
             patch('builtins.print'):
            with self.assertRaisesRegex(RuntimeError, 'stop'):
                fetch('api.php')
            sleep.assert_any_call(120)


if __name__ == '__main__':
    unittest.main()