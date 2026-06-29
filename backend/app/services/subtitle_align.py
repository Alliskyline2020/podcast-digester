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
    # Collapse multiple spaces to one
    out = re.sub(r" +", " ", out)
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
