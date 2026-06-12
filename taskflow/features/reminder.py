from __future__ import annotations

import logging
import threading
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from taskflow.database import Database

logger = logging.getLogger(__name__)


class ReminderManager:
    def __init__(self, db: Database) -> None:
        self.db = db
        self._watcher_thread: threading.Thread | None = None
        self._stop_event = threading.Event()

    def check_reminders(self) -> list[dict]:
        now = datetime.now().isoformat()
        rows = self.db.execute(
            "SELECT r.id AS reminder_id, r.task_id, r.remind_at, t.title AS task_title "
            "FROM reminders r JOIN tasks t ON r.task_id = t.id "
            "WHERE r.remind_at <= ? AND r.dismissed = 0 "
            "ORDER BY r.remind_at",
            [now],
        ).fetchall()
        return [
            {
                "reminder_id": row["reminder_id"],
                "task_id": row["task_id"],
                "task_title": row["task_title"],
                "remind_at": row["remind_at"],
            }
            for row in rows
        ]

    def dismiss_reminder(self, reminder_id: int) -> None:
        self.db.execute("UPDATE reminders SET dismissed = 1 WHERE id = ?", [reminder_id])

    def schedule_reminder(self, task_id: int, remind_at: datetime) -> int:
        cursor = self.db.execute(
            "INSERT INTO reminders (task_id, remind_at, dismissed) VALUES (?, ?, 0)",
            [task_id, remind_at.isoformat()],
        )
        return cursor.lastrowid

    def send_notification(self, title: str, message: str) -> None:
        try:
            from plyer import notification

            notification.notify(title=title, message=message, app_name="TaskFlow", timeout=5)
        except Exception:
            print(f"[TaskFlow Reminder] {title}: {message}")

    def _watch_loop(self, interval_seconds: int) -> None:
        while not self._stop_event.is_set():
            try:
                reminders = self.check_reminders()
                for r in reminders:
                    self.send_notification("Task Reminder", f"{r['task_title']} - due now")
                    self.dismiss_reminder(r["reminder_id"])
            except Exception:
                logger.exception("error checking reminders")
            self._stop_event.wait(interval_seconds)

    def start_watching(self, interval_seconds: int = 60) -> None:
        if self._watcher_thread is not None and self._watcher_thread.is_alive():
            return
        self._stop_event.clear()
        self._watcher_thread = threading.Thread(
            target=self._watch_loop,
            args=(interval_seconds,),
            daemon=True,
        )
        self._watcher_thread.start()

    def stop_watching(self) -> None:
        self._stop_event.set()
        if self._watcher_thread is not None:
            self._watcher_thread.join(timeout=5)
            self._watcher_thread = None
