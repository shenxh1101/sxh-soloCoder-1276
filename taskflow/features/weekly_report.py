from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

from rich.console import RenderableType
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from taskflow.db import Database


class WeeklyReport:
    def __init__(self, db: Database) -> None:
        self.db = db

    def _week_range(self, week_start: Optional[date] = None) -> tuple[date, date]:
        if week_start is None:
            week_start = date.today() - timedelta(days=date.today().weekday())
        week_end = week_start + timedelta(days=6)
        return week_start, week_end

    def _fetch_completed(self, start: date, end: date) -> list[dict]:
        return self.db.query_all(
            "SELECT t.*, p.name AS project_name FROM tasks t "
            "LEFT JOIN projects p ON t.project_id = p.id "
            "WHERE t.status = 'done' AND t.completed_at >= ? AND t.completed_at <= ? "
            "ORDER BY p.name, t.completed_at",
            (start.isoformat(), f"{end.isoformat()}T23:59:59"),
        )

    def _fetch_created(self, start: date, end: date) -> list[dict]:
        return self.db.query_all(
            "SELECT * FROM tasks WHERE created_at >= ? AND created_at <= ?",
            (start.isoformat(), f"{end.isoformat()}T23:59:59"),
        )

    def _fetch_pomodoro_summary(self, start: date, end: date) -> list[dict]:
        return self.db.query_all(
            "SELECT t.id AS task_id, t.title, SUM(p.duration_minutes) AS total_minutes "
            "FROM pomodoro_sessions p JOIN tasks t ON p.task_id = t.id "
            "WHERE p.completed = 1 AND p.started_at >= ? AND p.started_at <= ? "
            "GROUP BY p.task_id ORDER BY total_minutes DESC",
            (start.isoformat(), f"{end.isoformat()}T23:59:59"),
        )

    def _fetch_overdue(self, end: date) -> list[dict]:
        return self.db.query_all(
            "SELECT * FROM tasks WHERE status != 'done' AND due_date < ? AND due_date IS NOT NULL "
            "ORDER BY due_date",
            (end.isoformat(),),
        )

    def _fetch_next_week(self, week_end: date) -> list[dict]:
        next_start = week_end + timedelta(days=1)
        next_end = next_start + timedelta(days=6)
        return self.db.query_all(
            "SELECT * FROM tasks WHERE status != 'done' AND due_date >= ? AND due_date <= ? "
            "ORDER BY due_date",
            (next_start.isoformat(), next_end.isoformat()),
        )

    def _fetch_this_week_plan(self, start: date, end: date) -> list[dict]:
        return self.db.query_all(
            "SELECT * FROM tasks WHERE status != 'done' AND due_date IS NOT NULL AND due_date >= ? AND due_date <= ? "
            "ORDER BY due_date",
            (start.isoformat(), end.isoformat()),
        )

    def _priority_distribution(self, created: list[dict]) -> dict[str, int]:
        dist: dict[str, int] = {}
        for row in created:
            p = row.get("priority", "none") or "none"
            dist[p] = dist.get(p, 0) + 1
        return dist

    def generate(self, week_start: Optional[date] = None) -> str:
        start, end = self._week_range(week_start)
        completed = self._fetch_completed(start, end)
        created = self._fetch_created(start, end)
        pomodoro = self._fetch_pomodoro_summary(start, end)
        overdue = self._fetch_overdue(end)
        next_week = self._fetch_next_week(end)
        this_week_plan = self._fetch_this_week_plan(start, end)
        total_completed = len(completed)
        total_created = len(created)
        completion_rate = (total_completed / total_created * 100) if total_created else 0.0
        pri_dist = self._priority_distribution(created)

        task_minutes: dict[int, int] = {}
        for p in pomodoro:
            tid = p.get("task_id")
            if tid is not None:
                task_minutes[tid] = p.get("total_minutes", 0) or 0

        lines: list[str] = []
        lines.append(f"# Weekly Report: {start.isoformat()} ~ {end.isoformat()}")
        lines.append("")

        lines.append("## Summary")
        lines.append(f"- Tasks completed: **{total_completed}**")
        lines.append(f"- Tasks created: **{total_created}**")
        lines.append(f"- Completion rate: **{completion_rate:.1f}%**")
        lines.append("")

        lines.append("## Completed Tasks")
        current_project: str | None = None
        for row in completed:
            proj = row.get("project_name") or "No Project"
            if proj != current_project:
                lines.append(f"### {proj}")
                current_project = proj
            tid = row.get("id")
            minutes = task_minutes.get(tid, 0) if tid is not None else 0
            if minutes > 0:
                hours = minutes / 60
                lines.append(f"- {row['title']} ({hours:.1f}h)")
            else:
                lines.append(f"- {row['title']}")
        lines.append("")

        lines.append("## This Week Plan")
        if this_week_plan:
            for row in this_week_plan:
                due_display = row.get("due_date") or ""
                if row.get("due_time"):
                    due_display = f"{due_display} {row['due_time'][:5]}" if due_display else row["due_time"][:5]
                priority = row.get("priority", "none") or "none"
                if priority == "urgent_important":
                    pri_label = "🔴"
                elif priority == "not_urgent_important":
                    pri_label = "🟡"
                elif priority == "urgent_not_important":
                    pri_label = "🟠"
                else:
                    pri_label = "⚪"
                lines.append(f"- [{pri_label}] {row['title']} (到期: {due_display})")
        else:
            lines.append("- (none)")
        lines.append("")

        lines.append("## Time Tracking")
        total_hours = 0.0
        for row in pomodoro:
            hours = (row["total_minutes"] or 0) / 60
            total_hours += hours
            lines.append(f"- {row['title']}: {hours:.1f}h")
        lines.append(f"\n**Total:** {total_hours:.1f}h")
        lines.append("")

        lines.append("## Priority Distribution")
        for priority, count in sorted(pri_dist.items()):
            lines.append(f"- {priority}: {count}")
        lines.append("")

        if overdue:
            lines.append("## Overdue Tasks")
            for row in overdue:
                due_display = row.get("due_date") or ""
                if row.get("due_time"):
                    due_display = f"{due_display} {row['due_time'][:5]}" if due_display else row["due_time"][:5]
                lines.append(f"- {row['title']} (due: {due_display})")
            lines.append("")

        if next_week:
            lines.append("## Next Week Plan")
            for row in next_week:
                due_display = row.get("due_date") or ""
                if row.get("due_time"):
                    due_display = f"{due_display} {row['due_time'][:5]}" if due_display else row["due_time"][:5]
                lines.append(f"- {row['title']} (due: {due_display})")
            lines.append("")

        return "\n".join(lines)

    def format_as_rich(self, week_start: Optional[date] = None) -> RenderableType:
        start, end = self._week_range(week_start)
        completed = self._fetch_completed(start, end)
        created = self._fetch_created(start, end)
        pomodoro = self._fetch_pomodoro_summary(start, end)
        overdue = self._fetch_overdue(end)
        next_week = self._fetch_next_week(end)
        this_week_plan = self._fetch_this_week_plan(start, end)
        total_completed = len(completed)
        total_created = len(created)
        completion_rate = (total_completed / total_created * 100) if total_created else 0.0
        pri_dist = self._priority_distribution(created)

        task_minutes: dict[int, int] = {}
        for p in pomodoro:
            tid = p.get("task_id")
            if tid is not None:
                task_minutes[tid] = p.get("total_minutes", 0) or 0

        header = Panel(
            Text(f"Weekly Report: {start.isoformat()} ~ {end.isoformat()}", style="bold cyan", justify="center"),
            style="cyan",
        )

        summary_table = Table(title="Summary", show_header=True)
        summary_table.add_column("Metric", style="bold")
        summary_table.add_column("Value", justify="right")
        summary_table.add_row("Tasks Completed", str(total_completed))
        summary_table.add_row("Tasks Created", str(total_created))
        summary_table.add_row("Completion Rate", f"{completion_rate:.1f}%")

        completed_table = Table(title="Completed Tasks", show_header=True)
        completed_table.add_column("Project", style="magenta")
        completed_table.add_column("Task")
        completed_table.add_column("Time", justify="right", style="green")
        for row in completed:
            tid = row.get("id")
            minutes = task_minutes.get(tid, 0) if tid is not None else 0
            time_str = f"{minutes / 60:.1f}h" if minutes > 0 else ""
            completed_table.add_row(row.get("project_name") or "No Project", row["title"], time_str)

        plan_table = Table(title="This Week Plan", show_header=True)
        plan_table.add_column("Due", style="cyan")
        plan_table.add_column("Task Title")
        plan_table.add_column("Priority")
        if this_week_plan:
            for row in this_week_plan:
                due_display = row.get("due_date") or ""
                if row.get("due_time"):
                    due_display = f"{due_display} {row['due_time'][:5]}" if due_display else row["due_time"][:5]
                priority = row.get("priority", "none") or "none"
                if priority == "urgent_important":
                    pri_label = "🔴"
                elif priority == "not_urgent_important":
                    pri_label = "🟡"
                elif priority == "urgent_not_important":
                    pri_label = "🟠"
                else:
                    pri_label = "⚪"
                plan_table.add_row(due_display, row["title"], pri_label)
        else:
            plan_table.add_row("", "(no planned tasks)", "")

        time_table = Table(title="Time Tracking (Pomodoro)", show_header=True)
        time_table.add_column("Task")
        time_table.add_column("Hours", justify="right", style="green")
        total_hours = 0.0
        for row in pomodoro:
            hours = (row["total_minutes"] or 0) / 60
            total_hours += hours
            time_table.add_row(row["title"], f"{hours:.1f}h")
        time_table.add_row("[bold]Total[/bold]", f"[bold green]{total_hours:.1f}h[/bold green]")

        pri_table = Table(title="Priority Distribution", show_header=True)
        pri_table.add_column("Priority", style="yellow")
        pri_table.add_column("Count", justify="right")
        for priority, count in sorted(pri_dist.items()):
            pri_table.add_row(priority, str(count))

        overdue_table = None
        if overdue:
            overdue_table = Table(title="Overdue Tasks", show_header=True)
            overdue_table.add_column("Task", style="red")
            overdue_table.add_column("Due Date", style="red")
            for row in overdue:
                due_display = row.get("due_date") or ""
                if row.get("due_time"):
                    due_display = f"{due_display} {row['due_time'][:5]}" if due_display else row["due_time"][:5]
                overdue_table.add_row(row["title"], due_display)

        next_table = None
        if next_week:
            next_table = Table(title="Next Week Plan", show_header=True)
            next_table.add_column("Task", style="blue")
            next_table.add_column("Due Date")
            for row in next_week:
                due_display = row.get("due_date") or ""
                if row.get("due_time"):
                    due_display = f"{due_display} {row['due_time'][:5]}" if due_display else row["due_time"][:5]
                next_table.add_row(row["title"], due_display)

        md_content = self.generate(week_start)
        markdown_panel = Panel(Markdown(md_content), title="Full Report", border_style="dim")

        from rich.console import Group

        elements: list[RenderableType] = [header, summary_table, completed_table, plan_table, time_table, pri_table]
        if overdue_table is not None:
            elements.append(overdue_table)
        if next_table is not None:
            elements.append(next_table)
        elements.append(markdown_panel)
        return Group(*elements)
