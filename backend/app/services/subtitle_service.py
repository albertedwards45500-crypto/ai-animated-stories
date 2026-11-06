# -*- coding: utf-8 -*-
"""字幕服务：SRT/ASS 解析、时间轴校验、SRT 生成。

校验规则（开发文档 10.4.7 / PRD 4.2.6）：
- start < end；
- 时间不超出视频总时长；
- 相邻字幕无不合理重叠；
- 文本须能在原始对白或识别结果中找到依据（Mock/上传场景放宽为非空）。
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from app.core.response import BizError, CODE_BIZ_INVALID


@dataclass
class SubtitleLine:
    """单条字幕。

    Attributes:
        start_ms: 开始时间（毫秒）。
        end_ms: 结束时间（毫秒）。
        text: 字幕文本。
        character_id: 说话人 ID，可为 None。
    """

    start_ms: int
    end_ms: int
    text: str
    character_id: int | None = None


_TIME_RE = re.compile(r"(\d{2}):(\d{2}):(\d{2})[,.](\d{3})")


def parse_timestamp(ts: str) -> int:
    """解析 SRT/ASS 时间戳为毫秒。

    Args:
        ts: 形如 00:00:01,500 的时间戳。

    Returns:
        int: 毫秒值。

    Raises:
        ValueError: 格式非法。
    """
    m = _TIME_RE.fullmatch(ts.strip())
    if not m:
        raise ValueError(f"非法时间戳: {ts}")
    h, mi, s, ms = (int(g) for g in m.groups())
    return ((h * 60 + mi) * 60 + s) * 1000 + ms


def format_timestamp(ms: int) -> str:
    """毫秒格式化为 SRT 时间戳。

    Args:
        ms: 毫秒值。

    Returns:
        str: 形如 00:00:01,500 的字符串。
    """
    h, rem = divmod(max(ms, 0), 3600_000)
    mi, rem = divmod(rem, 60_000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{mi:02d}:{s:02d},{ms:03d}"


def parse_srt(content: str) -> list[SubtitleLine]:
    """解析 SRT 文本为字幕行列表。

    Args:
        content: SRT 文件内容。

    Returns:
        list[SubtitleLine]: 字幕行。

    Raises:
        BizError: 解析失败（40002）。
    """
    lines: list[SubtitleLine] = []
    block: list[str] = []
    for raw in content.replace("\r\n", "\n").split("\n") + [""]:
        if raw.strip() == "":
            if block:
                lines.extend(_parse_srt_block(block))
                block = []
        else:
            block.append(raw)
    if not lines:
        raise BizError(CODE_BIZ_INVALID, "SRT 解析失败：未找到有效字幕")
    return lines


def _parse_srt_block(block: list[str]) -> list[SubtitleLine]:
    """解析单个 SRT 块。

    Args:
        block: 块内文本行（序号、时间行、文本行）。

    Returns:
        list[SubtitleLine]: 该块的字幕行（多行文本合并）。
    """
    time_line_idx = next((i for i, l in enumerate(block) if "-->" in l), None)
    if time_line_idx is None:
        return []
    start_s, _, end_s = block[time_line_idx].partition("-->")
    text = " ".join(l.strip() for l in block[time_line_idx + 1:] if l.strip())
    if not text:
        return []
    return [SubtitleLine(start_ms=parse_timestamp(start_s), end_ms=parse_timestamp(end_s), text=text[:500])]


def validate_subtitles(lines: list[SubtitleLine], total_duration_ms: int | None) -> list[str]:
    """校验字幕时间轴规则。

    Args:
        lines: 字幕行列表。
        total_duration_ms: 视频总时长（毫秒），可为 None（不校验越界）。

    Returns:
        list[str]: 违规描述列表，空列表表示通过。
    """
    issues: list[str] = []
    ordered = sorted(lines, key=lambda l: l.start_ms)
    for i, line in enumerate(ordered):
        if line.start_ms >= line.end_ms:
            issues.append(f"第{i + 1}条字幕开始时间不小于结束时间")
        if total_duration_ms is not None and line.end_ms > total_duration_ms + 1000:
            issues.append(f"第{i + 1}条字幕超出视频总时长")
        if i > 0:
            prev = ordered[i - 1]
            overlap = min(prev.end_ms, line.end_ms) - line.start_ms
            if overlap > 500:  # 重叠超过 0.5s 视为不合理
                issues.append(f"第{i}与第{i + 1}条字幕不合理重叠({overlap}ms)")
    return issues


def build_srt(lines: list[SubtitleLine]) -> str:
    """将字幕行列表生成 SRT 文本。

    Args:
        lines: 字幕行。

    Returns:
        str: 完整 SRT 文件内容。
    """
    parts: list[str] = []
    for i, line in enumerate(lines, start=1):
        parts.append(f"{i}\n{format_timestamp(line.start_ms)} --> {format_timestamp(line.end_ms)}\n{line.text}\n")
    return "\n".join(parts)


def build_mock_subtitles(
    episode_title: str,
    segments: list[tuple],
) -> list[SubtitleLine]:
    """构造 Mock 字幕行（用于 Mock ASR 任务）。

    Args:
        episode_title: 剧集标题（首行字幕，0~2s 片头位置）。
        segments: (start_ms, end_ms, text) 或 (start_ms, end_ms, text, character_id) 序列。

    Returns:
        list[SubtitleLine]: 字幕行列表。

    Note:
            对白字幕与成片时间轴严格对齐，不能为标题行让位；仅当首个
            对白段起点 >= 2000ms（存在片头空间）时才插入标题行，
            否则跳过，避免与首条对白构成不合理重叠（校验阈值 500ms）。
    """
    result: list[SubtitleLine] = []
    first_start = segments[0][0] if segments else None
    if first_start is None or first_start >= 2000:
        result.append(SubtitleLine(start_ms=0, end_ms=2000, text=episode_title[:500]))
    for seg in segments:
        start_ms, end_ms, text = seg[0], seg[1], seg[2]
        character_id = seg[3] if len(seg) > 3 else None
        result.append(SubtitleLine(
            start_ms=start_ms, end_ms=end_ms, text=text[:500], character_id=character_id,
        ))
    return result
