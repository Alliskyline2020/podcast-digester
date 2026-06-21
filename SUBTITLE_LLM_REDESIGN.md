# 🔍 字幕切割逻辑问题分析

## ❌ 当前实现的问题

### 问题 1：机械切割
```python
# 当前代码
max_chars = 500  # 固定字符数限制
min_chars = 200  # 固定最小值

# 按字符数强制切分
would_exceed = len(current_para["text_original"]) + len(seg_text) > self.max_chars
if would_exceed:
    # 强制分段，不管语义是否完整
```

**结果：** 即使语义完整，到 500 字符也会被切碎

### 问题 2：标点符号切分
```python
# 当前代码
# 按句号硬性切分
if char in ['。', '！', '？', '.', '!', '?']:
    sentence_ends.append(i)
```

**问题：**
- 标点符号位置不准确
- 对话、引用中的标点也会触发分段
- 不理解真实语义边界

### 问题 3：没有语义理解
```python
# 当前实现
# 机械规则，完全不理解内容
```

**缺失的能力：**
- ❌ 不知道什么是"话题"
- ❌ 不知道什么是"段落边界"
- ❌ 不知道什么是"重要句子"

---

## 💡 正确的方案：使用 LLM

### 为什么需要 LLM？

**字幕分段是语义任务，不是规则任务：**

| 任务类型 | 适合方法 | 示例 |
|---------|---------|------|
| **规则任务** | 硬编码规则 | 去除 HTML 标签、清理空格 |
| **语义任务** | LLM 理解 | 什么是段落？哪里是边界？ |

**字幕分段需要：**
- ✅ 理解语义：知道什么是完整的一段话
- ✅ 识别话题：知道话题什么时候转变
- ✅ 理解结构：理解引用、对话、说明等结构
- ✅ 判断重要性：知道什么是重点句子

---

## 🎯 重新设计方案

### 方案 A：完全 LLM 化（推荐但成本高）

#### 1. LLM 智能分段

**提示词设计：**
```
你是一个字幕分段专家。请将以下字幕按照语义完整性分成段落。

要求：
1. 每个段落应该表达一个完整的意思
2. 话题转变时应该开始新段落
3. 段落长度建议在 100-300 字之间（可以根据内容调整）
4. 保留说话人信息和重要标记

输入字幕（按时间顺序）：
[00:00] 大家好我是小军...
[00:05] 本集节目我们来到了...
[00:10] 纽约刚刚下了一场大雪...

输出格式：
段落 1 [00:00 - 00:45]：
大家好我是小军。本集节目我们来到了美国纽约。现在正是中国新年。

段落 2 [00:45 - 01:20]：
纽约刚刚下了一场大雪...
```

**代码实现：**
```python
async def segment_with_llm(segments: List[Dict]) -> List[Dict]:
    """
    使用 LLM 智能分段
    """
    # 准备输入
    transcript_text = "\n".join([
        f"[{seg['start_ms']/1000:.2f}] {seg['text_original']}"
        for seg in segments
    ])

    # 调用 LLM
    response = await llm_client.chat.completions.create(
        model="deepseek-chat",
        messages=[
            {"role": "system", "content": SEGMENT_PROMPT},
            {"role": "user", "content": transcript_text}
        ],
        temperature=0.3  # 降低随机性
    )

    # 解析 LLM 输出
    paragraphs = parse_llm_segments(response.choices[0].message.content)

    return paragraphs
```

#### 2. LLM 智能清洗

**提示词设计：**
```
请清洗以下字幕文本，使其更易读：

要求：
1. 移除 HTML 标签和特殊符号
2. 移除无意义的语气词（但保留有意义的语气表达）
3. 保留重要标记（如引用、强调）
4. 修正明显的识别错误
5. 保持原文的语气和风格

原文：
<b>本集节目，我们来到了美国纽约。</b>现在正是中国新年...

清洗后：
本集节目，我们来到了美国纽约。现在正是中国新年...
```

#### 3. LLM 智能提取金句

**提示词设计：**
```
请从以下访谈中提取 3-5 个最有价值的金句。

要求：
1. 金句应该是有洞见的观点、深刻的见解或有趣的细节
2. 避免泛泛而谈的内容
3. 保留说话人的语气和风格
4. 标注金句的重要性和适用场景

输入：[完整字幕文本]

输出格式：
金句 1：
原文：[原文内容]
出处：[说话人和时间]
价值：[为什么重要]
适用人群：[谁会受益]
```

---

### 方案 B：混合方案（平衡成本和质量）

#### 1. 预处理 + LLM 优化

```python
async def hybrid_segment(segments: List[Dict]) -> List[Dict]:
    """
    混合分段方案：规则预处理 + LLM 优化
    """
    # 第一步：规则预处理（粗分段）
    coarse_paragraphs = rule_based_segment(segments, max_chars=800)

    # 第二步：LLM 优化边界
    optimized_paragraphs = []
    for para in coarse_paragraphs:
        # 让 LLM 判断是否需要合并/拆分
        decision = await llm_decide_boundary(para, next_para)

        if decision == "merge":
            optimized_paragraphs[-1].merge(para)
        elif decision == "split":
            sub_paras = await llm_split_paragraph(para)
            optimized_paragraphs.extend(sub_paras)
        else:
            optimized_paragraphs.append(para)

    return optimized_paragraphs
```

#### 2. 增量 LLM 处理

```python
# 只对新内容使用 LLM
if is_new_episode:
    paragraphs = await llm_segment(segments)
else:
    paragraphs = rule_based_segment(segments)
```

---

## 🔍 当前实现检查

### 检查 1：分段参数

```python
# 当前配置
max_chars = 500
min_chars = 200

# 问题：还是固定的字符数限制
```

**证据：** 用户反馈"还是比较碎"说明 500 字符还是不够，或者切分逻辑有问题

### 检查 2：切分逻辑

```python
# 当前代码
would_exceed = len(current_para["text_original"]) + len(seg_text) > self.max_chars
should_split = has_min_content and (
    would_exceed and (len(...) > self.max_chars * 1.2) or
    time_gap > self.merge_threshold
)

# 问题：仍然按字符数判断，不是按语义
```

### 检查 3：句子提取

```python
# 当前代码
for i, char in enumerate(text):
    if char in ['。', '！', '？', '.', '!', '?']:
        sentence_ends.append(i)

# 问题：机械按标点切分，不考虑语义
```

---

## 💡 推荐方案

### 方案 1：Full LLM（最智能，成本较高）

**优势：**
- ✅ 最智能的分段
- ✅ 理解语义和上下文
- ✅ 自动识别话题变化

**劣势：**
- ❌ 成本较高（每次分段都需要 LLM）
- ❌ 速度较慢

**适用场景：** 高价值内容、深度访谈

### 方案 2：Hybrid（推荐）

**流程：**
```
1. 粗分段（规则，800-1000字）
   ↓
2. LLM 判断边界（是否合并/拆分）
   ↓
3. LLM 清洗和优化
   ↓
4. LLM 提取金句（可选）
```

**优势：**
- ✅ 成本可控（只在边界判断时用 LLM）
- ✅ 速度快（大部分用规则）
- ✅ 质量高（LLM 保证语义正确）

**适用场景：** 所有类型内容

### 方案 3：渐进式优化（最稳妥）

**阶段 1：** 立即改进（规则优化）
```python
max_chars = 1000  # 提高到 1000
min_chars = 300
# 先缓解切碎问题
```

**阶段 2：** 添加 LLM 清洗
```python
# 用 LLM 清洗，但规则分段
cleaned_text = await llm_clean(text)
```

**阶段 3：** 添加 LLM 边界判断
```python
# 用 LLM 判断是否需要合并段落
should_merge = await llm_should_merge(para1, para2)
```

**阶段 4：** 完全 LLM 分段
```python
# 最终目标：完全用 LLM
paragraphs = await llm_segment(segments)
```

---

## 🎯 金句提取也应该用 LLM

### 当前问题

**金句提取可能：**
- 基于关键词匹配
- 基于句子长度
- 基于固定规则

**应该：**
- 理解句子价值
- 结合上下文判断
- 识别洞察和见解
- 标注重要性和适用场景

### LLM 金句提取示例

```python
async def extract_insights(transcript: str) -> List[Dict]:
    """
    使用 LLM 提取金句和洞察
    """
    prompt = f"""
请从以下访谈中提取 3-5 个最有价值的金句和洞察。

要求：
1. 金句应该是有洞见的观点、深刻的见解或有趣的细节
2. 避免泛泛而谈的内容
3. 保留说话人的语气和风格
4. 标注金句的重要性和适用场景

访谈内容：
{transcript}

输出格式（JSON）：
{{
  "insights": [
    {{
      "quote": "金句原文",
      "speaker": "说话人",
      "timestamp_ms": 时间戳,
      "importance": "high/medium/low",
      "context": "背景说明",
      "target_audience": "适用人群"
    }}
  ]
}}
"""

    response = await llm_client.chat.completions.create(
        model="deepseek-chat",
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"}
    )

    return json.loads(response.choices[0].message.content)
```

---

## 📊 成本对比

| 方案 | 成本（每1小时节目） | 质量 | 速度 |
|------|---------------------|------|------|
| **规则分段** | ~$0 | 60% | 快 |
| **LLM分段** | ~$0.50 | 95% | 慢 |
| **Hybrid分段** | ~$0.10 | 85% | 中等 |
| **渐进式** | ~$0.05 → $0.50 | 60% → 95% | 快 → 慢 |

---

## 🎯 待确认问题

1. **成本预算**：LLM 调用的成本预算是多少？
2. **实时性要求**：用户能否接受额外的处理时间？
3. **质量优先级**：分段质量的重要性 vs 成本？
4. **实施优先级**：先改进规则，还是直接上 LLM？
