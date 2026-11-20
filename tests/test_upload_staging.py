import hashlib
import json
import os
from pathlib import Path
import shlex
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from upload_staging import INBOX, main, publish, quote, validate_bundle
from validate_catalog import InvalidCatalog


class UploadTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.bundle = self.root / 'bundle'
        self.bundle.mkdir()
        self.work = self.root / 'work'
        self.work.mkdir()
        self.parent = 'a' * 64
        self.raw = json.dumps({'format': 'flowgraph-catalog-release', 'schema_version': 1,
                               'previous_release': self.parent, 'entries': []}).encode()
        self.identity = hashlib.sha256(self.raw).hexdigest()
        (self.bundle / 'catalog.json').write_bytes(self.raw)
        (self.bundle / 'READY').write_text(self.identity + '\n')
        self.files = {'READY': (self.parent + '\n').encode(), 'catalog.json': b'old'}
        self.lock = False
        self.commands = []
        self.fail_on = None
        self.corrupt_roundtrip = False

    def session(self, commands):
        for command in commands:
            self.commands.append(command)
            if command == self.fail_on:
                raise InvalidCatalog('simulated connection failure')
            parts = shlex.split(command)
            operation, *args = parts
            if operation == 'mkdir':
                if self.lock:
                    raise InvalidCatalog('upload locked')
                self.lock = True
            elif operation == 'rmdir':
                self.lock = False
            elif operation == 'get':
                content = self.files[args[0]]
                if self.corrupt_roundtrip and args[0] == 'catalog.json.uploading':
                    content += b'corrupt'
                Path(args[1]).write_bytes(content)
            elif operation == 'put':
                self.files[args[1]] = Path(args[0]).read_bytes()
            elif operation in ('rm', '-rm'):
                if operation == 'rm' and args[0] not in self.files:
                    raise InvalidCatalog('missing remote file')
                self.files.pop(args[0], None)
            elif operation == 'rename':
                self.files[args[1]] = self.files.pop(args[0])

    def test_success_marker_is_last_and_roundtrip_precedes_replacement(self):
        self.assertEqual(publish(self.bundle, self.parent, self.session, self.work), self.identity)
        self.assertFalse(self.lock)
        self.assertEqual(self.files, {'READY': (self.identity + '\n').encode(), 'catalog.json': self.raw})
        commands = '\n'.join(self.commands)
        self.assertLess(commands.index('get catalog.json.uploading'), commands.index('rm READY\n'))
        self.assertLess(commands.index('rename catalog.json.uploading'), commands.index('rename READY.uploading'))
        self.assertTrue(self.commands[0].startswith('cd "' + INBOX))

    def test_stale_parent_keeps_remote_bundle_and_lock(self):
        self.files['READY'] = ('b' * 64 + '\n').encode()
        before = dict(self.files)
        with self.assertRaisesRegex(InvalidCatalog, 'remote pending marker'):
            publish(self.bundle, self.parent, self.session, self.work)
        self.assertEqual(self.files, before)
        self.assertTrue(self.lock)

    def test_corrupt_roundtrip_keeps_old_marker(self):
        self.corrupt_roundtrip = True
        with self.assertRaisesRegex(InvalidCatalog, 'round-trip'):
            publish(self.bundle, self.parent, self.session, self.work)
        self.assertEqual(self.files['READY'], (self.parent + '\n').encode())
        self.assertTrue(self.lock)

    def test_existing_lock_prevents_any_transfer(self):
        self.lock = True
        with self.assertRaisesRegex(InvalidCatalog, 'locked'):
            publish(self.bundle, self.parent, self.session, self.work)
        self.assertFalse(any(c.startswith('put ') for c in self.commands))

    def test_disconnect_after_marker_removed_never_publishes_new_ready(self):
        self.fail_on = 'rename catalog.json.uploading catalog.json'
        with self.assertRaises(InvalidCatalog):
            publish(self.bundle, self.parent, self.session, self.work)
        self.assertNotIn('READY', self.files)
        self.assertTrue(self.lock)

    def test_retry_of_same_bundle_is_allowed_after_explicit_lock_recovery(self):
        self.files['READY'] = (self.identity + '\n').encode()
        self.assertEqual(publish(self.bundle, self.parent, self.session, self.work), self.identity)

    def test_invalid_local_bundle_makes_no_connection(self):
        (self.bundle / 'catalog.json').write_text('tampered')
        with self.assertRaises(InvalidCatalog):
            publish(self.bundle, self.parent, self.session, self.work)
        self.assertEqual(self.commands, [])

    def test_wrong_parent_and_symlinks_rejected(self):
        with self.assertRaises(InvalidCatalog):
            validate_bundle(self.bundle, 'b' * 64)
        (self.bundle / 'READY').unlink()
        (self.bundle / 'READY').symlink_to(self.bundle / 'catalog.json')
        with self.assertRaises(InvalidCatalog):
            validate_bundle(self.bundle, self.parent)

    def test_argument_quoting_rejects_command_injection(self):
        for value in ('x\nrm READY', 'x\rput secret', 'x\0'):
            with self.assertRaises(InvalidCatalog):
                quote(value)
        self.assertEqual(quote('/tmp/file with spaces'), '"/tmp/file with spaces"')

    def test_workflow_has_manual_trigger_and_scoped_credentials(self):
        workflow = (Path(__file__).resolve().parents[1] / '.github/workflows/deploy-staging.yml').read_text()
        self.assertIn('workflow_dispatch:', workflow)
        self.assertNotIn('pull_request:', workflow)
        self.assertNotIn('\n  push:', workflow)
        self.assertIn("if: github.ref == 'refs/heads/master'", workflow)
        self.assertIn('environment: staging', workflow)
        self.assertIn('cancel-in-progress: false', workflow)
        self.assertNotIn('write-all', workflow)
        self.assertNotIn('StrictHostKeyChecking=no', workflow)

    def test_transport_pins_host_and_does_not_put_password_in_arguments(self):
        from types import SimpleNamespace
        captured = []

        def execute(arguments, **kwargs):
            captured.append((arguments, kwargs))
            self.assertNotIn('test-password', ' '.join(arguments))
            self.assertIn('-oStrictHostKeyChecking=yes', arguments)
            self.assertIn('-oBatchMode=no', arguments)
            self.assertEqual(kwargs['env']['SSH_ASKPASS_REQUIRE'], 'force')
            self.assertEqual(kwargs['env']['STAGING_SFTP_PASSWORD'], 'test-password')
            self.session(Path(arguments[arguments.index('-b') + 1]).read_text().splitlines())
            return SimpleNamespace(returncode=0)

        environment = {'GITHUB_REF': 'refs/heads/master', 'STAGING_SFTP_USERNAME': 'staging-only',
                       'STAGING_SFTP_PASSWORD': 'test-password',
                       'STAGING_SFTP_KNOWN_HOSTS': 'ftp.cluster129.hosting.ovh.net ssh-ed25519 example-test-key'}
        with patch.dict(os.environ, environment, clear=True), patch.object(sys, 'argv', [
                'upload_staging.py', '--bundle', str(self.bundle), '--previous-release', self.parent]), \
                patch('upload_staging.subprocess.run', side_effect=execute):
            main()
        self.assertEqual(len(captured), 4)
        self.assertFalse(self.lock)

    def test_non_master_cannot_connect(self):
        with patch.dict(os.environ, {'GITHUB_REF': 'refs/heads/feature'}, clear=True), \
                patch.object(sys, 'argv', ['upload_staging.py', '--bundle', str(self.bundle),
                                          '--previous-release', self.parent]), \
                patch('upload_staging.subprocess.run') as execute:
            with self.assertRaises(SystemExit):
                main()
            execute.assert_not_called()


if __name__ == '__main__':
    unittest.main()