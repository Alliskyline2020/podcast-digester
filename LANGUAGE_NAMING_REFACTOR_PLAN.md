# 字段重构 + 音频语种判定 实施计划

> 状态：待评审 · 2026-07-02
> 范围：把 `text_original`/`text_translated`（角色命名）重构为 `text_zh`/`text_en`（语言命名），
> 同时修复 P0 根因——`_merge_bilingual_transcripts` 把英文硬编码为"原文"。
> 两个 effort 必须同一次落地，原因见 §1.3。

---

## 1. 背景

### 1.1 P0 根因（姚顺宇回归的真正来源）

`backend/app/sources/ytdlp_runner.py:298` 的 `_merge_bilingual_transcripts`：

```python
text_original=en_text or "",        # 行 348：英文硬编码为原文
text_translated=zh_seg.text_original,  # 行 349：中文降级为翻译
...
language="en",                      # 行 356 / 465：硬编码
```

对中文播客（原生中文 manual CC + 英文自动翻译 CC），这把**有损的英文自动翻译当成权威原文**，高质量中文 manual CC 反倒降级为"翻译"。整条链路（润色/分段/翻译条件/展示）建在有损英文地基上。docstring 直白写着"以英文字幕为原文（text_original，播客原语种）"——这个"播客原语种=英文"的假设对中文播客整条反向。

调用方（行 429–466）按文件名 `sub.{lang}.vtt` 区分中/英 CC，但**完全没有"哪个是音频实际语种"的概念**，两套都在时盲目假定英文是源。

可复用的探针 `_probe_audio_language`（`asr_afm3.py:277`，60s 采样判中/英）**只接在 ASR 分支**（`pipeline.py:256`），CC 获取分支没用它。

### 1.2 字段命名歧义

`Segment`（`models.py:55-62`）：

```python
text_original:   str  = "原始语言文本"      # 对中文视频却装英文 → 名实不符
text_translated: Optional[str] = "中文翻译"  # 描述写死"中文翻译"，烘焙了假设
text_with_punct: Optional[str]              # 保留（同语种润色版）
```

"原语种"概念只在采集/ASR 判定语种那一刻有用；之后字幕就只是"某语言的文本"。角色命名（original/translated）对"中文视频装英文"的场景自带歧义。

### 1.3 为什么两个 effort 必须合并

- 先做 naive 重命名、P0 未修 → 中文播客 `text_zh` 装有损英文、`text_en` 装原生中文，**比现状更糟**。
- 先修 P0、保留旧名 → "角色名"歧义依旧，重构白做一半。
- **正确顺序**：采集端先判定音频语种、按语种选权威 CC → 再把字段改为 `text_zh`/`text_en` 让语义落地。两步天然耦合。

---

## 2. 设计

### 2.1 字段语义（重构后）

| 字段 | 含义 |
|---|---|
| `Segment.text_zh` | 中文文本（无论原文还是译文） |
| `Segment.text_en` | 英文文本（无论原文还是译文） |
| `Segment.text_with_punct` | **音频语种**对应的去口水词+加标点版（展示与分段输入），保留 |
| `Segment.text_clean` | 分段器输出的同语种已润色文本，语义统一为"已润色" |
| `Transcript.language` / `Episode.language` | **音频实际语种** `"zh"`/`"en"`，由判定模块写入 |

**核心性质**：字段按**内容语种**命名，不再按"角色"。前端"哪轨展示"由 `episode.language` 决定。

### 2.2 音频语种判定模块（P0 修复核心）

新增 `backend/app/sources/lang_detect.py`，级联策略（A 起步、B 兜底，按既定方向）：

1. **manual CC 优先**（最强信号）：yt-dlp info-json 的 `subtitles`（人工）vs `automatic_captions`（自动）；人工 CC 的语种 = 音频语种。需新增 `--write-info-json`。
2. **元数据**：`info_json["language"]` / `title` 语种。
3. **文本启发**：各 CC 的 CJK 字符占比（区分"哪套是中文"，辅助）。
4. **音频探针兜底**：复用 `asr_afm3._probe_audio_language`。

签名（草案）：
```python
async def detect_source_language(
    cc_by_lang: dict[str, Transcript],   # {"zh": ..., "en": ...}
    info_json: dict | None,
    manual_langs: set[str],              # 来自 info subtitles (非 automatic)
    audio_path: Path | None = None,      # 探针兜底用
) -> SourceLangResult:                   # {lang, basis, confidence}
```
返回 `lang ∈ {"zh","en"}` + 判定依据（用于日志与降级审计）。

### 2.3 双语合并重构

`_merge_bilingual_transcripts(zh, en)` → `merge_bilingual(zh, en, source_lang)`：

- `source_lang="zh"` → `text_zh`=中文 CC，`text_en`=英文 CC，`language="zh"`
- `source_lang="en"` → `text_en`=英文 CC，`text_zh`=中文 CC，`language="en"`
- 时间戳对齐保留（3s 容差），主时间轴取自 source 语种 CC。

### 2.4 分段口径统一（P1 修复）

抽 `backend/app/services/segmenter_input.py`：

```python
def segments_for_segmenter(transcript) -> list[SegmentIn]:
    """单点收敛：所有分段入口统一喂 text_with_punct or <音频语种字段>。"""
```

四个入口（pipeline、`sync-subtitles`、`sync-subtitles-llm`、`batch-sync`）全部走它。输出字段对齐：都带 `id`，`text_clean` 统一为已润色同语种文本。

### 2.5 内容不丢失硬保证

- "音频语种字段"继承 `text_original` 的不可变权威语义，永不丢（已有断言保留）。
- 分段必须**覆盖全部 segment**：用 `segment_indices` 校验，缺失即断言/告警，不静默丢——把姚集 0 缺失的发现固化为测试。
- 任何衍生字段缺失 → 回退音频语种字段。

### 2.6 存量迁移的关键性质：content-based 自愈

迁移按**内容语种**（CJK 占比）路由，不按"角色"。因此能**自愈**姚这类倒挂：
- 旧数据 `text_original`=英文(自动译)、`text_translated`=中文(manual 高质)
- 迁移按内容：`text_zh` ← 中文(高质 manual) ✓，`text_en` ← 英文(自动译)
- 迁移后 `text_zh` 持有好中文，前端按 `language="zh"` 默认展中文润色版 → P0 用户面影响被迁移本身修复，无需逐集重处理（润色/分段质量可选单独重处理）。

---

## 3. 分阶段任务（TDD，每阶段独立可测可回滚）

### Phase 0 — 安全网（先于一切）
- [ ] 特征化测试：锁定当前 `_merge_bilingual_transcripts` 与三个分段器对已知样本的输出
- [ ] segment 覆盖率断言 helper + 测试（覆盖全部 `segment_indices`）
- [ ] dual-LCS 语义校验 helper（保留率 ≥0.85、新增率 ≤0.2）复用于润色/分段

### Phase 1 — 语种判定模块（独立纯函数）
- [ ] TDD `lang_detect.py`：manual CC 优先 / 元数据 / 文本启发 / 探针兜底，各级单测
- [ ] 集成测试：中文音频(zh manual + en auto) → `source="zh"`；英文音频(en manual) → `source="en"`
- [ ] 不接入主链路，纯模块 + 测试

### Phase 2 — Segment 模型加字段（additive，与旧字段并存）
- [ ] `Segment` 加 `text_zh`/`text_en`，`text_with_punct` 保留
- [ ] transcript.json / paragraph_mappings 序列化支持新字段
- [ ] 单测：往返序列化、缺字段回退

### Phase 3 — 重写采集（merge_bilingual + 单语 CC）
- [ ] `fetch_youtube_subtitles` 拉 info-json → 调判定模块得 `source_lang`
- [ ] `merge_bilingual(zh, en, source_lang)` 按 source 写 `text_zh`/`text_en`
- [ ] 单语 CC：zh → `text_zh`/`language="zh"`；en → `text_en`/`language="en"`
- [ ] TDD：姚场景 → `text_zh`=manual 中文、`language="zh"`

### Phase 4 — 迁移消费方（带旧字段回退）
- [ ] pipeline 润色：按 `transcript.language` 选 `text_zh`/`text_en` 作输入 → 写 `text_with_punct`
- [ ] 三个分段器 + `segments_for_segmenter` 收敛点（修 P1）
- [ ] 翻译条件：`language != 目标` 才译（中文播客不再回译）
- [ ] 路由（subtitles/admin）+ 下游 LLM（highlight/insight/summary）读新字段，回退旧字段
- [ ] 每处 TDD

### Phase 5 — 前端
- [ ] `subtitleLang`: original/translated/both → **zh/en/dual**
- [ ] 默认轨由 `episode.language` 决定（中文播客默认 zh、展 `text_zh` 润色版）
- [ ] `PlayerView.vue` / `TranscriptEditor.vue` / `SubtitlePane.vue` / `api.js` + 2 前端测试

### Phase 6 — 存量迁移（content-based 自愈）
- [ ] 迁移脚本：按 CJK 占比把旧 `text_original`/`text_translated` 路由到 `text_zh`/`text_en`
- [ ] 覆盖 40 episode 目录的 `transcript.json` + SQLite `paragraph_mappings` 列
- [ ] dry-run 模式 + 逐集报告（zh/en 段数、覆盖、告警）；先备份
- [ ] （可选）"按新逻辑重处理"按钮——修润色/分段质量，不修语种（语种已被迁移修好）

### Phase 7 — 清理（迁移验证后）
- [ ] 移除旧 `text_original`/`text_translated`（消费者已无回退依赖）
- [ ] 移除 `legacy.py:112` 的 `text_zh↔text_translated` 适配

---

## 4. 爆炸半径（已亲自核实）

| 层 | 文件/位置 |
|---|---|
| 模型 | `models.py:55-62`（Segment）、Transcript、TranscriptResponse |
| 采集 | `sources/ytdlp_runner.py:298-358,429-466,475+`、`sources/subtitle_vtt.py`、新增 `sources/lang_detect.py` |
| 处理 | `pipeline.py:224,256-268,308-314,578-594,701-704,901-938,972-973`、`asr_afm3.py:161,256,277-334` |
| 润色/分段 | `services/subtitle_processor.py:140`、`services/subtitle_segmenter.py`、`services/llm_semantic_segmenter.py`、新增 `services/segmenter_input.py` |
| 下游 LLM | `llm_highlight.py`、`llm_product_insight.py`、summary（读 `text_translated→text_original`） |
| 路由 | `routers/subtitles.py:158,242`、`routers/admin.py:133,140` |
| 存储 | `database.py`（paragraph_mappings 列 + transcript.json 同步）、`storage.py` |
| 前端 | `PlayerView.vue`、`TranscriptEditor.vue`、`SubtitlePane.vue`、`api.js` |
| 测试 | 13 个后端测试 + 2 个前端测试 |
| 存量数据 | 40 episode 目录 / 30 transcript.json + SQLite 列 |
| 遗留适配 | `legacy.py:112`（已把 LLM 输出的 `text_zh` 键映射到 `text_translated`——新字段名与既有内部约定对齐）|

---

## 5. 风险与缓解

| 风险 | 缓解 |
|---|---|
| 语种判定误判 | 级联 + 置信度/依据日志 + 探针兜底；误判可手动重处理 |
| 迁移脚本误路由 | content-based + dry-run + 逐集报告 + 先备份 |
| 字段并存期不一致 | 旧字段回退 + 特征化测试守门 |
| 与字幕管道重构（dual-LCS）叠加 | **本计划先于 dual-LCS 字幕重构落地**（rename 先行，验证逻辑读这些字段）|
| highlight/insight/click-to-play 受影响 | 不动逻辑，只改读取字段；回归测试守门 |

---

## 6. 验收标准

- [ ] 中文播客（姚）重处理后：`text_zh`=manual 中文、`language="zh"`、前端默认展中文润色版
- [ ] 英文播客：`text_en`=英文、`text_zh`=译文、`language="en"`
- [ ] 所有分段入口覆盖全部 segment（断言通过）
- [ ] 单元/集成/E2E 测试绿，覆盖率 ≥80%
- [ ] 40 episode 存量迁移 dry-run 报告无丢失
- [ ] highlight/insight/click-to-play 行为不变（回归测试通过）

---

## 7. 不动项

- 姚顺宇当前字幕**维持现状**（数据完整、未丢内容），待本方案落地后一并重处理，避免反复改。
- highlight/insight/产品洞察逻辑不改，只改它们读取的字段。
- `text_with_punct`/`text_clean` 作为"同语种质量变体"保留，仅赋值行重定向到音频语种字段。

---

## 8. 待确认（你已给方向，记录在此）

1. **语种判定力度**：A（元数据 + manual CC 优先）起步、B（音频采样探针）兜底 ✅
2. **存量处理**：迁移脚本自动纠语种 + 可选"重处理"按钮修质量 ✅
3. **双语合并**：保留（按 source_lang 决定主轨）✅
