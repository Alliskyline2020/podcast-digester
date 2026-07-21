"""pipeline 导出方法 _save_audio_to_library 的行为测试。

只测这个薄方法（标题选择 + 非致命），不跑完整 8 阶段管线（那需要 DB/parser/LLM）。
覆盖：中文标题优先、回退原始标题、无标题跳过、源缺失不抛错（保证不拖垮主流程）。
"""
from app import pipeline as pipeline_mod
from app.pipeline import AudioProcessPipeline


async def test_export_picks_chinese_title_when_available(tmp_path, monkeypatch):
    src = tmp_path / "media" / "ep_1" / "audio.m4a"
    src.parent.mkdir(parents=True)
    src.write_bytes(b"data")
    lib = tmp_path / "audio_library"
    monkeypatch.setattr(pipeline_mod.settings, "audio_library_dir", lib)

    pl = AudioProcessPipeline(tmp_path)
    await pl._save_audio_to_library(src, title_zh="中文标题", original_title="English Title")

    assert (lib / "中文标题.m4a").exists()
    assert not (lib / "English Title.m4a").exists()


async def test_export_falls_back_to_original_when_no_zh(tmp_path, monkeypatch):
    src = tmp_path / "a.m4a"
    src.write_bytes(b"data")
    lib = tmp_path / "audio_library"
    monkeypatch.setattr(pipeline_mod.settings, "audio_library_dir", lib)

    pl = AudioProcessPipeline(tmp_path)
    await pl._save_audio_to_library(src, title_zh=None, original_title="English Title")

    assert (lib / "English Title.m4a").exists()


async def test_export_skips_when_both_titles_empty(tmp_path, monkeypatch):
    lib = tmp_path / "audio_library"
    monkeypatch.setattr(pipeline_mod.settings, "audio_library_dir", lib)

    pl = AudioProcessPipeline(tmp_path)
    await pl._save_audio_to_library(tmp_path / "a.m4a", title_zh="", original_title="")

    # 无标题 → 直接跳过，连目录都不应被创建
    assert not lib.exists()


async def test_export_is_non_fatal_when_source_missing(tmp_path, monkeypatch):
    lib = tmp_path / "audio_library"
    monkeypatch.setattr(pipeline_mod.settings, "audio_library_dir", lib)

    pl = AudioProcessPipeline(tmp_path)
    # 源不存在 → 内部抛 FileNotFoundError，方法必须吞掉、不向上抛
    await pl._save_audio_to_library(tmp_path / "missing.m4a", title_zh=None, original_title="T")
