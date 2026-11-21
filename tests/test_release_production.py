from contextlib import redirect_stdout
import io
import json
import shutil
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import subprocess

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from release_production import check_source, deploy, approve, receipt, load_settings
from test_catalog import make_entry
from validate_catalog import InvalidCatalog


class ProductionReleaseTests(unittest.TestCase):
    def test_source_requires_clean_merged_master(self):
        for answers in [['?? secret'], ['', 'topic'], ['', 'master', 'a' * 40, 'b' * 40]]:
            with self.subTest(answers=answers), patch('release_production.git', side_effect=answers), \
                    patch('release_production.subprocess.run') as run:
                with self.assertRaises(InvalidCatalog):
                    check_source(Path('/checkout'))
                if len(answers) < 3:
                    run.assert_not_called()

    def test_saved_settings_reject_passwords_and_invalid_timeout(self):
        with tempfile.TemporaryDirectory() as temporary, patch('release_production.validate_connection'):
            path = Path(temporary) / 'settings.json'
            valid = {'username': 'user', 'known_hosts': '/key', 'wait_seconds': 90000}
            path.write_text(json.dumps(valid))
            self.assertEqual(load_settings(path), valid)
            for invalid in [{**valid, 'password': 'never-save'}, {**valid, 'wait_seconds': 0}]:
                path.write_text(json.dumps(invalid))
                with self.assertRaises(InvalidCatalog):
                    load_settings(path)

    def test_build_approval_wait_and_verify_order(self):
        for dry_run in [True, False]:
            with self.subTest(dry_run=dry_run), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                make_entry(root)
                current = {'release_id': 'b' * 64, 'source_commit': 'c' * 40}
                bundle = root / '.local/releases' / ('a' * 40 + '-' + 'b' * 64) / 'bundle'
                def next_receipt(*args):
                    return {'release_id': (bundle / 'READY').read_text().strip(), 'source_commit': 'a' * 40}
                with patch('release_production.receipt', side_effect=[current, next_receipt] if dry_run else None) as read, \
                        patch('release_production.git', return_value='changed'), \
                        patch('release_production.subprocess.run', return_value=subprocess.CompletedProcess([], 0)), \
                        patch('release_production.publish') as upload, \
                        patch('release_production.approve') as approval, \
                        patch('release_production.verify') as verify, redirect_stdout(io.StringIO()):
                    read.side_effect = lambda *args: current if not bundle.exists() else next_receipt()
                    deploy(root, {'wait_seconds': 60}, None, root, 'a' * 40, dry_run)
                    self.assertEqual(upload.called, not dry_run)
                    self.assertEqual(approval.called, not dry_run)
                    self.assertEqual(verify.called, not dry_run)
                payload = json.loads((bundle / 'catalog.json').read_text())
                self.assertEqual(payload['source_commit'], 'a' * 40)
                self.assertEqual(payload['previous_release'], 'b' * 64)

    def test_tool_only_merge_does_not_upload_or_approve(self):
        with patch('release_production.receipt', return_value={'source_commit': 'a' * 40}), \
                patch('release_production.subprocess.run', return_value=subprocess.CompletedProcess([], 0)), \
                patch('release_production.git', return_value=''), patch('release_production.publish') as upload, \
                patch('release_production.approve') as approval, patch('release_production.verify') as verify:
            deploy(Path('/checkout'), {}, None, None, 'b' * 40)
            upload.assert_not_called()
            approval.assert_not_called()
            verify.assert_called_once()

    def test_approval_is_roundtrip_verified_before_publication(self):
        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary)
            calls = []
            def session(commands):
                calls.append(commands)
                if len(calls) == 1:
                    shutil.copyfile(work / 'APPROVED', work / 'approval-roundtrip')
            approve('a' * 64, session, work)
            self.assertEqual(len(calls), 2)
            self.assertEqual(calls[-1][-1], 'rename APPROVED.uploading APPROVED')
            (work / 'approval-roundtrip').write_text('corrupt')
            with self.assertRaises(InvalidCatalog):
                approve('b' * 64, lambda commands: None, work)

    def test_missing_receipt_stops_without_guessing_parent(self):
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaises(OSError):
                receipt(lambda commands: None, Path(temporary))

    def test_timeout_preserves_explicit_warning_that_approval_is_still_live(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            make_entry(root)
            current = {'release_id': 'b' * 64, 'source_commit': 'c' * 40}
            with patch('release_production.receipt', return_value=current), \
                    patch('release_production.git', return_value='changed'), \
                    patch('release_production.subprocess.run', return_value=subprocess.CompletedProcess([], 0)), \
                    patch('release_production.publish'), patch('release_production.approve'), \
                    patch('release_production.time.monotonic', side_effect=[0, 61]), \
                    patch('release_production.verify') as verify:
                with self.assertRaisesRegex(InvalidCatalog, 'MAY import later'):
                    deploy(root, {'wait_seconds': 60}, None, root, 'a' * 40)
                verify.assert_not_called()

    def test_transport_rejects_unverified_host_before_connecting(self):
        from production_transport import validate_connection
        with tempfile.TemporaryDirectory() as temporary:
            key = Path(temporary) / 'known_hosts'
            key.write_text('ftp.cluster129.hosting.ovh.net ssh-ed25519 YWJj\n')
            with self.assertRaises(InvalidCatalog):
                validate_connection('user', key)


if __name__ == '__main__':
    unittest.main()