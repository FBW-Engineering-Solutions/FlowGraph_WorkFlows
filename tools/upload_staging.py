#!/usr/bin/env python3
"""Publish a release to the fixed staging inbox using OpenSSH SFTP only."""

import argparse
import getpass
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
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
    parser.add_argument('--username', required=True, help='Hosting SFTP username; never a database username')
    parser.add_argument('--known-hosts', type=Path, required=True, help='Local independently verified OpenSSH known_hosts file')
    parser.add_argument('--dry-run', action='store_true', help='Validate and display destination without connecting')
    args = parser.parse_args()
    try:
        require(not os.environ.get('CI') and not os.environ.get('GITHUB_ACTIONS'), 'local deployment only; CI is refused')
        identity = validate_bundle(args.bundle, args.previous_release)
        username = args.username
        require(bool(re.fullmatch(r'[A-Za-z0-9_-]+', username)), 'invalid SFTP username')
        require(args.known_hosts.is_file() and not args.known_hosts.is_symlink()
                and args.known_hosts.stat().st_size <= 1048576, 'missing or unsafe known_hosts file')
        hostkeys = args.known_hosts.read_text()
        require(any(len(line.split()) >= 3 and line.split()[0] == HOST
                    for line in hostkeys.splitlines() if line.strip() and not line.startswith('#')),
                'known_hosts must contain the verified staging host key')
        print(f'STAGING ONLY: {HOST}:22{INBOX}/pending\nRelease: {identity}\nParent: {args.previous_release}')
        if args.dry_run:
            print('Dry run: no connection or password prompt. Hosting credentials remain local.')
            return
        require(sys.stdin.isatty(), 'run from an interactive local terminal')
        confirmation = 'catalog-staging:' + identity
        require(input('Confirm backup and parent import; type '+confirmation+': ') == confirmation,
                'staging confirmation did not match')
        password = getpass.getpass('Hosting SFTP password (not saved): ')
        require(bool(password) and '\n' not in password and '\r' not in password, 'invalid password')
        with tempfile.TemporaryDirectory(prefix='catalog-sftp-') as temporary:
            work = Path(temporary)
            known = work / 'known_hosts'
            known.write_text(hostkeys + '\n')
            known.chmod(0o600)
            askpass = work / 'askpass'
            askpass.write_text('#!/bin/sh\nprintf "%s\\n" "$STAGING_SFTP_PASSWORD"\n')
            askpass.chmod(0o700)
            environment = {**os.environ, 'SSH_ASKPASS': str(askpass),
                           'SSH_ASKPASS_REQUIRE': 'force', 'DISPLAY': ':0',
                           'STAGING_SFTP_PASSWORD': password}

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

            identity = publish(args.bundle, args.previous_release, session, work)
        print('Uploaded staging bundle ' + identity + '. Database import is NOT yet confirmed; inspect cron logs.')
    except (InvalidCatalog, OSError, EOFError, ValueError, subprocess.SubprocessError):
        parser.exit(1, 'Staging upload stopped. Do not delete release state. Inspect the inbox and upload.lock before retrying; no database import was confirmed.\n')


if __name__ == '__main__':
    main()