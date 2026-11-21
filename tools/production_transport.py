"""Pinned OpenSSH transport for local scheduled releases; passwords stay in memory."""

from contextlib import contextmanager
import base64
import hashlib
import os
from pathlib import Path
import re
import subprocess
import tempfile

from upload_staging import HOST, HOST_FINGERPRINT
from validate_catalog import require


def validate_connection(username, known_hosts):
    require(isinstance(username, str) and bool(re.fullmatch(r'[A-Za-z0-9_-]+', username)), 'invalid SFTP username')
    key = Path(known_hosts)
    require(key.is_file() and not key.is_symlink() and key.stat().st_size <= 1048576,
            'missing or unsafe known_hosts file')
    text = key.read_text()
    keys = [line.split() for line in text.splitlines() if line.strip() and not line.startswith('#')]
    require(len(keys) == 1 and len(keys[0]) == 3 and keys[0][:2] == [HOST, 'ssh-ed25519'],
            'requires the single verified production ED25519 host key')
    digest = hashlib.sha256(base64.b64decode(keys[0][2], validate=True)).digest()
    require('SHA256:' + base64.b64encode(digest).decode().rstrip('=') == HOST_FINGERPRINT,
            'production host fingerprint mismatch')
    return text


@contextmanager
def connect(username, known_hosts, password):
    require(not os.environ.get('CI') and not os.environ.get('GITHUB_ACTIONS'), 'local releases only')
    hostkeys = validate_connection(username, known_hosts)
    require(bool(password) and not any(c in password for c in '\r\n\x00'), 'invalid password')
    with tempfile.TemporaryDirectory(prefix='production-sftp-') as temporary:
        work = Path(temporary)
        key = work / 'known_hosts'
        key.write_text(hostkeys)
        key.chmod(0o600)
        askpass = work / 'askpass'
        askpass.write_text('#!/bin/sh\nprintf "%s\\n" "$CATALOG_SFTP_PASSWORD"\n')
        askpass.chmod(0o700)
        environment = {**os.environ, 'SSH_ASKPASS': str(askpass), 'SSH_ASKPASS_REQUIRE': 'force',
                       'DISPLAY': ':0', 'CATALOG_SFTP_PASSWORD': password}

        def session(commands):
            batch = work / 'batch'
            batch.write_text('\n'.join(commands) + '\n')
            result = subprocess.run([
                'sftp', '-P', '22', '-oBatchMode=no', '-oStrictHostKeyChecking=yes',
                '-oUserKnownHostsFile=' + str(key), '-oGlobalKnownHostsFile=/dev/null',
                '-oPreferredAuthentications=password', '-oPubkeyAuthentication=no',
                '-oNumberOfPasswordPrompts=1', '-oConnectTimeout=30', '-b', str(batch), username + '@' + HOST,
            ], env=environment, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, timeout=180)
            require(result.returncode == 0, 'SFTP failed; inspect private credentials, inbox and locks before retrying')

        yield session, work