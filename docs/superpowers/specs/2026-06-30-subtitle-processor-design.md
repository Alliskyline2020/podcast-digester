# SubtitleProcessor 设计：对齐时间戳的字幕润色 + 翻译

- **日期**: 2026-06-30
- **状态**: 已确认，待实现
- **范围**: 后端字幕处理服务重构 + pipeline 接入 + 已有 11 个 episode 重跑

## 1. 问题陈述

当前字幕处理存在三个问题：

1. **批次级 drift（最严重）**：`subtitle_polisher` 把 15 个连续 segment 喂给 LLM、按 `id` 匹配输出。当批次内容连贯时，LLM 跨句重组，导致 `text_with_punct[id=N]` 实际描述的是 segment N±1 的音频。约 830 句错位（Manus 7%、部分中文 episode 2-5%）。表现：显示的文字和播放的音频对不上。
2. **两套冗余标点系统**：`punctuation_restorer`（接入 pipeline，仅中文、只加标点）和 `subtitle_polisher`（未接入，双语、加标点+去口水话，但有 drift）。
3. **英文翻译对齐无保证**：翻译无词法锚点，drift 无法用重叠度检测。

## 2. 目标 / 非目标

**目标**

- 中文 episode：润色（标点 + 口水话 + 口吃叠词修复）→ `text_with_punct`，不翻译。
- 英文 episode：轻量润色英文 → `text_with_punct`（原文备份）；高质量中文翻译 → `text_translated`（主输出）。
- 修复 drift：`text_with_punct[id]` / `text_translated[id]` 永远对应 `text_original[id]` 的音频。
- 接入 ingestion pipeline（新 episode 自动处理），替换冗余的 `punctuation_restorer`。
- 重跑已有 11 个 episode（覆盖 drift 文本）。

**非目标**

- 不改 `Segment` schema。
- 不改前端分段算法（`paragraphs` / `splitSegmentByLength`）的核心逻辑——drift 修好后分段自然正确。
- 不重新生成已存的金句 / 洞察（用户要求"不影响"）。
- 不把润色文本接到下游（ZH 下游仍读 `text_original`）——列为未来可选增强。

## 3. 硬约束（不可违反）

| 约束 | 含义 |
|---|---|
| **时间戳不可变** | `id` / `start_ms` / `end_ms` 永不写。播放/跳转/金句定位都依赖它。 |
| **语义不变** | 只加标点 + 删无语义口水话/叠词；不重写/换词/换序/补全。越界即回退原文。 |
| **段落不丢** | 段数不变；每个 segment 的关键字段逐字节相同；每段 `text_with_punct` 非空；EN 每段 `text_translated` 非空。 |

## 4. 数据模型与不可变性契约

**无 schema 变更。** `Segment` 字段访问权限：

| 字段 | 权限 | 说明 |
|---|---|---|
| `id`, `start_ms`, `end_ms` | 🔒 只读·永不触碰 | 时间戳/结构键 |
| `text_original` | 🔒 只读·永不触碰 | 原始 ASR 备份 |
| `text_with_punct` | ✍️ 润色写入 | 显示用 |
| `text_translated` | ✍️ 翻译写入（仅 EN） | 中文翻译，下游金句/洞察也读 |

**不可变性后置条件**（代码断言 + 测试项）：处理前后

```
[(s.id, s.start_ms, s.end_ms, s.text_original) for s in segments]
```

必须**逐字节相同**。

## 5. 架构：统一 `SubtitleProcessor` 服务

一个服务 owns 整个"原始字幕 → 可读 + 时间戳对齐"变换。单一接口：

```python
async def process(self, transcript: Transcript) -> Transcript
```

- 只写 `text_with_punct` 和 `text_translated`。
- 内部顺序：先润色（双语）→ 再翻译（仅 EN，从润色后的英文翻译，更干净源 → 更好中文）。
- 替换 pipeline stage 2.5 的 `_add_punctuation_to_transcript`（旧 `punctuation_restorer`）。旧 stage 5 翻译合并进 processor。**删除 `punctuation_restorer`。**

## 6. 润色路径（同语言：ZH 润色 + EN 轻润色）

```
对每批 15 个未润色 segment:
  inputs = [{id, text: s.text_original}]
  result = LLM(polish_prompt, inputs)          # {polished:[{id,text}]}
  对每个 s in batch（含异常兜底）:
    out = result.polished.get(s.id)
    若 out 非空 且 语义校验通过(out, s.text_original):
        s.text_with_punct = out                # 接受
    否则:
        s.text_with_punct = s.text_original    # 回退（drift / 语义被改 / LLM 漏返 / 异常）
```

**口水话感知的双向 LCS 语义校验** `semantic_ok(out, orig)`：

```
o = remove_fillers(normalize(orig))   # 去标点/空白/小写 + 删已知口水话/叠词白名单
p = remove_fillers(normalize(out))    # 同上白名单（prompt 指示 LLM 删的那批）
lcs = len(lcs_chars(o, p))
preserve  = lcs / max(len(o), 1)       # 实义内容保留率
addition  = (len(p) - lcs) / max(len(p), 1)  # 新增率
通过 ⇔ preserve ≥ 0.90 且 addition ≤ 0.15
```

**为什么先删口水话再算 LCS**：直接算会把"删口水话"和"丢实义内容"都算成保留率下降，导致口水话密集的段（最该润色的）被误判回退。先按白名单（中文 嗯/啊/呃/那个/然后呢/就是说/对吧/你看；英文 um/uh/you know/I mean/like/so/kind of...，即 prompt 同一份列表）从两侧剔除，LCS 就只度量**实义内容**的保留——删口水话不扣分，只有真丢内容才扣分。

- drift（邻段内容）→ 两率同时崩 → 回退。
- 语义篡改（丢实义内容）→ preserve 掉 → 回退。
- 幻觉/换词/加料 → addition 升 → 回退。

**硬保证**：`text_with_punct[id]` 永远对应 `text_original[id]` 的音频。最坏 = 未润色但正确。回退 = 写 `text_original` = 零语义改动。

## 7. 翻译路径（EN→ZH，主输出）

翻译无词法锚点，改用**结构保证 + 逐句兜底**：

```
对每批 EN segment（源 = 已润色 text_with_punct，无则 text_original）:
  result = LLM(translate_prompt, inputs)       # {translated:[{id,text_zh}]}
  若 result.ids == inputs.ids 且 数量一致:        # 结构校验 → 1:1 对齐可信
      写 text_translated（空/过短 → 回退）
  否则:                                         # 结构不符 → drift 风险
      整批降级为逐句翻译（单入单出，物理上不可能跨句重组）
```

三层防线：强约束 prompt（禁合并/换序）→ 结构校验 → 不符则逐句回退。最坏 = 逐句翻译（慢但对齐绝对正确）。

EN 回退链：已有 `text_translated`（双语字幕）→ 逐句翻译 → `text_original` 兜底。保证 EN 每段 `text_translated` 非空。

**下游影响**：下游读 `text_translated`，翻译提升 = 未来金句/洞察质量提升（正向）。已存金句不重生成，仍 seek 到不变的 `start_ms`。

## 8. 显示分段

**保留前端 `paragraphs` / `splitSegmentByLength`（MAX160/MIN40）不变。** 当前分段数学是对的，问题纯粹是 drift。drift 修复后，分段自然正确；润色补的标点让按句号切分更准，显示**作为副作用一并改善**。

已知小限制（非阻塞）：英文长 segment 被 `splitSegmentByLength` 切分时，子块翻译会空。但 ASR segment 粒度极细（8-13 字），几乎不触发切分；非切分段翻译正常携带。必要时顺手修（把翻译按比例分摊到子块）。

## 9. 下游安全证明

| 下游 | 读什么 | 处理器影响 | 结论 |
|---|---|---|---|
| 金句 `llm_highlight` | `text_translated or text_original` + 存 `start_ms`/`cited_segment_ids` | ZH 读 text_original(不动)；EN 读 text_translated(改好) | 已存金句 seek 到不变 start_ms → 仍有效；未来金句用更干净文本 → 更好 |
| 洞察 `llm_product_insights` | 同上 + `cited_segment_ids→id→start_ms` | id/start_ms 不可变 | 跳转永远正确 |
| 点击播放 `localSeekTo(start_ms)` | timestamp | 不可变 | 永远正确 |

不可变性后置条件保证 `id`/`start_ms`/`end_ms`/`text_original` 处理前后逐字节相同。**不重生成已存金句/洞察。**

## 10. Pipeline 接入

- 用 `SubtitleProcessor.process(transcript)` 替换 stage 2.5 `_add_punctuation_to_transcript`。
- `process` 内部：润色（双语）→ 翻译（EN，从润色源）。
- 旧 stage 5 翻译合并进 processor（保留进度回调 + checkpoint 语义，processor 后 pipeline 做一次 `transcript.json` checkpoint）。
- 删除 `app/services/punctuation_restorer.py`（及 pipeline 里的 `_needs_punctuation` / `_add_punctuation_to_transcript`）。

## 11. 重跑计划（已有 11 episode）

- 脚本：加载每个 `transcript.json` → `SubtitleProcessor.process()` → 写回文件 + DB。
- `skip_if_punctuated=False`（强制覆盖可能 drift 的 `text_with_punct`）。
- EN episode 从润色源重译，覆盖旧 `text_translated`。
- 每个 episode 跑完执行**不可变性后置条件检查**（段数 + 关键字段逐字节比对）。
- 幂等：重跑产生相同结果（低 temperature）。

## 12. 错误处理

- 批 LLM 失败 → 跳过该批，segment 回退 `text_original`，日志，继续。字幕非核心，降级 < 整集失败。
- 语义/结构校验不符 → 逐句回退（翻译）/ 回退原文（润色）。日志 drift 计数。
- **回退在异常路径也必须触发**（try/except 兜底，非仅正常分支）。
- 永不因字幕问题中断 episode。

## 13. 测试（pytest）

1. **`semantic_ok` 度量**（口水话感知）：纯口水话段（嗯然后呢…）删口水话后仍通过；润色样本通过；drift 样本（两率崩）失败；丢实义内容样本（保留率掉）失败；幻觉/换词样本（新增率高）失败。
2. **结构校验 + 回退路径**（翻译）：ids 不符 → 逐句回退。
3. **不可变性后置条件**：处理前后 `id`/`start_ms`/`end_ms`/`text_original` 逐字节相同；段数不变；每段 `text_with_punct` 非空；EN 每段 `text_translated` 非空。
4. **drift 回归**：喂入故意错位的 LLM 响应 → 断言 100% 回退原文。
5. **异常兜底**：LLM 抛异常 → 该批全部回退原文，段不丢、不空、不中断。
6. **集成**：小 transcript 跑通，验证对齐 + 时间戳完好。

## 14. 阈值常量

| 常量 | 值 | 说明 |
|---|---|---|
| `POLISH_BATCH_SIZE` | 15 | non-thinking 模式长批次 JSON 易出错 |
| `LCS_PRESERVE_MIN` | 0.90 | 实义内容保留率下限（口水话已剔除后） |
| `LCS_ADD_MAX` | 0.15 | 新增率上限（不幻觉） |
| `TRANSLATE_BATCH_SIZE` | 15 | 翻译批大小 |
| `POLISH_MODEL` | `deepseek-chat` | non-thinking，简单任务 |
| `TRANSLATE_MODEL` | `deepseek-chat` | non-thinking |

阈值集中定义，便于调参。
