"""视觉审阅面：**这份 surface 的内容**（业务），宿主生命周期全部归公共件。

本 Skill 只做四件事，别的都在 `planners-review-core/scripts/lib/review_host.py`：

  1. `surface_document(root)` —— 写出这份审阅面的内容（`id`/`title`/`dir`/`entry`/`feedback`/
     `wake`/`watch`/`capabilities`）。**这是业务，只有这里知道**：页面在 `review/`、
     反馈先落一份提交文件、要盯时间轴。
  2. 建文档 → 交给模组落盘并校验；
  3. 起/复用/停宿主 —— 直接调模组，本文件**不再实现**（曾经和 ppt-hell 各一份，已经漂移过：
     僵尸判据、SIGKILL 升级）；
  4. `open_review` 里那点**业务前置**：审阅页与时间轴在不在（`check_project`），以及
     `--surface-only` 这个 CLI 开关。

`dir` 为什么是项目根：审阅页在 `<project>/review/index.html`，而它读的时间轴在
`<project>/timeline/timeline.json`。这两处的最近公共祖先是项目根，所以 `dir` 只能取项目根 ——
把审阅页搬进项目根或把时间轴复制进 `review/` 都会改动既有的 `review/` 目录约定（见
`references/architecture.md` 6.4），不在这一轮里做。宿主仍然做包含性校验。

**页面里所有 `rel` 都相对 `dir`（＝项目根）**；`review-surface.json` 里声明的路径（含 `watch`）
相对 **surface 文件**。详见 `references/review-ui.md`。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib.planners_modules import resolve_module                    # noqa: E402
from visual_review_feedback import check_project                   # noqa: E402

# 公共模组里唯一那份宿主生命周期。**模块解析走本 Skill 的适配器**（发布后按名字找兄弟目录），
# 再把它 scripts/lib 放上 sys.path —— 模组自己不需要知道谁在调它。
sys.path.insert(0, str(resolve_module('planners-review-core')/'scripts'/'lib'))
import review_host                                                 # noqa: E402

REVIEW_DIR = 'review'
SURFACE_REL = f'{REVIEW_DIR}/review-surface.json'
HOST_STATE_REL = f'{REVIEW_DIR}/{review_host.HOST_STATE_NAME}'
ID = 'video-craft/visual'
# 一次提交只带一条记录（页面一次审一步）。唤醒语**不自称"只重出这一页"** ——
# 本 Skill 的返修环是「改 composition → npm run check → 重渲染整片」，那句话在这里是假的。
WAKE_TEXT = '{unit} 有一条画面反馈；读 feedback/*.jsonl，按 references/review-ui.md 的协议处理。'
# 宿主只 stat 它（mtime/size），一变就戳页面；**它不知道什么变了**，页面收到戳之后自己
# 重读时间轴、自己 diff（见 review-ui.md「变化戳与陈旧判定」）。
#
# **相对 surface 文件**（＝`review/`），不是相对 `dir`。这个字段曾经三种读法各不相同
# （schema 说相对 surface、校验器按 dir 解析、无插件宿主根本不读），2026-09-26 已统一 ——
# 这正是「第二家」暴露出来的那一条：本 Skill 的页面在 `review/` 子目录里，`dir` 却是项目根，
# 差一级就把歧义变成了错误。
WATCH = ['../timeline/timeline.json']


def surface_path(root):
    """这份 surface 文件在哪（本 Skill 的目录约定，模组不需要知道）。"""
    return Path(root)/SURFACE_REL


def surface_document(root=None):
    """这一份 surface 的内容。`project_root` / `dir` / `entry` / `feedback` 都**相对 surface 文件**。"""
    return {
        'contract_version': review_host.CONTRACT_VERSION,
        'id': ID,
        'title': '逐画面审阅',
        'description': '暂停在出问题的画面上，选中左侧 step 写一条反馈；先落本提交文件，模型收件后追加进 feedback/<chapterId>.jsonl。',
        'project_root': '..',
        'dir': '..',
        'entry': 'review/index.html',
        'feedback': 'review-submissions.json',
        'wake': {'mode': 'queue', 'text': WAKE_TEXT},
        # 本 Skill 没有单位级版本层（review-ui.md 把 `codeVersion` 记为已知缺口）。
        # 不为了适配缝硬造一个版本号；只声明宿主**该盯哪个文件**——时间轴一重派生，
        # 页面上的 step 清单与 caption 就旧了，页面据此提示作者重新加载。
        'watch': list(WATCH),
        # 这个面不上传图片：审阅只需要时间轴与播放器。声明为空就是为空。
        'capabilities': [],
    }


def write_surface(root):
    """建文档 → 交给模组落盘（幂等）。页面与它是同一对产物，所以由「开审阅」那一步一起写。"""
    path = surface_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    return review_host.write_surface(path, surface_document(root))


def validate_surface(root):
    """薄壳：模组收 surface 路径，本 Skill 的调用方习惯给项目根。"""
    return review_host.validate_surface(surface_path(root))


def submissions_path(surface):
    """surface 声明的提交文件（相对 surface 文件解析）。**一份**，不是每章一份 ——
    Skill 侧收件时再翻译成 `feedback/<chapterId>.jsonl` 追加（见 `review_inbox.py`）。"""
    doc = json.loads(Path(surface).read_text(encoding='utf-8'))
    return (Path(surface).parent/str(doc['feedback'])).resolve()


def open_review(root, port=0, open_browser=True, surface_only=False):
    """让作者审阅。**业务前置留在这一层**，宿主生命周期交给模组。

    两种模式，按「宿主有没有 `review_open` 工具」选（Agent 侧一眼可判，Skill 不猜环境）：

      · `surface_only=True` —— **有那个工具时走这条**：只写 surface、校验、报出**绝对路径**
        交给宿主去挂；**不起宿主、不开浏览器**。起了就会有两套界面同时写同一个提交文件。
      · 默认 —— **没有那个工具时走这条**：起无插件宿主（`serve-review.mjs`）并打开浏览器。
    """
    root = Path(root)
    # 业务前置：审阅页与时间轴在不在。缺了就别起宿主 —— 不给人一个存不进去的页面。
    problems = check_project(root)
    if problems:
        raise ValueError('现在还不能开审阅：\n  ' + '\n  '.join(problems))
    surface = write_surface(root)
    validate_surface(root)
    if surface_only:
        return {'status': 'surface_ready', 'surface': str(surface.resolve()),
                'entry': str((root/'review/index.html').resolve()),
                'host_started': False,
                'next_action_zh': '把 surface 的绝对路径交给宿主的 review_open 工具（有插件时）；'
                                  '没有那个工具就重跑 review（不带 --surface-only）起本地宿主。'}
    info = review_host.open_review(surface, port=port, open_browser=open_browser)
    info['next_action_zh'] = ('作者在页面上逐屏提交；没有插件时 wake 落在日志里，'
                              '人回对话说一声「已完成」。模型先跑 helpers/review_inbox.py <project> 收件。')
    return info


def main(argv=None):
    parser = argparse.ArgumentParser(
        description='视觉审阅面：写 review-surface.json，交给公共缝的宿主')
    parser.add_argument('project', help='HyperFrames 项目目录（含 review/ timeline/ composition/）')
    parser.add_argument('--port', type=int, default=0, help='无插件宿主的端口（默认 0＝自动选）')
    parser.add_argument('--no-open', action='store_true', help='不自动打开浏览器')
    parser.add_argument('--surface-only', '--no-host', dest='surface_only', action='store_true',
                        help='只写并校验 surface，报出绝对路径，不起宿主（宿主有 review_open 工具时用这条）')
    args = parser.parse_args(argv)
    project = Path(args.project).expanduser().resolve()
    try:
        result = open_review(project, port=args.port, open_browser=not args.no_open,
                            surface_only=args.surface_only)
    except ValueError as error:
        print(json.dumps({'ok': False, 'error': str(error)}, ensure_ascii=False, indent=1))
        return 2
    print(json.dumps({'ok': True, **result}, ensure_ascii=False, indent=1))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
