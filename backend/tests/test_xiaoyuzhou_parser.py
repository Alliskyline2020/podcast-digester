"""XiaoyuzhouParser.matches() 回归测试。

小宇宙真实域名为 xiaoyuzhoufm.com，episode id 为 24 位十六进制 ObjectId。
旧实现 PATTERNS 只认 xiaoyuzhou.com + 纯数字 id（\\d+），导致真实链接被当作
「不支持的源」拒绝。这里锁定修复后的识别行为。
"""
import pytest

from app.sources.xiaoyuzhou import XiaoyuzhouParser


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "url",
    [
        # 真实域名 + 24 位十六进制 episode id（用户实际碰到的格式）
        "https://www.xiaoyuzhoufm.com/episode/6a5b98a66356eb2d9be4ad2c",
        # 字母开头的十六进制 id：\d+ 会在 episode/ 后第一个字母处匹配失败，
        # 必须用 [a-zA-Z0-9]+ 才能覆盖（ObjectId 一半概率字母开头）
        "https://xiaoyuzhoufm.com/episode/af8d2a1b3c4e5f6a7b8c9d0e",
        # 旧域名 + 纯数字 id（兼容历史链接）
        "https://www.xiaoyuzhou.com/episode/123456",
        "https://podcast.xiaoyuzhou.com/episode/987654",
    ],
)
async def test_matches_accepts_xiaoyuzhou_episode_urls(url):
    parser = XiaoyuzhouParser()
    assert await parser.matches(url) is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "url",
    [
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "https://www.bilibili.com/video/BV1xx411c7mC",
        "https://example.com/episode/6a5b98a66356eb2d9be4ad2c",
        # podcast 合集路径（非单集 /episode/），不应被单集 parser 匹配
        "https://www.xiaoyuzhoufm.com/podcast/6a5b98a66356eb2d9be4ad2c",
    ],
)
async def test_matches_rejects_non_episode_or_other_sites(url):
    parser = XiaoyuzhouParser()
    assert await parser.matches(url) is False
