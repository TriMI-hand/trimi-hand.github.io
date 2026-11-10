#!/usr/bin/env python3
"""Prepare the original TRIMI clips as browser-friendly, letterboxed media.

Requires FFmpeg with libx264 and AAC. A portable imageio-ffmpeg installation is
also detected in ../../.media-tools. Originals are read only. Run from anywhere:

    python tools/prepare_media.py --source-root ../../video_assets

Use --only <output-name> to rebuild selected clips and --skip-existing to retain
already prepared outputs. The manifest records source mapping and output timing.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys


SITE_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = SITE_ROOT.parent.parent
CLIPS = [
    {"name": "dexterity/cube-rotate", "source": "dexterity-selected/cube_rotate.MOV"},
    {"name": "dexterity/cut-peel-tape", "source": "dexterity-selected/cut_peel_tape.MOV"},
    {"name": "dexterity/multi-grasp", "source": "dexterity-selected/multi_grasp.MOV"},
    {"name": "dexterity/put-drill-bit", "source": "dexterity-selected/put_drill_bit.mp4"},
    {"name": "dexterity/retain-cup", "source": "dexterity-selected/retain_cup.MOV"},
    {"name": "dexterity/screw-sort", "source": "dexterity-selected/screw_sort.MOV"},
    {"name": "demonstration-pick-place", "source": "policy_and_demonstrations/pick_place_demo.MOV"},
    {"name": "demonstration-unscrew", "source": "policy_and_demonstrations/unscrew_demo.MOV"},
    {"name": "policy-pick-place", "source": "policy_and_demonstrations/IMG_3880.mov"},
    {"name": "policy-unscrew", "source": "policy_and_demonstrations/IMG_3877.mov"},
    {"name": "tpu-hand", "source": "tpu_hand.mov"},
    {"name": "wearability", "source": "wearability_text.mov"},
    {"name": "teleop-cross-hand", "source": "teleop.mov", "start": 0.0, "duration": 3.0},
    {"name": "teleop-midas", "source": "teleop.mov", "start": 3.0},
]


def run(command: list[str], *, check: bool = True) -> subprocess.CompletedProcess:
    result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if check and result.returncode:
        raise RuntimeError(f"Command failed ({result.returncode}): {command!r}\n{result.stderr[-8000:]}")
    return result


def find_ffmpeg(explicit: str | None) -> str:
    choices = [explicit, os.environ.get("FFMPEG_BINARY"), shutil.which("ffmpeg")]
    choices += [str(p) for p in (WORKSPACE / ".media-tools/imageio_ffmpeg/binaries").glob("ffmpeg*.exe")]
    for candidate in choices:
        if candidate and Path(candidate).is_file():
            return str(Path(candidate).resolve())
    raise RuntimeError("FFmpeg not found. Supply --ffmpeg, set FFMPEG_BINARY, or install imageio-ffmpeg.")


def probe(ffmpeg: str, path: Path) -> dict:
    """Read FFmpeg's input metadata without decoding or changing the file."""
    info = run([ffmpeg, "-hide_banner", "-i", str(path)], check=False).stderr
    duration = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", info)
    video = next((line.strip() for line in info.splitlines() if "Video:" in line), "")
    dimensions = re.search(r"(?:,|\s)(\d{2,5})x(\d{2,5})(?:[\s,\[])" , video)
    fps = re.search(r"(\d+(?:\.\d+)?) fps", video)
    result = {
        "duration_seconds": (int(duration[1]) * 3600 + int(duration[2]) * 60 + float(duration[3])) if duration else None,
        "width": int(dimensions[1]) if dimensions else None,
        "height": int(dimensions[2]) if dimensions else None,
        "fps": float(fps[1]) if fps else None,
        "has_audio": bool(re.search(r"Stream .*Audio:", info)),
        "video_stream": video,
        "hdr": "smpte2084" in video or "arib-std-b67" in video,
    }
    if not video:
        raise RuntimeError(f"No video stream found in {path}:\n{info}")
    return result


def faststart(path: Path) -> bool:
    """Check that the top-level moov atom precedes mdat, enabling early play."""
    atoms: dict[bytes, int] = {}
    with path.open("rb") as stream:
        while True:
            offset = stream.tell()
            header = stream.read(8)
            if len(header) != 8:
                break
            length, kind = struct.unpack(">I4s", header)
            if length == 1:
                length = struct.unpack(">Q", stream.read(8))[0]
            if length == 0:
                break
            atoms.setdefault(kind, offset)
            if length < 8:
                break
            stream.seek(offset + length)
    return b"moov" in atoms and b"mdat" in atoms and atoms[b"moov"] < atoms[b"mdat"]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=WORKSPACE / "video_assets")
    parser.add_argument("--output-root", type=Path, default=SITE_ROOT / "public/videos")
    parser.add_argument("--ffmpeg")
    parser.add_argument("--only", action="append", default=[])
    parser.add_argument("--skip-existing", action="store_true")
    parser.add_argument("--crf", type=int, default=22)
    parser.add_argument("--preset", default="fast")
    args = parser.parse_args()
    ffmpeg = find_ffmpeg(args.ffmpeg)
    args.output_root.mkdir(parents=True, exist_ok=True)
    manifest_path = args.output_root / "manifest.json"
    old = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    records = {entry["name"]: entry for entry in old.get("clips", [])}
    version = run([ffmpeg, "-version"]).stdout.splitlines()[0]
    selected = [clip for clip in CLIPS if not args.only or clip["name"] in args.only]
    for clip in selected:
        source = args.source_root / clip["source"]
        if not source.is_file():
            raise FileNotFoundError(source)
        target = args.output_root / (clip["name"] + ".mp4")
        poster = args.output_root / (clip["name"] + ".jpg")
        target.parent.mkdir(parents=True, exist_ok=True)
        if args.skip_existing and target.is_file() and poster.is_file() and clip["name"] in records:
            print(f"Kept {clip['name']}", flush=True)
            continue
        source_info = probe(ffmpeg, source)
        print(f"Preparing {clip['name']} ({source_info['duration_seconds']}s)", flush=True)
        # FFmpeg's default autorotation preserves the displayed source orientation.
        filters = []
        if source_info["hdr"]:
            filters += ["zscale=t=linear:npl=100", "format=gbrpf32le", "tonemap=tonemap=hable:desat=0", "zscale=p=bt709:t=bt709:m=bt709:r=tv"]
        filters += ["scale=1280:720:force_original_aspect_ratio=decrease:force_divisible_by=2", "pad=1280:720:(ow-iw)/2:(oh-ih)/2:color=black", "setsar=1", "fps=30", "format=yuv420p"]
        command = [ffmpeg, "-hide_banner", "-loglevel", "warning", "-nostdin", "-y", "-i", str(source)]
        if clip.get("start", 0):
            command += ["-ss", str(clip["start"])]
        if "duration" in clip:
            command += ["-t", str(clip["duration"])]
        command += ["-map", "0:v:0", "-map", "0:a:0?", "-vf", ",".join(filters), "-c:v", "libx264", "-threads", "4", "-crf", str(args.crf), "-preset", args.preset, "-profile:v", "high", "-level:v", "3.1", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k", "-ac", "2", "-af", "aresample=async=1:first_pts=0", "-movflags", "+faststart", "-map_metadata", "-1", "-metadata:s:v:0", "rotate=0", str(target)]
        run(command)
        output_info = probe(ffmpeg, target)
        poster_time = min(1.0, max(0.0, (output_info["duration_seconds"] or 1) / 4))
        run([ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-y", "-ss", str(poster_time), "-i", str(target), "-frames:v", "1", "-q:v", "3", "-update", "1", str(poster)])
        is_faststart = faststart(target)
        if output_info["width"] != 1280 or output_info["height"] != 720 or "h264" not in output_info["video_stream"] or "yuv420p" not in output_info["video_stream"] or not is_faststart:
            raise RuntimeError(f"Unexpected output format for {target}: {output_info}")
        if clip["name"] == "teleop-cross-hand" and abs(output_info["duration_seconds"] - 3.0) > .001:
            raise RuntimeError("First teleoperation segment must be exactly 3.000 seconds")
        records[clip["name"]] = {
            "name": clip["name"], "source": clip["source"],
            "source_start_seconds": clip.get("start", 0.0),
            "source_end_seconds": (clip.get("start", 0.0) + clip["duration"]) if "duration" in clip else source_info["duration_seconds"],
            "source_duration_seconds": source_info["duration_seconds"],
            "video": clip["name"] + ".mp4", "poster": clip["name"] + ".jpg",
            "duration_seconds": output_info["duration_seconds"],
            "width": output_info["width"], "height": output_info["height"],
            "fps": output_info["fps"], "has_audio": output_info["has_audio"],
            "size_bytes": target.stat().st_size, "poster_size_bytes": poster.stat().st_size,
            "faststart": is_faststart, "hdr_tonemapped": source_info["hdr"],
        }
        manifest = {
            "generated_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
            "ffmpeg_version": version,
            "encoding": {"video": "H.264", "pixel_format": "yuv420p", "audio": "AAC 128 kbps, when present", "frame": "1280x720, contain/letterbox, no crop", "fps": 30, "crf": args.crf, "preset": args.preset, "faststart": True},
            "clips": [records[c["name"]] for c in CLIPS if c["name"] in records],
        }
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        print(f"Prepared {clip['name']}: {target.stat().st_size / 1_000_000:.2f} MB, {output_info['duration_seconds']}s", flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
