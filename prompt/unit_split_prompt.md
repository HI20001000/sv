# Unit Split Prompt

## Purpose
將清洗後的長劇本文本切分為可規劃、可引用、可分配的 `story_units`。

這個階段目前採用本地規則拆分，不直接調用 LLM 生成內容；但本檔中的拆分策略與參數
會在執行 `/docs` 時被讀取，直接影響第 3 步 `Unit Split` 的結果。

---

## Runtime Rules
- 優先以段落為單位聚合內容。
- 當單段超過 `window_max` 時，再按句子邊界細分。
- 每個 unit 儘量保持在 `window_min ~ window_max` 的字數窗口內。
- 若最後一個 unit 過短，且 `merge_short_tail_unit = true`，則合併到前一個 unit。
- `sentence_boundaries` 會作為句子切分標點集合使用。

---

## Runtime Config
```json
{
  "window_min": 1500,
  "window_max": 2200,
  "sentence_boundaries": "。！？!?；;",
  "merge_short_tail_unit": true
}
```

---

## Output Shape
每個 unit 會保留以下欄位：

```json
{
  "unit_id": "u_0001",
  "char_count": 0,
  "source_span": {
    "start_para": 1,
    "end_para": 3
  },
  "text": ""
}
```
