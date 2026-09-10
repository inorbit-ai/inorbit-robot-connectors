<!--
SPDX-FileCopyrightText: 2026 InOrbit, Inc.

SPDX-License-Identifier: MIT
-->

# Cleaning vertical — canonical datasources (proposal)

Status: **proposal**, nothing applied. Cleaning robots are a vertical to support
properly: this contract targets **any cleaning-robot connector** (reference mappings:
Gausium and a second OEM connector; a third OEM mapped for completeness), so account config
(DataSourceDefinitions, KPI definitions, dashboards, per-zone coverage) becomes a vertical
template that works unchanged across OEMs. When an OEM cannot provide a
field it is declared as a per-OEM gap — the field stays in the contract for everyone
else.

Conventions:

- snake_case keys, identical across OEMs.
- Percentages published normalized to **0–1** (the platform convention: % datasources
  store 0–1 and widgets display ×100). Legacy 0–100 sources adapt via `scale: 0.01`.
- SI units (m², s, L, km/h).
- Unit suffixes on keys/ids follow a fixed grammar: plain unit as-is (`_m2`, `_s`, `_l`),
  percentages `_pct` (values 0–1), counts `_count`, and rates join with `p` = "per"
  (`_m2ph` = m²/h, `_kmph` = km/h — never `_kmh`).
- **Enum fields publish two keys.** Fields normalized to an InOrbit-standard enum
  (`cleaning_mode`, `task_outcome`) are published twice: the normalized value under the
  canonical key, and the vendor's original value untouched under `<field>_raw`. Example:
  a Gausium robot dust-mopping publishes `cleaning_mode: "dust_mop"` and
  `cleaning_mode_raw: "__尘推"`. When a vendor sends a value the mapping doesn't know,
  the normalized key falls back to `"other"` while the raw key still shows exactly what
  the robot said — so unknown values stay visible (and bucketable in platform config,
  e.g. Modes) instead of vanishing, and mapping bugs are debuggable. Numeric fields lose
  nothing in translation and get no `_raw` twin.
- Mission fields are scalars → KPI-definable with no platform changes.
- Field mappings verified against live payloads captured 2026-08-14/15.

## 1. The datasources

### Mission report fields (end-of-task mission_tracking data — not datasources;
they land in mission data and are consumed by KPI definitions)

| Key | Unit | Meaning |
|---|---|---|
| `planned_area_m2` | m² | Area the task was supposed to clean |
| `cleaned_area_m2` | m² | Area actually cleaned |
| `coverage_pct` | 0–1 | cleaned / planned |
| `duration_s` | s | Wall time, start → end |
| `active_cleaning_time_s` | s | Time actually spent cleaning (excludes pauses/interruptions) |
| `efficiency_m2ph` | m²/h | Cleaned area per active hour |
| `water_used_l` | L | Water consumed |
| `battery_start_pct` | 0–1 | Battery at task start |
| `battery_end_pct` | 0–1 | Battery at task end |
| `battery_used_pct` | 0–1 | Battery consumed |
| `interruptions_count` | count | Pauses/breaks during the task |
| `cleaning_mode` | enum + raw | scrub, vacuum, sweep, dust_mop, polish, disinfect, other |
| `task_outcome` | enum | completed, incomplete, abandoned, not_reported (success threshold = `mission_success_percentage_threshold`) |
| `map_name` | string | Map(s)/floor(s) the task ran on (comma-joined) — free group-by dimension |
| `report_image_url` | url | OEM-rendered coverage/report image |

Per-zone coverage fields (`zone_<slug>_planned_m2/actual_m2/pct`) ride alongside; a
per-zone design spec is tracked separately from this doc.

### Live (timeline) datasources — basic observability

| Key | Unit | Meaning |
|---|---|---|
| `battery_pct` | 0–1 | Battery level |
| `charging` | bool | On charger and charging |
| `task_state` | enum | idle, cleaning, paused, unknown |
| `robot_online` | bool | Robot connectivity (not API health) |
| `current_map_name` | string | Map/floor the robot is localized on |
| `clean_water_tank_pct` | 0–1 | Fresh/solution tank level (bool-only OEMs publish 0/1) |
| `recovery_tank_pct` | 0–1 | Sewage/recovery tank level (idem) |
| `emergency_stop` | bool | E-stop engaged |
| `speed_kmph` | km/h | Current speed |
| `mission_status` | enum string | Robot operating mode, bound to the Modes panel (see "Robot modes" below) |

High-value optionals (publish when the OEM exposes them): per-part consumable wear
(`consumable_<part>_wear_pct`), battery health (`battery_soh`, `battery_cycles`), live
task progress (cleaned m² so far).

### Robot modes (`mission_status`)

The Modes panel maps arbitrary strings to modes, so the contract does not enforce a
vocabulary — but the strongly recommended approach is a **standard mode enum**, derived
**in each OEM's connector** from its API data and published as the `mission_status`
key-value:

| Mode | Meaning |
|---|---|
| `Idle` | Powered and reachable, no task, not charging |
| `Mission` | Running a cleaning task (a paused task counts as Mission unless `Paused` is adopted) |
| `Paused` | Optional: task paused, when the OEM distinguishes it |
| `Charging` | On the charger with no task running (Mission outranks Charging) |
| `Error` | E-stop, stuck, disabled, or fault states |

Deriving in the connector keeps the account config OEM-agnostic and makes the Modes
panel a trivial 1:1 mapping; raw vendor states remain available through `task_state`
for debugging. **Current state / migration:** the OEM B connector already publishes this
enum; Gausium currently emits raw vendor strings via a tag-level derived datasource
(bucketed in the Modes config) and should migrate the derivation into the connector
soon.

### Vendor extras (same naming scheme, optional)

`charge_stops_count`, `elevator_rides_count`, `coverage_heatmap_url`,
`consumable_brush_pct`/`consumable_filter_pct`/`consumable_suction_blade_pct` (per-report
residuals), `polished_area_planned_m2`/`polished_area_m2`, `operator`, `distance_m`.

Excluded on purpose: `energy_kwh` (OEM B documents its own value as error-prone; Gausium
has none — battery deltas cover it); distance as a common field (the platform derives
`estimatedDistance` from poses where they exist; OEM-reported distance is an extra);
tank end-levels as mission fields (they are live datasources).

## 2. OEM mappings

### Gausium (Scrubber 50, Open Platform API)

| Contract key | Source | Status |
|---|---|---|
| `planned_area_m2` / `cleaned_area_m2` | report `plannedCleaningAreaSquareMeter` / `actualCleaningAreaSquareMeter` | in mission data (legacy labels) |
| `coverage_pct` | report `completionPercentage` (already 0–1) | in mission data (legacy label) |
| `duration_s` | `endTime − startTime` | derive |
| `active_cleaning_time_s` | report `durationSeconds` | in mission data (legacy label) |
| `efficiency_m2ph` | report `efficiencySquareMeterPerHour` | in mission data (legacy label) |
| `water_used_l` | report `waterConsumptionLiter` | in mission data (legacy label) |
| `battery_start/end/used_pct` | report `startBatteryPercentage`/`endBatteryPercentage`/diff (0–100 → /100) | in mission data (legacy labels) |
| `interruptions_count` | count RUNNING→PAUSED transitions | **add** (connector-side counter) |
| `cleaning_mode` | `cleaningMode` via existing translation table | in mission data (raw label only) |
| `task_outcome` | MissionState logic (`taskEndStatus` + threshold) | exists as mission state |
| `map_name` | `subTasks[].mapName` | **add** |
| `report_image_url` | `taskReportPngUri` | in mission data (legacy label) |
| `battery_pct` / `charging` | status `battery.powerPercentage` (0–100 → publish /100) / `battery.charging` | adapt (tag def uses `scale: 0.01` meanwhile) |
| `task_state` | status `taskState` | published |
| `robot_online` | status `online` | published |
| `current_map_name` | `localizationInfo.map.name` | published (derived DSD) |
| `clean_water_tank_pct` / `recovery_tank_pct` | `device.cleanWaterTank.level` / `device.recoveryWaterTank.level` | published (derived DSDs) |
| `emergency_stop` | `emergencyStop.enabled` | published |
| `speed_kmph` | status `speedKilometerPerHour` | **add/verify** |
| `mission_status` | derive from `taskState` + `battery.charging` + `emergencyStop.enabled` | **add** (today a tag-level derived DSD emits raw strings, bucketed in the Modes config) |

### OEM B (Open Platform API)

| Contract key | Source | Status |
|---|---|---|
| `planned_area_m2` / `cleaned_area_m2` | report `task_area` / `clean_area` | in mission data (legacy labels) |
| `coverage_pct` | `clean_area / task_area` (NOT `percentage` — loop progress) | derive |
| `duration_s` | `end_time − start_time` | derive |
| `active_cleaning_time_s` | report `clean_time` | in mission data (legacy label) |
| `efficiency_m2ph` | `clean_area / (clean_time/3600)` | derive |
| `water_used_l` | report `cost_water` | in mission data (legacy label) |
| `battery_start/end/used_pct` | `battery + cost_battery` / `battery` / `cost_battery` (0–100 → /100) | partially in mission data |
| `interruptions_count` | report `break_count` | **add** |
| `cleaning_mode` | `mode`/`sub_mode` mapping | **add** mapping |
| `task_outcome` | `clean.result.status` decoded (1 in-progress, 2 paused, 3 interrupted, 4 finished, 5 abnormal, 6 canceled) + threshold | exists as mission state |
| `map_name` | `floor_list[].map_name` | **add** |
| `report_image_url` | `task_result_url` | **add** |
| `battery_pct` | status `battery` | published as `battery_percent`, already 0–1 — rename to canonical key only |
| `charging` | `is_charging` | published |
| `task_state` | decoded `clean.result.status` | **add** |
| `robot_online` | detail `online` | **add** (today only `api_connected` = API health) |
| `current_map_name` | detail `map.name` (+ `floor`) | **add** |
| `clean_water_tank_pct` | detail `cleanbot.rising` (= fresh-water %) | **add** (today only inside mission data) |
| `recovery_tank_pct` | detail `cleanbot.sewage` | **add** (idem) |
| `emergency_stop` | — | not exposed by the API |
| `speed_kmph` | — | not exposed by the API |
| `mission_status` | derived from `run_state` + `move_state` + `is_charging` | published (normalized enum) |

### OEM C — for completeness, not planned now

Existing integration keys map cleanly: `area cleaned (last mission)` → `cleaned_area_m2`;
planned = cleaned + `area uncleaned (last mission)`; `coverage (last mission)` →
`coverage_pct`; `fresh_water` → `clean_water_tank_pct`; `battery_level`/`charging` →
`battery_pct`/`charging`; `emergency_switch_pressed` → `emergency_stop`;
`localization_status` → localization state; `distance (last mission)` → `distance_m`
extra. Caveat: `dirt_water_full` is bool-only → `recovery_tank_pct` as 0/100.

## 3. Connector work — what's missing

**Gausium connector:**
1. Publish canonical snake_case mission-data keys alongside the current human labels
   (`"Actual cleaning area [m2]"` etc.); drop labels once account config migrates.
2. `interruptions_count` — count RUNNING→PAUSED transitions during a task.
3. `map_name` in mission data (from `subTasks`).
4. `speed_kmph` key-value (in status, likely unpublished — verify).
5. `mission_status` — derive the standard mode enum in the connector (from `taskState`,
   `battery.charging`, `emergencyStop.enabled`) and publish it, replacing the tag-level
   derived DSD that emits raw strings today.
6. High-value: per-part consumable wear (`device.<part>.usedLife/lifeSpan` — units not in
   Gausium docs, values suggest hours: confirm with OEM); battery health (`battery.soh`,
   `battery.cycleTimes`).

**OEM B connector (all from endpoints it already polls):**
1. Publish canonical mission-data keys alongside current labels; add `coverage_pct`,
   `efficiency_m2ph`, `duration_s` derivations, `interruptions_count`, `cleaning_mode`
   mapping, `map_name`, `report_image_url`.
2. Live key-values: `task_state` (decoded status), `robot_online` (detail `online`),
   `current_map_name` (+ floor), `clean_water_tank_pct` (`rising`), `recovery_tank_pct`
   (`sewage`).
3. Battery convention: OEM B publishes 0–1 today (matches the contract); Gausium
   publishes 0–100 — its canonical `battery_pct` must be 0–1 (or keep the tag adapter
   with `scale: 0.01` until then).
4. High-value: live task progress (`clean.result.area`/`time` mid-run).

## 4. Account config shape

One account-scoped `mission_tracking` datasource as fallback, plus one derived
datasource per field, e.g.:

```yaml
kind: DataSourceDefinition
metadata:
  scope: <CONFIG_SCOPE>
  id: cleaned_area_m2
apiVersion: v0.1
spec:
  label: Cleaned area
  unit: "m2"
  timeline: {}
  source:
    derived:
      transform: |
        mt = getValue("mission_tracking");
        mt.data.cleaned_area_m2
```

Percent datasources: values are 0–1, but always set `scale` explicitly — with
`unit: "%"` and no scale the platform defaults to `scale: 0.01` and re-scales an
already-normalized value (use `scale: 1` for 0–1 keys, `scale: 0.01` for legacy
0–100 keys).

Migration: connectors publish canonical keys alongside current ones → `KpiDefinition.yaml`
moves to canonical fields → legacy label keys drop.

## Field-semantics sources

Gausium developer docs (developer.gs-robot.com, "V1 Get Robot Status": tank levels are %,
`mapPosition` grid vs world meters, angle in degrees, speed km/h). OEM B's portal is JS-only;
semantics come from the OEM B connector's curated mission code (`rising` = fresh-water %,
`sewage` = %, `clean.result.status` map, `cost_water` L) plus live probes (`z` = heading,
verified against published theta).
