#!/usr/bin/env python3
"""Unified Video Style Extraction & Evolution CLI (`video-craft`).

Implements the model-agnostic 4-step protocol (`references/style-extraction.md`):
  1. `packet`    — Collect project feedback / video metadata + current style capacity into `packet.json`
  2. (Model)     — Fill out `proposal.json` following the 4-question rubric
  3. `check`     — Mechanically validate `proposal.json` (schema, no numbers/quotes in prose, caps, admission)
  4. `apply`     — Apply admitted rules to `idea/page/craft.md`, store single-project tendencies in
                   `candidates.json` (with 2-project auto-promotion and 3-project TTL expiry), extract
                   pattern strips/webm, rebuild `_video-vault/index.html`, and commit to local Git.
  5. `lint`      — Verify all styles in the vault obey every structural & line-count cap.
  6. `bootstrap` — Initialize a brand-new style playbook in the vault from a reference video or project.

Also supports direct one-shot CLI flags (`--video <path> --style <id> [--bootstrap]`) for quick invocation.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from resolve_vault import find_vault_root
from style_vault import (
    CANDIDATE_TTL,
    EVIDENCE_TYPES,
    MAX_ENTRIES,
    MAX_LOADED_LINES,
    MAX_PATTERNS,
    MAX_STAGE_LINES,
    PRODUCTION_MODES,
    RELATIONS,
    REQUIRED_FIELDS,
    STAGE_GLOBAL,
    STAGES,
    admission,
    evidence_text,
    lint_style,
    lint_vault,
    load_json,
    next_id,
    parse_stage,
    render_stage,
    text_problems,
)


# ---------------------------------------------------------------- 单一媒体抽取实现 (FFmpeg)

def find_video_file(target: Path | None) -> Path | None:
    if target is None or not target.exists():
        return None
    if target.is_file() and target.suffix.lower() in (".mp4", ".mov", ".mkv", ".webm"):
        return target
    if target.is_dir():
        for sub in ("成品", "deliverable", "edit/_engineering", "edit", "."):
            d = target / sub
            if d.is_dir():
                mp4s = sorted(d.glob("*.mp4")) + sorted(d.glob("*.mov"))
                if mp4s:
                    return mp4s[0]
    return None


def probe_video_meta(video_path: Path) -> dict[str, Any]:
    cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height,r_frame_rate:format=duration",
        "-of", "json", str(video_path),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        return {"duration": 30.0, "width": 1920, "height": 1080}
    try:
        data = json.loads(res.stdout)
        stream = (data.get("streams") or [{}])[0]
        fmt = data.get("format") or {}
        return {
            "width": int(stream.get("width") or 1920),
            "height": int(stream.get("height") or 1080),
            "r_frame_rate": stream.get("r_frame_rate", "30/1"),
            "duration": float(fmt.get("duration") or 30.0),
        }
    except (ValueError, KeyError, json.JSONDecodeError):
        return {"duration": 30.0, "width": 1920, "height": 1080}


def extract_style_board(video_path: Path, out_jpg: Path) -> bool:
    meta = probe_video_meta(video_path)
    dur = max(float(meta.get("duration") or 30.0), 1.0)
    fps = 12.0 / dur
    out_jpg.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-y", "-i", str(video_path),
        "-vf", f"fps={fps:.4f},scale=320:-1,tile=4x3",
        "-frames:v", "1", "-q:v", "4", str(out_jpg),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    return res.returncode == 0 and out_jpg.is_file()


def extract_pattern_media(
    video_path: Path,
    patterns_dir: Path,
    pat_id: str,
    start_sec: float,
    dur_sec: float = 2.0,
) -> dict[str, str | None]:
    patterns_dir.mkdir(parents=True, exist_ok=True)
    strip_jpg = patterns_dir / f"{pat_id}-strip.jpg"
    clip_webm = patterns_dir / f"{pat_id}.webm"

    fps = 3.0 / max(dur_sec, 0.6)
    subprocess.run(
        [
            "ffmpeg", "-y", "-ss", f"{start_sec:.2f}", "-t", f"{dur_sec:.2f}",
            "-i", str(video_path),
            "-vf", f"fps={fps:.4f},scale=480:-1,tile=3x1",
            "-frames:v", "1", "-q:v", "4", str(strip_jpg),
        ],
        capture_output=True, text=True,
    )
    subprocess.run(
        [
            "ffmpeg", "-y", "-ss", f"{start_sec:.2f}", "-t", f"{min(dur_sec, 2.5):.2f}",
            "-i", str(video_path),
            "-an", "-vf", "scale=640:-2,fps=24",
            "-c:v", "libvpx-vp9", "-b:v", "600k", "-crf", "34",
            str(clip_webm),
        ],
        capture_output=True, text=True,
    )
    return {
        "strip": f"patterns/{strip_jpg.name}" if strip_jpg.is_file() else None,
        "webm": f"patterns/{clip_webm.name}" if clip_webm.is_file() else None,
    }


def _vault_or_local(vault_arg: str | None) -> Path:
    if vault_arg:
        return Path(vault_arg).expanduser().resolve()
    v = find_vault_root()
    if v is not None:
        return v
    fallback = Path.cwd() / "_extracted_styles"
    fallback.mkdir(parents=True, exist_ok=True)
    if not (fallback / "manifest.json").is_file():
        (fallback / "manifest.json").write_text(
            json.dumps({"schema_version": "2.0.0", "styles": []}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    (fallback / "styles").mkdir(exist_ok=True)
    return fallback


def _git_commit_vault(vault: Path, message: str) -> str | None:
    if not (vault / ".git").exists():
        return None
    subprocess.run(["git", "-C", str(vault), "add", "-A"], capture_output=True, text=True)
    status = subprocess.run(["git", "-C", str(vault), "status", "--porcelain"], capture_output=True, text=True)
    if not status.stdout.strip():
        return None
    subprocess.run(
        [
            "git", "-C", str(vault),
            "-c", "user.name=thePlannerIvan",
            "-c", "user.email=Lawyif@163.com",
            "commit", "-qm", message,
        ],
        capture_output=True, text=True,
    )
    rev = subprocess.run(["git", "-C", str(vault), "rev-parse", "--short", "HEAD"], capture_output=True, text=True)
    return rev.stdout.strip() or None


def _rebuild_viewer(vault: Path) -> None:
    viewer_script = vault / "scripts" / "build_vault_viewer.py"
    if viewer_script.is_file():
        subprocess.run([sys.executable, str(viewer_script)], capture_output=True, text=True)


# ---------------------------------------------------------------- Step 1: packet

def build_packet(source: Path, style_id: str, vault: Path, out_path: Path | None = None) -> dict[str, Any]:
    sdir = vault / "styles" / style_id
    meta = load_json(sdir / "style.json", {"style_id": style_id, "production_mode": "keyframe-svg", "params": {}, "patterns": []})
    candidates = load_json(sdir / "candidates.json", [])

    # Collect current stage rules & remaining capacity
    stages_state: dict[str, Any] = {}
    for stage in STAGES:
        md_path = sdir / f"{stage}.md"
        text = md_path.read_text(encoding="utf-8") if md_path.is_file() else ""
        _, entries = parse_stage(text)
        n_lines = len(text.splitlines())
        gname = STAGE_GLOBAL[stage]
        g_lines = len((vault / "global" / gname).read_text(encoding="utf-8").splitlines()) if gname and (vault / "global" / gname).is_file() else 0
        stages_state[stage] = {
            "entries_count": len(entries),
            "entries_max": MAX_ENTRIES,
            "lines_count": n_lines,
            "lines_max": MAX_STAGE_LINES,
            "loaded_lines": n_lines + g_lines,
            "loaded_lines_max": MAX_LOADED_LINES,
            "entries": entries,
        }

    # Collect evidence from source (project dir or video file)
    source_name = source.stem if source.is_file() else source.name
    feedback_records: list[dict[str, Any]] = []
    project_prefs = ""
    visual_plan_summary: dict[str, Any] = {}
    if source.is_dir():
        fb_dir = source / "feedback"
        if fb_dir.is_dir():
            for jf in sorted(fb_dir.glob("*.jsonl")):
                for line in jf.read_text(encoding="utf-8").splitlines():
                    if not line.strip():
                        continue
                    try:
                        rec = json.loads(line)
                        feedback_records.append({
                            "file": jf.name,
                            "unitId": rec.get("unitId") or rec.get("stepId") or "overall",
                            "text": rec.get("text") or rec.get("note") or "",
                            "adjustments": rec.get("adjustments"),
                        })
                    except json.JSONDecodeError:
                        continue
        pref_file = source / "edit" / "preferences.md"
        if pref_file.is_file():
            project_prefs = pref_file.read_text(encoding="utf-8")[:3000]
        for vp_rel in ("deliverable/visual-plan.json", "visual-plan.json"):
            vp = source / vp_rel
            if vp.is_file():
                vp_data = load_json(vp, {})
                visual_plan_summary = {
                    "style_id": vp_data.get("style_id"),
                    "production_mode": vp_data.get("production_mode"),
                    "screens_count": len(vp_data.get("screens") or []),
                }
                break

    video_file = find_video_file(source)
    video_info: dict[str, Any] | None = None
    if video_file is not None:
        vmeta = probe_video_meta(video_file)
        board_out = (out_path.parent if out_path else (vault / "_style_extract")) / f"{style_id}-{source_name}-board.jpg"
        extract_style_board(video_file, board_out)
        video_info = {
            "path": str(video_file),
            "meta": vmeta,
            "contact_sheet": str(board_out) if board_out.is_file() else None,
        }

    packet = {
        "schema": "video-craft.style-extraction-packet.v1",
        "generated_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "style_id": style_id,
        "source_project": source_name,
        "source_path": str(source),
        "style_exists": sdir.is_dir(),
        "production_mode": meta.get("production_mode", "keyframe-svg"),
        "current_params": meta.get("params", {}),
        "current_patterns": meta.get("patterns", []),
        "stages": stages_state,
        "pending_candidates": candidates,
        "evidence_collected": {
            "feedback_records": feedback_records,
            "project_preferences_md": project_prefs,
            "visual_plan": visual_plan_summary,
            "video": video_info,
        },
        "extraction_rubric": {
            "rule_1_stage_routing": "idea (I01..I05, video-idea-system) | page (P01..P05, planners-ppt-hell/frame) | craft (C01..C05, video-craft)",
            "rule_2_no_numbers_in_prose": "Title and 做法 MUST NOT contain digits [0-9] or '#' hex colors; put numeric/color values in params_patch and reference keys via 参数.",
            "rule_3_no_quotes": "Never include quote marks 「」“” in titles or fields; summarize the actionable rule.",
            "rule_4_admission": {
                "feedback-negative": "Admitted immediately (依据: 反馈否定)",
                "feedback-tendency": "Requires 2 independent projects (stored in candidates.json on 1st project; auto-promoted on 2nd)",
                "approved-observation": "Requires 2 independent projects (or --confirm)",
                "reference-observation": "Stored in candidates.json unless --confirm is passed",
            },
            "rule_5_caps": f"Max {MAX_ENTRIES} entries and {MAX_STAGE_LINES} lines per stage; max {MAX_LOADED_LINES} loaded lines; when full, use relation='替代' or '合并' with target_id.",
        },
    }
    if out_path is not None:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(packet, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return packet


# ---------------------------------------------------------------- Step 3: check

def evaluate_proposal(
    proposal: dict[str, Any],
    vault: Path,
    confirmed: bool = False,
) -> dict[str, Any]:
    style_id = (proposal.get("style_id") or "").strip()
    if not style_id:
        return {"ok": False, "problems": ["proposal 缺 style_id"], "decisions": []}

    sdir = vault / "styles" / style_id
    meta = load_json(sdir / "style.json", {
        "style_id": style_id,
        "name": proposal.get("name") or style_id,
        "production_mode": proposal.get("production_mode") or "keyframe-svg",
        "default_frame_preset": proposal.get("default_frame_preset") or "landscape-left-host",
        "params": {},
        "patterns": [],
    })
    candidates: list[dict[str, Any]] = load_json(sdir / "candidates.json", [])

    # Merge params_patch
    merged_params = dict(meta.get("params") or {})
    params_patch = proposal.get("params_patch") or {}
    problems: list[str] = []
    for k, spec in params_patch.items():
        if not isinstance(spec, dict) or "value" not in spec or spec.get("source") not in ("measured", "author", "inferred"):
            problems.append(f"params_patch.{k} 必须含 value 与 source (measured|author|inferred)")
        else:
            merged_params[k] = spec

    # Load current stage entries
    stage_map: dict[str, list[dict[str, Any]]] = {}
    for st in STAGES:
        md_path = sdir / f"{st}.md"
        stage_map[st] = parse_stage(md_path.read_text(encoding="utf-8"))[1] if md_path.is_file() else []

    decisions: list[dict[str, Any]] = []
    promoted_candidate_titles: set[tuple[str, str]] = set()
    new_candidates: list[dict[str, Any]] = []

    for idx, rule in enumerate(proposal.get("rules") or [], 1):
        stage = rule.get("stage", "")
        rel = rule.get("relation", "新增")
        target_id = rule.get("target_id")
        title = (rule.get("title") or "").strip()
        fields = dict(rule.get("fields") or {})
        ev_list = list(rule.get("evidence") or [])
        tag = f"rules[{idx}]({stage}:{title or '无标题'})"

        if stage not in STAGES:
            problems.append(f"{tag} stage 必须是 idea / page / craft")
            continue
        if rel not in RELATIONS:
            problems.append(f"{tag} relation 必须是 {' / '.join(RELATIONS)}")
            continue
        if not title:
            problems.append(f"{tag} 缺 title")
            continue
        if not ev_list:
            problems.append(f"{tag} 缺 evidence 列表")
            continue
        for ev in ev_list:
            if ev.get("type") not in EVIDENCE_TYPES or not ev.get("project") or not ev.get("where"):
                problems.append(f"{tag} evidence 项需含 project, where, type ({'/'.join(EVIDENCE_TYPES)})")

        # Check if matching candidate already exists in candidates.json
        for cand in candidates:
            if cand.get("stage") == stage and cand.get("title") == title:
                for old_ev in cand.get("evidence") or []:
                    if old_ev not in ev_list:
                        ev_list.append(old_ev)
                promoted_candidate_titles.add((stage, title))

        admitted, basis, reason = admission(ev_list, confirmed=confirmed or bool(rule.get("confirmed")))
        fields["证据"] = evidence_text(ev_list)
        if basis:
            fields["依据"] = basis

        # Validate text and field rules even if going to candidates so bad rules never enter the pool
        check_fields = dict(fields)
        check_fields.setdefault("依据", basis or "复现")
        for req in ("做法", "证据", "执行"):
            if not check_fields.get(req):
                problems.append(f"{tag} 缺字段：{req}")
        for p_key in [k.strip() for k in re.split(r"[、,，]", check_fields.get("参数", "")) if k.strip()]:
            if p_key not in merged_params:
                problems.append(f"{tag} 引用了未定义的参数：params.{p_key}")
        problems += text_problems(tag, title, check_fields)

        if not admitted:
            decisions.append({
                "rule": title,
                "stage": stage,
                "destination": "candidates.json",
                "reason": reason,
            })
            new_candidates.append({
                "stage": stage,
                "relation": rel,
                "target_id": target_id,
                "title": title,
                "fields": {k: v for k, v in fields.items() if k != "依据"},
                "evidence": ev_list,
                "ttl_remaining": CANDIDATE_TTL,
            })
            continue

        # Rule is admitted into active stage file
        entries = stage_map[stage]
        all_ids = [e["id"] for st_entries in stage_map.values() for e in st_entries]
        if rel == "新增":
            new_entry_id = next_id(stage, all_ids)
            entries.append({"id": new_entry_id, "title": title, "fields": fields, "extra": []})
            decisions.append({"rule": title, "stage": stage, "destination": f"{stage}.md#{new_entry_id}", "basis": basis, "reason": reason})
        elif rel in ("替代", "合并"):
            target = next((e for e in entries if e["id"] == target_id), None)
            if target is None:
                problems.append(f"{tag} relation={rel} 指定的 target_id={target_id!r} 在 {stage}.md 中不存在")
                continue
            target["title"] = title
            if rel == "合并":
                old_ev = target["fields"].get("证据", "")
                fields["证据"] = "；".join(dict.fromkeys([x.strip() for x in (old_ev + "；" + fields["证据"]).split("；") if x.strip()]))
            target["fields"] = fields
            decisions.append({"rule": title, "stage": stage, "destination": f"{stage}.md#{target_id} ({rel})", "basis": basis, "reason": reason})
        elif rel == "补证":
            target = next((e for e in entries if e["id"] == target_id), None)
            if target is None:
                problems.append(f"{tag} relation=补证 指定的 target_id={target_id!r} 在 {stage}.md 中不存在")
                continue
            old_ev = target["fields"].get("证据", "")
            target["fields"]["证据"] = "；".join(dict.fromkeys([x.strip() for x in (old_ev + "；" + fields["证据"]).split("；") if x.strip()]))
            target["fields"]["依据"] = "复现"
            decisions.append({"rule": title, "stage": stage, "destination": f"{stage}.md#{target_id} (补证)", "basis": "复现", "reason": "补充新项目证据"})

    # Check resulting stage caps
    for st, entries in stage_map.items():
        rendered = render_stage(style_id, st, entries)
        n_lines = len(rendered.splitlines())
        if len(entries) > MAX_ENTRIES:
            problems.append(f"{st}.md 合入后有 {len(entries)} 条，超过 {MAX_ENTRIES} 条上限（请使用 relation='替代' 或 '合并'）")
        if n_lines > MAX_STAGE_LINES:
            problems.append(f"{st}.md 合入后共 {n_lines} 行，超过 {MAX_STAGE_LINES} 行上限")
        gname = STAGE_GLOBAL[st]
        if gname and (vault / "global" / gname).is_file():
            loaded = n_lines + len((vault / "global" / gname).read_text(encoding="utf-8").splitlines())
            if loaded > MAX_LOADED_LINES:
                problems.append(f"{st} 阶段加载总行数 {loaded} 超过 {MAX_LOADED_LINES} 行上限")

    # Check patterns cap
    existing_patterns = list(meta.get("patterns") or [])
    by_id = {p["id"]: p for p in existing_patterns if "id" in p}
    for pat in proposal.get("patterns") or []:
        pid = pat.get("id")
        if not pid:
            problems.append("patterns 项缺 id")
            continue
        if pat.get("replaces") and pat["replaces"] in by_id:
            del by_id[pat["replaces"]]
        by_id[pid] = pat
    if len(by_id) > MAX_PATTERNS:
        problems.append(f"patterns 合入后共 {len(by_id)} 个，超过 {MAX_PATTERNS} 个上限（请用 replaces 指定替换哪个旧招式）")

    return {
        "ok": not problems,
        "style_id": style_id,
        "problems": problems,
        "decisions": decisions,
        "_internal": {
            "meta": meta,
            "merged_params": merged_params,
            "stage_map": stage_map,
            "existing_candidates": candidates,
            "promoted_candidate_titles": promoted_candidate_titles,
            "new_candidates": new_candidates,
        },
    }


# ---------------------------------------------------------------- Step 4: apply

def apply_proposal(
    proposal: dict[str, Any],
    vault: Path,
    video_source: Path | None = None,
    confirmed: bool = False,
) -> dict[str, Any]:
    checked = evaluate_proposal(proposal, vault, confirmed=confirmed)
    if not checked["ok"]:
        return checked

    style_id = checked["style_id"]
    sdir = vault / "styles" / style_id
    sdir.mkdir(parents=True, exist_ok=True)
    (sdir / "patterns").mkdir(exist_ok=True)
    (sdir / "anchors").mkdir(exist_ok=True)

    internal = checked["_internal"]
    meta = internal["meta"]
    meta["params"] = internal["merged_params"]

    today = datetime.now().strftime("%Y-%m-%d")
    source_proj = (proposal.get("source_project") or (video_source.stem if video_source and video_source.is_file() else (video_source.name if video_source else "manual"))).strip()
    evolved_list = meta.setdefault("evolved_from_projects", [])
    is_new_project = source_proj and source_proj not in evolved_list
    if is_new_project:
        evolved_list.append(source_proj)
    meta["evolved_from_count"] = len(evolved_list)

    evo_log_path = sdir / "evolution-log.json"
    evo_log: list[dict[str, Any]] = load_json(evo_log_path, [])
    new_version = proposal.get("version") or f"v{max(len(evolved_list), 1)}.{len(evo_log) + 1} ({today})"
    meta["version"] = new_version
    meta["updated_at"] = today

    # Extract pattern clips if requested
    video_file = find_video_file(video_source)
    if video_file and not (sdir / "style-board.jpg").is_file():
        extract_style_board(video_file, sdir / "style-board.jpg")

    existing_patterns = {p["id"]: p for p in (meta.get("patterns") or []) if "id" in p}
    for pat in proposal.get("patterns") or []:
        pid = pat["id"]
        if pat.get("replaces") and pat["replaces"] in existing_patterns:
            del existing_patterns[pat["replaces"]]
        entry = dict(existing_patterns.get(pid) or {})
        for k in ("id", "title", "when_to_use", "rule", "code"):
            if pat.get(k) is not None:
                entry[k] = pat[k]
        clip_spec = pat.get("clip")
        if clip_spec and video_file:
            media = extract_pattern_media(
                video_file,
                sdir / "patterns",
                pid,
                float(clip_spec.get("start_sec", 2.0)),
                float(clip_spec.get("dur_sec", 2.0)),
            )
            if media.get("strip"):
                entry["strip"] = media["strip"]
            if media.get("webm"):
                entry["webm"] = media["webm"]
        existing_patterns[pid] = entry
    meta["patterns"] = list(existing_patterns.values())

    # Write stage markdowns
    for st, entries in internal["stage_map"].items():
        (sdir / f"{st}.md").write_text(render_stage(style_id, st, entries), encoding="utf-8")

    # Update candidates.json with TTL aging on new project
    remaining_candidates: list[dict[str, Any]] = []
    for cand in internal["existing_candidates"]:
        key = (cand.get("stage"), cand.get("title"))
        if key in internal["promoted_candidate_titles"]:
            continue
        ttl = int(cand.get("ttl_remaining", CANDIDATE_TTL))
        if is_new_project:
            ttl -= 1
        if ttl > 0:
            cand["ttl_remaining"] = ttl
            remaining_candidates.append(cand)
    for new_c in internal["new_candidates"]:
        # Replace if same (stage, title)
        remaining_candidates = [c for c in remaining_candidates if (c.get("stage"), c.get("title")) != (new_c["stage"], new_c["title"])]
        remaining_candidates.append(new_c)
    (sdir / "candidates.json").write_text(json.dumps(remaining_candidates, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # Write style.json & evolution-log.json
    (sdir / "style.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    summary = proposal.get("summary") or "按四步提取协议更新风格手册"
    evo_log.insert(0, {
        "version": new_version,
        "date": today,
        "source_video": source_proj,
        "type": "rule+pattern",
        "summary": summary,
        "decisions": checked["decisions"],
    })
    evo_log_path.write_text(json.dumps(evo_log, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # Ensure style is registered in manifest.json
    manifest_path = vault / "manifest.json"
    if manifest_path.is_file():
        manifest = load_json(manifest_path, {"schema_version": "2.0.0", "styles": []})
        if style_id not in manifest.setdefault("styles", []):
            manifest["styles"].append(style_id)
        manifest["updated_at"] = today
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    lint_errors = lint_style(vault, style_id)
    _rebuild_viewer(vault)
    commit_sha = _git_commit_vault(vault, f"evolve({style_id}): {summary}")
    return {
        "ok": not lint_errors,
        "style_id": style_id,
        "version": new_version,
        "decisions": checked["decisions"],
        "candidates_count": len(remaining_candidates),
        "lint_problems": lint_errors,
        "git_commit": commit_sha,
    }


def bootstrap_style_cmd(
    vault: Path,
    style_id: str,
    name: str,
    mode: str,
    source: Path,
    summary: str,
    clips: list[str],
) -> dict[str, Any]:
    sdir = vault / "styles" / style_id
    sdir.mkdir(parents=True, exist_ok=True)
    (sdir / "patterns").mkdir(exist_ok=True)
    (sdir / "anchors").mkdir(exist_ok=True)

    today = datetime.now().strftime("%Y-%m-%d")
    source_name = source.stem if source.is_file() else source.name
    default_preset = "vertical-zine-head" if mode == "footage-montage" else "landscape-left-host"

    video_file = find_video_file(source)
    patterns: list[dict[str, Any]] = []
    if video_file:
        extract_style_board(video_file, sdir / "style-board.jpg")
        for idx, spec in enumerate(clips, 1):
            parts = spec.split(":")
            pat_id = parts[0] if parts[0] else f"p{idx}-move"
            start_s = float(parts[1]) if len(parts) > 1 else 2.0 * idx
            dur_s = float(parts[2]) if len(parts) > 2 else 2.0
            media = extract_pattern_media(video_file, sdir / "patterns", pat_id, start_s, dur_s)
            pat_entry: dict[str, Any] = {
                "id": pat_id,
                "title": f"招式 · {pat_id}",
                "when_to_use": f"从 {source_name} 提炼的代表镜头",
                "rule": summary,
            }
            if media.get("strip"):
                pat_entry["strip"] = media["strip"]
            if media.get("webm"):
                pat_entry["webm"] = media["webm"]
            patterns.append(pat_entry)

    meta = {
        "style_id": style_id,
        "name": name or style_id,
        "version": f"v1.0 ({today})",
        "updated_at": today,
        "production_mode": mode,
        "default_frame_preset": default_preset,
        "evolved_from_count": 1,
        "evolved_from_projects": [source_name],
        "positioning": summary,
        "params": {
            "bg_primary": {"value": "#111111" if mode == "footage-montage" else "#F4F1EA", "source": "inferred"},
            "ink_primary": {"value": "#F5F3EE" if mode == "footage-montage" else "#161616", "source": "inferred"},
        },
        "patterns": patterns[:MAX_PATTERNS],
    }
    (sdir / "style.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for st in STAGES:
        if not (sdir / f"{st}.md").is_file():
            (sdir / f"{st}.md").write_text(render_stage(style_id, st, []), encoding="utf-8")
    if not (sdir / "candidates.json").is_file():
        (sdir / "candidates.json").write_text("[]\n", encoding="utf-8")
    (sdir / "evolution-log.json").write_text(
        json.dumps([{"version": meta["version"], "date": today, "source_video": source_name, "type": "bootstrap", "summary": summary}], ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    manifest_path = vault / "manifest.json"
    if manifest_path.is_file():
        manifest = load_json(manifest_path, {"schema_version": "2.0.0", "styles": []})
        if style_id not in manifest.setdefault("styles", []):
            manifest["styles"].append(style_id)
        manifest["updated_at"] = today
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    problems = lint_style(vault, style_id)
    _rebuild_viewer(vault)
    commit_sha = _git_commit_vault(vault, f"bootstrap({style_id}): {summary}")
    return {"ok": not problems, "action": "bootstrap", "style_id": style_id, "style_dir": str(sdir), "problems": problems, "git_commit": commit_sha}


# ---------------------------------------------------------------- CLI 入口

def main(argv: list[str] | None = None) -> int:
    argv_list = list(sys.argv[1:] if argv is None else argv)
    subcommands = {"packet", "check", "apply", "lint", "bootstrap"}

    if argv_list and argv_list[0] in subcommands:
        cmd = argv_list[0]
        rest = argv_list[1:]
        parser = argparse.ArgumentParser(prog=f"extract_style.py {cmd}")
        parser.add_argument("--vault", default=None, help="Override vault root directory")
        if cmd == "lint":
            parser.add_argument("--style", default=None, help="Lint a single style_id (default: all styles)")
            parser.add_argument("--json", action="store_true")
            args = parser.parse_args(rest)
            vault = _vault_or_local(args.vault)
            problems = lint_style(vault, args.style) if args.style else lint_vault(vault)
            print(json.dumps({"ok": not problems, "vault": str(vault), "problems": problems}, ensure_ascii=False, indent=2))
            return 0 if not problems else 1

        if cmd == "packet":
            parser.add_argument("--video", "--project", dest="source", required=True)
            parser.add_argument("--style", required=True)
            parser.add_argument("--out", default=None, help="Path to write packet.json")
            args = parser.parse_args(rest)
            vault = _vault_or_local(args.vault)
            out_p = Path(args.out).expanduser().resolve() if args.out else None
            pkt = build_packet(Path(args.source).expanduser().resolve(), args.style, vault, out_p)
            print(json.dumps(pkt, ensure_ascii=False, indent=2))
            return 0

        if cmd in ("check", "apply"):
            parser.add_argument("--proposal", required=True, help="Path to proposal.json")
            parser.add_argument("--video", "--project", dest="source", default=None, help="Optional video/project path for pattern clip extraction")
            parser.add_argument("--confirm", action="store_true", help="Explicitly confirm admission of reference/single-project rules")
            args = parser.parse_args(rest)
            vault = _vault_or_local(args.vault)
            prop = load_json(Path(args.proposal).expanduser().resolve(), None)
            if not isinstance(prop, dict):
                print(json.dumps({"ok": False, "problems": [f"无法读取 proposal：{args.proposal}"]}, ensure_ascii=False), file=sys.stderr)
                return 2
            if cmd == "check":
                res = evaluate_proposal(prop, vault, confirmed=args.confirm)
                res.pop("_internal", None)
                print(json.dumps(res, ensure_ascii=False, indent=2))
                return 0 if res["ok"] else 1
            src = Path(args.source).expanduser().resolve() if args.source else None
            res = apply_proposal(prop, vault, video_source=src, confirmed=args.confirm)
            print(json.dumps(res, ensure_ascii=False, indent=2))
            return 0 if res["ok"] else 1

        if cmd == "bootstrap":
            parser.add_argument("--video", "--project", dest="source", required=True)
            parser.add_argument("--style", required=True)
            parser.add_argument("--name", default=None)
            parser.add_argument("--mode", choices=PRODUCTION_MODES, default="keyframe-svg")
            parser.add_argument("--summary", default="初始化新视频风格手册")
            parser.add_argument("--clip", action="append", default=[])
            args = parser.parse_args(rest)
            vault = _vault_or_local(args.vault)
            res = bootstrap_style_cmd(vault, args.style, args.name or args.style, args.mode, Path(args.source).expanduser().resolve(), args.summary, args.clip)
            print(json.dumps(res, ensure_ascii=False, indent=2))
            return 0 if res["ok"] else 1

    # Direct flag compatibility mode: --video <path> --style <id> [--bootstrap] [--proposal <json>]
    parser = argparse.ArgumentParser(
        description="Extract or evolve a video style (`packet` / `check` / `apply` / `lint` / `bootstrap`, or direct flags)."
    )
    parser.add_argument("--video", "--project", dest="source", required=True, help="Path to reference video (.mp4/.mov) or finished video project directory")
    parser.add_argument("--style", required=True, help="Target style_id")
    parser.add_argument("--proposal", default=None, help="Optional proposal.json to apply")
    parser.add_argument("--summary", default="提炼视频风格规则与代表性动效招式", help="Summary of extracted or evolved rules/patterns")
    parser.add_argument("--version", default=None, help="Optional explicit version string")
    parser.add_argument("--bootstrap", action="store_true", help="Create a brand-new style playbook")
    parser.add_argument("--name", default=None, help="Display name when bootstrapping a new style")
    parser.add_argument("--mode", choices=PRODUCTION_MODES, default="keyframe-svg", help="Production mode")
    parser.add_argument("--clip", action="append", default=[], help="Pattern clip to extract: <pattern_id>:<start_sec>:<dur_sec>")
    parser.add_argument("--out-dir", "--vault", dest="vault", default=None, help="Override vault / output directory")
    parser.add_argument("--confirm", action="store_true", help="Confirm direct rule admission")
    args = parser.parse_args(argv_list)

    source_path = Path(args.source).expanduser().resolve()
    if not source_path.exists():
        print(json.dumps({"ok": False, "error": f"输入路径不存在：{source_path}"}, ensure_ascii=False), file=sys.stderr)
        return 2

    vault = _vault_or_local(args.vault)
    if args.bootstrap:
        res = bootstrap_style_cmd(vault, args.style, args.name or args.style, args.mode, source_path, args.summary, args.clip)
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return 0 if res["ok"] else 1

    if args.proposal:
        prop = load_json(Path(args.proposal).expanduser().resolve(), {})
    else:
        patterns_payload = []
        for idx, spec in enumerate(args.clip, 1):
            parts = spec.split(":")
            pat_id = parts[0] if parts[0] else f"p{idx}-move"
            start_s = float(parts[1]) if len(parts) > 1 else 2.0 * idx
            dur_s = float(parts[2]) if len(parts) > 2 else 2.0
            patterns_payload.append({
                "id": pat_id,
                "title": f"招式 · {pat_id}",
                "when_to_use": f"从 {source_path.name} 提炼的代表片段",
                "rule": args.summary,
                "clip": {"start_sec": start_s, "dur_sec": dur_s},
            })
        prop = {
            "style_id": args.style,
            "source_project": source_path.stem if source_path.is_file() else source_path.name,
            "summary": args.summary,
            "version": args.version,
            "rules": [],
            "patterns": patterns_payload,
        }
    res = apply_proposal(prop, vault, video_source=source_path, confirmed=args.confirm)
    print(json.dumps(res, ensure_ascii=False, indent=2))
    return 0 if res["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
