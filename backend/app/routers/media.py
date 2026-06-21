"""Media router: audio file serving with HTTP Range support.

Routes:
- GET /media/{episode_id}/audio.{ext}   流式音频，支持 Range 请求

Range 支持是音频 seek 的硬需求，浏览器 <audio> 元素依赖它做拖动播放。
"""
from pathlib import Path
from typing import Optional, Tuple

from fastapi import APIRouter, HTTPException, Request, Response

from ..deps import data_dir


router = APIRouter()


def _parse_range_header(range_header: str, file_size: int) -> Optional[Tuple[int, int]]:
    """解析 Range 头，返回 (start, end) 或 None"""
    if not range_header.startswith("bytes="):
        return None

    range_spec = range_header[6:]  # 移除 "bytes=" 前缀

    try:
        # 支持 "bytes=start-end" 格式
        if "-" in range_spec:
            start_str, end_str = range_spec.split("-", 1)

            if start_str and end_str:
                # bytes=start-end
                start = int(start_str)
                end = int(end_str)
            elif start_str:
                # bytes=start- (从 start 到文件末尾)
                start = int(start_str)
                end = file_size - 1
            elif end_str:
                # bytes=-suffix (最后 suffix 字节)
                suffix = int(end_str)
                start = max(0, file_size - suffix)
                end = file_size - 1
            else:
                return None

            # 验证范围
            if start < 0 or end >= file_size or start > end:
                return None

            return (start, end)
    except (ValueError, IndexError):
        return None

    return None


async def serve_audio_with_range(file_path: Path, request: Request) -> Response:
    """
    提供音频文件，支持 HTTP Range 请求

    这是专用于音频文件的服务函数，支持 Range 请求以便浏览器进行 seek 操作
    """
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="音频文件不存在")

    file_size = file_path.stat().st_size
    range_header = request.headers.get("range")

    # 根据 Content-Type 映射
    content_type_map = {
        ".m4a": "audio/mp4a-latm",
        ".mp3": "audio/mpeg",
        ".mp4": "audio/mp4",
        ".webm": "audio/webm",
        ".opus": "audio/opus",
        ".wav": "audio/wav",
    }
    ext = file_path.suffix.lower()
    content_type = content_type_map.get(ext, "audio/m4a")

    if range_header:
        parsed_range = _parse_range_header(range_header, file_size)

        if parsed_range:
            start, end = parsed_range
            content_length = end - start + 1

            # 读取指定范围的数据
            with open(file_path, "rb") as f:
                f.seek(start)
                chunk = f.read(content_length)

            return Response(
                content=chunk,
                status_code=206,  # Partial Content
                headers={
                    "Content-Type": content_type,
                    "Content-Length": str(content_length),
                    "Content-Range": f"bytes {start}-{end}/{file_size}",
                    "Accept-Ranges": "bytes",
                    "Cache-Control": "public, max-age=86400",
                },
            )

    # 不支持 Range 或 Range 解析失败，返回整个文件
    # 对于大文件，使用流式传输
    async def file_iterator():
        with open(file_path, "rb") as f:
            while chunk := f.read(8192):
                yield chunk

    return Response(
        content=file_iterator(),
        status_code=200,
        headers={
            "Content-Type": content_type,
            "Content-Length": str(file_size),
            "Accept-Ranges": "bytes",
            "Cache-Control": "public, max-age=86400",
        },
    )


@router.get("/media/{episode_id}/audio.m4a")
@router.get("/media/{episode_id}/audio.mp3")
@router.get("/media/{episode_id}/audio.mp4")
@router.get("/media/{episode_id}/audio.webm")
@router.get("/media/{episode_id}/audio.opus")
@router.get("/media/{episode_id}/audio.wav")
async def serve_audio_file(episode_id: str, request: Request) -> Response:
    """
    提供音频文件，支持 HTTP Range 请求

    支持格式: m4a, mp3, mp4, webm, opus, wav
    浏览器使用 Range 请求进行音频 seek
    """
    media_dir = data_dir / "media" / episode_id

    # 尝试不同的音频格式
    audio_file = None
    for ext in [".m4a", ".mp3", ".mp4", ".webm", ".opus", ".wav"]:
        potential_file = media_dir / f"audio{ext}"
        if potential_file.exists():
            audio_file = potential_file
            break

    if not audio_file:
        raise HTTPException(status_code=404, detail="音频文件不存在")

    return await serve_audio_with_range(audio_file, request)
