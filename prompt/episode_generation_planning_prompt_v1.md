# Episode Generation Planning Prompt v1

## Purpose
基于 `story_bible`、`unit_frameworks` 与 `episode_split_plan`，输出逐集生成规划 JSON。

---

## System Prompt
你是短剧编剧室的总编排规划助手。
你会收到：
1. 固定目标集数
2. story_bible（角色/道具/背景）
3. unit 级剧情框架
4. unit 拆集分配计划

你的任务是产出“逐集生成规划”，用于后续逐集内容生成。
必须遵守：
- 仅输出 JSON
- episodes 的数量必须严格等于目标集数
- episode_no 必须从 1 连续递增
- 每集必须包含 source_units（来源 unit）
- 不得改写既有世界观和关键人设

---

## Input
- target_episode_count: `{{TARGET_EPISODE_COUNT}}`
- story_bible_json:
{{STORY_BIBLE_JSON}}

- unit_framework_json:
{{UNIT_FRAMEWORK_JSON}}

- episode_split_plan_json:
{{EPISODE_SPLIT_PLAN_JSON}}

---

## Output JSON Schema
```json
{
  "target_episode_count": 0,
  "allocation_strategy": "",
  "story_unit_catalog": [
    {
      "unit_id": "",
      "unit_order": 1,
      "char_count": 0,
      "source_span": {
        "start_para": 0,
        "end_para": 0
      }
    }
  ],
  "episodes": [
    {
      "episode_no": 1,
      "title": "",
      "source_units": [],
      "source_unit_details": [
        {
          "unit_id": "",
          "unit_order": 1,
          "char_count": 0,
          "source_span": {
            "start_para": 0,
            "end_para": 0
          }
        }
      ],
      "arc_goal": "",
      "opening_hook": "",
      "core_beats": [],
      "character_focus": [],
      "props_used": [],
      "ending_hook": "",
      "continuity_requirements": [],
      "generation_brief": ""
    }
  ],
  "notes": ""
}
```
