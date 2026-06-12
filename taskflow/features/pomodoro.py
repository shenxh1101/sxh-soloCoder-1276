from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from time import time
from typing import TYPE_CHECKING

from rich.bar import Bar

if TYPE_CHECKING:
    from taskflow.core.config import Config
    from taskflow.core.db import Database


@dataclass
class PomodoroSession:
    task_id: int
    start_time: datetime
    duration: int
    completed: bool


class PomodoroTimer:
    def __init__(self, db: Database, config: Config) -> None:
        self.db = db
        self.config = config
        self._session: PomodoroSession | None = None
        self._elapsed: int = 0
        self._running: bool = False
        self._paused: bool = False
        self._stop_event = threading.Event()
        self._pause_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._start_timestamp: float = 0.0
        self._pause_elapsed: int = 0

    @property
    def is_running(self) -> bool:
        return self._running and not self._paused

    @property
    def is_paused(self) -> bool:
        return self._running and self._paused

    def start(self, task_id: int) -> None:
        if self._running:
            raise RuntimeError("A pomodoro session is already running")

        duration = self.config.get("pomodoro_duration", 25) * 60
        self._session = PomodoroSession(
            task_id=task_id,
            start_time=datetime.now(),
            duration=duration,
            completed=False,
        )
        self._elapsed = 0
        self._running = True
        self._paused = False
        self._stop_event.clear()
        self._pause_event.set()
        self._start_timestamp = time()
        self._pause_elapsed = 0

        self._thread = threading.Thread(target=self._tick, daemon=True)
        self._thread.start()

    def cancel(self) -> None:
        if not self._running:
            return
        self._stop_event.set()
        self._pause_event.set()
        if self._thread is not None:
            self._thread.join(timeout=2)
        self._running = False
        self._paused = False
        self._session = None

    def pause(self) -> None:
        if not self._running or self._paused:
            return
        self._pause_elapsed = self.get_elapsed()
        self._paused = True
        self._pause_event.clear()

    def resume(self) -> None:
        if not self._running or not self._paused:
            return
        self._start_timestamp = time()
        self._paused = False
        self._pause_event.set()

    def get_elapsed(self) -> int:
        if not self._running:
            return self._elapsed
        if self._paused:
            return self._pause_elapsed
        current_elapsed = self._pause_elapsed + int(time() - self._start_timestamp)
        return current_elapsed

    def get_remaining(self) -> int:
        if self._session is None:
            return 0
        remaining = self._session.duration - self.get_elapsed()
        return max(remaining, 0)

    def _tick(self) -> None:
        while not self._stop_event.is_set():
            self._pause_event.wait(timeout=0.5)
            if self._stop_event.is_set():
                break
            if self._paused:
                continue

            elapsed = self.get_elapsed()
            self._elapsed = elapsed

            if self._session is not None and elapsed >= self._session.duration:
                self._session.completed = True
                self._running = False
                self.db.add_pomodoro_session(
                    task_id=self._session.task_id,
                    start_time=self._session.start_time,
                    duration=self._session.duration,
                    completed=True,
                )
                break


class PomodoroStats:
    def __init__(self, db: Database) -> None:
        self.db = db

    def get_daily_stats(self, days: int = 7) -> dict[date, int]:
        sessions = self.db.get_pomodoro_sessions()
        stats: dict[date, int] = {}
        today = date.today()
        for i in range(days):
            d = today - timedelta(days=i)
            stats[d] = 0

        for session in sessions:
            if not session.get("completed", False):
                continue
            session_date = session["start_time"].date() if isinstance(session["start_time"], datetime) else session["start_time"]
            if session_date in stats:
                stats[session_date] += session.get("duration", 0) // 60

        return stats

    def get_peak_hours(self, days: int = 30) -> dict[int, int]:
        sessions = self.db.get_pomodoro_sessions()
        cutoff = datetime.now() - timedelta(days=days)
        hours: dict[int, int] = {h: 0 for h in range(24)}

        for session in sessions:
            if not session.get("completed", False):
                continue
            start = session["start_time"]
            if not isinstance(start, datetime):
                continue
            if start < cutoff:
                continue
            hours[start.hour] += 1

        return hours

    def get_weekly_summary(self) -> dict:
        daily = self.get_daily_stats(days=7)
        total_minutes = sum(daily.values())
        avg_per_day = total_minutes / 7

        most_productive_day = max(daily, key=daily.get) if any(daily.values()) else None

        streak = 0
        today = date.today()
        for i in range(365):
            d = today - timedelta(days=i)
            if daily.get(d, 0) > 0 if d in daily else self._has_session_on(d):
                streak += 1
            else:
                if i > 0:
                    break

        return {
            "total_minutes": total_minutes,
            "avg_per_day": round(avg_per_day, 1),
            "most_productive_day": most_productive_day,
            "streak": streak,
        }

    def _has_session_on(self, d: date) -> bool:
        sessions = self.db.get_pomodoro_sessions()
        for session in sessions:
            if not session.get("completed", False):
                continue
            start = session["start_time"]
            session_date = start.date() if isinstance(start, datetime) else start
            if session_date == d:
                return True
        return False

    def format_stats_chart(self, days: int = 7) -> str:
        daily = self.get_daily_stats(days=days)
        max_minutes = max(daily.values()) if any(daily.values()) else 1

        lines: list[str] = []
        sorted_days = sorted(daily.keys(), reverse=True)

        for d in sorted_days:
            minutes = daily[d]
            bar_width = int((minutes / max_minutes) * 30) if max_minutes > 0 else 0
            bar = Bar(bar_width, max_width=30)
            lines.append(f"{d.strftime('%a %m/%d')} | {bar} {minutes}m")

        return "\n".join(lines)
