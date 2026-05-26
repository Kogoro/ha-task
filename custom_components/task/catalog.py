"""Task catalog for importing predefined tasks."""

import asyncio
import json
from pathlib import Path
from typing import Any

CATALOG_PATH = Path(__file__).parent / "task_catalog.json"


def _load_catalog_sync() -> dict[str, Any]:
    """Load the task catalog from the JSON file (blocking)."""
    with CATALOG_PATH.open(encoding="utf-8") as f:
        return json.load(f)


async def load_catalog() -> dict[str, Any]:
    """Load the task catalog from the JSON file."""
    return await asyncio.to_thread(_load_catalog_sync)


async def get_categories(lang: str = "en") -> list[dict[str, str]]:
    """Return list of categories with id, name, icon for a given language."""
    catalog = await load_catalog()
    return [
        {
            "id": cat["id"],
            "name": cat["name"].get(lang, cat["name"]["en"]),
            "icon": cat["icon"],
        }
        for cat in catalog["categories"]
    ]


async def get_tasks_for_categories(
    category_ids: list[str], lang: str = "en"
) -> list[dict[str, Any]]:
    """Return tasks from selected categories, localized."""
    catalog = await load_catalog()
    tasks = []
    for cat in catalog["categories"]:
        if cat["id"] in category_ids:
            for task in cat["tasks"]:
                tasks.append(
                    {
                        "id": task["id"],
                        "name": task["name"].get(lang, task["name"]["en"]),
                        "description": task["description"].get(
                            lang, task["description"]["en"]
                        ),
                        "icon": task["icon"],
                        "default_interval_days": task["default_interval_days"],
                        "type": task["type"],
                        "category_id": cat["id"],
                        "category_name": cat["name"].get(lang, cat["name"]["en"]),
                    }
                )
    return tasks


async def get_task_by_id(task_id: str, lang: str = "en") -> dict[str, Any] | None:
    """Look up a single task by its unique ID."""
    catalog = await load_catalog()
    for cat in catalog["categories"]:
        for task in cat["tasks"]:
            if task["id"] == task_id:
                return {
                    "id": task["id"],
                    "name": task["name"].get(lang, task["name"]["en"]),
                    "description": task["description"].get(
                        lang, task["description"]["en"]
                    ),
                    "icon": task["icon"],
                    "default_interval_days": task["default_interval_days"],
                    "type": task["type"],
                    "category_id": cat["id"],
                    "category_name": cat["name"].get(lang, cat["name"]["en"]),
                }
    return None
