"""EDL 剪接预演面：**这份 surface 的内容**（业务），宿主生命周期全部归公共件。

这一面和视觉审阅面（`review_surface.py`）形状不同，值得写清楚它为什么长这样：

  · **它不是"逐单位决定"，是"在板子上挑"**。反馈落点 `selections.json` 没有决定词表
    （不是 approve/revise，而是**选择**：删哪些词、留多少停顿、恢复哪段、改哪个字）。
  · **它仍然声明 `feedback`** —— 因为结果是**下一步要执行的工件**（`apply_selection.py`
    读它去改 EDL），不是一句回对话的话。工件不许穿过人类语言通道：几十上百条浮点区间塞进
    一句 prompt 再变回 JSON 是丢信息的（规则"信息跨过任何一条边界都必须还是同一件事"）。
    `wake` 只当**门铃**。
  · **整体意见（R10）走另一条通道**：页面另给一个「整段意见」入口，它**只 wake、不写
    `selections.json`** —— 写进去会被 `apply_selection.py` 静默忽略（它只 get
    `words/pauses/restore/fixes`），那是一个死字段（R5b 的反面：进了数据却没人读）。

## 为什么 `dir` 是"素材与剪辑目录的公共根"

这一页要在 SOURCE 时间轴上拖 `<video>`，素材**天生在剪辑目录之外**（真项目里 4/4 都是
`edit_dir/..`），而页面里给播放器的 URL 是 `"/<素材文件名>.mp4"` —— 也就是说这个页面从写出来
那天起就假定 **serve root = 公共根**，页面路径 = `relpath(EDIT, ROOT)/edl_preview.html`。

所以 `dir` 取公共根，页面里那些 URL **一个字符都不用改**，`selections.json` 里存的 `dir`
（`/<剪辑目录名>`）也与旧服务器时代**逐字节相同**。代价是宿主会 serve 到 `edit_dir` 之上 ——
这与它自己那台旧服务器**完全同一个姿态**（`edl_preview_serve.py` 的 ROOT 就是这个公共根）。

页面的 `rel` 一律相对 `dir`；surface 里声明的路径（含 `watch`）相对 **surface 文件**。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib.planners_modules import resolve_module                    # noqa: E402

# 公共模组里唯一那份宿主生命周期。**模块解析走本 Skill 的适配器**（发布后按名字找兄弟目录），
# 再把它 scripts/lib 放上 sys.path —— 模组自己不需要知道谁在调它。
sys.path.insert(0, str(resolve_module('planners-review-core')/'scripts'/'lib'))
import review_host                                                 # noqa: E402

SURFACE_NAME = 'edl_review_surface.json'
PAGE_NAME = 'edl_preview.html'
FEEDBACK_NAME = 'selections.json'
EDIT_NAME = 'edl.json'
ID = 'video-craft/edl-preview'
# 宿主只 stat 它（mtime/size），一变就戳页面：这一页的数据是**构建时内联**的，所以 edl.json
# 一动，页面上的时间轴可能就是旧版。宿主不知道什么变了，页面也没法自己 diff（它手上没有
# 构建时那份 edl.json），所以那一条提示只说戳证明了的事。
WATCH = [EDIT_NAME]
WAKE_TEXT = ('{unit}：剪接选择有更新，读 ' + FEEDBACK_NAME + '，跑 helpers/apply_selection.py 应用，'
             '再重出这一页。')
HOST_STATE_REL = review_host.HOST_STATE_NAME                      # 与 surface 同目录


def load_edl(edit: Path) -> dict:
    path = Path(edit)/EDIT_NAME
    if not path.is_file():
        raise ValueError(f'这里不是剪辑目录（没有 {EDIT_NAME}）：{path}')
    return json.loads(path.read_text(encoding='utf-8'))


def common_root(edit: Path) -> Path:
    """剪辑目录与所有素材的公共根 —— 也就是这一面的 `dir`（＝宿主 serve 的那棵树）。

    与 `edl_preview_build.py` / 退役的 `edl_preview_serve.py` **同一个算法**：页面里的素材 URL
    就是这个根下面的绝对路径。取不到公共根就退回剪辑目录（单项目、素材就在旁边的情形）。
    """
    edit = Path(edit).resolve()
    edl = load_edl(edit)
    sources = []
    for value in (edl.get('sources') or {}).values():
        candidate = Path(value)
        sources.append(candidate if candidate.is_absolute() else (edit/candidate))
    try:
        return Path(os.path.commonpath([edit, *[p.resolve() for p in sources]]))
    except ValueError:
        return edit


def rel_root(edit: Path) -> str:
    """`dir` / `project_root` 的值（相对 **surface 文件**，而 surface 与 edl.json 同目录）。"""
    return os.path.relpath(common_root(edit), Path(edit).resolve())


def page_path(edit: Path) -> Path:
    return Path(edit).resolve()/PAGE_NAME


def surface_path(edit: Path) -> Path:
    """这份 surface 文件在哪（本 Skill 的目录约定，模组不需要知道）。"""
    return Path(edit).resolve()/SURFACE_NAME


def surface_document(edit) -> dict:
    """这一份 surface 的内容。四个路径都**相对 surface 文件**（`entry` 再相对 `dir`）。"""
    edit = Path(edit).resolve()
    root = rel_root(edit)
    return {
        'contract_version': review_host.CONTRACT_VERSION,
        'id': ID,
        'title': 'EDL 剪接预演',
        'description': ('在时间线上拖选要删的词/停顿、双击改字；「保存选择」整份覆盖 '
                        + FEEDBACK_NAME + '，回对话说一声「剪」。整段意见另走一道，不写进那份文件。'),
        'project_root': root,
        'dir': root,
        'entry': (Path(edit).relative_to(common_root(edit))/PAGE_NAME).as_posix(),
        'feedback': FEEDBACK_NAME,
        # 唤醒走**插话**（`steer` → `next-step`）：提交的语义是"现在就改"，`queue` 会排到当前回合之后。
        'wake': {'mode': 'steer', 'text': WAKE_TEXT},
        'watch': list(WATCH),
        # 这个面不上传图片（审阅只需要时间轴与播放器）。声明为空就是为空。
        'capabilities': [],
    }


def check_project(edit) -> None:
    """开审阅之前的**业务前置**：剪辑与页面在不在。缺页面就说清怎么产它。"""
    edit = Path(edit).resolve()
    load_edl(edit)
    page = page_path(edit)
    if not page.is_file():
        raise ValueError(f'还没有这一页：{page}\n先跑 helpers/edl_preview_build.py {edit}')


def write_surface(edit):
    """建文档 → 交给模组落盘（幂等）。"""
    path = surface_path(edit)
    path.parent.mkdir(parents=True, exist_ok=True)
    return review_host.write_surface(path, surface_document(edit))


def validate_surface(edit):
    """薄壳：模组收 surface 路径，本 Skill 的调用方习惯给剪辑目录。"""
    return review_host.validate_surface(surface_path(edit))


def feedback_path(surface) -> Path:
    """surface 声明的提交文件（相对 surface 文件解析）。这一面**就是** `selections.json` ——
    保存语义是整份覆盖，与旧 `/api/save` 1:1，所以**不需要任何收件层形状翻译**。"""
    doc = json.loads(Path(surface).read_text(encoding='utf-8'))
    return (Path(surface).parent/str(doc['feedback'])).resolve()


def open_review(edit, port=0, open_browser=True, surface_only=False):
    """清点 → 写 surface → 校验 → 起/复用宿主（`surface_only` 时到此为止）。

    返回宿主状态加上这一面的几个路径，形状与视觉审阅面的 `open_review` 保持一致，
    好让 Skill 的两条线在调用方看来是同一个东西。
    """
    edit = Path(edit).resolve()
    check_project(edit)
    path = write_surface(edit)
    validate_surface(edit)
    base = {'surface': str(path),
            'entry': str(page_path(edit)),
            'feedback_path': str(feedback_path(path))}
    if surface_only:
        return {**base, 'host_started': False,
                'next_action_zh': '把 surface 的绝对路径交给宿主的 review_open 工具（有插件时）；'
                                  '没有那个工具就重跑，不带 --surface-only 起本地宿主。'}
    info = review_host.open_review(path, port=port, open_browser=open_browser)
    return {**info, **base,
            'host_state': str(path.parent/review_host.HOST_STATE_NAME),
            'next_action_zh': '在页面上拖选剪点 → 「保存选择」；整段意见走另一条（只回对话）。'
                              '没有插件时 wake 落在日志里，人回对话说一声「剪」。'}


def main(argv=None):
    parser = argparse.ArgumentParser(description='EDL 剪接预演面：写 surface 并起审阅宿主')
    parser.add_argument('edit_dir')
    parser.add_argument('--port', type=int, default=0)
    parser.add_argument('--no-open', action='store_true')
    parser.add_argument('--surface-only', action='store_true')
    args = parser.parse_args(argv)
    try:
        result = open_review(Path(args.edit_dir).expanduser().resolve(), port=args.port,
                             open_browser=not args.no_open, surface_only=args.surface_only)
    except (ValueError, OSError, json.JSONDecodeError) as error:
        print(str(error))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
