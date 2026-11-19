# Security

Workflows can run Python, access files, start external tools, and use the network.
Read a workflow before executing it. A green CI check is not a safety guarantee.

Never commit credentials or private data. If you discover a vulnerability or an
exposed secret, use GitHub's private vulnerability reporting when enabled, or
contact the maintainer privately through the repository owner's GitHub profile.
Do not post credentials or sensitive details in a public issue.

Revoke exposed credentials immediately. Deleting a file does not remove it from
Git history. Maintainers: see docs/MAINTAINERS.md for CI and publication boundaries.
