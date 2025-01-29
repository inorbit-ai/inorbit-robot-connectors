# Mission execution logic
from __future__ import annotations

from typing import Any
from typing import Dict
from typing import List
from typing import Union

from inorbit_mir_connector.src.missions.datatypes import MissionDefinition
from inorbit_mir_connector.src.missions.datatypes import MissionTask
from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field
from pydantic import model_validator
from typing_extensions import Self


class Mission(BaseModel):
    """
    Represents a (parsed) mission. It includes the definition, the runtime arguments and tasks.
    The object is serializable
    """

    id: str
    robot_id: str
    definition: MissionDefinition
    arguments: Union[Dict[str, Any], None] = Field(default=None)
    tasks_list: List[MissionTask] = Field(default=None)  # Derived from 'definition'
    model_config = ConfigDict(extra="forbid")

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)  # Let Pydantic initialize fields from constructor args
        if not self.tasks_list:  # if not coming from a serialized version
            # TODO make another public constructor instead of this hack
            self.tasks_list = self._build_tasks(self.definition)
        pass

    def _build_tasks(self, mission_definition: MissionDefinition) -> List[MissionTask]:
        tasks = [
            MissionTask(taskId=s.complete_task, label=s.complete_task)
            for s in mission_definition.steps
            if s.complete_task is not None
        ]
        return tasks

    def find_task(self, task_id):
        return next((task for task in self.tasks_list if task.task_id == task_id), None)

    def mark_task_completed(self, task_id):
        # task = self._tasks.get(task_id)
        task = self.find_task(task_id)
        if task is None:
            return
        task.completed = True
        task.in_progress = False

    def mark_task_in_progress(self, task_id):
        # task = self._tasks.get(task_id)
        task = self.find_task(task_id)
        if task is None:
            return
        task.in_progress = True

    @model_validator(mode="after")
    def validate(self) -> Self:
        # TO be overloaded by the child classes.
        return self
