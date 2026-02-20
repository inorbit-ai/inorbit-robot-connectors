# SPDX-FileCopyrightText: 2026 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

SHELL := /bin/bash

.PHONY: bump bump-patch bump-minor bump-major

# Usage: make bump PART=patch|minor|major|alpha|beta|rc|post|dev|stable [DRY=1] [DIRTY=1]
# Convenience targets: bump-patch, bump-minor, bump-major
bump:
	@set -euo pipefail; \
	PART=$${PART:-patch}; \
	DRY=$${DRY:-0}; \
	DIRTY=$${DIRTY:-0}; \
	if [ "$$DRY" != "0" ]; then \
		uv version --bump $$PART --dry-run; \
		exit 0; \
	fi; \
	if [ "$$DIRTY" = "0" ] && { ! git diff --quiet || ! git diff --cached --quiet; }; then \
		echo "Working tree must be clean before bumping"; \
		exit 1; \
	fi; \
	old_version=$$(uv version --short); \
	uv version --bump $$PART; \
	new_version=$$(uv version --short); \
	git add pyproject.toml uv.lock; \
	git commit -m "Bump inorbit-omron-connector version: $${old_version} → $${new_version}"; \
	git tag -a "inorbit-omron-connector-v$${new_version}" -m "Bump inorbit-omron-connector version: $${old_version} → $${new_version}"; \
	echo "Bumped version $$old_version → $$new_version"

bump-patch:
	@$(MAKE) bump PART=patch DRY=$${DRY:-0}

bump-minor:
	@$(MAKE) bump PART=minor DRY=$${DRY:-0}

bump-major:
	@$(MAKE) bump PART=major DRY=$${DRY:-0}
