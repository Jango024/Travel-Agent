"""SQLite-backed persistence for background task records."""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional


@dataclass
class TaskRecord:
    """Internal representation of a long running task."""

    id: str
    status: str
    created_at: datetime
    config_payload: Dict[str, Any]
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Serialise the task into a JSON-ready structure."""

        return {
            "id": self.id,
            "status": self.status,
            "created_at": self.created_at.isoformat(),
            "config": self.config_payload,
            "error": self.error,
            "metadata": self.metadata,
            "result": self.result,
        }


class TaskRepository:
    """SQLite backed persistence for :class:`TaskRecord` objects."""

    def __init__(self, database: str) -> None:
        self.database = database
        db_path = Path(database)
        if db_path.parent and not db_path.parent.exists():
            db_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database)
        connection.row_factory = sqlite3.Row
        return connection

    def _ensure_schema(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    config TEXT NOT NULL,
                    result TEXT,
                    error TEXT,
                    metadata TEXT NOT NULL
                )
                """
            )

    def create_task(self, record: TaskRecord) -> None:
        payload = (
            record.id,
            record.status,
            record.created_at.isoformat(),
            json.dumps(record.config_payload),
            json.dumps(record.result) if record.result is not None else None,
            record.error,
            json.dumps(record.metadata or {}),
        )
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO tasks (id, status, created_at, config, result, error, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                payload,
            )

    def update_status(self, task_id: str, status: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE tasks SET status = ? WHERE id = ?",
                (status, task_id),
            )

    def update_result(self, task_id: str, result: Dict[str, Any]) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE tasks SET status = ?, result = ?, error = NULL WHERE id = ?",
                ("finished", json.dumps(result), task_id),
            )

    def update_error(self, task_id: str, message: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE tasks SET status = ?, error = ?, result = NULL WHERE id = ?",
                ("failed", message, task_id),
            )

    def get(self, task_id: str) -> Optional[TaskRecord]:
        with self._connect() as connection:
            cursor = connection.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
            row = cursor.fetchone()
        if not row:
            return None
        return TaskRecord(
            id=row["id"],
            status=row["status"],
            created_at=datetime.fromisoformat(row["created_at"]),
            config_payload=json.loads(row["config"]),
            result=json.loads(row["result"]) if row["result"] else None,
            error=row["error"],
            metadata=json.loads(row["metadata"]) if row["metadata"] else {},
        )
