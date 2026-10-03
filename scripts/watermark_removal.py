"""Remove a fading white corner watermark by temporal background reconstruction.

The implementation is inspired by chainCAI/doubao-video-watermark-removal, but
uses vectorised NumPy operations and deliberately conservative detection.  It
keeps the source file, audio streams and metadata intact and writes a new MP4.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

import numpy as np
from PIL import Image, ImageFilter


ProgressCallback = Callable[[str], None]


class WatermarkRemovalError(RuntimeError):
    """Raised when the input cannot be processed safely."""


class WatermarkNotFound(WatermarkRemovalError):
    """Raised when conservative detection finds no suitable watermark."""


@dataclass(frozen=True)
class VideoInfo:
    width: int
    height: int
    fps: float
    frame_rate: str
    frame_count: int


@dataclass
class WatermarkRegion:
    box: tuple[int, int, int, int]
    background: np.ndarray
    hard_mask: np.ndarray
    soft_mask: np.ndarray
    activity: np.ndarray


@dataclass(frozen=True)
class RemovalResult:
    output: Path
    frame_count: int
    regions: tuple[tuple[int, int, int, int], ...]


def _run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, check=True, text=True, **kwargs)


def probe_video(video: Path) -> VideoInfo:
    if not video.is_file():
        raise WatermarkRemovalError(f"输入视频不存在：{video}")
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        raise WatermarkRemovalError("需要先安装 ffmpeg，并确保 ffmpeg/ffprobe 位于 PATH")

    result = _run(
        [
            "ffprobe", "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=width,height,avg_frame_rate,nb_frames",
            "-of", "json", str(video),
        ],
        capture_output=True,
    )
    streams = json.loads(result.stdout).get("streams", [])
    if not streams:
        raise WatermarkRemovalError("输入文件没有视频流")
    stream = streams[0]
    frame_rate = str(stream.get("avg_frame_rate") or "24/1")
    numerator, denominator = (int(value) for value in frame_rate.split("/"))
    fps = numerator / denominator if denominator else 24.0
    return VideoInfo(
        width=int(stream["width"]),
        height=int(stream["height"]),
        fps=fps,
        frame_rate=frame_rate,
        frame_count=int(stream.get("nb_frames") or 0),
    )


def _corner_boxes(info: VideoInfo) -> list[tuple[int, int, int, int]]:
    scan_width = min(220, max(96, round(info.width * 0.18)))
    scan_height = min(120, max(64, round(info.height * 0.14)))
    return [
        (0, 0, scan_width, scan_height),
        (info.width - scan_width, 0, info.width, scan_height),
        (0, info.height - scan_height, scan_width, info.height),
        (info.width - scan_width, info.height - scan_height, info.width, info.height),
    ]


def _read_exact(stream: object, size: int) -> bytes:
    chunks: list[bytes] = []
    remaining = size
    while remaining:
        chunk = stream.read(remaining)  # type: ignore[attr-defined]
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def _decode_analysis_frames(
    video: Path,
    info: VideoInfo,
    boxes: list[tuple[int, int, int, int]],
) -> tuple[list[np.ndarray], int]:
    command = [
        "ffmpeg", "-v", "error", "-i", str(video),
        "-map", "0:v:0", "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1",
    ]
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    assert process.stdout is not None
    frame_size = info.width * info.height * 3
    collected: list[list[np.ndarray]] = [[] for _ in boxes]
    count = 0
    while True:
        raw = _read_exact(process.stdout, frame_size)
        if not raw:
            break
        if len(raw) != frame_size:
            process.kill()
            raise WatermarkRemovalError("ffmpeg 返回了不完整的视频帧")
        frame = np.frombuffer(raw, dtype=np.uint8).reshape(info.height, info.width, 3)
        for index, (x0, y0, x1, y1) in enumerate(boxes):
            collected[index].append(frame[y0:y1, x0:x1].copy())
        count += 1
    stderr = process.stderr.read().decode(errors="replace") if process.stderr else ""
    if process.wait() != 0:
        raise WatermarkRemovalError(f"视频解码失败：{stderr.strip()}")
    if count < 2:
        raise WatermarkRemovalError("视频帧数不足，无法做时间域分析")
    return [np.stack(frames) for frames in collected], count


def _luma(rgb: np.ndarray) -> np.ndarray:
    values = rgb.astype(np.float32)
    return values[..., 0] * 0.299 + values[..., 1] * 0.587 + values[..., 2] * 0.114


def _components(mask: np.ndarray) -> Iterable[tuple[np.ndarray, tuple[int, int, int, int]]]:
    height, width = mask.shape
    visited = np.zeros_like(mask, dtype=bool)
    for start_y, start_x in zip(*np.nonzero(mask & ~visited)):
        if visited[start_y, start_x]:
            continue
        queue = deque([(int(start_x), int(start_y))])
        visited[start_y, start_x] = True
        points: list[tuple[int, int]] = []
        while queue:
            x, y = queue.popleft()
            points.append((x, y))
            for ny in range(max(0, y - 1), min(height, y + 2)):
                for nx in range(max(0, x - 1), min(width, x + 2)):
                    if mask[ny, nx] and not visited[ny, nx]:
                        visited[ny, nx] = True
                        queue.append((nx, ny))
        component = np.asarray(points, dtype=np.int32)
        xs, ys = component[:, 0], component[:, 1]
        yield component, (int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1)


def _analyse_box(
    frames: np.ndarray,
    origin: tuple[int, int],
) -> list[WatermarkRegion]:
    luminance = _luma(frames)
    low_luma = np.percentile(luminance, 10, axis=0)
    high_luma = np.percentile(luminance, 90, axis=0)
    low_rgb = np.percentile(frames, 10, axis=0).astype(np.uint8)
    delta = luminance - low_luma[None, ...]
    channel_spread = frames.max(axis=-1).astype(np.int16) - frames.min(axis=-1).astype(np.int16)

    # An OriginalDoubao mark is neutral white, repeatedly brightens the same pixels and
    # spends a meaningful part of the timeline visible.  The occupancy test is
    # what rejects short-lived white stars and moving UI edges in the samples.
    neutral_bright = (
        (delta > 28)
        & (luminance > 115)
        & (channel_spread < 38)
    )
    occupancy = neutral_bright.mean(axis=0)
    candidate = (
        ((high_luma - low_luma) > 36)
        & (high_luma > 135)
        & (low_luma < 185)
        & (occupancy > 0.16)
    )

    # Join strokes belonging to adjacent characters for component filtering.
    joined = np.asarray(
        Image.fromarray(candidate.astype(np.uint8) * 255)
        .filter(ImageFilter.MaxFilter(7))
        .filter(ImageFilter.MinFilter(3))
    ) > 0

    regions: list[WatermarkRegion] = []
    for component, box in _components(joined):
        x0, y0, x1, y1 = box
        width, height = x1 - x0, y1 - y0
        area = len(component)
        if area < 45 or not (22 <= width <= 170 and 7 <= height <= 55):
            continue
        if not (1.25 <= width / max(height, 1) <= 10.0):
            continue

        margin = 4
        x0, y0 = max(0, x0 - margin), max(0, y0 - margin)
        x1, y1 = min(candidate.shape[1], x1 + margin), min(candidate.shape[0], y1 + margin)
        hard = candidate[y0:y1, x0:x1]
        if hard.sum() < 18:
            continue
        hard = np.asarray(
            Image.fromarray(hard.astype(np.uint8) * 255).filter(ImageFilter.MaxFilter(5))
        ) > 0
        soft = np.asarray(
            Image.fromarray(hard.astype(np.uint8) * 255).filter(ImageFilter.GaussianBlur(1.35)),
            dtype=np.float32,
        ) / 255.0

        zone_luma = luminance[:, y0:y1, x0:x1]
        zone_low = low_luma[y0:y1, x0:x1]
        activity = np.median((zone_luma - zone_low[None, ...])[:, hard], axis=1)
        floor = float(np.percentile(activity, 15))
        peak = float(np.percentile(activity, 90))
        if peak - floor < 12:
            continue
        activity = np.clip((activity - floor - 2) / max(peak - floor - 2, 1), 0, 1).astype(np.float32)
        if np.count_nonzero(activity > 0.25) < max(3, round(len(activity) * 0.08)):
            continue

        ox, oy = origin
        regions.append(
            WatermarkRegion(
                box=(ox + x0, oy + y0, ox + x1, oy + y1),
                background=low_rgb[y0:y1, x0:x1],
                hard_mask=hard,
                soft_mask=soft,
                activity=activity,
            )
        )
    return regions


def detect_watermarks(video: Path, info: VideoInfo | None = None) -> tuple[list[WatermarkRegion], int]:
    info = info or probe_video(video)
    boxes = _corner_boxes(info)
    frame_sets, decoded_count = _decode_analysis_frames(video, info, boxes)
    regions: list[WatermarkRegion] = []
    edge_slack = max(32, round(min(info.width, info.height) * 0.065))
    for corner, (box, frames) in enumerate(zip(boxes, frame_sets)):
        candidates = _analyse_box(frames, (box[0], box[1]))
        anchored_candidates: list[WatermarkRegion] = []
        for region in candidates:
            x0, y0, x1, y1 = region.box
            anchored = (
                (corner == 0 and x0 <= edge_slack and y0 <= edge_slack)
                or (corner == 1 and x1 >= info.width - edge_slack and y0 <= edge_slack)
                or (corner == 2 and x0 <= edge_slack and y1 >= info.height - edge_slack)
                or (
                    corner == 3
                    and x1 >= info.width - edge_slack
                    and y1 >= info.height - edge_slack
                )
            )
            if anchored:
                anchored_candidates.append(region)

        # A text mark is often split into two components by the scene behind
        # it.  Retain neighbouring components when at least one reaches the
        # expected corner anchor; isolated interior components stay rejected.
        for region in candidates:
            x0, y0, x1, y1 = region.box
            nearby = any(
                max(x0, anchor.box[0]) <= min(x1, anchor.box[2]) + 12
                and max(y0, anchor.box[1]) <= min(y1, anchor.box[3]) + 12
                for anchor in anchored_candidates
            )
            if nearby:
                regions.append(region)

    masked_pixels = sum(int(region.hard_mask.sum()) for region in regions)
    if masked_pixels > info.width * info.height * 0.012:
        raise WatermarkRemovalError("自动检测范围异常偏大，已拒绝处理以保护原画面")
    return regions, decoded_count


def _encode_clean_video(
    video: Path,
    output: Path,
    info: VideoInfo,
    regions: list[WatermarkRegion],
    frame_count: int,
    progress: ProgressCallback,
) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    partial = output.with_name(output.stem + ".processing" + output.suffix)
    decoder = subprocess.Popen(
        [
            "ffmpeg", "-v", "error", "-i", str(video), "-map", "0:v:0",
            "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    encoder = subprocess.Popen(
        [
            "ffmpeg", "-y", "-v", "error",
            "-f", "rawvideo", "-pix_fmt", "rgb24",
            "-video_size", f"{info.width}x{info.height}",
            "-framerate", info.frame_rate, "-i", "pipe:0", "-i", str(video),
            "-map", "0:v:0", "-map", "1:a?", "-map_metadata", "1",
            "-c:v", "libx264", "-preset", "medium", "-crf", "20",
            "-pix_fmt", "yuv420p", "-c:a", "copy", "-movflags", "+faststart",
            str(partial),
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    assert decoder.stdout is not None and encoder.stdin is not None
    frame_size = info.width * info.height * 3
    processed = 0
    try:
        while True:
            raw = _read_exact(decoder.stdout, frame_size)
            if not raw:
                break
            if len(raw) != frame_size:
                raise WatermarkRemovalError("重建阶段收到不完整的视频帧")
            frame = np.frombuffer(raw, dtype=np.uint8).reshape(info.height, info.width, 3).copy()
            for region in regions:
                if processed >= len(region.activity) or region.activity[processed] <= 0.02:
                    continue
                x0, y0, x1, y1 = region.box
                crop_u8 = frame[y0:y1, x0:x1]
                alpha = region.soft_mask[..., None] * float(region.activity[processed])
                restored = crop_u8.astype(np.float32) + (
                    region.background.astype(np.float32) - crop_u8.astype(np.float32)
                ) * alpha
                frame[y0:y1, x0:x1] = np.clip(restored, 0, 255).astype(np.uint8)
            encoder.stdin.write(frame.tobytes())
            processed += 1
            if processed % 48 == 0:
                progress(f"正在重建水印区域：{processed}/{frame_count} 帧")
        encoder.stdin.close()
        decoder_error = decoder.stderr.read().decode(errors="replace") if decoder.stderr else ""
        decoder_code = decoder.wait()
        encoder_error = encoder.stderr.read().decode(errors="replace") if encoder.stderr else ""
        encoder_code = encoder.wait()
        if decoder_code or encoder_code:
            raise WatermarkRemovalError(
                "ffmpeg 重建失败：" + (decoder_error or encoder_error).strip()
            )
        partial.replace(output)
    except Exception:
        decoder.kill()
        encoder.kill()
        partial.unlink(missing_ok=True)
        raise


def remove_watermark(
    input_path: str | Path,
    output_path: str | Path | None = None,
    progress: ProgressCallback | None = None,
) -> RemovalResult:
    video = Path(input_path).resolve()
    output = (
        Path(output_path).resolve()
        if output_path is not None
        else video.with_name(video.stem + "_去水印" + video.suffix)
    )
    if output == video:
        raise WatermarkRemovalError("输出路径不能覆盖输入视频")
    notify = progress or (lambda message: print(message, flush=True))
    info = probe_video(video)
    notify(f"分析视频：{info.width}x{info.height} @ {info.fps:.2f} fps")
    regions, frame_count = detect_watermarks(video, info)
    if not regions:
        raise WatermarkNotFound("未检测到符合特征的动态白色角落水印")
    notify("检测区域：" + ", ".join(str(region.box) for region in regions))
    _encode_clean_video(video, output, info, regions, frame_count, notify)
    notify(f"处理完成：{output}")
    return RemovalResult(output, frame_count, tuple(region.box for region in regions))


def remove_with_delogo(
    input_path: str | Path,
    zones: Iterable[tuple[int, int, int, int]],
    output_path: str | Path | None = None,
    progress: ProgressCallback | None = None,
) -> RemovalResult:
    """Remove constant marks with ffmpeg's spatial interpolation filter.

    ``zones`` use ``x,y,width,height`` coordinates.  This is intentionally a
    manual fallback: applying delogo to an incorrectly detected area can blur
    real content, so the application never guesses these rectangles.
    """

    video = Path(input_path).resolve()
    output = (
        Path(output_path).resolve()
        if output_path is not None
        else video.with_name(video.stem + "_去水印" + video.suffix)
    )
    if output == video:
        raise WatermarkRemovalError("输出路径不能覆盖输入视频")
    info = probe_video(video)
    checked: list[tuple[int, int, int, int]] = []
    for x, y, width, height in zones:
        if width < 8 or height < 8:
            raise WatermarkRemovalError("delogo 区域宽高不能小于 8 像素")
        if x < 0 or y < 0 or x + width > info.width or y + height > info.height:
            raise WatermarkRemovalError(
                f"delogo 区域 {(x, y, width, height)} 超出 {info.width}x{info.height} 画面"
            )
        checked.append((x, y, width, height))
    if not checked:
        raise WatermarkRemovalError("delogo 模式至少需要一个 -z 区域")

    notify = progress or (lambda message: print(message, flush=True))
    output.parent.mkdir(parents=True, exist_ok=True)
    partial = output.with_name(output.stem + ".processing" + output.suffix)
    filters = ",".join(
        f"delogo=x={x}:y={y}:w={width}:h={height}:show=0"
        for x, y, width, height in checked
    )
    notify("delogo 区域：" + ", ".join(str(zone) for zone in checked))
    try:
        _run(
            [
                "ffmpeg", "-y", "-v", "error", "-i", str(video),
                "-vf", filters, "-map_metadata", "0", "-map", "0:v:0", "-map", "0:a?",
                "-c:v", "libx264", "-preset", "medium", "-crf", "20",
                "-pix_fmt", "yuv420p", "-c:a", "copy", "-movflags", "+faststart",
                str(partial),
            ],
            capture_output=True,
        )
        partial.replace(output)
    except Exception:
        partial.unlink(missing_ok=True)
        raise
    notify(f"处理完成：{output}")
    return RemovalResult(output, info.frame_count, tuple(checked))


def main() -> int:
    parser = argparse.ArgumentParser(description="时间域背景重建去除 OriginalDoubao 动态角落水印")
    parser.add_argument("input", type=Path, help="输入 MP4")
    parser.add_argument("output", nargs="?", type=Path, help="输出 MP4")
    parser.add_argument(
        "--method", choices=("temporal", "delogo"), default="temporal",
        help="temporal 适合会完全淡出的水印；delogo 适合常驻水印",
    )
    parser.add_argument(
        "-z", "--zone", action="append", default=[], metavar="X,Y,W,H",
        help="delogo 矩形，可重复指定",
    )
    parser.add_argument("--detect-only", action="store_true", help="只打印检测区域，不生成视频")
    args = parser.parse_args()
    try:
        if args.detect_only:
            info = probe_video(args.input.resolve())
            regions, frame_count = detect_watermarks(args.input.resolve(), info)
            print(json.dumps({"frames": frame_count, "regions": [r.box for r in regions]}, ensure_ascii=False))
            return 0 if regions else 2
        if args.method == "delogo":
            zones = [tuple(int(value) for value in zone.split(",")) for zone in args.zone]
            if any(len(zone) != 4 for zone in zones):
                raise WatermarkRemovalError("-z 格式应为 x,y,width,height")
            remove_with_delogo(args.input, zones, args.output)  # type: ignore[arg-type]
        else:
            remove_watermark(args.input, args.output)
        return 0
    except WatermarkNotFound as exc:
        print(f"未处理：{exc}", file=sys.stderr)
        return 2
    except (WatermarkRemovalError, subprocess.CalledProcessError) as exc:
        print(f"处理失败：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
