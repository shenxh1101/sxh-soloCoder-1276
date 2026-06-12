from __future__ import annotations

import threading
from datetime import date, datetime, timedelta
from time import time
from typing import TYPE_CHECKING, Optional, Tuple

from rich.bar import Bar

from taskflow.db import Database
from taskflow.config import Config
from taskflow.db.models import PomodoroSession

if TYPE_CHECKING:
    pass


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
        self._duration_seconds: int = 0

    @property
    def is_running(self) -> bool:
        return self._running and not self._paused

    @property
    def is_paused(self) -> bool:
        return self._running and self._paused

    def start(self, task_id: int) -> None:
        if self._running:
            raise RuntimeError("A pomodoro session is already running")

        duration_minutes = self.config.pomodoro_duration
        self._duration_seconds = duration_minutes * 60
        self._session = PomodoroSession(
            task_id=task_id,
            started_at=datetime.now().isoformat(),
            duration_minutes=duration_minutes,
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
        remaining = self._duration_seconds - self.get_elapsed()
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

            if self._session is not None and elapsed >= self._duration_seconds:
                self._session.completed = True
                self._running = False
                self.db.add_pomodoro_session(self._session)
                break


class PomodoroStats:
    def __init__(self, db: Database) -> None:
        self.db = db

    def _week_range(self, ref_date: Optional[date] = None) -> Tuple[date, date]:
        if ref_date is None:
            ref_date = date.today()
        week_start = ref_date - timedelta(days=ref_date.weekday())
        week_end = week_start + timedelta(days=6)
        return week_start, week_end

    def get_daily_stats(self, days: int = 7) -> dict[date, int]:
        sessions = self.db.get_pomodoro_sessions()
        stats: dict[date, int] = {}
        today = date.today()
        for i in range(days):
            d = today - timedelta(days=i)
            stats[d] = 0

        for session in sessions:
            if session.get("completed", 0) != 1:
                continue
            started_at_str = session.get("started_at")
            if not started_at_str:
                continue
            try:
                start_dt = datetime.fromisoformat(started_at_str)
            except (ValueError, TypeError):
                continue
            session_date = start_dt.date()
            if session_date in stats:
                stats[session_date] += session.get("duration_minutes", 0)

        return stats

    def get_peak_hours(self, days: int = 30) -> dict[int, int]:
        sessions = self.db.get_pomodoro_sessions()
        cutoff = datetime.now() - timedelta(days=days)
        hours: dict[int, int] = {h: 0 for h in range(24)}

        for session in sessions:
            if session.get("completed", 0) != 1:
                continue
            started_at_str = session.get("started_at")
            if not started_at_str:
                continue
            try:
                start = datetime.fromisoformat(started_at_str)
            except (ValueError, TypeError):
                continue
            if start < cutoff:
                continue
            hours[start.hour] += 1

        return hours

    def get_weekly_summary(self) -> dict:
        week_start, week_end = self._week_range()
        start_str = week_start.isoformat()
        end_str = f"{week_end.isoformat()}T23:59:59"

        sessions = self.db.query_all(
            "SELECT * FROM pomodoro_sessions WHERE completed = 1 AND started_at >= ? AND started_at <= ?",
            (start_str, end_str),
        )

        total_minutes = sum(s.get("duration_minutes", 0) for s in sessions)

        per_day: dict[date, int] = {}
        d = week_start
        while d <= week_end:
            per_day[d] = 0
            d += timedelta(days=1)

        for session in sessions:
            started_at_str = session.get("started_at")
            if not started_at_str:
                continue
            try:
                start_dt = datetime.fromisoformat(started_at_str)
            except (ValueError, TypeError):
                continue
            session_date = start_dt.date()
            if session_date in per_day:
                per_day[session_date] += session.get("duration_minutes", 0)

        avg_per_day = total_minutes / 7
        most_productive_day = max(per_day, key=per_day.get) if any(per_day.values()) else None

        streak = 0
        today = date.today()
        all_sessions = self.db.get_pomodoro_sessions()
        for i in range(365):
            d = today - timedelta(days=i)
            found = False
            for session in all_sessions:
                if session.get("completed", 0) != 1:
                    continue
                started_at_str = session.get("started_at")
                if not started_at_str:
                    continue
                try:
                    start = datetime.fromisoformat(started_at_str)
                except (ValueError, TypeError):
                    continue
                if start.date() == d:
                    found = True
                    break
            if found:
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

    def get_this_week_stats(self) -> dict:
        week_start, week_end = self._week_range()
        start_str = week_start.isoformat()
        end_str = f"{week_end.isoformat()}T23:59:59"

        sessions = self.db.query_all(
            "SELECT * FROM pomodoro_sessions WHERE completed = 1 AND started_at >= ? AND started_at <= ?",
            (start_str, end_str),
        )

        total_sessions = len(sessions)
        total_minutes = sum(s.get("duration_minutes", 0) for s in sessions)

        per_task_rows = self.db.query_all(
            "SELECT p.task_id, t.title, COUNT(*) AS sessions, SUM(p.duration_minutes) AS minutes "
            "FROM pomodoro_sessions p JOIN tasks t ON p.task_id = t.id "
            "WHERE p.completed = 1 AND p.started_at >= ? AND p.started_at <= ? "
            "GROUP BY p.task_id ORDER BY minutes DESC",
            (start_str, end_str),
        )

        per_task = []
        for row in per_task_rows:
            per_task.append({
                "task_id": row["task_id"],
                "title": row["title"],
                "sessions": row["sessions"],
                "minutes": row["minutes"] or 0,
            })

        day_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        per_day: dict[str, int] = {name: 0 for name in day_names}

        for session in sessions:
            started_at_str = session.get("started_at")
            if not started_at_str:
                continue
            try:
                start_dt = datetime.fromisoformat(started_at_str)
            except (ValueError, TypeError):
                continue
            weekday_idx = start_dt.weekday()
            per_day[day_names[weekday_idx]] += session.get("duration_minutes", 0)

        return {
            "week_start": week_start.isoformat(),
            "week_end": week_end.isoformat(),
            "total_sessions": total_sessions,
            "total_minutes": total_minutes,
            "per_task": per_task,
            "per_day": per_day,
        }

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
