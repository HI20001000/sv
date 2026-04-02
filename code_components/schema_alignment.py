from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Callable

from code_components.knowledge_base import get_knowledge_item, list_knowledge_records
from code_components.langChain import optimize_schema_with_prompt, score_schema_alignment_with_prompt
from code_components.story_schema import normalize_story_schema


PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_ALIGNMENT_ROOT = PROJECT_ROOT / "schema_alignment"
FIELD_WEIGHTS_PATH = SCHEMA_ALIGNMENT_ROOT / "field_weights.json"
DEFAULT_SCHEMA_ALIGNMENT_TOP_K = 3
DEFAULT_SCHEMA_ALIGNMENT_THRESHOLD = 0.65
DEFAULT_SCHEMA_EXTRACTION_MAX_ATTEMPTS = 3
DEFAULT_SCHEMA_ALIGNMENT_MAX_ROUNDS = 3

FIELD_WEIGHTS: dict[str, float] = {
    "核心冲突": 0.18,
    "主角目标": 0.10,
    "主角痛点": 0.08,
    "关系张力点": 0.14,
    "主要情节点": 0.10,
    "反转点": 0.12,
    "情感曲线": 0.08,
    "钩子点": 0.10,
    "文化绑定元素": 0.05,
    "高风险本地化项": 0.05,
}
GRADE_VALUES = {"高": 0.8, "中": 0.5, "低": 0.2}
TOPK_COEFFICIENTS = [0.5, 0.35, 0.15]
ProgressCallback = Callable[[str, dict[str, Any]], None]


def ensure_schema_alignment_root() -> None:
    SCHEMA_ALIGNMENT_ROOT.mkdir(parents=True, exist_ok=True)
    if not FIELD_WEIGHTS_PATH.exists():
        write_json_artifact(FIELD_WEIGHTS_PATH, FIELD_WEIGHTS)


def create_schema_alignment_run_dir(project_dir: Path) -> Path:
    ensure_schema_alignment_root()
    run_dir = SCHEMA_ALIGNMENT_ROOT / project_dir.name
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


def read_schema_extraction_max_attempts() -> int:
    return _read_positive_int("SCHEMA_EXTRACTION_MAX_ATTEMPTS", DEFAULT_SCHEMA_EXTRACTION_MAX_ATTEMPTS)


def validate_required_fields(schema: Any) -> dict[str, Any]:
    normalized = normalize_story_schema(schema)
    missing: list[dict[str, str]] = []

    core = normalized.get("story_core", {})
    plot = normalized.get("plot_structure", {})
    localization = normalized.get("localization_features", {})
    summary = normalized.get("source_summary", {})
    background = normalized.get("background", {})

    _require_meaningful(core.get("core_conflict"), "story_core.core_conflict", "核心冲突", missing)
    _require_meaningful(core.get("protagonist_objective"), "story_core.protagonist_objective", "主角目标", missing)
    _require_meaningful(core.get("protagonist_pain_point"), "story_core.protagonist_pain_point", "主角痛点", missing)
    _require_meaningful(core.get("relationship_tensions"), "story_core.relationship_tensions", "关系张力点", missing)
    _require_meaningful(plot.get("major_plot_points"), "plot_structure.major_plot_points", "主要情节点", missing)
    _require_meaningful(plot.get("reversal_points"), "plot_structure.reversal_points", "反转点", missing)
    _require_meaningful(plot.get("emotional_curve"), "plot_structure.emotional_curve", "情感曲线", missing)
    _require_meaningful(plot.get("hook_points"), "plot_structure.hook_points", "钩子点", missing)
    _require_meaningful(
        localization.get("cultural_binding_elements"),
        "localization_features.cultural_binding_elements",
        "文化绑定元素",
        missing,
    )
    _require_meaningful(
        localization.get("high_risk_localization_items"),
        "localization_features.high_risk_localization_items",
        "高风险本地化项",
        missing,
    )
    if not (_has_meaningful_value(summary.get("genre")) or _has_meaningful_value(summary.get("theme"))):
        missing.append(
            {
                "field": "source_summary.genre_or_theme",
                "business_field": "题材标签",
                "reason": "source_summary.genre 和 source_summary.theme 至少需要一个有内容。",
            }
        )
    if not (
        _has_meaningful_value(background.get("era"))
        or _has_meaningful_value(background.get("world_rules"))
        or _has_meaningful_value(background.get("cultural_context"))
    ):
        missing.append(
            {
                "field": "background.era_or_world_rules_or_cultural_context",
                "business_field": "时代/世界观类型",
                "reason": "background.era、background.world_rules、background.cultural_context 至少需要一个有内容。",
            }
        )

    return {
        "passed": not missing,
        "missing_count": len(missing),
        "missing_fields": missing,
        "checked_required_set": [
            "story_core.core_conflict",
            "story_core.protagonist_objective",
            "story_core.protagonist_pain_point",
            "story_core.relationship_tensions",
            "plot_structure.major_plot_points",
            "plot_structure.reversal_points",
            "plot_structure.emotional_curve",
            "plot_structure.hook_points",
            "localization_features.cultural_binding_elements",
            "localization_features.high_risk_localization_items",
            "source_summary.genre_or_theme",
            "background.era_or_world_rules_or_cultural_context",
        ],
    }


def align_schema_with_knowledge_base(
    llm,
    schema: dict[str, Any],
    run_dir: Path,
    progress_callback: ProgressCallback | None = None,
) -> dict[str, Any]:
    ensure_schema_alignment_root()
    run_dir.mkdir(parents=True, exist_ok=True)
    write_json_artifact(FIELD_WEIGHTS_PATH, FIELD_WEIGHTS)

    top_k = _read_positive_int("SCHEMA_ALIGNMENT_TOP_K", DEFAULT_SCHEMA_ALIGNMENT_TOP_K)
    threshold = _read_float("SCHEMA_ALIGNMENT_THRESHOLD", DEFAULT_SCHEMA_ALIGNMENT_THRESHOLD)
    max_rounds = _read_positive_int("SCHEMA_ALIGNMENT_MAX_ROUNDS", DEFAULT_SCHEMA_ALIGNMENT_MAX_ROUNDS)
    if top_k != 3:
        top_k = 3

    current_schema = normalize_story_schema(schema)
    rounds: list[dict[str, Any]] = []

    for round_index in range(1, max_rounds + 1):
        _emit_progress(
            progress_callback,
            "schema_alignment",
            f"Schema alignment round {round_index}/{max_rounds}: recalling TopK={top_k}",
        )
        topk = recall_top_k(current_schema, top_k=top_k)
        write_json_artifact(run_dir / f"topk_recall_round_{round_index}.json", _strip_candidate_schemas(topk))

        scoring_table = score_topk_candidates(
            llm=llm,
            source_schema=current_schema,
            topk=topk,
            round_index=round_index,
            threshold=threshold,
        )
        write_json_artifact(run_dir / f"scoring_table_round_{round_index}.json", scoring_table)

        aggregate = scoring_table["topk_aggregate"]
        _emit_progress(
            progress_callback,
            "schema_alignment",
            f"Schema alignment round {round_index}: aggregate={aggregate:.3f}, threshold={threshold:.3f}",
            aggregate=aggregate,
            threshold=threshold,
            round_index=round_index,
        )
        if scoring_table["passed"]:
            final_summary = {
                "status": "passed",
                "round": round_index,
                "topk_aggregate": aggregate,
                "threshold": threshold,
                "final_schema_file": "final_schema.json",
            }
            write_json_artifact(run_dir / "final_schema.json", current_schema)
            write_json_artifact(run_dir / "alignment_summary.json", final_summary)
            return {
                "schema": current_schema,
                "summary": final_summary,
                "rounds": rounds + [scoring_table],
            }

        low_fields = scoring_table["low_fields"]
        if round_index >= max_rounds:
            failure_summary = {
                "status": "failed",
                "reason": "Schema alignment aggregate did not reach threshold within max rounds.",
                "round": round_index,
                "topk_aggregate": aggregate,
                "threshold": threshold,
                "low_fields": low_fields,
            }
            write_json_artifact(run_dir / "final_failure_report.json", failure_summary)
            raise ValueError(
                "Schema alignment failed after "
                f"{max_rounds} rounds. Final aggregate={aggregate:.3f}; "
                f"low_fields={', '.join(low_fields)}. See {run_dir / 'final_failure_report.json'}"
            )

        reference = _select_reference_candidate(scoring_table, topk, low_fields)
        optimized = optimize_schema_from_reference(
            llm=llm,
            current_schema=current_schema,
            reference_schema=reference["schema"],
            low_fields=low_fields,
            scoring_table=scoring_table,
        )
        current_schema = optimized["schema"]
        write_json_artifact(run_dir / f"optimized_schema_round_{round_index}.json", current_schema)
        write_json_artifact(run_dir / f"changed_fields_round_{round_index}.json", optimized["changed_fields"])
        rounds.append(
            {
                **scoring_table,
                "optimization_reference_record_id": reference["record"]["id"],
                "changed_fields": optimized["changed_fields"],
            }
        )
        _emit_progress(
            progress_callback,
            "schema_alignment",
            f"Schema optimized for low fields: {', '.join(low_fields)}",
            low_fields=low_fields,
            round_index=round_index,
        )

    raise ValueError("Schema alignment failed unexpectedly.")


def recall_top_k(schema: dict[str, Any], top_k: int = 3) -> list[dict[str, Any]]:
    records = _load_completed_knowledge_schemas()
    if len(records) < top_k:
        raise ValueError(
            f"Knowledge Base needs at least {top_k} completed records for TopK recall; found {len(records)}."
        )

    source_profile = _build_recall_profile(schema)
    ranked: list[dict[str, Any]] = []
    for item in records:
        candidate_profile = _build_recall_profile(item["schema"])
        field_scores = {
            key: _text_similarity(source_profile.get(key, ""), candidate_profile.get(key, ""))
            for key in source_profile
        }
        recall_score = sum(field_scores.values()) / max(len(field_scores), 1)
        ranked.append(
            {
                "record": item["record"],
                "schema": item["schema"],
                "recall_score": round(recall_score, 6),
                "recall_field_scores": field_scores,
                "recall_profile": candidate_profile,
            }
        )

    ranked.sort(key=lambda item: item["recall_score"], reverse=True)
    return ranked[:top_k]


def score_topk_candidates(
    llm,
    source_schema: dict[str, Any],
    topk: list[dict[str, Any]],
    round_index: int,
    threshold: float,
) -> dict[str, Any]:
    candidate_scores: list[dict[str, Any]] = []
    for rank, candidate in enumerate(topk, start=1):
        comparison_fields = {
            "source": _build_weight_field_payload(source_schema),
            "candidate": _build_weight_field_payload(candidate["schema"]),
        }
        raw_response = score_schema_alignment_with_prompt(
            llm=llm,
            source_schema_json=json.dumps(source_schema, ensure_ascii=False, indent=2),
            candidate_schema_json=json.dumps(candidate["schema"], ensure_ascii=False, indent=2),
            comparison_fields_json=json.dumps(comparison_fields, ensure_ascii=False, indent=2),
            field_weights_json=json.dumps(FIELD_WEIGHTS, ensure_ascii=False, indent=2),
        )
        parsed = _parse_json_response(raw_response, f"Schema alignment scoring rank {rank}")
        normalized = _normalize_score_response(parsed)
        score = sum(FIELD_WEIGHTS[field] * normalized["fields"][field]["numeric"] for field in FIELD_WEIGHTS)
        candidate_scores.append(
            {
                "rank": rank,
                "record_id": candidate["record"].get("id"),
                "original_filename": candidate["record"].get("original_filename"),
                "recall_score": candidate["recall_score"],
                "score": round(score, 6),
                "fields": normalized["fields"],
            }
        )

    topk_aggregate = sum(
        TOPK_COEFFICIENTS[index] * candidate_scores[index]["score"]
        for index in range(min(len(candidate_scores), len(TOPK_COEFFICIENTS)))
    )
    field_aggregates = _build_field_aggregates(candidate_scores)
    low_fields = [field for field, value in field_aggregates.items() if value < 0.5]
    if not low_fields:
        low_fields = [min(field_aggregates, key=field_aggregates.get)]

    return {
        "round": round_index,
        "threshold": threshold,
        "topk_aggregate": round(topk_aggregate, 6),
        "passed": topk_aggregate >= threshold,
        "candidate_scores": candidate_scores,
        "field_aggregates": field_aggregates,
        "low_fields": low_fields,
        "field_weights": FIELD_WEIGHTS,
        "grade_values": GRADE_VALUES,
        "aggregate_formula": "0.5 * score_1 + 0.35 * score_2 + 0.15 * score_3",
    }


def optimize_schema_from_reference(
    llm,
    current_schema: dict[str, Any],
    reference_schema: dict[str, Any],
    low_fields: list[str],
    scoring_table: dict[str, Any],
) -> dict[str, Any]:
    raw_response = optimize_schema_with_prompt(
        llm=llm,
        current_schema_json=json.dumps(current_schema, ensure_ascii=False, indent=2),
        reference_schema_json=json.dumps(reference_schema, ensure_ascii=False, indent=2),
        low_fields_json=json.dumps(low_fields, ensure_ascii=False, indent=2),
        scoring_table_json=json.dumps(scoring_table, ensure_ascii=False, indent=2),
        field_weights_json=json.dumps(FIELD_WEIGHTS, ensure_ascii=False, indent=2),
    )
    parsed = _parse_json_response(raw_response, "Schema optimization")
    if isinstance(parsed, dict) and isinstance(parsed.get("schema"), dict):
        optimized_schema = normalize_story_schema(parsed["schema"])
        changed_fields = parsed.get("changed_fields")
    else:
        optimized_schema = normalize_story_schema(parsed)
        changed_fields = []

    if not isinstance(changed_fields, list):
        changed_fields = []

    return {
        "schema": optimized_schema,
        "changed_fields": changed_fields,
    }


def write_json_artifact(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _normalize_score_response(data: Any) -> dict[str, Any]:
    raw_fields = data.get("fields") if isinstance(data, dict) else {}
    if not isinstance(raw_fields, dict):
        raw_fields = {}

    fields: dict[str, dict[str, Any]] = {}
    for field in FIELD_WEIGHTS:
        raw_value = raw_fields.get(field, {})
        if isinstance(raw_value, dict):
            grade = _normalize_grade(raw_value.get("grade"))
            reason = _coerce_text(raw_value.get("reason"))
        else:
            grade = _normalize_grade(raw_value)
            reason = ""
        fields[field] = {
            "grade": grade,
            "numeric": GRADE_VALUES[grade],
            "reason": reason,
            "weight": FIELD_WEIGHTS[field],
            "weighted_score": round(FIELD_WEIGHTS[field] * GRADE_VALUES[grade], 6),
        }
    return {"fields": fields}


def _build_field_aggregates(candidate_scores: list[dict[str, Any]]) -> dict[str, float]:
    aggregates: dict[str, float] = {}
    for field in FIELD_WEIGHTS:
        total = 0.0
        for index, candidate in enumerate(candidate_scores[: len(TOPK_COEFFICIENTS)]):
            total += TOPK_COEFFICIENTS[index] * candidate["fields"][field]["numeric"]
        aggregates[field] = round(total, 6)
    return aggregates


def _select_reference_candidate(
    scoring_table: dict[str, Any],
    topk: list[dict[str, Any]],
    low_fields: list[str],
) -> dict[str, Any]:
    candidate_scores = scoring_table["candidate_scores"]
    best_rank = 1
    best_value = -1.0
    for candidate in candidate_scores:
        if len(low_fields) == 1:
            value = candidate["fields"][low_fields[0]]["numeric"]
        else:
            value = sum(candidate["fields"][field]["numeric"] for field in low_fields) / max(len(low_fields), 1)
        if value > best_value:
            best_value = value
            best_rank = int(candidate["rank"])
    return topk[best_rank - 1]


def _load_completed_knowledge_schemas() -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for record in list_knowledge_records():
        if str(record.get("status") or "").lower() != "completed":
            continue
        if not record.get("structured_path"):
            continue
        try:
            item = get_knowledge_item(str(record["id"]))
        except Exception:
            continue
        items.append({"record": item["record"], "schema": normalize_story_schema(item.get("features", {}))})
    return items


def _strip_candidate_schemas(topk: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "rank": index,
            "record": item["record"],
            "recall_score": item["recall_score"],
            "recall_field_scores": item["recall_field_scores"],
            "recall_profile": item["recall_profile"],
        }
        for index, item in enumerate(topk, start=1)
    ]


def _build_recall_profile(schema: dict[str, Any]) -> dict[str, str]:
    normalized = normalize_story_schema(schema)
    core = normalized["story_core"]
    plot = normalized["plot_structure"]
    localization = normalized["localization_features"]
    summary = normalized["source_summary"]
    background = normalized["background"]
    return {
        "核心冲突": _display_value(core.get("core_conflict")),
        "角色模式": _join_values(
            [
                core.get("protagonist"),
                core.get("antagonist"),
                normalized.get("characters"),
            ]
        ),
        "关系张力点": _display_value(core.get("relationship_tensions")),
        "反转点类型": _display_value(plot.get("reversal_points")),
        "钩子点类型": _display_value(plot.get("hook_points")),
        "文化绑定负担强度": _display_value(localization.get("cultural_binding_elements")),
        "题材标签": _join_values([summary.get("genre"), summary.get("theme"), summary.get("tone")]),
        "时代": _display_value(background.get("era")),
        "世界观类型": _join_values([background.get("world_rules"), background.get("cultural_context")]),
    }


def _build_weight_field_payload(schema: dict[str, Any]) -> dict[str, Any]:
    normalized = normalize_story_schema(schema)
    return {
        "核心冲突": normalized["story_core"].get("core_conflict"),
        "主角目标": normalized["story_core"].get("protagonist_objective"),
        "主角痛点": normalized["story_core"].get("protagonist_pain_point"),
        "关系张力点": normalized["story_core"].get("relationship_tensions"),
        "主要情节点": normalized["plot_structure"].get("major_plot_points"),
        "反转点": normalized["plot_structure"].get("reversal_points"),
        "情感曲线": normalized["plot_structure"].get("emotional_curve"),
        "钩子点": normalized["plot_structure"].get("hook_points"),
        "文化绑定元素": normalized["localization_features"].get("cultural_binding_elements"),
        "高风险本地化项": normalized["localization_features"].get("high_risk_localization_items"),
    }


def _require_meaningful(value: Any, field: str, business_field: str, missing: list[dict[str, str]]) -> None:
    if _has_meaningful_value(value):
        return
    missing.append(
        {
            "field": field,
            "business_field": business_field,
            "reason": f"{field} is empty or does not contain meaningful extracted content.",
        }
    )


def _has_meaningful_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (int, float, bool)):
        return True
    if isinstance(value, list):
        return any(_has_meaningful_value(item) for item in value)
    if isinstance(value, dict):
        return any(
            _has_meaningful_value(item)
            for key, item in value.items()
            if key not in {"evidence", "confidence", "order", "replaceable"}
        )
    return bool(value)


def _text_similarity(left: str, right: str) -> float:
    left_tokens = _tokenize(left)
    right_tokens = _tokenize(right)
    if not left_tokens or not right_tokens:
        return 0.0
    overlap = len(left_tokens & right_tokens)
    union = len(left_tokens | right_tokens)
    return round(overlap / union, 6) if union else 0.0


def _tokenize(text: str) -> set[str]:
    normalized = str(text or "").lower()
    tokens = set(re.findall(r"[a-z0-9_]+", normalized))
    tokens.update(re.findall(r"[\u4e00-\u9fff]", normalized))
    return {token for token in tokens if token.strip()}


def _display_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, list):
        return " ".join(_display_value(item) for item in value if _display_value(item))
    if isinstance(value, dict):
        return " ".join(
            _display_value(item)
            for key, item in value.items()
            if key not in {"evidence", "confidence", "order"} and _display_value(item)
        )
    return str(value)


def _join_values(values: list[Any]) -> str:
    return " ".join(_display_value(value) for value in values if _display_value(value))


def _parse_json_response(raw_response: str, source_name: str) -> Any:
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


def _normalize_grade(value: Any) -> str:
    text = _coerce_text(value)
    if text in GRADE_VALUES:
        return text
    lowered = text.lower()
    if lowered in {"high", "h", "高等", "高相似"}:
        return "高"
    if lowered in {"medium", "mid", "m", "中等", "中相似"}:
        return "中"
    return "低"


def _coerce_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float, bool)):
        return str(value)
    return json.dumps(value, ensure_ascii=False)


def _read_positive_int(name: str, default: int) -> int:
    raw_value = os.getenv(name, str(default))
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if value <= 0:
        raise ValueError(f"{name} must be positive")
    return value


def _read_float(name: str, default: float) -> float:
    raw_value = os.getenv(name, str(default))
    try:
        value = float(raw_value)
    except ValueError as exc:
        raise ValueError(f"{name} must be a number") from exc
    if value <= 0:
        raise ValueError(f"{name} must be positive")
    return value


def _emit_progress(
    progress_callback: ProgressCallback | None,
    stage: str,
    message: str,
    **extra: Any,
) -> None:
    if progress_callback is None:
        return
    try:
        progress_callback(stage, {"stage": stage, "message": message, **extra})
    except Exception:
        return
