from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from rapidfuzz import fuzz

if TYPE_CHECKING:
    from taskflow.core.db import Database


@dataclass
class SearchResult:
    item: dict
    score: float
    matched_field: str


class SearchEngine:
    FIELD_WEIGHTS: dict[str, float] = {
        "title": 3.0,
        "project": 2.0,
        "tags": 2.0,
        "notes": 1.0,
        "attachments": 1.0,
    }

    def __init__(self, db: Database) -> None:
        self.db = db
        self._items: list[dict] = []

    def _index_items(self) -> list[dict]:
        items: list[dict] = []
        tasks = self.db.get_all_tasks()
        for task in tasks:
            entry: dict = {
                "task_id": task.get("id"),
                "title": task.get("title", ""),
                "notes": "",
                "tags": "",
                "project": "",
                "attachments": "",
            }
            notes = task.get("notes") or task.get("note") or ""
            if isinstance(notes, list):
                notes = " ".join(str(n) for n in notes)
            entry["notes"] = str(notes)

            tags = task.get("tags") or []
            if isinstance(tags, str):
                entry["tags"] = tags
            elif isinstance(tags, list):
                entry["tags"] = " ".join(str(t) for t in tags)

            project = task.get("project") or task.get("project_name") or ""
            entry["project"] = str(project)

            attachments = task.get("attachments") or []
            if isinstance(attachments, str):
                entry["attachments"] = attachments
            elif isinstance(attachments, list):
                names = []
                for att in attachments:
                    if isinstance(att, dict):
                        names.append(att.get("name", ""))
                    else:
                        names.append(str(att))
                entry["attachments"] = " ".join(names)

            items.append(entry)
        self._items = items
        return items

    def search(self, query: str, limit: int = 20) -> list[SearchResult]:
        if not query.strip():
            return []

        items = self._index_items()
        results: list[SearchResult] = []

        for item in items:
            best_score = 0.0
            best_field = ""

            for field, weight in self.FIELD_WEIGHTS.items():
                field_value = item.get(field, "")
                if not field_value:
                    continue

                score = fuzz.token_sort_ratio(query, field_value) * weight
                if score > best_score:
                    best_score = score
                    best_field = field

            if best_score > 0:
                results.append(
                    SearchResult(item=item, score=best_score, matched_field=best_field)
                )

        results.sort(key=lambda r: r.score, reverse=True)
        return results[:limit]
