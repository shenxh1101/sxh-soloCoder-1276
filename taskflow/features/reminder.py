from __future__ import annotations

import logging
import threading
from datetime import datetime

from taskflow.db import Database
from taskflow.db.models import Reminder, Task

logger = logging.getLogger(__name__)


class ReminderManager:
    def __init__(self, db: Database) -> None:
        self.db = db
        self._watcher_thread: threading.Thread | None = None
        self._stop_event = threading.Event()

    def check_reminders(self) -> list[dict]:
        reminders = self.db.get_pending_reminders()
        result: list[dict] = []
        for r in reminders:
            task = self.db.get_task(r.task_id) if r.task_id is not None else None
            task_title = task.title if task else ""
            result.append({
                "reminder_id": r.id,
                "task_id": r.task_id,
                "task_title": task_title,
                "remind_at": r.remind_at,
            })
        return result

    def dismiss_reminder(self, reminder_id: int) -> None:
        self.db.dismiss_reminder(reminder_id)

    def schedule_reminder(self, task_id: int, remind_at: datetime) -> int:
        reminder = Reminder(
            task_id=task_id,
            remind_at=remind_at.isoformat(),
            dismissed=False,
        )
        return self.db.create_reminder(reminder)

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
