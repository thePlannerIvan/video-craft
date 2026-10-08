"""EDL 剪接预演面（第四条形状：**在板子上挑**）的回归网。

**基线是"无覆盖"**：接缝之前这一条线没有任何测试（`apply_selection` 只在 `test_edit_contracts.py`
的注释里出现过一次，`edl_preview_build/serve` 与 `selections.json` 零覆盖）。这个文件是它的
**第一张**回归网 —— 接缝顺带给它一张网，本身就是一项产出。

要证明的事：

  ① **面的形状**：`dir` ＝ 素材与剪辑目录的**公共根**（页面里那些 `/<素材>.mp4` 从写出来那天起
     就假定 serve root 是它）；`entry` 相对 `dir`；`feedback` 就是 `selections.json`
     （保存语义整份覆盖，与旧 `/api/save` **1:1**，不需要任何收件层形状翻译）；`watch` 盯 `edl.json`。
  ② **页面契约**：裸标记只此一次（R3）· **R11** 永久刷新出口且是**纯 HTML 链接**（不依赖页面自己的
     JS）· **R10** 整体入口（只 wake、不写 `selections.json`）· 没有顶层读存储（不透明源陷阱）·
     **没有任何 `await` 排在渲染前面**。
  ③ **验证第 12 条**：加载后断页**真的长出了内容**（DOM 里的词数），不是只看宿主返回 ok。
  ④ **验证第 13 条（反面对照）**：把 `connect()` 换成**永不返回** → 页面**仍须**完整画出来。
  ⑤ **保存**：拖选一个词 → 保存 → `selections.json` 被整份覆盖，键与旧时代一致（含照旧写回去的 `dir`）。
  ⑥ **整体意见**：只 wake，**不写** `selections.json`。
  ⑦ **Range**：真素材（四个真项目里素材最大的那个）上 `bytes=0-1023` **只发 1024 B**。

跑法：`tests/` 下
    PYTHONPATH=..:../helpers python -m unittest test_edl_review
加了 `VIDEO_CRAFT_BROWSER_TESTS=1` 才跑浏览器那几条（DOM / 反面对照 / 保存 / 整体意见）。

真项目**只读**：测试自己把它硬链接成一个工作副本（大素材不复制），在副本里改与写。
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

HELPERS = Path(__file__).parents[1] / "helpers"
VIDEO_CRAFT = Path(__file__).parents[1]
sys.path.insert(0, str(HELPERS))
sys.path.insert(0, str(HELPERS / "lib"))

from lib.planners_modules import resolve_module  # noqa: E402
sys.path.insert(0, str(resolve_module('planners-review-core') / 'scripts' / 'lib'))
import review_host            # noqa: E402
import edl_review_surface     # noqa: E402

# 只挑**正常词**：`#w-root .w` 还会命中"已剪内容"里的 `.w.cut`，拖那些走的是"恢复"那条分支。
WORDS = "#w-root .wseg span.w:not(.cut)"
WORKSPACE = VIDEO_CRAFT.parents[2]              # …/CodexProject（video-craft → 03-design-delivery → 02-skills-library → 根）
REAL_PROJECTS = WORKSPACE / "05-VideoProject"


def have_playwright():
    try:
        import playwright.sync_api  # noqa: F401
        return True
    except ImportError:
        return False


def biggest_real_project():
    """四个真项目里素材最大的那个（Range 要在真大小的文件上验，不是在玩具上）。"""
    chosen = None
    for edl in sorted(REAL_PROJECTS.glob("*/edit/edl.json")):
        try:
            doc = json.loads(edl.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        total = 0
        for value in (doc.get("sources") or {}).values():
            path = Path(value)
            path = path if path.is_absolute() else (edl.parent / path)
            if path.is_file():
                total += path.stat().st_size
        if total and (chosen is None or total > chosen[1]):
            chosen = (edl.parent.parent, total)
    return chosen


def make_work_copy(project: Path, into: Path) -> Path:
    """把真项目硬链接成副本：小文件复制、`.mp4` 只 `link`（同 inode，不占空间、也不用等）。

    **不能用符号链接**：宿主对静态文件做 realpath 包含性校验，指向根外的软链会被（正确地）404。
    硬链接的路径就在根里，所以既省空间又照常能 Range。
    """
    target = into / project.name
    target.mkdir(parents=True)
    for src in project.rglob("*"):
        if not src.is_file():
            continue
        rel = src.relative_to(project)
        dest = target / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        if src.suffix.lower() in (".mp4", ".mov", ".m4v"):
            os.link(src, dest)
        else:
            shutil.copy2(src, dest)
    # 副本里 edl.json 的素材路径指回**真项目**的绝对路径 → 公共根会被拉到工作区顶上。
    # 改写成"从剪辑目录到副本里那份素材"的相对路径（副本与原项目同一套布局，所以这个相对
    # 路径一模一样）。**不许压平成 `../<文件名>`**：真项目会把素材放在子目录里
    # （实测 `../assets/BLACK_talk.mp4`），压平之后那个 URL 在 serve root 下根本不存在。
    edit = target / "edit"
    original_edit = project / "edit"
    doc = json.loads((edit / "edl.json").read_text(encoding="utf-8"))
    for key, value in list((doc.get("sources") or {}).items()):
        source = Path(value)
        source = source if source.is_absolute() else (original_edit / source)
        doc["sources"][key] = os.path.relpath(source.resolve(), original_edit).replace(os.sep, "/")
    (edit / "edl.json").write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    return edit


def http(url, headers=None):
    """返回 (status, 大小写不敏感的响应头, 字节)。HTTP 头名大小写不敏感，所以按小写存。"""
    request = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(request) as response:
            return response.status, {k.lower(): v for k, v in response.headers.items()}, response.read()
    except urllib.error.HTTPError as error:
        return error.code, {k.lower(): v for k, v in error.headers.items()}, error.read()


class EdlRealProjectCase(unittest.TestCase):
    """真项目（硬链接副本）：建页 → 面 → 宿主 → Range。**只读真项目本身。**"""

    @classmethod
    def setUpClass(cls):
        found = biggest_real_project()
        if found is None:
            raise unittest.SkipTest("找不到带 edl.json 的真项目")
        cls.real, cls.real_bytes = found
        cls.tmp = Path(tempfile.mkdtemp(prefix="edl-review-real-")).resolve()
        cls.edit = make_work_copy(cls.real, cls.tmp)
        for script in ("edl_preview_build.py",):
            done = subprocess.run([sys.executable, str(HELPERS / script), str(cls.edit)],
                                  capture_output=True, text=True)
            if done.returncode != 0:
                raise AssertionError(f"{script} 失败：{done.stdout}{done.stderr}")
        cls.info = edl_review_surface.open_review(cls.edit, open_browser=False)
        cls.base = f"http://127.0.0.1:{cls.info['port']}"
        cls.page_text = (cls.edit / "edl_preview.html").read_text(encoding="utf-8")

    @classmethod
    def tearDownClass(cls):
        review_host.stop_host(cls.info)
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_the_real_project_still_points_its_media_outside_the_edit_dir(self):
        """这一面的形状之所以是"公共根"，是因为素材天生在剪辑目录之外。先把这个前提钉住。"""
        edit = self.real / "edit"
        doc = json.loads((edit / "edl.json").read_text(encoding="utf-8"))
        outside = []
        for value in doc["sources"].values():
            path = Path(value)
            path = path if path.is_absolute() else (edit / path)
            if not str(path.resolve()).startswith(str(edit.resolve()) + os.sep):
                outside.append(path)
        self.assertTrue(outside, "这个真项目的素材应当在 edit_dir 之外（不然这一面就没必要取公共根）")
        self.assertEqual(edl_review_surface.common_root(self.edit), self.tmp / self.real.name)

    def test_a_single_range_sends_exactly_that_many_bytes_not_the_whole_file(self):
        """**"看着像支持"不算** —— 这条断言的是**实收字节数**，用的是真素材的真实大小。"""
        asset = next((self.real / "edit").parent.glob("*.mp4"))
        size = asset.stat().st_size
        self.assertGreater(size, 100 * 1024 * 1024, "该用素材最大的那个真项目来验 Range")
        url = f"{self.base}/{urllib.parse.quote(asset.name)}"

        status, headers, body = http(url, {"Range": "bytes=0-1023"})
        self.assertEqual(status, 206)
        self.assertEqual(len(body), 1024, f"只该发 1024 B，不是整个 {size} B")
        self.assertEqual(headers["content-range"], f"bytes 0-1023/{size}")
        self.assertEqual(headers["content-length"], "1024")
        self.assertEqual(headers["accept-ranges"], "bytes")
        with open(asset, "rb") as handle:
            self.assertEqual(body, handle.read(1024), "取回的要真的是**那一段**字节")

        status, headers, body = http(url)
        self.assertEqual(status, 200)
        self.assertEqual(len(body), size)
        self.assertEqual(headers["accept-ranges"], "bytes", "整份也要声明能分段，否则浏览器不知道可以 seek")

        status, headers, body = http(url, {"Range": f"bytes={size}-"})
        self.assertEqual(status, 416)
        self.assertEqual(headers["content-range"], f"bytes */{size}")
        self.assertEqual(len(body), 0)

    def test_the_service_root_is_the_common_root_so_the_pages_media_urls_are_unchanged(self):
        """页面里那些 `/<素材>.mp4` 是**相对 serve root**（公共根）写的 —— 这也是 `dir` 的取值理由。"""
        self.assertTrue((self.tmp / self.real.name / "edit").is_dir())
        self.assertIn("{{REVIEW_BRIDGE}}", self.page_text, "磁盘上那一份带着注入点")
        entry = json.loads((self.edit / "edl_review_surface.json").read_text(encoding="utf-8"))["entry"]
        status, _, body = http(f"{self.base}/{urllib.parse.quote(entry)}")
        self.assertEqual(status, 200)
        text = body.decode("utf-8")
        self.assertNotIn("{{REVIEW_BRIDGE}}", text, "serve 出去的页面里注入点必须已被换掉")
        self.assertIn("/__review/bridge.js", text)
        self.assertIn("const SEGS = [", text)
        # 页面给播放器的 URL 一律是 **serve root 下的绝对路径**（`/xxx.mp4`）——这一条从写出来
        # 那天起就假定 serve root 是公共根，也是 `dir` 取公共根的理由。逐个核对真的能落到文件上。
        match = re.search(r"^const SRC = (\{.*?\});$", text, re.M)
        self.assertIsNotNone(match, "页面里没有 const SRC = {…}")
        src = json.loads(match.group(1))
        self.assertTrue(src, "SRC 不该是空的")
        for key, url in src.items():
            with self.subTest(key=key):
                self.assertFalse(url.startswith("/"), f"{url} 必须相对 surface dir")
                self.assertTrue((self.edit.parent / url.lstrip("/")).is_file(),
                                f"{url} 在 serve root（公共根）下不存在")
        self.assertIn('await review.asset(SRC[key])', text)

    def test_the_page_is_served_and_really_grows_content(self):
        """**验证第 12 条**：不只看宿主 ok —— 断言磁盘上这一页真的带着内容（词/段/时间轴数据）。"""
        text = self.page_text
        self.assertIn("const SEGS = [", text)
        self.assertIn("id=\"w-root\"", text)
        self.assertIn("const CUES = ", text)
        # 页面的内联数据规模：这一版是 58 段 / 2694 词那一档，至少得是"有很多"，不是空壳
        self.assertGreater(len(text), 200_000, f"页面才 {len(text)} 字节 —— 内联数据没进去？")

    def test_selections_written_here_are_a_whole_file_overwrite_with_the_old_keys(self):
        """保存在收件层**不需要任何形状翻译**：就是整份覆盖。`dir` 照旧写回去（删掉＝改形状）。"""
        payload = {"words": [{"src": "x", "start": 1.0, "end": 1.4}],
                   "pauses": [], "restore": [], "fixes": [], "dir": f"/{self.real.name}/edit"}
        request = urllib.request.Request(
            f"{self.base}/__review/write", data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(request) as response:
            self.assertEqual(response.status, 200)
            self.assertTrue(json.loads(response.read())["ok"])
        saved = json.loads((self.edit / "selections.json").read_text(encoding="utf-8"))
        self.assertEqual(saved, payload, "整份覆盖、字段一个不多一个不少")
        self.assertEqual(sorted(saved), ["dir", "fixes", "pauses", "restore", "words"])


class EdlPageContractCase(unittest.TestCase):
    """页面的静态契约（不起宿主、不开浏览器）。"""

    @classmethod
    def setUpClass(cls):
        source = (HELPERS / "edl_preview_build.py").read_text(encoding="utf-8")
        cls.html = source[source.index('HTML = """'):source.index('"""\n\ndata = {')]

    def test_the_injection_point_is_a_bare_marker_appearing_exactly_once(self):
        """R3：裸标记独占一行，全页只此一次（塞进 src="" 或 <script> 里都会炸）。"""
        self.assertEqual(self.html.count("{{REVIEW_BRIDGE}}"), 1)
        for line in self.html.splitlines():
            if "{{REVIEW_BRIDGE}}" in line:
                self.assertEqual(line.strip(), "{{REVIEW_BRIDGE}}", "标记必须裸着独占一行")

    def test_the_page_can_always_refresh_itself_plain_html_no_js_needed(self):
        """R11：入口**无条件存在**、不在告警里、而且是纯 HTML 链接（页面自己的 JS 坏了也能用）。"""
        self.assertIn('id="page-reload"', self.html)
        head = self.html[self.html.index('id="page-reload"') - 120:self.html.index('id="page-reload"') + 120]
        self.assertIn("<a", head)
        self.assertIn('href=""', head)
        self.assertNotIn("onclick", head)
        self.assertLess(self.html.index('id="page-reload"'), self.html.index('id="staleness"'))

    def test_an_overall_opinion_has_its_own_entry_and_does_not_touch_selections(self):
        """R10：整体一句**只走 wake、不写 selections.json**（写进去会被 apply_selection 静默忽略）。"""
        self.assertIn('id="ov-text"', self.html)
        self.assertIn('id="ov-send"', self.html)
        start = self.html.index('document.getElementById("ov-send")')
        block = self.html[start:self.html.index("(async () => {", start)]
        self.assertIn("review.wake(", block)
        self.assertNotIn("review.write(", block, "整体那一条不许写文件")

    def test_rendering_is_not_behind_any_await(self):
        """**渲染必须排在第一个 `await` 之前**（验证第 12/13 条的结构性那一半）。"""
        # 内联数据 → 同步画完；桥的接线在**整页渲染之后**的 IIFE 里
        self.assertLess(self.html.index("const SEGS = __SEGS__;"), self.html.index("ReviewBridge.connect"))
        self.assertLess(self.html.index("const SEGS = __SEGS__;"), self.html.index("(async () => {"))
        for marker in ("SEGS.forEach", "wstats();"):
            self.assertLess(self.html.index(marker), self.html.index("ReviewBridge.connect"),
                            f"{marker} 必须在接线之前")
        # 接线之前不许有 **top-level** await（列 0 的 await）。点事件处理器（`async () => {…}`）
        # 里面的 await 不算 —— 那些要人来点才会跑，而渲染早就同步画完了。
        before = self.html[:self.html.index("(async () => {")]
        top_level = [line for line in before.splitlines() if line.startswith("await ")]
        self.assertEqual(top_level, [], "渲染前面不许有 top-level await —— 那会把整页挂在握手上")

    def test_no_top_level_storage_reads(self):
        """不透明源陷阱：顶层读 localStorage/sessionStorage 会**整页静默死**。"""
        self.assertNotIn("localStorage", self.html)
        self.assertNotIn("sessionStorage", self.html)

    def test_saving_goes_through_the_bridge_not_a_hardcoded_endpoint(self):
        self.assertIn("review.write(payload)", self.html)
        self.assertNotIn('fetch("/api/save"', self.html)
        self.assertIn("helpers/apply_selection.py", self.html, "门铃那句要说清下一步跑什么")


@unittest.skipUnless(os.environ.get("VIDEO_CRAFT_BROWSER_TESTS") == "1",
                     "set VIDEO_CRAFT_BROWSER_TESTS=1 for the browser cases")
@unittest.skipUnless(have_playwright(), "needs playwright")
class EdlBrowserCase(unittest.TestCase):
    """浏览器：DOM 真的画出来 / 反面对照 / 保存 / 整体意见（真项目副本上跑）。"""

    @classmethod
    def setUpClass(cls):
        from playwright.sync_api import sync_playwright
        found = biggest_real_project()
        if found is None:
            raise unittest.SkipTest("找不到带 edl.json 的真项目")
        cls.tmp = Path(tempfile.mkdtemp(prefix="edl-review-browser-")).resolve()
        cls.edit = make_work_copy(found[0], cls.tmp)
        subprocess.run([sys.executable, str(HELPERS / "edl_preview_build.py"), str(cls.edit)],
                       capture_output=True, text=True, check=True)
        cls.info = edl_review_surface.open_review(cls.edit, open_browser=False)
        # **整类共用一个浏览器**：原来每个用例各起一次（4 次），而这个 fixture 还压着一个
        # 2 GB 的硬链接项目 + 一个真宿主 —— 连着起浏览器时偶发过一次 ERROR（全量跑一次、
        # 单独跑与连跑两次都过）。启动次数降到 1 是从结构上收掉这类抖动，不是靠重试。
        cls.pw = sync_playwright().start()
        cls.browser = cls.pw.chromium.launch()

    @classmethod
    def tearDownClass(cls):
        # 失败也要收干净：原来失败路径不关浏览器 → Chromium 残留 → 后面的启动更容易抖。
        try:
            cls.browser.close()
        finally:
            cls.pw.stop()
            review_host.stop_host(cls.info)
            shutil.rmtree(cls.tmp, ignore_errors=True)

    def open_page(self, stub_bridge=None):
        page = self.browser.new_page()
        self.addCleanup(page.close)
        if stub_bridge is not None:
            page.route("**/__review/bridge.js", lambda route: route.fulfill(
                status=200, content_type="text/javascript", body=stub_bridge))
        page.goto(self.info["url"], wait_until="load")
        page.wait_for_selector(WORDS, timeout=20000)
        return page

    def test_the_page_really_renders_the_words_and_the_timeline(self):
        """**验证第 12 条**：DOM 断言 —— 逐字面板里真的长出了几千个词、时间轴有刻度。"""
        page = self.open_page()
        words = page.locator(WORDS).count()
        self.assertGreater(words, 500, f"逐字面板只画出 {words} 个词 —— 会不会是空壳？")
        self.assertTrue(page.locator("#ruler").count() or page.locator("#track").count()
                        or page.locator("canvas").count(), "时间轴没画出来")
        self.assertTrue(page.locator("#w-save").is_visible())
        self.assertTrue(page.locator("#page-reload").is_visible(), "R11：刷新入口必须一直可见")
        self.assertTrue(page.locator("#ov-text").is_visible(), "R10：整体入口必须一直可见")
        self.assertIn("已连接审阅宿主", page.inner_text("#net"))

    def test_the_page_still_renders_when_the_handshake_never_returns(self):
        """**验证第 13 条（反面对照）**：`connect()` 换成**永不返回** → 页面仍须完整画出来。

        video-idea 的念稿面在这里翻过车：`boot()` 把 `render()` 挂在 `await connect()` 上，
        `try/catch` 只接得住"拒绝"、接不住"一直不返回" → 插件路径下只显示静态骨架、逐段全空、
        **零报错**（上一轮验收只验了 `review_open` 的返回，没验页面）。
        """
        stub = "window.ReviewBridge = { connect: () => new Promise(() => {}), };"
        page = self.open_page(stub_bridge=stub)
        words = page.locator(WORDS).count()
        self.assertGreater(words, 500, f"握手永不返回时只剩 {words} 个词 —— 渲染被挂在握手上了")
        self.assertIn("正在连接审阅宿主", page.inner_text("#net"), "连接状态就该停在「正在连接」那一档")

    def test_drag_select_then_save_writes_the_file_and_rings_the_bell(self):
        """真交互：拖选一个词 → 保存 → `selections.json` 整份覆盖 + wake 落日志。"""
        page = self.open_page()
        first = page.locator(WORDS).nth(20)
        third = page.locator(WORDS).nth(23)
        # 必须先滚进视口：这一页 `min-width:1280px`、逐字面板在很下面，实测第 20 个词在
        # y≈1179（视口高 720）—— 不滚的话鼠标点落在视口外，`mouseover` 根本碰不到词。
        first.scroll_into_view_if_needed()
        third.scroll_into_view_if_needed()
        box1, box2 = first.bounding_box(), third.bounding_box()
        self.assertIsNotNone(box1)
        page.mouse.move(box1["x"] + box1["width"] / 2, box1["y"] + box1["height"] / 2)
        page.mouse.down()
        page.mouse.move(box2["x"] + box2["width"] / 2, box2["y"] + box2["height"] / 2, steps=6)
        page.mouse.up()
        page.wait_for_function(
            "() => !/0 处选中/.test(document.getElementById('wstats').textContent)", timeout=8000)
        page.click("#w-save")
        page.wait_for_function(
            "() => /已保存/.test(document.getElementById('w-save').textContent)", timeout=15000)
        saved = json.loads((self.edit / "selections.json").read_text(encoding="utf-8"))
        self.assertEqual(sorted(saved), ["dir", "fixes", "pauses", "restore", "words"])
        self.assertTrue(saved["words"], "拖选之后 words 不该是空的")
        # `dir` ＝ 页面 URL 去掉文件名（`location.pathname` 的老口径），也就是"这一页相对
        # serve root 在哪"。真项目历史值就是 `/edit`（四个项目全是），所以要按面自己声明的
        # entry 算出来比，不能想当然是 `/<项目名>/edit`。
        entry = json.loads((self.edit / "edl_review_surface.json").read_text(encoding="utf-8"))["entry"]
        expected = "/" + Path(entry).parent.as_posix()
        self.assertEqual(saved["dir"], expected,
                         "`dir` 照旧写回去（与旧服务器时代逐字节同一个口径）")
        self.assertEqual(expected, "/edit", "真项目的历史值就是 /edit（四个项目全一致）")
        self.assertEqual(set(saved["words"][0]), {"src", "start", "end"})
        # 门铃：wake 落在 surface 旁边那一刻的日志里
        wake_log = self.edit / review_host.WAKE_LOG_NAME
        self.assertTrue(wake_log.is_file(), "保存之后应当敲一下门铃")
        self.assertIn("apply_selection.py", wake_log.read_text(encoding="utf-8"))

    def test_an_overall_opinion_goes_to_the_conversation_and_leaves_the_file_alone(self):
        """R10 的另一条通道：整体一句 → wake 里有它，`selections.json` **一个字节不变**。"""
        target = self.edit / "selections.json"
        before = target.read_bytes() if target.is_file() else None
        page = self.open_page()
        page.fill("#ov-text", "整段节奏偏慢，这一版剪点我想重挑")
        page.click("#ov-send")
        page.wait_for_function(
            "() => /已发回对话/.test(document.getElementById('ov-state').textContent)", timeout=15000)
        after = target.read_bytes() if target.is_file() else None
        self.assertEqual(before, after, "整体意见**不许**动 selections.json")
        wake_log = (self.edit / review_host.WAKE_LOG_NAME).read_text(encoding="utf-8")
        self.assertIn("整段节奏偏慢", wake_log)
        self.assertIn("整段", wake_log)
