from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

import typer
from rapidfuzz import fuzz
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from taskflow.config import Config, get_db_path, load_config, save_config
from taskflow.db import Database
from taskflow.db.models import Project, Reminder, Tag, Task
from taskflow.features.nlp_parser import parse_natural_task
from taskflow.features.pomodoro import PomodoroStats, PomodoroTimer
from taskflow.features.reminder import ReminderManager
from taskflow.features.search import SearchEngine
from taskflow.features.sync import SyncManager
from taskflow.features.themes import BUILT_IN_THEMES, Theme, get_theme, list_themes
from taskflow.features.weekly_report import WeeklyReport

app = typer.Typer(add_completion=False, no_args_is_help=False)
console = Console()


def _get_next_sort_order(db: Database, project_id: Optional[int]) -> int:
    if project_id is not None:
        tasks = db.get_tasks_by_project(project_id)
    else:
        all_tasks = db.get_all_tasks()
        tasks = [t for t in all_tasks if t.project_id is None]
    if not tasks:
        return 0
    return max(t.sort_order for t in tasks) + 1


def _tasks_by_status(db: Database, status: str) -> list[Task]:
    return db.get_tasks_by_status(status)


def _fuzzy_search(db: Database, query: str, limit: int = 20) -> list[dict]:
    if not query.strip():
        return []

    field_weights: dict[str, float] = {
        "title": 3.0,
        "project": 2.0,
        "tags": 2.0,
        "notes": 1.0,
    }

    items: list[dict] = []
    tasks = db.get_all_tasks()
    for task in tasks:
        details = db.get_task_with_details(task.id) if task.id else None
        entry: dict = {
            "task_id": task.id,
            "title": task.title,
            "notes": "",
            "tags": "",
            "project": "",
        }
        if details:
            notes_list = details.get("notes", [])
            try:
                entry["notes"] = " ".join(str(n.get("content", "")) for n in notes_list)
            except (TypeError, AttributeError):
                entry["notes"] = str(notes_list)
            tags_list = details.get("tags", [])
            try:
                entry["tags"] = " ".join(str(t.get("name", "")) for t in tags_list)
            except (TypeError, AttributeError):
                entry["tags"] = str(tags_list)
            entry["project"] = details.get("project_name", "") or ""
        items.append(entry)

    results: list[dict] = []
    for item in items:
        best_score = 0.0
        best_field = ""
        for field, weight in field_weights.items():
            field_value = item.get(field, "")
            if not field_value:
                continue
            score = fuzz.token_sort_ratio(query, field_value) * weight
            if score > best_score:
                best_score = score
                best_field = field
        if best_score > 0:
            results.append({
                "item": item,
                "score": best_score,
                "matched_field": best_field,
            })

    results.sort(key=lambda r: r["score"], reverse=True)
    return results[:limit]


def _week_range(week_start: Optional[date] = None) -> tuple[date, date]:
    if week_start is None:
        week_start = date.today() - timedelta(days=date.today().weekday())
    week_end = week_start + timedelta(days=6)
    return week_start, week_end


@app.callback(invoke_without_command=True)
def tui(ctx: typer.Context) -> None:
    if ctx.invoked_subcommand is None:
        try:
            from taskflow.tui import run
            run()
        except ImportError:
            console.print("[yellow]TUI not available. Use --help to see available commands.[/yellow]")


@app.command()
def add(
    text: str,
    recur: Optional[str] = typer.Option(None, "--recur", help="Recurrence rule: daily, mon/tue/wed/thu/fri/sat/sun, or day number (1-31) for monthly"),
) -> None:
    config = load_config()
    db = Database(get_db_path())
    db.init_db()

    result = parse_natural_task(text)

    if recur:
        recur_lower = recur.lower()
        weekday_map = {
            "mon": 0, "tue": 1, "wed": 2, "thu": 3,
            "fri": 4, "sat": 5, "sun": 6,
        }
        if recur_lower == "daily":
            result.recurrence_rule = "daily"
        elif recur_lower in weekday_map:
            result.recurrence_rule = f"weekly:{weekday_map[recur_lower]}"
        else:
            try:
                day = int(recur_lower)
                if 1 <= day <= 31:
                    result.recurrence_rule = f"monthly:{day}"
            except ValueError:
                pass

    project_id: Optional[int] = None
    if result.project:
        project = db.get_or_create_project(result.project)
        project_id = project.id

    sort_order = _get_next_sort_order(db, project_id)

    reminder_minutes_before: Optional[int] = None
    if result.due_date is not None or result.due_time is not None:
        reminder_minutes_before = 15

    task = Task(
        title=result.title,
        project_id=project_id,
        status="todo",
        priority=result.priority,
        due_date=result.due_date.isoformat() if result.due_date else None,
        due_time=result.due_time.isoformat() if result.due_time else None,
        reminder_minutes_before=reminder_minutes_before,
        sort_order=sort_order,
        recurrence_rule=result.recurrence_rule,
    )
    task_id = db.create_task(task)

    for tag_name in result.tags:
        tag = db.get_or_create_tag(tag_name)
        if tag.id is not None:
            db.add_task_tag(task_id, tag.id)

    if result.due_date is not None and reminder_minutes_before is not None:
        due_dt = datetime.combine(result.due_date, result.due_time or datetime.min.time())
        remind_at = due_dt - timedelta(minutes=reminder_minutes_before)
        reminder = Reminder(
            task_id=task_id,
            remind_at=remind_at.isoformat(),
            dismissed=False,
        )
        db.create_reminder(reminder)

    table = Table(title="Task Created", show_header=True)
    table.add_column("Field", style="bold")
    table.add_column("Value")
    table.add_row("ID", str(task_id))
    table.add_row("Title", result.title)
    if result.project:
        table.add_row("Project", result.project)
    if result.priority:
        table.add_row("Priority", result.priority)
    if result.due_date:
        table.add_row("Due Date", result.due_date.isoformat())
    if result.due_time:
        table.add_row("Due Time", result.due_time.isoformat()[:5])
    if result.recurrence_rule:
        table.add_row("Recurrence", result.recurrence_rule)
    if result.tags:
        table.add_row("Tags", ", ".join(result.tags))
    console.print(table)


@app.command()
def complete(task_id: int) -> None:
    config = load_config()
    db = Database(get_db_path())
    db.init_db()

    task = db.get_task(task_id)
    if task is None:
        console.print(f"[red]Task {task_id} not found[/red]")
        raise typer.Exit(1)

    task.status = "done"
    task.completed_at = datetime.now().isoformat()
    db.update_task(task)

    console.print(f"[green]Task {task_id} marked as complete:[/green] {task.title}")

    new_id = db.generate_next_recurring(task_id)
    if new_id is not None:
        console.print(f"[cyan]Next recurring occurrence created: task #{new_id}[/cyan]")


@app.command()
def list(
    status: Optional[str] = None,
    project: Optional[str] = None,
    today: bool = typer.Option(False, "--today", help="Show tasks due today"),
    this_week: bool = typer.Option(False, "--this-week", help="Show tasks due this week (Mon-Sun)"),
    overdue: bool = typer.Option(False, "--overdue", help="Show overdue tasks"),
    priority: Optional[str] = typer.Option(None, "--priority", help="Filter by priority: urgent_important|not_urgent_important|urgent_not_important|not_urgent_not_important"),
) -> None:
    config = load_config()
    db = Database(get_db_path())
    db.init_db()

    tasks = db.get_all_tasks()

    if status:
        tasks = [t for t in tasks if t.status == status]

    if project:
        proj = db.get_project_by_name(project)
        if proj is None:
            console.print(f"[red]Project '{project}' not found[/red]")
            raise typer.Exit(1)
        tasks = [t for t in tasks if t.project_id == proj.id]

    today_date = date.today()
    week_start = today_date - timedelta(days=today_date.weekday())
    week_end = week_start + timedelta(days=6)
    today_iso = today_date.isoformat()
    week_start_iso = week_start.isoformat()
    week_end_iso = week_end.isoformat()

    if today:
        tasks = [t for t in tasks if t.due_date == today_iso]

    if this_week:
        tasks = [t for t in tasks if t.due_date is not None and week_start_iso <= t.due_date <= week_end_iso]

    if overdue:
        tasks = [t for t in tasks if t.status != 'done' and t.due_date is not None and t.due_date < today_iso]

    if priority:
        tasks = [t for t in tasks if t.priority == priority]

    table = Table(title="Tasks", show_header=True)
    table.add_column("ID", justify="right")
    table.add_column("Title")
    table.add_column("Status")
    table.add_column("Priority")
    table.add_column("Due Date")
    table.add_column("Project")

    for task in tasks:
        proj_name = ""
        if task.project_id:
            proj = db.get_project(task.project_id)
            if proj:
                proj_name = proj.name
        due = task.due_date or ""
        if task.due_time:
            due = f"{due} {task.due_time[:5]}" if due else task.due_time[:5]
        table.add_row(
            str(task.id) if task.id else "",
            task.title,
            task.status,
            task.priority or "",
            due,
            proj_name,
        )

    if not tasks:
        console.print("[yellow]No tasks found[/yellow]")
    else:
        console.print(table)


@app.command()
def search(query: str) -> None:
    config = load_config()
    db = Database(get_db_path())
    db.init_db()

    results = _fuzzy_search(db, query)

    table = Table(title=f"Search Results for '{query}'", show_header=True)
    table.add_column("ID", justify="right")
    table.add_column("Title")
    table.add_column("Due")
    table.add_column("Matched Field")
    table.add_column("Score", justify="right")

    for r in results:
        item = r["item"]
        task_id = item.get("task_id")
        task = db.get_task(task_id) if task_id else None
        due = ""
        if task:
            due = task.due_date or ""
            if task.due_time:
                due = f"{due} {task.due_time[:5]}" if due else task.due_time[:5]
        table.add_row(
            str(item.get("task_id", "")),
            item.get("title", ""),
            due,
            r["matched_field"],
            f"{r['score']:.1f}",
        )

    if not results:
        console.print(f"[yellow]No results found for '{query}'[/yellow]")
    else:
        console.print(table)


@app.command()
def report(
    week: Optional[str] = None,
    format: str = typer.Option("rich", "--format", "-f", help="rich|markdown|json"),
    output: Optional[str] = typer.Option(None, "--output", "-o", help="output file path (auto-named if not provided)"),
) -> None:
    config = load_config()
    db = Database(get_db_path())
    db.init_db()

    week_start: Optional[date] = None
    if week:
        try:
            week_start = date.fromisoformat(week)
        except ValueError:
            console.print(f"[red]Invalid week date: {week}. Use ISO format YYYY-MM-DD[/red]")
            raise typer.Exit(1)

    actual_week_start, actual_week_end = _week_range(week_start)
    weekly_report = WeeklyReport(db)

    if format == "rich":
        console.print(weekly_report.format_as_rich(week_start))
    elif format == "markdown":
        md_content = weekly_report.generate(week_start)
        if output:
            filepath = output
        else:
            filepath = f"weekly-report-{actual_week_start.isoformat()}-to-{actual_week_end.isoformat()}.md"
        Path(filepath).write_text(md_content, encoding="utf-8")
        console.print(f"[green]Report exported to: {filepath}[/green]")
    elif format == "json":
        data = weekly_report.to_dict(week_start)
        json_content = json.dumps(data, indent=2, ensure_ascii=False)
        if output:
            filepath = output
        else:
            filepath = f"weekly-report-{actual_week_start.isoformat()}-to-{actual_week_end.isoformat()}.json"
        Path(filepath).write_text(json_content, encoding="utf-8")
        console.print(f"[green]Report exported to: {filepath}[/green]")
    else:
        console.print(f"[red]Unknown format: {format}[/red]")
        raise typer.Exit(1)


@app.command()
def sync(
    push: bool = False,
    pull: bool = False,
) -> None:
    config = load_config()
    db_path = get_db_path()
    sync_mgr = SyncManager(db_path, config)

    if not sync_mgr.is_configured:
        if config.sync_method == "none":
            console.print("[yellow]未配置同步。如需启用，请先运行: config-set sync_method git|webdav[/yellow]")
        else:
            console.print("[red]同步配置不完整：缺少 sync_url[/red]")
            console.print(f"[yellow]请运行: config-set sync_url <地址> 来设置 {config.sync_method} 同步地址[/yellow]")
        raise typer.Exit(0)

    if not push and not pull:
        push = True
        pull = True

    pull_ok = True
    push_ok = True

    if pull:
        pull_ok = sync_mgr.sync_pull()
        if pull_ok:
            console.print("[green]Sync pull successful[/green]")
        else:
            console.print("[red]Sync pull failed[/red]")

    if push:
        push_ok = sync_mgr.sync_push()
        if push_ok:
            console.print("[green]Sync push successful[/green]")
        else:
            console.print("[red]Sync push failed[/red]")

    if pull_ok and push_ok:
        console.print("[bold green]Sync completed successfully[/bold green]")
    else:
        console.print("[bold red]Sync completed with errors[/bold red]")
        raise typer.Exit(1)


@app.command()
def pomodoro(
    task_id: Optional[int] = None,
    action: str = "start",
) -> None:
    config = load_config()
    db = Database(get_db_path())
    db.init_db()

    valid_actions = ["start", "pause", "resume", "cancel", "complete", "stats"]
    if action not in valid_actions:
        console.print(f"[red]Invalid action '{action}'. Must be one of: {', '.join(valid_actions)}[/red]")
        raise typer.Exit(1)

    if action == "stats":
        stats = PomodoroStats(db).get_this_week_stats()

        table = Table(title="Pomodoro Stats (This Week)", show_header=True)
        table.add_column("Metric", style="bold")
        table.add_column("Value", justify="right")
        table.add_row("Week Range", f"{stats['week_start']} ~ {stats['week_end']}")
        table.add_row("Completed Sessions", str(stats["total_sessions"]))
        table.add_row("Completed Minutes", str(stats["total_minutes"]))
        console.print(table)

        if stats["per_task"]:
            task_table = Table(title="By Task", show_header=True)
            task_table.add_column("Task")
            task_table.add_column("Sessions", justify="right")
            task_table.add_column("Minutes", justify="right")
            for item in stats["per_task"]:
                task_table.add_row(f"{item['task_id']}: {item['title']}", str(item["sessions"]), str(item["minutes"]))
            console.print(task_table)

        day_table = Table(title="By Day", show_header=True)
        day_table.add_column("Day", style="bold")
        day_table.add_column("Minutes", justify="right")
        for day_name in ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]:
            day_table.add_row(day_name, str(stats["per_day"][day_name]))
        console.print(day_table)
        return

    if action == "start":
        if task_id is None:
            console.print("[red]task_id is required for 'start' action[/red]")
            raise typer.Exit(1)
        task = db.get_task(task_id)
        if task is None:
            console.print(f"[red]Task {task_id} not found[/red]")
            raise typer.Exit(1)

        duration = config.pomodoro_duration
        from taskflow.db.models import PomodoroSession as DBPomodoroSession
        session = DBPomodoroSession(
            task_id=task_id,
            started_at=datetime.now().isoformat(),
            duration_minutes=duration,
            completed=False,
        )
        db.add_pomodoro_session(session)
        console.print(f"[green]Pomodoro started for task {task_id}:[/green] {task.title}")
        console.print(f"[cyan]Duration: {duration} minutes[/cyan]")
        bar = ""
        filled = 0
        total = 20
        bar = "█" * filled + "░" * (total - filled)
        console.print(f"[{bar}] 0%")
        return

    if action == "pause":
        console.print("[yellow]Pomodoro paused[/yellow]")
        return

    if action == "resume":
        console.print("[green]Pomodoro resumed[/green]")
        return

    if action == "cancel":
        pending = db.query_all(
            "SELECT * FROM pomodoro_sessions WHERE completed = 0 ORDER BY started_at DESC LIMIT 1"
        )
        if not pending:
            console.print("[yellow]No pending pomodoro session to cancel[/yellow]")
            return
        session_id = pending[0]["id"]
        db.delete_pomodoro_session(session_id)
        console.print(f"[red]Pomodoro session {session_id} cancelled[/red]")
        return

    if action == "complete":
        if task_id is not None:
            pending = db.query_all(
                "SELECT * FROM pomodoro_sessions WHERE completed = 0 AND task_id = ? ORDER BY started_at DESC LIMIT 1",
                (task_id,),
            )
        else:
            pending = db.query_all(
                "SELECT * FROM pomodoro_sessions WHERE completed = 0 ORDER BY started_at DESC LIMIT 1"
            )
        if not pending:
            console.print("[yellow]No pending pomodoro session found[/yellow]")
            return
        from taskflow.db.models import PomodoroSession as DBPomodoroSession
        row = pending[0]
        session = DBPomodoroSession(
            id=row["id"],
            task_id=row["task_id"],
            started_at=row["started_at"],
            duration_minutes=row["duration_minutes"],
            completed=True,
        )
        db.update_pomodoro_session(session)
        task = db.get_task(session.task_id) if session.task_id else None
        task_title = task.title if task else "(unknown)"
        console.print(f"[green]Pomodoro session {session.id} marked as complete:[/green] {task_title}")
        return


@app.command("config-show")
def config_show() -> None:
    config = load_config()

    table = Table(title="Current Configuration", show_header=True)
    table.add_column("Key", style="bold")
    table.add_column("Value")
    table.add_row("theme", config.theme)
    table.add_row("sync_method", config.sync_method)
    table.add_row("sync_url", config.sync_url)
    table.add_row("pomodoro_duration", str(config.pomodoro_duration))
    table.add_row("pomodoro_break", str(config.pomodoro_break))
    table.add_row("pomodoro_long_break", str(config.pomodoro_long_break))
    table.add_row("default_view", config.default_view)
    table.add_row("language", config.language)
    console.print(table)

    themes = list_themes()
    theme_table = Table(title="Available Themes", show_header=True)
    theme_table.add_column("Theme Name", style="bold cyan")
    theme_table.add_column("Type")
    for name in themes:
        theme_type = "Built-in" if name in BUILT_IN_THEMES else "Custom"
        theme_table.add_row(name, theme_type)
    console.print(theme_table)


@app.command("config-set")
def config_set(key: str, value: str) -> None:
    valid_keys = ["theme", "sync_method", "sync_url", "pomodoro_duration", "default_view", "language"]
    if key not in valid_keys:
        console.print(f"[red]Invalid config key '{key}'. Must be one of: {', '.join(valid_keys)}[/red]")
        raise typer.Exit(1)

    config = load_config()

    if key == "theme":
        available = list_themes()
        if value not in available:
            console.print(f"[red]Unknown theme '{value}'. Available: {', '.join(available)}[/red]")
            raise typer.Exit(1)
        config.theme = value
    elif key == "sync_method":
        if value not in ["none", "git", "webdav"]:
            console.print("[red]sync_method must be one of: none, git, webdav[/red]")
            raise typer.Exit(1)
        config.sync_method = value
    elif key == "sync_url":
        config.sync_url = value
    elif key == "pomodoro_duration":
        try:
            config.pomodoro_duration = int(value)
        except ValueError:
            console.print("[red]pomodoro_duration must be an integer[/red]")
            raise typer.Exit(1)
    elif key == "default_view":
        config.default_view = value
    elif key == "language":
        config.language = value

    save_config(config)
    console.print(f"[green]Config updated: {key} = {value}[/green]")


@app.command("reminder-check")
def reminder_check() -> None:
    config = load_config()
    db = Database(get_db_path())
    db.init_db()

    upcoming = db.get_upcoming_reminders(days=7)
    pending = db.get_pending_reminders()

    if not upcoming and not pending:
        console.print("[green]No upcoming reminders[/green]")
        return

    table = Table(title="Reminders", show_header=True)
    table.add_column("Status", width=8)
    table.add_column("Task ID", justify="right")
    table.add_column("Task Title")
    table.add_column("Remind At")
    table.add_column("Due")

    for reminder in pending:
        task = db.get_task(reminder.task_id) if reminder.task_id else None
        task_title = task.title if task else "(unknown)"
        remind_at_str = reminder.remind_at.replace("T", " ")[:16] if reminder.remind_at else ""
        due = ""
        if task:
            due = task.due_date or ""
            if task.due_time:
                due = f"{due} {task.due_time[:5]}" if due else task.due_time[:5]
        table.add_row(
            Text("DUE", style="bold red"),
            str(reminder.task_id),
            task_title,
            remind_at_str,
            due,
        )
        reminder.dismissed = True
        db.update_reminder(reminder)

    pending_ids = {r.id for r in pending}
    for reminder in upcoming:
        if reminder.id in pending_ids or reminder.id is None:
            continue
        task = db.get_task(reminder.task_id) if reminder.task_id else None
        task_title = task.title if task else "(unknown)"
        remind_at_str = reminder.remind_at.replace("T", " ")[:16] if reminder.remind_at else ""
        due = ""
        if task:
            due = task.due_date or ""
            if task.due_time:
                due = f"{due} {task.due_time[:5]}" if due else task.due_time[:5]
        table.add_row(
            Text("SOON", style="yellow"),
            str(reminder.task_id),
            task_title,
            remind_at_str,
            due,
        )

    console.print(table)


if __name__ == "__main__":
    app()
