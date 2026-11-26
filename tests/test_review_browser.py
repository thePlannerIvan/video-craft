"""Optional browser/interface smoke: the real review page driven through the review surface.

要证明的事：
  ① 页面加载时注入点已被换掉（页面里不带桥的副本），`ReviewBridge` 真的可用；
  ② 时间轴**经桥**读进来并渲染成 step 清单（不是靠 fetch 相对路径撞上的）；
  ③ 一次提交 → 记录落进 surface 声明的**一份**提交文件，**且** wake 被调用（带 stepId）；
  ④ 收件：把那份提交文件翻译成 `feedback/<chapterId>.jsonl` 的**追加**，
     原有行还在、新行已追加、`.previous/` 备份行为不变；
  ⑤ 重复收件是空操作（内容哈希游标），不会长出第二条。

**不覆盖**：播放器（`<hyperframes-player>` 指向 `localhost:5176` 的预览端点）—— 这个
fixture 里没有 HyperFrames 预览服务，也没有插件宿主。这条是这个面上唯一绕过缝的资产，
插件宿主下能不能加载**没有实测**，不许把这条测试读成"整页在插件下也成立"。

All approvals below are synthetic test data.
"""
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

HELPERS = Path(__file__).parents[1] / "helpers"
TEMPLATE = Path(__file__).parents[1] / "visual" / "assets" / "review-page-template.html"
sys.path.insert(0, str(HELPERS))
sys.path.insert(0, str(HELPERS / "_internal"))
sys.path.insert(0, str(HELPERS / "_internal"))

import review_inbox          # noqa: E402
import review_surface        # noqa: E402
from lib.planners_modules import resolve_module  # noqa: E402
sys.path.insert(0, str(resolve_module('planners-review-core') / 'scripts' / 'lib'))
import review_host  # noqa: E402  （宿主生命周期只有公共模组那一份）


TIMELINE = {
    "totalChapters": 2, "totalSteps": 3, "totalDurationMs": 12000,
    "chapters": [
        {"id": "intro", "title": "开场", "steps": [
            {"id": "intro-001", "step": 1, "caption": "第一屏要说的话", "durationMs": 4000,
             "startMs": 0, "cueRange": [0, 2], "screenIntent": "标题"},
            {"id": "intro-002", "step": 2, "caption": "第二屏要说的话", "durationMs": 4000,
             "startMs": 4000, "cueRange": [2, 4], "screenIntent": "对比"},
        ]},
        {"id": "body", "title": "主体", "steps": [
            {"id": "body-001", "step": 1, "caption": "主体屏要说的话", "durationMs": 4000,
             "startMs": 8000, "cueRange": [4, 6], "screenIntent": "图表"},
        ]},
    ],
}


def submissions_file(project) -> "Path":
    return project / "review" / "review-submissions.json"


def wait_records(path, want, timeout=20.0):
    """轮询落盘文件的行数 —— 比等状态条上那句"本批 N 条"确定（N 取决于作者已有几条）。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
            if len(doc.get("records") or []) >= want:
                return len(doc["records"])
        except (OSError, ValueError):
            pass
        time.sleep(0.1)
    raise AssertionError(f"{path} 没在 {timeout}s 内到 {want} 条")


def have_playwright():
    try:
        import playwright.sync_api  # noqa: F401
        return True
    except ImportError:
        return False


# 2026-10-16 由 opt-in 改为 opt-out：这几条是唯一能抓「审阅页面写读键域不一致」
# 这类缺陷的用例，默认跳过等于让它们永远不跑（作者丢过一次画布改字就是撞在这条
# 未执行路径上）。装不上 playwright 时下面那条 skipUnless 仍会跳过。
@unittest.skipIf(os.environ.get("VIDEO_CRAFT_BROWSER_TESTS") == "0",
                    "set VIDEO_CRAFT_BROWSER_TESTS=0 to skip local browser/interface smoke")
@unittest.skipUnless(have_playwright(), "needs playwright")
class ReviewBrowserTests(unittest.TestCase):
    def setUp(self):
        self.project = Path(tempfile.mkdtemp(prefix="video-craft-browser-")).resolve()
        (self.project / "review").mkdir()
        (self.project / "review" / "index.html").write_text(
            TEMPLATE.read_text(encoding="utf-8"), encoding="utf-8")
        (self.project / "timeline").mkdir()
        (self.project / "timeline" / "timeline.json").write_text(
            json.dumps(TIMELINE, ensure_ascii=False), encoding="utf-8")
        self.exchanges = []
        self.host = review_surface.open_review(self.project, open_browser=False)
        self.addCleanup(self._stop)

    def _stop(self):
        review_host.stop_host(self.host)

    def wire(self, page):
        """把页面与宿主之间**真的发生过的请求**记下来（报告里要给出请求/响应）。

        记的范围比 `/__review/` 大：没插件时 `readText` 是**同源相对 fetch**（走 base），
        不是 `/__review/read`。只盯 `/__review/` 会把「时间轴到底怎么来的」看漏 —— 那正是
        这个面上最容易静默出错的一步（路径差一级就 404，而桥不检查 response.ok）。
        """
        wanted = ("/__review/", "/timeline/", "/review/review-surface.json")

        def on_request(request):
            if any(part in request.url for part in wanted):
                self.exchanges.append(["→", request.method, request.url.split("127.0.0.1")[-1],
                                       (request.post_data or "")[:200]])

        def on_response(response):
            if any(part in response.url for part in wanted):
                self.exchanges.append(["←", response.status, response.url.split("127.0.0.1")[-1], ""])
        page.on("request", on_request)
        page.on("response", on_response)

    def test_page_reads_timeline_through_the_bridge_and_submits(self):
        from playwright.sync_api import sync_playwright

        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page()
            self.wire(page)
            # 这个 fixture 里没有 HyperFrames 预览服务，也没有外网。把这两条外部请求挡掉，
            # 让这次冒烟是确定性的；**播放器因此不在覆盖范围内**（见模块 docstring）。
            page.route("**/localhost:5176/**", lambda route: route.abort())
            page.route("**/cdn.jsdelivr.net/**", lambda route: route.abort())
            page.goto(self.host["url"], wait_until="domcontentloaded")

            # ① 注入点已被换成桥的地址，页面里没有桥的副本
            page.wait_for_function("() => !!window.ReviewBridge", timeout=15000)
            served = page.content()
            self.assertIn("/__review/bridge.js", served)
            self.assertNotIn("{{REVIEW_BRIDGE}}", served)

            # ② 时间轴经桥读进来、渲染成 step 清单
            page.wait_for_selector(".step", timeout=15000)
            page.wait_for_function(
                "() => document.querySelectorAll('.step-caption').length === 3", timeout=15000)
            captions = page.eval_on_selector_all(".step-caption", "els => els.map(e => e.textContent)")
            self.assertIn("第一屏要说的话", captions)
            self.assertIn("主体屏要说的话", captions)
            self.assertIn("2 章 · 3 步", page.inner_text("#project-name"))
            # 保存按钮在桥连上之后才可用 —— 不承诺一个存不进去的页面
            self.assertFalse(page.is_disabled("#fb-save"))

            # ③ **第一条路：不选任何屏，直接说一句整片意见。**
            #    页面默认就落在「整片意见」，所以这里**一个 step 都不点**。
            self.assertEqual(page.get_attribute("#mode-overall", "class") or "", "mode-tab active")
            page.wait_for_function(
                "() => !document.getElementById('fb-save').disabled", timeout=15000)
            page.fill("#fb-text", "整片节奏偏慢，第三段可以再压一压")

            page.click("#fb-save")
            page.wait_for_function(
                "() => /已写入/.test(document.getElementById('save-state').textContent)", timeout=15000)
            submissions = self.project / "review" / "review-submissions.json"
            self.assertTrue(submissions.is_file(), "提交没有落到 surface 声明的文件")
            overall = json.loads(submissions.read_text(encoding="utf-8"))["records"]
            self.assertEqual(len(overall), 1)
            self.assertEqual(overall[0]["phase"], "overall")
            # **没有伪造的单位字段**
            for field in ("chapterId", "stepId", "stepIndex", "caption", "durationMs"):
                with self.subTest(field=field):
                    self.assertNotIn(field, overall[0])
            self.assertEqual(
                set(overall[0]["adjustments"]),
                {"choreography", "svg_edits", "annotations"},
            )

            # ④ **第二条路：选中某一屏 → 逐屏那条行为不变。**
            page.click(".step:nth-child(2)")           # chapter header 之后第一个 step
            page.wait_for_function("() => document.querySelector('.step.active') !== null")
            # 点屏会自动切到「当前屏」
            self.assertIn("active", page.get_attribute("#mode-step", "class") or "")
            page.fill("#fb-text", "这一屏太挤了")
            page.click("#fb-save")
            page.wait_for_function(
                "() => /本批 2 条/.test(document.getElementById('save-state').textContent)", timeout=15000)

            doc = json.loads(submissions.read_text(encoding="utf-8"))
            self.assertEqual(doc["contract_version"], "video-craft-review-submissions/1.0.0")
            self.assertEqual(len(doc["records"]), 2)
            record = doc["records"][1]
            self.assertEqual(record["text"], "这一屏太挤了")
            self.assertEqual(record["chapterId"], "intro")
            self.assertEqual(record["stepId"], "intro-001")
            self.assertEqual(record["status"], "open")
            # 记录必须**带上** review-ui.md 列出的每个契约字段。
            # 原先这里断言「整集合相等」，即把一份硬编码字段表当成契约的缓存——
            # 它被 env 门跳过的那段时间里页面加了 buildId/unitId/animationAnchor，
            # 谁也没发现，门一开测试就红。review-ui.md 从未把记录声明成闭合集合
            # （它列的是「反馈必须携带什么」，`:7` 还把 unitId/animationAnchor 写成载荷的一部分），
            # 所以判据收回成该有的形状：契约字段一个不少。
            for field in ("chapterId", "stepId", "stepIndex", "caption", "durationMs",
                          "type", "text", "status", "batchId", "createdAt", "snapshot",
                          "playbackTimeMs", "adjustments"):
                with self.subTest(contract_field=field):
                    self.assertIn(field, record)
            self.assertRegex(record["snapshot"], r"^[0-9a-f]{8,}$")
            self.assertIsInstance(record["playbackTimeMs"], int)
            self.assertEqual(set(record["adjustments"]), {
                "choreography", "svg_edits", "annotations"})

            # ④b wake 被调用两次：整片那条用**整句覆盖**（surface 的模板是逐屏口气）
            wake_log = Path(self.host["wake_log"])
            self.assertTrue(wake_log.is_file(), "wake 没有被调用")
            wakes = [json.loads(line) for line in wake_log.read_text(encoding="utf-8").splitlines()
                     if line.strip() and json.loads(line).get("kind") == "wake"]
            self.assertEqual(len(wakes), 2)
            self.assertEqual(wakes[0]["unit"], "整片")
            self.assertIn("feedback/*.jsonl", wakes[0]["text"])
            self.assertEqual(wakes[1]["unit"], record["stepId"])
            self.assertIn(record["stepId"], wakes[1]["text"])
            # 独立浏览器模式下应诚实反馈“已保存，回对话继续即可”，且不伪造“已送达”
            save_text = page.inner_text("#save-state")
            self.assertIn("已保存，回对话继续即可", save_text)
            self.assertNotIn("已送达", save_text)

            # ⑦ 宿主戳 → 页面自己重读、自己 diff。
            #    **只改一句 caption 也要被发现** —— 那是记录会抄走的字段，也正是旧指纹漏掉的
            #    （旧指纹只比结构，改 caption 时它认为"没变"，于是人对着旧文字提的意见
            #     挂着一条已经不存在的话，且没有任何提示。实测触发过。）
            timeline_path = self.project / "timeline" / "timeline.json"
            data = json.loads(timeline_path.read_text(encoding="utf-8"))
            self.assertIn("第一屏要说的话", data["chapters"][0]["steps"][0]["caption"])
            data["chapters"][0]["steps"][0]["caption"] = "第一屏改过的话"
            timeline_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            page.wait_for_function(
                "() => !document.getElementById('stale-note').hidden", timeout=20000)
            note = page.inner_text("#stale-note")
            self.assertIn("时间轴已经变了", note)
            self.assertIn("重新加载", note)
            # **提示要求人做的动作，页面上就得做得到**（用户报过：让人"重新加载"却没有那个按钮）
            self.assertEqual(page.locator("#stale-note button#stale-reload").count(), 1)
            self.assertEqual(page.inner_text("#stale-note button#stale-reload"), "重新加载")

            # ⑧ 橙条挂着时再提交一次：**记录里要带上陈旧标记**（只给人看的告警 = 机器看不见的告警）
            page.fill("#fb-text", "这一条是对着旧文字说的")
            page.click("#fb-save")
            wait_records(submissions_file(self.project), 3)
            rows = json.loads(submissions_file(self.project).read_text(encoding="utf-8"))["records"]
            self.assertEqual(rows[2]["stale"], True)
            self.assertRegex(rows[2]["stale_timeline"], r"^[0-9a-f]{8}$")
            # 前两条没有橙条 → **不许带这个字段**（不是常态字段）
            for earlier in rows[:2]:
                with self.subTest(earlier=earlier.get("phase") or earlier.get("stepId")):
                    self.assertNotIn("stale", earlier)
                    self.assertNotIn("stale_timeline", earlier)

            # ⑨ 点那个出口：页面真的重载，重载之后提示消失（时间轴与页面一致了就不该再报陈旧）
            with page.expect_navigation():
                page.click("#stale-reload")
            page.wait_for_function(
                "() => document.querySelectorAll('.step-caption').length === 3", timeout=20000)
            self.assertTrue(page.locator("#stale-note").is_hidden(), "重载后不该再报陈旧")
            after_reload = page.eval_on_selector_all(".step-caption", "els => els.map(e => e.textContent)")
            self.assertIn("第一屏改过的话", after_reload)     # 真的重读了时间轴

            # ⑩ **"页面变了、数据没变"** —— 用户报的那一种。
            #    只改磁盘上这一页（模拟"模型改了页面，让他重载拿新版"），数据一个字节不动，
            #    然后用**永久入口**刷新：必须拿到新版。以前这个场景没有任何出口（刷新按钮
            #    只长在橙色告警里，而数据没变就不会有告警）。
            self.assertTrue(page.locator("#page-reload").is_visible(), "永久刷新入口必须一直可见")
            served_page = self.project / "review" / "index.html"
            page_html = served_page.read_text(encoding="utf-8")
            self.assertNotIn("新版标记", page_html)
            served_page.write_text(
                page_html.replace("<h1>逐画面审阅 · ", "<h1>逐画面审阅（新版标记）· ", 1), encoding="utf-8")
            # 数据（时间轴）没动，所以**不该**有橙条
            self.assertTrue(page.locator("#stale-note").is_hidden(), "数据没变就不该报陈旧")
            with page.expect_navigation():
                page.click("#page-reload")
            page.wait_for_function(
                "() => document.querySelector('h1').textContent.includes('新版标记')", timeout=20000)
            self.assertIn("新版标记", page.inner_text("h1"))
            self.assertTrue(page.inner_text("#project-name").startswith("2 章 · 3 步"),   # 数据还是那一份
                            page.inner_text("#project-name"))
            browser.close()

        # ⑩ 收件：三条各进各的文件（整片 1 条 + 逐屏 2 条，其中一条带陈旧标记）
        receipt = review_inbox.import_submissions(self.project)
        self.assertTrue(receipt["ok"], receipt)
        self.assertEqual(len(receipt["imported"]), 3)
        self.assertEqual(sorted(one["file"] for one in receipt["imported"]),
                         ["feedback/intro.jsonl", "feedback/intro.jsonl", "feedback/overall.jsonl"])

        # 整片那条落 overall.jsonl，且**一个单位字段都没有**
        overall_jsonl = self.project / "feedback" / "overall.jsonl"
        self.assertTrue(overall_jsonl.is_file())
        overall_written = [json.loads(line) for line in overall_jsonl.read_text(encoding="utf-8").splitlines() if line.strip()]
        self.assertEqual(len(overall_written), 1)
        self.assertEqual(overall_written[0]["phase"], "overall")
        # 判据收回成「契约字段必须在、单位字段必须不在」。
        # 原先这里是整集合硬编码 —— 那是契约的一份缓存，页面合法地长了 buildId 与
        # adjustments 之后就过时了；它被 env 门跳过的那段时间里没人发现。
        for field in ("phase", "type", "text", "status", "batchId", "createdAt",
                      "snapshot", "playbackTimeMs", "buildId", "adjustments"):
            with self.subTest(contract_field=field):
                self.assertIn(field, overall_written[0])
        for field in ("unitId", "chapterId", "stepId", "stepIndex", "caption",
                      "durationMs", "animationAnchor"):
            with self.subTest(unit_field=field):
                self.assertNotIn(field, overall_written[0])

        jsonl = self.project / "feedback" / "intro.jsonl"
        self.assertTrue(jsonl.is_file())
        written = [json.loads(line) for line in jsonl.read_text(encoding="utf-8").splitlines() if line.strip()]
        self.assertEqual(len(written), 2)
        self.assertEqual(written[0], record)
        # **陈旧标记真的到了模型读的那个文件里**（R5b：只给人看的告警 = 机器看不见的告警）
        self.assertTrue(written[1]["stale"])
        self.assertRegex(written[1]["stale_timeline"], r"^[0-9a-f]{8}$")
        self.assertEqual(written[1]["text"], "这一条是对着旧文字说的")
        self.assertEqual(written[1]["stale_timeline"], rows[2]["stale_timeline"])
        # 没橙条那条**不许**被带上这个字段
        self.assertNotIn("stale", written[0])
        self.assertNotIn("stale", overall_written[0])

        # ⑪ 重复收件是空操作（三条都不许再长）
        again = review_inbox.import_submissions(self.project)
        self.assertEqual(again["imported"], [])
        self.assertEqual(len(again["skipped"]), 3)
        expected = {jsonl.name: 2, overall_jsonl.name: 1}
        for path in (jsonl, overall_jsonl):
            with self.subTest(path=path.name):
                self.assertEqual(
                    len([line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]),
                    expected[path.name])

        # 交换记录留档：报告里要给出真实发生过的请求。
        # 注意「时间轴是相对 fetch 拿的」而不是 `/__review/read` —— 这正是 base 差一级会踩的地方，
        # 所以两条都断言：桥被真的取过，时间轴与 surface 也被真的取过（都是 200）。
        self.assertTrue(any("/__review/bridge.js" in e[2] and e[0] == "→" for e in self.exchanges), self.exchanges)
        self.assertTrue(any("/__review/write" in e[2] and e[0] == "→" for e in self.exchanges), self.exchanges)
        self.assertTrue(any("/__review/wake" in e[2] and e[0] == "→" for e in self.exchanges), self.exchanges)
        for path in ("/timeline/timeline.json", "/review/review-surface.json"):
            with self.subTest(path=path):
                self.assertTrue(any(path in e[2] and e[0] == "←" and e[1] == 200 for e in self.exchanges),
                                f"{path} 没有被成功取到：{self.exchanges}")

    def test_zero_engineering_jargon_in_review_ui(self):
        from playwright.sync_api import sync_playwright

        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            try:
                page = browser.new_page(viewport={"width": 1440, "height": 900})
                page.route("**/localhost:5176/**", lambda route: route.abort())
                page.route("**/cdn.jsdelivr.net/**", lambda route: route.abort())
                page.goto(self.host["url"], wait_until="domcontentloaded")
                page.wait_for_selector(".step", timeout=15000)
                visible = page.inner_text("body")
                forbidden = [
                    "VIDEO CRAFT", "复合双通道", "审阅宿主", "serve-review.mjs",
                    "feedback/overall.jsonl", "choreography.json", "HyperFrames",
                    "工程态", "反馈给 Agent", "整 beat", "本 beat",
                    "live_stage.py", "edl_review_surface.py", "review_open",
                    "build_review", "composition", "审阅桥", "宿主", "快照",
                ]
                for term in forbidden:
                    self.assertNotIn(term, visible, f"画面审阅页可见文本出现禁用工程术语/说明：{term}")
                removed_selectors = [
                    "#view-verbatim-btn", "#verbatim-iframe-wrap", "#density-panel",
                    "#elem-edit-bar", "#interaction-mode-group", "#choreo-deck",
                    "#advanced-toggle", "#btn-play-screen", "#btn-show-all",
                    "#btn-focus-toggle", "#btn-toggle-cues", "#beat-switcher",
                    "#feedback-panel", "#tool-box", "#tool-select", "#tool-director",
                    "#annotation-overlay", ".canvas-toolbar",
                ]
                for selector in removed_selectors:
                    with self.subTest(selector=selector):
                        self.assertEqual(
                            page.locator(selector).count(), 0,
                            f"已下线控件不应再出现在审阅页 DOM：{selector}",
                        )
            finally:
                browser.close()

    def test_responsive_16_9_stage_across_wide_half_and_narrow_viewports(self):
        from playwright.sync_api import sync_playwright

        def overlap_2d(a, b):
            return (
                a["x"] < b["x"] + b["width"] - 1
                and b["x"] < a["x"] + a["width"] - 1
                and a["y"] < b["y"] + b["height"] - 1
                and b["y"] < a["y"] + a["height"] - 1
            )

        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            try:
                page = browser.new_page()
                page.route("**/localhost:5176/**", lambda route: route.abort())
                page.route("**/cdn.jsdelivr.net/**", lambda route: route.abort())
                page.goto(self.host["url"], wait_until="domcontentloaded")
                page.wait_for_selector(".step", timeout=15000)

                for vw, vh in ((1440, 900), (860, 800), (460, 800)):
                    with self.subTest(viewport=(vw, vh)):
                        page.set_viewport_size({"width": vw, "height": vh})
                        page.wait_for_timeout(80)
                        metrics = page.evaluate("""() => {
                            const rect = sel => {
                                const el = document.querySelector(sel);
                                if (!el) return null;
                                const r = el.getBoundingClientRect();
                                return { x: r.x, y: r.y, width: r.width, height: r.height };
                            };
                            return {
                                scrollW: document.documentElement.scrollWidth,
                                innerW: window.innerWidth,
                                scrollH: document.documentElement.scrollHeight,
                                innerH: window.innerHeight,
                                player: rect(".player-box"),
                                steps: rect("#steps"),
                                transport: rect("#global-transport-bar"),
                                feedback: rect(".feedback"),
                            };
                        }""")
                        self.assertLessEqual(
                            metrics["scrollW"], metrics["innerW"] + 1,
                            f"水平溢出 ({vw}x{vh}): {metrics['scrollW']} > {metrics['innerW']}",
                        )
                        p = metrics["player"]
                        self.assertIsNotNone(p)
                        self.assertGreater(p["width"], 200)
                        self.assertLess(abs(p["width"] / p["height"] - (16.0 / 9.0)), 0.05, p)
                        self.assertGreaterEqual(p["x"], -1.0, p)
                        self.assertLessEqual(p["x"] + p["width"], vw + 1.0, p)
                        for other_name in ("steps", "transport", "feedback"):
                            other = metrics[other_name]
                            self.assertIsNotNone(other)
                            self.assertFalse(
                                overlap_2d(p, other),
                                f"{vw}x{vh} 下舞台与 {other_name} 重叠: player={p} other={other}",
                            )
                        if vw == 1440:
                            orient = page.evaluate("() => document.body.dataset.orientation")
                            self.assertEqual(orient, "landscape")
                            # Landscape: feedback form sits below transport bar, empty history side-right collapsed by default
                            fb_box = metrics["feedback"]
                            tr_box = metrics["transport"]
                            self.assertGreaterEqual(fb_box["y"], tr_box["y"] + tr_box["height"] - 2, (fb_box, tr_box))
                            self.assertTrue(page.evaluate("() => document.body.classList.contains('history-collapsed')"))
                            # Click history toggle to expand right panel, then verify splitter drag
                            page.click("#btn-toggle-history")
                            page.wait_for_function("() => !document.body.classList.contains('history-collapsed')")
                            handle = page.locator("#main-split-handle")
                            self.assertTrue(handle.is_visible())
                            hbox = handle.bounding_box()
                            before_w = page.evaluate("() => document.querySelector('.side-right').getBoundingClientRect().width")
                            page.mouse.move(hbox["x"] + hbox["width"] / 2, hbox["y"] + hbox["height"] / 2)
                            page.mouse.down()
                            page.mouse.move(hbox["x"] - 80, hbox["y"] + hbox["height"] / 2, steps=5)
                            page.mouse.up()
                            after_w = page.evaluate("() => document.querySelector('.side-right').getBoundingClientRect().width")
                            self.assertGreater(after_w, before_w + 40, f"Draggable splitter failed: {before_w} -> {after_w}")
                        if vw == 460:
                            self.assertGreater(metrics["scrollH"], metrics["innerH"], "窄屏下应可纵向滚动")
                            page.locator("#fb-save").scroll_into_view_if_needed()
                            self.assertTrue(page.locator("#fb-save").is_visible())
            finally:
                browser.close()

    def test_audio_preset_and_dry_voice_ab_toggle(self):
        import struct
        import wave
        import build_review
        from playwright.sync_api import sync_playwright

        with tempfile.TemporaryDirectory() as td:
            proj = Path(td)
            (proj / "edit").mkdir()
            (proj / "timeline").mkdir()
            (proj / "timeline" / "timeline.json").write_text(json.dumps(TIMELINE, ensure_ascii=False), encoding="utf-8")
            (proj / "recompose.json").write_text(json.dumps({
                "canvas": {"w": 1920, "h": 1080, "fps": 30},
                "personSlot": {"x": 0, "y": 0, "w": 500, "h": 1080},
                "captionSafe": {"x": 0, "y": 880, "w": 1920, "h": 200},
            }), encoding="utf-8")
            for wav_name in ("audio_mix.wav", "voice_dry.wav"):
                with wave.open(str(proj / "edit" / wav_name), "wb") as wf:
                    wf.setnchannels(1)
                    wf.setsampwidth(2)
                    wf.setframerate(16000)
                    wf.writeframes(struct.pack("<" + "h" * 1600, *([0] * 1600)))

            data = build_review.build_review_data(proj, proj / "edit")
            self.assertEqual(data["media"]["audioTracks"]["mix"], "edit/audio_mix.wav")
            self.assertEqual(data["media"]["audioTracks"]["dry"], "edit/voice_dry.wav")
            self.assertEqual(data["media"]["audioTracks"]["preset"], "podcast-warm")
            build_review.write_review_files(proj, data)
            host = review_surface.open_review(proj, open_browser=False)
            self.addCleanup(review_host.stop_host, host)

            with sync_playwright() as pw:
                browser = pw.chromium.launch()
                try:
                    page = browser.new_page(viewport={"width": 1280, "height": 800})
                    page.route("**/localhost:5176/**", lambda route: route.abort())
                    page.route("**/cdn.jsdelivr.net/**", lambda route: route.abort())
                    page.goto(host["url"], wait_until="domcontentloaded")
                    page.wait_for_function("() => !document.getElementById('fb-save').disabled", timeout=15000)

                    btn = page.locator("#btn-audio-ab")
                    self.assertEqual(btn.inner_text().strip(), "播客音色")
                    self.assertEqual(page.evaluate("() => document.body.dataset.audioMode"), "mix")
                    page.wait_for_function(
                        "() => !!document.getElementById('review-audio-alt').getAttribute('src')",
                        timeout=10000,
                    )
                    mix_src = page.evaluate("() => document.getElementById('review-audio-alt').getAttribute('src')")

                    btn.click()
                    page.wait_for_function(
                        """(prev) => document.body.dataset.audioMode === 'dry'
                            && !!document.getElementById('review-audio-alt').getAttribute('src')
                            && document.getElementById('review-audio-alt').getAttribute('src') !== prev""",
                        arg=mix_src,
                        timeout=10000,
                    )
                    dry_src = page.evaluate("() => document.getElementById('review-audio-alt').getAttribute('src')")
                    self.assertNotEqual(dry_src, mix_src)
                    self.assertEqual(btn.inner_text().strip(), "纯干声")

                    btn.click()
                    page.wait_for_function(
                        """(exp) => document.body.dataset.audioMode === 'mix'
                            && document.getElementById('review-audio-alt').getAttribute('src') === exp""",
                        arg=mix_src,
                        timeout=10000,
                    )
                    self.assertEqual(btn.inner_text().strip(), "播客音色")
                finally:
                    browser.close()

    def test_recompose_mode_keeps_minimal_ui_and_submits(self):
        import build_review
        from playwright.sync_api import sync_playwright

        with tempfile.TemporaryDirectory() as td:
            proj = Path(td)
            (proj / "edit").mkdir()
            (proj / "timeline").mkdir()
            (proj / "timeline" / "timeline.json").write_text(
                json.dumps(TIMELINE, ensure_ascii=False), encoding="utf-8"
            )
            (proj / "recompose.json").write_text(json.dumps({
                "canvas": {"w": 1920, "h": 1080, "fps": 30},
                "personSlot": {"x": 0, "y": 0, "w": 500, "h": 1080},
                "captionSafe": {"x": 0, "y": 880, "w": 1920, "h": 200},
            }), encoding="utf-8")

            data = build_review.build_review_data(proj, proj / "edit")
            data["density"] = {
                "enabled": True,
                "beats": [
                    {"id": "b1", "caption": "开场段落", "stepIds": ["intro-001"]},
                ],
            }
            build_review.write_review_files(proj, data)
            host = review_surface.open_review(proj, open_browser=False)
            self.addCleanup(review_host.stop_host, host)

            with sync_playwright() as pw:
                browser = pw.chromium.launch()
                try:
                    page = browser.new_page(viewport={"width": 1440, "height": 900})
                    page.route("**/localhost:5176/**", lambda route: route.abort())
                    page.route("**/cdn.jsdelivr.net/**", lambda route: route.abort())
                    page.goto(host["url"], wait_until="domcontentloaded")
                    page.wait_for_selector(".step", timeout=15000)
                    page.wait_for_function("() => !document.getElementById('fb-save').disabled", timeout=15000)

                    self.assertFalse(page.evaluate("() => document.body.classList.contains('density-on')"))
                    for sel in ("#density-panel", "#beat-switcher", "#feedback-panel", "#vfb-save"):
                        self.assertEqual(page.locator(sel).count(), 0, sel)
                    self.assertTrue(page.locator("#steps").is_visible())
                    self.assertTrue(page.locator("#fb-save").is_visible())

                    page.fill("#fb-text", "口播段落衔接再紧凑一点")
                    page.click("#fb-save")
                    page.wait_for_function(
                        "() => /已写入/.test(document.getElementById('save-state').textContent)", timeout=15000
                    )
                    self.assertIn("已保存，回对话继续即可", page.inner_text("#save-state"))
                    submissions = proj / "review" / "review-submissions.json"
                    records = json.loads(submissions.read_text(encoding="utf-8"))["records"]
                    self.assertEqual(len(records), 1)
                    self.assertEqual(records[0]["text"], "口播段落衔接再紧凑一点")
                    # Landscape auto-expands history panel immediately upon submission
                    page.wait_for_function("() => !document.body.classList.contains('history-collapsed')")
                    self.assertTrue(page.locator("#fb-history-list").is_visible())
                finally:
                    browser.close()

    def test_portrait_9_16_layout_and_manual_orientation_toggle(self):
        import build_review
        from playwright.sync_api import sync_playwright

        with tempfile.TemporaryDirectory() as td:
            proj = Path(td)
            (proj / "edit").mkdir()
            (proj / "timeline").mkdir()
            (proj / "timeline" / "timeline.json").write_text(
                json.dumps(TIMELINE, ensure_ascii=False), encoding="utf-8"
            )
            (proj / "frame.json").write_text(json.dumps({
                "framePreset": "vertical-zine-head",
                "canvas": {"w": 1080, "h": 1920, "fps": 30},
            }), encoding="utf-8")

            data = build_review.build_review_data(proj, proj / "edit")
            self.assertEqual(data["orientation"], "portrait")
            self.assertEqual(data["aspectRatio"], "9:16")
            build_review.write_review_files(proj, data)
            host = review_surface.open_review(proj, open_browser=False)
            self.addCleanup(review_host.stop_host, host)

            with sync_playwright() as pw:
                browser = pw.chromium.launch()
                try:
                    page = browser.new_page(viewport={"width": 1440, "height": 900})
                    page.route("**/localhost:5176/**", lambda route: route.abort())
                    page.route("**/cdn.jsdelivr.net/**", lambda route: route.abort())
                    page.goto(host["url"], wait_until="domcontentloaded")
                    page.wait_for_selector(".step", timeout=15000)
                    page.wait_for_function("() => !document.getElementById('fb-save').disabled", timeout=15000)

                    metrics = page.evaluate("""() => {
                        const rect = sel => {
                            const el = document.querySelector(sel);
                            if (!el) return null;
                            const r = el.getBoundingClientRect();
                            return { x: r.x, y: r.y, width: r.width, height: r.height };
                        };
                        return {
                            orientation: document.body.dataset.orientation,
                            scrollW: document.documentElement.scrollWidth,
                            innerW: window.innerWidth,
                            innerH: window.innerHeight,
                            player: rect(".player-box"),
                            feedback: rect(".feedback"),
                            rightSlotHasFb: !!document.querySelector("#right-feedback-slot .feedback"),
                            history: rect("#fb-history-list"),
                        };
                    }""")
                    self.assertEqual(metrics["orientation"], "portrait")
                    self.assertTrue(metrics["rightSlotHasFb"])
                    self.assertLessEqual(metrics["scrollW"], metrics["innerW"] + 1)
                    p = metrics["player"]
                    self.assertLess(abs((p["width"] / p["height"]) - (9.0 / 16.0)), 0.05, p)
                    self.assertGreaterEqual(p["height"], metrics["innerH"] * 0.72, p)
                    self.assertLess(metrics["feedback"]["y"], metrics["history"]["y"] + 2)

                    # Manual orientation toggle switches cleanly between portrait and landscape
                    page.click("#btn-orientation-toggle")
                    page.wait_for_function("() => document.body.dataset.orientation === 'landscape'")
                    self.assertTrue(page.evaluate("() => !!document.querySelector('#center-feedback-slot .feedback')"))
                    page.click("#btn-orientation-toggle")
                    page.wait_for_function("() => document.body.dataset.orientation === 'portrait'")
                    self.assertTrue(page.evaluate("() => !!document.querySelector('#right-feedback-slot .feedback')"))
                finally:
                    browser.close()


if __name__ == "__main__":
    unittest.main()
