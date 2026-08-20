<!--
SPDX-FileCopyrightText: 2026 InOrbit, Inc.

SPDX-License-Identifier: MIT
-->

# Gausium Open Platform connector: canonical cleaning-vertical datasources

Status: approved design, not implemented.
Date: 2026-08-20.

## 1. Goal

Reshape everything this connector publishes to the canonical data contract defined by
the cleaning vertical initiative, so account config (DataSourceDefinitions, KPI
definitions, dashboards) becomes an OEM-agnostic vertical template rather than
Gausium-specific plumbing. Along the way, publish the data the connector already fetches
but throws away, and delete the polling that returns nothing.

Breaking changes are accepted: every published key name changes.

### Scope

In scope: `gausium_open_platform_connector` connector code and its `cac_examples/`.

Out of scope: `gausium_legacy_connector`, account-level config, and version bumps (those
ship separately, never as part of this work).

### Evidence base

Live payloads captured on 2026-08-16 from a Scrubber 50 (`robotFamilyCode: "50"`) on a US
tenant, plus the annotated Open Platform API request collection. Every field and enum
below was read from those, not from memory. Sample references throughout ("the sample
robot", "the sample reports") mean that capture.

### Known collision

A completed v2.0.0 fleet rewrite exists on `claude/gausium-fleet-connector-6de7f6`
(pushed, awaiting live test). It renames every module this spec edits
(`src/robot/robot_api.py` to `src/api/client.py`, `src/robot/robot.py` to
`src/api/data_poller.py`, `config/connector_model.py` to `src/config/models.py`, command
handling extracted to `src/commands.py`, `cac_examples/` to `cac/`) and is already at
2.0.0. This spec deliberately targets `main` and the current layout; the fleet rewrite
absorbs these changes on rebase.

## 2. Conventions

Taken from the contract, restated because every table below depends on them:

- snake_case keys, identical across OEMs.
- Percentages published as **0-1**. Gausium reports 0-100 for battery, tanks and
  consumables, so those are divided by 100.
- SI units: m^2, s, L, km/h.
- Unit suffix grammar: plain unit as-is (`_m2`, `_s`, `_l`), percentages `_pct` (0-1),
  counts `_count`, rates join with `p` for "per" (`_m2ph`, `_kmph`).
- Fields normalized to an InOrbit enum publish twice: the normalized value under the
  canonical key, the untouched vendor value under `<field>_raw`. Unknown vendor values
  normalize to `"other"` while the raw key still shows exactly what the robot said.
  Numeric fields get no `_raw` twin.
- Mission-report fields are scalars, so they are KPI-definable with no platform changes.

## 3. Live key-values

Published every execution loop tick from the v1 status (`GET /v1alpha1/robots/{sn}/status`)
and v2 S status (`GET /openapi/v2alpha1/s/robots/{sn}/status`), both already polled.

### 3.1 Removed

| Key | Why |
|---|---|
| `**status` (the entire v1 status dict splatted as key-values) | Replaced by explicit canonical keys. Nested camelCase vendor blobs forced account config into derived-datasource transforms |
| `battery_percentage` | Replaced by `battery_pct`, 0-1 |
| `total_traveled_distance` | Source endpoint `bot.*/robot-task/robot/details/{sn}` returns `{"code":500,...,"msg":"Internal server error"}` on both the CN and US hosts. The value has always been `0.0`, with a ft-to-m conversion applied on top of the zero |
| `total_operation_time` | Same dead endpoint |

### 3.2 Contract keys

| Key | Source | Transform |
|---|---|---|
| `battery_pct` | v1 `battery.powerPercentage` | / 100 |
| `charging` | v1 `battery.charging` | none |
| `task_state` | v1 `taskState` | raw vendor enum (`IDLE`, `RUNNING`, `PAUSED`, `OTHER`) |
| `robot_online` | v1 `online` | none |
| `current_map_name` | v1 `localizationInfo.map.name` | none |
| `clean_water_tank_pct` | v1 `device.cleanWaterTank.level` | / 100 |
| `recovery_tank_pct` | v1 `device.recoveryWaterTank.level` | / 100 |
| `emergency_stop` | v1 `emergencyStop.enabled` | none |
| `speed_kmph` | v1 `speedKilometerPerHour` | none |
| `mission_status` | derived | the standardized robot-mode datasource, closed five-value enum, see 3.4 |
| `cleaning_mode` / `cleaning_mode_raw` | v2 `currentTask.workMode.name` | see 5.1. Live mode while a task runs; absent when idle |

Tank `level` units are not stated in the Gausium docs. The observed values (`60` clean,
`0` recovery) read as percent, so they are treated as 0-100 and divided by 100.

### 3.3 Additional keys

Derivable from the same two payloads, published today only as opaque nested blobs.

| Key | Source | Notes |
|---|---|---|
| `localization_state` | v1 `localizationInfo.localizationState` | `NORMAL` / `LOST`. Deliberately not folded into `mission_status`, see 3.4 |
| `nav_status` | v1 `navStatus` | e.g. `NAVI_IDLE`. Enumeration unpublished by Gausium |
| `elevator_status` | v1 `currentElevatorStatus` | e.g. `ELEVATOR_CONTROLLER_IDLE` |
| `manual_control` | v2 `currentTask.manualControlling` | bool |
| `battery_soh` | v1 `battery.soh` | **string** enum, observed `"HEALTHY"`. Not numeric, see 9 |
| `battery_cycles` | v1 `battery.cycleTimes` | count |
| `battery_temp_c` | max of v1 `battery.temperature1..7` | Celsius assumed (26-27 at idle). Max is the alert-relevant figure |
| `consumable_<part>_wear_pct` | v1/v2 `device.<part>.usedLife / .lifeSpan` | see below |
| `executable_tasks` | v1 `executableTasks[]` | JSON list of `{id, name, map_name}` |
| `nav_points` | v2 `navigationPoints.naviPoints[].naviPointName` | JSON list of names |
| `work_modes` | v1/v2 `workModes[]` | JSON list of `{id, name, strength, type}` |

Consumable wear is computed generically: for every `device.<part>` object carrying both
`lifeSpan` (> 0) and `usedLife`, publish
`consumable_<snake_case_part>_wear_pct = usedLife / lifeSpan`, clamped to 0-1. No
hardcoded part list, because the set varies by model. On the sample robot this yields
seven keys, of which only `consumable_soft_squeegee_wear_pct` is non-zero
(`22.106201 / 250 = 0.0884`). The v2 payload on other S models additionally exposes
`cleanWaterFilter`, `hepaSensor` and `rightSideBrush`, which the generic rule picks up
for free.

`usedLife` and `lifeSpan` units are undocumented (values suggest hours). The **ratio is
unit-free**, so the wear percentage is well defined regardless. This resolves the open
question the contract raised about these fields.

Note the naming trap: the live `consumable_*_wear_pct` keys are *consumed* fraction,
while the mission-report `consumable_*_pct` keys (5.3) are vendor *residual* percentages,
i.e. remaining. Opposite senses, kept distinct by the `_wear_` infix.

### 3.4 `mission_status`: the standardized robot-mode datasource

`mission_status` is **the** datasource the InOrbit Modes panel binds to. Standardizing it
is a goal of this work in its own right, not a side effect of the key rename, so it is
pinned exactly here.

**The key.** `mission_status`, a string key-value, published on every execution loop tick.
It is always present and always one of the five values below: never absent, never null,
never a vendor string. A gap or an unexpected value would show as an unknown mode in the
panel, so the derivation has a total fallback (`Idle`) by construction.

**The closed value set.** Exactly these five strings, capitalized as written:

| Order | Value | Condition |
|---|---|---|
| 1 | `Error` | v1 `emergencyStop.enabled` |
| 2 | `Paused` | `taskState == PAUSED` |
| 3 | `Mission` | `taskState in (RUNNING, OTHER)` or v2 `currentTask.taskInstanceId` non-empty |
| 4 | `Charging` | v1 `battery.charging` |
| 5 | `Idle` | otherwise |

First match wins. `Mission` outranks `Charging` per the contract. `Paused` is adopted
because Gausium distinguishes it. The set is closed: adding a sixth value is a change to
the vertical contract, not a connector implementation detail, because every OEM's Modes
config would have to learn it.

**No `_raw` twin.** The convention in section 2 gives normalized enums a `<field>_raw`
companion, but `mission_status` is derived from several fields rather than translated from
one, so there is no single raw value to preserve. The vendor state remains fully visible
through `task_state`, `emergency_stop`, `charging` and `localization_state`, which is the
debugging path when a mode looks wrong.

**Why the connector derives it.** Deriving in the connector makes the account-side
configuration a plain key-value binding and identical for every OEM, which is the entire
point of the vertical template. The alternative, deriving in account config, is what the
Gausium setup does today: a tag-level derived DataSourceDefinition emitting raw vendor
strings that the Modes config then buckets. **That derived datasource is retired by this
work** and must be removed from account config when these keys ship, or it will keep
shadowing the connector's value. Elsewhere in this repo, `mir_connector` publishes the
same vocabulary but computes it in a derived-datasource transform over `mission_text` and
`state_text`; connector-side derivation is the standard going forward.

**The datasource definition.** A plain `DataSourceDefinition`, no transform, no unit, no
scale:

```yaml
kind: DataSourceDefinition
metadata:
  scope: <CONFIG_SCOPE>
  id: mission_status
apiVersion: v0.1
spec:
  label: Mission status
  timeline: {}
  source:
    keyValue:
      key: mission_status
```

**The Modes configuration.** Modes are configured against this datasource in the InOrbit
UI, not as a config-as-code object, so this repo cannot ship the mapping itself. Because
the connector emits the standard vocabulary, that mapping is 1:1, value to mode, with no
bucketing rules, pattern matching, or per-account customization. This is also why
`StatusDefinition` is not involved: that kind expresses threshold rules over numeric
datasources for the Fleet Status widget, and has nothing to do with modes.

`localizationState == "LOST"` is **not** mapped to `Error`. The sample robot is
simultaneously `IDLE`, `LOST` and `online` while parked, so that rule would fire
continuously on a healthy fleet. Localization health is exposed as its own
`localization_state` key for alerting to consume.

This is independent of `MissionState.get_from_status` in `mission.py`, which keeps its
current behaviour of treating e-stop as a paused mission.

### 3.5 Unchanged keys

`api_connected` (API reachability, deliberately distinct from `robot_online` which is
vendor-reported robot reachability), `connector_version`, `display_name`, `model_family`,
`model_type`, `software_version`.

## 4. Pose

**Decision: keep grid coordinates times a resolution constant. Do not switch to
`worldX`/`worldY`.**

`localizationInfo.mapPosition.worldX/worldY` are documented as world metres and are
tempting, since `connector.py` currently multiplies grid coordinates by a hardcoded
`MAP_RESOLUTION = 0.05`. But published pose must share a frame with the published map
image, and that image's `MapConfig` uses `origin_x=0, origin_y=0` with the same 0.05
constant. Consuming world metres would require the map's true `originX`/`originY`, and
the only endpoint that exposes them (`POST /openapi/v1/map/robotMap/list`) returns
`originX`, `originY`, `resolution`, `gridWidth` and `gridHeight` all as **zero**.
Switching would misalign pose against the map image.

Instead, `MAP_RESOLUTION` moves into connector config as `map_resolution`
(default `0.05`), consumed by both the pose conversion and the `MapConfig` construction
so the two cannot drift. A robot on a map with different resolution becomes a config
fix rather than a code change.

`localization_state` is published so `LOST` is visible, which is also why the sample
payloads carry no `mapPosition` at all.

## 5. Mission tracking data

### 5.1 Cleaning-mode normalization

A second mapping, alongside the existing `CLEANING_MODE_TRANSLATION` (which produces
human labels and stays for display), maps the vendor mode to the contract enum
(`scrub`, `vacuum`, `sweep`, `dust_mop`, `polish`, `disinfect`, `other`). Input is
normalized first by stripping leading underscores, as `_translate_cleaning_mode` already
does: reports carry `洗地`, while `cleanModes[]` and `workModes[]` carry `__洗地`.

| Vendor value (underscores stripped) | Contract enum |
|---|---|
| `洗地`, `滚刷洗地` | `scrub` |
| `尘推`, `快速尘推`, `低速尘推`, `静音推尘`, `布刷尘推` | `dust_mop` |
| `抛光`, `深度抛光`, `结晶模式` | `polish` |
| `吸尘`, `吸风清洁`, `suction_cleaning` | `vacuum` |
| `扫地` | `sweep` |
| `喷雾消毒` | `disinfect` |
| everything else | `other` |

The rule is: map only unambiguous modes. Intensity variants (`轻度清洁`, `中度清洁`,
`重度清洁`, `middle_cleaning`, `heavy_cleaning`) and `地毯清洁` (carpet cleaning),
`测试` (test) normalize to `other` rather than being guessed into a category. The raw
value is always preserved in `cleaning_mode_raw`, so nothing is lost and a mis-mapping is
debuggable. The observed value on the sample robot is `洗地` -> `scrub`.

### 5.2 In-progress report `data`

| Key | Source |
|---|---|
| `map_name` | v1 `localizationInfo.map.name` |
| `task_id` | v1 `executingTask.id` |
| `task_instance_id` | v2 `currentTask.taskInstanceId` |
| `task_state` | v1 `taskState` |
| `distance_m` | v1 `executingTask.cleaningMileage` (unit undocumented, assumed metres) |
| `time_elapsed_s` | v1 `executingTask.timeRemaining` (empirically elapsed, not remaining) |
| `cleaning_mode` / `cleaning_mode_raw` | v2 `currentTask.workMode.name` |
| `interruptions_count` | connector counter, see 5.4 |

### 5.3 Completed report `data`

Sourced from `GET /openapi/v2alpha1/robots/{sn}/taskReports`.

| Key | Source | Transform |
|---|---|---|
| `planned_area_m2` | `plannedCleaningAreaSquareMeter` | none |
| `cleaned_area_m2` | `actualCleaningAreaSquareMeter` | none |
| `coverage_pct` | `completionPercentage` | already 0-1; falls back to `cleaned / planned` if absent |
| `duration_s` | `endTime - startTime` | ISO 8601 delta in seconds |
| `active_cleaning_time_s` | `durationSeconds` | none |
| `efficiency_m2ph` | `efficiencySquareMeterPerHour` | vendor value used as-is |
| `water_used_l` | `waterConsumptionLiter` | none |
| `battery_start_pct` | `startBatteryPercentage` | / 100 |
| `battery_end_pct` | `endBatteryPercentage` | / 100 |
| `battery_used_pct` | `startBatteryPercentage - endBatteryPercentage` | / 100 |
| `interruptions_count` | connector counter | see 5.4 |
| `cleaning_mode` / `cleaning_mode_raw` | `cleaningMode` | see 5.1 |
| `task_outcome` | derived | see 5.5 |
| `task_end_status_raw` | `taskEndStatus` | raw int |
| `task_instance_id` | `taskInstanceId` | correlates the completed report with the in-progress updates |
| `task_progress` | `taskProgress` | published raw. `0` on every sample report, and the docs never define it or relate it to `completionPercentage`, so it is passed through rather than interpreted |
| `map_name` | `subTasks[].mapName` | unique, comma-joined; falls back to the current map |
| `map_<slug>_cleaned_area_m2` | `subTasks[]` | per-map breakdown, see 5.6 |
| `report_image_url` | `taskReportPngUri` | none |
| `polished_area_planned_m2` | `plannedPolishingAreaSquareMeter` | none |
| `polished_area_m2` | `actualPolishingAreaSquareMeter` | none |
| `operator` | `operator` | none |
| `report_id` | `id` | none |
| `task_id` | `taskId` | static task identity, lets KPIs trend one recurring task across runs |
| `plan_id` | `planId` | schedule plan identity |
| `area_names` | `areaNameList` | raw string, floor-prefixed groups separated by `;`, areas by `,` |
| `loop_count` | `loopCount` | none |
| `expected_loop_count` | `expectedLoopCount` | none |
| `consumable_brush_pct` | `consumablesResidualPercentage.brush` | / 100, residual (remaining) |
| `consumable_filter_pct` | `consumablesResidualPercentage.filter` | / 100, residual |
| `consumable_suction_blade_pct` | `consumablesResidualPercentage.suctionBlade` | / 100, residual |
| `report_map_image_urls` | report map-images query | see 6 |

`duration_s` and `active_cleaning_time_s` are genuinely different quantities, not a
rename: the sample report shows `durationSeconds: 2904` against an `endTime - startTime`
of 2941 s.

Report field extraction, including this timestamp delta, should live in one
transport-agnostic place rather than inline in the poll path. The push callback in
section 11 delivers the same fields with epoch-millisecond timestamps instead of ISO 8601
strings, and that is the only difference it needs to absorb.

`estimatedDurationSecs` on the InOrbit mission object changes from `durationSeconds` to
`duration_s`, wall time being the honest figure for a finished mission.

`planRunningTime` (7321 s in a report whose task ran 2904 s) is left unpublished: the
docs never define it and it does not correspond to any observed duration.

### 5.4 `interruptions_count`

No vendor field provides this, confirmed against both report APIs. It is connector
state: increment when the observed `taskState` transitions `RUNNING -> PAUSED`, reset
when `currentTask.taskInstanceId` changes. Counts vendor task-state transitions only;
e-stop is tracked separately by `emergency_stop`. Published in both the in-progress and
completed report data.

### 5.5 `task_outcome` from `taskEndStatus`

Today `_complete_mission` decides mission state purely from `completionPercentage`
against `mission_success_percentage_threshold`, plus a
`MISSION_PROGRESS_BAR_ADVANCED_PERCENTAGE_THRESHOLD = 0.90` progress-bar heuristic. It
ignores `taskEndStatus` entirely, so a task an operator stopped early is
indistinguishable from one that failed.

`taskEndStatus` is a documented enum (Task Report Push page): `-1` Unknown, `0` Normal,
`1` Manual, `2` Error, `3` Startup failure. New mapping:

| `taskEndStatus` | Coverage >= threshold | `task_outcome` / MissionState |
|---|---|---|
| `0` Normal | yes | `completed` |
| `0` Normal | no | `incomplete` |
| `1` Manual | yes | `completed` |
| `1` Manual | no | `abandoned` |
| `2` Error | any | `abandoned` |
| `3` Startup failure | any | `abandoned` |
| `-1` or absent | - | fall back to the current progress-bar plus threshold logic |
| report never found | - | `not_reported` (unchanged) |

The 0.90 progress-bar heuristic survives only in the `-1`/absent row. `task_outcome`
publishes the same four contract values the existing `MissionState` members already use,
so no new state vocabulary is introduced. The `Error` detail string for `incomplete`
missions is retained, and `abandoned` gains an analogous detail naming the vendor end
status.

Expected effect in practice: all 20 sample reports carry
`taskEndStatus: 1` at roughly 30 % coverage, so they stay `abandoned` but for a stated
reason rather than by heuristic.

### 5.6 Per-map breakdown, and why per-zone coverage is not filled

The contract carries per-zone coverage as flat scalars riding alongside the mission
fields (`zone_<slug>_planned_m2`, `zone_<slug>_actual_m2`, `zone_<slug>_pct`), so they
stay KPI-definable. Gausium supplies part of that shape and not the rest.

**Available and published.** `subTasks[]` breaks a task down per map, each entry carrying
`mapId`, `mapName`, `actualCleaningAreaSquareMeter` and `taskId`. For a multi-floor task
this is per-floor cleaned area. Published with the contract's grammar as
`map_<slug>_cleaned_area_m2`, one scalar key per sub-task, where `<slug>` is the map name
lowercased with each run of non-alphanumeric characters collapsed to `_` and leading and
trailing `_` stripped. If two map names slug identically, later ones get a numeric
suffix so no key is silently overwritten. On the sample report this yields a single
`map_target_cleaned_area_m2`-shaped key at `659.965`.

The dimension is named `map_`, not `zone_`, because a Gausium sub-task is a map or floor
rather than a spatial subdivision within one. Reusing `zone_` would collide with the
contract's meaning once true zones arrive.

**Not available.** Per-map *planned* area has no field, so per-map coverage percentage
cannot be computed and no `map_<slug>_pct` is published. No planned-area value is
synthesized from the task total: that would be an invented number wherever a task spans
more than one map, and adds nothing where it spans exactly one, since task-level
`coverage_pct` already covers that case.

**Zones proper.** `areaNameList` carries area *names* only, no per-area figures, and is
`""` on every sample report. It is published raw so the dimension exists the moment the
vendor populates it. Actual per-zone areas appear in no report field, and zone
definitions come from the subareas endpoint, which returns `partitions: []` on the sample
robot. So `zone_<slug>_*` stays unfilled for want of vendor data, not by choice: nothing
in this spec blocks it, and the per-map keys above are the same shape, so filling zones
later is an additional loop over a richer payload rather than a redesign.

### 5.7 `filter_truthy` must go

`mission.py` currently passes report data through `filter_truthy`, which drops any falsy
value. Under canonical keys that silently deletes `interruptions_count: 0`,
`water_used_l: 0.0`, `coverage_pct: 0` and every `false` boolean, giving KPI definitions
an unstable key set that appears and disappears per mission. Replace it with a filter
that drops `None` only.

## 6. Endpoints

### Added

| Endpoint | Purpose |
|---|---|
| `GET /v1alpha1/robots/{sn}/commands/{id}` | Command lifecycle state. Today `submit_task` and `task_command` report `CommandResultCode.SUCCESS` as soon as the POST is accepted. Capture the command id from the POST response, poll to a terminal state, report the real outcome. Response shape is unverified: the sample listing was `{"robotCommands": [], "total": "0"}` because no command had ever been issued, so the implementation must tolerate an unknown state vocabulary and time out rather than assume one |
| `POST /openapi-server/v1/api/task/report/map-images/query` | Verified working, returns `data[].url` per report. Feeds `report_map_image_urls` |

### Removed

| Endpoint / loop | Why |
|---|---|
| `_update_task_reports` (v1 `taskReports`, polled every 5 s) | `Robot.task_reports` is never read anywhere in the codebase. Pure waste. Note this is a different code path from the v2 report poll in `mission.py`, which stays |
| `_update_robot_details` (`bot.*/robot-task/robot/details/{sn}`, every 60 s) | 500 on both hosts, and its two key-values are removed per 3.1 |

### Verified dead, not adopted

| Endpoint | Observed |
|---|---|
| `GET /v1alpha1/robots/{sn}/statusReports` | Read timeout on the CN host, `{"reports": []}` on the US host. No uptime data exists to publish |
| `GET /robot-task/robot/details/statistics/{sn}` | `code 500` on both hosts |
| All V3 fusion and schedule APIs | `supportFusionTask: 0`, `supportTimerScheduleTask: 0` for `robotFamilyCode: "50"`; work modes `[]`, plans `[]`, schedule resources' regions/paths/positions all `[]` |
| `GET /openapi/v2alpha1/robots/{sn}/getSiteInfo` | `code 5, "The robot is not on a site."` |
| `GET /v1alpha1/robots/{sn}/maps/{mapId}` | `"Map: ... not found"` with both a map id and a map version id. The v2 map endpoint works and stays |

### Deferred by decision

| Endpoint | Reason |
|---|---|
| `POST /openapi/v1/map/robotMap/list` | Returns exactly one map, identical to the current one, with all geometry fields zero. Nothing to publish until a multi-map robot exists |
| `POST /openapi/v1/map/subareas/get` | Returns `partitions: []`. Would be the `submit_task` area catalog once areas are defined |
| Task Report Push and Incident Push webhooks | Planned as its own follow-up task, specified in section 11 |
| Batch status (`status:batchGet`) | Only relevant to a fleet-connector refactor, which the `claude/gausium-fleet-connector-6de7f6` branch already implements |
| Per-zone coverage (`zone_<slug>_*`) | Blocked on vendor data, not deferred by choice. No report field carries per-zone areas and the subareas endpoint returns `partitions: []`. The per-map breakdown that *is* available is published, see 5.6 |

## 7. Config as code

`gausium_open_platform_connector/cac_examples/` currently holds only
`RobotFootprint.yaml`, while the MiR, OTTO, Instock and legacy Gausium connectors all
ship datasource and mission-tracking examples. Added:

- `data_sources.yaml`: one DataSourceDefinition per live key-value from section 3, with
  `unit` and `scale` always explicit. Percent datasources set `scale: 1` because the
  values are already 0-1; omitting `scale` with `unit: "%"` makes the platform default to
  `0.01` and re-scale an already-normalized value. Includes the `mission_status`
  definition given verbatim in 3.4, which is a plain `keyValue` binding precisely because
  the connector now owns the derivation.
- `mission_tracking.yaml`: the `mission_tracking` DataSourceDefinition (`type: json`)
  plus the `MissionTracking` object with `processingType: [api]` and
  `autoClosePreviousMission: true`, following the legacy Gausium connector's shape.
- `status_definition.yaml`: `StatusDefinition` threshold rules over the numeric
  datasources worth surfacing in the Fleet Status widget, at minimum `battery_pct` and
  the two tank levels. This kind is **not** the Modes mapping: modes bind to the
  `mission_status` datasource and are configured in the InOrbit UI, as 3.4 explains.
- Three sample derived DataSourceDefinitions (`cleaned_area_m2`, `coverage_pct`,
  `efficiency_m2ph`) demonstrating the mission-field transform pattern, rather than all
  sixteen.
- `README.md` updated to list the files, and to state that applying
  `status_definition.yaml` requires toggling "display in Fleet Status" per status in
  Settings before the widget shows anything.

## 8. Implementation layers

Stacked PRs (gh-stack), based on `main`, each layer one scope. Paths are relative to
`gausium_open_platform_connector/inorbit_gausium_connector/`:

| # | Branch | Files | Content |
|---|---|---|---|
| 1 | `gausium/housekeeping` | `src/robot/robot.py`, `src/connector.py`, `config/connector_model.py` | Delete both dead polls and their key-values (3.1, 6). `map_resolution` config replaces the module constant (4). No new published data |
| 2 | `gausium/cleaning-mode-enum` | `src/mission.py` | Vendor-to-contract enum table and the `_raw` twin convention (5.1) |
| 3 | `gausium/canonical-key-values` | `src/connector.py`, `tests/test_connector.py` | Key-value rewrite: contract keys, additional keys, `mission_status` derivation (3.2-3.4) |
| 4 | `gausium/canonical-mission-data` | `src/mission.py` | Report `data` reshaped to canonical keys, per-map breakdown, `filter_truthy` replaced (5.2, 5.3, 5.6, 5.7). No state-logic change |
| 5 | `gausium/task-end-status` | `src/mission.py` | `task_outcome` from `taskEndStatus` (5.5). Isolated because it is the only behaviour change, so it can be reverted alone |
| 6 | `gausium/interruptions-count` | `src/mission.py` | Per-instance transition counter (5.4) |
| 7 | `gausium/command-feedback` | `src/robot/robot_api.py`, `src/connector.py` | Command-state polling and real result codes (6) |
| 8 | `gausium/report-map-images` | `src/robot/robot_api.py`, `src/mission.py` | Report map-images query and `report_map_image_urls` (6) |
| 9 | `gausium/cac-examples` | `../cac_examples/` | Section 7. Last, because it locks in the key names layers 3-8 settle |

Layers 7 and 8 are independent of 2-6 and could ship as standalone PRs off `main`
instead of riding the stack.

## 9. Feedback for the contract

Two corrections for the cleaning vertical initiative's Gausium mapping:

1. `battery_soh` is a **string** enum (observed `"HEALTHY"`), not a number. The contract
   lists it under numeric battery-health optionals.
2. `task_outcome` has a documented vendor source, `taskEndStatus`
   (`-1`/`0`/`1`/`2`/`3`), which the contract's "MissionState logic (`taskEndStatus` +
   threshold)" row names without giving the enum. The decoding in 5.5 should be the
   reference for other OEM mappings.

Also worth folding back: consumable wear is expressible as a unit-free ratio, so the
contract's "units not in Gausium docs, confirm with OEM" caveat on
`consumable_<part>_wear_pct` does not block the field.

## 10. Testing

The captured payloads become fixtures: `B1_status_v1.json`, `B2_status_v2_S.json`,
`C2_task_reports_v2_90d.json`.

| Layer | Check |
|---|---|
| 1 | Pose and `MapConfig` both read `map_resolution`; a non-default value moves published pose proportionally. Removed loops no longer start |
| 2 | Every table entry maps to its enum; an unseen vendor value yields `other` with the raw value preserved |
| 3 | The full key-value set from the sample status payloads, exact keys and values, including the 0-1 conversions and the seven generated consumable keys. `mission_status` precedence table, one case per row, including `IDLE` + `LOST` yielding `Idle` not `Error`; plus that it is always emitted and always within the closed five-value set, including on an empty or partial status payload |
| 4 | Report `data` matches the canonical set for a sample report; a report with `water_used_l: 0` and `interruptions_count: 0` keeps both keys. A two-sub-task report yields two `map_<slug>_cleaned_area_m2` keys; two maps slugging identically yield two distinct keys, not one overwritten |
| 5 | One case per row of the `task_outcome` table, including the `-1`/absent fallback and the no-report path |
| 6 | Counter increments only on `RUNNING -> PAUSED`, resets on a new `taskInstanceId` |
| 7 | Terminal state reported as success and failure; timeout path does not hang the command handler |
| 8 | URLs land in `report_map_image_urls`; a failing query does not break report completion |
| 9 | `cac_examples` YAML parses; ids match the keys layers 3-8 publish |

## 11. Follow-up task: push callbacks replacing polling

Not part of this work. Captured here because it changes how several things specified
above are sourced, and because the design decisions in sections 5 and 6 should not
foreclose it.

Gausium's Robot Push Service can POST to a callback URL we register, replacing polling
for the data it covers. Two subscriptions exist:

**Task Report Push.** Delivers a completed task report with the same field set as the
polled v2 `taskReports` response, wrapped as
`{appId, payload: {serialNumber, modelTypeCode, taskReport: {...}}}`.

**Incident Push.** Delivers robot incidents as
`{appId, payload: {serialNumber, modelTypeCode, content: {...}}}`, with `incidentCode`,
`incidentName`, `incidentLevel`, `incidentId`, `incidentStatus` (`1` alarm, `0` recover),
`startTime`, `endTime`, and the task and map context the incident occurred in (`taskId`,
`subTaskId`, `taskInstanceId`, `taskName`, `mapId`, `mapName`, `navInstanceId`,
`navName`). `incidentLevel` is a documented severity scale:

| Level | Meaning |
|---|---|
| H0 | Event notification, not an alarm |
| H1 | Buried point statistics |
| H2 | Routine robot state, user-resolvable without guidance |
| H3 | Warning, does not affect the task, user-resolvable |
| H4 | Affects the task, user-resolvable |
| H5 | Hidden danger, does not affect the task, not user-resolvable |
| H6 | Fault, affects the task, not user-resolvable |
| H7 | Quality issue, serious failure |

### What it replaces

| Polling | Push status |
|---|---|
| `_wait_for_task_report_async` in `mission.py`: polls `taskReports` every 0.5 s for up to 10 minutes after every mission ends | Fully replaceable by Task Report Push, and the biggest single reduction in API traffic this connector makes |
| Status polling for live key-values (section 3) | Not replaceable. There is no status push; the two status endpoints stay |
| Command state (section 6) | Not replaceable. No command push exists |

Incident Push replaces nothing: it is pure addition. No status field or report field
exposes incidents today, so this is an alerting surface the connector currently cannot
see at all.

### Constraints that shape the design

- **Push cannot be the only path.** Gausium documents no acknowledgement contract, no
  retry or backoff behaviour, no delivery guarantee and no signature verification for
  either callback. The report path must stay hybrid: push as the fast path, the existing
  poll as fallback after a timeout, so a dropped delivery degrades to today's behaviour
  rather than losing a mission.
- **Timestamps differ between transports.** The push payload sends `startTime` and
  `endTime` as epoch milliseconds (integers); the polled v2 API sends ISO 8601 strings.
  Report parsing must accept both. Section 5.3 derives `duration_s` from these fields, so
  keeping that derivation in one place, transport-agnostic, is what makes the push path a
  small change later rather than a second parser.
- **Inbound HTTP is new to this connector.** It is an outbound-only process today.
  A receiver means a listening port, TLS termination, and a route from the payload's
  `serialNumber` to the InOrbit robot id, which matters more once the connector is
  fleet-shaped.
- **Auth is a body-level `appId`**, not the OAuth bearer used everywhere else, so it
  becomes its own config secret. Registration of the URL and `appId` pair is done through
  Gausium, not through an API.
- **Documentation gap.** Subscriptions created or re-saved on or after 2025-05-15 are
  stated to carry new top-level fields alongside `appId` and `payload`, but the docs never
  enumerate them. A receiver should tolerate unknown top-level fields.
- The InOrbit surface for incidents (key-values, events, or both) is left to that task's
  own design.
