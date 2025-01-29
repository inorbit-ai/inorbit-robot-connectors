import json
from typing import List

import aiosql
import aiosqlite
from logger import setup_logger
from missions.datatypes import MissionWorkerState
from missions.db import WorkerPersistenceDB

logger = setup_logger(name="SQLiteBackend")

# Queries for aiosql. For more information about queries and parsing results, see:
# https://gist.github.com/petrilli/81511edd88db935d17af0ec271ed950b

# noqa: E501
SQL_QUERIES = """
--- name: initialize_missions_table
CREATE TABLE IF NOT EXISTS missions (
  mission_id TEXT PRIMARY KEY,
  state TEXT,
  finished BOOL NOT NULL,
  robot_id TEXT,
  paused BOOL NOT NULL
);

-- name: get-mission
-- Gets a mission state from the db
SELECT mission_id, state, robot_id FROM missions WHERE mission_id=:mission_id;

-- name: get-all-missions
-- Gets ALL mission states from DB (used during startup)
SELECT mission_id, state, robot_id FROM missions;

-- name: get-all-finished-and-paused-missions
-- Gets ALL mission states from DB for a given 'finished' flag (normally False, unfinished)
-- and 'paused' flag (normally False, unpaused)
SELECT mission_id, state, robot_id FROM missions WHERE finished = :finished and paused = :paused;

-- name: save-mission
-- Gets ALL mission states from DB (used during startup)
INSERT OR REPLACE INTO missions ("mission_id", "state", "finished", "robot_id", "paused")
  VALUES (:mission_id, :state, :finished, :robot_id, :paused)

-- name: get-robot-active-mission
-- Gets a mission state from the db
SELECT mission_id FROM missions WHERE robot_id=:robot_id and finished = false;

-- name: delete-mission
-- Deletes a mission from the db
DELETE FROM missions WHERE mission_id=:mission_id;

-- name: delete-finished-missions
-- Deletes all finished missions from the db
DELETE FROM missions WHERE finished = true;

"""  # noqa: E501
queries = aiosql.from_str(SQL_QUERIES, "aiosqlite")


def parse_row(row):
    id: str = row["mission_id"]
    state: str = row["state"]
    robot_id: str = row["robot_id"]
    return {"mission_id": id, "state": json.loads(state), "robot_id": robot_id}


class SqliteDB(WorkerPersistenceDB):
    def __init__(self, filename):
        self.filename = filename
        self.db = None
        logger.info(f"Constructing sqlite3 db {self.filename}")

    async def connect(self):
        if self.db:
            return  # nothing to do
        try:
            self.db = await aiosqlite.connect(self.filename)
            self.db.row_factory = aiosqlite.Row
            await self.initialize_tables()
        except Exception as e:
            logger.error(f"Could not connect to DB {self.filename}")
            raise e

    async def shutdown(self):
        if self.db:
            db = self.db
            self.db = None  # make db immediately  unavailable for any other thread
            await db.close()

    async def initialize_tables(self):
        await queries.initialize_missions_table(self.db)
        await self.add_paused_field_migration()

    async def add_paused_field_migration(self):
        """
        This migration was created after implementing pause/resume in the service.
        If the missions table doesn't have the "paused" field, it creates a new table with
        "paused" as not nullable field and renames it to "missions", also initalizes all the
        paused columns with a 0 (0 = BOOL False)
        """
        # Create a cursor object
        cursor = await self.db.cursor()
        missions_table = "missions"
        temp_missions_table = "temp_missions"
        paused_column = "paused"
        # Check if the column exists in the missions table
        await cursor.execute(f"PRAGMA table_info({missions_table})")
        columns = [column[1] for column in await cursor.fetchall()]
        if paused_column not in columns:
            # If the column doesn't exist, create a new table with the column field
            # NOTE (Elvio): Creating a new table here and migrating data to it because
            # in sqlite it's not possible to create a new "NOT NULL" field on already existing
            # table (paused column)
            await cursor.execute(
                f"""
                CREATE TABLE {temp_missions_table} (
                  "mission_id"	TEXT,
                  "state"	TEXT,
                  "finished"	BOOL NOT NULL,
                  "robot_id"	TEXT,
                  "paused"	BOOL NOT NULL,
                  PRIMARY KEY("mission_id")
                );
                """
            )
            await cursor.execute(
                f"""
                INSERT INTO {temp_missions_table} (mission_id, state, finished, robot_id, paused)
                SELECT mission_id, state, finished, robot_id, 0 FROM {missions_table};
                """
            )
            await cursor.execute(f"DROP TABLE {missions_table};")
            await cursor.execute(f"ALTER TABLE {temp_missions_table} RENAME TO {missions_table};")
            # Commit the changes
            await self.db.commit()

    async def fetch_mission(self, mission_id) -> MissionWorkerState:
        mission_row = await queries.get_mission(self.db, mission_id=mission_id)
        if not len(mission_row):
            return None
        try:
            return MissionWorkerState.model_validate(parse_row(mission_row[0]))
        except Exception as e:
            logger.warning("Cannot parse row object", e)
            return None

    async def save_mission(self, mission: MissionWorkerState):
        if not self.db or not self.db.is_alive():
            # This may happen during shutdown. Instead of throwing an exception to logs (or
            # to swallow the error) let's just log a warning. If the warning appears in logs
            # after App shutdown msgs, we know they are not serious
            logger.warning("Attempt to save mission state without a DB connection; ignored")
        await queries.save_mission(
            self.db,
            mission_id=mission.mission_id,
            robot_id=mission.robot_id,
            state=json.dumps(mission.state),
            finished=mission.finished,
            paused=mission.paused,
        )
        await self.db.commit()

    async def fetch_all_missions(self, finished=None, paused=None) -> List[MissionWorkerState]:
        """
        Loads all mission rows from db (optionally, only missions finished/unfinished
        """
        if finished is None and paused is None:
            missions = await queries.get_all_missions(self.db)
        else:
            missions = await queries.get_all_finished_and_paused_missions(
                self.db, finished=finished, paused=paused
            )
        # Parse JSON from them (doing this manually, until we find a better JSON support)
        missions_docs = []
        for m in missions:
            try:
                row = parse_row(m)
                doc = MissionWorkerState.model_validate(row)
                missions_docs.append(doc)
            except Exception as e:
                logger.error(e)
                try:
                    logger.error(f"Removing mission {m['mission_id']}")
                    await self.delete_mission(m["mission_id"])
                except Exception as ex:
                    logger.error(ex)
        return missions_docs

    async def fetch_robot_active_mission(self, robot_id: str):
        """
        Returns the id of the mission being currently executed by a robot if any
        """
        mission_row = await queries.get_robot_active_mission(self.db, robot_id=robot_id)
        if len(mission_row) == 0:
            return None
        return mission_row[0]["mission_id"]

    async def delete_mission(self, mission_id: str):
        """
        Deletes a mission from the DB
        """
        await queries.delete_mission(self.db, mission_id=mission_id)
        await self.db.commit()

    async def delete_finished_missions(self):
        """
        Deletes all finished missions from the DB
        """
        await queries.delete_finished_missions(self.db)
        await self.db.commit()

    # async def set_bluebotics_mission_id(
    #     self, bluebotics_mission_id: str, inorbit_mission_id: str
    # ) -> None:
    #     """
    #     Sets the bluebotics mission id in the DB

    #     Args:
    #         bluebotics_mission_id (str): The bluebotics mission id to be set in the DB

    #     Returns:
    #         None
    #     """
    #     await queries.set_bluebotics_mission_id(
    #         self.db, bluebotics_mission_id=bluebotics_mission_id, mission_id=inorbit_mission_id
    #     )
    #     await self.db.commit()

    # async def get_bluebotics_mission_id(self, mission_id: str) -> str:
    #     """
    #     Gets the bluebotics mission id from the DB

    #     Returns:
    #         str: The bluebotics mission id
    #     """
    #     mission_row = await queries.get_mission(self.db, mission_id=mission_id)
    #     if len(mission_row) == 0:
    #         return None
    #     return mission_row[0]["bluebotics_mission_id"]
