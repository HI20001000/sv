# 短劇生成工作流與資料流說明

本文檔基於目前代碼實現，梳理 `/docs` 命令的端到端處理流程，並將「執行工作流」與「資料流轉」放在同一套視角下說明。

它回答的是三個問題：

1. 使用者從哪裡進入這條流程
2. 程式每一步做了什麼
3. 一份原始文檔如何逐步演化為可追蹤的短劇產物

`/docs` 的實際入口鏈路如下：

- `chat_cli.py -> run_terminal_chat() -> /docs -> process_script_to_output()`

---

## 0. 入口與模組分工

### 0.1 使用者入口

1. 啟動 `python chat_cli.py`
2. 終端進入互動模式
3. 輸入 `/docs`
4. 從 `input_documents/` 選擇 `.txt` 或 `.docx` 文件
5. 進入固定的 8 階段短劇生產流程

### 0.2 核心模組責任

- `chat_cli.py`
  - 載入 `.env`
  - 校驗模型配置
  - 建立 LLM 與聊天工作流
  - 啟動終端互動
- `code_components/terminal_chat.py`
  - 處理聊天命令與 `/docs` 命令分流
  - 顯示進度、摘要與輸出位置
- `code_components/document_browser.py`
  - 列出輸入文件
  - 讀取 `.txt` / `.docx` 內容
- `code_components/langChain/model_runtime.py`
  - 建立 `ChatOpenAI`
  - 載入 prompt 模板
  - 將變量注入 prompt 並調用模型
- `code_components/script_processing.py`
  - 實現 `/docs` 主流程
  - 負責資料切分、LLM 調用、JSON 正規化、驗證、fallback 與落盤

---

## 1. 工作流與資料流總覽

目前的 `/docs` 管線不是一次性交給模型整體生成，而是：

- 先由程式控制流程與切分資料
- 再讓 LLM 只處理特定階段的生成任務
- 最後由程式再次做校驗、補洞、整理與輸出

也就是說，這是一條「LLM 生成 + 程式約束」的混合工作流。

### 1.1 端到端流程圖

```text
python chat_cli.py
  -> validate_env()
  -> make_llm()
  -> run_terminal_chat()
       -> /docs
       -> list_input_documents()
       -> load_document_content()
       -> process_script_to_output()
            1. script cleaning
            2. feature extraction
            3. unit split
            4. unit framework extraction
            5. episode split planning
            6. episode generation planning
            7. episode content generation
            8. storyboard generation
            -> write outputs + project_meta.json
```

### 1.2 資料流圖

```text
input_documents/<source>.txt|docx
  -> raw_script
  -> script_cleaned.txt
  -> story_bible.json
  -> story_units.json
  -> unit_frameworks.json
  -> episode_split_plan.json
  -> episode_generation_plan.json
  -> episodes/episode_0001.json ...
  -> storyboards/episode_0001_storyboard.json ...
  -> episodes_overview.json
  -> project_meta.json
```

### 1.3 這條流程的設計特徵

- 流程整體是固定順序執行，其中第 7、8 步採用有界並發
- 多數階段都允許局部失敗後 fallback，而不是立即中止
- 真正的硬性校驗主要集中在「拆集規劃」
- 每次執行都會產生獨立輸出目錄，便於回溯
- 根目錄會同步覆蓋 `episode_split_plan.json` 與 `episode_generation_plan.json` 作為鏡像快照

---

## 2. 階段化工作流與資料變化

`process_script_to_output()` 固定執行以下 8 步。

### 2.1 劇本清洗

- Prompt：`prompt/script_cleaning_prompt.md`
- 輸入：原始文檔文本 `raw_script`
- 輸出：`script_cleaned.txt`
- 關鍵參數：`CLEANING_CHUNK_SIZE`，默認 `4000`
- 工作內容：
  - 先用 LLM 對原文做清洗與格式規整
  - 若結果為空，改走分塊清洗
  - 若分塊仍失敗，走本地文本清理 fallback
- 資料變化：
  - 非結構化原文 -> 可供後續處理的標準化劇本文本

### 2.2 特徵提取（Story Bible）

- Prompt：`prompt/script_feature_extraction_prompt.md`
- 輸入：清洗後文本
- 輸出：`story_bible.json`
- 關鍵參數：`FEATURE_CHUNK_SIZE`，默認 `4000`
- 核心字段：
  - `characters`
  - `props`
  - `background`
- 工作內容：
  - 按段切分文本後逐段抽取角色、道具、背景等信息
  - 對各段結果做合併、去重與歸一化
- 資料變化：
  - 劇本文本 -> 全局故事知識庫

### 2.3 Unit 拆分

- Prompt：`prompt/unit_split_prompt.md`
- 輸入：清洗後文本
- 輸出：`story_units.json`
- 關鍵參數：
  - `UNIT_WINDOW_MIN`，默認 `1500`
  - `UNIT_WINDOW_MAX`，默認 `2200`
- 主要字段：
  - `unit_id`
  - `char_count`
  - `source_span`
  - `text`
- 工作內容：
  - 讀取 `unit_split_prompt.md` 內的拆分規則與配置
  - 按段落與句子進行規則切分
  - 控制每個 unit 的字數窗口與尾段合併策略
- 資料變化：
  - 長文本 -> 可分配、可規劃、可引用的故事單元

### 2.4 Unit 框架提煉

- Prompt：`prompt/unit_framework_extraction_prompt.md`
- 輸入：每個 unit 的 `unit_id + text`
- 輸出：`unit_frameworks.json`
- 目標字段：
  - `summary`
  - `key_events`
  - `core_conflict`
  - `hook`
  - `ending_state`
- 工作內容：
  - 逐 unit 提煉劇情摘要與衝突信息
  - 若單個 unit 提煉失敗，使用文本截斷與句子提取生成 fallback 框架
- 資料變化：
  - 原始 unit 文本 -> 更適合用於拆集與逐集規劃的摘要結構

### 2.5 拆集規劃

- Prompt：`prompt/unit_episode_split_planning_prompt.md`
- 輸入：`unit_frameworks + target_episode_count`
- 輸出：
  - 項目內：`output/.../episode_split_plan.json`
  - 根目錄鏡像：`episode_split_plan.json`
- 關鍵參數：
  - `DEFAULT_EPISODE_COUNT`
  - `EPISODE_SPLIT_REPAIR_ROUNDS`
- 強校驗規則：
  - 所有 `unit_id` 必須全部覆蓋且不能重複
  - `episode_count` 必須是非負整數
  - 總和必須嚴格等於目標集數
- 工作內容：
  - 先由 LLM 規劃 unit 到 episode 的分配
  - 若不合法，進入自動 repair rounds 修復
  - 若多輪修復仍不合法，流程報錯終止
- 資料變化：
  - Unit 級劇情框架 -> 全局集數分配方案

### 2.6 逐集生成規劃

- Prompt：`prompt/episode_generation_planning_prompt.md`
- 輸入：
  - `story_bible`
  - `story_units`
  - `unit_frameworks`
  - `episode_split_plan`
- 輸出：
  - 項目內：`output/.../episode_generation_plan.json`
  - 根目錄鏡像：`episode_generation_plan.json`
- 每集典型字段：
  - `title`
  - `source_units`
  - `arc_goal`
  - `opening_hook`
  - `core_beats`
  - `character_focus`
  - `props_used`
  - `ending_hook`
  - `continuity_requirements`
  - `generation_brief`
- 工作內容：
  - 把拆集結果展開為逐集可執行藍圖
  - 若模型輸出不完整，程式會補足 `source_units`、`core_beats`、`character_focus` 等默認值
- 資料變化：
  - 集數分配方案 -> 可逐集消費的生成合同

### 2.7 逐集內容生成

- Prompt：`prompt/episode_content_generation_prompt.md`
- 輸入：
  - `story_bible`
  - 單集 `episode_plan`
  - 對應 `source_units`
- 輸出：
  - `episodes/episode_0001.json ...`
  - `episodes/index.json`
  - `episodes_overview.json`
- 工作內容：
  - 按集生成標題、摘要、劇本正文與場景提綱
  - 使用有界並發提交逐集 LLM 任務，完成即落盤，最後統一生成索引
  - 若某一集模型生成失敗，使用 `episode_plan + source_units` 拼裝 fallback 內容
- 資料變化：
  - 逐集藍圖 -> 逐集可閱讀腳本

### 2.8 逐集分鏡生成

- Prompt：`prompt/storyboard_generation_prompt.md`
- 輸入：
  - `story_bible`
  - `episodes/episode_000x.json`
- 輸出：
  - `storyboards/episode_0001_storyboard.json ...`
  - `storyboards/index.json`
- 附加校驗：
  - 對白覆蓋率
  - 未知角色檢測
  - 必要道具覆蓋情況
  - 未知道具檢測
- 工作內容：
  - 把單集腳本轉為場景 / 鏡頭結構
  - 使用有界並發提交逐集分鏡任務，完成即落盤，最後統一生成索引
  - 若模型生成失敗，從劇本文本解析場景並構造保底分鏡
- 資料變化：
  - 逐集腳本 -> 結構化分鏡輸出

---

## 3. 產物目錄結構

每次 `/docs` 執行都會創建一個新的項目目錄：

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
  storyboards/
    episode_0001_storyboard.json
    ...
    index.json
  episodes_overview.json
  project_meta.json
```

此外，根目錄還會同步覆蓋：

- `episode_split_plan.json`
- `episode_generation_plan.json`

這兩個文件更像最近一次執行的鏡像快照，而不是歷史版本存檔。

---

## 4. 運行元信息與可追蹤性

`project_meta.json` 會記錄：

- 輸入文件名與原文字數
- 清洗後字數與清洗策略
- 各階段所用 prompt 文件
- Unit 數量、目標集數、規劃集數、實際生成數
- 各步耗時與總耗時
- 關鍵輸出文件與目錄名稱

它的作用是讓一次 `/docs` 執行具備基本的回溯能力。

---

## 5. 當前工作流的失敗處理策略

目前實現優先保證的是「流程可繼續」而不是「每一步都必須完美」。

- 劇本清洗失敗：分塊清洗，再退回本地清理
- 特徵提取部分失敗：跳過失敗分段，合併其餘有效結果
- Unit 框架失敗：對單個 unit 使用 fallback 框架
- 拆集規劃失敗：進入 repair rounds；若仍非法則中止
- 單集腳本失敗：該集使用 fallback，不阻塞其他集
- 分鏡生成失敗：該集使用 fallback，不阻塞其他集

只有在核心約束無法滿足時，流程才會真正停止，典型場景是：

- 拆集規劃在多輪修復後仍不合法
- 配置參數本身非法
- prompt 文件缺失
- 輸入文件不可讀

---

## 6. 一句話總結

這條 `/docs` 管線可以概括為：

```text
原始文檔 -> 清洗 -> 結構化知識提取 -> 故事單元切分 -> 集數規劃 -> 逐集腳本 -> 逐集分鏡 -> 可追蹤輸出
```

其中，LLM 負責生成與理解，程式負責切分、驗證、修復、落盤與追蹤。
