#!/usr/bin/env python3
"""The one mix output: voice (+ optional ducked music + restrained local SFX) -> delivery loudness.

Guardrails for --sfx (when not bypassed via --no-sfx or --dry):
  1. Trigger whitelist: only `chapter`, `reveal`, `turn` are permitted.
  2. Density ceiling: average at least 15s between SFX triggers (`max_allowed = max(1, int(dur // 15))`
     and min 3.0s between any two adjacent triggers); denser inputs are rejected (exit 1).
  3. Level discipline: --sfx-under-db MUST stay within [18.0, 22.0] dB below target voice LUFS (default 20.0).
  4. One-flag bypass: `--no-sfx`, `--raw-voice`, or `--dry` cleanly bypasses SFX / voice processing.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import struct
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILL_ROOT = HERE.parent
SFX_DIR = SKILL_ROOT / "assets" / "sfx"
SFX_MANIFEST = SFX_DIR / "manifest.json"
ALLOWED_SFX_KINDS = ("chapter", "reveal", "turn")
MIN_AVG_INTERVAL_S = 15.0
MIN_GAP_S = 3.0


def run(cmd: list[str]) -> subprocess.CompletedProcess:
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        lines = (r.stderr or r.stdout or "").strip().splitlines()
        detail = lines[-1][:240] if lines else f"exit {r.returncode}"
        sys.exit(f"ffmpeg 失败：{detail}")
    return r


def lufs(path: Path) -> float:
    r = run(["ffmpeg", "-hide_banner", "-i", str(path), "-af", "loudnorm=print_format=json",
             "-f", "null", "-"])
    m = re.search(r'\{[^{}]*"input_i"[^{}]*\}', r.stderr, re.S)
    if not m:
        sys.exit(f"量不到响度：{path}")
    return float(json.loads(m.group(0))["input_i"])


def probe_duration(path: Path) -> float:
    out = run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
               "-of", "csv=p=0", str(path)]).stdout.strip()
    return float(out)


def load_sfx_catalog() -> list[dict]:
    if not SFX_MANIFEST.is_file():
        return []
    doc = json.loads(SFX_MANIFEST.read_text(encoding="utf-8"))
    items = doc.get("items") or []
    out = []
    for item in items:
        entry = dict(item)
        entry["path"] = str((SFX_DIR / item["file"]).resolve())
        out.append(entry)
    return out


def measure_clip_rms_and_peak(path: Path) -> tuple[float, float]:
    """Measure active RMS and peak dBFS; works even for very short (<0.4s) SFX WAVs."""
    if path.suffix.lower() == ".wav":
        try:
            with wave.open(str(path), "rb") as wf:
                if wf.getsampwidth() == 2:
                    raw = wf.readframes(wf.getnframes())
                    if raw:
                        vals = struct.unpack(f"<{len(raw) // 2}h", raw)
                        active = [v / 32768.0 for v in vals]
                        # Compute active RMS over samples above 1% of peak to avoid edge fade dilution
                        peak = max(abs(x) for x in active) or 1e-9
                        loud_samples = [x for x in active if abs(x) >= peak * 0.1] or active
                        rms = math.sqrt(sum(x * x for x in loud_samples) / len(loud_samples)) or 1e-9
                        return 20.0 * math.log10(rms), 20.0 * math.log10(peak)
        except Exception:
            pass
    r = run(["ffmpeg", "-hide_banner", "-i", str(path), "-af", "volumedetect", "-f", "null", "-"])
    m_mean = re.search(r"mean_volume:\s*(-?[\d.]+)\s+dB", r.stderr)
    m_max = re.search(r"max_volume:\s*(-?[\d.]+)\s+dB", r.stderr)
    mean_v = float(m_mean.group(1)) if m_mean else -24.0
    max_v = float(m_max.group(1)) if m_max else -12.0
    return mean_v, max_v


def resolve_sfx_sound(sound: str, plan_dir: Path, catalog: dict[str, dict]) -> Path:
    if sound in catalog:
        p = Path(catalog[sound]["path"])
        if p.is_file():
            return p
    by_rel = SFX_DIR / sound
    if by_rel.is_file():
        return by_rel.resolve()
    p = Path(sound).expanduser()
    if not p.is_absolute():
        p = plan_dir / p
    if p.is_file():
        return p.resolve()
    sys.exit(f"找不到音效文件：{sound}")


def validate_sfx_plan(sfx_path: Path, dur: float, sfx_under_db: float) -> list[dict]:
    if not sfx_path.is_file():
        sys.exit(f"找不到音效计划：{sfx_path}")
    if not (18.0 <= sfx_under_db <= 22.0):
        sys.exit(f"--sfx-under-db 必须在 18–22 dB 之间（当前 {sfx_under_db} dB），避免抢夺人声或不可闻")
    try:
        raw = json.loads(sfx_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        sys.exit(f"音效计划 JSON 无效（{sfx_path}）：{exc}")
    events = raw.get("events") if isinstance(raw, dict) else raw
    if not isinstance(events, list):
        sys.exit("音效计划必须是事件数组或包含 events 数组的对象")
    if not events:
        return []

    catalog = {item["id"]: item for item in load_sfx_catalog()}
    cleaned = []
    for i, ev in enumerate(events):
        if not isinstance(ev, dict):
            sys.exit(f"sfx[{i}] 必须是对象")
        kind = str(ev.get("kind") or "").strip()
        if kind not in ALLOWED_SFX_KINDS:
            sys.exit(f"sfx[{i}] kind={kind!r} 不在允许列表 {ALLOWED_SFX_KINDS}")
        try:
            t = float(ev["t"])
        except (KeyError, TypeError, ValueError):
            sys.exit(f"sfx[{i}] 缺少合法时间戳 t")
        if t < 0.0 or t > dur:
            sys.exit(f"sfx[{i}] t={t:.2f}s 超出音频范围 [0, {dur:.2f}s]")
        sound = str(ev.get("sound") or "").strip()
        if not sound:
            default_for_kind = next((item["id"] for item in catalog.values() if item["kind"] == kind), None)
            if not default_for_kind:
                sys.exit(f"sfx[{i}] 缺少 sound 且内置目录无 {kind} 默认音效")
            sound = default_for_kind
        resolved = resolve_sfx_sound(sound, sfx_path.parent, catalog)
        cleaned.append({"t": t, "kind": kind, "sound": sound, "path": resolved})

    cleaned.sort(key=lambda e: e["t"])
    n = len(cleaned)
    max_allowed = max(1, int(dur // MIN_AVG_INTERVAL_S))
    if n > max_allowed or (n > 1 and (dur / n) < MIN_AVG_INTERVAL_S):
        sys.exit(
            f"音效密度过高：{dur:.1f}s 内请求 {n} 次（平均 {dur / n:.1f}s/次）；"
            f"硬限制全片平均每 {int(MIN_AVG_INTERVAL_S)}–25s 最多 1 次（上限 {max_allowed} 次）"
        )
    for prev, nxt in zip(cleaned, cleaned[1:]):
        if nxt["t"] - prev["t"] < MIN_GAP_S:
            sys.exit(
                f"相邻音效过近（{prev['t']:.2f}s 与 {nxt['t']:.2f}s 相距 < {MIN_GAP_S:.1f}s）"
            )
    return cleaned


def main() -> int:
    ap = argparse.ArgumentParser(description="single mix: voice (+music + restrained local SFX) -> delivery loudness")
    ap.add_argument("voice", nargs="?", type=Path, default=None)
    ap.add_argument("-o", "--output", type=Path, default=None)
    ap.add_argument("--bgm", type=Path, default=None)
    ap.add_argument("--bgm-lufs", type=float, default=-32.0)
    ap.add_argument("--target-lufs", type=float, default=-14.0)
    ap.add_argument("--tail", type=float, default=0.0, help="seconds of BGM tail after voice")
    ap.add_argument("--voice-preset", choices=("none", "podcast-warm", "raw"), default="none",
                    help="Optional voice preset applied before mix (use 'none' if voice is pre-fixed)")
    ap.add_argument("--raw-voice", action="store_true", help="Force pure raw voice without EQ/compression")
    ap.add_argument("--dry", action="store_true", help="One-flag pure dry voice export: bypass EQ/compression, BGM, and SFX")
    ap.add_argument("--sfx", type=Path, default=None, help="JSON SFX plan [{t, kind, sound}]")
    ap.add_argument("--sfx-under-db", type=float, default=20.0,
                    help="Level delta below voice target LUFS (must stay in [18, 22], default: 20)")
    ap.add_argument("--no-sfx", action="store_true", help="Strip SFX cleanly even if --sfx plan is supplied")
    ap.add_argument("--list-sfx", action="store_true", help="List built-in local restrained SFX assets and exit")
    ap.add_argument("--json", action="store_true", help="Output machine-readable JSON")
    a = ap.parse_args()

    if a.list_sfx:
        items = load_sfx_catalog()
        if a.json:
            print(json.dumps({"items": items}, ensure_ascii=False, indent=2))
        else:
            for item in items:
                print(f"{item['id']}\t{item['kind']}\t{item['duration_s']}s\t{item['file']}")
        return 0

    if not a.voice or not a.output:
        sys.exit("必须提供 voice 输入与 -o/--output 输出路径（或使用 --list-sfx）")
    if not a.voice.is_file():
        sys.exit(f"找不到人声：{a.voice}")

    a.output.parent.mkdir(parents=True, exist_ok=True)
    dur = probe_duration(a.voice)

    use_bgm = None if a.dry else a.bgm
    use_sfx = [] if (a.dry or a.no_sfx or a.sfx is None) else validate_sfx_plan(a.sfx, dur, a.sfx_under_db)

    voice_mode = "raw" if (a.dry or a.raw_voice) else a.voice_preset

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        voice_wav = a.voice
        if voice_mode in ("podcast-warm", "raw"):
            import audio_fix
            voice_wav = tmp / "voice_prepped.wav"
            audio_fix.apply_voice_preset(a.voice, voice_wav, preset=voice_mode, target_lufs=a.target_lufs)

        if a.dry:
            # Pure dry voice: keep exact clean signal without EQ/comp/loudnorm/SFX/BGM
            if voice_wav != a.voice:
                run(["ffmpeg", "-v", "error", "-y", "-i", str(voice_wav),
                     "-ar", "48000", "-ac", "2", str(a.output)])
            else:
                run(["ffmpeg", "-v", "error", "-y", "-i", str(a.voice),
                     "-vn", "-ar", "48000", "-ac", "2", str(a.output)])
            out_lu = lufs(a.output)
            if a.json:
                print(json.dumps({"mode": "dry", "voice_preset": "raw", "sfx_count": 0,
                                  "output_lufs": round(out_lu, 2), "output": str(a.output)}, ensure_ascii=False))
            else:
                print(f"dry voice · {out_lu:.1f} LUFS -> {a.output}")
            return 0

        # Pre-level voice to exact target_lufs unless simple single-voice mode
        if not use_bgm and not use_sfx:
            if voice_mode == "raw":
                run(["ffmpeg", "-v", "error", "-y", "-i", str(voice_wav),
                     "-ar", "48000", "-ac", "2", str(a.output)])
            else:
                gain = a.target_lufs - lufs(voice_wav)
                af = f"volume={gain:.2f}dB,alimiter=limit=0.841:level=false"
                run(["ffmpeg", "-v", "error", "-y", "-i", str(voice_wav), "-af", af,
                     "-ar", "48000", "-ac", "2", str(a.output)])
            out_lu = lufs(a.output)
            if a.json:
                print(json.dumps({"mode": "voice-only", "voice_preset": voice_mode, "sfx_count": 0,
                                  "output_lufs": round(out_lu, 2), "output": str(a.output)}, ensure_ascii=False))
            else:
                print(f"voice only · {out_lu:.1f} LUFS → {a.output}")
            return 0

        # Complex graph: voice + optional BGM + optional restrained local SFX
        inputs = ["-i", str(voice_wav)]
        filters = []
        mix_labels = []

        voice_split = ",asplit=2[voice][sc]" if use_bgm else "[voice]"
        if voice_mode == "raw":
            filters.append(f"[0:a]aresample=48000,aformat=channel_layouts=stereo{voice_split}")
        else:
            v_gain = a.target_lufs - lufs(voice_wav)
            filters.append(
                f"[0:a]aresample=48000,aformat=channel_layouts=stereo,"
                f"volume={v_gain:.2f}dB,alimiter=limit=0.841:level=false{voice_split}"
            )
        mix_labels.append("[voice]")

        idx = 1
        if use_bgm:
            if not use_bgm.is_file():
                sys.exit(f"找不到 BGM：{use_bgm}")
            inputs.extend(["-i", str(use_bgm)])
            bed_gain = a.bgm_lufs - lufs(use_bgm)
            total = dur + max(0.0, a.tail)
            filters.append(
                f"[{idx}:a]aresample=48000,aformat=channel_layouts=stereo,"
                f"atrim=0:{total:.3f},asetpts=PTS-STARTPTS,"
                f"volume={bed_gain:.2f}dB,afade=t=in:st=0:d=0.8[bed0];"
                f"[bed0][sc]sidechaincompress=threshold=0.1:ratio=2.5:attack=40:release=500[bed]"
            )
            mix_labels.append("[bed]")
            idx += 1

        target_sfx_rms = a.target_lufs - a.sfx_under_db
        for s_i, ev in enumerate(use_sfx):
            inputs.extend(["-i", str(ev["path"])])
            rms_db, peak_db = measure_clip_rms_and_peak(ev["path"])
            gain_db = target_sfx_rms - rms_db
            # Never exceed -18 dBFS peak regardless of crest factor
            if peak_db + gain_db > -18.0:
                gain_db = -18.0 - peak_db
            delay_ms = max(0, int(round(ev["t"] * 1000)))
            lbl = f"sfx{s_i}"
            filters.append(
                f"[{idx}:a]aresample=48000,aformat=channel_layouts=stereo,"
                f"volume={gain_db:.2f}dB,adelay={delay_ms}|{delay_ms}[{lbl}]"
            )
            mix_labels.append(f"[{lbl}]")
            idx += 1

        amix_in = "".join(mix_labels)
        if use_bgm and not use_sfx:
            # Preserve exact existing BGM+voice loudnorm signature
            filters.append(
                f"{amix_in}amix=inputs={len(mix_labels)}:duration=first:dropout_transition=0,"
                f"loudnorm=I={a.target_lufs}:TP=-1.5:LRA=11[out]"
            )
        else:
            # normalize=0 keeps voice at exact -14 LUFS and SFX exact [-18..-22 dB] underneath voice!
            filters.append(
                f"{amix_in}amix=inputs={len(mix_labels)}:duration=first:dropout_transition=0:normalize=0,"
                f"alimiter=limit=0.841:level=false[out]"
            )

        fc = ";".join(filters)
        run(["ffmpeg", "-v", "error", "-y", *inputs,
             "-filter_complex", fc, "-map", "[out]", "-ar", "48000", "-ac", "2", str(a.output)])
        out_lu = lufs(a.output)
        if a.json:
            print(json.dumps({
                "mode": "mix",
                "voice_preset": voice_mode,
                "bgm": bool(use_bgm),
                "sfx_count": len(use_sfx),
                "sfx_under_db": a.sfx_under_db if use_sfx else None,
                "output_lufs": round(out_lu, 2),
                "output": str(a.output),
            }, ensure_ascii=False))
        else:
            print(f"mix · sfx={len(use_sfx)} · {out_lu:.1f} LUFS → {a.output}")
        return 0


if __name__ == "__main__":
    sys.exit(main())
