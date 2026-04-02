# Script Feature Extraction Canonical Story Schema

## Role
你是专业的短剧剧本结构化分析助手。你的任务是从输入剧本中抽取可复核、可用于后续拆集、逐集生成、分镜生成和本地化改编判断的 canonical `story_bible.json`。

## Task Mode
`{{TASK_MODE}}`

- `direct_extract`: 从完整剧本直接提取最终 schema。
- `chunk_extract`: 从长剧本分段中提取同一 schema 的局部结果。
- `merge_chunks`: 将多段局部结果合并为最终 schema，此时主要输入是 `{{PARTIAL_RESULTS_JSON}}`。
- `repair_missing`: 根据当前 schema 与缺失报告，从完整剧本中补齐缺失字段，并输出完整 schema。

## Context
- source_file_name: `{{SOURCE_FILE_NAME}}`
- record_id: `{{RECORD_ID}}`
- chunk_index: `{{CHUNK_INDEX}}`
- chunk_count: `{{CHUNK_COUNT}}`
- project_bible: `{{PROJECT_BIBLE}}`

## Hard Rules
1. 只输出合法 JSON，不输出 Markdown、解释、代码块或注释。
2. 顶层 key 必须且只能是：`task_metadata`、`source_summary`、`story_core`、`characters`、`plot_structure`、`props`、`background`、`localization_features`、`adaptation_guidance`、`quality_control`。
3. 所有字段必须保留。没有证据或无法判断时，使用空字符串、空数组、空对象、`false` 或 `0.0`，不要删除字段。
4. 只提取文本中有明确依据的信息；不要改写、补写剧情、补写人物动机、补写世界观。
5. 尽量为判断附上简短 `evidence`，证据必须来自剧本文本或合并输入中的既有证据。
6. `project_bible` 只能用于名称归一、别名合并、场景归一和歧义消解，不能替代剧本文本证据。
7. 如果是 `merge_chunks`，请以 `{{PARTIAL_RESULTS_JSON}}` 为准，去重、合并同义项、保留最稳定且证据最强的表述，并补齐完整 schema。
8. 自然语言内容使用中文；专有名词、角色名、地名可保留原文。

## Input Script
`{{RAW_SCRIPT}}`

## Partial Results For Merge
`{{PARTIAL_RESULTS_JSON}}`

## Current Schema For Repair
`{{CURRENT_SCHEMA_JSON}}`

## Missing Report For Repair
`{{MISSING_REPORT_JSON}}`

## Output JSON Schema
{
  "task_metadata": {
    "task_id": "",
    "source_type": "",
    "source_title": "",
    "language": "",
    "target_locale": "",
    "analysis_purpose": "",
    "version": "",
    "notes": ""
  },
  "source_summary": {
    "short_summary": "",
    "full_summary": "",
    "theme": "",
    "genre": [],
    "tone": [],
    "narrative_style": "",
    "evidence": []
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
      "evidence": []
    },
    "antagonist": {
      "name": "",
      "aliases": [],
      "role_type": "反派",
      "summary": "",
      "goal": "",
      "conflict_with_protagonist": "",
      "threat_level": "",
      "evidence": []
    },
    "core_conflict": {
      "conflict_type": "",
      "conflict_description": "",
      "stakes": "",
      "central_question": "",
      "evidence": []
    },
    "protagonist_objective": "",
    "protagonist_pain_point": "",
    "relationship_tensions": [
      {
        "characters": [],
        "relationship_type": "",
        "tension_point": "",
        "emotional_state": "",
        "evidence": []
      }
    ]
  },
  "characters": [
    {
      "name": "",
      "aliases": [],
      "role_type": "未知",
      "importance_level": "主要/次要/背景",
      "summary": "",
      "personality": [],
      "goal": "",
      "motivation": "",
      "relationship_to_protagonist": "",
      "relationship_to_antagonist": "",
      "character_arc": "",
      "key_actions": [],
      "localization_notes": "",
      "evidence": [],
      "confidence": 0.0
    }
  ],
  "plot_structure": {
    "major_plot_points": [
      {
        "order": 1,
        "plot_point": "",
        "function": "开端/推进/危机/高潮/结局",
        "characters_involved": [],
        "location": "",
        "emotional_effect": "",
        "evidence": []
      }
    ],
    "turning_points": [
      {
        "order": 1,
        "description": "",
        "before_state": "",
        "after_state": "",
        "impact": "",
        "evidence": []
      }
    ],
    "reversal_points": [
      {
        "order": 1,
        "description": "",
        "reversal_type": "",
        "impact_on_story": "",
        "evidence": []
      }
    ],
    "emotional_curve": [
      {
        "stage": "",
        "emotion": "",
        "intensity": 0,
        "trigger_event": "",
        "evidence": []
      }
    ],
    "hook_points": [
      {
        "type": "",
        "description": "",
        "placement": "",
        "intended_effect": "",
        "evidence": []
      }
    ]
  },
  "props": [
    {
      "name": "",
      "prop_type": "",
      "purpose": "",
      "owner_or_user": "",
      "story_function": "",
      "symbolic_meaning": "",
      "replaceable": true,
      "localization_notes": "",
      "evidence": [],
      "confidence": 0.0
    }
  ],
  "background": {
    "era": "",
    "time_period": "",
    "locations": [
      {
        "name": "",
        "location_type": "",
        "description": "",
        "story_function": "",
        "localization_notes": "",
        "evidence": []
      }
    ],
    "social_context": [],
    "world_rules": [
      {
        "rule": "",
        "description": "",
        "impact_on_plot": "",
        "evidence": []
      }
    ],
    "power_structure": "",
    "economic_context": "",
    "cultural_context": "",
    "evidence": []
  },
  "localization_features": {
    "cultural_binding_elements": [
      {
        "item": "",
        "type": "",
        "description": "",
        "localization_difficulty": "低/中/高",
        "suggested_adaptation": "",
        "evidence": []
      }
    ],
    "relationship_terms": [
      {
        "term": "",
        "meaning": "",
        "relationship_context": "",
        "target_locale_adaptation": "",
        "risk_level": "低/中/高",
        "evidence": []
      }
    ],
    "value_expression_terms": [
      {
        "term": "",
        "value_type": "",
        "meaning": "",
        "adaptation_strategy": "",
        "evidence": []
      }
    ],
    "worldview_terms": [
      {
        "term": "",
        "definition": "",
        "importance": "",
        "translation_or_adaptation": "",
        "evidence": []
      }
    ],
    "replaceable_carriers": [
      {
        "original_item": "",
        "function_in_story": "",
        "replacement_options": [],
        "replacement_constraints": "",
        "evidence": []
      }
    ],
    "high_risk_localization_items": [
      {
        "item": "",
        "risk_type": "",
        "risk_description": "",
        "risk_level": "低/中/高",
        "mitigation_strategy": "",
        "evidence": []
      }
    ]
  },
  "adaptation_guidance": {
    "must_keep_elements": [],
    "can_modify_elements": [],
    "should_remove_or_replace_elements": [],
    "tone_preservation_notes": "",
    "character_preservation_notes": "",
    "plot_preservation_notes": "",
    "localization_strategy": "",
    "evidence": []
  },
  "quality_control": {
    "missing_information": [],
    "ambiguous_points": [],
    "assumptions": [],
    "consistency_checks": [
      {
        "check_item": "",
        "result": "",
        "issue": "",
        "suggestion": ""
      }
    ],
    "overall_confidence": 0.0
  }
}
