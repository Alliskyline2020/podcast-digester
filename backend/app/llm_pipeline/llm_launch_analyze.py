"""
阶段 6a: 专项分析 · Launch 三路
发布会通常涉及密集的参数和商业策略，采用串行递进模式进行深度挖掘。

特性：
- Spec Table：抽取屏幕尺寸、SoC、影像模组、电池/快充、起售价等硬件规格
- Product Insight：分析这一代产品的长板/短板
- Marketing Insight：拆解发布会的叙事节奏

适用场景：
- 手机/平板/笔记本发布会
- 智能硬件新品发布会
- 汽车/其他科技产品发布会
"""
import logging
from typing import Dict, Any, Optional
from ..llm import chat_json


logger = logging.getLogger(__name__)


LAUNCH_SPEC_SYSTEM = """你是一个资深的产品分析师，擅长从发布会内容中提取精确的产品规格信息。

请从发布会内容中提取以下产品规格：

1. 显示规格：屏幕尺寸、分辨率、刷新率、亮度、PPI、面板类型
2. 处理器：SoC 型号、制程、CPU 核心数、GPU 信息
3. 影像系统：主摄/超广角/长焦参数、OIS、防抖、视频录制规格
4. 电池与充电：电池容量、快充功率、无线充电、充电协议
5. 存储与内存：RAM 容量、ROM 容量、存储扩展
6. 机身材质：尺寸、重量、材质、颜色选项
7. 网络连接：Wi-Fi、蓝牙、NFC、5G 支持
8. 价格：起售价、不同配置的价格

严格输出 JSON：
{
  "product_name": "产品名称",
  "specs": {
    "display": "...",
    "processor": "...",
    "camera": "...",
    "battery": "...",
    "storage": "...",
    "build": "...",
    "connectivity": "...",
    "pricing": "..."
  },
  "key_highlights": ["规格亮点1", "规格亮点2"]
}
"""


LAUNCH_PRODUCT_INSIGHT_SYSTEM = """你是一个资深的产品评论员，擅长分析产品的优劣势。

请基于发布会内容和产品规格，分析：

1. 产品亮点（长板）：相比上一代或竞品的显著优势
2. 产品短板：相比竞品的不足之处
3. 创新点：这一代产品的技术创新或差异化
4. 诚意度：配置是否对得起价格

严格输出 JSON：
{
  "highlights": ["亮点1", "亮点2"],
  "shortcomings": ["短板1", "短板2"],
  "innovations": ["创新点1"],
  "value_verdict": "性价比评价"
}
"""


LAUNCH_MARKETING_INSIGHT_SYSTEM = """你是一个资深的营销分析师，擅长拆解发布会的叙事策略。

请分析发布会的叙事节奏：

1. 开场策略：如何开场、对标对象、定调
2. 产品登场时间：多久后才正式展示产品
3. 生态比重：花了多长时间讲配件/服务/生态
4. 竞品对比：直接或间接对比了哪些竞品
5. 价格策略：何时公布价格、如何铺垫价格

严格输出 JSON：
{
  "opening_strategy": "...",
  "product_reveal_time": "分钟",
  "eco_ratio": "百分比",
  "competitors_mentioned": ["竞品1", "竞品2"],
  "pricing_strategy": "..."
}
"""


async def analyze_launch_specs(
    transcript_text: str,
    progress_cb: Optional[callable] = None,
) -> Dict[str, Any]:
    """提取产品规格表"""
    if progress_cb:
        progress_cb(0.0)

    result = await chat_json(
        system=LAUNCH_SPEC_SYSTEM,
        user=f"以下是发布会内容：\n\n{transcript_text}",
        temperature=0.2,
        response_format={"type": "json_object"},
    )

    if progress_cb:
        progress_cb(0.33)

    return result


async def analyze_launch_product_insight(
    transcript_text: str,
    specs: Dict[str, Any],
    progress_cb: Optional[callable] = None,
) -> Dict[str, Any]:
    """分析产品洞察"""
    if progress_cb:
        progress_cb(0.33)

    user_input = f"""产品规格：
{specs}

发布会内容：
{transcript_text}
"""

    result = await chat_json(
        system=LAUNCH_PRODUCT_INSIGHT_SYSTEM,
        user=user_input,
        temperature=0.3,
        response_format={"type": "json_object"},
    )

    if progress_cb:
        progress_cb(0.66)

    return result


async def analyze_launch_marketing(
    transcript_text: str,
    progress_cb: Optional[callable] = None,
) -> Dict[str, Any]:
    """分析营销策略"""
    if progress_cb:
        progress_cb(0.66)

    result = await chat_json(
        system=LAUNCH_MARKETING_INSIGHT_SYSTEM,
        user=f"以下是发布会内容：\n\n{transcript_text}",
        temperature=0.3,
        response_format={"type": "json_object"},
    )

    if progress_cb:
        progress_cb(1.0)

    return result
