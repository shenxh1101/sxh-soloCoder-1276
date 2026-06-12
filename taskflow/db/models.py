from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class Project:
    id: Optional[int] = None
    name: str = ""
    parent_id: Optional[int] = None
    sort_order: int = 0
    color: Optional[str] = None
    collapsed: bool = False
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


@dataclass
class Task:
    id: Optional[int] = None
    title: str = ""
    project_id: Optional[int] = None
    status: str = "todo"
    priority: Optional[str] = None
    due_date: Optional[str] = None
    due_time: Optional[str] = None
    reminder_minutes_before: Optional[int] = None
    completed_at: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    sort_order: int = 0
    recurrence_rule: Optional[str] = None


@dataclass
class Subtask:
    id: Optional[int] = None
    task_id: Optional[int] = None
    title: str = ""
    done: bool = False
    sort_order: int = 0
    created_at: Optional[str] = None


@dataclass
class Tag:
    id: Optional[int] = None
    name: str = ""
    color: Optional[str] = None


@dataclass
class TaskTag:
    task_id: Optional[int] = None
    tag_id: Optional[int] = None


@dataclass
class Attachment:
    id: Optional[int] = None
    task_id: Optional[int] = None
    name: str = ""
    path_or_url: str = ""
    created_at: Optional[str] = None


@dataclass
class Note:
    id: Optional[int] = None
    task_id: Optional[int] = None
    content: str = ""
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


@dataclass
class PomodoroSession:
    id: Optional[int] = None
    task_id: Optional[int] = None
    started_at: Optional[str] = None
    duration_minutes: int = 25
    completed: bool = False


@dataclass
class Reminder:
    id: Optional[int] = None
    task_id: Optional[int] = None
    remind_at: Optional[str] = None
    dismissed: bool = False
