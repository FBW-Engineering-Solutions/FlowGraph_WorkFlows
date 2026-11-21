PYTHON ?= python3

.PHONY: help test validate setup-production release-production release-production-dry-run

help:
	@echo 'test / validate: offline catalog checks'
	@echo 'setup-production: save local non-secret SFTP settings once'
	@echo 'release-production: test, build, upload, approve, wait for cron and verify'
	@echo 'release-production-dry-run: read current receipt and prepare locally without uploading'
	@echo 'No release arguments or per-release .env changes. Requires one-time hosted sync setup.'

test:
	$(PYTHON) -m unittest discover -s tests -v

validate:
	$(PYTHON) tools/validate_catalog.py

setup-production:
	$(PYTHON) tools/release_production.py --setup

release-production:
	$(PYTHON) tools/release_production.py

release-production-dry-run:
	$(PYTHON) tools/release_production.py --dry-run