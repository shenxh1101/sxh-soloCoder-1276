import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .models import (
    Attachment,
    Note,
    PomodoroSession,
    Project,
    Reminder,
    Subtask,
    Tag,
    Task,
    TaskTag,
)

DB_DIR = Path.home() / ".taskflow"
DB_PATH = DB_DIR / "taskflow.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL DEFAULT '',
    parent_id INTEGER,
    sort_order INTEGER NOT NULL DEFAULT 0,
    color TEXT,
    collapsed INTEGER NOT NULL DEFAULT 0,
    created_at TEXT,
    updated_at TEXT,
    FOREIGN KEY (parent_id) REFERENCES projects(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL DEFAULT '',
    project_id INTEGER,
    status TEXT NOT NULL DEFAULT 'todo',
    priority TEXT,
    due_date TEXT,
    due_time TEXT,
    reminder_minutes_before INTEGER,
    completed_at TEXT,
    created_at TEXT,
    updated_at TEXT,
    sort_order INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS subtasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    done INTEGER NOT NULL DEFAULT 0,
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at TEXT,
    FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS tags (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL DEFAULT '',
    color TEXT
);

CREATE TABLE IF NOT EXISTS task_tags (
    task_id INTEGER NOT NULL,
    tag_id INTEGER NOT NULL,
    PRIMARY KEY (task_id, tag_id),
    FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE,
    FOREIGN KEY (tag_id) REFERENCES tags(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS attachments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER NOT NULL,
    name TEXT NOT NULL DEFAULT '',
    path_or_url TEXT NOT NULL DEFAULT '',
    created_at TEXT,
    FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER NOT NULL,
    content TEXT NOT NULL DEFAULT '',
    created_at TEXT,
    updated_at TEXT,
    FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS pomodoro_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER NOT NULL,
    started_at TEXT,
    duration_minutes INTEGER NOT NULL DEFAULT 25,
    completed INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS reminders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER NOT NULL,
    remind_at TEXT,
    dismissed INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE
);
"""


def _now() -> str:
    return datetime.now().isoformat()


def _row_to_project(row: sqlite3.Row) -> Project:
    return Project(
        id=row["id"],
        name=row["name"],
        parent_id=row["parent_id"],
        sort_order=row["sort_order"],
        color=row["color"],
        collapsed=bool(row["collapsed"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _row_to_task(row: sqlite3.Row) -> Task:
    return Task(
        id=row["id"],
        title=row["title"],
        project_id=row["project_id"],
        status=row["status"],
        priority=row["priority"],
        due_date=row["due_date"],
        due_time=row["due_time"],
        reminder_minutes_before=row["reminder_minutes_before"],
        completed_at=row["completed_at"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        sort_order=row["sort_order"],
    )


def _row_to_subtask(row: sqlite3.Row) -> Subtask:
    return Subtask(
        id=row["id"],
        task_id=row["task_id"],
        title=row["title"],
        done=bool(row["done"]),
        sort_order=row["sort_order"],
        created_at=row["created_at"],
    )


def _row_to_tag(row: sqlite3.Row) -> Tag:
    return Tag(
        id=row["id"],
        name=row["name"],
        color=row["color"],
    )


def _row_to_attachment(row: sqlite3.Row) -> Attachment:
    return Attachment(
        id=row["id"],
        task_id=row["task_id"],
        name=row["name"],
        path_or_url=row["path_or_url"],
        created_at=row["created_at"],
    )


def _row_to_note(row: sqlite3.Row) -> Note:
    return Note(
        id=row["id"],
        task_id=row["task_id"],
        content=row["content"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _row_to_pomodoro(row: sqlite3.Row) -> PomodoroSession:
    return PomodoroSession(
        id=row["id"],
        task_id=row["task_id"],
        started_at=row["started_at"],
        duration_minutes=row["duration_minutes"],
        completed=bool(row["completed"]),
    )


def _row_to_reminder(row: sqlite3.Row) -> Reminder:
    return Reminder(
        id=row["id"],
        task_id=row["task_id"],
        remind_at=row["remind_at"],
        dismissed=bool(row["dismissed"]),
    )


class Database:
    def __init__(self, db_path: Optional[Path] = None) -> None:
        self.db_path = db_path or DB_PATH

    @contextmanager
    def _connect(self):
        DB_DIR.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    # ── Projects ──────────────────────────────────────────────

    def create_project(self, project: Project) -> int:
        now = _now()
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO projects (name, parent_id, sort_order, color, collapsed, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (project.name, project.parent_id, project.sort_order, project.color,
                 int(project.collapsed), now, now),
            )
            return cur.lastrowid

    def get_project(self, project_id: int) -> Optional[Project]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
            return _row_to_project(row) if row else None

    def list_projects(self, parent_id: Optional[int] = None) -> List[Project]:
        with self._connect() as conn:
            if parent_id is None:
                rows = conn.execute("SELECT * FROM projects ORDER BY sort_order").fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM projects WHERE parent_id = ? ORDER BY sort_order",
                    (parent_id,),
                ).fetchall()
            return [_row_to_project(r) for r in rows]

    def update_project(self, project: Project) -> None:
        if project.id is None:
            return
        now = _now()
        with self._connect() as conn:
            conn.execute(
                "UPDATE projects SET name=?, parent_id=?, sort_order=?, color=?, collapsed=?, updated_at=? "
                "WHERE id=?",
                (project.name, project.parent_id, project.sort_order, project.color,
                 int(project.collapsed), now, project.id),
            )

    def delete_project(self, project_id: int) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))

    # ── Tasks ─────────────────────────────────────────────────

    def create_task(self, task: Task) -> int:
        now = _now()
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO tasks (title, project_id, status, priority, due_date, due_time, "
                "reminder_minutes_before, completed_at, created_at, updated_at, sort_order) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (task.title, task.project_id, task.status, task.priority, task.due_date,
                 task.due_time, task.reminder_minutes_before, task.completed_at,
                 now, now, task.sort_order),
            )
            return cur.lastrowid

    def get_task(self, task_id: int) -> Optional[Task]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
            return _row_to_task(row) if row else None

    def update_task(self, task: Task) -> None:
        if task.id is None:
            return
        now = _now()
        with self._connect() as conn:
            conn.execute(
                "UPDATE tasks SET title=?, project_id=?, status=?, priority=?, due_date=?, "
                "due_time=?, reminder_minutes_before=?, completed_at=?, updated_at=?, sort_order=? "
                "WHERE id=?",
                (task.title, task.project_id, task.status, task.priority, task.due_date,
                 task.due_time, task.reminder_minutes_before, task.completed_at,
                 now, task.sort_order, task.id),
            )

    def delete_task(self, task_id: int) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))

    def get_tasks_by_project(self, project_id: int) -> List[Task]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM tasks WHERE project_id = ? ORDER BY sort_order",
                (project_id,),
            ).fetchall()
            return [_row_to_task(r) for r in rows]

    def get_tasks_by_status(self, status: str) -> List[Task]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM tasks WHERE status = ? ORDER BY sort_order",
                (status,),
            ).fetchall()
            return [_row_to_task(r) for r in rows]

    def move_task(self, task_id: int, new_project_id: Optional[int], new_sort_order: int) -> None:
        now = _now()
        with self._connect() as conn:
            conn.execute(
                "UPDATE tasks SET project_id=?, sort_order=?, updated_at=? WHERE id=?",
                (new_project_id, new_sort_order, now, task_id),
            )

    def reorder_tasks(self, project_id: Optional[int], task_id_order_list: List[Tuple[int, int]]) -> None:
        now = _now()
        with self._connect() as conn:
            for task_id, sort_order in task_id_order_list:
                conn.execute(
                    "UPDATE tasks SET sort_order=?, updated_at=? WHERE id=? AND project_id=?",
                    (sort_order, now, task_id, project_id),
                )

    def search_tasks(self, query: str) -> List[Task]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM tasks WHERE title LIKE ? ORDER BY sort_order",
                (f"%{query}%",),
            ).fetchall()
            return [_row_to_task(r) for r in rows]

    # ── Subtasks ──────────────────────────────────────────────

    def create_subtask(self, subtask: Subtask) -> int:
        now = _now()
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO subtasks (task_id, title, done, sort_order, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (subtask.task_id, subtask.title, int(subtask.done), subtask.sort_order, now),
            )
            return cur.lastrowid

    def get_subtask(self, subtask_id: int) -> Optional[Subtask]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM subtasks WHERE id = ?", (subtask_id,)).fetchone()
            return _row_to_subtask(row) if row else None

    def get_subtasks(self, task_id: int) -> List[Subtask]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM subtasks WHERE task_id = ? ORDER BY sort_order",
                (task_id,),
            ).fetchall()
            return [_row_to_subtask(r) for r in rows]

    def update_subtask(self, subtask: Subtask) -> None:
        if subtask.id is None:
            return
        with self._connect() as conn:
            conn.execute(
                "UPDATE subtasks SET title=?, done=?, sort_order=? WHERE id=?",
                (subtask.title, int(subtask.done), subtask.sort_order, subtask.id),
            )

    def delete_subtask(self, subtask_id: int) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM subtasks WHERE id = ?", (subtask_id,))

    # ── Tags ──────────────────────────────────────────────────

    def create_tag(self, tag: Tag) -> int:
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO tags (name, color) VALUES (?, ?)",
                (tag.name, tag.color),
            )
            return cur.lastrowid

    def get_tag(self, tag_id: int) -> Optional[Tag]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM tags WHERE id = ?", (tag_id,)).fetchone()
            return _row_to_tag(row) if row else None

    def list_tags(self) -> List[Tag]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM tags ORDER BY name").fetchall()
            return [_row_to_tag(r) for r in rows]

    def update_tag(self, tag: Tag) -> None:
        if tag.id is None:
            return
        with self._connect() as conn:
            conn.execute(
                "UPDATE tags SET name=?, color=? WHERE id=?",
                (tag.name, tag.color, tag.id),
            )

    def delete_tag(self, tag_id: int) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM tags WHERE id = ?", (tag_id,))

    def get_tags(self, task_id: int) -> List[Tag]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT t.* FROM tags t JOIN task_tags tt ON t.id = tt.tag_id "
                "WHERE tt.task_id = ?",
                (task_id,),
            ).fetchall()
            return [_row_to_tag(r) for r in rows]

    def add_task_tag(self, task_id: int, tag_id: int) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO task_tags (task_id, tag_id) VALUES (?, ?)",
                (task_id, tag_id),
            )

    def remove_task_tag(self, task_id: int, tag_id: int) -> None:
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM task_tags WHERE task_id = ? AND tag_id = ?",
                (task_id, tag_id),
            )

    # ── Attachments ───────────────────────────────────────────

    def create_attachment(self, attachment: Attachment) -> int:
        now = _now()
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO attachments (task_id, name, path_or_url, created_at) "
                "VALUES (?, ?, ?, ?)",
                (attachment.task_id, attachment.name, attachment.path_or_url, now),
            )
            return cur.lastrowid

    def get_attachment(self, attachment_id: int) -> Optional[Attachment]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM attachments WHERE id = ?", (attachment_id,)).fetchone()
            return _row_to_attachment(row) if row else None

    def get_attachments(self, task_id: int) -> List[Attachment]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM attachments WHERE task_id = ? ORDER BY created_at",
                (task_id,),
            ).fetchall()
            return [_row_to_attachment(r) for r in rows]

    def delete_attachment(self, attachment_id: int) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM attachments WHERE id = ?", (attachment_id,))

    # ── Notes ─────────────────────────────────────────────────

    def create_note(self, note: Note) -> int:
        now = _now()
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO notes (task_id, content, created_at, updated_at) "
                "VALUES (?, ?, ?, ?)",
                (note.task_id, note.content, now, now),
            )
            return cur.lastrowid

    def get_note(self, note_id: int) -> Optional[Note]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM notes WHERE id = ?", (note_id,)).fetchone()
            return _row_to_note(row) if row else None

    def get_notes(self, task_id: int) -> List[Note]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM notes WHERE task_id = ? ORDER BY created_at",
                (task_id,),
            ).fetchall()
            return [_row_to_note(r) for r in rows]

    def update_note(self, note: Note) -> None:
        if note.id is None:
            return
        now = _now()
        with self._connect() as conn:
            conn.execute(
                "UPDATE notes SET content=?, updated_at=? WHERE id=?",
                (note.content, now, note.id),
            )

    def delete_note(self, note_id: int) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM notes WHERE id = ?", (note_id,))

    # ── Pomodoro Sessions ─────────────────────────────────────

    def add_pomodoro_session(self, session: PomodoroSession) -> int:
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO pomodoro_sessions (task_id, started_at, duration_minutes, completed) "
                "VALUES (?, ?, ?, ?)",
                (session.task_id, session.started_at, session.duration_minutes, int(session.completed)),
            )
            return cur.lastrowid

    def get_pomodoro_session(self, session_id: int) -> Optional[PomodoroSession]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM pomodoro_sessions WHERE id = ?", (session_id,)).fetchone()
            return _row_to_pomodoro(row) if row else None

    def update_pomodoro_session(self, session: PomodoroSession) -> None:
        if session.id is None:
            return
        with self._connect() as conn:
            conn.execute(
                "UPDATE pomodoro_sessions SET task_id=?, started_at=?, duration_minutes=?, completed=? "
                "WHERE id=?",
                (session.task_id, session.started_at, session.duration_minutes,
                 int(session.completed), session.id),
            )

    def delete_pomodoro_session(self, session_id: int) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM pomodoro_sessions WHERE id = ?", (session_id,))

    def get_pomodoro_stats(self, date_range: Tuple[str, str]) -> Dict[str, Any]:
        start_date, end_date = date_range
        with self._connect() as conn:
            total_row = conn.execute(
                "SELECT COUNT(*) AS count, SUM(duration_minutes) AS total_minutes "
                "FROM pomodoro_sessions WHERE started_at BETWEEN ? AND ?",
                (start_date, end_date),
            ).fetchone()
            completed_row = conn.execute(
                "SELECT COUNT(*) AS count, SUM(duration_minutes) AS total_minutes "
                "FROM pomodoro_sessions WHERE started_at BETWEEN ? AND ? AND completed = 1",
                (start_date, end_date),
            ).fetchone()
            by_task_rows = conn.execute(
                "SELECT task_id, COUNT(*) AS count, SUM(duration_minutes) AS total_minutes "
                "FROM pomodoro_sessions WHERE started_at BETWEEN ? AND ? AND completed = 1 "
                "GROUP BY task_id",
                (start_date, end_date),
            ).fetchall()
            by_task = {}
            for r in by_task_rows:
                by_task[r["task_id"]] = {
                    "count": r["count"],
                    "total_minutes": r["total_minutes"] or 0,
                }
            return {
                "total_sessions": total_row["count"] or 0,
                "total_minutes": total_row["total_minutes"] or 0,
                "completed_sessions": completed_row["count"] or 0,
                "completed_minutes": completed_row["total_minutes"] or 0,
                "by_task": by_task,
            }

    # ── Reminders ─────────────────────────────────────────────

    def create_reminder(self, reminder: Reminder) -> int:
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO reminders (task_id, remind_at, dismissed) VALUES (?, ?, ?)",
                (reminder.task_id, reminder.remind_at, int(reminder.dismissed)),
            )
            return cur.lastrowid

    def get_reminder(self, reminder_id: int) -> Optional[Reminder]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM reminders WHERE id = ?", (reminder_id,)).fetchone()
            return _row_to_reminder(row) if row else None

    def get_reminders_by_task(self, task_id: int) -> List[Reminder]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM reminders WHERE task_id = ? ORDER BY remind_at",
                (task_id,),
            ).fetchall()
            return [_row_to_reminder(r) for r in rows]

    def get_pending_reminders(self) -> List[Reminder]:
        now = _now()
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM reminders WHERE dismissed = 0 AND remind_at <= ?",
                (now,),
            ).fetchall()
            return [_row_to_reminder(r) for r in rows]

    def update_reminder(self, reminder: Reminder) -> None:
        if reminder.id is None:
            return
        with self._connect() as conn:
            conn.execute(
                "UPDATE reminders SET task_id=?, remind_at=?, dismissed=? WHERE id=?",
                (reminder.task_id, reminder.remind_at, int(reminder.dismissed), reminder.id),
            )

    def dismiss_reminder(self, reminder_id: int) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE reminders SET dismissed = 1 WHERE id = ?",
                (reminder_id,),
            )

    def delete_reminder(self, reminder_id: int) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM reminders WHERE id = ?", (reminder_id,))

    # ── Stats ─────────────────────────────────────────────────

    def get_weekly_stats(self, start_date: str, end_date: str) -> Dict[str, Any]:
        with self._connect() as conn:
            tasks_created = conn.execute(
                "SELECT COUNT(*) AS count FROM tasks WHERE created_at BETWEEN ? AND ?",
                (start_date, end_date),
            ).fetchone()["count"]
            tasks_completed = conn.execute(
                "SELECT COUNT(*) AS count FROM tasks WHERE completed_at BETWEEN ? AND ?",
                (start_date, end_date),
            ).fetchone()["count"]
            tasks_by_status_rows = conn.execute(
                "SELECT status, COUNT(*) AS count FROM tasks GROUP BY status"
            ).fetchall()
            tasks_by_status = {r["status"]: r["count"] for r in tasks_by_status_rows}
            pomodoro = self.get_pomodoro_stats((start_date, end_date))
            overdue = conn.execute(
                "SELECT COUNT(*) AS count FROM tasks "
                "WHERE due_date < ? AND status NOT IN ('done', 'archived')",
                (end_date,),
            ).fetchone()["count"]
            return {
                "tasks_created": tasks_created or 0,
                "tasks_completed": tasks_completed or 0,
                "tasks_by_status": tasks_by_status,
                "pomodoro": pomodoro,
                "overdue_tasks": overdue or 0,
            }
