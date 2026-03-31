from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROMPT_DIR = PROJECT_ROOT / "prompt"

CLEANING_PROMPT_PATH = PROMPT_DIR / "script_cleaning_prompt.md"
FEATURE_PROMPT_PATH = PROMPT_DIR / "script_feature_extraction_prompt.md"
UNIT_SPLIT_PROMPT_PATH = PROMPT_DIR / "unit_split_prompt.md"
UNIT_FRAMEWORK_PROMPT_PATH = PROMPT_DIR / "unit_framework_extraction_prompt.md"
UNIT_EPISODE_PLAN_PROMPT_PATH = PROMPT_DIR / "unit_episode_split_planning_prompt.md"
EPISODE_GENERATION_PLAN_PROMPT_PATH = PROMPT_DIR / "episode_generation_planning_prompt.md"
EPISODE_CONTENT_PROMPT_PATH = PROMPT_DIR / "episode_content_generation_prompt.md"
STORYBOARD_PROMPT_PATH = PROMPT_DIR / "storyboard_generation_prompt.md"

PROMPT_WORKFLOW_STEPS: tuple[dict[str, Any], ...] = (
    {
        "key": "script_cleaning",
        "order": 1,
        "stage": "cleaning",
        "title": "Script Cleaning",
        "description": "Clean and normalize the raw source script before extraction.",
        "prompt_path": CLEANING_PROMPT_PATH,
    },
    {
        "key": "feature_extraction",
        "order": 2,
        "stage": "feature_extraction",
        "title": "Feature Extraction",
        "description": "Extract story bible elements such as characters, props, and background.",
        "prompt_path": FEATURE_PROMPT_PATH,
    },
    {
        "key": "unit_split",
        "order": 3,
        "stage": "unit_split",
        "title": "Unit Split",
        "description": "Split the cleaned script into units using editable runtime prompt rules.",
        "prompt_path": UNIT_SPLIT_PROMPT_PATH,
    },
    {
        "key": "unit_framework",
        "order": 4,
        "stage": "unit_framework",
        "title": "Unit Framework Extraction",
        "description": "Summarize each unit into a structured framework for planning.",
        "prompt_path": UNIT_FRAMEWORK_PROMPT_PATH,
    },
    {
        "key": "episode_split_plan",
        "order": 5,
        "stage": "episode_plan",
        "title": "Episode Split Planning",
        "description": "Turn unit frameworks into a multi-episode split plan.",
        "prompt_path": UNIT_EPISODE_PLAN_PROMPT_PATH,
    },
    {
        "key": "episode_generation_plan",
        "order": 6,
        "stage": "episode_generation_plan",
        "title": "Episode Generation Planning",
        "description": "Build the full per-episode generation plan from the story bible and split plan.",
        "prompt_path": EPISODE_GENERATION_PLAN_PROMPT_PATH,
    },
    {
        "key": "episode_content_generation",
        "order": 7,
        "stage": "episode_content_generation",
        "title": "Episode Content Generation",
        "description": "Generate each episode script from its plan and source units.",
        "prompt_path": EPISODE_CONTENT_PROMPT_PATH,
    },
    {
        "key": "storyboard_generation",
        "order": 8,
        "stage": "storyboard_generation",
        "title": "Storyboard Generation",
        "description": "Generate shot-by-shot storyboard output from the episode content.",
        "prompt_path": STORYBOARD_PROMPT_PATH,
    },
)


def resolve_prompt_path(path: Path | str) -> Path:
    path_obj = Path(path)
    candidates = [path_obj]

    stem = path_obj.stem
    suffix = path_obj.suffix
    if stem.endswith("_v1"):
        candidates.append(path_obj.with_name(f"{stem[:-3]}{suffix}"))
    else:
        candidates.append(path_obj.with_name(f"{stem}_v1{suffix}"))

    seen: set[Path] = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        if candidate.exists():
            return candidate

    raise FileNotFoundError(f"Prompt file not found: {path_obj}")


def get_prompt_workflow_step(key: str) -> dict[str, Any]:
    for step in PROMPT_WORKFLOW_STEPS:
        if step["key"] == key:
            return dict(step)
    raise KeyError(key)


def get_prompt_path_by_key(key: str) -> Path:
    step = get_prompt_workflow_step(key)
    prompt_path = step.get("prompt_path")
    if prompt_path is None:
        raise ValueError(f"Workflow step '{key}' does not have a prompt file.")
    return Path(prompt_path)


def serialize_prompt_workflow() -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for step in PROMPT_WORKFLOW_STEPS:
        prompt_path = step.get("prompt_path")
        resolved_path: Path | None = None
        prompt_exists = False
        updated_at = None

        if prompt_path is not None:
            try:
                resolved_path = resolve_prompt_path(prompt_path)
                prompt_exists = True
                updated_at = datetime.fromtimestamp(
                    resolved_path.stat().st_mtime
                ).isoformat(timespec="seconds")
            except FileNotFoundError:
                resolved_path = Path(prompt_path)

        items.append(
            {
                "key": step["key"],
                "order": step["order"],
                "stage": step["stage"],
                "title": step["title"],
                "description": step["description"],
                "has_prompt": prompt_path is not None,
                "prompt_exists": prompt_exists,
                "file_name": resolved_path.name if resolved_path is not None else None,
                "file_path": str(resolved_path) if resolved_path is not None else None,
                "updated_at": updated_at,
            }
        )
    return items
