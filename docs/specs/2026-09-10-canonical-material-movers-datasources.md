<!--
SPDX-FileCopyrightText: 2026 InOrbit, Inc.

SPDX-License-Identifier: MIT
-->

# Canonical material-moving-vertical datasources: Omron FLOWCore and MiR

Status: draft proposal, not implemented, not yet reviewed.
Date: 2026-09-10.

## 1. Goal

Define, for the material-moving (AMR) vertical, the same kind of OEM-agnostic canonical
data contract the cleaning vertical already has (see
`gausium_open_platform_connector/docs/specs/2026-08-20-canonical-cleaning-datasources.md`),
and reshape `omron_flowcore_connector` and `mir_connector` to publish it, so account
config (DataSourceDefinitions, KPI definitions, Modes, dashboards) becomes a template
shared by both OEMs instead of two independent dialects.

Unlike the Gausium spec, there is no pre-existing reference implementation for this
vertical to align to. This document *is* the first draft of that contract, derived from
comparing what the two connectors already do. Breaking changes are accepted: key names may
change on both connectors.

### Scope

In scope: `omron_flowcore_connector` and `mir_connector` code and their `cac/` /
`cac_examples/` directories.

Out of scope: `otto_connector` and `instock_connector` (also material-moving-shaped, not
touched here — see 9.4), `gausium_legacy_connector` and `gausium_open_platform_connector`
(different vertical), account-level config, version bumps.

### Evidence base

**This is source-code analysis, not live capture.** Everything below was read from `main`
on 2026-09-10: `omron_flowcore_connector/inorbit_omron_connector/` and
`mir_connector/inorbit_mir_connector/` (connector code, tests, `cac`/`cac_examples`).
Test fixtures stand in for live payloads where they show concrete values, but several
items below could not be settled from code alone — those are flagged explicitly as open
questions in section 9 rather than guessed, the same way the Gausium spec flagged
undocumented tank units and `battery_soh`'s type. Before implementing, capture live
status/mission payloads from one Omron and one MiR robot to close those.

## 2. Conventions

Same platform-wide conventions the cleaning vertical uses, restated because the tables
below depend on them:

- snake_case keys, identical across OEMs.
- Percentages published as **0-1**.
- SI units: m, s, m/s, kg where applicable.
- Unit suffix grammar: plain unit as-is (`_m`, `_s`), percentages `_pct` (0-1), counts
  `_count`, rates join with `p` for "per".
- Fields normalized to an InOrbit enum publish twice: the normalized value under the
  canonical key, the untouched vendor value under `<field>_raw`. Unknown vendor values
  normalize to `"other"`/`"unknown"` while the raw key still shows exactly what the robot
  said. A value derived from *several* fields (like `mission_status`) gets no `_raw` twin,
  since there is no single raw value to preserve — the inputs remain visible under their
  own keys.
- Numeric fields get no `_raw` twin.
- Omit rather than guess: an unrecognized enum value still omits the canonical key only
  when even "other"/"unknown" would be misleading (rare); a derived figure whose arithmetic
  doesn't hold is withheld rather than published wrong.

### The `mission_tracking` envelope is not connector-chosen

Both connectors already publish a JSON-typed key-value literally named `mission_tracking`,
and both shape it as `{missionId, inProgress, status, state, label, completedPercent,
startTs, endTs?, data: {...}, tasks?: [...]}`. That envelope is camelCase and fixed by the
InOrbit `MissionTracking`/Mission-object schema, not a per-connector choice — it is out of
scope for snake_case homogenization. **All homogenization work on mission data targets the
inner `data{}` dict**, which is connector-authored and where the two connectors currently
disagree (section 5), plus the vendor vocabularies feeding the envelope's own `state` and
`status` fields.

## 3. Live key-values

### 3.1 Already aligned, no change

| Key | Meaning | Omron source | MiR source |
|---|---|---|---|
| `connector_version` | connector build version | `key_values.py:83` | `get_module_version()`, `connector.py` |
| `api_connected` | connector-to-vendor-API reachability | `key_values.py:84` | `robot.api_connected`, `connector.py` |

These already match in name and meaning on both connectors. Nothing to do.

### 3.2 Contract keys: renamed or reshaped

| Key | Omron today | Omron change | MiR today | MiR change |
|---|---|---|---|---|
| `battery_pct` | `battery_percent` = `float(value)`, **no /100** (`key_values.py:121`), source `DataStoreValueLatest("BatteryStateOfCharge")` | rename, add `/100`, **pending live confirmation of vendor scale** (see 9.1) | `"battery percent"` (literal space, `connector.py`), already `to_inorbit_percent()` (÷100) | rename only, drop the space |
| `robot_online` | already this name, `offline_reason is None` (`key_values.py:85`) | none | not published today | add, see 9.2 — thinner distinction from `api_connected` on MiR's single-robot embedded API than on Omron's fleet-manager API |
| `task_state` / `task_state_raw` | not published as a single normalized live key today (only raw `omron_sub_status`) | new: normalize `omron_sub_status` to `idle`/`executing`/`paused`/`unknown`, publish `task_state_raw` = the untouched `omron_sub_status` string | not published as a single normalized live key today (only raw `state_text`) | new: normalize `state_text` the same way, publish `task_state_raw` = untouched `state_text` |
| `mission_status` | `status` today (`IDLE`/`BUSY`/`CHARGING`/`ERROR`, derived in `map_status()`, `key_values.py:46-61`) | rename value set to the four-value, capitalized `Idle`/`Mission`/`Charging`/`Error` (matches the cleaning vertical's own `mission_status`, since Modes is a platform-wide widget, not vertical-specific): `BUSY`→`Mission`, `IDLE`→`Idle`, `CHARGING`→`Charging`, `ERROR`→`Error` | not computed in connector code today — computed **account-side** by a derived DataSourceDefinition over `mission_text`/`state_text` (`cac_examples/data_sources.yaml:75-90`) | **migrate into the connector**, replicating the existing account-side logic verbatim, then retire that derived datasource (same move the Gausium spec made — "deriving in the connector is the direction to converge on") |
| `emergency_stop` | not published as a boolean; `EstopPressed` is only a bucket inside `map_status()`'s `ERROR` case | new: `omron_sub_status == "EstopPressed"` | `emergency_button_pressed` (diagnostics `Emergency button != "Released"`, v3-firmware-only) | rename to `emergency_stop` for the shared name; stays v3-only, omitted (not `false`) on v2 firmware — no signal exists there |
| `battery_time_remaining_s` | not published | new, **if** a DataStore key exists (unconfirmed, see 9.1) | `battery_time_remaining` (already seconds) | rename only, add `_s` suffix |
| `distance_to_next_target_m` | not published, no analog found | declared per-OEM gap unless FLOWCore exposes one (unconfirmed) | `distance_to_next_target` | rename only, add `_m` suffix |
| `odometer_m` (lifetime distance, distinct from per-mission `distance_m`, see 5.3) | not published — `get_robot_odometry()` always returns `None` (`robot_manager.py:384-391`), not implemented, not a confirmed vendor gap | needs investigation before deciding (9.3) | `moved` (cumulative meters since... unclear reset point) | rename only |

### 3.3 Vendor vocabulary tables

**`task_state` mapping.**

| Contract value | Omron `omron_sub_status` values | MiR `state_text` values |
|---|---|---|
| `idle` | `Available`, `Parked`, `Allocated`, `Unallocated` | (needs a value from live capture — not in evidence, see 9.4) |
| `executing` | `Driving`, `BeforePickup`, `AfterDropoff`, `BeforeDropoff`, `BeforeEvery`, `AfterEvery` | `"Executing"` |
| `paused` | `Interrupted` (observed as a named-but-unbucketed value per `key_values.py:56-59`) | `"Pause"` (observed, `mir_api_base.py:313`) |
| `unknown` | anything unrecognized, e.g. `AvailableForJobs`, `Parking` | anything unrecognized |

Docking/charging substates (`Docked`, `Docking`, `Charging`, `DockParking`, `DockParked`,
`ForcedDocking` for Omron) and fault substates (`Fault`, `Lost`, `Disconnected`,
`MotorsDisabled`, `OutgoingArclConnectionLost`) are **not** `task_state` values — they feed
`mission_status`'s `Charging`/`Error` buckets instead, same split the cleaning vertical
makes between `task_state` (robot-execution state) and `mission_status` (mode bucket for
Modes widget).

**`mission_status` precedence**, matching the cleaning vertical's own precedence order
(`Error` outranks `Mission` outranks `Charging` outranks `Idle`):

| Order | Value | Omron condition | MiR condition (migrated from `data_sources.yaml:75-90`) |
|---|---|---|---|
| 1 | `Error` | `omron_sub_status` in the `ERROR` bucket (3.3 above), incl. `EstopPressed` | `state_text in ("EmergencyStop", "Error")` |
| 2 | `Mission` | `omron_sub_status` in the `BUSY` bucket | `state_text == "Executing"` and `mission_text` does not match `"Charging"` |
| 3 | `Charging` | `omron_sub_status` in the `CHARGING` bucket | `state_text == "Executing"` and `mission_text` matches `"Charging"` |
| 4 | `Idle` | `omron_sub_status` in the `IDLE` bucket, or unrecognized (fallback) | anything else |

MiR's existing account-side rule folds "charging" detection into a `mission_text` string
match rather than a dedicated status; kept as-is on migration since it's already proven,
but flagged in 9.5 as worth tightening once a live `mission_text` sample during charging is
available.

**No `_raw` twin for `mission_status`**, same reasoning as the cleaning vertical: it's
derived from more than one field. The inputs (`task_state_raw`, `emergency_stop`) remain
the debugging path.

**What this replaces on MiR.** The account-side `mission_status` derived datasource
(`data_sources.yaml:75-90`) is retired once the connector publishes the key directly, or it
will shadow the connector's value — same caution the cleaning vertical spec called out for
Gausium. The neighboring `emergency-stopped` derived datasource
(`data_sources.yaml:92-105`) is separately dead — it reads `getValue('status_text')` into
an unused variable and actually checks `getValue('status')`, a key that has never been
published (the real key is `state_text`), so it can never fire. It should be deleted
outright as part of this work, not migrated: the new connector-side `emergency_stop` key
replaces its intent.

### 3.4 Unchanged, kept as-is on the connector that already has them

No attempt is made here to invent Omron equivalents for MiR's v3-firmware-only diagnostic
set (`laser_front_blocked`, `laser_back_blocked`, `front_scanner_cover_clean`,
`back_scanner_cover_clean`, `charger_cable_connected`, `speed_violation_ok`,
`wifi_ssid`, `wifi_frequency_mhz`, `wifi_signal_dbm`, `wifi_access_point_mac`,
`wifi_mac_address`, `wifi_ip_address`, `wifi_link_up_count`, `wifi_link_down_count`,
`temperature_celsius`) or for Omron's `robot_ip`/`robot_attached`/`offline_reason` on MiR.
These names are already generic enough that a future OEM with equivalent signals can adopt
them unchanged; declared per-OEM gaps rather than filled with invented data, per the
"omit rather than guess" convention.

`offline_reason`'s four-value vocabulary (`api_unreachable`, `not_in_fleet`,
`disconnected`, `no_telemetry`, `robot_manager.py:29-32`) is worth adopting on MiR too, but
`not_in_fleet` presumes a fleet-manager mediating between the connector and the robot,
which MiR's embedded per-robot API doesn't have — MiR would only ever produce a subset
(`api_unreachable`, `disconnected`, `no_telemetry`). That's a declared, structural per-OEM
gap, not an oversight.

## 4. Pose

Both connectors already converge on **x, y in meters, yaw in radians** — no unit change
needed on either side (Omron: mm→m via `/1000.0`, deg→rad via `radians()`,
`robot_manager.py:42-49`; MiR: meters as-is, `radians(status.position.orientation)` for
yaw at publish time).

**`frame_id` does not converge.** MiR already publishes the real map id
(`status.map_id`). Omron hardcodes the literal string `"map_frame"`
(`robot_manager.py:42-49`) regardless of which map the robot is actually on — a bug, not a
design choice, and it silently breaks multi-map fleets. Fixing it requires finding a
current-map name/id field in the FLOWCore API (unconfirmed in evidence, see 9.3) before a
canonical `frame_id` behavior can be specified for Omron. Until then, this item stays open
rather than shipping a guessed field name.

## 5. Mission tracking data

### 5.1 The envelope itself: keep as-is

`missionId`, `inProgress`, `label`, `startTs`, `endTs` (MiR has it; Omron doesn't derive
one today, see 5.4), and `tasks` (MiR's action list / Omron's segment list) already carry
equivalent meaning on both connectors and are not touched.

### 5.2 Envelope `state` and `status`: shared vocabulary

**`state`** (canonical: `queued` / `executing` / `paused` / `completed` / `aborted` /
`failed` / `canceled` / `unknown`):

| Contract value | Omron `OmronJobStatus` (`mission/tracking.py:15-26`) | MiR mission state |
|---|---|---|
| `queued` | `Queued`, `Pending` | unconfirmed — MiR's `Pending`/`Queued` states are presumed to exist per the MiR API but were not observed in any test or fixture read (9.4) |
| `executing` | `InProgress` | `Executing` |
| `paused` | `Waiting` (tentative — see below) | no observed native-mission-level pause state distinct from `Executing`; only the robot-level `state_text` shows `"Pause"` (9.5) |
| `completed` | `Completed` | `Completed`, `Done` (`MISSION_STATE_DONE` — presumed a synonym of `Completed`, not confirmed distinct, 9.4) |
| `aborted` | — (Omron has no aborted-by-user distinct from cancelled today) | `Aborted` (also merged from raw `Abort`, `mission_tracking.py:75-76`) |
| `failed` | `Failed` | no observed equivalent (9.4) |
| `canceled` | `Cancelled`, `Canceled` (both vendor spellings collapse to one contract value) | no observed equivalent distinct from `Aborted` (9.4) |
| `unknown` | `Unknown`, `Interrupted` (tentative, see below) | anything unrecognized |

`Waiting` and `Interrupted` are Omron vendor values whose exact meaning against `paused` vs
`unknown` is a judgment call from naming alone, not confirmed by a captured payload — flag
per section 9 before locking the mapping in.

**`status`** (health, canonical: `ok` / `warning` / `error`):

- Omron already computes this three-value set via `_map_health()`
  (`mission/tracking.py:319-324`) — no change.
- MiR only sets a binary `"OK"`/`"error"` on completion. Adopting the three-value set on
  MiR needs a `warning` condition defined (e.g., a mission that completed but with a
  degraded outcome) — not fabricated here since MiR has no such signal today; MiR keeps
  publishing only `ok`/`error` until one is identified. This is a declared per-OEM
  narrower-vocabulary case, same pattern as `mission_status`'s `Charging` bucket being
  Omron-only richer.

### 5.3 Inner `data{}`: the actual homogenization

MiR's current `data{}` keys are Title Case with units in parens
(`"Total Distance (m)"`, `"Uptime (s)"`, `"WiFi RSSI (dbm)"`,
`"Battery Time Remaning (s)"` — note the vendor/connector typo) and mix mission-scoped
figures with connector-context figures that duplicate live key-values
(`"Robot Model"`, `"Serial Number"`, `"Uptime (s)"`). Omron's `data{}` is closer to
snake_case-adjacent already (`jobId`, `jobType`, `priority`, `isSuccess`) but is itself
camelCase, inherited from the vendor payload shape rather than deliberately chosen.

Canonical `data{}` fields:

| Key | Omron source | MiR source | Note |
|---|---|---|---|
| `mission_type` / `mission_type_raw` | `jobType` (`P`/`D`/`PD`/`M`) normalized to `pickup`/`dropoff`/`delivery`/`multi_goal`/`other` | — | MiR native missions are free-form user-defined graphs with no vendor type field; declared Omron-only, not filled with a guess |
| `priority` | `priority` (raw, default `"Normal"`) | — | same — no MiR concept of mission priority found |
| `mission_steps_count` | new: total segment count (already computed internally for `completedPercent`, `mission/tracking.py:138-141`) | `"Mission Steps"` → rename | |
| `distance_m` | not available (no distance/odometry source at all, 9.3) | `"Total Distance (m)"` → **not a rename, a fix**: today it republishes the lifetime `odometer_m` value unchanged inside every mission's report, so it never resets per mission (confirmed bug). Needs a connector-side delta: `odometer_m` at mission end minus `odometer_m` at mission start | mission-scoped meaning only; MiR needs the delta computed, Omron needs a source before it can be filled |
| `duration_s` | new: `endTs - startTs` once `finished` semantics are confirmed (9.4 — `finished`'s type/units are unobserved, currently passed through raw with no transform) | new: `endTs - startTs` (MiR already has both timestamps) | mirrors the cleaning vertical's `duration_s` (wall time, not vendor-reported) |
| `interruptions_count` | new: connector counter, incremented on an `executing`→`paused` `state` transition, reset on new `missionId` | new: same pattern, but must watch the **robot-level** `state_text` (`"Pause"`) rather than the native-mission `state` field, since MiR's native mission state has no confirmed distinct paused value (5.2) — a cross-source wiring detail, not a shared implementation | same derivation pattern as the cleaning vertical's `interruptions_count`, applied to both |
| `wifi_rssi_dbm` | not available | `"WiFi RSSI (dbm)"` → rename | kept MiR-only rather than duplicating the live `wifi_signal_dbm` key by policy call — open question in 9.6 whether a mission-scoped signal snapshot is worth keeping at all vs. just dropping it as redundant |
| `battery_time_remaining_s` | not available | `"Battery Time Remaning (s)"` → rename, fixing the typo | redundant with the live key (3.2); recommend dropping from `data{}` rather than duplicating, per 9.6 |

**Dropped rather than migrated**, because they only duplicate already-published
connector-context (not mission-scoped) live key-values: MiR's `data["Robot Model"]`,
`data["Serial Number"]`, `data["Uptime (s)"]`, and the mislabeled `data["Total Missions"]`
(which is actually just the mission id repeated, not a count — `mission_tracking.py`).
None of these describe the mission itself. This mirrors the cleaning-vertical spec's own
`filter_truthy` cleanup: a mission report's `data{}` should carry only fields whose meaning
changes per mission.

`isSuccess` / `isSuccessNum` (Omron): the `status`/`state` fields at the envelope level
already carry this; the numeric duplicate (`isSuccessNum`, a bool mirrored as `1`/`0`)
is redundant and should be dropped, keeping only `isSuccess`.

## 6. Dead or wasteful polling to remove

| Connector | What | Why remove |
|---|---|---|
| Omron | `mission/tracking.py:138-141` hardcoded fallback of 10 segments when `get_job_segment_list` fails | Silently degrades `completedPercent` accuracy with a guessed magic number instead of omitting the field or retrying — a correctness bug uncovered while inventorying, not itself a rename target, but should be fixed alongside this work since it affects a canonical field (`completedPercent`) |
| Omron | `arcl_client.py:187-201`: `_read_loop`'s docstring claims it parses status lines; it only detects disconnection | Not a "delete" — a scope clarification. No key-value originates from ARCL today; don't imply otherwise in the next round of docs/comments |
| MiR | Prometheus metrics fetched every 2s and mostly discarded: `mir_robot_position_x_meters`, `mir_robot_position_y_meters`, `mir_robot_orientation_degrees`, `mir_robot_info`, `mir_robot_errors`, `mir_robot_state_id`, `mir_robot_uptime_seconds`, `mir_robot_battery_percent`, `mir_robot_battery_time_remaining_seconds`, `mir_robot_wifi_access_point_info`, `mir_robot_wifi_access_point_frequency_hertz` | Redundant with `/status` and diagnostics fields already published from a different endpoint, never used as a fallback or cross-check. Candidate for removal, though lower priority than the key-value renames since it's not user-visible — flag for the connector owner to confirm nothing depends on it before deleting |
| MiR | `connector.py:394` TODO acknowledges diagnostics has "a lot of valuable data" only partially parsed | Not resolved here — the fields this spec adds (`emergency_stop`, wifi/laser/cover booleans already exist) cover the parts relevant to homogenization; the rest stays a follow-up, not blocking |

## 7. Config as code

`omron_flowcore_connector/cac/data_sources.yaml` (new — no such file exists today per the
scope 3-file listing) and `mir_connector/cac_examples/data_sources.yaml` (exists, needs
edits) should both define, with matching `id`s: `battery_pct`, `task_state`,
`mission_status`, `emergency_stop`, plus whichever per-OEM keys each connector actually
publishes (declared gaps stay undefined, not stubbed).

- `mission_status`: a plain `keyValue` DataSourceDefinition, no transform, on both — same
  shape as the cleaning vertical's (see that spec's 3.4 for the exact YAML), since both
  connectors now compute the value themselves.
- MiR's `cac_examples/data_sources.yaml:92-105` `emergency-stopped` derived datasource: delete.
- MiR's `cac_examples/data_sources.yaml:75-90` `mission_status` derived datasource: delete
  once the connector ships the key, same caution as the Gausium spec gave about a
  shadowing derived datasource.
- `mission_tracking.yaml` on both: update field docs to the new `data{}` shape (5.3); the
  `MissionTracking`/`type: json` object definition itself is unchanged.

## 8. Implementation layers

Proposed as independent stacked PRs per connector, not interleaved, since the two
codebases don't share files:

**Omron**

| # | Content |
|---|---|
| 1 | `battery_pct` scale fix (pending 9.1 confirmation), `robot_online` unchanged, `task_state`/`task_state_raw` |
| 2 | `mission_status` rename + four-value vocabulary |
| 3 | `emergency_stop` derivation |
| 4 | Mission `data{}` reshape: `mission_type`/`mission_type_raw`, `mission_steps_count`, `interruptions_count`, drop `isSuccessNum` |
| 5 | Segment-count-fallback bug fix (section 6) |
| 6 | `cac/data_sources.yaml` |

**MiR**

| # | Content |
|---|---|
| 1 | `battery_pct` rename (drop the space), `battery_time_remaining_s`, `distance_to_next_target_m`, `odometer_m` renames |
| 2 | `task_state`/`task_state_raw`, `emergency_stop` rename |
| 3 | `mission_status` migrated into connector code; delete both stale derived datasources |
| 4 | Mission `data{}` reshape: rename Title-Case keys, drop connector-context duplicates, fix the mission-scoped `distance_m` bug, add `duration_s`, `interruptions_count` |
| 5 | `cac_examples/data_sources.yaml`, `mission_tracking.yaml` updates |

Each connector's layer 4 is the highest-risk one (behavior change, not just rename) and
should ship separately from the pure renames, same isolation principle the cleaning
vertical spec used for its `task_outcome` layer.

## 9. Open questions (need live payloads to resolve)

1. **Omron `battery_percent` scale.** Currently published as `float(value)` with no
   division; the only observed value (test fixture `50.0`) is consistent with either a
   0-100 or an already-0-1-ish reading. Capture a live `DataStoreValueLatest`
   `BatteryStateOfCharge` response before deciding whether `/100` is correct.
2. **MiR `robot_online` semantics.** MiR's API is embedded per-robot, so "API reachable"
   and "robot online" may nearly coincide — worth checking whether the MiR REST API
   distinguishes "robot responded but reports itself disconnected from network" from "API
   didn't respond at all" before adding a key that would just mirror `api_connected`.
3. **Omron pose `frame_id` and `odometer_m`/`distance_m` source.** No map-name field or
   odometry/velocity field was found in the evidence read of `robot_manager.py`,
   `api_client.py`, or `models.py`. Needs a targeted look at the FLOWCore API docs or a
   live `/DataStoreValueLatest` probe (the same technique the Gausium spec used to find its
   dead endpoints) for a current-map key and any velocity/odometry key before `frame_id`
   and `odometer_m`/`distance_m` can be filled for Omron.
4. **Unobserved MiR mission states** (`Pending`/`Queued`/`Failed`/`Canceled` distinct from
   `Aborted`) **and Omron's `Waiting`/`Interrupted`/`finished` field.** None of these were
   seen in a real payload or test fixture — only inferred from naming. A live capture
   spanning a queued, a failed, and a paused-then-resumed mission on each OEM would confirm
   or correct the mapping in 5.2 and the `finished` field's type in 5.3.
5. **MiR's `mission_text` "Charging" string match.** The account-side rule being migrated
   in 3.3 detects charging via a substring match on `mission_text` rather than a dedicated
   status; worth checking whether a live sample while charging still matches, before
   locking it into connector code (a migration bug here is harder to notice than in an
   editable derived datasource).
6. **Whether mission-scoped `wifi_rssi_dbm` and `battery_time_remaining_s` in MiR's
   `data{}` are worth keeping at all**, given the live key-values already cover both. This
   spec's default is to drop them; keep only if a captured multi-mission report shows a
   value that meaningfully varies from the live key at report time (e.g., signal strength
   read at the exact task moment, not the polling tick).

## 10. Out of scope, but should converge next

`otto_connector` and `instock_connector` are also material-moving-shaped, but their code
was not read for this spec — pulling them into this contract is separate follow-up work
once Omron and MiR have shipped and the vocabulary has proven itself against a second
data point, same sequencing the cleaning vertical is following (Gausium aligning to one
existing reference before a third cleaning OEM joins).
