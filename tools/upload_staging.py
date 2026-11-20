#!/usr/bin/env python3
"""Publish a release to the fixed staging inbox using OpenSSH SFTP only."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile

from validate_catalog import InvalidCatalog, require


HOST = 'ftp.cluster129.hosting.ovh.net'
INBOX = '/home/fbwescj/catalog-staging/storage/app/private/catalog-inbox'


def quote(value):
    require(isinstance(value, str) and value and not any(c in value for c in '\r\n\x00'),
            'unsafe SFTP argument')
    return '"' + value.replace('\\', '\\\\').replace('"', '\\"') + '"'


def validate_bundle(bundle, previous):
    require(re.fullmatch(r'[a-f0-9]{64}', previous), 'invalid previous release')
    require(bundle.is_dir() and not bundle.is_symlink(), 'unsafe bundle directory')
    for name, limit in [('catalog.json', 16777216), ('READY', 65)]:
        path = bundle / name
        require(path.is_file() and not path.is_symlink() and path.stat().st_size <= limit,
                'missing or unsafe bundle file')
    raw = (bundle / 'catalog.json').read_bytes()
    identity = hashlib.sha256(raw).hexdigest()
    require((bundle / 'READY').read_bytes() == (identity + '\n').encode(), 'bundle checksum mismatch')
    payload = json.loads(raw)
    require(payload.get('format') == 'flowgraph-catalog-release'
            and payload.get('schema_version') == 1 and payload.get('previous_release') == previous,
            'bundle parent or schema mismatch')
    return identity


def publish(bundle, previous, session, work):
    """session executes a fail-fast batch; any failure leaves the upload lock for recovery."""
    identity = validate_bundle(bundle, previous)
    # Missing inbox/pending must be created and checked manually during first setup.
    # mkdir fails if another uploader holds this lock or an interrupted upload needs repair.
    session(['cd ' + quote(INBOX), 'mkdir upload.lock', 'cd pending',
             'get READY ' + quote(str(work / 'remote-READY'))])
    require((work / 'remote-READY').read_bytes() in ((previous + '\n').encode(), (identity + '\n').encode()),
            'remote pending marker is neither parent nor this release; inspect upload.lock')
    session(['cd ' + quote(INBOX + '/pending'), '-rm catalog.json.uploading',
             'put ' + quote(str(bundle / 'catalog.json')) + ' catalog.json.uploading',
             'get catalog.json.uploading ' + quote(str(work / 'roundtrip.json'))])
    require(hashlib.sha256((work / 'roundtrip.json').read_bytes()).hexdigest() == identity,
            'remote payload round-trip checksum mismatch; inspect upload.lock')
    # Stage the marker before removing the old one. Cron can only read an old valid
    # pair, a missing marker, or the newly verified pair. Never upload over READY.
    session(['cd ' + quote(INBOX + '/pending'), '-rm READY.uploading',
             'put ' + quote(str(bundle / 'READY')) + ' READY.uploading',
             'get READY.uploading ' + quote(str(work / 'roundtrip-READY'))])
    require((work / 'roundtrip-READY').read_bytes() == (identity + '\n').encode(),
            'remote marker round-trip mismatch; inspect upload.lock')
    session(['cd ' + quote(INBOX + '/pending'),
             'rm READY', 'rm catalog.json', 'rename catalog.json.uploading catalog.json',
             'rename READY.uploading READY', 'cd ..', 'rmdir upload.lock'])
    return identity


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle', type=Path, required=True)
    parser.add_argument('--previous-release', required=True)
    args = parser.parse_args()
    try:
        require(os.environ.get('GITHUB_REF') == 'refs/heads/master', 'deployment requires master')
        username = os.environ.get('STAGING_SFTP_USERNAME', '')
        password = os.environ.get('STAGING_SFTP_PASSWORD', '')
        hostkeys = os.environ.get('STAGING_SFTP_KNOWN_HOSTS', '')
        require(bool(re.fullmatch(r'[A-Za-z0-9_-]+', username)) and bool(password), 'missing SFTP credentials')
        require(bool(hostkeys.strip()) and all(
            line.split()[0] == HOST and len(line.split()) >= 3
            for line in hostkeys.splitlines() if line.strip()), 'invalid pinned host keys')
        with tempfile.TemporaryDirectory(prefix='catalog-sftp-') as temporary:
            work = Path(temporary)
            known = work / 'known_hosts'
            known.write_text(hostkeys + '\n')
            known.chmod(0o600)
            askpass = work / 'askpass'
            askpass.write_text('#!/bin/sh\nprintf "%s\\n" "$STAGING_SFTP_PASSWORD"\n')
            askpass.chmod(0o700)
            environment = {**os.environ, 'SSH_ASKPASS': str(askpass),
                           'SSH_ASKPASS_REQUIRE': 'force', 'DISPLAY': ':0'}

            def session(commands):
                batch = work / 'batch'
                batch.write_text('\n'.join(commands) + '\n')
                result = subprocess.run([
                    'sftp', '-P', '22', '-oBatchMode=no', '-oStrictHostKeyChecking=yes',
                    '-oUserKnownHostsFile=' + str(known), '-oGlobalKnownHostsFile=/dev/null',
                    '-oPreferredAuthentications=password', '-oPubkeyAuthentication=no',
                    '-oNumberOfPasswordPrompts=1', '-oConnectTimeout=30',
                    '-b', str(batch), username + '@' + HOST,
                ], env=environment, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE, timeout=180)
                require(result.returncode == 0, 'SFTP failed; inspect credentials, pin, permissions and upload.lock privately')

            identity = publish(args.bundle.resolve(), args.previous_release, session, work)
        print('Uploaded staging bundle ' + identity + '. Database import is NOT yet confirmed; inspect cron logs.')
        summary = os.environ.get('GITHUB_STEP_SUMMARY')
        if summary:
            with open(summary, 'a') as stream:
                stream.write(f'## Staging bundle uploaded\n\nRelease: `{identity}`\n\n'
                             f'Parent: `{args.previous_release}`\n\n'
                             'Upload only. Confirm the scheduled import and verify downloads before the next deployment.\n')
    except (InvalidCatalog, OSError, ValueError, subprocess.SubprocessError):
        parser.exit(1, 'Staging upload stopped. Do not delete release state. Inspect the inbox and upload.lock before retrying; no database import was confirmed.\n')


if __name__ == '__main__':
    main()