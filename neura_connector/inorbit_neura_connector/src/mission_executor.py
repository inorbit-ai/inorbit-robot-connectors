"""Mission executor — runs multi-step missions.

A mission definition is a JSON object:
{
  "name": "Sample Mission",
  "actions": [
    {"type": "drive_to", "params": {"point_id": 5}, "on_failure": "abort"},
    {"type": "extend_lifting", "params": {}, "on_failure": "retry", "max_retries": 3, "retry_delay": 5},
    {"type": "drive_to", "params": {"point_id": 12}},
    {"type": "retract_lifting", "params": {}}
  ]
}

on_failure per action:
  - "abort"  (default) — stop the mission immediately
  - "retry"  — retry up to max_retries times, then abort
"""

import asyncio
import logging
import time
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger(__name__)

MISSION_STATE_EXECUTING = "Executing"
MISSION_STATE_DONE = "Done"
MISSION_STATE_ABORTED = "Aborted"
MISSION_STATE_PAUSED = "Paused"

DEFAULT_MAX_RETRIES = 3
DEFAULT_RETRY_DELAY = 5.0


class MissionExecutor:
    """Executes multi-step missions against a robot API."""

    def __init__(self, api, publish_fn: Callable):
        """
        Args:
            api: Robot API (NexusApi or NeurapyMavApi) with async command methods.
            publish_fn: callable(key_values, is_event) to report mission state to InOrbit.
        """
        self._api = api
        self._publish = publish_fn
        self._current_mission: Optional[Dict] = None
        self._cancel_event = asyncio.Event()
        self._pause_event = asyncio.Event()
        self._pause_event.set()  # not paused initially
        self._task: Optional[asyncio.Task] = None

    @property
    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def execute(self, mission_id: str, definition: Dict, args: Dict) -> None:
        if self.is_running:
            raise RuntimeError("A mission is already running — cancel it first")

        self._cancel_event.clear()
        self._pause_event.set()
        self._current_mission = {
            "id": mission_id,
            "definition": definition,
            "args": args,
            "state": MISSION_STATE_EXECUTING,
            "start_ts": time.time() * 1000,
        }
        self._task = asyncio.create_task(self._run())

    async def cancel(self) -> None:
        if not self.is_running:
            return
        logger.info(f"Cancelling mission {self._current_mission['id']}")
        self._cancel_event.set()
        self._pause_event.set()  # unblock if paused
        await self._task

    async def pause(self) -> None:
        if not self.is_running:
            return
        logger.info(f"Pausing mission {self._current_mission['id']}")
        self._pause_event.clear()
        self._report(state=MISSION_STATE_PAUSED)
        try:
            await self._api.pause_drive()
        except Exception:
            pass

    async def resume(self) -> None:
        if not self.is_running:
            return
        logger.info(f"Resuming mission {self._current_mission['id']}")
        self._pause_event.set()
        self._report(state=MISSION_STATE_EXECUTING)
        try:
            await self._api.resume_drive()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Internal execution loop
    # ------------------------------------------------------------------

    async def _run(self):
        mission = self._current_mission
        actions = mission["definition"].get("actions", [])
        total = len(actions)
        mission_name = mission["definition"].get("name", mission["id"])

        logger.info(f"Mission '{mission_name}' started — {total} actions")
        self._report(state=MISSION_STATE_EXECUTING, completed=0.0)

        for idx, action in enumerate(actions):
            if self._cancel_event.is_set():
                self._finish(MISSION_STATE_ABORTED, f"Cancelled before step {idx + 1}")
                return

            await self._pause_event.wait()
            if self._cancel_event.is_set():
                self._finish(MISSION_STATE_ABORTED, "Cancelled while paused")
                return

            action_type = action.get("type", "unknown")
            params = action.get("params", {})
            on_failure = action.get("on_failure", "abort")
            max_retries = int(action.get("max_retries", DEFAULT_MAX_RETRIES))
            retry_delay = float(action.get("retry_delay", DEFAULT_RETRY_DELAY))

            success = await self._execute_action(
                idx, total, action_type, params, on_failure, max_retries, retry_delay
            )

            if not success:
                self._finish(MISSION_STATE_ABORTED, f"Step {idx + 1} ({action_type}) failed")
                return

            self._report(
                state=MISSION_STATE_EXECUTING,
                completed=(idx + 1) / total,
            )

        self._finish(MISSION_STATE_DONE)

    async def _execute_action(
        self, idx: int, total: int, action_type: str, params: Dict,
        on_failure: str, max_retries: int, retry_delay: float,
    ) -> bool:
        attempt = 0
        while True:
            attempt += 1
            try:
                logger.info(
                    f"  [{idx + 1}/{total}] {action_type} "
                    f"(attempt {attempt}{'/' + str(max_retries) if on_failure == 'retry' else ''})"
                )
                await self._dispatch(action_type, params)
                return True

            except Exception as exc:
                logger.error(f"  [{idx + 1}/{total}] {action_type} failed: {exc}")

                if self._cancel_event.is_set():
                    return False

                if on_failure == "retry" and attempt < max_retries:
                    logger.info(f"  Retrying in {retry_delay}s...")
                    try:
                        await asyncio.wait_for(
                            self._cancel_event.wait(), timeout=retry_delay
                        )
                        return False  # cancel was set during wait
                    except asyncio.TimeoutError:
                        continue
                else:
                    return False

    async def _dispatch(self, action_type: str, params: Dict) -> Any:
        """Map action type strings to API calls."""
        if action_type == "drive_to":
            return await self._api.drive_to(
                int(params.get("point_id", 0)),
                float(params.get("timeout", 180)),
            )
        elif action_type == "abort_drive":
            return await self._api.abort_drive()
        elif action_type == "pause_drive":
            return await self._api.pause_drive()
        elif action_type == "resume_drive":
            return await self._api.resume_drive()
        elif action_type == "extend_lifting":
            return await self._api.extend_lifting_units(
                float(params.get("timeout", 60))
            )
        elif action_type == "retract_lifting":
            return await self._api.retract_lifting_units(
                float(params.get("timeout", 60))
            )
        elif action_type == "lock_amr":
            return await self._api.lock_amr()
        elif action_type == "release_amr":
            return await self._api.release_amr()
        elif action_type == "reset":
            return await self._api.reset(
                float(params.get("timeout", 30))
            )
        elif action_type == "soft_estop":
            active = str(params.get("active", "true")).lower() == "true"
            return await self._api.set_navitrol_soft_estop(active)
        else:
            raise ValueError(f"Unknown action type: {action_type}")

    # ------------------------------------------------------------------
    # Reporting
    # ------------------------------------------------------------------

    def _report(self, state: str, completed: float = None):
        mission = self._current_mission
        values = {
            "missionId": mission["id"],
            "inProgress": state == MISSION_STATE_EXECUTING or state == MISSION_STATE_PAUSED,
            "state": state,
            "label": mission["definition"].get("name", mission["id"]),
            "startTs": mission["start_ts"],
        }
        if completed is not None:
            values["completedPercent"] = completed
        self._publish(key_values={"mission_tracking": values}, is_event=True)

    def _finish(self, state: str, error_detail: str = None):
        mission = self._current_mission
        end_ts = time.time() * 1000
        values = {
            "missionId": mission["id"],
            "inProgress": False,
            "state": state,
            "label": mission["definition"].get("name", mission["id"]),
            "startTs": mission["start_ts"],
            "endTs": end_ts,
            "completedPercent": 1.0 if state == MISSION_STATE_DONE else None,
            "status": "OK" if state == MISSION_STATE_DONE else "error",
        }
        if error_detail:
            values["data"] = {"error": error_detail}
        self._publish(key_values={"mission_tracking": values}, is_event=True)

        logger.info(f"Mission '{mission['id']}' finished — {state}"
                     + (f": {error_detail}" if error_detail else ""))
        self._current_mission = None
