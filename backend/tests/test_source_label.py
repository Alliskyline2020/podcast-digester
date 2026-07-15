"""_source_label_from 的单元测试（来源平台标签推断）。

纯函数，不依赖数据库：直接覆盖各域名分支与 fallback。
重点回归：小宇宙真实主域 xiaoyuzhoufm.com（xiaoyuzhou.com 是别名）。
"""
from app.routers.episodes import _source_label_from


def test_youtube_label():
    assert _source_label_from("https://www.youtube.com/watch?v=abc") == "YouTube"
    assert _source_label_from("https://youtu.be/abc") == "YouTube"


def test_bilibili_label():
    assert _source_label_from("https://www.bilibili.com/video/BV1xx") == "B站"


def test_douyin_label():
    assert _source_label_from("https://www.douyin.com/video/123") == "抖音"


def test_xiaoyuzhou_alias_domain():
    # xiaoyuzhou.com 别名
    assert _source_label_from("https://www.xiaoyuzhou.com/episode/123") == "小宇宙"


def test_xiaoyuzhoufm_real_domain():
    # 小宇宙真实主域 xiaoyuzhoufm.com，单集 id 为 hex
    assert (
        _source_label_from(
            "https://www.xiaoyuzhoufm.com/episode/6a26b614a1049eb63a9b23e2"
        )
        == "小宇宙"
    )


def test_xiaoyuzhoufm_bare_host():
    assert (
        _source_label_from("https://xiaoyuzhoufm.com/episode/abcdef0123456789")
        == "小宇宙"
    )


def test_local_path_label(tmp_path):
    f = tmp_path / "ep.m4a"
    f.write_text("x")
    assert _source_label_from(str(f)) == "本地"
    assert _source_label_from("/tmp/recording.mp3") == "本地"


def test_fallback_to_source_type_db_when_url_unknown():
    # URL 分支匹配不到时，回退到 DB source_type
    assert _source_label_from("https://unknown.example/x", "xiaoyuzhou") == "小宇宙"
    assert _source_label_from("https://unknown.example/x", "xiao_yu_zhou") == "小宇宙"
    assert _source_label_from("https://unknown.example/x", "youtube") == "YouTube"


def test_fm_link_label_independent_of_source_type():
    # 即便 DB 还没写入 source_type，URL 也应能正确识别小宇宙
    assert (
        _source_label_from(
            "https://www.xiaoyuzhoufm.com/episode/6a26b614a1049eb63a9b23e2", None
        )
        == "小宇宙"
    )


def test_empty_input_no_source_type_returns_empty():
    assert _source_label_from("", None) == ""
    assert _source_label_from(None, None) == ""
