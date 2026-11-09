#!/usr/bin/env python3
"""风格库的格式、上限与准入：唯一实现。

`extract_style.py`（packet / check / apply / lint）与测试都只调这里。
规则的含义与写法见 references/style-extraction.md；本模块只做机械判断，
不判断一条规则对不对。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]

STAGES = {"idea": "I", "page": "P", "craft": "C"}
STAGE_TITLES = {
    "idea": "创意、口播与素材清单（video-idea-system 读）",
    "page": "静态画面与画框（planners-ppt-hell 读；footage-montage 由 video-craft 画框层读）",
    "craft": "动效、剪辑与声画（video-craft 读）",
}
# 每个阶段与它同时被加载的全局文件；合计行数受 MAX_LOADED_LINES 约束
STAGE_GLOBAL = {"idea": "voice-profile.md", "page": None, "craft": "author-spec.md"}

MAX_ENTRIES = 5          # 每个阶段文件；与 preferences.md「每种风格 ≤5 条」同一口径（按消费者计）
MAX_STAGE_LINES = 40
MAX_LOADED_LINES = 110   # 全局文件 + 阶段文件，与 author-spec.md 的行数上限同一个数
MAX_PATTERNS = 4
MAX_BODY_LINES = 8
CANDIDATE_TTL = 3        # 候选进库后，同风格再做 3 个项目仍未复现 → 删除

REQUIRED_FIELDS = ("做法", "证据", "执行", "依据")
OPTIONAL_FIELDS = ("参数", "例外")
FIELD_ORDER = REQUIRED_FIELDS[:3] + ("参数", "例外", "依据")
BASIS = ("反馈否定", "复现", "作者确认", "迁移")
PRODUCTION_MODES = ("keyframe-svg", "footage-montage")

EVIDENCE_TYPES = ("feedback-negative", "feedback-tendency", "approved-observation", "reference-observation")
RELATIONS = ("新增", "替代", "合并", "补证")

ENTRY_RE = re.compile(r"^##\s+([IPC]\d{2})\s+(.+?)\s*$")
FIELD_RE = re.compile(r"^-\s*(做法|证据|执行|依据|参数|例外)\s*[：:]\s*(.+?)\s*$")
QUOTE_MARKS = ("「", "」", "“", "”")
NUMBER_RE = re.compile(r"[0-9#]")
EXCEPTION_RE = re.compile(r"^[GV]\d{2}$")


# ---------------------------------------------------------------- 阶段文件

def parse_stage(text: str) -> tuple[list[str], list[dict]]:
    """返回（文件头行，条目列表）。条目：{id, title, fields{名: 值}, extra[未识别行]}。"""
    header: list[str] = []
    entries: list[dict] = []
    current: dict | None = None
    for line in text.splitlines():
        m = ENTRY_RE.match(line)
        if m:
            current = {"id": m.group(1), "title": m.group(2), "fields": {}, "extra": []}
            entries.append(current)
            continue
        if current is None:
            header.append(line)
            continue
        if not line.strip():
            continue
        f = FIELD_RE.match(line.strip())
        if f:
            current["fields"][f.group(1)] = f.group(2)
        else:
            current["extra"].append(line)
    return header, entries


def render_stage(style_id: str, stage: str, entries: list[dict]) -> str:
    lines = [
        f"# {style_id} · {stage} · {STAGE_TITLES[stage]}",
        "",
        f"> 条目格式、准入与上限见 video-craft `references/style-extraction.md`；本文件 ≤{MAX_ENTRIES} 条，"
        "由 `extract_style.py lint` 检查。没有条目时按全局判准做。",
    ]
    for e in entries:
        lines += ["", f"## {e['id']} {e['title']}"]
        for name in FIELD_ORDER:
            value = e["fields"].get(name)
            if value:
                lines.append(f"- {name}：{value}")
    return "\n".join(lines) + "\n"


def next_id(stage: str, taken: list[str]) -> str:
    prefix = STAGES[stage]
    nums = [int(t[1:]) for t in taken if t.startswith(prefix) and t[1:].isdigit()]
    return f"{prefix}{(max(nums) + 1) if nums else 1:02d}"


# ---------------------------------------------------------------- 文字检查（lint 与 check 共用）

def text_problems(where: str, title: str, fields: dict) -> list[str]:
    problems: list[str] = []
    for name, value in [("标题", title), *fields.items()]:
        if any(q in (value or "") for q in QUOTE_MARKS):
            problems.append(f"{where} {name} 含引号：规则不引原话，只写结论")
    for name, value in (("标题", title), ("做法", fields.get("做法", ""))):
        if NUMBER_RE.search(value or ""):
            problems.append(f"{where} {name} 含数字或色值：数值写进 style.json params，规则里用 参数 字段引用键名")
    exe = fields.get("执行", "")
    parts = [p.strip() for p in re.split(r"[；;]", exe) if p.strip()]
    if not parts:
        problems.append(f"{where} 执行 为空")
    for part in parts:
        if part.startswith("check:"):
            target = part[len("check:"):].strip().split()[0] if part[len("check:"):].strip() else ""
            if not target or not (SKILL_ROOT / target).exists():
                problems.append(f"{where} check: 指向的路径不存在：{target or '（空）'}")
        elif part.startswith("judgment:"):
            if not part[len("judgment:"):].strip():
                problems.append(f"{where} judgment: 没写看什么")
        else:
            problems.append(f"{where} 执行点缺少 check:/judgment: 前缀：{part}")
    for exc in [x.strip() for x in re.split(r"[、,，]", fields.get("例外", "")) if x.strip()]:
        if not EXCEPTION_RE.match(exc):
            problems.append(f"{where} 例外 只能写全局条目编号（G01 / V03）：{exc}")
    return problems


# ---------------------------------------------------------------- 风格目录

def load_json(path: Path, default):
    if not path.is_file():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return default


def frame_presets(meta: dict) -> list[str]:
    raw = meta.get("default_frame_preset") or meta.get("frame_preset") or ""
    return [p.strip() for p in str(raw).split("/") if p.strip()]


def stage_entries(style_dir: Path, stage: str) -> list[dict]:
    path = style_dir / f"{stage}.md"
    if not path.is_file():
        return []
    return parse_stage(path.read_text(encoding="utf-8"))[1]


def lint_style(vault: Path, style_id: str) -> list[str]:
    sdir = vault / "styles" / style_id
    tag = f"[{style_id}]"
    problems: list[str] = []
    meta = load_json(sdir / "style.json", None)
    if meta is None:
        return [f"{tag} 缺 style.json 或不是合法 JSON"]
    if meta.get("production_mode") not in PRODUCTION_MODES:
        problems.append(f"{tag} production_mode 必须是 {' / '.join(PRODUCTION_MODES)}")
    for preset in frame_presets(meta):
        if not (vault / "frames" / f"{preset}.json").is_file():
            problems.append(f"{tag} 画框预设不存在：frames/{preset}.json")
    params = meta.get("params", {}) or {}
    for key, spec in params.items():
        if not isinstance(spec, dict) or "value" not in spec or spec.get("source") not in ("measured", "author", "inferred"):
            problems.append(f"{tag} params.{key} 需要 value 与 source（measured / author / inferred）")

    seen_ids: set[str] = set()
    for stage, prefix in STAGES.items():
        path = sdir / f"{stage}.md"
        if not path.is_file():
            problems.append(f"{tag} 缺 {stage}.md")
            continue
        text = path.read_text(encoding="utf-8")
        header, entries = parse_stage(text)
        stray = [ln for ln in header if ln.strip() and not ln.startswith("# ") and not ln.startswith("> ")]
        if stray:
            problems.append(
                f"{tag} {stage}.md 含未归入 ## {prefix}01 条目的游离行（所有规则必须写成 ## {prefix}XX 标题 + 四字段）：{stray[0].strip()[:36]}"
            )
        n_lines = len(text.splitlines())
        if len(entries) > MAX_ENTRIES:
            problems.append(f"{tag} {stage}.md 有 {len(entries)} 条，超过 {MAX_ENTRIES} 条上限")
        if n_lines > MAX_STAGE_LINES:
            problems.append(f"{tag} {stage}.md 共 {n_lines} 行，超过 {MAX_STAGE_LINES} 行上限")
        gname = STAGE_GLOBAL[stage]
        if gname and (vault / "global" / gname).is_file():
            loaded = n_lines + len((vault / "global" / gname).read_text(encoding="utf-8").splitlines())
            if loaded > MAX_LOADED_LINES:
                problems.append(f"{tag} {stage} 阶段加载 global/{gname} + {stage}.md 共 {loaded} 行，超过 {MAX_LOADED_LINES}")
        for e in entries:
            where = f"{tag} {stage}.md {e['id']}"
            if not e["id"].startswith(prefix):
                problems.append(f"{where} 编号前缀应为 {prefix}")
            if e["id"] in seen_ids:
                problems.append(f"{where} 编号重复")
            seen_ids.add(e["id"])
            for name in REQUIRED_FIELDS:
                if not e["fields"].get(name):
                    problems.append(f"{where} 缺字段：{name}")
            if e["fields"].get("依据") and e["fields"]["依据"] not in BASIS:
                problems.append(f"{where} 依据 只能是 {' / '.join(BASIS)}")
            body = len(e["fields"]) + len(e["extra"])
            if body > MAX_BODY_LINES:
                problems.append(f"{where} 正文 {body} 行，超过 {MAX_BODY_LINES}")
            if e["extra"]:
                problems.append(f"{where} 有无法识别的行（只允许 - 字段：值）：{e['extra'][0].strip()[:30]}")
            for key in [k.strip() for k in re.split(r"[、,，]", e["fields"].get("参数", "")) if k.strip()]:
                if key not in params:
                    problems.append(f"{where} 引用的参数不存在：params.{key}")
            problems += text_problems(where, e["title"], e["fields"])

    patterns = meta.get("patterns", []) or []
    if len(patterns) > MAX_PATTERNS:
        problems.append(f"{tag} 招式 {len(patterns)} 个，超过 {MAX_PATTERNS} 个上限")
    for p in patterns:
        for key in ("strip", "webm", "code"):
            rel = p.get(key)
            if rel and not (sdir / rel).is_file():
                problems.append(f"{tag} 招式 {p.get('id')} 声明的 {key} 不存在：{rel}")
    return problems


def lint_vault(vault: Path) -> list[str]:
    manifest = load_json(vault / "manifest.json", None)
    if manifest is None:
        return [f"缺 manifest.json：{vault}"]
    problems: list[str] = []
    declared = manifest.get("styles", [])
    on_disk = sorted(p.name for p in (vault / "styles").iterdir() if p.is_dir()) if (vault / "styles").is_dir() else []
    for s in declared:
        if s not in on_disk:
            problems.append(f"manifest 登记了不存在的风格：{s}")
    for s in on_disk:
        if s not in declared:
            problems.append(f"风格目录未在 manifest 登记：{s}")
        problems += lint_style(vault, s)
    return problems


# ---------------------------------------------------------------- 准入

def admission(evidence: list[dict], confirmed: bool) -> tuple[bool, str, str]:
    """返回（是否进入加载文件，依据，说明）。模型不决定这件事。"""
    if confirmed:
        return True, "作者确认", "作者已确认"
    if any(e.get("type") == "feedback-negative" for e in evidence):
        return True, "反馈否定", "作者明确否定过，一次即收"
    projects = {e.get("project") for e in evidence
                if e.get("type") in ("feedback-tendency", "approved-observation", "feedback-negative")}
    if len(projects) >= 2:
        return True, "复现", f"已在 {len(projects)} 个项目出现"
    if evidence and all(e.get("type") == "reference-observation" for e in evidence):
        return False, "", "只来自外部参考片，需作者确认"
    return False, "", f"倾向型，目前 {len(projects)} 个项目，需 2 个项目复现或作者确认"


def evidence_text(evidence: list[dict]) -> str:
    seen: list[str] = []
    for e in evidence:
        item = f"{e.get('project')} {e.get('where')}".strip()
        if item not in seen:
            seen.append(item)
    return "；".join(seen)
