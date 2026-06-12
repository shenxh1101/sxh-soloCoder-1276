from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from rapidfuzz import fuzz

from taskflow.db import Database

if TYPE_CHECKING:
    pass


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
            task_id = getattr(task, "id", None)
            entry: dict = {
                "task_id": task_id,
                "title": getattr(task, "title", "") or "",
                "notes": "",
                "tags": "",
                "project": "",
                "attachments": "",
            }

            if task_id is not None:
                details = self.db.get_task_with_details(task_id)
                if details:
                    entry["title"] = details.get("title") or entry["title"]
                    entry["project"] = details.get("project_name") or ""

                    tags = details.get("tags") or []
                    if isinstance(tags, list):
                        tag_names = []
                        for t in tags:
                            if isinstance(t, dict):
                                tag_names.append(t.get("name", "") or "")
                            else:
                                tag_names.append(str(t) or "")
                        entry["tags"] = " ".join(tag_names)

                    notes = details.get("notes") or []
                    if isinstance(notes, list):
                        note_contents = []
                        for n in notes:
                            if isinstance(n, dict):
                                note_contents.append(n.get("content", "") or "")
                            else:
                                note_contents.append(str(n) or "")
                        entry["notes"] = " ".join(note_contents)

                    attachments = details.get("attachments") or []
                    if isinstance(attachments, list):
                        att_names = []
                        for a in attachments:
                            if isinstance(a, dict):
                                att_names.append(a.get("name", "") or "")
                            else:
                                att_names.append(str(a) or "")
                        entry["attachments"] = " ".join(att_names)

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
