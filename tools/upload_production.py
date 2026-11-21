#!/usr/bin/env python3
"""Local production-only uploader. NEVER run before frozen preflight and cutover approval."""

from upload_staging import main


if __name__ == '__main__':
    main('production')