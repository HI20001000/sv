from __future__ import annotations

import threading
import json
import os
import re
import shutil
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from code_components.document_browser import load_document_content
from code_components.langChain import (
    clean_script_with_prompt,
    extract_script_features_with_prompt,
    extract_unit_framework_with_prompt,
    generate_episode_content_with_prompt,
    generate_storyboard_with_prompt,
    make_llm,
    plan_episode_generation_with_prompt,
    plan_unit_episode_split_with_prompt,
)


OUTPUT_ROOT = Path("output")
CLEANING_PROMPT_PATH = Path("prompt/script_cleaning_prompt_v1.md")
FEATURE_PROMPT_PATH = Path("prompt/script_feature_extraction_prompt_v1.md")
UNIT_FRAMEWORK_PROMPT_PATH = Path("prompt/unit_framework_extraction_prompt_v1.md")
UNIT_EPISODE_PLAN_PROMPT_PATH = Path("prompt/unit_episode_split_planning_prompt_v1.md")
EPISODE_GENERATION_PLAN_PROMPT_PATH = Path("prompt/episode_generation_planning_prompt_v1.md")
EPISODE_CONTENT_PROMPT_PATH = Path("prompt/episode_content_generation_prompt_v1.md")
STORYBOARD_PROMPT_PATH = Path("prompt/storyboard_generation_prompt_v1.md")
CLEANING_CHUNK_SIZE = 4000
DEFAULT_FEATURE_CHUNK_SIZE = 4000
DEFAULT_UNIT_WINDOW_MIN = 1500
DEFAULT_UNIT_WINDOW_MAX = 2200
DEFAULT_EPISODE_COUNT = 60
DEFAULT_EPISODE_SPLIT_REPAIR_ROUNDS = 2
DEFAULT_EPISODE_CONTENT_MAX_WORKERS = 4
DEFAULT_STORYBOARD_MAX_WORKERS = 4
EPISODE_PLAN_ROOT_PATH = Path("episode_split_plan.json")
EPISODE_GENERATION_PLAN_ROOT_PATH = Path("episode_generation_plan.json")
ProgressCallback = Callable[[str, dict[str, Any]], None]


@dataclass
class ScriptOutputResult:
    project_dir: Path
    cleaned_script_path: Path
    story_bible_path: Path
    story_units_path: Path
    unit_frameworks_path: Path
    project_episode_plan_path: Path
    root_episode_plan_path: Path
    project_episode_generation_plan_path: Path
    root_episode_generation_plan_path: Path
    episodes_dir: Path
    storyboards_dir: Path
    unit_count: int
    target_episode_count: int
    planned_episode_count: int
    planned_episode_outline_count: int
    generated_episode_count: int
    generated_storyboard_count: int
    source_snapshot_path: Path
    source_chars: int
    cleaned_chars: int
    total_elapsed_seconds: float


def process_script_to_output(
    llm,
    source_path: Path,
    progress_callback: ProgressCallback | None = None,
) -> ScriptOutputResult:
    run_started_at = time.perf_counter()
    step_elapsed_seconds: dict[str, float] = {}

    _emit_progress(
        progress_callback,
        stage="init",
        message=f"开始处理文件：{source_path.name}",
        source_file=source_path.name,
    )
    raw_script = load_document_content(source_path)
    source_chars = len(raw_script)
    cleaning_chunk_size = _read_cleaning_chunk_size_config()
    is_cleaning_overlong = source_chars > cleaning_chunk_size
    _emit_progress(
        progress_callback,
        stage="cleaning",
        message=(
            f"1/8 剧本清洗中（字数: {source_chars}，阈值: {cleaning_chunk_size}，"
            f"是否过长: {'是' if is_cleaning_overlong else '否'}）"
        ),
        source_chars=source_chars,
        cleaning_chunk_size=cleaning_chunk_size,
        cleaning_overlong=is_cleaning_overlong,
    )
    cleaning_started_at = time.perf_counter()
    cleaned_script, cleaning_strategy = _clean_script_robust(
        llm=llm,
        raw_script=raw_script,
        cleaning_chunk_size=cleaning_chunk_size,
        progress_callback=progress_callback,
    )
    cleaning_elapsed = time.perf_counter() - cleaning_started_at
    step_elapsed_seconds["cleaning"] = cleaning_elapsed
    cleaned_chars = len(cleaned_script)
    _emit_progress(
        progress_callback,
        stage="cleaning_done",
        message=(
            "1/8 剧本清洗完成（"
            f"策略: {cleaning_strategy}，清洗后字数: {cleaned_chars}，"
            f"耗时: {cleaning_elapsed:.2f}s）"
        ),
        cleaning_strategy=cleaning_strategy,
        cleaned_chars=cleaned_chars,
        elapsed_seconds=cleaning_elapsed,
    )

    project_dir = _create_project_dir(source_path)
    source_dir = project_dir / "source"
    source_dir.mkdir(parents=True, exist_ok=True)

    source_snapshot_path = source_dir / source_path.name
    shutil.copy2(source_path, source_snapshot_path)

    cleaned_script_path = project_dir / "script_cleaned.txt"
    text_to_write = cleaned_script if cleaned_script else "[EMPTY_SCRIPT]"
    cleaned_script_path.write_text(text_to_write, encoding="utf-8")

    _emit_progress(
        progress_callback,
        stage="feature_extraction",
        message="2/8 特征提取中",
    )
    feature_started_at = time.perf_counter()
    story_bible = _extract_story_bible(
        llm=llm,
        cleaned_script=cleaned_script,
        progress_callback=progress_callback,
    )
    feature_elapsed = time.perf_counter() - feature_started_at
    step_elapsed_seconds["feature_extraction"] = feature_elapsed
    feature_characters = story_bible.get("characters", [])
    feature_props = story_bible.get("props", [])
    _emit_progress(
        progress_callback,
        stage="feature_extraction_done",
        message=(
            "2/8 特征提取完成（"
            f"角色: {len(feature_characters) if isinstance(feature_characters, list) else 0}，"
            f"道具: {len(feature_props) if isinstance(feature_props, list) else 0}，"
            f"耗时: {feature_elapsed:.2f}s）"
        ),
        elapsed_seconds=feature_elapsed,
    )
    story_bible_path = project_dir / "story_bible.json"
    story_bible_path.write_text(
        json.dumps(story_bible, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    unit_window_min, unit_window_max = _read_unit_window_config()
    _emit_progress(
        progress_callback,
        stage="unit_split",
        message=f"3/8 拆分 Unit 中（窗口: {unit_window_min}-{unit_window_max} 字）",
        unit_window_min=unit_window_min,
        unit_window_max=unit_window_max,
    )
    unit_split_started_at = time.perf_counter()
    story_units = _split_into_units(
        text=cleaned_script,
        window_min=unit_window_min,
        window_max=unit_window_max,
    )
    unit_split_elapsed = time.perf_counter() - unit_split_started_at
    step_elapsed_seconds["unit_split"] = unit_split_elapsed
    story_units_path = project_dir / "story_units.json"
    story_units_path.write_text(
        json.dumps(story_units, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    _emit_progress(
        progress_callback,
        stage="unit_split_done",
        message=f"3/8 拆分 Unit 完成（Unit 数量: {len(story_units)}，耗时: {unit_split_elapsed:.2f}s）",
        unit_count=len(story_units),
        elapsed_seconds=unit_split_elapsed,
    )

    _emit_progress(
        progress_callback,
        stage="unit_framework",
        message="4/8 提炼 Unit 框架中",
    )
    unit_framework_started_at = time.perf_counter()
    unit_frameworks = _extract_unit_frameworks(
        llm=llm,
        story_units=story_units,
        progress_callback=progress_callback,
    )
    unit_framework_elapsed = time.perf_counter() - unit_framework_started_at
    step_elapsed_seconds["unit_framework"] = unit_framework_elapsed
    unit_frameworks_path = project_dir / "unit_frameworks.json"
    unit_frameworks_path.write_text(
        json.dumps(unit_frameworks, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    _emit_progress(
        progress_callback,
        stage="unit_framework_done",
        message=f"4/8 提炼 Unit 框架完成（框架数量: {len(unit_frameworks)}，耗时: {unit_framework_elapsed:.2f}s）",
        unit_framework_count=len(unit_frameworks),
        elapsed_seconds=unit_framework_elapsed,
    )

    target_episode_count = _read_episode_count_config()
    _emit_progress(
        progress_callback,
        stage="episode_plan",
        message=f"5/8 生成拆集计划中（目标集数: {target_episode_count}）",
        target_episode_count=target_episode_count,
    )
    episode_plan_started_at = time.perf_counter()
    episode_plan = _generate_episode_split_plan(
        llm=llm,
        unit_frameworks=unit_frameworks,
        story_units=story_units,
        target_episode_count=target_episode_count,
    )
    episode_plan_elapsed = time.perf_counter() - episode_plan_started_at
    step_elapsed_seconds["episode_split_plan"] = episode_plan_elapsed
    project_episode_plan_path = project_dir / "episode_split_plan.json"
    project_episode_plan_path.write_text(
        json.dumps(episode_plan, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    EPISODE_PLAN_ROOT_PATH.write_text(
        json.dumps(episode_plan, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    planned_episode_count = int(episode_plan.get("planned_episode_count", 0))
    _emit_progress(
        progress_callback,
        stage="episode_plan_done",
        message=(
            "5/8 生成拆集计划完成（"
            f"计划集数: {planned_episode_count}，目标集数: {target_episode_count}，"
            f"耗时: {episode_plan_elapsed:.2f}s）"
        ),
        planned_episode_count=planned_episode_count,
        target_episode_count=target_episode_count,
        elapsed_seconds=episode_plan_elapsed,
    )

    _emit_progress(
        progress_callback,
        stage="episode_generation_plan",
        message="6/8 生成逐集内容规划中",
    )
    episode_generation_plan_started_at = time.perf_counter()
    episode_generation_plan = _generate_episode_generation_plan(
        llm=llm,
        story_bible=story_bible,
        story_units=story_units,
        unit_frameworks=unit_frameworks,
        episode_split_plan=episode_plan,
        target_episode_count=target_episode_count,
    )
    episode_generation_plan_elapsed = time.perf_counter() - episode_generation_plan_started_at
    step_elapsed_seconds["episode_generation_plan"] = episode_generation_plan_elapsed
    project_episode_generation_plan_path = project_dir / "episode_generation_plan.json"
    project_episode_generation_plan_path.write_text(
        json.dumps(episode_generation_plan, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    EPISODE_GENERATION_PLAN_ROOT_PATH.write_text(
        json.dumps(episode_generation_plan, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    planned_episode_outline_count = int(episode_generation_plan.get("planned_episode_count", 0))
    _emit_progress(
        progress_callback,
        stage="episode_generation_plan_done",
        message=(
            "6/8 生成逐集内容规划完成（"
            f"规划集数: {planned_episode_outline_count}，目标集数: {target_episode_count}，"
            f"耗时: {episode_generation_plan_elapsed:.2f}s）"
        ),
        planned_episode_outline_count=planned_episode_outline_count,
        target_episode_count=target_episode_count,
        elapsed_seconds=episode_generation_plan_elapsed,
    )

    _emit_progress(
        progress_callback,
        stage="episode_content_generation",
        message=f"7/8 逐集生成内容中（目标: {target_episode_count} 集）",
    )
    episodes_dir = project_dir / "episodes"
    episode_content_started_at = time.perf_counter()
    generated_episode_count = _generate_episode_contents(
        llm=llm,
        project_dir=project_dir,
        episodes_dir=episodes_dir,
        story_bible=story_bible,
        story_units=story_units,
        episode_generation_plan=episode_generation_plan,
        target_episode_count=target_episode_count,
        progress_callback=progress_callback,
    )
    episode_content_elapsed = time.perf_counter() - episode_content_started_at
    step_elapsed_seconds["episode_content_generation"] = episode_content_elapsed
    _emit_progress(
        progress_callback,
        stage="episode_content_generation_done",
        message=f"7/8 逐集生成内容完成（已生成: {generated_episode_count} 集，耗时: {episode_content_elapsed:.2f}s）",
        generated_episode_count=generated_episode_count,
        elapsed_seconds=episode_content_elapsed,
    )

    _emit_progress(
        progress_callback,
        stage="storyboard_generation",
        message=f"8/8 逐集生成分镜中（目标: {target_episode_count} 集）",
    )
    storyboards_dir = project_dir / "storyboards"
    storyboard_started_at = time.perf_counter()
    generated_storyboard_count = _generate_episode_storyboards(
        llm=llm,
        episodes_dir=episodes_dir,
        storyboards_dir=storyboards_dir,
        story_bible=story_bible,
        target_episode_count=target_episode_count,
        progress_callback=progress_callback,
    )
    storyboard_elapsed = time.perf_counter() - storyboard_started_at
    step_elapsed_seconds["storyboard_generation"] = storyboard_elapsed
    _emit_progress(
        progress_callback,
        stage="storyboard_generation_done",
        message=f"8/8 逐集生成分镜完成（已生成: {generated_storyboard_count} 集，耗时: {storyboard_elapsed:.2f}s）",
        generated_storyboard_count=generated_storyboard_count,
        elapsed_seconds=storyboard_elapsed,
    )

    total_elapsed_seconds = time.perf_counter() - run_started_at

    meta_path = project_dir / "project_meta.json"
    meta = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "source_file": source_path.name,
        "source_chars": source_chars,
        "cleaned_chars": cleaned_chars,
        "cleaning_overlong": is_cleaning_overlong,
        "cleaning_chunk_size": cleaning_chunk_size,
        "cleaning_strategy": cleaning_strategy,
        "cleaning_prompt_file": str(CLEANING_PROMPT_PATH),
        "feature_prompt_file": str(FEATURE_PROMPT_PATH),
        "feature_chunk_size": _read_feature_chunk_size_config(),
        "unit_framework_prompt_file": str(UNIT_FRAMEWORK_PROMPT_PATH),
        "unit_episode_plan_prompt_file": str(UNIT_EPISODE_PLAN_PROMPT_PATH),
        "episode_split_repair_rounds": _read_episode_split_repair_rounds_config(),
        "episode_generation_plan_prompt_file": str(EPISODE_GENERATION_PLAN_PROMPT_PATH),
        "episode_content_prompt_file": str(EPISODE_CONTENT_PROMPT_PATH),
        "storyboard_prompt_file": str(STORYBOARD_PROMPT_PATH),
        "cleaned_script_file": cleaned_script_path.name,
        "story_bible_file": story_bible_path.name,
        "story_units_file": story_units_path.name,
        "unit_frameworks_file": unit_frameworks_path.name,
        "episode_split_plan_file": project_episode_plan_path.name,
        "episode_split_plan_root_file": str(EPISODE_PLAN_ROOT_PATH),
        "episode_generation_plan_file": project_episode_generation_plan_path.name,
        "episode_generation_plan_root_file": str(EPISODE_GENERATION_PLAN_ROOT_PATH),
        "episodes_dir": episodes_dir.name,
        "episodes_overview_file": "episodes_overview.json",
        "storyboards_dir": storyboards_dir.name,
        "storyboards_index_file": "index.json",
        "episode_content_max_workers": _read_episode_content_max_workers_config(),
        "storyboard_max_workers": _read_storyboard_max_workers_config(),
        "unit_window_min": unit_window_min,
        "unit_window_max": unit_window_max,
        "unit_count": len(story_units),
        "target_episode_count": target_episode_count,
        "planned_episode_count": planned_episode_count,
        "planned_episode_outline_count": planned_episode_outline_count,
        "generated_episode_count": generated_episode_count,
        "generated_storyboard_count": generated_storyboard_count,
        "step_elapsed_seconds": {
            key: round(value, 4) for key, value in step_elapsed_seconds.items()
        },
        "total_elapsed_seconds": round(total_elapsed_seconds, 4),
    }
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    _emit_progress(
        progress_callback,
        stage="done",
        message=f"处理流程完成（总耗时: {total_elapsed_seconds:.2f}s）",
        total_elapsed_seconds=total_elapsed_seconds,
    )

    return ScriptOutputResult(
        project_dir=project_dir,
        cleaned_script_path=cleaned_script_path,
        story_bible_path=story_bible_path,
        story_units_path=story_units_path,
        unit_frameworks_path=unit_frameworks_path,
        project_episode_plan_path=project_episode_plan_path,
        root_episode_plan_path=EPISODE_PLAN_ROOT_PATH,
        project_episode_generation_plan_path=project_episode_generation_plan_path,
        root_episode_generation_plan_path=EPISODE_GENERATION_PLAN_ROOT_PATH,
        episodes_dir=episodes_dir,
        storyboards_dir=storyboards_dir,
        unit_count=len(story_units),
        target_episode_count=target_episode_count,
        planned_episode_count=planned_episode_count,
        planned_episode_outline_count=planned_episode_outline_count,
        generated_episode_count=generated_episode_count,
        generated_storyboard_count=generated_storyboard_count,
        source_snapshot_path=source_snapshot_path,
        source_chars=source_chars,
        cleaned_chars=cleaned_chars,
        total_elapsed_seconds=total_elapsed_seconds,
    )


def _create_project_dir(source_path: Path) -> Path:
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)

    base_name = _slugify(source_path.stem)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    project_dir = OUTPUT_ROOT / f"{base_name}_{timestamp}"
    project_dir.mkdir(parents=True, exist_ok=True)
    return project_dir


def _slugify(text: str) -> str:
    slug = re.sub(r"[^\w\-]+", "_", text, flags=re.UNICODE).strip("_")
    return slug or "script"


def _emit_progress(
    progress_callback: ProgressCallback | None,
    stage: str,
    message: str,
    **extra: Any,
) -> None:
    if progress_callback is None:
        return

    payload = {"stage": stage, "message": message, **extra}
    try:
        progress_callback(stage, payload)
    except Exception:
        # Progress rendering should not interrupt the main processing pipeline.
        return


def _extract_story_bible(
    llm,
    cleaned_script: str,
    progress_callback: ProgressCallback | None = None,
) -> dict[str, Any]:
    if not cleaned_script.strip():
        return _empty_story_bible()

    feature_chunk_size = _read_feature_chunk_size_config()
    chunks = _split_text(cleaned_script, feature_chunk_size)
    if not chunks:
        return _empty_story_bible()

    _emit_progress(
        progress_callback,
        stage="feature_extraction_internal",
        message=f"特征分段提取中（共 {len(chunks)} 段，分段阈值: {feature_chunk_size}）",
        feature_chunk_size=feature_chunk_size,
        chunk_count=len(chunks),
    )

    extracted_chunks: list[dict[str, Any]] = []
    for chunk_index, chunk in enumerate(chunks, start=1):
        _emit_progress(
            progress_callback,
            stage="feature_extraction_internal",
            message=f"特征提取进度：第 {chunk_index}/{len(chunks)} 段",
            chunk_index=chunk_index,
            chunk_count=len(chunks),
        )
        try:
            raw_response = extract_script_features_with_prompt(
                llm=llm,
                script_text=chunk,
                prompt_path=FEATURE_PROMPT_PATH,
            )
            parsed = _parse_json_response(raw_response, source_name="Feature extraction")
            extracted_chunks.append(_normalize_story_bible(parsed))
        except Exception:
            _emit_progress(
                progress_callback,
                stage="feature_extraction_internal",
                message=f"特征提取第 {chunk_index}/{len(chunks)} 段解析失败，已跳过该段",
                chunk_index=chunk_index,
                chunk_count=len(chunks),
            )

    if not extracted_chunks:
        raise ValueError("Feature extraction failed for all chunks")

    merged = _merge_story_bibles(extracted_chunks)
    _emit_progress(
        progress_callback,
        stage="feature_extraction_internal",
        message=(
            "特征分段合并完成（"
            f"有效分段: {len(extracted_chunks)}/{len(chunks)}，"
            f"角色: {len(merged.get('characters', []))}，"
            f"道具: {len(merged.get('props', []))}）"
        ),
        chunk_success_count=len(extracted_chunks),
        chunk_count=len(chunks),
    )
    return merged


def _merge_story_bibles(items: list[dict[str, Any]]) -> dict[str, Any]:
    if not items:
        return _empty_story_bible()

    character_map: dict[str, dict[str, Any]] = {}
    prop_map: dict[str, dict[str, Any]] = {}

    era = ""
    locations: list[str] = []
    social_context: list[str] = []
    world_rules: list[str] = []
    background_evidence: list[str] = []

    for item in items:
        normalized_item = _normalize_story_bible(item)
        for character in normalized_item.get("characters", []):
            key = _build_entity_key(character.get("name"), character.get("aliases"))
            if not key:
                continue
            if key not in character_map:
                character_map[key] = character
            else:
                character_map[key] = _merge_character_record(character_map[key], character)

        for prop in normalized_item.get("props", []):
            key = _build_entity_key(prop.get("name"), [])
            if not key:
                continue
            if key not in prop_map:
                prop_map[key] = prop
            else:
                prop_map[key] = _merge_prop_record(prop_map[key], prop)

        background = normalized_item.get("background", {})
        if isinstance(background, dict):
            current_era = _coerce_text(background.get("era"))
            if not era and current_era:
                era = current_era
            locations = _unique_texts(locations + _coerce_text_sequence(background.get("locations")))
            social_context = _unique_texts(social_context + _coerce_text_sequence(background.get("social_context")))
            world_rules = _unique_texts(world_rules + _coerce_text_sequence(background.get("world_rules")))
            background_evidence = _unique_texts(
                background_evidence + _coerce_text_sequence(background.get("evidence"))
            )

    merged = {
        "characters": list(character_map.values()),
        "props": list(prop_map.values()),
        "background": {
            "era": era,
            "locations": locations,
            "social_context": social_context,
            "world_rules": world_rules,
            "evidence": background_evidence,
        },
    }
    return _normalize_story_bible(merged)


def _merge_character_record(base: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    base_name = _coerce_text(base.get("name"))
    incoming_name = _coerce_text(incoming.get("name"))

    merged_name = base_name or incoming_name
    if len(incoming_name) > len(merged_name):
        merged_name = incoming_name

    base_role = _coerce_text(base.get("role_type")) or "未知"
    incoming_role = _coerce_text(incoming.get("role_type")) or "未知"
    if base_role == "未知" and incoming_role != "未知":
        merged_role = incoming_role
    else:
        merged_role = base_role

    base_summary = _coerce_text(base.get("summary"))
    incoming_summary = _coerce_text(incoming.get("summary"))
    merged_summary = incoming_summary if len(incoming_summary) > len(base_summary) else base_summary

    merged_aliases = _unique_texts(
        _coerce_text_sequence(base.get("aliases")) + _coerce_text_sequence(incoming.get("aliases"))
    )
    merged_aliases = [alias for alias in merged_aliases if alias != merged_name]

    merged_evidence = _unique_texts(
        _coerce_text_sequence(base.get("evidence")) + _coerce_text_sequence(incoming.get("evidence"))
    )

    return {
        "name": merged_name,
        "aliases": merged_aliases,
        "role_type": merged_role if merged_role else "未知",
        "summary": merged_summary,
        "evidence": merged_evidence,
    }


def _merge_prop_record(base: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    base_name = _coerce_text(base.get("name"))
    incoming_name = _coerce_text(incoming.get("name"))
    merged_name = base_name or incoming_name
    if len(incoming_name) > len(merged_name):
        merged_name = incoming_name

    base_purpose = _coerce_text(base.get("purpose"))
    incoming_purpose = _coerce_text(incoming.get("purpose"))
    merged_purpose = incoming_purpose if len(incoming_purpose) > len(base_purpose) else base_purpose

    merged_owner = _coerce_text(base.get("owner_or_user")) or _coerce_text(incoming.get("owner_or_user"))
    merged_evidence = _unique_texts(
        _coerce_text_sequence(base.get("evidence")) + _coerce_text_sequence(incoming.get("evidence"))
    )

    return {
        "name": merged_name,
        "purpose": merged_purpose,
        "owner_or_user": merged_owner,
        "evidence": merged_evidence,
    }


def _build_entity_key(primary_name: Any, aliases: Any) -> str:
    name = _coerce_text(primary_name)
    if name:
        return _normalize_key(name)

    alias_list = _coerce_text_sequence(aliases)
    if alias_list:
        return _normalize_key(alias_list[0])
    return ""


def _normalize_key(value: str) -> str:
    return re.sub(r"\s+", "", value).lower()


def _extract_unit_frameworks(
    llm,
    story_units: list[dict[str, Any]],
    progress_callback: ProgressCallback | None = None,
) -> list[dict[str, Any]]:
    if not story_units:
        return []

    frameworks: list[dict[str, Any]] = []
    total = len(story_units)
    for index, unit in enumerate(story_units, start=1):
        unit_id = str(unit.get("unit_id", f"u_{index:04d}"))
        _emit_progress(
            progress_callback,
            stage="unit_framework_internal",
            message=f"Unit 框架提炼进度：{index}/{total}（{unit_id}）",
            unit_index=index,
            unit_total=total,
            unit_id=unit_id,
        )
        frameworks.append(_extract_single_unit_framework(llm=llm, unit=unit))

    return frameworks


def _extract_single_unit_framework(llm, unit: dict[str, Any]) -> dict[str, Any]:
    unit_id = str(unit.get("unit_id", ""))
    unit_text = str(unit.get("text", ""))
    if not unit_text.strip():
        return _fallback_unit_framework(unit)

    try:
        raw_response = extract_unit_framework_with_prompt(
            llm=llm,
            unit_id=unit_id,
            unit_text=unit_text,
            prompt_path=UNIT_FRAMEWORK_PROMPT_PATH,
        )
        parsed = _parse_json_response(raw_response)
        if not isinstance(parsed, dict):
            return _fallback_unit_framework(unit)
        return _normalize_unit_framework(unit, parsed)
    except Exception:
        return _fallback_unit_framework(unit)


def _normalize_unit_framework(unit: dict[str, Any], parsed: dict[str, Any]) -> dict[str, Any]:
    unit_id = str(unit.get("unit_id", parsed.get("unit_id", "")))
    char_count = int(unit.get("char_count", 0)) if isinstance(unit.get("char_count", 0), int) else 0
    source_span = unit.get("source_span", {})
    if not isinstance(source_span, dict):
        source_span = {}

    summary = _coerce_text(parsed.get("summary"))
    if not summary:
        summary = _coerce_text(unit.get("text", ""))[:120]

    return {
        "unit_id": unit_id,
        "char_count": char_count,
        "source_span": {
            "start_para": int(source_span.get("start_para", 0)) if isinstance(source_span.get("start_para", 0), int) else 0,
            "end_para": int(source_span.get("end_para", 0)) if isinstance(source_span.get("end_para", 0), int) else 0,
        },
        "summary": summary,
        "key_events": _coerce_text_list(parsed.get("key_events")),
        "core_conflict": _coerce_text(parsed.get("core_conflict")),
        "hook": _coerce_text(parsed.get("hook")),
        "ending_state": _coerce_text(parsed.get("ending_state")),
    }


def _fallback_unit_framework(unit: dict[str, Any]) -> dict[str, Any]:
    unit_text = _coerce_text(unit.get("text"))
    sentences = _sentence_split(unit_text)
    key_events = [s.strip() for s in sentences[:3] if s.strip()]
    summary = unit_text[:120]
    source_span = unit.get("source_span", {})
    if not isinstance(source_span, dict):
        source_span = {}
    return {
        "unit_id": _coerce_text(unit.get("unit_id")),
        "char_count": int(unit.get("char_count", 0)) if isinstance(unit.get("char_count", 0), int) else 0,
        "source_span": {
            "start_para": int(source_span.get("start_para", 0)) if isinstance(source_span.get("start_para", 0), int) else 0,
            "end_para": int(source_span.get("end_para", 0)) if isinstance(source_span.get("end_para", 0), int) else 0,
        },
        "summary": summary,
        "key_events": key_events,
        "core_conflict": "",
        "hook": "",
        "ending_state": "",
    }


def _generate_episode_split_plan(
    llm,
    unit_frameworks: list[dict[str, Any]],
    story_units: list[dict[str, Any]],
    target_episode_count: int,
) -> dict[str, Any]:
    unit_ids = [str(item.get("unit_id", "")) for item in story_units]
    char_count_map = {
        str(item.get("unit_id", "")): int(item.get("char_count", 0))
        for item in story_units
        if isinstance(item.get("char_count", 0), int)
    }

    if target_episode_count <= 0:
        raise ValueError("DEFAULT_EPISODE_COUNT must be a positive integer")

    if not unit_ids:
        return {
            "target_episode_count": target_episode_count,
            "planned_episode_count": 0,
            "allocation_strategy": "empty_units",
            "unit_allocations": [],
            "notes": "No units generated from cleaned script.",
            "validation": {
                "sum_matches_target": target_episode_count == 0,
            },
        }

    framework_json = json.dumps(unit_frameworks, ensure_ascii=False, indent=2)
    max_repair_rounds = _read_episode_split_repair_rounds_config()

    parsed_plan: Any = {}
    plan_error_messages: list[str] = []
    try:
        raw_response = plan_unit_episode_split_with_prompt(
            llm=llm,
            unit_framework_json=framework_json,
            target_episode_count=target_episode_count,
            prompt_path=UNIT_EPISODE_PLAN_PROMPT_PATH,
        )
        parsed_plan = _parse_json_response(raw_response, source_name="Unit episode split planning")
    except Exception as exc:
        parsed_plan = {}
        plan_error_messages.append(f"initial_plan_error: {exc}")

    normalized_plan = _normalize_episode_split_plan(
        plan_data=parsed_plan,
        unit_ids=unit_ids,
        char_count_map=char_count_map,
        target_episode_count=target_episode_count,
    )
    if plan_error_messages:
        validation = normalized_plan.get("validation")
        if isinstance(validation, dict):
            errors = validation.get("errors")
            if not isinstance(errors, list):
                errors = []
            validation["errors"] = [*errors, *plan_error_messages]
            validation["is_valid"] = False

    validation = normalized_plan.get("validation", {})
    if isinstance(validation, dict) and validation.get("is_valid"):
        return normalized_plan

    current_plan_json = json.dumps(parsed_plan, ensure_ascii=False, indent=2) if isinstance(parsed_plan, dict) else "{}"
    for repair_round in range(1, max_repair_rounds + 1):
        current_errors = []
        if isinstance(validation, dict):
            raw_errors = validation.get("errors")
            if isinstance(raw_errors, list):
                current_errors = [str(item) for item in raw_errors if str(item).strip()]

        repaired_plan: Any = {}
        repair_error = ""
        try:
            repaired_raw_response = _repair_episode_split_plan_with_llm(
                llm=llm,
                unit_framework_json=framework_json,
                target_episode_count=target_episode_count,
                previous_plan_json=current_plan_json,
                validation_errors=current_errors,
            )
            repaired_plan = _parse_json_response(
                repaired_raw_response,
                source_name=f"Unit episode split repair round {repair_round}",
            )
        except Exception as exc:
            repaired_plan = {}
            repair_error = f"repair_round_{repair_round}_error: {exc}"

        normalized_plan = _normalize_episode_split_plan(
            plan_data=repaired_plan,
            unit_ids=unit_ids,
            char_count_map=char_count_map,
            target_episode_count=target_episode_count,
        )
        validation = normalized_plan.get("validation")
        if isinstance(validation, dict) and repair_error:
            errors = validation.get("errors")
            if not isinstance(errors, list):
                errors = []
            validation["errors"] = [*errors, repair_error]
            validation["is_valid"] = False

        validation = normalized_plan.get("validation", {})
        if isinstance(validation, dict) and validation.get("is_valid"):
            normalized_plan["repair_rounds"] = repair_round
            return normalized_plan

        current_plan_json = (
            json.dumps(repaired_plan, ensure_ascii=False, indent=2)
            if isinstance(repaired_plan, dict)
            else "{}"
        )

    final_errors: list[str] = []
    if isinstance(validation, dict):
        raw_errors = validation.get("errors")
        if isinstance(raw_errors, list):
            final_errors = [str(item) for item in raw_errors if str(item).strip()]
    joined_errors = " | ".join(final_errors[:6]) if final_errors else "unknown validation failure"
    raise ValueError(
        "Episode split planning failed after LLM planning and repair rounds. "
        f"Reason: {joined_errors}"
    )


def _repair_episode_split_plan_with_llm(
    llm,
    unit_framework_json: str,
    target_episode_count: int,
    previous_plan_json: str,
    validation_errors: list[str],
) -> str:
    error_lines = "\n".join(f"- {item}" for item in validation_errors[:20]) or "- no explicit validation error"
    prompt = (
        "You are a short-drama unit-to-episode allocation repair assistant.\n"
        "Fix the invalid JSON plan and output only valid JSON.\n"
        "Hard constraints:\n"
        "1) unit_allocations must include every existing unit_id exactly once.\n"
        "2) episode_count must be a non-negative integer for every unit.\n"
        "3) sum(unit_allocations[*].episode_count) must equal target_episode_count exactly.\n"
        "4) You may set any unit to 0, 1, or more episodes based on story continuity and dramatic value.\n"
        "5) Do not invent unit_id values.\n"
        "6) Output JSON only. No markdown.\n\n"
        "Return schema:\n"
        "{\n"
        '  "target_episode_count": 0,\n'
        '  "allocation_strategy": "",\n'
        '  "unit_allocations": [{"unit_id": "", "episode_count": 0, "reason": ""}],\n'
        '  "notes": ""\n'
        "}\n\n"
        f"target_episode_count:\n{target_episode_count}\n\n"
        f"unit_framework_json:\n{unit_framework_json}\n\n"
        f"invalid_plan_json:\n{previous_plan_json}\n\n"
        f"validation_errors:\n{error_lines}\n"
    )
    response = llm.invoke(prompt)
    return str(response.content).strip()


def _generate_episode_generation_plan(
    llm,
    story_bible: dict[str, Any],
    story_units: list[dict[str, Any]],
    unit_frameworks: list[dict[str, Any]],
    episode_split_plan: dict[str, Any],
    target_episode_count: int,
) -> dict[str, Any]:
    plan_data: Any = {}
    try:
        raw_response = plan_episode_generation_with_prompt(
            llm=llm,
            story_bible_json=json.dumps(story_bible, ensure_ascii=False, indent=2),
            unit_framework_json=json.dumps(unit_frameworks, ensure_ascii=False, indent=2),
            episode_split_plan_json=json.dumps(episode_split_plan, ensure_ascii=False, indent=2),
            target_episode_count=target_episode_count,
            prompt_path=EPISODE_GENERATION_PLAN_PROMPT_PATH,
        )
        plan_data = _parse_json_response(raw_response, source_name="Episode generation planning")
    except Exception:
        plan_data = {}

    return _normalize_episode_generation_plan(
        plan_data=plan_data,
        story_bible=story_bible,
        story_units=story_units,
        unit_frameworks=unit_frameworks,
        episode_split_plan=episode_split_plan,
        target_episode_count=target_episode_count,
    )


def _normalize_episode_generation_plan(
    plan_data: Any,
    story_bible: dict[str, Any],
    story_units: list[dict[str, Any]],
    unit_frameworks: list[dict[str, Any]],
    episode_split_plan: dict[str, Any],
    target_episode_count: int,
) -> dict[str, Any]:
    if not isinstance(plan_data, dict):
        plan_data = {}

    unit_ids = [
        _coerce_text(item.get("unit_id"))
        for item in unit_frameworks
        if isinstance(item, dict) and _coerce_text(item.get("unit_id"))
    ]
    story_unit_catalog, story_unit_map = _build_story_unit_catalog(story_units=story_units)
    if story_unit_catalog:
        unit_ids = [item["unit_id"] for item in story_unit_catalog]
    unit_summary_by_id: dict[str, str] = {}
    for item in unit_frameworks:
        if not isinstance(item, dict):
            continue
        unit_id = _coerce_text(item.get("unit_id"))
        if not unit_id:
            continue
        unit_summary_by_id[unit_id] = _coerce_text(item.get("summary"))

    raw_episodes = plan_data.get("episodes")
    if not isinstance(raw_episodes, list):
        raw_episodes = []

    unit_allocations = episode_split_plan.get("unit_allocations", [])
    if not isinstance(unit_allocations, list):
        unit_allocations = []
    episode_unit_sequence = _build_episode_unit_sequence(
        unit_allocations=unit_allocations,
        unit_ids=unit_ids,
        target_episode_count=target_episode_count,
    )

    default_character_focus = _build_default_character_focus(story_bible)
    episodes: list[dict[str, Any]] = []
    for index in range(target_episode_count):
        raw_episode = raw_episodes[index] if index < len(raw_episodes) and isinstance(raw_episodes[index], dict) else {}
        fallback_unit = episode_unit_sequence[index] if index < len(episode_unit_sequence) else ""

        source_units = _coerce_source_units(raw_episode.get("source_units"), unit_ids)
        if not source_units and fallback_unit:
            source_units = [fallback_unit]
        if not source_units and unit_ids:
            source_units = [unit_ids[min(index, len(unit_ids) - 1)]]

        source_unit_details = [
            story_unit_map[unit_id]
            for unit_id in source_units
            if unit_id in story_unit_map
        ]
        unit_context = _build_unit_context_text(source_units, unit_summary_by_id)
        title = _coerce_text(raw_episode.get("title")) or f"第{index + 1}集"
        arc_goal = _coerce_text(raw_episode.get("arc_goal")) or unit_context
        opening_hook = _coerce_text(raw_episode.get("opening_hook"))
        core_beats = _coerce_text_sequence(raw_episode.get("core_beats"))
        if not core_beats:
            core_beats = _build_default_core_beats(unit_context)
        character_focus = _coerce_text_sequence(raw_episode.get("character_focus"))
        if not character_focus:
            character_focus = default_character_focus
        props_used = _coerce_text_sequence(raw_episode.get("props_used"))
        ending_hook = _coerce_text(raw_episode.get("ending_hook"))
        continuity_requirements = _coerce_text_sequence(raw_episode.get("continuity_requirements"))
        generation_brief = _coerce_text(raw_episode.get("generation_brief"))
        if not generation_brief:
            generation_brief = _build_generation_brief(
                arc_goal=arc_goal,
                opening_hook=opening_hook,
                core_beats=core_beats,
                ending_hook=ending_hook,
            )

        episodes.append(
            {
                "episode_no": index + 1,
                "title": title,
                "source_units": source_units,
                "source_unit_details": source_unit_details,
                "arc_goal": arc_goal,
                "opening_hook": opening_hook,
                "core_beats": core_beats,
                "character_focus": character_focus,
                "props_used": props_used,
                "ending_hook": ending_hook,
                "continuity_requirements": continuity_requirements,
                "generation_brief": generation_brief,
            }
        )

    planned_episode_count = len(episodes)
    return {
        "target_episode_count": target_episode_count,
        "planned_episode_count": planned_episode_count,
        "allocation_strategy": (
            _coerce_text(plan_data.get("allocation_strategy"))
            or _coerce_text(episode_split_plan.get("allocation_strategy"))
            or "unit_allocation_guided"
        ),
        "episode_source": "llm_then_normalized" if raw_episodes else "programmatic_fallback",
        "unit_allocations": unit_allocations,
        "story_unit_catalog": story_unit_catalog,
        "generation_input_contract": {
            "required_files": [
                "story_bible.json",
                "episode_generation_plan.json",
                "story_units.json",
            ],
            "binding_key": "unit_id",
            "per_episode_input": {
                "episode_plan_object": "episodes[n]",
                "source_units_lookup": "story_units by unit_id in episodes[n].source_units",
            },
        },
        "episodes": episodes,
        "notes": _coerce_text(plan_data.get("notes")),
        "validation": {
            "sum_matches_target": planned_episode_count == target_episode_count,
            "all_episodes_have_source_units": all(bool(item.get("source_units")) for item in episodes),
            "all_source_units_resolvable": all(
                all(unit_id in story_unit_map for unit_id in item.get("source_units", []))
                for item in episodes
            ),
            "target_episode_count": target_episode_count,
            "planned_episode_count": planned_episode_count,
        },
    }


def _build_episode_unit_sequence(
    unit_allocations: list[dict[str, Any]],
    unit_ids: list[str],
    target_episode_count: int,
) -> list[str]:
    sequence: list[str] = []
    for item in unit_allocations:
        if not isinstance(item, dict):
            continue
        unit_id = _coerce_text(item.get("unit_id"))
        count = _coerce_int(item.get("episode_count"), default=0, minimum=0)
        if not unit_id or unit_id not in unit_ids or count <= 0:
            continue
        sequence.extend([unit_id] * count)

    if len(sequence) < target_episode_count and unit_ids:
        cursor = 0
        while len(sequence) < target_episode_count:
            sequence.append(unit_ids[cursor % len(unit_ids)])
            cursor += 1

    return sequence[:target_episode_count]


def _build_story_unit_catalog(
    story_units: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    catalog: list[dict[str, Any]] = []
    unit_map: dict[str, dict[str, Any]] = {}

    for index, item in enumerate(story_units, start=1):
        if not isinstance(item, dict):
            continue
        unit_id = _coerce_text(item.get("unit_id"))
        if not unit_id:
            continue

        source_span = item.get("source_span", {})
        if not isinstance(source_span, dict):
            source_span = {}

        detail = {
            "unit_id": unit_id,
            "unit_order": index,
            "char_count": _coerce_int(item.get("char_count"), default=0, minimum=0),
            "source_span": {
                "start_para": _coerce_int(source_span.get("start_para"), default=0, minimum=0),
                "end_para": _coerce_int(source_span.get("end_para"), default=0, minimum=0),
            },
        }
        catalog.append(detail)
        unit_map[unit_id] = detail

    return catalog, unit_map


def _coerce_source_units(value: Any, valid_unit_ids: list[str]) -> list[str]:
    candidate_units = _coerce_text_sequence(value)
    output: list[str] = []
    for unit_id in candidate_units:
        if unit_id in valid_unit_ids and unit_id not in output:
            output.append(unit_id)
    return output


def _build_unit_context_text(source_units: list[str], unit_summary_by_id: dict[str, str]) -> str:
    parts: list[str] = []
    for unit_id in source_units:
        summary = _coerce_text(unit_summary_by_id.get(unit_id))
        if summary:
            parts.append(f"{unit_id}: {summary[:80]}")
    return "；".join(parts)


def _build_default_character_focus(story_bible: dict[str, Any]) -> list[str]:
    characters = story_bible.get("characters", [])
    if not isinstance(characters, list):
        return []
    output: list[str] = []
    for item in characters:
        if not isinstance(item, dict):
            continue
        name = _coerce_text(item.get("name"))
        if not name:
            continue
        output.append(name)
        if len(output) >= 3:
            break
    return output


def _build_default_core_beats(unit_context: str) -> list[str]:
    if unit_context:
        return [
            f"承接上集并进入主冲突：{unit_context[:80]}",
            "围绕关键矛盾推进并制造对抗升级",
            "在结尾抛出新问题或新压力",
        ]
    return [
        "承接上集并快速进入本集冲突",
        "围绕主冲突推进并升级对抗",
        "结尾抛出下一集钩子",
    ]


def _build_generation_brief(
    arc_goal: str,
    opening_hook: str,
    core_beats: list[str],
    ending_hook: str,
) -> str:
    parts: list[str] = []
    if arc_goal:
        parts.append(f"目标: {arc_goal}")
    if opening_hook:
        parts.append(f"开场钩子: {opening_hook}")
    if core_beats:
        parts.append("推进: " + " | ".join(core_beats[:3]))
    if ending_hook:
        parts.append(f"结尾钩子: {ending_hook}")
    return "；".join(parts)


def _generate_episode_contents(
    llm,
    project_dir: Path,
    episodes_dir: Path,
    story_bible: dict[str, Any],
    story_units: list[dict[str, Any]],
    episode_generation_plan: dict[str, Any],
    target_episode_count: int,
    progress_callback: ProgressCallback | None = None,
) -> int:
    episodes_dir.mkdir(parents=True, exist_ok=True)

    planned_episodes = episode_generation_plan.get("episodes", [])
    if not isinstance(planned_episodes, list):
        planned_episodes = []

    story_unit_map = _build_story_unit_map_with_text(story_units)
    generated_index: list[dict[str, Any]] = []
    story_bible_json = json.dumps(story_bible, ensure_ascii=False, indent=2)

    max_workers = min(_read_episode_content_max_workers_config(), max(target_episode_count, 1))
    llm_thread_local = threading.local() if max_workers > 1 else None

    _emit_progress(
        progress_callback,
        stage="episode_content_generation_internal",
        message=f"逐集生成任务已提交（共 {target_episode_count} 集，并发: {max_workers}）",
        target_episode_count=target_episode_count,
        max_workers=max_workers,
        completed_episode_count=0,
    )

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = []
        for episode_no in range(1, target_episode_count + 1):
            plan_item = (
                planned_episodes[episode_no - 1]
                if episode_no - 1 < len(planned_episodes) and isinstance(planned_episodes[episode_no - 1], dict)
                else {}
            )
            source_unit_ids = _coerce_source_units(plan_item.get("source_units"), list(story_unit_map.keys()))
            if not source_unit_ids and story_unit_map:
                source_unit_ids = [list(story_unit_map.keys())[min(episode_no - 1, len(story_unit_map) - 1)]]

            source_units_payload = [
                story_unit_map[unit_id]
                for unit_id in source_unit_ids
                if unit_id in story_unit_map
            ]
            futures.append(
                executor.submit(
                    _generate_single_episode_content,
                    llm=llm,
                    llm_thread_local=llm_thread_local,
                    episode_no=episode_no,
                    plan_item=plan_item,
                    source_unit_ids=source_unit_ids,
                    source_units_payload=source_units_payload,
                    story_bible_json=story_bible_json,
                )
            )

        completed_count = 0
        for future in as_completed(futures):
            result = future.result()
            episode_no = int(result["episode_no"])
            episode_file_name = f"episode_{episode_no:04d}.json"
            episode_path = episodes_dir / episode_file_name
            episode_path.write_text(
                json.dumps(result["output_payload"], ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            generated_index.append(
                {
                    "episode_no": episode_no,
                    "file": episode_file_name,
                    "generation_status": str(result["generation_status"]),
                    "source_units": result["source_unit_ids"],
                }
            )
            completed_count += 1
            _emit_progress(
                progress_callback,
                stage="episode_content_generation_internal",
                message=(
                    f"逐集生成已完成 {completed_count}/{target_episode_count} 集"
                    f"（刚完成第 {episode_no} 集，状态: {result['generation_status']}）"
                ),
                episode_no=episode_no,
                target_episode_count=target_episode_count,
                completed_episode_count=completed_count,
                max_workers=max_workers,
                generation_status=result["generation_status"],
            )

    generated_index.sort(key=lambda item: _coerce_int(item.get("episode_no"), default=0, minimum=0))

    index_payload = {
        "target_episode_count": target_episode_count,
        "generated_episode_count": len(generated_index),
        "episodes": generated_index,
    }
    (episodes_dir / "index.json").write_text(
        json.dumps(index_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (project_dir / "episodes_overview.json").write_text(
        json.dumps(index_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return len(generated_index)


def _generate_episode_storyboards(
    llm,
    episodes_dir: Path,
    storyboards_dir: Path,
    story_bible: dict[str, Any],
    target_episode_count: int,
    progress_callback: ProgressCallback | None = None,
) -> int:
    storyboards_dir.mkdir(parents=True, exist_ok=True)

    story_bible_json = json.dumps(story_bible, ensure_ascii=False, indent=2)
    generated_index: list[dict[str, Any]] = []

    max_workers = min(_read_storyboard_max_workers_config(), max(target_episode_count, 1))
    llm_thread_local = threading.local() if max_workers > 1 else None

    _emit_progress(
        progress_callback,
        stage="storyboard_generation_internal",
        message=f"分镜生成任务已提交（共 {target_episode_count} 集，并发: {max_workers}）",
        target_episode_count=target_episode_count,
        max_workers=max_workers,
        completed_storyboard_count=0,
    )

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [
            executor.submit(
                _generate_single_storyboard,
                llm=llm,
                llm_thread_local=llm_thread_local,
                episode_no=episode_no,
                episode_file_name=f"episode_{episode_no:04d}.json",
                episode_path=episodes_dir / f"episode_{episode_no:04d}.json",
                story_bible=story_bible,
                story_bible_json=story_bible_json,
            )
            for episode_no in range(1, target_episode_count + 1)
        ]

        completed_count = 0
        for future in as_completed(futures):
            result = future.result()
            episode_no = int(result["episode_no"])
            storyboard_file_name = f"episode_{episode_no:04d}_storyboard.json"
            (storyboards_dir / storyboard_file_name).write_text(
                json.dumps(result["output_payload"], ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            validation = result["validation"]
            generated_index.append(
                {
                    "episode_no": episode_no,
                    "file": storyboard_file_name,
                    "source_episode_file": str(result["source_episode_file"]),
                    "generation_status": str(result["generation_status"]),
                    "dialogue_coverage_rate": validation.get("dialogue_coverage_rate", 0.0),
                    "unknown_character_count": len(validation.get("unknown_characters", [])),
                    "unknown_prop_count": len(validation.get("unknown_props", [])),
                }
            )
            completed_count += 1
            _emit_progress(
                progress_callback,
                stage="storyboard_generation_internal",
                message=(
                    f"分镜生成已完成 {completed_count}/{target_episode_count} 集"
                    f"（刚完成第 {episode_no} 集，状态: {result['generation_status']}）"
                ),
                episode_no=episode_no,
                target_episode_count=target_episode_count,
                completed_storyboard_count=completed_count,
                max_workers=max_workers,
                generation_status=result["generation_status"],
            )

    generated_index.sort(key=lambda item: _coerce_int(item.get("episode_no"), default=0, minimum=0))

    index_payload = {
        "target_episode_count": target_episode_count,
        "generated_storyboard_count": len(generated_index),
        "episodes": generated_index,
    }
    (storyboards_dir / "index.json").write_text(
        json.dumps(index_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    return len(generated_index)


def _generate_single_episode_content(
    llm,
    llm_thread_local: threading.local | None,
    episode_no: int,
    plan_item: dict[str, Any],
    source_unit_ids: list[str],
    source_units_payload: list[dict[str, Any]],
    story_bible_json: str,
) -> dict[str, Any]:
    episode_plan_json = json.dumps(plan_item, ensure_ascii=False, indent=2)
    source_units_json = json.dumps(source_units_payload, ensure_ascii=False, indent=2)
    worker_llm = _get_parallel_worker_llm(llm=llm, llm_thread_local=llm_thread_local)

    try:
        raw_response = generate_episode_content_with_prompt(
            llm=worker_llm,
            story_bible_json=story_bible_json,
            episode_plan_json=episode_plan_json,
            source_units_json=source_units_json,
            prompt_path=EPISODE_CONTENT_PROMPT_PATH,
        )
        episode_content = _normalize_generated_episode_content(
            raw_response=raw_response,
            episode_no=episode_no,
            plan_item=plan_item,
            source_unit_ids=source_unit_ids,
        )
        generation_status = "llm"
    except Exception:
        episode_content = _fallback_episode_content(
            episode_no=episode_no,
            plan_item=plan_item,
            source_units_payload=source_units_payload,
        )
        generation_status = "fallback"

    return {
        "episode_no": episode_no,
        "generation_status": generation_status,
        "source_unit_ids": source_unit_ids,
        "output_payload": {
            "episode_no": episode_no,
            "generation_status": generation_status,
            "source_units": source_unit_ids,
            "source_units_payload": source_units_payload,
            "episode_plan": plan_item,
            "generated_content": episode_content,
        },
    }


def _generate_single_storyboard(
    llm,
    llm_thread_local: threading.local | None,
    episode_no: int,
    episode_file_name: str,
    episode_path: Path,
    story_bible: dict[str, Any],
    story_bible_json: str,
) -> dict[str, Any]:
    if episode_path.exists():
        episode_payload = _safe_load_json_file(episode_path, default={})
        if not isinstance(episode_payload, dict):
            episode_payload = {}
    else:
        episode_payload = {}

    episode_json = json.dumps(episode_payload, ensure_ascii=False, indent=2)
    worker_llm = _get_parallel_worker_llm(llm=llm, llm_thread_local=llm_thread_local)

    try:
        raw_response = generate_storyboard_with_prompt(
            llm=worker_llm,
            story_bible_json=story_bible_json,
            episode_json=episode_json,
            prompt_path=STORYBOARD_PROMPT_PATH,
        )
        storyboard = _normalize_generated_storyboard(
            raw_response=raw_response,
            episode_payload=episode_payload,
        )
        generation_status = "llm"
    except Exception:
        storyboard = _fallback_storyboard_from_episode(episode_payload=episode_payload)
        generation_status = "fallback"

    validation = _validate_storyboard(
        storyboard=storyboard,
        episode_payload=episode_payload,
        story_bible=story_bible,
    )

    return {
        "episode_no": episode_no,
        "source_episode_file": episode_file_name,
        "generation_status": generation_status,
        "validation": validation,
        "output_payload": {
            "episode_no": episode_no,
            "generation_status": generation_status,
            "source_episode_file": episode_file_name,
            "storyboard": storyboard,
            "validation": validation,
        },
    }


def _get_parallel_worker_llm(llm, llm_thread_local: threading.local | None):
    if llm_thread_local is None:
        return llm

    worker_llm = getattr(llm_thread_local, "llm", None)
    if worker_llm is None:
        worker_llm = make_llm()
        llm_thread_local.llm = worker_llm
    return worker_llm


def _normalize_generated_storyboard(
    raw_response: str,
    episode_payload: dict[str, Any],
) -> dict[str, Any]:
    parsed = _parse_json_response(raw_response, source_name="Storyboard generation")
    if not isinstance(parsed, dict):
        return _fallback_storyboard_from_episode(episode_payload=episode_payload)

    episode_no = _coerce_int(
        parsed.get("episode_no"),
        default=_coerce_int(episode_payload.get("episode_no"), default=0, minimum=0),
        minimum=0,
    )
    title = (
        _coerce_text(parsed.get("title"))
        or _coerce_text((episode_payload.get("generated_content") or {}).get("title"))
        or _coerce_text((episode_payload.get("episode_plan") or {}).get("title"))
        or f"第{episode_no}集"
    )

    raw_scenes = parsed.get("scenes")
    scenes: list[dict[str, Any]] = []
    if isinstance(raw_scenes, list):
        for scene_index, scene in enumerate(raw_scenes, start=1):
            if not isinstance(scene, dict):
                continue
            scene_no = _coerce_int(scene.get("scene_no"), default=scene_index, minimum=1)
            raw_shots = scene.get("shots")
            if not isinstance(raw_shots, list):
                raw_shots = []
            shots = _normalize_storyboard_shots(raw_shots=raw_shots, scene_no=scene_no)
            scenes.append(
                {
                    "scene_no": scene_no,
                    "shots": shots,
                }
            )

    if not scenes and isinstance(parsed.get("shots"), list):
        shots = _normalize_storyboard_shots(raw_shots=parsed.get("shots"), scene_no=1)
        scenes = [{"scene_no": 1, "shots": shots}]

    if not scenes:
        fallback = _fallback_storyboard_from_episode(episode_payload=episode_payload)
        scenes = fallback.get("scenes", [])

    return {
        "episode_no": episode_no,
        "title": title,
        "scenes": scenes,
    }


def _normalize_storyboard_shots(raw_shots: list[Any], scene_no: int) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for shot_index, item in enumerate(raw_shots, start=1):
        if not isinstance(item, dict):
            continue
        shot_no = _coerce_int(item.get("shot_no"), default=shot_index, minimum=1)
        shot_scene_no = _coerce_int(item.get("scene_no"), default=scene_no, minimum=1)
        purpose = _coerce_text(item.get("purpose"))
        visual = _coerce_text(item.get("visual"))
        characters = _coerce_name_list(item.get("characters"))
        dialogue = _coerce_text(item.get("dialogue"))
        duration = _coerce_duration_seconds(item.get("duration"), default=3.0)
        output.append(
            {
                "shot_no": shot_no,
                "scene_no": shot_scene_no,
                "purpose": purpose,
                "visual": visual,
                "characters": characters,
                "dialogue": dialogue,
                "duration": duration,
            }
        )
    return output


def _fallback_storyboard_from_episode(episode_payload: dict[str, Any]) -> dict[str, Any]:
    episode_no = _coerce_int(episode_payload.get("episode_no"), default=0, minimum=0)
    generated_content = episode_payload.get("generated_content", {})
    episode_plan = episode_payload.get("episode_plan", {})
    if not isinstance(generated_content, dict):
        generated_content = {}
    if not isinstance(episode_plan, dict):
        episode_plan = {}

    title = (
        _coerce_text(generated_content.get("title"))
        or _coerce_text(episode_plan.get("title"))
        or f"第{episode_no}集"
    )
    script = _coerce_text(generated_content.get("script"))
    parsed_scenes = _parse_script_scenes(script)

    scenes: list[dict[str, Any]] = []
    for scene_index, scene in enumerate(parsed_scenes, start=1):
        scene_no = _coerce_int(scene.get("scene_no"), default=scene_index, minimum=1)
        heading = _coerce_text(scene.get("heading"))
        plot = _coerce_text(scene.get("plot"))
        cast = _coerce_name_list(scene.get("cast"))
        dialogues = scene.get("dialogues", [])
        if not isinstance(dialogues, list):
            dialogues = []

        shots: list[dict[str, Any]] = []
        shot_no = 1
        for dialogue_item in dialogues:
            if not isinstance(dialogue_item, dict):
                continue
            speaker = _coerce_text(dialogue_item.get("speaker"))
            line = _coerce_text(dialogue_item.get("line"))
            if not speaker and not line:
                continue
            dialogue_text = f"{speaker}：{line}" if speaker and line else line
            characters = [speaker] if speaker else cast[:1]
            visual_parts = [heading, plot]
            visual = "；".join(part for part in visual_parts if part)
            shots.append(
                {
                    "shot_no": shot_no,
                    "scene_no": scene_no,
                    "purpose": "推进对白与冲突",
                    "visual": visual,
                    "characters": _coerce_name_list(characters),
                    "dialogue": dialogue_text,
                    "duration": _estimate_dialogue_duration_seconds(line),
                }
            )
            shot_no += 1

        if not shots:
            visual_parts = [heading, plot]
            visual = "；".join(part for part in visual_parts if part)
            shots.append(
                {
                    "shot_no": 1,
                    "scene_no": scene_no,
                    "purpose": "建立场景并推进剧情",
                    "visual": visual,
                    "characters": cast,
                    "dialogue": "",
                    "duration": 3.0,
                }
            )

        scenes.append(
            {
                "scene_no": scene_no,
                "shots": shots,
            }
        )

    if not scenes:
        scenes = [
            {
                "scene_no": 1,
                "shots": [
                    {
                        "shot_no": 1,
                        "scene_no": 1,
                        "purpose": "建立场景并推进剧情",
                        "visual": "未解析到有效场景，保底镜头。",
                        "characters": [],
                        "dialogue": "",
                        "duration": 3.0,
                    }
                ],
            }
        ]

    return {
        "episode_no": episode_no,
        "title": title,
        "scenes": scenes,
    }


def _validate_storyboard(
    storyboard: dict[str, Any],
    episode_payload: dict[str, Any],
    story_bible: dict[str, Any],
) -> dict[str, Any]:
    script = _coerce_text((episode_payload.get("generated_content") or {}).get("script"))
    episode_dialogues = _extract_dialogue_pairs_from_script(script)
    storyboard_dialogues = _extract_dialogue_pairs_from_storyboard(storyboard)

    storyboard_dialogue_set = {_build_dialogue_key(item.get("speaker", ""), item.get("line", "")) for item in storyboard_dialogues}
    storyboard_dialogue_set = {key for key in storyboard_dialogue_set if key}

    missing_dialogues: list[str] = []
    for item in episode_dialogues:
        key = _build_dialogue_key(item.get("speaker", ""), item.get("line", ""))
        if key and key not in storyboard_dialogue_set:
            speaker = _coerce_text(item.get("speaker"))
            line = _coerce_text(item.get("line"))
            preview = f"{speaker}：{line}" if speaker else line
            if preview:
                missing_dialogues.append(preview)

    dialogue_total = len(episode_dialogues)
    dialogue_covered = max(dialogue_total - len(missing_dialogues), 0)
    dialogue_coverage_rate = round((dialogue_covered / dialogue_total), 4) if dialogue_total > 0 else 1.0

    allowed_character_keys = _build_story_character_key_set(story_bible)
    unknown_characters = _find_unknown_characters(storyboard, allowed_character_keys)

    allowed_prop_keys = _build_story_prop_key_set(story_bible)
    used_props = _extract_storyboard_marked_props(storyboard)
    used_prop_keys = {_normalize_key(_strip_name_annotations(prop)) for prop in used_props}
    used_prop_keys = {key for key in used_prop_keys if key}
    required_props = _coerce_text_sequence((episode_payload.get("episode_plan") or {}).get("props_used"))
    required_props = _unique_texts(required_props)
    missing_required_props = [
        prop
        for prop in required_props
        if _normalize_key(_strip_name_annotations(prop)) not in used_prop_keys
    ]

    unknown_props = [
        prop
        for prop in used_props
        if _normalize_key(_strip_name_annotations(prop)) not in allowed_prop_keys
    ]
    unknown_props = _unique_texts(unknown_props)

    return {
        "dialogue_total": dialogue_total,
        "dialogue_covered": dialogue_covered,
        "dialogue_coverage_rate": dialogue_coverage_rate,
        "missing_dialogues": missing_dialogues,
        "unknown_characters": unknown_characters,
        "required_props": required_props,
        "missing_required_props": missing_required_props,
        "unknown_props": unknown_props,
        "checks": {
            "all_dialogue_covered": len(missing_dialogues) == 0,
            "characters_in_story_bible": len(unknown_characters) == 0,
            "required_props_covered": len(missing_required_props) == 0,
            "props_in_story_bible": len(unknown_props) == 0,
        },
    }


def _parse_script_scenes(script: str) -> list[dict[str, Any]]:
    if not script.strip():
        return []

    lines = script.splitlines()
    scenes: list[dict[str, Any]] = []
    current_lines: list[str] = []
    current_heading = ""

    for line in lines:
        text = line.strip()
        if re.match(r"^场景\s*\d+\s*[：:]", text):
            if current_lines:
                scenes.append(_build_scene_block(current_heading, current_lines, len(scenes) + 1))
            current_heading = text
            current_lines = [text]
            continue

        if not current_lines and text:
            current_heading = "场景 1"
        if text or current_lines:
            current_lines.append(text)

    if current_lines:
        scenes.append(_build_scene_block(current_heading, current_lines, len(scenes) + 1))

    return scenes


def _build_scene_block(heading: str, lines: list[str], scene_no: int) -> dict[str, Any]:
    cast: list[str] = []
    plot = ""
    dialogues: list[dict[str, str]] = []
    in_dialogue = False

    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("出场角色"):
            _, _, right = line.partition("：")
            cast = _coerce_name_list(right)
            continue
        if line.startswith("剧情"):
            _, _, right = line.partition("：")
            plot = _coerce_text(right)
            in_dialogue = False
            continue
        if line.startswith("对白"):
            in_dialogue = True
            continue
        if line.startswith("场景"):
            continue

        pair = _parse_dialogue_line(line)
        if in_dialogue and pair is not None:
            dialogues.append(pair)

    return {
        "scene_no": scene_no,
        "heading": heading,
        "cast": cast,
        "plot": plot,
        "dialogues": dialogues,
    }


def _extract_dialogue_pairs_from_script(script: str) -> list[dict[str, str]]:
    scenes = _parse_script_scenes(script)
    output: list[dict[str, str]] = []
    for scene in scenes:
        for item in scene.get("dialogues", []):
            if isinstance(item, dict):
                speaker = _coerce_text(item.get("speaker"))
                line = _coerce_text(item.get("line"))
                if speaker or line:
                    output.append({"speaker": speaker, "line": line})
    return output


def _extract_dialogue_pairs_from_storyboard(storyboard: dict[str, Any]) -> list[dict[str, str]]:
    scenes = storyboard.get("scenes", [])
    if not isinstance(scenes, list):
        return []

    output: list[dict[str, str]] = []
    for scene in scenes:
        if not isinstance(scene, dict):
            continue
        shots = scene.get("shots", [])
        if not isinstance(shots, list):
            continue
        for shot in shots:
            if not isinstance(shot, dict):
                continue
            dialogue = _coerce_text(shot.get("dialogue"))
            if not dialogue:
                continue
            for line in dialogue.splitlines():
                parsed = _parse_dialogue_line(line.strip())
                if parsed is not None:
                    output.append(parsed)
                else:
                    fallback_text = _coerce_text(line)
                    if fallback_text:
                        output.append({"speaker": "", "line": fallback_text})
    return output


def _parse_dialogue_line(line: str) -> dict[str, str] | None:
    if not line:
        return None
    match = re.match(r"^([^：:]{1,40})[：:]\s*(.+)$", line)
    if not match:
        return None

    speaker = _coerce_text(match.group(1))
    text = _coerce_text(match.group(2))
    if not speaker and not text:
        return None

    blocked_prefixes = ("场景", "出场角色", "剧情", "对白")
    if any(speaker.startswith(prefix) for prefix in blocked_prefixes):
        return None

    return {
        "speaker": speaker,
        "line": text,
    }


def _build_dialogue_key(speaker: str, line: str) -> str:
    speaker_key = _normalize_key(_strip_name_annotations(speaker))
    line_key = _normalize_for_dialogue_compare(line)
    if speaker_key and line_key:
        return f"{speaker_key}|{line_key}"
    return line_key


def _normalize_for_dialogue_compare(text: str) -> str:
    value = _coerce_text(text).lower()
    value = re.sub(r"\s+", "", value)
    value = re.sub(r"[，。！？、：；,.!?;\"'“”‘’（）()【】\[\]…·\-]", "", value)
    return value


def _build_story_character_key_set(story_bible: dict[str, Any]) -> set[str]:
    output: set[str] = set()
    characters = story_bible.get("characters", [])
    if not isinstance(characters, list):
        return output
    for item in characters:
        if not isinstance(item, dict):
            continue
        names = [_coerce_text(item.get("name"))] + _coerce_text_sequence(item.get("aliases"))
        for name in names:
            key = _normalize_key(_strip_name_annotations(name))
            if key:
                output.add(key)
    return output


def _build_story_prop_key_set(story_bible: dict[str, Any]) -> set[str]:
    output: set[str] = set()
    props = story_bible.get("props", [])
    if not isinstance(props, list):
        return output
    for item in props:
        if isinstance(item, dict):
            name = _coerce_text(item.get("name"))
        else:
            name = _coerce_text(item)
        key = _normalize_key(_strip_name_annotations(name))
        if key:
            output.add(key)
    return output


def _find_unknown_characters(storyboard: dict[str, Any], allowed_character_keys: set[str]) -> list[str]:
    scenes = storyboard.get("scenes", [])
    if not isinstance(scenes, list):
        return []

    unknown: list[str] = []
    for scene in scenes:
        if not isinstance(scene, dict):
            continue
        shots = scene.get("shots", [])
        if not isinstance(shots, list):
            continue
        for shot in shots:
            if not isinstance(shot, dict):
                continue
            for name in _coerce_name_list(shot.get("characters")):
                key = _normalize_key(_strip_name_annotations(name))
                if key and key not in allowed_character_keys:
                    unknown.append(name)
    return _unique_texts(unknown)


def _extract_storyboard_marked_props(storyboard: dict[str, Any]) -> list[str]:
    scenes = storyboard.get("scenes", [])
    if not isinstance(scenes, list):
        return []
    used_props: list[str] = []

    for scene in scenes:
        if not isinstance(scene, dict):
            continue
        shots = scene.get("shots", [])
        if not isinstance(shots, list):
            continue
        for shot in shots:
            if not isinstance(shot, dict):
                continue
            visual = _coerce_text(shot.get("visual"))
            dialogue = _coerce_text(shot.get("dialogue"))
            blob = f"{visual}\n{dialogue}"
            matches = re.findall(r"道具[:：]\s*([^\s，,；;。！!？?\]】]+)", blob)
            for match in matches:
                prop_name = _coerce_text(match)
                if prop_name:
                    used_props.append(prop_name)

    return _unique_texts(used_props)


def _coerce_name_list(value: Any) -> list[str]:
    if isinstance(value, list):
        raw_values = [_coerce_text(item) for item in value]
        return _unique_texts([item for item in raw_values if item])
    if isinstance(value, str):
        text = _coerce_text(value)
        if not text:
            return []
        parts = re.split(r"[、,，/|；;]", text)
        return _unique_texts([_coerce_text(part) for part in parts if _coerce_text(part)])
    return []


def _strip_name_annotations(name: str) -> str:
    text = _coerce_text(name)
    text = re.sub(r"[（(].*?[）)]", "", text)
    return _coerce_text(text)


def _coerce_duration_seconds(value: Any, default: float = 3.0) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = default
    if parsed <= 0:
        parsed = default
    return round(min(max(parsed, 0.5), 12.0), 2)


def _estimate_dialogue_duration_seconds(dialogue: str) -> float:
    text = _coerce_text(dialogue)
    if not text:
        return 2.0
    estimate = 1.5 + (len(text) / 18.0)
    return _coerce_duration_seconds(estimate, default=3.0)


def _safe_load_json_file(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _build_story_unit_map_with_text(story_units: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    output: dict[str, dict[str, Any]] = {}
    for item in story_units:
        if not isinstance(item, dict):
            continue
        unit_id = _coerce_text(item.get("unit_id"))
        if not unit_id:
            continue
        source_span = item.get("source_span", {})
        if not isinstance(source_span, dict):
            source_span = {}
        output[unit_id] = {
            "unit_id": unit_id,
            "char_count": _coerce_int(item.get("char_count"), default=0, minimum=0),
            "source_span": {
                "start_para": _coerce_int(source_span.get("start_para"), default=0, minimum=0),
                "end_para": _coerce_int(source_span.get("end_para"), default=0, minimum=0),
            },
            "text": _coerce_text(item.get("text")),
        }
    return output


def _normalize_generated_episode_content(
    raw_response: str,
    episode_no: int,
    plan_item: dict[str, Any],
    source_unit_ids: list[str],
) -> dict[str, Any]:
    parsed = _parse_json_response(raw_response, source_name="Episode content generation")
    if not isinstance(parsed, dict):
        return _fallback_episode_content(
            episode_no=episode_no,
            plan_item=plan_item,
            source_units_payload=[],
        )

    title = _coerce_text(parsed.get("title")) or _coerce_text(plan_item.get("title")) or f"第{episode_no}集"
    short_summary = _coerce_text(parsed.get("short_summary"))
    script = _coerce_text(parsed.get("script"))
    scene_outline = _coerce_text_sequence(parsed.get("scene_outline"))
    continuity_notes = _coerce_text_sequence(parsed.get("continuity_notes"))

    return {
        "episode_no": episode_no,
        "title": title,
        "short_summary": short_summary,
        "script": script,
        "scene_outline": scene_outline,
        "continuity_notes": continuity_notes,
        "source_units": source_unit_ids,
    }


def _fallback_episode_content(
    episode_no: int,
    plan_item: dict[str, Any],
    source_units_payload: list[dict[str, Any]],
) -> dict[str, Any]:
    title = _coerce_text(plan_item.get("title")) or f"第{episode_no}集"
    arc_goal = _coerce_text(plan_item.get("arc_goal"))
    core_beats = _coerce_text_sequence(plan_item.get("core_beats"))
    source_text = "\n\n".join(_coerce_text(item.get("text"))[:400] for item in source_units_payload if isinstance(item, dict))
    source_text = source_text.strip()
    if len(source_text) > 1200:
        source_text = source_text[:1200]

    script_parts = [part for part in [arc_goal, "；".join(core_beats), source_text] if part]
    fallback_script = "\n\n".join(script_parts).strip()

    return {
        "episode_no": episode_no,
        "title": title,
        "short_summary": arc_goal,
        "script": fallback_script,
        "scene_outline": core_beats,
        "continuity_notes": _coerce_text_sequence(plan_item.get("continuity_requirements")),
        "source_units": [item.get("unit_id", "") for item in source_units_payload if isinstance(item, dict)],
    }


def _normalize_episode_split_plan(
    plan_data: Any,
    unit_ids: list[str],
    char_count_map: dict[str, int],
    target_episode_count: int,
) -> dict[str, Any]:
    if not isinstance(plan_data, dict):
        plan_data = {}

    raw_allocations = plan_data.get("unit_allocations")
    if not isinstance(raw_allocations, list):
        raw_allocations = plan_data.get("allocation")
    errors: list[str] = []
    if not isinstance(raw_allocations, list):
        raw_allocations = []
        errors.append("unit_allocations_missing_or_not_list")

    proposed_count_by_unit: dict[str, int] = {}
    reason_by_unit: dict[str, str] = {}
    unknown_unit_ids: list[str] = []
    duplicate_unit_ids: list[str] = []

    for index, item in enumerate(raw_allocations, start=1):
        if not isinstance(item, dict):
            errors.append(f"unit_allocations[{index}]_not_object")
            continue

        unit_id = _coerce_text(item.get("unit_id"))
        if not unit_id:
            errors.append(f"unit_allocations[{index}]_missing_unit_id")
            continue
        if unit_id not in unit_ids:
            unknown_unit_ids.append(unit_id)
            continue
        if unit_id in proposed_count_by_unit:
            duplicate_unit_ids.append(unit_id)
            continue

        raw_count = item.get("episode_count")
        try:
            parsed_count = int(raw_count)
        except (TypeError, ValueError):
            errors.append(f"unit_allocations[{index}]_invalid_episode_count")
            continue
        if parsed_count < 0:
            errors.append(f"unit_allocations[{index}]_negative_episode_count")
            continue

        proposed_count_by_unit[unit_id] = parsed_count
        reason_by_unit[unit_id] = _coerce_text(item.get("reason"))

    if unknown_unit_ids:
        errors.append("unknown_unit_ids_present")
    if duplicate_unit_ids:
        errors.append("duplicate_unit_ids_present")

    missing_unit_ids = [unit_id for unit_id in unit_ids if unit_id not in proposed_count_by_unit]
    if missing_unit_ids:
        errors.append("missing_unit_ids_present")

    normalized_allocations: list[dict[str, Any]] = []
    for unit_id in unit_ids:
        normalized_allocations.append(
            {
                "unit_id": unit_id,
                "episode_count": proposed_count_by_unit.get(unit_id, 0),
                "char_count": int(char_count_map.get(unit_id, 0)),
                "reason": reason_by_unit.get(unit_id, ""),
            }
        )

    planned_episode_count = sum(item["episode_count"] for item in normalized_allocations)
    sum_matches_target = planned_episode_count == target_episode_count
    if not sum_matches_target:
        errors.append("episode_count_sum_not_equal_target")

    all_units_covered = not missing_unit_ids and not duplicate_unit_ids and not unknown_unit_ids
    is_valid = sum_matches_target and all_units_covered and not errors
    return {
        "target_episode_count": target_episode_count,
        "planned_episode_count": planned_episode_count,
        "allocation_strategy": _coerce_text(plan_data.get("allocation_strategy")) or "llm_unit_allocation",
        "unit_allocations": normalized_allocations,
        "notes": _coerce_text(plan_data.get("notes")),
        "validation": {
            "sum_matches_target": sum_matches_target,
            "unit_count": len(unit_ids),
            "target_episode_count": target_episode_count,
            "planned_episode_count": planned_episode_count,
            "all_units_covered": all_units_covered,
            "no_unknown_unit_ids": not unknown_unit_ids,
            "no_duplicate_unit_ids": not duplicate_unit_ids,
            "missing_unit_ids": missing_unit_ids,
            "unknown_unit_ids": _unique_texts(unknown_unit_ids),
            "duplicate_unit_ids": _unique_texts(duplicate_unit_ids),
            "errors": _unique_texts(errors),
            "is_valid": is_valid,
        },
    }


def _coerce_text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    return ""


def _coerce_text_sequence(value: Any) -> list[str]:
    if isinstance(value, str):
        text = _coerce_text(value)
        return [text] if text else []

    if not isinstance(value, list):
        return []

    output: list[str] = []
    for item in value:
        text = _coerce_text(item)
        if text:
            output.append(text)
    return _unique_texts(output)


def _coerce_text_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return _coerce_text_sequence(value)


def _unique_texts(values: list[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for item in values:
        text = _coerce_text(item)
        if not text:
            continue
        key = _normalize_key(text)
        if key in seen:
            continue
        seen.add(key)
        output.append(text)
    return output


def _coerce_int(value: Any, default: int = 0, minimum: int | None = None) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default

    if minimum is not None:
        return max(parsed, minimum)
    return parsed


def _parse_json_response(raw_response: str, source_name: str = "LLM") -> Any:
    text = raw_response.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
        text = text.strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            return json.loads(text[start : end + 1])
        raise ValueError(f"{source_name} returned non-JSON content")


def _normalize_story_bible(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        return _empty_story_bible()

    raw_characters = data.get("characters")
    raw_props = data.get("props")
    raw_background = data.get("background")

    if not isinstance(raw_characters, list):
        raw_characters = []
    if not isinstance(raw_props, list):
        raw_props = []
    if not isinstance(raw_background, dict):
        raw_background = {}

    characters: list[dict[str, Any]] = []
    for item in raw_characters:
        normalized = _normalize_character_item(item)
        if normalized is not None:
            characters.append(normalized)

    props: list[dict[str, Any]] = []
    for item in raw_props:
        normalized = _normalize_prop_item(item)
        if normalized is not None:
            props.append(normalized)

    background = {
        "era": _coerce_text(raw_background.get("era")),
        "locations": _coerce_text_sequence(raw_background.get("locations")),
        "social_context": _coerce_text_sequence(raw_background.get("social_context")),
        "world_rules": _coerce_text_sequence(raw_background.get("world_rules")),
        "evidence": _coerce_text_sequence(raw_background.get("evidence")),
    }

    normalized = {
        "characters": characters,
        "props": props,
        "background": background,
    }
    return _dedupe_story_bible(normalized)


def _normalize_character_item(item: Any) -> dict[str, Any] | None:
    if isinstance(item, str):
        name = _coerce_text(item)
        if not name:
            return None
        return {
            "name": name,
            "aliases": [],
            "role_type": "未知",
            "summary": "",
            "evidence": [],
        }

    if not isinstance(item, dict):
        return None

    name = _coerce_text(item.get("name"))
    aliases = _coerce_text_sequence(item.get("aliases"))
    if not name and aliases:
        name = aliases[0]
    if not name:
        return None

    role_type = _coerce_text(item.get("role_type")) or "未知"
    summary = _coerce_text(item.get("summary"))
    evidence = _coerce_text_sequence(item.get("evidence"))

    aliases = [alias for alias in aliases if alias != name]
    return {
        "name": name,
        "aliases": aliases,
        "role_type": role_type,
        "summary": summary,
        "evidence": evidence,
    }


def _normalize_prop_item(item: Any) -> dict[str, Any] | None:
    if isinstance(item, str):
        name = _coerce_text(item)
        if not name:
            return None
        return {
            "name": name,
            "purpose": "",
            "owner_or_user": "",
            "evidence": [],
        }

    if not isinstance(item, dict):
        return None

    name = _coerce_text(item.get("name"))
    if not name:
        return None

    return {
        "name": name,
        "purpose": _coerce_text(item.get("purpose")),
        "owner_or_user": _coerce_text(item.get("owner_or_user")),
        "evidence": _coerce_text_sequence(item.get("evidence")),
    }


def _dedupe_story_bible(story_bible: dict[str, Any]) -> dict[str, Any]:
    characters = story_bible.get("characters", [])
    props = story_bible.get("props", [])
    background = story_bible.get("background", {})

    if not isinstance(characters, list):
        characters = []
    if not isinstance(props, list):
        props = []
    if not isinstance(background, dict):
        background = {}

    character_map: dict[str, dict[str, Any]] = {}
    for item in characters:
        if not isinstance(item, dict):
            continue
        key = _build_entity_key(item.get("name"), item.get("aliases"))
        if not key:
            continue
        if key not in character_map:
            character_map[key] = item
        else:
            character_map[key] = _merge_character_record(character_map[key], item)

    prop_map: dict[str, dict[str, Any]] = {}
    for item in props:
        if not isinstance(item, dict):
            continue
        key = _build_entity_key(item.get("name"), [])
        if not key:
            continue
        if key not in prop_map:
            prop_map[key] = item
        else:
            prop_map[key] = _merge_prop_record(prop_map[key], item)

    deduped = {
        "characters": sorted(
            list(character_map.values()),
            key=lambda item: _normalize_key(_coerce_text(item.get("name"))),
        ),
        "props": sorted(
            list(prop_map.values()),
            key=lambda item: _normalize_key(_coerce_text(item.get("name"))),
        ),
        "background": {
            "era": _coerce_text(background.get("era")),
            "locations": _coerce_text_sequence(background.get("locations")),
            "social_context": _coerce_text_sequence(background.get("social_context")),
            "world_rules": _coerce_text_sequence(background.get("world_rules")),
            "evidence": _coerce_text_sequence(background.get("evidence")),
        },
    }
    return deduped


def _empty_story_bible() -> dict[str, Any]:
    return {
        "characters": [],
        "props": [],
        "background": {
            "era": "",
            "locations": [],
            "social_context": [],
            "world_rules": [],
            "evidence": [],
        },
    }


def _clean_script_robust(
    llm,
    raw_script: str,
    cleaning_chunk_size: int,
    progress_callback: ProgressCallback | None = None,
) -> tuple[str, str]:
    cleaned = clean_script_with_prompt(
        llm=llm,
        raw_script=raw_script,
        prompt_path=CLEANING_PROMPT_PATH,
    )
    if cleaned.strip():
        _emit_progress(
            progress_callback,
            stage="cleaning_internal",
            message="剧本清洗主流程返回有效结果",
            cleaning_strategy="llm",
        )
        return cleaned, "llm"

    _emit_progress(
        progress_callback,
        stage="cleaning_internal",
        message="剧本清洗主流程返回空结果，进入兜底策略",
    )
    if len(raw_script) <= cleaning_chunk_size * 2:
        chunked_cleaned = _clean_script_in_chunks(
            llm=llm,
            raw_script=raw_script,
            cleaning_chunk_size=cleaning_chunk_size,
            progress_callback=progress_callback,
        )
        if chunked_cleaned.strip():
            _emit_progress(
                progress_callback,
                stage="cleaning_internal",
                message="分块清洗成功",
                cleaning_strategy="chunked",
            )
            return chunked_cleaned, "chunked"

    _emit_progress(
        progress_callback,
        stage="cleaning_internal",
        message="分块清洗不可用或失败，使用本地清洗兜底",
        cleaning_strategy="local_fallback",
    )
    return _local_cleanup_fallback(raw_script), "local_fallback"


def _clean_script_in_chunks(
    llm,
    raw_script: str,
    cleaning_chunk_size: int,
    progress_callback: ProgressCallback | None = None,
) -> str:
    chunks = _split_text(raw_script, cleaning_chunk_size)
    if not chunks:
        return ""

    _emit_progress(
        progress_callback,
        stage="cleaning_internal",
        message=f"分块清洗中（共 {len(chunks)} 块）",
        chunk_count=len(chunks),
    )
    cleaned_chunks: list[str] = []
    for chunk_index, chunk in enumerate(chunks, start=1):
        _emit_progress(
            progress_callback,
            stage="cleaning_internal",
            message=f"分块清洗进度：第 {chunk_index}/{len(chunks)} 块",
            chunk_index=chunk_index,
            chunk_count=len(chunks),
        )
        cleaned_chunk = clean_script_with_prompt(
            llm=llm,
            raw_script=chunk,
            prompt_path=CLEANING_PROMPT_PATH,
        ).strip()
        cleaned_chunks.append(cleaned_chunk if cleaned_chunk else chunk.strip())

    return "\n\n".join(part for part in cleaned_chunks if part)


def _split_text(text: str, chunk_size: int) -> list[str]:
    normalized = text.replace("\r\n", "\n").strip()
    if not normalized:
        return []

    paragraphs = [p.strip() for p in re.split(r"\n{2,}", normalized) if p.strip()]
    chunks: list[str] = []
    current = ""

    for paragraph in paragraphs:
        if len(paragraph) > chunk_size:
            if current:
                chunks.append(current.strip())
                current = ""
            chunks.extend(_split_long_block(paragraph, chunk_size))
            continue

        candidate = paragraph if not current else f"{current}\n\n{paragraph}"
        if len(candidate) <= chunk_size:
            current = candidate
        else:
            chunks.append(current.strip())
            current = paragraph

    if current.strip():
        chunks.append(current.strip())

    return chunks


def _split_long_block(block: str, chunk_size: int) -> list[str]:
    return [block[i : i + chunk_size].strip() for i in range(0, len(block), chunk_size) if block[i : i + chunk_size].strip()]


def _local_cleanup_fallback(raw_script: str) -> str:
    text = raw_script.replace("\r\n", "\n")
    text = re.sub(r"[\u200b-\u200f\ufeff]", "", text)
    lines = [line.strip() for line in text.split("\n")]
    text = "\n".join(lines)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _read_unit_window_config() -> tuple[int, int]:
    raw_min = os.getenv("UNIT_WINDOW_MIN", str(DEFAULT_UNIT_WINDOW_MIN))
    raw_max = os.getenv("UNIT_WINDOW_MAX", str(DEFAULT_UNIT_WINDOW_MAX))
    try:
        window_min = int(raw_min)
        window_max = int(raw_max)
    except ValueError as exc:
        raise ValueError("UNIT_WINDOW_MIN and UNIT_WINDOW_MAX must be integers") from exc

    if window_min <= 0 or window_max <= 0:
        raise ValueError("UNIT_WINDOW_MIN and UNIT_WINDOW_MAX must be positive")
    if window_min >= window_max:
        raise ValueError("UNIT_WINDOW_MIN must be smaller than UNIT_WINDOW_MAX")
    return window_min, window_max


def _read_feature_chunk_size_config() -> int:
    raw_size = os.getenv("FEATURE_CHUNK_SIZE", str(DEFAULT_FEATURE_CHUNK_SIZE))
    try:
        chunk_size = int(raw_size)
    except ValueError as exc:
        raise ValueError("FEATURE_CHUNK_SIZE must be an integer") from exc

    if chunk_size <= 0:
        raise ValueError("FEATURE_CHUNK_SIZE must be positive")
    return chunk_size


def _read_cleaning_chunk_size_config() -> int:
    raw_size = os.getenv("CLEANING_CHUNK_SIZE", str(CLEANING_CHUNK_SIZE))
    try:
        chunk_size = int(raw_size)
    except ValueError as exc:
        raise ValueError("CLEANING_CHUNK_SIZE must be an integer") from exc

    if chunk_size <= 0:
        raise ValueError("CLEANING_CHUNK_SIZE must be positive")
    return chunk_size


def _read_episode_count_config() -> int:
    raw_count = os.getenv("DEFAULT_EPISODE_COUNT", str(DEFAULT_EPISODE_COUNT))
    try:
        count = int(raw_count)
    except ValueError as exc:
        raise ValueError("DEFAULT_EPISODE_COUNT must be an integer") from exc

    if count <= 0:
        raise ValueError("DEFAULT_EPISODE_COUNT must be positive")
    return count


def _read_episode_split_repair_rounds_config() -> int:
    raw_rounds = os.getenv("EPISODE_SPLIT_REPAIR_ROUNDS", str(DEFAULT_EPISODE_SPLIT_REPAIR_ROUNDS))
    try:
        rounds = int(raw_rounds)
    except ValueError as exc:
        raise ValueError("EPISODE_SPLIT_REPAIR_ROUNDS must be an integer") from exc

    if rounds < 0:
        raise ValueError("EPISODE_SPLIT_REPAIR_ROUNDS must be >= 0")
    return rounds


def _read_episode_content_max_workers_config() -> int:
    raw_workers = os.getenv("EPISODE_CONTENT_MAX_WORKERS", str(DEFAULT_EPISODE_CONTENT_MAX_WORKERS))
    try:
        workers = int(raw_workers)
    except ValueError as exc:
        raise ValueError("EPISODE_CONTENT_MAX_WORKERS must be an integer") from exc

    if workers <= 0:
        raise ValueError("EPISODE_CONTENT_MAX_WORKERS must be positive")
    return workers


def _read_storyboard_max_workers_config() -> int:
    raw_workers = os.getenv("STORYBOARD_MAX_WORKERS", str(DEFAULT_STORYBOARD_MAX_WORKERS))
    try:
        workers = int(raw_workers)
    except ValueError as exc:
        raise ValueError("STORYBOARD_MAX_WORKERS must be an integer") from exc

    if workers <= 0:
        raise ValueError("STORYBOARD_MAX_WORKERS must be positive")
    return workers


def _split_into_units(text: str, window_min: int, window_max: int) -> list[dict[str, Any]]:
    normalized = text.replace("\r\n", "\n").strip()
    if not normalized or normalized == "[EMPTY_SCRIPT]":
        return []

    paragraphs = [p.strip() for p in re.split(r"\n{2,}", normalized) if p.strip()]
    expanded: list[tuple[str, int, int]] = []
    for para_index, paragraph in enumerate(paragraphs):
        pieces = _split_paragraph_if_needed(paragraph, window_max)
        if not pieces:
            continue
        for piece in pieces:
            expanded.append((piece, para_index, para_index))

    units: list[dict[str, Any]] = []
    cursor = 0
    unit_idx = 1
    while cursor < len(expanded):
        piece, start_para, _ = expanded[cursor]
        current_parts = [piece]
        current_chars = len(piece)
        end_para = start_para
        cursor += 1

        while cursor < len(expanded):
            next_piece, _, next_end_para = expanded[cursor]
            projected = current_chars + 2 + len(next_piece)
            if projected <= window_max:
                current_parts.append(next_piece)
                current_chars = projected
                end_para = next_end_para
                cursor += 1
            elif current_chars < window_min:
                current_parts.append(next_piece)
                current_chars = projected
                end_para = next_end_para
                cursor += 1
            else:
                break

        unit_text = "\n\n".join(current_parts).strip()
        units.append(
            {
                "unit_id": f"u_{unit_idx:04d}",
                "char_count": len(unit_text),
                "source_span": {
                    "start_para": start_para + 1,
                    "end_para": end_para + 1,
                },
                "text": unit_text,
            }
        )
        unit_idx += 1

    if len(units) >= 2 and units[-1]["char_count"] < window_min:
        merged_text = (units[-2]["text"] + "\n\n" + units[-1]["text"]).strip()
        units[-2]["text"] = merged_text
        units[-2]["char_count"] = len(merged_text)
        units[-2]["source_span"]["end_para"] = units[-1]["source_span"]["end_para"]
        units.pop()

    return units


def _split_paragraph_if_needed(paragraph: str, window_max: int) -> list[str]:
    if len(paragraph) <= window_max:
        return [paragraph]

    sentences = _sentence_split(paragraph)
    chunks: list[str] = []
    current = ""

    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue
        if len(sentence) > window_max:
            if current.strip():
                chunks.append(current.strip())
                current = ""
            chunks.extend(
                [
                    sentence[i : i + window_max].strip()
                    for i in range(0, len(sentence), window_max)
                    if sentence[i : i + window_max].strip()
                ]
            )
            continue

        candidate = sentence if not current else f"{current}{sentence}"
        if len(candidate) <= window_max:
            current = candidate
        else:
            chunks.append(current.strip())
            current = sentence

    if current.strip():
        chunks.append(current.strip())

    return chunks


def _sentence_split(text: str) -> list[str]:
    parts = re.split(r"(?<=[。！？!?；;])", text)
    return [part for part in parts if part and part.strip()]
