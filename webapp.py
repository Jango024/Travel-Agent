"""Flask based backend and web interface for the travel agent."""
from __future__ import annotations

import logging
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Any, Callable, Dict, Optional
from uuid import uuid4

import requests
from flask import Flask, jsonify, redirect, render_template, request, url_for

from agent_core import AgentResult, create_config_from_form, create_config_from_text, run_agent_workflow
from task_repository import TaskRecord, TaskRepository

LOGGER = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

app = Flask(__name__)


class TelegramNotifier:
    def __init__(self, token: Optional[str]) -> None:
        self.token = token

    def send_message(self, chat_id: str, text: str) -> None:
        if not self.token:
            LOGGER.info("Skipping Telegram notification (token missing).")
            return
        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        try:
            response = requests.post(url, json={"chat_id": chat_id, "text": text}, timeout=10)
            response.raise_for_status()
        except requests.RequestException as exc:  # pragma: no cover - network safeguard
            LOGGER.error("Failed to deliver Telegram message: %s", exc)


class TaskManager:
    def __init__(self, repository: TaskRepository) -> None:
        self.executor = ThreadPoolExecutor(max_workers=4)
        self.repository = repository

    def submit(
        self,
        config_data: Dict[str, Any],
        run_fn: Callable[[], AgentResult],
        metadata: Optional[Dict[str, Any]] = None,
        completion: Optional[Callable[[TaskRecord], None]] = None,
    ) -> TaskRecord:
        task_id = uuid4().hex
        record = TaskRecord(
            id=task_id,
            status="queued",
            created_at=datetime.utcnow(),
            config_payload=config_data,
            metadata=metadata or {},
        )

        def _runner() -> None:
            self._update_status(task_id, "running")
            try:
                result = run_fn()
                self._update_result(task_id, result)
                if completion:
                    current = self.get(task_id)
                    if current:
                        completion(current)
            except Exception as exc:  # pragma: no cover - runtime safeguard
                LOGGER.exception("Task %s failed", task_id)
                self._update_error(task_id, str(exc))
                if completion:
                    current = self.get(task_id)
                    if current:
                        completion(current)

        self.repository.create_task(record)
        self.executor.submit(_runner)
        return record

    def _update_status(self, task_id: str, status: str) -> None:
        self.repository.update_status(task_id, status)

    def _update_result(self, task_id: str, result: AgentResult) -> None:
        self.repository.update_result(task_id, result.to_dict())

    def _update_error(self, task_id: str, message: str) -> None:
        self.repository.update_error(task_id, message)

    def get(self, task_id: str) -> Optional[TaskRecord]:
        return self.repository.get(task_id)


task_repository = TaskRepository(os.getenv("TASK_DB_PATH", os.path.join(os.getcwd(), "tasks.db")))
task_manager = TaskManager(task_repository)
telegram_notifier = TelegramNotifier(os.getenv("TELEGRAM_BOT_TOKEN"))


@app.route("/")
def index() -> str:
    return render_template("index.html")


@app.route("/run", methods=["POST"])
def run_from_form():
    form_data = request.form.to_dict(flat=False)
    flat_data = {key: values if len(values) > 1 else values[0] for key, values in form_data.items()}
    config = create_config_from_form(flat_data)

    def _run() -> AgentResult:
        return run_agent_workflow(config)

    record = task_manager.submit(config.to_dict(), _run)
    return redirect(url_for("status_page", task_id=record.id))


@app.route("/status/<task_id>")
def status_page(task_id: str) -> str:
    task = task_manager.get(task_id)
    if not task:
        return render_template("status.html", task_id=task_id, task=None)
    return render_template("status.html", task_id=task_id, task=task.to_dict())


@app.route("/api/status/<task_id>")
def task_status(task_id: str):
    task = task_manager.get(task_id)
    if not task:
        return jsonify({"error": "unknown task"}), 404
    return jsonify(task.to_dict())


@app.route("/api/run-from-bot", methods=["POST"])
def run_from_bot():
    payload = request.get_json(force=True) or {}
    message = payload.get("message")
    chat_id = payload.get("chat_id")
    if not message or not chat_id:
        return jsonify({"error": "message and chat_id required"}), 400

    config = create_config_from_text(str(message))

    def _run() -> AgentResult:
        return run_agent_workflow(config)

    def _notify(record: TaskRecord) -> None:
        if record.status == "finished" and record.result:
            report_text = record.result.get("report") if isinstance(record.result, dict) else getattr(record.result, "report", None)
            if report_text:
                telegram_notifier.send_message(chat_id, report_text)
        elif record.status == "failed":
            telegram_notifier.send_message(chat_id, f"Die Suche ist fehlgeschlagen: {record.error}")

    record = task_manager.submit(
        config.to_dict(),
        _run,
        metadata={"source": "telegram", "chat_id": chat_id},
        completion=_notify,
    )
    status_url = url_for("task_status", task_id=record.id, _external=True)
    return jsonify({"task_id": record.id, "status_url": status_url})


if __name__ == "__main__":
    app.run(debug=True)
