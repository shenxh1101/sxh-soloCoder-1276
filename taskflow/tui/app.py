from __future__ import annotations

import sys
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Optional

from prompt_toolkit import PromptSession
from prompt_toolkit.key_binding import KeyBindings
from rich.console import Console, Group
from rich.layout import Layout
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.tree import Tree

from taskflow.config import Config, get_db_path, load_config
from taskflow.db import Database
from taskflow.db.models import Note, Project, Reminder, Subtask, Task
from taskflow.features.nlp_parser import parse_natural_task
from taskflow.features.search import SearchEngine
from taskflow.features.themes import Theme, get_theme


@dataclass
class AppState:
    db: Database
    config: Config
    theme: Theme
    projects: list[Project] = field(default_factory=list)
    tasks: list[Task] = field(default_factory=list)
    selected_project_id: Optional[int] = None
    selected_task_id: Optional[int] = None
    project_cursor: int = 0
    task_cursor: int = 0
    focus_panel: str = "projects"
    task_view: str = "list"
    collapsed_projects: set[int] = field(default_factory=set)
    calendar_offset: int = 0
    status_message: str = "Welcome to TaskFlow! Press ? for help."
    search_query: str = ""


def _status_label(status: str) -> str:
    mapping = {
        "todo": "📋 ToDo",
        "in_progress": "🚀 Doing",
        "done": "✅ Done",
        "archived": "📦 Archived",
    }
    return mapping.get(status, status)


def _priority_label(priority: Optional[str]) -> str:
    if not priority:
        return ""
    mapping = {
        "urgent_important": "🔴 Q1",
        "not_urgent_important": "🟡 Q2",
        "urgent_not_important": "🟠 Q3",
        "not_urgent_not_important": "⚪ Q4",
    }
    return mapping.get(priority, priority)


def _priority_color(priority: Optional[str], theme: Theme) -> str:
    if not priority:
        return theme.muted
    return theme.priority_colors.get(priority, theme.muted)


def _status_color(status: str, theme: Theme) -> str:
    mapping = {
        "todo": theme.muted,
        "in_progress": theme.accent,
        "done": theme.success,
        "archived": theme.muted,
    }
    return mapping.get(status, theme.muted)


def _build_project_tree(state: AppState, tree: Tree, parent_id: Optional[int], depth: int = 0) -> None:
    children = [p for p in state.projects if p.parent_id == parent_id]
    children.sort(key=lambda p: p.sort_order)

    for idx, project in enumerate(children):
        collapsed = project.id in state.collapsed_projects
        label = f"{'▸ ' if collapsed else '▾ ' if any(p.parent_id == project.id for p in state.projects) else '  '}"
        label += f"[bold]{project.name}[/bold]"

        proj_tasks = [t for t in state.tasks if t.project_id == project.id and t.status != "archived"]
        if proj_tasks:
            label += f" [dim]({len(proj_tasks)})[/dim]"

        is_selected = state.selected_project_id == project.id and state.focus_panel == "projects"
        style = f"reverse {state.theme.project_color}" if is_selected else state.theme.project_color

        branch = tree.add(Text.from_markup(label), style=style)

        if not collapsed:
            _build_project_tree(state, branch, project.id, depth + 1)


def render_projects_panel(state: AppState) -> Panel:
    root = Tree("📁 All Projects", guide_style=state.theme.muted)
    _build_project_tree(state, root, None)
    return Panel(root, title="[bold]Projects[/bold]", border_style=state.theme.panel_border)


def render_task_list_view(state: AppState) -> Panel:
    if state.search_query:
        engine = SearchEngine(state.db)
        results = engine.search(state.search_query)
        task_ids = [r.item.get("task_id") for r in results if r.item.get("task_id") is not None]
        filtered = [t for t in state.tasks if t.id in task_ids]
    elif state.selected_project_id is None:
        filtered = [t for t in state.tasks if t.status != "archived"]
    else:
        filtered = [t for t in state.tasks if t.project_id == state.selected_project_id and t.status != "archived"]

    table = Table(show_header=True, expand=True, header_style=f"bold {state.theme.accent}")
    table.add_column("ID", justify="right", width=5, style=state.theme.muted)
    table.add_column("Status", width=10)
    table.add_column("Priority", width=6)
    table.add_column("Title", ratio=1)
    table.add_column("Due", width=18)
    table.add_column("Tags", width=20)

    for idx, task in enumerate(filtered):
        is_selected = state.selected_task_id == task.id and state.focus_panel == "tasks"
        row_style = f"on {state.theme.highlight}" if is_selected else ""

        status_style = _status_color(task.status, state.theme)
        status_txt = Text(_status_label(task.status), style=status_style)

        pri_color = _priority_color(task.priority, state.theme)
        pri_txt = Text(_priority_label(task.priority), style=pri_color)

        due_parts = []
        if task.due_date:
            due_parts.append(task.due_date)
        if task.due_time:
            due_parts.append(task.due_time[:5])
        due_txt = Text(" ".join(due_parts), style=state.theme.warning if due_parts else state.theme.muted)

        tags = state.db.get_tags(task.id) if task.id else []
        tag_str = ", ".join(f"#{t.name}" for t in tags[:3])
        tag_txt = Text(tag_str, style=state.theme.tag_colors[0] if tags else state.theme.muted)

        table.add_row(
            Text(str(task.id) if task.id else "", style=row_style or state.theme.muted),
            status_txt,
            pri_txt,
            Text(task.title, style=row_style),
            due_txt,
            tag_txt,
            style=row_style,
        )

    if not filtered:
        table.add_row(Text("(no tasks)", style=state.theme.muted), "", "", "", "", "")

    title = f"[bold]Tasks[/bold] — [{state.task_view.upper()}]"
    if state.search_query:
        title += f" 🔍 '{state.search_query}'"
    return Panel(table, title=title, border_style=state.theme.panel_border)


def render_task_kanban_view(state: AppState) -> Panel:
    columns = [
        ("todo", "📋 ToDo", []),
        ("in_progress", "🚀 Doing", []),
        ("done", "✅ Done", []),
    ]

    if state.search_query:
        engine = SearchEngine(state.db)
        results = engine.search(state.search_query)
        task_ids = {r.item.get("task_id") for r in results if r.item.get("task_id") is not None}
        filtered = [t for t in state.tasks if t.id in task_ids]
    elif state.selected_project_id is None:
        filtered = [t for t in state.tasks if t.status != "archived"]
    else:
        filtered = [t for t in state.tasks if t.project_id == state.selected_project_id and t.status != "archived"]

    for task in filtered:
        for status, _, bucket in columns:
            if task.status == status:
                bucket.append(task)
                break

    grid = Table.grid(expand=True, padding=1)
    for _ in columns:
        grid.add_column(ratio=1)

    rows = []
    for status, label, bucket in columns:
        col_table = Table(show_header=False, expand=True)
        col_table.add_column(ratio=1)
        col_title = f"[bold]{label}[/bold] ({len(bucket)})"

        if not bucket:
            col_table.add_row(Text("—", style=state.theme.muted))
        else:
            for task in bucket:
                is_selected = state.selected_task_id == task.id and state.focus_panel == "tasks"
                pri_color = _priority_color(task.priority, state.theme)
                txt = Text()
                txt.append(f"[{task.id}] ", style=state.theme.muted)
                txt.append(f"{_priority_label(task.priority)} ", style=pri_color)
                txt.append(task.title, style=f"reverse {state.theme.highlight}" if is_selected else "")
                due_parts = []
                if task.due_date:
                    due_parts.append(task.due_date)
                if task.due_time:
                    due_parts.append(task.due_time[:5])
                if due_parts:
                    txt.append(f"  📅 {' '.join(due_parts)}", style=state.theme.warning)
                col_table.add_row(Panel(txt, border_style=state.theme.muted, padding=(0, 1)))

        rows.append((col_title, col_table))

    header_row = [Text(t, style=f"bold {state.theme.accent}") for t, _, _ in columns]
    grid.add_row(*header_row)
    grid.add_row(*[r[1] for r in rows])

    title = f"[bold]Tasks[/bold] — [KANBAN]"
    if state.search_query:
        title += f" 🔍 '{state.search_query}'"
    return Panel(grid, title=title, border_style=state.theme.panel_border)


def render_task_calendar_view(state: AppState) -> Panel:
    today = date.today() + timedelta(weeks=state.calendar_offset)
    start_of_week = today - timedelta(days=today.weekday())
    days = [start_of_week + timedelta(days=i) for i in range(7)]

    table = Table(show_header=True, expand=True, header_style=f"bold {state.theme.accent}")
    day_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    for i, d in enumerate(days):
        is_today = d == date.today()
        style = f"bold {state.theme.warning}" if is_today else ""
        table.add_column(f"[{day_names[i]}] {d.month}/{d.day}", style=style, ratio=1)

    if state.search_query:
        engine = SearchEngine(state.db)
        results = engine.search(state.search_query)
        task_ids = {r.item.get("task_id") for r in results if r.item.get("task_id") is not None}
        filtered = [t for t in state.tasks if t.id in task_ids]
    elif state.selected_project_id is None:
        filtered = [t for t in state.tasks if t.status != "archived"]
    else:
        filtered = [t for t in state.tasks if t.project_id == state.selected_project_id and t.status != "archived"]

    tasks_by_day: dict[date, list[Task]] = {d: [] for d in days}
    for task in filtered:
        if task.due_date:
            try:
                td = date.fromisoformat(task.due_date)
                if td in tasks_by_day:
                    tasks_by_day[td].append(task)
            except ValueError:
                pass

    max_rows = max((len(v) for v in tasks_by_day.values()), default=1)
    for row_i in range(max_rows):
        row_cells = []
        for d in days:
            if row_i < len(tasks_by_day[d]):
                task = tasks_by_day[d][row_i]
                is_selected = state.selected_task_id == task.id and state.focus_panel == "tasks"
                pri_color = _priority_color(task.priority, state.theme)
                txt = Text()
                txt.append(f"[{task.id}] ", style=state.theme.muted)
                txt.append(task.title, style=f"reverse {state.theme.highlight}" if is_selected else "")
                if task.status == "done":
                    txt.stylize("strike")
                row_cells.append(Panel(txt, border_style=pri_color, padding=(0, 1)))
            else:
                row_cells.append(Text(""))
        table.add_row(*row_cells)

    title = f"[bold]Tasks[/bold] — [CALENDAR] {start_of_week.isoformat()} ~ {(start_of_week + timedelta(days=6)).isoformat()}"
    if state.search_query:
        title += f" 🔍 '{state.search_query}'"
    return Panel(table, title=title, border_style=state.theme.panel_border)


def render_tasks_panel(state: AppState) -> Panel:
    if state.task_view == "kanban":
        return render_task_kanban_view(state)
    elif state.task_view == "calendar":
        return render_task_calendar_view(state)
    else:
        return render_task_list_view(state)


def render_detail_panel(state: AppState) -> Panel:
    if state.selected_task_id is None:
        return Panel(
            Text("Select a task to see details\n\n"
                 "Shortcuts:\n"
                 "  Tab / Shift+Tab — switch panels\n"
                 "  1/2/3 — list / kanban / calendar\n"
                 "  j/k or ↑/↓ — navigate\n"
                 "  a — add task (natural language)\n"
                 "  c — complete task\n"
                 "  d — delete task\n"
                 "  / — search\n"
                 "  Esc — clear search\n"
                 "  n — add note\n"
                 "  [ / ] — calendar week\n"
                 "  Space — toggle project collapse\n"
                 "  q — quit\n\n"
                 "Project commands:\n"
                 "  p add [name] — add project (child of selected if any)\n"
                 "  p rename [name] — rename selected project\n"
                 "  p move <id> — move selected project (0/root for root)\n"
                 "  p delete — delete selected project\n"
                 "  p up / p down — reorder selected project",
                 style=state.theme.muted),
            title="[bold]Task Detail[/bold]",
            border_style=state.theme.panel_border,
        )

    details = state.db.get_task_with_details(state.selected_task_id)
    if not details:
        return Panel(Text("Task not found", style=state.theme.error), title="[bold]Task Detail[/bold]",
                     border_style=state.theme.panel_border)

    title = Text(details.get("title", ""), style=f"bold {state.theme.accent}", overflow="fold")
    status_style = _status_color(details.get("status", ""), state.theme)
    status_text = Text(f"Status: {_status_label(details.get('status', ''))}", style=status_style)

    pri_color = _priority_color(details.get("priority"), state.theme)
    pri_text = Text(f"Priority: {_priority_label(details.get('priority')) or '—'}", style=pri_color)

    info_lines = [status_text, pri_text]

    project_name = details.get("project_name") or "—"
    info_lines.append(Text(f"Project: {project_name}", style=state.theme.project_color))

    due_parts = []
    if details.get("due_date"):
        due_parts.append(details["due_date"])
    if details.get("due_time"):
        due_parts.append(details["due_time"][:5])
    if due_parts:
        info_lines.append(Text(f"Due: {' '.join(due_parts)}", style=state.theme.warning))
    else:
        info_lines.append(Text("Due: —", style=state.theme.muted))

    tags = details.get("tags", [])
    if tags:
        tag_text = Text("Tags: ", style=state.theme.muted)
        for i, t in enumerate(tags):
            c = state.theme.tag_colors[i % len(state.theme.tag_colors)]
            tag_text.append(f"#{t.get('name', '')} ", style=c)
        info_lines.append(tag_text)

    info_lines.append(Text(""))

    subtasks = details.get("subtasks", [])
    if subtasks:
        info_lines.append(Text(f"Subtasks ({len(subtasks)}):", style=f"bold {state.theme.accent}"))
        for s in subtasks:
            marker = "✅" if s.get("done") else "⬜"
            info_lines.append(Text(f"  {marker} {s.get('title', '')}"))
        info_lines.append(Text(""))

    attachments = details.get("attachments", [])
    if attachments:
        info_lines.append(Text(f"Attachments ({len(attachments)}):", style=f"bold {state.theme.accent}"))
        for a in attachments:
            info_lines.append(Text(f"  📎 {a.get('name', '')} — {a.get('path_or_url', '')}", style=state.theme.muted))
        info_lines.append(Text(""))

    notes = details.get("notes", [])
    if notes:
        info_lines.append(Text(f"Notes / Log ({len(notes)}):", style=f"bold {state.theme.accent}"))
        for n in notes:
            info_lines.append(Text(f"  ── {n.get('created_at', '')[:19]} ──", style=state.theme.muted))
            content = n.get("content", "")
            for line in content.split("\n"):
                info_lines.append(Text(f"  {line}", style=state.theme.fg))
            info_lines.append(Text(""))

    if details.get("created_at"):
        info_lines.append(Text(f"Created: {details['created_at'][:19]}", style=state.theme.muted))
    if details.get("completed_at"):
        info_lines.append(Text(f"Completed: {details['completed_at'][:19]}", style=state.theme.success))

    group = Group(title, Text(""), *info_lines)
    return Panel(
        group,
        title=f"[bold]Task Detail[/bold] — ID #{details.get('id', '?')}",
        border_style=state.theme.panel_border,
    )


def render_status_bar(state: AppState) -> Panel:
    focus_map = {"projects": "Projects", "tasks": "Tasks", "detail": "Detail"}
    focus = focus_map.get(state.focus_panel, "Tasks")

    counts = {s: 0 for s in ["todo", "in_progress", "done"]}
    for t in state.tasks:
        if t.status in counts:
            counts[t.status] += 1

    text = Text()
    text.append(f" [ {focus} ] ", style=f"bold on {state.theme.accent}")
    text.append(f"  Projects: {len(state.projects)}  ", style=state.theme.fg)
    text.append(f"ToDo: {counts['todo']}  ", style=state.theme.muted)
    text.append(f"Doing: {counts['in_progress']}  ", style=state.theme.accent)
    text.append(f"Done: {counts['done']}  ", style=state.theme.success)
    text.append(f"│ {state.status_message}", style=state.theme.warning)

    return Panel(text, border_style=state.theme.panel_border, height=3)


def refresh_data(state: AppState) -> None:
    state.projects = state.db.list_projects()
    state.tasks = state.db.get_all_tasks()


def get_visible_task_ids(state: AppState) -> list[int]:
    if state.search_query:
        engine = SearchEngine(state.db)
        results = engine.search(state.search_query)
        return [r.item.get("task_id") for r in results if r.item.get("task_id") is not None]

    if state.selected_project_id is None:
        return [t.id for t in state.tasks if t.id is not None and t.status != "archived"]
    return [t.id for t in state.tasks if t.project_id == state.selected_project_id and t.id is not None and t.status != "archived"]


def get_visible_project_ids(state: AppState) -> list[int]:
    return [p.id for p in state.projects if p.id is not None]


def navigate_tasks(state: AppState, delta: int) -> None:
    ids = get_visible_task_ids(state)
    if not ids:
        state.selected_task_id = None
        return
    if state.selected_task_id is None or state.selected_task_id not in ids:
        state.selected_task_id = ids[0]
        return
    idx = ids.index(state.selected_task_id)
    idx = max(0, min(len(ids) - 1, idx + delta))
    state.selected_task_id = ids[idx]


def navigate_projects(state: AppState, delta: int) -> None:
    ids = get_visible_project_ids(state)
    if not ids:
        state.selected_project_id = None
        return
    if state.selected_project_id is None:
        state.selected_project_id = ids[0]
        return
    if state.selected_project_id not in ids:
        state.selected_project_id = ids[0]
        return
    idx = ids.index(state.selected_project_id)
    idx = max(0, min(len(ids) - 1, idx + delta))
    state.selected_project_id = ids[idx]


def toggle_project_collapse(state: AppState) -> None:
    if state.selected_project_id is not None:
        if state.selected_project_id in state.collapsed_projects:
            state.collapsed_projects.discard(state.selected_project_id)
        else:
            state.collapsed_projects.add(state.selected_project_id)


def add_task_interactive(state: AppState, console: Console) -> None:
    try:
        session: PromptSession = PromptSession()
        text = session.prompt("➕ New task (natural language): ")
        if not text.strip():
            state.status_message = "Cancelled."
            return
    except (EOFError, KeyboardInterrupt):
        state.status_message = "Cancelled."
        return

    result = parse_natural_task(text)

    project_id = state.selected_project_id
    if result.project:
        proj = state.db.get_or_create_project(result.project)
        project_id = proj.id

    sort_order = 0
    if project_id is not None:
        existing = state.db.get_tasks_by_project(project_id)
        if existing:
            sort_order = max(t.sort_order for t in existing) + 1
    else:
        unassigned = [t for t in state.db.get_all_tasks() if t.project_id is None]
        if unassigned:
            sort_order = max(t.sort_order for t in unassigned) + 1

    task = Task(
        title=result.title or text,
        project_id=project_id,
        status="todo",
        priority=result.priority,
        due_date=result.due_date.isoformat() if result.due_date else None,
        due_time=result.due_time.isoformat() if result.due_time else None,
        reminder_minutes_before=15 if (result.due_date or result.due_time) else None,
        sort_order=sort_order,
    )
    task_id = state.db.create_task(task)

    for tag_name in result.tags:
        tag = state.db.get_or_create_tag(tag_name)
        if tag.id is not None:
            state.db.add_task_tag(task_id, tag.id)

    if result.due_date is not None:
        due_dt = datetime.combine(result.due_date, result.due_time or datetime.min.time())
        remind_at = due_dt - timedelta(minutes=15)
        reminder = Reminder(task_id=task_id, remind_at=remind_at.isoformat(), dismissed=False)
        state.db.create_reminder(reminder)

    state.selected_task_id = task_id
    state.status_message = f"Created task #{task_id}: {result.title or text}"
    refresh_data(state)


def add_note_interactive(state: AppState, console: Console) -> None:
    if state.selected_task_id is None:
        state.status_message = "No task selected."
        return
    try:
        session: PromptSession = PromptSession()
        text = session.prompt("📝 Note content (Markdown): ")
        if not text.strip():
            state.status_message = "Cancelled."
            return
    except (EOFError, KeyboardInterrupt):
        state.status_message = "Cancelled."
        return

    note = Note(task_id=state.selected_task_id, content=text)
    state.db.create_note(note)
    state.status_message = "Note added."
    refresh_data(state)


def search_interactive(state: AppState, console: Console) -> None:
    try:
        session: PromptSession = PromptSession()
        text = session.prompt("🔍 Search: ")
        state.search_query = text.strip()
        state.status_message = f"Searching: '{state.search_query}'" if state.search_query else "Search cleared."
    except (EOFError, KeyboardInterrupt):
        state.status_message = "Search cancelled."


def complete_selected_task(state: AppState) -> None:
    if state.selected_task_id is None:
        state.status_message = "No task selected."
        return
    task = state.db.get_task(state.selected_task_id)
    if task is None:
        state.status_message = "Task not found."
        return
    if task.status == "done":
        task.status = "todo"
        task.completed_at = None
        state.status_message = f"Task #{task.id} unmarked as done."
    else:
        task.status = "done"
        task.completed_at = datetime.now().isoformat()
        state.status_message = f"Task #{task.id} marked as done! 🎉"
    state.db.update_task(task)
    refresh_data(state)


def delete_selected_task(state: AppState) -> None:
    if state.selected_task_id is None:
        state.status_message = "No task selected."
        return
    tid = state.selected_task_id
    state.db.delete_task(tid)
    state.selected_task_id = None
    state.status_message = f"Task #{tid} deleted."
    refresh_data(state)


def add_project_interactive(state: AppState, name: Optional[str] = None) -> None:
    if not name:
        try:
            session: PromptSession = PromptSession()
            name = session.prompt("Project name: ")
            if not name.strip():
                state.status_message = "Cancelled."
                return
        except (EOFError, KeyboardInterrupt):
            state.status_message = "Cancelled."
            return

    parent_id = state.selected_project_id
    sort_order = 0
    siblings = state.db.list_projects(parent_id)
    if siblings:
        sort_order = max(p.sort_order for p in siblings) + 1

    project = Project(name=name.strip(), parent_id=parent_id, sort_order=sort_order)
    new_id = state.db.create_project(project)
    state.selected_project_id = new_id
    state.status_message = f"Created project #{new_id}: {name.strip()}"
    refresh_data(state)


def rename_project_interactive(state: AppState, new_name: Optional[str] = None) -> None:
    if state.selected_project_id is None:
        state.status_message = "No project selected."
        return
    if not new_name:
        try:
            session: PromptSession = PromptSession()
            new_name = session.prompt("New project name: ")
            if not new_name.strip():
                state.status_message = "Cancelled."
                return
        except (EOFError, KeyboardInterrupt):
            state.status_message = "Cancelled."
            return

    project = state.db.get_project(state.selected_project_id)
    if project is None:
        state.status_message = "Project not found."
        return
    project.name = new_name.strip()
    state.db.update_project(project)
    state.status_message = f"Renamed project to: {new_name.strip()}"
    refresh_data(state)


def move_project_interactive(state: AppState, target_id_str: str) -> None:
    if state.selected_project_id is None:
        state.status_message = "No project selected."
        return
    target_id_str = target_id_str.strip().lower()
    if target_id_str in ("0", "root"):
        target_id: Optional[int] = None
        target_label = "root"
    else:
        try:
            target_id = int(target_id_str)
            target_project = state.db.get_project(target_id)
            if target_project is None:
                state.status_message = f"Target project #{target_id} not found."
                return
            target_label = target_project.name
        except ValueError:
            state.status_message = f"Invalid target project id: '{target_id_str}'"
            return

    state.db.move_project(state.selected_project_id, target_id)
    state.status_message = f"Moved project under: {target_label}"
    refresh_data(state)


def delete_selected_project(state: AppState) -> None:
    if state.selected_project_id is None:
        state.status_message = "No project selected."
        return
    pid = state.selected_project_id
    project = state.db.get_project(pid)
    name = project.name if project else f"#{pid}"
    state.db.delete_project(pid)
    state.selected_project_id = None
    state.status_message = f"Deleted project: {name}"
    refresh_data(state)


def reorder_selected_project(state: AppState, direction: str) -> None:
    if state.selected_project_id is None:
        state.status_message = "No project selected."
        return
    state.db.reorder_project(state.selected_project_id, direction)
    state.status_message = f"Moved project {direction}."
    refresh_data(state)


def render_layout(state: AppState) -> Layout:
    layout = Layout()
    layout.split_column(
        Layout(name="body", ratio=1),
        Layout(name="status", size=3),
    )
    layout["body"].split_row(
        Layout(name="projects", size=32),
        Layout(name="tasks", ratio=2),
        Layout(name="detail", ratio=2),
    )
    layout["projects"].update(render_projects_panel(state))
    layout["tasks"].update(render_tasks_panel(state))
    layout["detail"].update(render_detail_panel(state))
    layout["status"].update(render_status_bar(state))
    return layout


def run() -> None:
    console = Console()
    config = load_config()
    db = Database(get_db_path())
    db.init_db()

    if not db.list_projects():
        db.create_project(Project(name="工作", sort_order=0))
        db.create_project(Project(name="个人", sort_order=1))
        db.create_project(Project(name="学习", sort_order=2))

    try:
        theme = get_theme(config.theme)
    except ValueError:
        theme = get_theme("dracula")

    state = AppState(db=db, config=config, theme=theme)
    refresh_data(state)

    kb = KeyBindings()
    prompt_session: PromptSession = PromptSession(key_bindings=kb)

    running = True

    while running:
        try:
            console.clear()
            layout = render_layout(state)
            console.print(layout)

            prompt_session: PromptSession = PromptSession()
            cmd = prompt_session.prompt("> ", key_bindings=None).strip().lower()

            if cmd in ("q", "quit", "exit"):
                running = False
            elif cmd in ("?", "help"):
                state.status_message = "Commands: q=quit, a=add task, c=complete, d=delete task, n=note, /=search, p add/rename/move/delete/up/down=projects, 1/2/3=views, [/]=calendar, space=collapse"
            elif cmd == "a":
                add_task_interactive(state, console)
            elif cmd == "c":
                complete_selected_task(state)
            elif cmd == "d":
                delete_selected_task(state)
            elif cmd == "n":
                add_note_interactive(state, console)
            elif cmd == "/":
                search_interactive(state, console)
            elif cmd == "escape" or cmd == "esc":
                state.search_query = ""
                state.status_message = "Search cleared."
            elif cmd == "1":
                state.task_view = "list"
                state.status_message = "View: List"
            elif cmd == "2":
                state.task_view = "kanban"
                state.status_message = "View: Kanban"
            elif cmd == "3":
                state.task_view = "calendar"
                state.status_message = "View: Calendar"
            elif cmd == "[":
                state.calendar_offset -= 1
                state.status_message = f"Calendar: week {state.calendar_offset}"
            elif cmd == "]":
                state.calendar_offset += 1
                state.status_message = f"Calendar: week {state.calendar_offset}"
            elif cmd == "space":
                if state.focus_panel == "projects":
                    toggle_project_collapse(state)
            elif cmd == "tab":
                panels = ["projects", "tasks", "detail"]
                i = panels.index(state.focus_panel) if state.focus_panel in panels else 0
                state.focus_panel = panels[(i + 1) % len(panels)]
                state.status_message = f"Focus: {state.focus_panel}"
            elif cmd in ("k", "up"):
                if state.focus_panel == "projects":
                    navigate_projects(state, -1)
                else:
                    navigate_tasks(state, -1)
            elif cmd in ("j", "down"):
                if state.focus_panel == "projects":
                    navigate_projects(state, 1)
                else:
                    navigate_tasks(state, 1)
            elif cmd == "r":
                refresh_data(state)
                state.status_message = "Refreshed."
            elif cmd.startswith("select "):
                try:
                    tid = int(cmd.split()[1])
                    if any(t.id == tid for t in state.tasks):
                        state.selected_task_id = tid
                        state.status_message = f"Selected task #{tid}"
                except (ValueError, IndexError):
                    state.status_message = "Invalid select command. Use: select <task_id>"
            elif cmd.startswith("p "):
                parts = cmd[2:].strip()
                if not parts:
                    state.status_message = "Project commands: p add/rename/move/delete/up/down"
                else:
                    subparts = parts.split(None, 1)
                    subcmd = subparts[0]
                    arg = subparts[1] if len(subparts) > 1 else None
                    if subcmd == "add":
                        add_project_interactive(state, arg)
                    elif subcmd == "rename":
                        rename_project_interactive(state, arg)
                    elif subcmd == "move":
                        if arg:
                            move_project_interactive(state, arg)
                        else:
                            state.status_message = "Usage: p move <target_project_id> (or 0/root)"
                    elif subcmd == "delete":
                        delete_selected_project(state)
                    elif subcmd == "up":
                        reorder_selected_project(state, "up")
                    elif subcmd == "down":
                        reorder_selected_project(state, "down")
                    else:
                        state.status_message = f"Unknown project command: '{subcmd}'. Use: p add/rename/move/delete/up/down"
            elif cmd == "":
                pass
            else:
                state.status_message = f"Unknown command: '{cmd}'. Type ? for help."

        except (EOFError, KeyboardInterrupt):
            running = False

    console.clear()
    console.print(Panel(Text("👋 Goodbye from TaskFlow!", style="bold cyan"), border_style="cyan"))
