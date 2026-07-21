"""「按标题命名导出音频到音频库」工具与配置的单元测试。

背景：原始音频落在 data/media/<opaque_episode_id>/audio.m4a，用户无法按标题查找。
新功能：下载（含标题翻译）后，把音频副本按标题命名复制到 audio_library_dir。
本文件覆盖文件名安全化、按字节截断、重名加序号、复制语义、以及 config 里的
目录默认值与环境变量覆盖。
"""
import pytest

from app.utils import audio_library


# ---------- sanitize_filename ----------

def test_sanitize_replaces_illegal_chars():
    # 路径分隔符 / 控制字符 / macOS 的 ':' / 通配符等 → '_'
    assert audio_library.sanitize_filename("a/b:c?d*e<f>") == "a_b_c_d_e_f"


def test_sanitize_replaces_backslash():
    assert audio_library.sanitize_filename("a\\b") == "a_b"


def test_sanitize_collapses_whitespace_and_underscore_runs():
    # 空白连续 → 单个空格（保留可读性）；下划线连续 → 单个下划线
    assert audio_library.sanitize_filename("a   b") == "a b"
    assert audio_library.sanitize_filename("a___b") == "a_b"
    assert audio_library.sanitize_filename("a   b___c") == "a b_c"


def test_sanitize_strips_leading_dot_so_file_not_hidden():
    # 前置 '.' 在 unix 上会把文件隐藏，必须去掉
    assert audio_library.sanitize_filename(".Secret") == "Secret"
    assert audio_library.sanitize_filename("  .hidden  ") == "hidden"


def test_sanitize_empty_or_all_illegal_falls_back():
    assert audio_library.sanitize_filename("") == "untitled"
    assert audio_library.sanitize_filename("   ") == "untitled"
    assert audio_library.sanitize_filename("///") == "untitled"


def test_sanitize_truncates_long_cjk_to_byte_budget():
    # 100 个中文字符 = 300 UTF-8 字节，远超文件名字节预算
    long_title = "测" * 100
    result = audio_library.sanitize_filename(long_title)
    # 截断后必须落在字节预算内
    assert len(result.encode("utf-8")) <= audio_library._MAX_BASENAME_BYTES
    # 且不能切碎一个多字节字符（能完整 round-trip 即落在字符边界）
    result.encode("utf-8").decode("utf-8")


def test_sanitize_keeps_normal_title_intact():
    # 普通标题（含中文/数字/空格）应原样保留，空格不被替换成下划线
    assert audio_library.sanitize_filename("第 178 期：聊聊 AI") == "第 178 期：聊聊 AI"


# ---------- resolve_export_path ----------

def test_resolve_export_path_no_collision(tmp_path):
    dest = audio_library.resolve_export_path(tmp_path, "Ep One", "x.m4a")
    assert dest == tmp_path / "Ep One.m4a"


def test_resolve_export_path_preserves_extension(tmp_path):
    assert audio_library.resolve_export_path(tmp_path, "T", "x.mp3") == tmp_path / "T.mp3"
    # 源无扩展名 → 目标也无
    assert audio_library.resolve_export_path(tmp_path, "T", "audio") == tmp_path / "T"


def test_resolve_export_path_collision_appends_number(tmp_path):
    (tmp_path / "Title.m4a").touch()
    dest2 = audio_library.resolve_export_path(tmp_path, "Title", "x.m4a")
    assert dest2 == tmp_path / "Title (2).m4a"

    (tmp_path / "Title (2).m4a").touch()
    dest3 = audio_library.resolve_export_path(tmp_path, "Title", "x.m4a")
    assert dest3 == tmp_path / "Title (3).m4a"


def test_resolve_export_path_sanitizes_title(tmp_path):
    # 标题里的非法字符在拼路径时也要被安全化
    dest = audio_library.resolve_export_path(tmp_path, "a/b:c", "x.m4a")
    assert dest == tmp_path / "a_b_c.m4a"


# ---------- save_audio_to_library ----------

def test_save_audio_copies_content_and_keeps_source(tmp_path):
    src = tmp_path / "media" / "ep_1" / "audio.m4a"
    src.parent.mkdir(parents=True)
    src.write_bytes(b"AUDIOBYTES")
    out = tmp_path / "library"

    dest = audio_library.save_audio_to_library(src, "我的标题", out)

    assert dest == out / "我的标题.m4a"
    assert dest.read_bytes() == b"AUDIOBYTES"
    assert src.exists(), "源文件必须保留（pipeline 转录还要读）"


def test_save_audio_creates_nested_output_dir(tmp_path):
    src = tmp_path / "a.mp3"
    src.write_bytes(b"x")
    out = tmp_path / "deep" / "nested" / "lib"

    dest = audio_library.save_audio_to_library(src, "Title", out)

    assert out.exists()
    assert dest.exists()


def test_save_audio_collision_does_not_overwrite(tmp_path):
    src = tmp_path / "a.m4a"
    src.write_bytes(b"NEW")
    out = tmp_path / "lib"
    out.mkdir()
    (out / "Title.m4a").write_bytes(b"OLD")

    dest = audio_library.save_audio_to_library(src, "Title", out)

    assert dest == out / "Title (2).m4a"
    assert (out / "Title.m4a").read_bytes() == b"OLD", "已存在文件不可被覆盖"
    assert dest.read_bytes() == b"NEW"


def test_save_audio_missing_source_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        audio_library.save_audio_to_library(tmp_path / "nope.m4a", "T", tmp_path)


# ---------- config: audio_library_dir ----------

def test_audio_library_dir_defaults_under_data(monkeypatch):
    monkeypatch.delenv("PODCAST_DIGESTER_AUDIO_OUTPUT_DIR", raising=False)
    from app.config import Settings

    s = Settings()
    assert s.audio_library_dir == s.data_dir / "audio_library"


def test_audio_library_dir_env_override(monkeypatch, tmp_path):
    custom = tmp_path / "mylib"
    monkeypatch.setenv("PODCAST_DIGESTER_AUDIO_OUTPUT_DIR", str(custom))
    from app.config import Settings

    s = Settings()
    assert s.audio_library_dir == custom
