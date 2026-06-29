# SubtitleProcessor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the drifting `subtitle_polisher` + redundant `punctuation_restorer` with one `SubtitleProcessor` service that polishes (ZH) and translates (EN) subtitles with hard guarantees: timestamps immutable, semantics preserved, no segment lost — without breaking highlights/insights/click-to-play.

**Architecture:** A new `SubtitleProcessor` service owns the subtitle transformation. Polish uses a filler-aware two-sided LCS validation gate (catches drift AND semantic alteration), falling back to `text_original` on any failure. Translation reuses the proven `translate_segments` plus a structural no-gap fallback. Pipeline stage 2.5 calls `processor.polish()`, stage 5 calls `processor.translate()`. Only `text_with_punct` / `text_translated` are ever written; `id`/`start_ms`/`end_ms`/`text_original` are byte-identical before/after (asserted).

**Tech Stack:** Python 3, FastAPI app, pydantic models, pytest (tests in `backend/tests/`), DeepSeek `chat_json` LLM helper, existing `translate_segments`.

## Global Constraints

- **Timestamps immutable**: never write `Segment.id` / `start_ms` / `end_ms`. Asserted post-condition.
- **Semantics immutable**: polish only adds punctuation + removes a closed filler/stutter whitelist; any over-change trips the filler-aware LCS gate → fall back to `text_original`.
- **No segment lost**: segment count unchanged; `text_with_punct` non-empty for every segment whose `text_original` is non-empty; EN `text_translated` non-empty for every segment (ultimate fallback `text_original`).
- **Downstream untouched**: highlights/insights read `text_translated or text_original`; click-to-play seeks to `start_ms`. Processor writes only display fields, so these are provably unaffected.
- **No LLM calls in unit tests**: mock `chat_json` and `translate_segments`.
- Thresholds: `POLISH_BATCH_SIZE=15`, `LCS_PRESERVE_MIN=0.90`, `LCS_ADD_MAX=0.15`, model `deepseek-chat`.

---

## File Structure

- **Create** `backend/app/services/subtitle_align.py` — pure alignment/semantic-check functions + filler whitelist. No LLM, no I/O. Fully unit-testable.
- **Create** `backend/app/services/subtitle_processor.py` — `SubtitleProcessor` class with `polish()`, `translate()`, and immutability snapshot/assert helpers. Replaces `subtitle_polisher.py`.
- **Create** `backend/tests/test_subtitle_align.py` — unit tests for alignment functions.
- **Create** `backend/tests/test_subtitle_processor.py` — unit tests for polish/translate (mocked LLM) + immutability.
- **Modify** `backend/app/pipeline.py` — stage 2.5 → `processor.polish()`; stage 5 → `processor.translate()`; delete `_needs_punctuation` + `_add_punctuation_to_transcript`.
- **Delete** `backend/app/services/punctuation_restorer.py` (zh-only, redundant).
- **Delete** `backend/app/services/subtitle_polisher.py` (replaced by `subtitle_processor.py`).
- **Create** `backend/rerun_subtitle_processor.py` — one-off rerun for the 11 existing episodes + immutability check.

---

### Task 1: Filler-aware LCS alignment utilities

**Files:**
- Create: `backend/app/services/subtitle_align.py`
- Test: `backend/tests/test_subtitle_align.py`

**Interfaces:**
- Produces: `normalize(text) -> str`, `remove_fillers(text) -> str`, `semantic_ok(polished, original) -> bool`, plus constants `LCS_PRESERVE_MIN=0.90`, `LCS_ADD_MAX=0.15`.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_subtitle_align.py`:

```python
"""subtitle_align 纯函数单元测试。"""
from app.services.subtitle_align import (
    normalize, remove_fillers, semantic_ok, LCS_PRESERVE_MIN, LCS_ADD_MAX,
)


def test_normalize_strips_punctuation_whitespace_and_lowercases():
    assert normalize("Hello, World!  你好。") == "helloworld你好"


def test_remove_fillers_chinese_substring():
    # 删口水话, 保留实义内容
    assert remove_fillers("嗯然后呢我觉得这个浏览器") == "我觉得这个浏览器"


def test_remove_fillers_english_word_boundary():
    # 词边界删, 不误删子串(如 "like" 不应吃掉 "likely")
    assert remove_fillers("um you know the likely case") == " the likely case"


def test_semantic_ok_passes_clean_punctuation_only():
    original = "我觉得这个浏览器很好用"
    polished = "我觉得，这个浏览器很好用。"
    assert semantic_ok(polished, original) is True


def test_semantic_ok_passes_filler_removal():
    # 删口水话不应扣分(白名单已剔除后再算 LCS)
    original = "嗯然后呢我觉得这个浏览器很好用"
    polished = "我觉得这个浏览器很好用。"
    assert semantic_ok(polished, original) is True


def test_semantic_ok_rejects_drift_different_content():
    # drift: polished 是邻段内容, 与原文实义几乎不重叠
    original = "维护成本和移动端的商业模式"
    polished = "Craigslist 和 BAT 是新媒介的代表。"
    assert semantic_ok(polished, original) is False


def test_semantic_ok_rejects_content_loss():
    # 丢了实义内容("浏览器") → 保留率掉
    original = "我收到过一些收购的offer因为浏览器是谁的"
    polished = "我收到过一些。"  # 丢了大半实义内容
    assert semantic_ok(polished, original) is False


def test_semantic_ok_rejects_hallucination_addition():
    # 加了原文没有的实义内容 → 新增率升
    original = "浏览器是谁的"
    polished = "浏览器是谁的OpenAI和谷歌都在争夺这个入口"
    assert semantic_ok(polished, original) is False


def test_thresholds():
    assert LCS_PRESERVE_MIN == 0.90
    assert LCS_ADD_MAX == 0.15
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && ./venv/bin/pytest tests/test_subtitle_align.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.subtitle_align'`

- [ ] **Step 3: Write the implementation**

Create `backend/app/services/subtitle_align.py`:

```python
"""字幕对齐与语义校验的纯函数。

口水话感知的双向 LCS 校验: 先按白名单从两侧剔除口水话/叠词, 再用字符级
最长公共子序列度量实义内容的保留率与新增率。用于检测润色输出的
drift(邻段内容)和语义篡改(丢内容/幻觉/换词)。

无 LLM, 无 I/O, 完全可单测。
"""
import re

# 口水话/填充词白名单 —— 与 SubtitleProcessor 的 POLISH prompt 指示 LLM 删除的列表一致。
# 长串在前, 避免短串先替换破坏长串(如 "就是说" 先于 "就是")。
ZH_FILLERS = [
    "就是这个", "就是说", "然后呢", "对吧", "你看", "的话",
    "那个", "然后", "嗯", "啊", "呃", "哎", "呢", "吧", "嘛", "哦",
]
EN_FILLERS = [
    "you know", "i mean", "sort of", "kind of",
    "basically", "actually", "literally",
    "um", "uh", "er", "ah", "hmm", "like", "so",
]

_PUNCT_RE = re.compile(r"[，。！？、；：""''（）【】《》…\s,.!?;:\"'()\[\]<>\\-]")

LCS_PRESERVE_MIN = 0.90  # 实义内容保留率下限(口水话已剔除后)
LCS_ADD_MAX = 0.15       # 新增率上限(防幻觉/换词)


def normalize(text: str) -> str:
    """去标点/空白/小写。"""
    return _PUNCT_RE.sub("", text or "").lower()


def remove_fillers(text: str) -> str:
    """删除已知口水话/填充词。中文按子串, 英文按词边界。"""
    out = text or ""
    for f in ZH_FILLERS:
        out = out.replace(f, "")
    for f in EN_FILLERS:
        out = re.sub(r"\b" + re.escape(f) + r"\b", "", out)
    return out


def _lcs_len(a: str, b: str) -> int:
    """字符级最长公共子序列长度(空间优化, O(min(len)) 内存)。"""
    if not a or not b:
        return 0
    prev = [0] * (len(b) + 1)
    for i in range(1, len(a) + 1):
        cur = [0] * (len(b) + 1)
        ai = a[i - 1]
        for j in range(1, len(b) + 1):
            if ai == b[j - 1]:
                cur[j] = prev[j - 1] + 1
            else:
                cur[j] = prev[j] if prev[j] >= cur[j - 1] else cur[j - 1]
        prev = cur
    return prev[len(b)]


def semantic_ok(polished: str, original: str) -> bool:
    """口水话感知双向 LCS 校验。

    返回 True 当且仅当 polished 在实义内容上与 original 一致(只删了白名单口水话、加了标点)。
    drift(邻段内容)或语义篡改(丢实义内容/幻觉/换词)都返回 False。

    边界: original 去口水话后为空(纯口水话句)时, 只要 polished 也很短即通过
    (空 polished 由调用方的非空检查兜底回退原文)。
    """
    o = remove_fillers(normalize(original))
    p = remove_fillers(normalize(polished))
    if not o:
        return len(p) <= 2
    lcs = _lcs_len(o, p)
    preserve = lcs / len(o)
    addition = (len(p) - lcs) / len(p) if len(p) else 0.0
    return preserve >= LCS_PRESERVE_MIN and addition <= LCS_ADD_MAX
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && ./venv/bin/pytest tests/test_subtitle_align.py -v`
Expected: 9 passed.

- [ ] **Step 5: Commit**

```bash
cd backend && git add app/services/subtitle_align.py tests/test_subtitle_align.py
git -c user.name="Al Li" -c user.email="alli@local" commit -m "feat: filler-aware LCS alignment utils for subtitle validation"
```

---

### Task 2: SubtitleProcessor.polish (LCS-gated, drift-proof)

**Files:**
- Create: `backend/app/services/subtitle_processor.py`
- Test: `backend/tests/test_subtitle_processor.py`

**Interfaces:**
- Consumes: `semantic_ok` from Task 1; `chat_json` from `app.llm`.
- Produces: `SubtitleProcessor` class with `async polish(transcript, progress_cb=None) -> int` (modifies `segment.text_with_punct` in place; returns polished count); `_snapshot(transcript)` and `_assert_immutability(snapshot, transcript)`.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_subtitle_processor.py`:

```python
"""SubtitleProcessor 单元测试(LLM 全部 mock)。"""
import pytest
from app.models import Segment, Transcript
from app.services.subtitle_processor import SubtitleProcessor


def _seg(i, text, translated=None):
    return Segment(id=i, start_ms=i * 1000, end_ms=i * 1000 + 999,
                   text_original=text, text_translated=translated)


def _transcript(lang, segs):
    return Transcript(episode_id="ep_test", language=lang, segments=segs)


@pytest.mark.asyncio
async def test_polish_accepts_clean_punctuation(monkeypatch):
    async def fake_chat_json(system, user, **kw):
        return {"polished": [{"id": 0, "text": "我觉得，这个浏览器很好用。"}]}
    monkeypatch.setattr("app.services.subtitle_processor.chat_json", fake_chat_json)

    t = _transcript("zh", [_seg(0, "我觉得这个浏览器很好用")])
    n = await SubtitleProcessor().polish(t)
    assert n == 1
    assert t.segments[0].text_with_punct == "我觉得，这个浏览器很好用。"


@pytest.mark.asyncio
async def test_polish_falls_back_on_drift(monkeypatch):
    # LLM 返回邻段内容(drift) → semantic_ok False → 回退原文
    async def fake_chat_json(system, user, **kw):
        return {"polished": [{"id": 0, "text": "Craigslist 和 BAT 是新媒介的代表。"}]}
    monkeypatch.setattr("app.services.subtitle_processor.chat_json", fake_chat_json)

    t = _transcript("zh", [_seg(0, "维护成本和移动端的商业模式")])
    n = await SubtitleProcessor().polish(t)
    assert n == 0  # 没有任何句被接受
    assert t.segments[0].text_with_punct == "维护成本和移动端的商业模式"  # 回退原文


@pytest.mark.asyncio
async def test_polish_falls_back_when_llm_missing_id(monkeypatch):
    async def fake_chat_json(system, user, **kw):
        return {"polished": []}  # LLM 漏返
    monkeypatch.setattr("app.services.subtitle_processor.chat_json", fake_chat_json)

    t = _transcript("zh", [_seg(0, "这是一个测试")])
    await SubtitleProcessor().polish(t)
    assert t.segments[0].text_with_punct == "这是一个测试"  # 回退, 非空


@pytest.mark.asyncio
async def test_polish_falls_back_on_llm_exception(monkeypatch):
    async def fake_chat_json(system, user, **kw):
        raise RuntimeError("api down")
    monkeypatch.setattr("app.services.subtitle_processor.chat_json", fake_chat_json)

    t = _transcript("zh", [_seg(0, "这是一个测试"), _seg(1, "第二句话")])
    await SubtitleProcessor().polish(t)  # 不抛异常
    assert t.segments[0].text_with_punct == "这是一个测试"
    assert t.segments[1].text_with_punct == "第二句话"


@pytest.mark.asyncio
async def test_polish_preserves_timestamps_and_original(monkeypatch):
    async def fake_chat_json(system, user, **kw):
        return {"polished": [{"id": 0, "text": "这是测试。"}]}
    monkeypatch.setattr("app.services.subtitle_processor.chat_json", fake_chat_json)

    seg = _seg(0, "这是测试")
    t = _transcript("zh", [seg])
    snap = SubtitleProcessor()._snapshot(t)
    await SubtitleProcessor().polish(t)
    SubtitleProcessor()._assert_immutability(snap, t)  # 不抛 = 通过
    # text_with_punct 非空, 但 id/start_ms/end_ms/text_original 未变
    assert (seg.id, seg.start_ms, seg.end_ms, seg.text_original) == snap[0]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && ./venv/bin/pytest tests/test_subtitle_processor.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.subtitle_processor'`.

- [ ] **Step 3: Write the implementation**

Create `backend/app/services/subtitle_processor.py`:

```python
"""SubtitleProcessor: 对齐时间戳的字幕润色(ZH)+翻译(EN)统一服务。

硬约束:
- 时间戳不可变: id/start_ms/end_ms 永不写(后置条件断言)。
- 语义不变: 只加标点+删白名单口水话; 越界(口水话感知 LCS 校验)即回退 text_original。
- 段落不丢: 段数不变; 每个有 text_original 的 segment, text_with_punct 非空。

下游金句/洞察读 text_translated or text_original, 跳转靠 start_ms; 本服务只写
text_with_punct/text_translated, 故不影响金句/洞察/点击播放。
"""
import logging
from typing import Callable, Optional

from ..llm import chat_json
from ..llm_pipeline import translate_segments
from .subtitle_align import semantic_ok

logger = logging.getLogger(__name__)

POLISH_BATCH_SIZE = 15
POLISH_MODEL = "deepseek-chat"
POLISH_MAX_TOKENS = 8000

POLISH_SYSTEM = """你是专业的播客字幕编辑。对 ASR 字幕(中文或英文)做两件事:

1. **补充正确标点**: ASR 标点经常不准/缺失/错位。根据语义重新加正确标点让字幕自然可读。
   - 中文: 逗号、句号、问号、感叹号、顿号、分号
   - 英文: comma, period, question mark, exclamation mark, semicolon, colon; 修正首字母大写与句末标点

2. **去除口水话和无意义填充**, 但保留有语义作用的词:
   - 中文: 删 "嗯""啊""呃""那个""然后呢""就是说""对吧""你看""的话""就是这个" 等口头禅/语气词/无意义重复
   - 英文: 删 "um", "uh", "er", "ah", "hmm", "you know", "I mean", "like"(填充), "sort of", "kind of", "basically", "actually", "literally"(填充), 以及无意义重复("the the", "I I")
   - 中文"然后/因为"、英文 "because/therefore/however/so"(表逻辑) → 保留
   - 人名/产品名/公司名/数字/术语 → 原样保留

**绝对铁律(违反任一条都算失败)**:
- 不改变语义, 不增删信息, 不修正事实, 不补全省略
- 输出语言与输入相同(不翻译)
- 输出句数严格等于输入句数, 按 id 一一对应, 不改顺序/不合并/不拆分
- 人名/产品名/公司名/数字/术语原样保留(Manus、OpenAI、2025、GPT-4)
- 某句已很好则原样输出"""


def _build_polish_user(inputs: list) -> str:
    import json
    return f"""以下是 {len(inputs)} 句 ASR 字幕(中文或英文), 逐句优化(加标点 + 去口水话)。保持每句原有语言, 不要翻译。

输入字幕(JSON 数组):
{json.dumps(inputs, ensure_ascii=False, indent=2)}

输出 JSON(严格格式):
{{
  "polished": [
    {{"id": 0, "text": "第 0 句优化后的文本"}}
  ]
}}

务必: polished 数组长度 = {len(inputs)}; 每个 id 与输入相同; 输出语言与输入相同; 只改标点和口水话, 不改语义; 不合并/拆分/换序。"""


class SubtitleProcessor:
    """字幕润色 + 翻译, 只写显示字段, 时间戳/语义/段数不变。"""

    # ---------- 不可变性 ----------
    def _snapshot(self, transcript) -> list:
        return [(s.id, s.start_ms, s.end_ms, s.text_original) for s in transcript.segments]

    def _assert_immutability(self, snapshot: list, transcript) -> None:
        cur = [(s.id, s.start_ms, s.end_ms, s.text_original) for s in transcript.segments]
        assert cur == snapshot, "不可变性违反: id/start_ms/end_ms/text_original 被改动"

    # ---------- 润色 ----------
    async def polish(self, transcript, progress_cb: Optional[Callable[[float], None]] = None) -> int:
        """润色所有 segment 的 text_with_punct(双语)。返回实际接受的句数。

        每个 text_original 非空的 segment, 处理后 text_with_punct 必非空:
        LLM 输出通过 semantic_ok 才接受, 否则回退 text_original(drift/语义被改/漏返/异常)。
        """
        segments = transcript.segments
        total = len(segments)
        if total == 0:
            return 0
        polished = 0
        for start in range(0, total, POLISH_BATCH_SIZE):
            batch = segments[start:start + POLISH_BATCH_SIZE]
            inputs = [{"id": s.id, "text": s.text_original}
                      for s in batch if (s.text_original or "").strip()]
            pmap: dict = {}
            if inputs:
                try:
                    result = await chat_json(
                        system=POLISH_SYSTEM,
                        user=_build_polish_user(inputs),
                        temperature=0.2,
                        model=POLISH_MODEL,
                        max_tokens=POLISH_MAX_TOKENS,
                        response_format={"type": "json_object"},
                    )
                    pmap = {p.get("id"): (p.get("text") or "").strip()
                            for p in result.get("polished", [])}
                except Exception as e:
                    logger.warning(f"[polish] 批 {start}-{start+len(batch)} LLM 失败, 整批回退原文: {e}")
            accepted = 0
            for s in batch:
                if not (s.text_original or "").strip():
                    continue  # 原文为空(ASR 空段): 不丢段, 不强行填空
                out = pmap.get(s.id, "")
                if out and semantic_ok(out, s.text_original):
                    s.text_with_punct = out
                    accepted += 1
                else:
                    s.text_with_punct = s.text_original  # 回退 = 零语义改动
            polished += accepted
            logger.info(f"[polish] 批 {start}-{start+len(batch)}/{total}: 接受 {accepted}/{len(inputs)}")
            if progress_cb:
                progress_cb((start + len(batch)) / total)
        return polished

    # ---------- 翻译(EN→ZH) ----------
    async def translate(self, transcript, progress_cb: Optional[Callable[[float], None]] = None) -> int:
        """EN→ZH 翻译, 写 text_translated。ZH 直接跳过。返回写入句数。

        复用经过验证的 translate_segments(1:1 by id, 自然对齐), 再做结构兜底:
        每个 EN segment 必须得到非空 text_translated(已有翻译 > 原文兜底), 绝不空/丢段。
        """
        if transcript.language == "zh":
            return 0
        segments = transcript.segments
        translations = await translate_segments(transcript, progress_cb=progress_cb)
        by_id = {t.get("id"): (t.get("text_zh") or t.get("text_translated") or "").strip()
                 for t in translations}
        translated = 0
        for s in segments:
            zh = by_id.get(s.id, "")
            if zh:
                s.text_translated = zh
                translated += 1
            elif not (s.text_translated or "").strip():
                # 结构兜底: translate_segments 漏掉的段 → 原文兜底, 绝不空
                s.text_translated = s.text_original or ""
        logger.info(f"[translate] 写入 {translated}/{len(segments)} 段 text_translated")
        return translated
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && ./venv/bin/pytest tests/test_subtitle_processor.py -v`
Expected: 5 passed. (Note: requires `pytest-asyncio`; if not installed, see Step 4b.)

- [ ] **Step 4b: Ensure async test support**

Run: `cd backend && ./venv/bin/pip show pytest-asyncio 2>/dev/null | head -1 || ./venv/bin/pip install pytest-asyncio`
If installed, also confirm `pytest.ini` has asyncio mode. If `pytest-asyncio` is missing or tests error with "async def functions are not natively supported", add to `backend/pytest.ini` under `[pytest]`:
```ini
asyncio_mode = auto
```
Re-run: `cd backend && ./venv/bin/pytest tests/test_subtitle_processor.py -v` → 5 passed.

- [ ] **Step 5: Commit**

```bash
cd backend && git add app/services/subtitle_processor.py tests/test_subtitle_processor.py pytest.ini
git -c user.name="Al Li" -c user.email="alli@local" commit -m "feat: SubtitleProcessor.polish with LCS-gated drift fallback"
```

---

### Task 3: SubtitleProcessor.translate (structural no-gap)

**Files:**
- Modify: `backend/tests/test_subtitle_processor.py` (append tests)
- `subtitle_processor.py` translate() already written in Task 2; this task verifies it.

**Interfaces:**
- Consumes: `translate_segments` from `app.llm_pipeline` (mocked in tests).
- Produces: verified `translate()` behavior — every EN segment gets non-empty `text_translated`.

- [ ] **Step 1: Append the failing tests**

Append to `backend/tests/test_subtitle_processor.py`:

```python
@pytest.mark.asyncio
async def test_translate_skips_zh(monkeypatch):
    called = []
    async def fake_translate(transcript, progress_cb=None):
        called.append(1)
        return []
    monkeypatch.setattr("app.services.subtitle_processor.translate_segments", fake_translate)

    t = _transcript("zh", [_seg(0, "中文")])
    n = await SubtitleProcessor().translate(t)
    assert n == 0
    assert called == []  # ZH 不调 translate_segments


@pytest.mark.asyncio
async def test_translate_writes_all_segments(monkeypatch):
    async def fake_translate(transcript, progress_cb=None):
        return [{"id": 0, "text_zh": "这是中文0"}, {"id": 1, "text_zh": "这是中文1"}]
    monkeypatch.setattr("app.services.subtitle_processor.translate_segments", fake_translate)

    t = _transcript("en", [_seg(0, "english zero"), _seg(1, "english one")])
    n = await SubtitleProcessor().translate(t)
    assert n == 2
    assert t.segments[0].text_translated == "这是中文0"
    assert t.segments[1].text_translated == "这是中文1"


@pytest.mark.asyncio
async def test_translate_fills_gaps_with_original(monkeypatch):
    # translate_segments 漏掉 id=1 → 不丢段, 用原文兜底
    async def fake_translate(transcript, progress_cb=None):
        return [{"id": 0, "text_zh": "这是中文0"}]
    monkeypatch.setattr("app.services.subtitle_processor.translate_segments", fake_translate)

    t = _transcript("en", [_seg(0, "english zero"), _seg(1, "english one")])
    n = await SubtitleProcessor().translate(t)
    assert n == 1
    assert t.segments[0].text_translated == "这是中文0"
    assert t.segments[1].text_translated == "english one"  # 原文兜底, 非空
```

- [ ] **Step 2: Run tests to verify they fail (or pass if Task 2 impl already covers)**

Run: `cd backend && ./venv/bin/pytest tests/test_subtitle_processor.py::test_translate_fills_gaps_with_original tests/test_subtitle_processor.py::test_translate_skips_zh -v`
Expected: pass (translate() was implemented in Task 2). If any fail, fix `translate()` in `subtitle_processor.py` to match the spec: ZH skip, write all by id, gap → `text_original` fallback.

- [ ] **Step 3: Run full processor test file**

Run: `cd backend && ./venv/bin/pytest tests/test_subtitle_processor.py -v`
Expected: 8 passed.

- [ ] **Step 4: Commit**

```bash
cd backend && git add tests/test_subtitle_processor.py
git -c user.name="Al Li" -c user.email="alli@local" commit -m "test: SubtitleProcessor.translate no-gap + ZH-skip coverage"
```

---

### Task 4: Pipeline integration + delete legacy code

**Files:**
- Modify: `backend/app/pipeline.py` (stage 2.5 ~line 263-265; stage 5 ~line 290-314; delete helper methods ~line 602-680)
- Delete: `backend/app/services/punctuation_restorer.py`
- Delete: `backend/app/services/subtitle_polisher.py`

**Interfaces:**
- Consumes: `SubtitleProcessor` from Task 2.
- Produces: pipeline stage 2.5 = `processor.polish()`; stage 5 = `processor.translate()`; legacy punctuation code removed.

- [ ] **Step 1: Replace stage 2.5 (polish) in pipeline.py**

In `backend/app/pipeline.py`, find the block (around line 263-265):

```python
        # === 阶段 2.5: 添加标点符号（可选，仅中文ASR字幕）===
        if transcript.language == "zh" and self._needs_punctuation(transcript):
            await self._add_punctuation_to_transcript(episode_id, transcript, on_progress)
```

Replace with:

```python
        # === 阶段 2.5: 字幕润色（双语，加标点+去口水话，时间戳/语义/段数不变）===
        from .services.subtitle_processor import SubtitleProcessor
        await SubtitleProcessor().polish(
            transcript,
            progress_cb=(lambda p: on_progress("polish", p)) if on_progress else None,
        )
```

- [ ] **Step 2: Replace stage 5 (translate) in pipeline.py**

Find the stage-5 block (around line 290-314), from the comment `# === 阶段 5: 翻译（可选）===` through the `_complete_stage(..., "translate", ...)` line. Replace the inner translation+merge logic so the block becomes:

```python
        # === 阶段 5: 翻译（可选，EN→ZH，结构校验+不丢段）===
        # 双语字幕合并后 text_translated 已有中文 → 跳过；英文单语才翻译。
        # 下游 split/summary/highlight/insights 统一用 text_translated 优先。
        _translated_ratio = (
            sum(1 for s in transcript.segments if s.text_translated) /
            max(len(transcript.segments), 1)
        )
        if transcript.language != "zh" and _translated_ratio < 0.5:
            logger.info(f"Translate needed (translated ratio {_translated_ratio:.0%})")
            await self._add_stage(stages, "translate", EpisodeStatus.LLM_RUNNING, sync_stages)
            await SubtitleProcessor().translate(
                transcript,
                progress_cb=lambda p: self._update_stage_progress_sync(stages, "translate", p, episode_id, sync_stages),
            )
            self._checkpoint_json(episode_id, "transcript.json", transcript.model_dump())
            await self._complete_stage(stages, "translate", completed_stages, sync_stages)
```

(Note: `SubtitleProcessor` is already imported at the top of stage 2.5 in the same method scope; the `from .services.subtitle_processor import SubtitleProcessor` above covers both. If the linter complains about re-import, hoist it to the file's top imports instead.)

- [ ] **Step 3: Delete the legacy helper methods**

In `backend/app/pipeline.py`, delete the methods `_needs_punctuation` and `_add_punctuation_to_transcript` (around lines 602-680), including their docstrings. These are now unused.

- [ ] **Step 4: Delete the legacy service files**

```bash
cd backend && git rm app/services/punctuation_restorer.py app/services/subtitle_polisher.py
```

- [ ] **Step 5: Verify no dangling references**

Run:
```bash
cd backend && grep -rn "punctuation_restorer\|_needs_punctuation\|_add_punctuation_to_transcript\|subtitle_polisher\|polish_subtitles\|polish_episode_subtitles" app/ --include="*.py"
```
Expected: no output (no references remain). If any remain (e.g. a one-off script outside `app/`), leave it — only `app/` matters for the running service.

- [ ] **Step 6: Verify import + syntax**

Run: `cd backend && ./venv/bin/python -c "from app.pipeline import PodcastPipeline; from app.services.subtitle_processor import SubtitleProcessor; print('import ok')"`
Expected: `import ok`.

- [ ] **Step 7: Run the full existing test suite (regression)**

Run: `cd backend && ./venv/bin/pytest tests/ -x -q`
Expected: all pass (no regressions from removing legacy code). If a test imported `punctuation_restorer` directly, update or delete that test.

- [ ] **Step 8: Commit**

```bash
cd backend && git add app/pipeline.py
git -c user.name="Al Li" -c user.email="alli@local" commit -m "refactor: wire SubtitleProcessor into pipeline, remove legacy punctuation code"
```

---

### Task 5: Rerun script for the 11 existing episodes

**Files:**
- Create: `backend/rerun_subtitle_processor.py`

**Interfaces:**
- Consumes: `SubtitleProcessor`, `Transcript`, `EpisodeRepository`.

- [ ] **Step 1: Write the rerun script**

Create `backend/rerun_subtitle_processor.py`:

```python
#!/usr/bin/env python3
"""重跑 SubtitleProcessor 修复已有 episode 的 drift + 补翻译。

每个 episode:
1. 加载 transcript.json
2. 快照关键字段 → polish → translate → 断言不可变性
3. 写回 transcript.json + DB
4. 打印覆盖率(text_with_punct / text_translated)

强制覆盖已有 text_with_punct(skip_if_punctuated=False 语义: polish 总是重算并校验)。
"""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from app.services.subtitle_processor import SubtitleProcessor
from app.models import Transcript
from app.database import EpisodeRepository

DATA_DIR = Path(__file__).parent.parent / "data" / "media"
processor = SubtitleProcessor()


def coverage(segments: list) -> dict:
    n = len(segments)
    with_orig = sum(1 for s in segments if (s.text_original or "").strip())
    with_punct = sum(1 for s in segments if (s.text_with_punct or "").strip())
    with_trans = sum(1 for s in segments if (s.text_translated or "").strip())
    return {
        "total": n,
        "text_with_punct": f"{with_punct}/{with_orig}",
        "text_translated": f"{with_trans}/{n}",
    }


async def process_one(ep_dir: Path) -> dict:
    tf = ep_dir / "transcript.json"
    if not tf.exists():
        return {"episode": ep_dir.name, "error": "no transcript.json"}
    data = json.loads(tf.read_text(encoding="utf-8"))
    transcript = Transcript.model_validate(data)

    snap = processor._snapshot(transcript)
    polished = await processor.polish(transcript)
    translated = await processor.translate(transcript)
    processor._assert_immutability(snap, transcript)  # 时间戳/原文/段数未变

    data["segments"] = [s.model_dump() for s in transcript.segments]
    tf.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    await EpisodeRepository.update_transcript(transcript.episode_id, data)

    return {
        "episode": ep_dir.name,
        "language": transcript.language,
        "polished": polished,
        "translated": translated,
        **coverage(transcript.segments),
    }


async def main():
    episodes = sorted(p for p in DATA_DIR.iterdir() if (p / "transcript.json").exists())
    print(f">>> 发现 {len(episodes)} 个 episode")
    results = []
    for ep in episodes:
        print(f">>> 处理 {ep.name} ...", flush=True)
        try:
            r = await process_one(ep)
        except Exception as e:
            r = {"episode": ep.name, "error": str(e)}
            print(f"    ❌ {e}", flush=True)
        print(f"    {r}", flush=True)
        results.append(r)
    print("=== 汇总 ===")
    for r in results:
        print(r)


if __name__ == "__main__":
    logging_setup = __import__("logging")
    logging_setup.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    asyncio.run(main())
```

- [ ] **Step 2: Syntax check**

Run: `cd backend && ./venv/bin/python -c "import ast; ast.parse(open('rerun_subtitle_processor.py').read()); print('syntax ok')"`
Expected: `syntax ok`.

- [ ] **Step 3: Commit**

```bash
cd backend && git add rerun_subtitle_processor.py
git -c user.name="Al Li" -c user.email="alli@local" commit -m "chore: rerun script for SubtitleProcessor over existing episodes"
```

---

### Task 6: End-to-end verification on one real episode

**Files:** none (verification only)

- [ ] **Step 1: Run the rerun script on a single known-drifted episode**

Pick the episode with the most drift (Manus, `ep_*` — identify by listing `data/media`). Run for ONE episode by temporarily restricting the script, or run all and watch the first:

Run (background-safe, log to file):
```bash
cd backend && nohup ./venv/bin/python -u rerun_subtitle_processor.py > /tmp/rerun_subtitle.log 2>&1 &
```

- [ ] **Step 2: Monitor the first episode completes and asserts immutability**

Run (after ~2-3 min):
```bash
sleep 120 && grep -E ">>> 处理|polished|translated|❌|不可变性" /tmp/rerun_subtitle.log | head -20
```
Expected: first episode prints `polished: <N>`, `translated: <N>`, coverage with `text_with_punct` near `total`, and NO `不可变性违反` assertion error.

- [ ] **Step 3: Spot-check a previously-drifted segment is now aligned**

Run (replace EP_ID with the Manus episode id):
```bash
python3 -c "
import json
d = json.load(open('/Users/alli/podcast-digester/backend/../data/media/EP_ID/transcript.json'))
# 找一个之前 drift 的 segment, 比对 text_with_punct 和 text_original 语义一致
for s in d['segments'][40:55]:
    print(s['id'], '|', s.get('text_original')[:30], '=>', (s.get('text_with_punct') or '')[:30])
"
```
Expected: each `text_with_punct` is a punctuated/filler-removed version of the SAME `text_original` (same content), not neighboring content.

- [ ] **Step 4: Verify downstream unaffected — highlight still seeks correctly**

Run:
```bash
python3 -c "
import json, glob
# 任一 episode 的 highlights: start_ms 仍在 segment 时间范围内
for f in glob.glob('/Users/alli/podcast-digester/data/media/*/highlights.json'):
    d = json.load(open(f))
    hs = d.get('highlights') or d.get('items') or []
    if hs:
        print(f, '->', len(hs), 'highlights, sample start_ms =', hs[0].get('start_ms'))
        break
"
```
Expected: highlights file intact, `start_ms` values present (unchanged — we never wrote them).

- [ ] **Step 5: Let the full rerun finish, then summarize**

Run:
```bash
sleep 600 && tail -30 /tmp/rerun_subtitle.log
```
Expected: all 11 episodes processed; each shows non-empty `text_with_punct` coverage; no assertion errors. Report the coverage table to the user.

- [ ] **Step 6: Commit any data + final state**

```bash
cd /Users/alli/podcast-digester && git add data backend/rerun_subtitle_processor.py
git -c user.name="Al Li" -c user.email="alli@local" commit -m "data: rerun SubtitleProcessor over all episodes (drift fixed, timestamps intact)" || echo "no data changes to commit"
```

---

## Self-Review

**1. Spec coverage:**
- §4 data model + immutability contract → Task 1 (`semantic_ok`), Task 2 (`_snapshot`/`_assert_immutability`), asserted in Task 6 Step 2.
- §6 polish path (filler-aware LCS + fallback) → Task 1 (utils) + Task 2 (`polish()`).
- §7 translation path (structural + no-gap) → Task 2 (`translate()`) + Task 3 (tests).
- §9 downstream safety → guaranteed by writing only display fields; verified Task 6 Step 4.
- §10 pipeline integration → Task 4.
- §11 rerun 11 episodes → Task 5 (script) + Task 6 (run).
- §12 error handling (batch fail → fallback, exception path) → Task 2 `polish()` try/except, tested in `test_polish_falls_back_on_llm_exception`.
- §13 testing (semantic_ok metric, structural validation, immutability, drift regression, exception, integration) → Tasks 1-3, 6.
- §14 threshold constants → Task 1 (`LCS_PRESERVE_MIN=0.90`, `LCS_ADD_MAX=0.15`), Task 2 (`POLISH_BATCH_SIZE=15`, `POLISH_MODEL`).

**2. Placeholder scan:** No TBD/TODO; every code step has full code; every command has expected output.

**3. Type consistency:** `SubtitleProcessor().polish(transcript, progress_cb=None) -> int` and `.translate(...) -> int` used identically in Tasks 2, 3, 4, 5. `_snapshot`/`_assert_immutability` consistent across Tasks 2 & 5. `semantic_ok(polished, original)` signature consistent in Task 1 tests and Task 2 impl.

**Deliberate deviation from spec (noted for transparency):** Spec §7 mentioned "translate from polished source (text_with_punct)". This plan keeps translation on `text_original` (reusing `translate_segments`, which is shared by two pipeline paths + legacy). Rationale: changing the translation source would risk the other call sites for marginal gain, and none of the hard requirements (timestamps/semantics/no-loss/downstream) depend on it. The "translate-from-polished" refinement is deferred (YAGNI).
