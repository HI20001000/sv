from __future__ import annotations

import json
from typing import Any


def empty_story_schema() -> dict[str, Any]:
    return {
        "task_metadata": {
            "task_id": "",
            "source_type": "",
            "source_title": "",
            "language": "",
            "target_locale": "",
            "analysis_purpose": "",
            "version": "",
            "notes": "",
        },
        "source_summary": {
            "short_summary": "",
            "full_summary": "",
            "theme": "",
            "genre": [],
            "tone": [],
            "narrative_style": "",
            "evidence": [],
        },
        "story_core": {
            "protagonist": {
                "name": "",
                "aliases": [],
                "role_type": "主角",
                "summary": "",
                "goal": "",
                "pain_point": "",
                "motivation": "",
                "weakness": "",
                "growth_arc": "",
                "evidence": [],
            },
            "antagonist": {
                "name": "",
                "aliases": [],
                "role_type": "反派",
                "summary": "",
                "goal": "",
                "conflict_with_protagonist": "",
                "threat_level": "",
                "evidence": [],
            },
            "core_conflict": {
                "conflict_type": "",
                "conflict_description": "",
                "stakes": "",
                "central_question": "",
                "evidence": [],
            },
            "protagonist_objective": "",
            "protagonist_pain_point": "",
            "relationship_tensions": [],
        },
        "characters": [],
        "plot_structure": {
            "major_plot_points": [],
            "turning_points": [],
            "reversal_points": [],
            "emotional_curve": [],
            "hook_points": [],
        },
        "props": [],
        "background": {
            "era": "",
            "time_period": "",
            "locations": [],
            "social_context": [],
            "world_rules": [],
            "power_structure": "",
            "economic_context": "",
            "cultural_context": "",
            "evidence": [],
        },
        "localization_features": {
            "cultural_binding_elements": [],
            "relationship_terms": [],
            "value_expression_terms": [],
            "worldview_terms": [],
            "replaceable_carriers": [],
            "high_risk_localization_items": [],
        },
        "adaptation_guidance": {
            "must_keep_elements": [],
            "can_modify_elements": [],
            "should_remove_or_replace_elements": [],
            "tone_preservation_notes": "",
            "character_preservation_notes": "",
            "plot_preservation_notes": "",
            "localization_strategy": "",
            "evidence": [],
        },
        "quality_control": {
            "missing_information": [],
            "ambiguous_points": [],
            "assumptions": [],
            "consistency_checks": [],
            "overall_confidence": 0.0,
        },
    }


def normalize_story_schema(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        return empty_story_schema()

    if _looks_like_legacy_kb_schema(data):
        data = _legacy_kb_to_story_schema(data)

    if _looks_like_legacy_story_bible(data):
        data = _legacy_to_story_schema(data)

    base = empty_story_schema()
    metadata = _coerce_dict(data.get("task_metadata"))
    summary = _coerce_dict(data.get("source_summary"))
    story_core = _coerce_dict(data.get("story_core"))
    plot_structure = _coerce_dict(data.get("plot_structure"))
    background = _coerce_dict(data.get("background"))
    localization = _coerce_dict(data.get("localization_features"))
    guidance = _coerce_dict(data.get("adaptation_guidance"))
    quality = _coerce_dict(data.get("quality_control"))

    normalized = {
        "task_metadata": {
            "task_id": _coerce_text(metadata.get("task_id")),
            "source_type": _coerce_text(metadata.get("source_type")),
            "source_title": _coerce_text(metadata.get("source_title")),
            "language": _coerce_text(metadata.get("language")),
            "target_locale": _coerce_text(metadata.get("target_locale")),
            "analysis_purpose": _coerce_text(metadata.get("analysis_purpose")),
            "version": _coerce_text(metadata.get("version")),
            "notes": _coerce_text(metadata.get("notes")),
        },
        "source_summary": {
            "short_summary": _coerce_text(summary.get("short_summary")),
            "full_summary": _coerce_text(summary.get("full_summary")),
            "theme": _coerce_text(summary.get("theme")),
            "genre": _coerce_list(summary.get("genre")),
            "tone": _coerce_list(summary.get("tone")),
            "narrative_style": _coerce_text(summary.get("narrative_style")),
            "evidence": _coerce_list(summary.get("evidence")),
        },
        "story_core": {
            "protagonist": _normalize_core_protagonist(story_core.get("protagonist")),
            "antagonist": _normalize_core_antagonist(story_core.get("antagonist")),
            "core_conflict": _normalize_core_conflict(story_core.get("core_conflict")),
            "protagonist_objective": _coerce_text(story_core.get("protagonist_objective")),
            "protagonist_pain_point": _coerce_text(story_core.get("protagonist_pain_point")),
            "relationship_tensions": [
                _normalize_relationship_tension(item)
                for item in _coerce_list(story_core.get("relationship_tensions"))
            ],
        },
        "characters": _dedupe_named_records(
            [_normalize_character(item) for item in _coerce_list(data.get("characters"))],
            aliases_key="aliases",
        ),
        "plot_structure": {
            "major_plot_points": [
                _normalize_major_plot_point(item, index)
                for index, item in enumerate(_coerce_list(plot_structure.get("major_plot_points")), start=1)
            ],
            "turning_points": [
                _normalize_turning_point(item, index)
                for index, item in enumerate(_coerce_list(plot_structure.get("turning_points")), start=1)
            ],
            "reversal_points": [
                _normalize_reversal_point(item, index)
                for index, item in enumerate(_coerce_list(plot_structure.get("reversal_points")), start=1)
            ],
            "emotional_curve": [
                _normalize_emotional_curve(item)
                for item in _coerce_list(plot_structure.get("emotional_curve"))
            ],
            "hook_points": [
                _normalize_hook_point(item)
                for item in _coerce_list(plot_structure.get("hook_points"))
            ],
        },
        "props": _dedupe_named_records(
            [_normalize_prop(item) for item in _coerce_list(data.get("props"))],
            aliases_key=None,
        ),
        "background": {
            "era": _coerce_text(background.get("era")),
            "time_period": _coerce_text(background.get("time_period")),
            "locations": [
                _normalize_location(item)
                for item in _coerce_list(background.get("locations"))
            ],
            "social_context": _coerce_list(background.get("social_context")),
            "world_rules": [
                _normalize_world_rule(item)
                for item in _coerce_list(background.get("world_rules"))
            ],
            "power_structure": _coerce_text(background.get("power_structure")),
            "economic_context": _coerce_text(background.get("economic_context")),
            "cultural_context": _coerce_text(background.get("cultural_context")),
            "evidence": _coerce_list(background.get("evidence")),
        },
        "localization_features": {
            "cultural_binding_elements": [
                _normalize_cultural_binding(item)
                for item in _coerce_list(localization.get("cultural_binding_elements"))
            ],
            "relationship_terms": [
                _normalize_relationship_term(item)
                for item in _coerce_list(localization.get("relationship_terms"))
            ],
            "value_expression_terms": [
                _normalize_value_term(item)
                for item in _coerce_list(localization.get("value_expression_terms"))
            ],
            "worldview_terms": [
                _normalize_worldview_term(item)
                for item in _coerce_list(localization.get("worldview_terms"))
            ],
            "replaceable_carriers": [
                _normalize_replaceable_carrier(item)
                for item in _coerce_list(localization.get("replaceable_carriers"))
            ],
            "high_risk_localization_items": [
                _normalize_high_risk_item(item)
                for item in _coerce_list(localization.get("high_risk_localization_items"))
            ],
        },
        "adaptation_guidance": {
            "must_keep_elements": _coerce_list(guidance.get("must_keep_elements")),
            "can_modify_elements": _coerce_list(guidance.get("can_modify_elements")),
            "should_remove_or_replace_elements": _coerce_list(guidance.get("should_remove_or_replace_elements")),
            "tone_preservation_notes": _coerce_text(guidance.get("tone_preservation_notes")),
            "character_preservation_notes": _coerce_text(guidance.get("character_preservation_notes")),
            "plot_preservation_notes": _coerce_text(guidance.get("plot_preservation_notes")),
            "localization_strategy": _coerce_text(guidance.get("localization_strategy")),
            "evidence": _coerce_list(guidance.get("evidence")),
        },
        "quality_control": {
            "missing_information": _coerce_list(quality.get("missing_information")),
            "ambiguous_points": _coerce_list(quality.get("ambiguous_points")),
            "assumptions": _coerce_list(quality.get("assumptions")),
            "consistency_checks": [
                _normalize_consistency_check(item)
                for item in _coerce_list(quality.get("consistency_checks"))
            ],
            "overall_confidence": _coerce_float(quality.get("overall_confidence")),
        },
    }

    _fill_core_from_characters(normalized)
    _fill_summary_from_legacy(base, normalized)
    return normalized


def story_schema_to_runtime_context(data: Any) -> dict[str, Any]:
    schema = normalize_story_schema(data)
    background = schema["background"]
    return {
        **schema,
        "characters": schema["characters"],
        "props": schema["props"],
        "background": {
            "era": background.get("era", ""),
            "time_period": background.get("time_period", ""),
            "locations": extract_text_sequence(background.get("locations")),
            "social_context": extract_text_sequence(background.get("social_context")),
            "world_rules": extract_text_sequence(background.get("world_rules")),
            "power_structure": background.get("power_structure", ""),
            "economic_context": background.get("economic_context", ""),
            "cultural_context": background.get("cultural_context", ""),
            "evidence": extract_text_sequence(background.get("evidence")),
        },
        "background_details": background,
    }


def extract_text_sequence(value: Any) -> list[str]:
    output: list[str] = []
    for item in _coerce_list(value):
        text = _display_text(item)
        if text:
            output.append(text)
    return _unique_texts(output)


def merge_story_schemas(items: list[Any]) -> dict[str, Any]:
    schemas = [normalize_story_schema(item) for item in items if isinstance(item, dict)]
    if not schemas:
        return empty_story_schema()

    merged = empty_story_schema()

    for key in merged["task_metadata"]:
        merged["task_metadata"][key] = _first_text(schema["task_metadata"].get(key) for schema in schemas)

    summary = merged["source_summary"]
    for key in ("short_summary", "full_summary", "theme", "narrative_style"):
        summary[key] = _first_text(schema["source_summary"].get(key) for schema in schemas)
    summary["genre"] = _merge_lists(schema["source_summary"].get("genre") for schema in schemas)
    summary["tone"] = _merge_lists(schema["source_summary"].get("tone") for schema in schemas)
    summary["evidence"] = _merge_lists(schema["source_summary"].get("evidence") for schema in schemas)

    core = merged["story_core"]
    for role_key in ("protagonist", "antagonist"):
        for field in core[role_key]:
            if field == "aliases" or field == "evidence":
                core[role_key][field] = _merge_lists(schema["story_core"][role_key].get(field) for schema in schemas)
            else:
                core[role_key][field] = _first_text(schema["story_core"][role_key].get(field) for schema in schemas)
    for field in core["core_conflict"]:
        if field == "evidence":
            core["core_conflict"][field] = _merge_lists(schema["story_core"]["core_conflict"].get(field) for schema in schemas)
        else:
            core["core_conflict"][field] = _first_text(
                schema["story_core"]["core_conflict"].get(field) for schema in schemas
            )
    core["protagonist_objective"] = _first_text(
        schema["story_core"].get("protagonist_objective") for schema in schemas
    )
    core["protagonist_pain_point"] = _first_text(
        schema["story_core"].get("protagonist_pain_point") for schema in schemas
    )
    core["relationship_tensions"] = _merge_records(schema["story_core"].get("relationship_tensions") for schema in schemas)

    merged["characters"] = _merge_records(schema.get("characters") for schema in schemas)
    merged["props"] = _merge_records(schema.get("props") for schema in schemas)

    plot = merged["plot_structure"]
    for field in plot:
        plot[field] = _merge_records(schema["plot_structure"].get(field) for schema in schemas)

    background = merged["background"]
    for key in ("era", "time_period", "power_structure", "economic_context", "cultural_context"):
        background[key] = _first_text(schema["background"].get(key) for schema in schemas)
    for key in ("locations", "social_context", "world_rules", "evidence"):
        background[key] = _merge_records(schema["background"].get(key) for schema in schemas)

    localization = merged["localization_features"]
    for key in localization:
        localization[key] = _merge_records(schema["localization_features"].get(key) for schema in schemas)

    guidance = merged["adaptation_guidance"]
    for key in ("must_keep_elements", "can_modify_elements", "should_remove_or_replace_elements", "evidence"):
        guidance[key] = _merge_lists(schema["adaptation_guidance"].get(key) for schema in schemas)
    for key in (
        "tone_preservation_notes",
        "character_preservation_notes",
        "plot_preservation_notes",
        "localization_strategy",
    ):
        guidance[key] = _first_text(schema["adaptation_guidance"].get(key) for schema in schemas)

    quality = merged["quality_control"]
    for key in ("missing_information", "ambiguous_points", "assumptions"):
        quality[key] = _merge_lists(schema["quality_control"].get(key) for schema in schemas)
    quality["consistency_checks"] = _merge_records(schema["quality_control"].get("consistency_checks") for schema in schemas)
    quality["overall_confidence"] = max(schema["quality_control"].get("overall_confidence", 0.0) for schema in schemas)

    return normalize_story_schema(merged)


def _legacy_to_story_schema(data: dict[str, Any]) -> dict[str, Any]:
    background = _coerce_dict(data.get("background"))
    return {
        "characters": data.get("characters", []),
        "props": data.get("props", []),
        "background": {
            "era": background.get("era", ""),
            "locations": [
                {"name": _display_text(item), "location_type": "", "description": "", "story_function": "", "localization_notes": "", "evidence": []}
                for item in _coerce_list(background.get("locations"))
                if _display_text(item)
            ],
            "social_context": _coerce_list(background.get("social_context")),
            "world_rules": [
                {"rule": _display_text(item), "description": "", "impact_on_plot": "", "evidence": []}
                for item in _coerce_list(background.get("world_rules"))
                if _display_text(item)
            ],
            "evidence": _coerce_list(background.get("evidence")),
        },
    }


def _legacy_kb_to_story_schema(data: dict[str, Any]) -> dict[str, Any]:
    metadata = _coerce_dict(data.get("任务元数据"))
    summary = _coerce_dict(data.get("源文本摘要"))
    content = _coerce_dict(data.get("内容特征"))
    culture = _coerce_dict(data.get("文化特征"))

    raw_protagonist = content.get("主角")
    raw_antagonist = content.get("反派")
    raw_core_conflict = content.get("核心冲突")
    protagonist = _coerce_dict(raw_protagonist) or {"summary": _display_text(raw_protagonist)}
    antagonist = _coerce_dict(raw_antagonist) or {"summary": _display_text(raw_antagonist)}
    core_conflict = _coerce_dict(raw_core_conflict) or {"conflict_description": _display_text(raw_core_conflict)}

    characters = []
    if protagonist:
        characters.append(
            {
                "name": protagonist.get("name") or protagonist.get("姓名") or protagonist.get("名称") or "",
                "aliases": protagonist.get("aliases") or protagonist.get("别名") or protagonist.get("称谓") or [],
                "role_type": "主角",
                "summary": protagonist.get("summary") or protagonist.get("摘要") or _display_text(protagonist),
                "goal": protagonist.get("goal") or content.get("主角目标") or "",
                "motivation": protagonist.get("motivation") or "",
                "evidence": protagonist.get("evidence") or protagonist.get("证据") or [],
            }
        )
    if antagonist:
        characters.append(
            {
                "name": antagonist.get("name") or antagonist.get("姓名") or antagonist.get("名称") or "",
                "aliases": antagonist.get("aliases") or antagonist.get("别名") or antagonist.get("称谓") or [],
                "role_type": "反派",
                "summary": antagonist.get("summary") or antagonist.get("摘要") or _display_text(antagonist),
                "goal": antagonist.get("goal") or "",
                "evidence": antagonist.get("evidence") or antagonist.get("证据") or [],
            }
        )

    return {
        "task_metadata": {
            "task_id": _coerce_text(metadata.get("task_id") or metadata.get("record_id")),
            "source_type": _coerce_text(metadata.get("source_type")),
            "source_title": _coerce_text(metadata.get("source_title") or metadata.get("source_file_name")),
            "language": _coerce_text(metadata.get("language")),
            "target_locale": _coerce_text(metadata.get("target_locale")),
            "analysis_purpose": _coerce_text(metadata.get("analysis_purpose")),
            "version": _coerce_text(metadata.get("version")),
            "notes": _coerce_text(metadata.get("notes")),
        },
        "source_summary": {
            "short_summary": _coerce_text(
                summary.get("short_summary") or summary.get("摘要") or summary.get("summary") or summary.get("主线摘要")
            ),
            "full_summary": _coerce_text(
                summary.get("full_summary") or summary.get("详细摘要") or summary.get("主线摘要")
            ),
            "theme": _coerce_text(summary.get("theme") or summary.get("主题") or summary.get("题材")),
            "genre": _coerce_list(summary.get("genre") or summary.get("类型") or summary.get("题材")),
            "tone": _coerce_list(summary.get("tone") or summary.get("基调") or summary.get("故事基调")),
            "narrative_style": _coerce_text(summary.get("narrative_style") or summary.get("叙事风格")),
            "evidence": _coerce_list(summary.get("evidence") or summary.get("证据")),
        },
        "story_core": {
            "protagonist": protagonist,
            "antagonist": antagonist,
            "core_conflict": core_conflict,
            "protagonist_objective": content.get("主角目标", ""),
            "protagonist_pain_point": content.get("主角痛点", ""),
            "relationship_tensions": content.get("关系张力点", []),
        },
        "characters": characters,
        "plot_structure": {
            "major_plot_points": content.get("主要情节点", []),
            "turning_points": [],
            "reversal_points": content.get("反转点", []),
            "emotional_curve": content.get("情感曲线", []),
            "hook_points": content.get("钩子点", []),
        },
        "localization_features": {
            "cultural_binding_elements": culture.get("文化绑定元素", []),
            "relationship_terms": culture.get("关系称谓", []),
            "value_expression_terms": culture.get("价值表达术语", []),
            "worldview_terms": culture.get("世界观术语", []),
            "replaceable_carriers": culture.get("可替换载体", []),
            "high_risk_localization_items": culture.get("高风险本地化项", []),
        },
    }


def _looks_like_legacy_story_bible(data: dict[str, Any]) -> bool:
    new_schema_keys = {
        "source_summary",
        "story_core",
        "plot_structure",
        "localization_features",
        "adaptation_guidance",
        "quality_control",
    }
    return (
        "task_metadata" not in data
        and not any(key in data for key in new_schema_keys)
        and any(key in data for key in ("characters", "props", "background"))
    )


def _looks_like_legacy_kb_schema(data: dict[str, Any]) -> bool:
    return "task_metadata" not in data and any(key in data for key in ("任务元数据", "内容特征", "文化特征"))


def _normalize_core_protagonist(value: Any) -> dict[str, Any]:
    raw = _coerce_dict(value)
    return {
        "name": _coerce_text(raw.get("name") or raw.get("姓名") or raw.get("名称")),
        "aliases": _coerce_list(raw.get("aliases") or raw.get("别名") or raw.get("称谓")),
        "role_type": _coerce_text(raw.get("role_type")) or "主角",
        "summary": _coerce_text(raw.get("summary") or raw.get("摘要") or raw.get("identity") or raw.get("身份")),
        "goal": _coerce_text(raw.get("goal") or raw.get("目标")),
        "pain_point": _coerce_text(raw.get("pain_point") or raw.get("痛点") or raw.get("situation") or raw.get("处境")),
        "motivation": _coerce_text(raw.get("motivation") or raw.get("动机")),
        "weakness": _coerce_text(raw.get("weakness") or raw.get("弱点")),
        "growth_arc": _coerce_text(raw.get("growth_arc") or raw.get("成长线")),
        "evidence": _coerce_list(raw.get("evidence") or raw.get("证据")),
    }


def _normalize_core_antagonist(value: Any) -> dict[str, Any]:
    raw = _coerce_dict(value)
    return {
        "name": _coerce_text(raw.get("name") or raw.get("姓名") or raw.get("名称")),
        "aliases": _coerce_list(raw.get("aliases") or raw.get("别名") or raw.get("称谓")),
        "role_type": _coerce_text(raw.get("role_type")) or "反派",
        "summary": _coerce_text(raw.get("summary") or raw.get("摘要") or raw.get("identity") or raw.get("身份")),
        "goal": _coerce_text(raw.get("goal") or raw.get("目标")),
        "conflict_with_protagonist": _coerce_text(
            raw.get("conflict_with_protagonist") or raw.get("与主角冲突") or raw.get("methods") or raw.get("手段")
        ),
        "threat_level": _coerce_text(raw.get("threat_level") or raw.get("威胁等级")),
        "evidence": _coerce_list(raw.get("evidence") or raw.get("证据")),
    }


def _normalize_core_conflict(value: Any) -> dict[str, Any]:
    raw = _coerce_dict(value)
    return {
        "conflict_type": _coerce_text(raw.get("conflict_type") or raw.get("type") or raw.get("类型")),
        "conflict_description": _coerce_text(
            raw.get("conflict_description")
            or raw.get("description")
            or raw.get("主矛盾")
            or raw.get("核心冲突")
        ),
        "stakes": _coerce_text(raw.get("stakes") or raw.get("外部阻力") or raw.get("冲突升级方式")),
        "central_question": _coerce_text(raw.get("central_question") or raw.get("内在痛点")),
        "evidence": _coerce_list(raw.get("evidence") or raw.get("证据")),
    }


def _normalize_relationship_tension(value: Any) -> dict[str, Any]:
    raw = _coerce_dict(value)
    if not raw:
        raw = {"tension_point": _display_text(value)}
    return {
        "characters": _coerce_list(raw.get("characters")),
        "relationship_type": _coerce_text(raw.get("relationship_type")),
        "tension_point": _coerce_text(raw.get("tension_point") or raw.get("description") or raw.get("name")),
        "emotional_state": _coerce_text(raw.get("emotional_state")),
        "evidence": _coerce_list(raw.get("evidence")),
    }


def _normalize_character(value: Any) -> dict[str, Any]:
    raw = _coerce_dict(value)
    if not raw:
        raw = {"name": _display_text(value)}
    return {
        "name": _coerce_text(raw.get("name")),
        "aliases": _coerce_list(raw.get("aliases")),
        "role_type": _coerce_text(raw.get("role_type")) or "未知",
        "importance_level": _coerce_text(raw.get("importance_level")),
        "summary": _coerce_text(raw.get("summary")),
        "personality": _coerce_list(raw.get("personality")),
        "goal": _coerce_text(raw.get("goal")),
        "motivation": _coerce_text(raw.get("motivation")),
        "relationship_to_protagonist": _coerce_text(raw.get("relationship_to_protagonist")),
        "relationship_to_antagonist": _coerce_text(raw.get("relationship_to_antagonist")),
        "character_arc": _coerce_text(raw.get("character_arc")),
        "key_actions": _coerce_list(raw.get("key_actions")),
        "localization_notes": _coerce_text(raw.get("localization_notes")),
        "evidence": _coerce_list(raw.get("evidence")),
        "confidence": _coerce_float(raw.get("confidence")),
    }


def _normalize_prop(value: Any) -> dict[str, Any]:
    raw = _coerce_dict(value)
    if not raw:
        raw = {"name": _display_text(value)}
    return {
        "name": _coerce_text(raw.get("name")),
        "prop_type": _coerce_text(raw.get("prop_type")),
        "purpose": _coerce_text(raw.get("purpose")),
        "owner_or_user": _coerce_text(raw.get("owner_or_user")),
        "story_function": _coerce_text(raw.get("story_function")),
        "symbolic_meaning": _coerce_text(raw.get("symbolic_meaning")),
        "replaceable": _coerce_bool(raw.get("replaceable"), default=True),
        "localization_notes": _coerce_text(raw.get("localization_notes")),
        "evidence": _coerce_list(raw.get("evidence")),
        "confidence": _coerce_float(raw.get("confidence")),
    }


def _normalize_major_plot_point(value: Any, index: int) -> dict[str, Any]:
    raw = _coerce_dict(value)
    if not raw:
        raw = {"plot_point": _display_text(value)}
    return {
        "order": _coerce_int(raw.get("order"), default=index),
        "plot_point": _coerce_text(raw.get("plot_point") or raw.get("description") or raw.get("name")),
        "function": _coerce_text(raw.get("function") or raw.get("功能")),
        "characters_involved": _coerce_list(raw.get("characters_involved")),
        "location": _coerce_text(raw.get("location")),
        "emotional_effect": _coerce_text(raw.get("emotional_effect")),
        "evidence": _coerce_list(raw.get("evidence")),
    }


def _normalize_turning_point(value: Any, index: int) -> dict[str, Any]:
    raw = _coerce_dict(value)
    if not raw:
        raw = {"description": _display_text(value)}
    return {
        "order": _coerce_int(raw.get("order"), default=index),
        "description": _coerce_text(raw.get("description")),
        "before_state": _coerce_text(raw.get("before_state")),
        "after_state": _coerce_text(raw.get("after_state")),
        "impact": _coerce_text(raw.get("impact")),
        "evidence": _coerce_list(raw.get("evidence")),
    }


def _normalize_reversal_point(value: Any, index: int) -> dict[str, Any]:
    raw = _coerce_dict(value)
    if not raw:
        raw = {"description": _display_text(value)}
    return {
        "order": _coerce_int(raw.get("order"), default=index),
        "description": _coerce_text(raw.get("description") or raw.get("name")),
        "reversal_type": _coerce_text(raw.get("reversal_type") or raw.get("type") or raw.get("类型")),
        "impact_on_story": _coerce_text(raw.get("impact_on_story")),
        "evidence": _coerce_list(raw.get("evidence")),
    }


def _normalize_emotional_curve(value: Any) -> dict[str, Any]:
    raw = _coerce_dict(value)
    if not raw:
        raw = {"emotion": _display_text(value)}
    return {
        "stage": _coerce_text(raw.get("stage")),
        "emotion": _coerce_text(raw.get("emotion") or raw.get("description") or raw.get("name")),
        "intensity": _coerce_int(raw.get("intensity"), default=0),
        "trigger_event": _coerce_text(raw.get("trigger_event")),
        "evidence": _coerce_list(raw.get("evidence")),
    }


def _normalize_hook_point(value: Any) -> dict[str, Any]:
    raw = _coerce_dict(value)
    if not raw:
        raw = {"description": _display_text(value)}
    return {
        "type": _coerce_text(raw.get("type") or raw.get("name")),
        "description": _coerce_text(raw.get("description") or raw.get("name")),
        "placement": _coerce_text(raw.get("placement")),
        "intended_effect": _coerce_text(raw.get("intended_effect")),
        "evidence": _coerce_list(raw.get("evidence")),
    }


def _normalize_location(value: Any) -> dict[str, Any]:
    raw = _coerce_dict(value)
    if not raw:
        raw = {"name": _display_text(value)}
    return {
        "name": _coerce_text(raw.get("name")),
        "location_type": _coerce_text(raw.get("location_type")),
        "description": _coerce_text(raw.get("description")),
        "story_function": _coerce_text(raw.get("story_function")),
        "localization_notes": _coerce_text(raw.get("localization_notes")),
        "evidence": _coerce_list(raw.get("evidence")),
    }


def _normalize_world_rule(value: Any) -> dict[str, Any]:
    raw = _coerce_dict(value)
    if not raw:
        raw = {"rule": _display_text(value)}
    return {
        "rule": _coerce_text(raw.get("rule")),
        "description": _coerce_text(raw.get("description")),
        "impact_on_plot": _coerce_text(raw.get("impact_on_plot")),
        "evidence": _coerce_list(raw.get("evidence")),
    }


def _normalize_cultural_binding(value: Any) -> dict[str, Any]:
    raw = _coerce_dict(value)
    if not raw:
        raw = {"item": _display_text(value)}
    return {
        "item": _coerce_text(raw.get("item") or raw.get("name")),
        "type": _coerce_text(raw.get("type") or raw.get("类型")),
        "description": _coerce_text(raw.get("description") or raw.get("负担强度")),
        "localization_difficulty": _coerce_text(raw.get("localization_difficulty") or raw.get("负担强度")),
        "suggested_adaptation": _coerce_text(raw.get("suggested_adaptation")),
        "evidence": _coerce_list(raw.get("evidence")),
    }


def _normalize_relationship_term(value: Any) -> dict[str, Any]:
    raw = _coerce_dict(value)
    if not raw:
        raw = {"term": _display_text(value)}
    return {
        "term": _coerce_text(raw.get("term")),
        "meaning": _coerce_text(raw.get("meaning")),
        "relationship_context": _coerce_text(raw.get("relationship_context")),
        "target_locale_adaptation": _coerce_text(raw.get("target_locale_adaptation")),
        "risk_level": _coerce_text(raw.get("risk_level")),
        "evidence": _coerce_list(raw.get("evidence")),
    }


def _normalize_value_term(value: Any) -> dict[str, Any]:
    raw = _coerce_dict(value)
    if not raw:
        raw = {"term": _display_text(value)}
    return {
        "term": _coerce_text(raw.get("term")),
        "value_type": _coerce_text(raw.get("value_type")),
        "meaning": _coerce_text(raw.get("meaning")),
        "adaptation_strategy": _coerce_text(raw.get("adaptation_strategy")),
        "evidence": _coerce_list(raw.get("evidence")),
    }


def _normalize_worldview_term(value: Any) -> dict[str, Any]:
    raw = _coerce_dict(value)
    if not raw:
        raw = {"term": _display_text(value)}
    return {
        "term": _coerce_text(raw.get("term")),
        "definition": _coerce_text(raw.get("definition")),
        "importance": _coerce_text(raw.get("importance")),
        "translation_or_adaptation": _coerce_text(raw.get("translation_or_adaptation")),
        "evidence": _coerce_list(raw.get("evidence")),
    }


def _normalize_replaceable_carrier(value: Any) -> dict[str, Any]:
    raw = _coerce_dict(value)
    if not raw:
        raw = {"original_item": _display_text(value)}
    return {
        "original_item": _coerce_text(raw.get("original_item")),
        "function_in_story": _coerce_text(raw.get("function_in_story")),
        "replacement_options": _coerce_list(raw.get("replacement_options")),
        "replacement_constraints": _coerce_text(raw.get("replacement_constraints")),
        "evidence": _coerce_list(raw.get("evidence")),
    }


def _normalize_high_risk_item(value: Any) -> dict[str, Any]:
    raw = _coerce_dict(value)
    if not raw:
        raw = {"item": _display_text(value)}
    return {
        "item": _coerce_text(raw.get("item") or raw.get("name")),
        "risk_type": _coerce_text(raw.get("risk_type") or raw.get("type") or raw.get("类型")),
        "risk_description": _coerce_text(raw.get("risk_description") or raw.get("description")),
        "risk_level": _coerce_text(raw.get("risk_level") or raw.get("风险等级")),
        "mitigation_strategy": _coerce_text(raw.get("mitigation_strategy")),
        "evidence": _coerce_list(raw.get("evidence")),
    }


def _normalize_consistency_check(value: Any) -> dict[str, Any]:
    raw = _coerce_dict(value)
    if not raw:
        raw = {"check_item": _display_text(value)}
    return {
        "check_item": _coerce_text(raw.get("check_item")),
        "result": _coerce_text(raw.get("result")),
        "issue": _coerce_text(raw.get("issue")),
        "suggestion": _coerce_text(raw.get("suggestion")),
    }


def _dedupe_named_records(items: list[dict[str, Any]], aliases_key: str | None) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in items:
        name = _coerce_text(item.get("name"))
        if not name:
            continue
        candidates = [name]
        if aliases_key:
            candidates.extend(_coerce_list(item.get(aliases_key)))
        key = next((_normalize_key(candidate) for candidate in candidates if _normalize_key(candidate)), "")
        if not key or key in seen:
            continue
        seen.add(key)
        output.append(item)
    return output


def _fill_core_from_characters(schema: dict[str, Any]) -> None:
    characters = schema.get("characters", [])
    if not isinstance(characters, list):
        return
    core = schema.get("story_core", {})
    protagonist = core.get("protagonist", {})
    antagonist = core.get("antagonist", {})
    for character in characters:
        role_type = _coerce_text(character.get("role_type"))
        if not protagonist.get("name") and "主角" in role_type:
            protagonist.update(
                {
                    "name": character.get("name", ""),
                    "aliases": character.get("aliases", []),
                    "summary": character.get("summary", ""),
                    "goal": character.get("goal", ""),
                    "motivation": character.get("motivation", ""),
                    "growth_arc": character.get("character_arc", ""),
                    "evidence": character.get("evidence", []),
                }
            )
        if not antagonist.get("name") and "反派" in role_type:
            antagonist.update(
                {
                    "name": character.get("name", ""),
                    "aliases": character.get("aliases", []),
                    "summary": character.get("summary", ""),
                    "goal": character.get("goal", ""),
                    "evidence": character.get("evidence", []),
                }
            )


def _fill_summary_from_legacy(_: dict[str, Any], schema: dict[str, Any]) -> None:
    if schema["source_summary"]["short_summary"]:
        return
    core_conflict = schema["story_core"]["core_conflict"].get("conflict_description", "")
    if core_conflict:
        schema["source_summary"]["short_summary"] = core_conflict


def _coerce_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _coerce_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if value is None:
        return []
    if isinstance(value, str) and not value.strip():
        return []
    return [value]


def _coerce_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, dict):
        return _display_text(value)
    return json.dumps(value, ensure_ascii=False)


def _display_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        for key in ("name", "item", "term", "rule", "description", "plot_point", "summary", "tension_point"):
            text = _coerce_text(value.get(key))
            if text:
                return text
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, list):
        return " / ".join(text for text in (_display_text(item) for item in value) if text)
    return str(value)


def _coerce_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _coerce_float(value: Any) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(parsed, 1.0))


def _coerce_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes", "y"}:
            return True
        if lowered in {"false", "0", "no", "n"}:
            return False
    return default


def _unique_texts(values: list[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for value in values:
        text = _coerce_text(value)
        key = _normalize_key(text)
        if not text or key in seen:
            continue
        seen.add(key)
        output.append(text)
    return output


def _first_text(values: Any) -> str:
    for value in values:
        text = _coerce_text(value)
        if text:
            return text
    return ""


def _merge_lists(values: Any) -> list[str]:
    merged: list[str] = []
    for value in values:
        merged.extend(extract_text_sequence(value))
    return _unique_texts(merged)


def _merge_records(values: Any) -> list[Any]:
    output: list[Any] = []
    seen: set[str] = set()
    for value in values:
        for item in _coerce_list(value):
            text = _display_text(item)
            key = _normalize_key(text) if text else json.dumps(item, ensure_ascii=False, sort_keys=True)
            if not key or key in seen:
                continue
            seen.add(key)
            output.append(item)
    return output


def _normalize_key(value: str) -> str:
    return "".join(str(value).lower().split())
