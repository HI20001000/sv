# Storyboard Generation Prompt v1

## Purpose

基于 `story_bible.json` 与单集 `episode_000x.json`，生成该集分镜结构。  
只输出结构化分镜 JSON，不输出解释文字。

---

## Rules

1. 输入仅使用：
- `story_bible_json`
- `episode_json`

2. 场景与对白来源：
- 以 `episode_json.generated_content.script` 为主文本
- 参考 `episode_json.episode_plan` 的主线目标与核心节点

3. 分镜结构要求：
- 先拆 `scenes[]`，每个 scene 下包含 `shots[]`
- 每个 shot 仅包含以下字段：
  - `shot_no`
  - `scene_no`
  - `purpose`
  - `visual`
  - `characters`
  - `dialogue`
  - `duration`

4. 角色一致性要求：
- `characters` 中的人名必须来自 `story_bible_json.characters.name` 或 aliases
- 不要使用未在 story_bible 出现的新角色名

5. 道具抽取与绑定（重点）：
- 先从 `story_bible_json.props` 抽取 `allowed_props`（只允许使用这些道具名）
- 再从 `episode_json.episode_plan.props_used` 抽取 `required_props`
- 分镜必须优先覆盖 `required_props`
- 当镜头中出现道具时，必须在 `visual` 中用 `道具:道具名` 显式标注
- `道具名` 必须与 `allowed_props` 完全一致（不要同义替换、不要改写）
- 禁止虚构新道具；禁止使用不在 `allowed_props` 中的道具

6. 对白覆盖要求：
- `dialogue` 尽量复用原句，不要改写关键信息
- 目标是让剧本对白可被分镜完整覆盖

7. 生成策略要求：
- 每个 scene 至少 1 个 shot
- 尽量让每个 shot 的 `purpose` 清晰（推进冲突/交代信息/情绪转折）
- `duration` 使用秒数（可为小数），保证节奏紧凑

8. 输出约束：
- 只输出合法 JSON
- 不输出 markdown
- 不输出额外文本

---

## Input

`story_bible_json`:

```json
{{STORY_BIBLE_JSON}}
```

`episode_json`:

```json
{{EPISODE_JSON}}
```

---

## Output Schema

```json
{
  "episode_no": 1,
  "title": "",
  "scenes": [
    {
      "scene_no": 1,
      "shots": [
        {
          "shot_no": 1,
          "scene_no": 1,
          "purpose": "",
          "visual": "道具:婚礼请柬；特写顾盼手中请柬，情绪克制但锋利。",
          "characters": [
            "顾盼"
          ],
          "dialogue": "顾盼：意义非凡？不过是想让我去当那个背景板罢了。",
          "duration": 3.0
        }
      ]
    }
  ]
}
```
