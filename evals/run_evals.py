#!/usr/bin/env python3
"""`run_evals` —— 验收用例的结构校验 + 路线覆盖矩阵。不调模型、不碰项目。

为什么只做结构校验
------------------
`evals.json` 的用例是给模型读的行为判据（prompt + must_do / must_not_do），
判断"模型做没做到"需要人或有模型参与，脚本判不了。但"这份用例文件本身还能不能用"
是机械的：字段齐不齐、id 有没有重复、路线标签在不在、新路线有没有用例覆盖。
2026-11 之前这七条用例全停在 recompose 时代（montage / frame / 素材清单 / 返修
零命中）却没人发现，就是因为只有 `json.tool` 验语法。

跑法（Skill 根）：
    python3 evals/run_evals.py

输出：逐条 PASS/FAIL + 路线矩阵 + 话题覆盖；退码 0 = 全过，1 = 有错。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
EVALS = HERE / "evals.json"

ROUTES = ("recompose", "montage", "frame", "shared")
# 每条路线至少要有几条用例。shared 是横切片型/路线都成立的用例（工程态、返修、交付）。
ROUTE_MINIMUM = {"recompose": 1, "montage": 1, "frame": 1, "shared": 1}

# 新增路线（montage / frame）的用例必须在 must_do 里落到真实入口上，否则 route 只是标签。
ROUTE_ANCHORS = {
    "recompose": (),
    "montage": ("montage.py", "scan_materials", "素材清单", "镜头表"),
    "frame": ("frame.py", "画框", "token"),
    "shared": (),
}

# 话题覆盖：这些是 2026-11 升级要防的"死文档"缺口，每条至少命中一条用例。
TOPICS = (
    ("素材清单", ("scan_materials", "material-inventory", "素材清单")),
    ("镜头表/plan", ("montage.py", "montage-plan", "镜头表")),
    ("画框/预览落位", ("frame.py", "frame-spec", "画框", "preview", "contain")),
    ("返修闭环", ("review_inbox", "收件", "返修", "重建审阅", "重建快照")),
    ("终态分级", ("_engineering", "成品/", "审阅素材", "交付件")),
)

ID_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
MIN_ITEM_CHARS = 6          # 短于这个长度的判据基本是"注意/小心"式空话

CASE_KEYS = ("id", "route", "prompt", "must_do", "must_not_do")


def load_cases(path):
    """返回 (cases, errors)。兼容数组和 {'evals': [...]} / {'cases': [...]} 两种形状。"""
    try:
        blob = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        return [], ["读不到 %s：%s" % (path, exc)]
    except ValueError as exc:
        return [], ["%s 不是合法 JSON：%s" % (path, exc)]
    if isinstance(blob, dict):
        blob = blob.get("evals") or blob.get("cases")
    if not isinstance(blob, list):
        return [], ["用例必须是数组（或含 evals/cases 数组的对象）"]
    if not blob:
        return [], ["用例数组为空"]
    return blob, []


def text_of(case):
    """一条用例的全部可读文本，用来算话题覆盖。"""
    parts = [case.get("prompt") or ""]
    for key in ("must_do", "must_not_do"):
        value = case.get(key)
        if isinstance(value, list):
            parts.extend(x for x in value if isinstance(x, str))
    return "\n".join(parts)


def check_case(index, case, seen_ids):
    """返回 (errors, warnings, route)。"""
    errors, warnings = [], []
    label = "evals[%d]" % index
    if not isinstance(case, dict):
        return ["%s 必须是对象" % label], [], None

    for key in CASE_KEYS:
        if key not in case:
            errors.append("%s 缺少字段 %s" % (label, key))
    case_id = case.get("id")
    if not isinstance(case_id, str) or not case_id.strip():
        errors.append("%s.id 必须是非空字符串" % label)
        case_id = None
    else:
        if not ID_PATTERN.match(case_id):
            errors.append("%s.id 必须是 kebab-case：%s" % (label, case_id))
        if len(case_id) > 64:
            errors.append("%s.id 超过 64 字符：%s" % (label, case_id))
        if case_id in seen_ids:
            errors.append("%s.id 重复：%s" % (label, case_id))
        else:
            seen_ids.add(case_id)

    route = case.get("route")
    if route is None:
        # 老用例允许从文本推断一次，推断不出才是错；推断出来给一条提示。
        guessed = guess_route(case)
        if guessed is None:
            errors.append("%s 缺少 route，且文本里推断不出" % label)
        else:
            warnings.append("%s 没有 route，按文本推断为 %s" % (label, guessed))
            route = guessed
    elif route not in ROUTES:
        errors.append("%s.route 不在 %s 里：%r" % (label, "/".join(ROUTES), route))
        route = None

    prompt = case.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        errors.append("%s.prompt 必须是非空字符串" % label)

    for key in ("must_do", "must_not_do"):
        value = case.get(key)
        if not isinstance(value, list) or not value:
            errors.append("%s.%s 必须是非空数组" % (label, key))
            continue
        items = []
        for pos, item in enumerate(value):
            if not isinstance(item, str) or not item.strip():
                errors.append("%s.%s[%d] 必须是非空字符串" % (label, key, pos))
                continue
            if len(item.strip()) < MIN_ITEM_CHARS:
                errors.append("%s.%s[%d] 太短，写不成可判断的行为：%r"
                              % (label, key, pos, item))
            items.append(" ".join(item.split()))
        if len(set(items)) != len(items):
            errors.append("%s.%s 有重复项" % (label, key))

    do = [" ".join(x.split()) for x in case.get("must_do") or []
          if isinstance(x, str)]
    dont = [" ".join(x.split()) for x in case.get("must_not_do") or []
            if isinstance(x, str)]
    both = sorted(set(do) & set(dont))
    if both:
        errors.append("%s 同一条判据同时出现在 must_do 与 must_not_do：%s"
                      % (label, both[0]))

    if route in ROUTE_ANCHORS and ROUTE_ANCHORS[route]:
        blob = "\n".join(do)
        if not any(anchor in blob for anchor in ROUTE_ANCHORS[route]):
            errors.append("%s 标了 route=%s，但 must_do 没落到该路线入口（%s）"
                          % (label, route, " / ".join(ROUTE_ANCHORS[route])))
    return errors, warnings, route


def guess_route(case):
    blob = text_of(case)
    hits = {
        "montage": ("montage.py", "素材清单", "镜头表", "montage-route"),
        "frame": ("frame.py", "画框", "frame-spec"),
        "recompose": ("composition", "recompose", "edl"),
    }
    scores = {route: sum(1 for word in words if word in blob)
              for route, words in hits.items()}
    best = max(scores, key=lambda route: scores[route])
    return best if scores[best] else None


def list_len(case, key):
    value = case.get(key) if isinstance(case, dict) else None
    return len(value) if isinstance(value, list) else 0


def render(cases, routes):
    lines = []
    passed = 0
    for index, case in enumerate(cases):
        case_id = case.get("id") if isinstance(case, dict) else None
        route = routes[index]
        do_n = list_len(case, "must_do")
        dont_n = list_len(case, "must_not_do")
        error = index in FAILED
        lines.append("%s  %-42s route=%-9s must_do=%d must_not_do=%d"
                     % ("FAIL" if error else "PASS", case_id or "?", route or "-",
                        do_n, dont_n))
        passed += 0 if error else 1
    return lines, passed


FAILED = {}


def main(argv=None):
    parser = argparse.ArgumentParser(description="校验 evals.json 结构与路线覆盖")
    parser.add_argument("--json", help="把覆盖矩阵写成 JSON 文件（给人或 CI 看）")
    args = parser.parse_args(argv)

    FAILED.clear()
    errors, warnings = [], []
    cases, load_errors = load_cases(EVALS)
    errors.extend(load_errors)

    seen_ids = set()
    routes = []
    for index, case in enumerate(cases):
        case_errors, case_warnings, route = check_case(index, case, seen_ids)
        errors.extend(case_errors)
        warnings.extend(case_warnings)
        routes.append(route)
        if case_errors:
            FAILED[index] = case_errors

    # 同一段判据可以出现在不同用例里（角度不同），但整份重复的 prompt 多是复制粘贴。
    prompts = {}
    for index, case in enumerate(cases):
        if not isinstance(case, dict):
            continue
        prompt = (case.get("prompt") or "").strip()
        if not prompt:
            continue
        if prompt in prompts:
            FAILED.setdefault(index, []).append(
                "与 evals[%d] 的 prompt 完全相同" % prompts[prompt])
            errors.append("evals[%d].prompt 与 evals[%d] 重复"
                          % (index, prompts[prompt]))
        else:
            prompts[prompt] = index

    counts = {route: 0 for route in ROUTES}
    for route in routes:
        if route in counts:
            counts[route] += 1
    for route, minimum in ROUTE_MINIMUM.items():
        if counts[route] < minimum:
            errors.append("路线覆盖不足：%s 有 %d 条，至少 %d 条"
                          % (route, counts[route], minimum))

    topic_hits = {}
    for topic, words in TOPICS:
        hits = []
        for index, case in enumerate(cases):
            if not isinstance(case, dict):
                continue
            blob = text_of(case)
            if any(word in blob for word in words):
                hits.append(str(case.get("id") or "evals[%d]" % index))
        topic_hits[topic] = hits
        if not hits:
            errors.append("话题覆盖缺口：没有用例命中「%s」（%s）"
                          % (topic, " / ".join(words)))

    # ── 输出 ────────────────────────────────────────────────────────────
    print("%s：%d 条用例" % (EVALS.relative_to(HERE.parent), len(cases)))
    print()
    for index, line in enumerate(render(cases, routes)[0]):
        print(line)
    print()
    print("路线覆盖（下限 %s）" % ", ".join("%s≥%d" % (r, m) for r, m in ROUTE_MINIMUM.items()))
    for route in ROUTES:
        ids = [str(c.get("id")) for i, c in enumerate(cases)
               if routes[i] == route and isinstance(c, dict)]
        print("  %-9s %-2d %s" % (route, counts[route], ", ".join(ids) or "—"))
    unlabeled = len(cases) - sum(counts.values())
    if unlabeled:
        print("  %-9s %-2d %s" % ("未标注", unlabeled, "（route 缺失或非法，按错误处理）"))
    print()
    print("话题覆盖（每条至少 1 条用例）")
    for topic, _ in TOPICS:
        print("  %-12s %-2d %s" % (topic, len(topic_hits[topic]),
                                   ", ".join(topic_hits[topic]) or "—"))

    if warnings:
        print()
        for warning in warnings:
            print("WARN  %s" % warning)
    if errors:
        print()
        for error in errors:
            print("ERROR %s" % error)
        print()
        print("FAIL：%d 项错误（%d/%d 条用例结构通过）"
              % (len(errors), len(cases) - len(FAILED), len(cases)))
        return 1

    print()
    print("PASS：%d/%d 条用例结构合法，路线与话题覆盖满足下限" % (len(cases), len(cases)))
    if args.json:
        payload = {
            "cases": len(cases),
            "routes": counts,
            "topics": {topic: hits for topic, hits in topic_hits.items()},
            "ids": [c.get("id") for c in cases if isinstance(c, dict)],
        }
        Path(args.json).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print("覆盖矩阵已写入 %s" % args.json)
    print("未调用模型：这份用例的语义判据仍需人或模型逐条对照。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
