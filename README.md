# 短剧生成终端工具（LangChain）

本项目是一个终端交互式短剧生成工具，核心能力包含两部分：

1. 通用多轮聊天（流式输出）
2. 基于文档的一键短剧生产流程（`/docs` 命令）

`/docs` 会从 `input_documents/` 读取 `.txt` 或 `.docx`，自动完成：
剧本清洗 -> 特征提取 -> Unit 拆分 -> Unit 框架提炼 -> 拆集计划 -> 逐集规划 -> 逐集剧本 -> 逐集分镜。

---

## 环境要求

- Python 3.10+
- Node.js 18+
- 可用的 OpenAI-compatible 接口（项目通过 `langchain-openai` 调用）

---

## 安装依赖

```powershell
pip install -r requirements.txt
```

前端依赖安装：

```powershell
cd web
npm install
```

---

## 配置 `.env`

### 必填项

```env
LLM_BASE_URL=https://your-openai-compatible-endpoint/v1
LLM_MODEL=your-model-name
LLM_API_KEY=your-api-key
```

### 可选项（不填走默认值）

```env
CLEANING_CHUNK_SIZE=4000
FEATURE_CHUNK_SIZE=4000
UNIT_WINDOW_MIN=1500
UNIT_WINDOW_MAX=2200
DEFAULT_EPISODE_COUNT=60
EPISODE_SPLIT_REPAIR_ROUNDS=2
EPISODE_CONTENT_MAX_WORKERS=4
STORYBOARD_MAX_WORKERS=4
```

说明：

- `UNIT_WINDOW_MIN` 必须小于 `UNIT_WINDOW_MAX`
- `DEFAULT_EPISODE_COUNT` 为 `/docs` 默认目标集数
- `EPISODE_SPLIT_REPAIR_ROUNDS` 是拆集计划修复轮次
- `EPISODE_CONTENT_MAX_WORKERS` 控制第 7 步逐集内容生成的并发数
- `STORYBOARD_MAX_WORKERS` 控制第 8 步逐集分镜生成的并发数

---

## 启动

### 1) 启动 Web API

在项目根目录执行：

```powershell
uvicorn web_api:app --reload --host 127.0.0.1 --port 8000
```

启动后可访问：

- API 基础地址：`http://127.0.0.1:8000`
- Swagger 文档：`http://127.0.0.1:8000/api/docs`

### 2) 启动前端开发环境

在 `web/` 目录执行：

```powershell
cd web
npm run dev
```

默认访问地址通常为：

- `http://127.0.0.1:5173`

说明：

- 前端开发服务器会将 `/api` 请求代理到 `http://127.0.0.1:8000`
- 使用前端界面时，请先启动 Web API，再启动前端

### 3) 启动终端 CLI

```powershell
python chat_cli.py
```

启动后可直接聊天，也可执行 `/docs` 进入文档生产流程。

---

## 使用流程（推荐）

1. 将源文档放入 `input_documents/`（支持 `.txt`、`.docx`）
2. 运行 `python chat_cli.py`
3. 输入 `/docs`
4. 按编号选择文件
5. 等待 8 阶段处理完成
6. 在 `output/<源文件名_时间戳>/` 查看全部产物

---

## 终端命令

- `/help` 查看帮助
- `/clear` 清屏（不清空上下文记忆）
- `/history` 查看当前上下文消息数量
- `/model` 查看当前模型和 `base_url`
- `/ping` 发送最小请求测试模型连通性
- `/docs` 执行短剧生产流程
- `/exit` 退出

---

## 输出目录说明

每次 `/docs` 执行都会创建一个新的项目目录：

```text
output/
  <source_name>_<YYYYMMDD_HHMMSS>/
    source/
    script_cleaned.txt
    story_bible.json
    story_units.json
    unit_frameworks.json
    episode_split_plan.json
    episode_generation_plan.json
    episodes/
    storyboards/
    episodes_overview.json
    project_meta.json
```

同时会在根目录同步覆盖：

- `episode_split_plan.json`
- `episode_generation_plan.json`

---

## Prompt 文件说明

`prompt/` 目录下每个模板都对应 `/docs` 流程中的固定阶段，调用入口在 `code_components/script_processing.py`（底层由 `code_components/langChain/model_runtime.py` 读模板并注入变量）。

| Prompt 文件 | 对应流程阶段 | 在流程中做什么 | 主要用意 |
|---|---|---|---|
| `prompt/script_cleaning_prompt.md` | 1. 剧本清洗 | 清洗原始文本，输出 `script_cleaned.txt` | 去噪、规范格式、保留原剧情表达，为后续结构化处理提供稳定输入 |
| `prompt/script_feature_extraction_prompt.md` | 2. 特征提取 | 从清洗文本抽取结构化特征，输出 `story_bible.json` | 提取角色、道具、背景等核心信息，作为后续规划与生成的基础 |
| `prompt/unit_split_prompt.md` | 3. Unit 拆分 | 读取拆分规则与参数，输出 `story_units.json` | 控制 unit 切分窗口、句子边界与尾段合并策略，使该阶段也可通过 prompt 调整 |
| `prompt/unit_framework_extraction_prompt.md` | 4. Unit 框架提炼 | 对每个 unit 提炼摘要与冲突信息，输出 `unit_frameworks.json` | 把长文本 unit 转成可用于拆集决策的“剧情框架” |
| `prompt/unit_episode_split_planning_prompt.md` | 5. 拆集规划 | 按 unit 分配 `episode_count`，输出 `episode_split_plan.json` | 在满足总集数约束下完成 unit->集数分配，并保证可校验 |
| `prompt/episode_generation_planning_prompt.md` | 6. 逐集生成规划 | 产出每集的标题、目标、beats、角色焦点等，输出 `episode_generation_plan.json` | 把“拆集结果”变成“逐集可执行的生成蓝图” |
| `prompt/episode_content_generation_prompt.md` | 7. 逐集内容生成 | 基于 story bible + 单集规划 + source units 生成单集剧本内容 | 生成可直接使用的单集脚本文本（非分镜） |
| `prompt/storyboard_generation_prompt.md` | 8. 逐集分镜生成 | 基于单集剧本与 story bible 生成分镜 JSON | 将剧本进一步结构化为场景/镜头级输出，便于后续制作 |

补充说明：

- 第 3 步 `Unit 拆分` 是程序规则拆分（非 prompt 驱动）。
- 第 5 步有强校验（总集数必须严格等于目标值），必要时会触发自动修复轮次（`EPISODE_SPLIT_REPAIR_ROUNDS`）。

---

## 常见问题

### 1) 启动时报环境变量缺失

检查 `.env` 是否包含 `LLM_BASE_URL`、`LLM_MODEL`、`LLM_API_KEY`。

### 2) `/ping` 或聊天报调用失败

- 检查 `LLM_BASE_URL` 是否正确（通常包含 `/v1`）
- 检查 `LLM_API_KEY` 是否有效
- 检查 `LLM_MODEL` 是否为服务端可用模型

### 3) `/docs` 看不到可选文件

确认 `input_documents/` 下存在 `.txt` 或 `.docx` 文件。

### 4) 拆集或逐集生成效果不稳定

先尝试：

- 调大模型能力
- 调整 `DEFAULT_EPISODE_COUNT`
- 调整 `UNIT_WINDOW_MIN/MAX`
- 检查 `prompt/` 下模板是否符合当前业务目标

---

## 安全提示

`.env` 中包含 API Key，建议：

- 不要提交到公开仓库
- 生产环境使用安全密钥管理方式
