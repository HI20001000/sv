# 短剧生成工作流程说明

本文档按当前代码实现梳理 `/docs` 的端到端流程，入口函数为：

- `chat_cli.py -> run_terminal_chat() -> /docs -> process_script_to_output()`

---

## 0. 输入与入口

### 输入来源

- 目录：`input_documents/`
- 支持格式：`.txt`、`.docx`
- 文本读取：`code_components/document_browser.py`

### 触发方式

1. 启动 `python chat_cli.py`
2. 在终端输入 `/docs`
3. 选择文件编号

---

## 1. 流程总览（8 阶段）

`process_script_to_output()` 固定执行如下 8 步：

1. 剧本清洗（cleaning）
2. 特征提取（feature extraction）
3. Unit 拆分（unit split）
4. Unit 框架提炼（unit framework）
5. 拆集规划（episode split plan）
6. 逐集生成规划（episode generation plan）
7. 逐集内容生成（episode content）
8. 逐集分镜生成（storyboard）

---

## 2. 各阶段输入输出与规则

### 2.1 剧本清洗

- Prompt：`prompt/script_cleaning_prompt_v1.md`
- 输入：原始文档文本
- 输出：`script_cleaned.txt`
- 关键参数：`CLEANING_CHUNK_SIZE`（默认 4000）
- 兜底策略：
  - LLM 清洗为空时，尝试分块清洗
  - 分块仍失败，走本地清洗 fallback

### 2.2 特征提取（story bible）

- Prompt：`prompt/script_feature_extraction_prompt_v1.md`
- 输入：清洗后文本
- 输出：`story_bible.json`
- 关键参数：`FEATURE_CHUNK_SIZE`（默认 4000）
- 结构核心：
  - `characters`
  - `props`
  - `background`
- 内置去重、归一化与容错解析

### 2.3 Unit 拆分

- 输入：清洗后文本
- 输出：`story_units.json`
- 关键参数：
  - `UNIT_WINDOW_MIN`（默认 1500）
  - `UNIT_WINDOW_MAX`（默认 2200）
- 结果字段示例：
  - `unit_id`
  - `char_count`
  - `source_span`
  - `text`

### 2.4 Unit 框架提炼

- Prompt：`prompt/unit_framework_extraction_prompt_v1.md`
- 输入：每个 unit 的 `unit_id + text`
- 输出：`unit_frameworks.json`
- 目标字段：
  - `summary`
  - `key_events`
  - `core_conflict`
  - `hook`
  - `ending_state`
- 兜底：任一 unit 提炼失败时会按文本自动生成简化框架，流程不中断

### 2.5 拆集规划

- Prompt：`prompt/unit_episode_split_planning_prompt_v1.md`
- 输入：`unit_frameworks` + 目标集数
- 输出：
  - 项目内：`output/.../episode_split_plan.json`
  - 根目录镜像：`episode_split_plan.json`
- 关键参数：
  - `DEFAULT_EPISODE_COUNT`（默认 60）
  - `EPISODE_SPLIT_REPAIR_ROUNDS`（默认 2）
- 强校验：
  - 所有 `unit_id` 必须覆盖且不重复
  - `episode_count` 必须为非负整数
  - 总和必须严格等于目标集数
- 不通过时会触发修复回合，仍失败则抛错终止

### 2.6 逐集生成规划

- Prompt：`prompt/episode_generation_planning_prompt_v1.md`
- 输入：
  - `story_bible`
  - `story_units`
  - `unit_frameworks`
  - `episode_split_plan`
- 输出：
  - 项目内：`output/.../episode_generation_plan.json`
  - 根目录镜像：`episode_generation_plan.json`
- 结果包含：
  - 每集标题、来源 unit、主线目标、关键 beat、人物焦点、衔接要求
  - `generation_input_contract`（后续生成的绑定约束）

### 2.7 逐集内容生成

- Prompt：`prompt/episode_content_generation_prompt_v1.md`
- 输入（按集）：
  - `story_bible`
  - 单集 `episode_plan`
  - 对应 `source_units`
- 输出目录：
  - `episodes/episode_0001.json ...`
  - `episodes/index.json`
  - `episodes_plan/episode_plan_0001.json ...`
  - `episodes_plan/index.json`
  - `episodes_overview.json`
- 兜底：LLM 失败时使用 `episode_plan + source_units` 拼装 fallback 剧本

### 2.8 逐集分镜生成

- Prompt：`prompt/storyboard_generation_prompt_v1.md`
- 输入（按集）：
  - `story_bible`
  - `episodes/episode_000x.json`
- 输出：
  - `storyboards/episode_0001_storyboard.json ...`
  - `storyboards/index.json`
- 附加校验：
  - 对白覆盖率
  - 未知角色/道具检测
- 兜底：LLM 失败时从剧本文本生成基础分镜结构

---

## 3. 产物目录结构

每次执行会创建独立项目目录：

```text
output/<slug>_<timestamp>/
  source/<原始文件>
  script_cleaned.txt
  story_bible.json
  story_units.json
  unit_frameworks.json
  episode_split_plan.json
  episode_generation_plan.json
  episodes/
    episode_0001.json
    ...
    index.json
  episodes_plan/
    episode_plan_0001.json
    ...
    index.json
  storyboards/
    episode_0001_storyboard.json
    ...
    index.json
  episodes_overview.json
  project_meta.json
```

---

## 4. 运行元信息与可追踪性

`project_meta.json` 会记录：

- 输入文件、字数、清洗策略
- 各阶段 prompt 文件路径
- 单步耗时与总耗时
- Unit 数、目标集数、计划集数、实际生成数
- 关键输出文件名与目录

可用于回溯单次任务配置和性能。

---

## 5. 失败处理策略总结

当前实现优先保证“流程可继续”：

- 清洗失败：分块 + 本地清洗
- 特征提取异常：分段容错并归一化
- Unit 框架失败：unit 级 fallback
- 拆集无效：自动修复若干轮
- 单集剧本/分镜失败：逐集 fallback，不影响其他集

只有关键约束无法满足（例如拆集计划长期不合法）时才终止流程。
