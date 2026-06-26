# src/mission: vendored module (do not edit casually)

This package is vendored **verbatim** from the Mappalink MiR connector:
- Repo: https://github.com/mappalink/inorbit-mir-connector
- Pinned commit: c516f7d9e8e6b8b3cbaa396e2984ce149c6e7925 (2026-05-21)
- Upstream path: mir_connector/src/mission/

## Rules for changing files in this directory

1. **Log every edit in the file header.** Each file has a `# Modifications from upstream` block
   under its SPDX header. Append `- <YYYY-MM-DD> <author>: <what changed and why>` for ANY change.
2. **Keep SPDX headers** (`SPDX-FileCopyrightText: 2026 Mappalink`, `SPDX-License-Identifier: MIT`).
3. **Do not reformat or relint** vendored files, because it destroys the upstream diff. Functional
   changes only.
4. **Prefer not to edit here.** Subclass/wrap in connector code (`src/mission_exec.py`,
   `src/mir_api/`) instead. Edit a vendored file only when there is no clean override point.
5. **Re-syncing with upstream:** diff this dir against the pinned commit, bump the pin above,
   re-apply each recorded modification, update headers.
