"""The visual scene review's save path, from the page to the file the agent reads.

Pins the one non-negotiable property of a review surface: **the opinion must not be lost**.
The chain has three links and each is asserted here:

  ① the host really serves *this* project's page and files（不然人在看别人的页面）;
  ② the record really reaches `feedback/<chapterId>.jsonl` —— 而现在是**两跳**：
     页面写 surface 声明的**一份**提交文件（宿主只做覆盖写），`review_inbox` 收件时
     翻译成每章一份的 JSONL **追加**;
  ③ the agent reads it from there.

The transport has moved twice and these tests moved with it:
  · 最早是「生成一行 JSONL → 人复制 → 粘贴」——败在第 ② 跳靠人;
  · 然后是本 Skill 自己的 HTTP 服务器（`visual_review_serve.py`，直存）;
  · 现在是公共缝（`planners-review-core` 的宿主 + 桥）。
**行为一直是同一组行为**，所以断言保留：追加不覆盖、旧内容进 `.previous/` 且不出现在
agent 的 `feedback/*.jsonl` 读法里、chapterId 折不出 `feedback/`、缺件先于人看到页面前说清楚、
不端出旧项目的页面。服务那一段没了，但「不端出旧项目」换了判据（见 HostIdentityCase）。

The record schema is the agent-side contract from `references/review-ui.md`; these tests write
every documented field and require it back unchanged.
"""
import functools
import http.server
import importlib.util
import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

HELPERS = Path(__file__).parents[1] / "helpers"
TEMPLATE = Path(__file__).parents[1] / "visual" / "assets" / "review-page-template.html"


def load(name: str):
    spec = importlib.util.spec_from_file_location(f"video_craft_{name}", HELPERS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


FEEDBACK = load("visual_review_feedback")
INBOX = load("review_inbox")
SURFACE = load("review_surface")
# 宿主生命周期只有公共模组那一份；测试直接调它，别的照旧走 Skill 的薄壳。
HOST = __import__("review_host")

# The ten fields the documented schema carries, plus `srtRange` and
# `codeVersion`: the page does not produce those two (see review-ui.md), but the
# save path must write through whatever a review surface sends, so a future page
# change needs no change here.
RECORD = {
    "chapterId": "intro",
    "stepId": "intro-003",
    "stepIndex": 3,
    "srtRange": [12, 14],
    "caption": "Current caption text",
    "durationMs": 7500,
    "type": "visual",
    "text": "This screen is too dense.",
    "status": "open",
    "batchId": "review-20260705-1",
    "createdAt": "2026-07-05T12:00:00.000Z",
    "codeVersion": "abc1234",
}
TIMELINE = {"totalChapters": 1, "totalSteps": 1, "totalDurationMs": 7500,
            "chapters": [{"id": "intro", "title": "开场", "steps": []}]}


def have_node():
    try:
        HOST.node_binary()
        return True
    except ValueError:
        return False


def make_project(root: Path, timeline=None, page=None):
    """一个最小但**真的能开**的项目：审阅页 + 时间轴（surface 由被测代码自己写）。"""
    (root / "review").mkdir(parents=True, exist_ok=True)
    (root / "timeline").mkdir(parents=True, exist_ok=True)
    (root / "review" / "index.html").write_text(
        page if page is not None else TEMPLATE.read_text(encoding="utf-8"), encoding="utf-8")
    (root / "timeline" / "timeline.json").write_text(
        json.dumps(timeline if timeline is not None else TIMELINE, ensure_ascii=False), encoding="utf-8")
    return root


def post_submissions(project: Path, records):
    """页面做的事：把这一批记录整体写进 surface 声明的那份提交文件（宿主是覆盖写）。"""
    path = INBOX.submissions_path(project)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"contract_version": "video-craft-review-submissions/1.0.0",
                                "surface": "video-craft/visual",
                                "updated_at": "2026-07-05T12:00:00.000Z",
                                "records": records}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


class TempProjectCase(unittest.TestCase):
    def setUp(self):
        self.project = Path(tempfile.mkdtemp(prefix="video-craft-review-")).resolve()
        make_project(self.project)

    def lines(self, name: str) -> list:
        path = self.project / "feedback" / name
        return [json.loads(one) for one in path.read_text(encoding="utf-8").splitlines() if one.strip()]


class SurfaceWrittenCase(TempProjectCase):
    """审阅面已经立起来了的项目。收件与宿主都要先有 surface ——
    它声明提交文件在哪、dir 是哪一棵，两者都靠它。"""

    def setUp(self):
        super().setUp()
        SURFACE.write_surface(self.project)


# --- ② the record really reaches the file ----------------------------------

class AppendSemanticsCase(TempProjectCase):
    """The append path itself. `review_inbox` calls it; it is the last link that can lose
    an opinion, so it is tested with no transport in the way."""

    def test_record_lands_in_the_chapter_file_unchanged(self):
        info = FEEDBACK.save_feedback(self.project, "intro.jsonl", FEEDBACK.normalize_record(RECORD))
        self.assertEqual(info["file"], "feedback/intro.jsonl")
        self.assertEqual(info["records"], 1)

        written = self.lines("intro.jsonl")
        self.assertEqual(len(written), 1)
        self.assertEqual(written[0], RECORD)
        self.assertEqual(set(written[0]), set(RECORD))

    def test_appending_keeps_every_round_in_one_file(self):
        first = dict(RECORD, text="第一轮")
        second = dict(RECORD, text="第二轮", batchId="review-20260705-2")
        FEEDBACK.save_feedback(self.project, "intro.jsonl", FEEDBACK.normalize_record(first))
        info = FEEDBACK.save_feedback(self.project, "intro.jsonl", FEEDBACK.normalize_record(second))
        self.assertEqual(info["records"], 2)
        self.assertEqual([one["text"] for one in self.lines("intro.jsonl")], ["第一轮", "第二轮"])

    def test_previous_version_is_kept_out_of_the_agents_read_glob(self):
        first = dict(RECORD, text="第一轮")
        FEEDBACK.save_feedback(self.project, "intro.jsonl", FEEDBACK.normalize_record(first))
        FEEDBACK.save_feedback(self.project, "intro.jsonl", FEEDBACK.normalize_record(RECORD))

        previous = self.project / "feedback" / FEEDBACK.PREVIOUS_DIR / "intro.jsonl"
        self.assertTrue(previous.is_file())
        self.assertEqual([json.loads(one) for one in previous.read_text(encoding="utf-8").splitlines()],
                         [first])
        # `feedback/*.jsonl` is what the agent reads (review-ui.md protocol 1):
        # the backup must not look like author feedback.
        self.assertEqual([p.name for p in (self.project / "feedback").glob("*.jsonl")], ["intro.jsonl"])

    def test_normalize_fills_only_the_two_documented_derivations(self):
        # 页面没带 status/createdAt 时才补；带了就一个字节都不动。
        filled = FEEDBACK.normalize_record({"chapterId": "intro", "text": "x"})
        self.assertEqual(filled["status"], "open")
        self.assertTrue(filled["createdAt"])
        self.assertEqual(set(filled), {"chapterId", "text", "status", "createdAt"})
        self.assertEqual(FEEDBACK.normalize_record(RECORD), RECORD)

    def test_chapter_id_cannot_escape_the_feedback_dir(self):
        info = FEEDBACK.save_feedback(self.project, FEEDBACK.record_filename("../../evil"),
                                      FEEDBACK.normalize_record(dict(RECORD, chapterId="../../evil")))
        target = (self.project / info["file"]).resolve()
        self.assertEqual(target.parent, (self.project / "feedback").resolve())
        self.assertFalse((self.project / "evil.jsonl").exists())
        # The record keeps the chapterId the page meant; only the file name is
        # folded, so grouping by chapterId still matches timeline.json.
        self.assertEqual(self.lines(target.name)[0]["chapterId"], "../../evil")

    def test_non_ascii_chapter_id_still_gets_its_own_file(self):
        # v1 folded every non-ASCII character, so 「开场」 and 「收尾」 both became
        # `---.jsonl` — two chapters, one file, silently mixed. Chapter ids come
        # from timeline/grouping.json and nothing enforces ASCII.
        for chapter in ("开场", "收尾"):
            FEEDBACK.save_feedback(self.project, FEEDBACK.record_filename(chapter),
                                   FEEDBACK.normalize_record(dict(RECORD, chapterId=chapter)))
        self.assertEqual([p.name for p in (self.project / "feedback").glob("*.jsonl")],
                         ["开场.jsonl", "收尾.jsonl"])

    def test_append_leaves_no_tmp_behind(self):
        FEEDBACK.save_feedback(self.project, "intro.jsonl", FEEDBACK.normalize_record(RECORD))
        self.assertEqual([p.name for p in (self.project / "feedback").iterdir() if p.is_file()],
                         ["intro.jsonl"])


# --- ②b the inbox translates one submission file into per-chapter appends ----

class InboxCase(SurfaceWrittenCase):
    """收件：surface 声明**一份**提交文件，本 Skill 的形状是**每章一份、只追加**。
    形状对不上就在这里翻译 —— 不为了适配缝去改本 Skill 的反馈形状。"""

    def test_submission_is_translated_into_a_per_chapter_append(self):
        post_submissions(self.project, [RECORD])
        receipt = INBOX.import_submissions(self.project)
        self.assertTrue(receipt["ok"], receipt)
        self.assertEqual(len(receipt["imported"]), 1)
        self.assertEqual(receipt["imported"][0]["file"], "feedback/intro.jsonl")
        self.assertEqual(self.lines("intro.jsonl"), [RECORD])

    def test_importing_twice_appends_nothing_the_second_time(self):
        post_submissions(self.project, [RECORD])
        first = INBOX.import_submissions(self.project)
        second = INBOX.import_submissions(self.project)
        self.assertEqual(len(first["imported"]), 1)
        self.assertEqual(second["imported"], [])
        self.assertEqual(len(second["skipped"]), 1)
        self.assertEqual(len(self.lines("intro.jsonl")), 1)

    def test_a_rewritten_opinion_is_a_new_record_not_a_duplicate(self):
        # 同一句话、不同时刻 = 作者真的又提了一次，必须收成两条。
        post_submissions(self.project, [RECORD])
        INBOX.import_submissions(self.project)
        post_submissions(self.project, [RECORD, dict(RECORD, createdAt="2026-07-05T13:00:00.000Z")])
        receipt = INBOX.import_submissions(self.project)
        self.assertEqual(len(receipt["imported"]), 1)
        self.assertEqual(len(self.lines("intro.jsonl")), 2)

    def test_a_second_round_keeps_the_first_round_lines(self):
        """作者连写三条、模型分两轮收件：原有行一条都不能少。"""
        post_submissions(self.project, [dict(RECORD, text="一"), dict(RECORD, text="二")])
        INBOX.import_submissions(self.project)
        self.assertEqual([one["text"] for one in self.lines("intro.jsonl")], ["一", "二"])
        post_submissions(self.project, [dict(RECORD, text="一"), dict(RECORD, text="二"),
                                        dict(RECORD, text="三")])
        receipt = INBOX.import_submissions(self.project)
        self.assertEqual(len(receipt["imported"]), 1)
        self.assertEqual([one["text"] for one in self.lines("intro.jsonl")], ["一", "二", "三"])

    def test_the_previous_backup_still_happens_through_the_inbox(self):
        """备份行为走收件这条路时也不能丢。"""
        post_submissions(self.project, [dict(RECORD, text="第一轮")])
        INBOX.import_submissions(self.project)
        post_submissions(self.project, [dict(RECORD, text="第一轮"),
                                        dict(RECORD, text="第二轮", createdAt="2026-07-05T13:00:00.000Z")])
        INBOX.import_submissions(self.project)
        previous = self.project / "feedback" / FEEDBACK.PREVIOUS_DIR / "intro.jsonl"
        self.assertTrue(previous.is_file())
        self.assertEqual([one["text"] for one in self.lines(FEEDBACK.PREVIOUS_DIR + "/intro.jsonl")],
                         ["第一轮"])
        self.assertEqual([p.name for p in (self.project / "feedback").glob("*.jsonl")], ["intro.jsonl"])

    def test_storyboard_checkpoint_writes_storyboard_jsonl(self):
        # 真实数据长这样（`PPTSkillV2/feedback/storyboard.jsonl`）：`phase` 显式写着，
        # `chapterId` 是**真章节**。phase 以前由端点携带，缝只有一个写入口，所以只能读记录。
        post_submissions(self.project, [{"phase": "storyboard", "chapterId": "cta",
                                         "stepId": "cta-001", "text": "分组要改"}])
        receipt = INBOX.import_submissions(self.project)
        self.assertTrue(receipt["ok"], receipt)
        self.assertEqual(receipt["imported"][0]["file"], f"feedback/{FEEDBACK.STORYBOARD_FILE}")
        written = self.lines(FEEDBACK.STORYBOARD_FILE)
        self.assertEqual(len(written), 1)
        self.assertEqual(written[0]["phase"], "storyboard")
        self.assertEqual(written[0]["chapterId"], "cta")
        self.assertEqual(written[0]["status"], "open")
        self.assertTrue(written[0]["createdAt"])

    def test_an_overall_opinion_lands_in_its_own_file_without_an_invented_step(self):
        """**整片意见不针对任何一屏**，所以它没有 chapterId/stepId —— 也不许给它编一个。

        它本来就带 `phase`，收件按 phase 认，落 `feedback/overall.jsonl`。
        规则（模组 design-and-porting-rules R10）：页面不许把逐单位当成唯一入口；
        收件侧的对偶：不许为了塞进 `feedback/<chapterId>.jsonl` 而伪造单位字段。
        """
        post_submissions(self.project, [{"phase": "overall", "type": "visual",
                                         "text": "整片节奏偏慢，第三段可以再压一压",
                                         "status": "open", "createdAt": "2026-09-26T00:00:00.000Z"}])
        receipt = INBOX.import_submissions(self.project)
        self.assertTrue(receipt["ok"], receipt)
        self.assertEqual(receipt["imported"][0]["file"], f"feedback/{FEEDBACK.OVERALL_FILE}")

        written = self.lines(FEEDBACK.OVERALL_FILE)
        self.assertEqual(len(written), 1)
        # 一个单位字段都不许多出来
        self.assertNotIn("stepId", written[0])
        self.assertNotIn("chapterId", written[0])
        self.assertNotIn("stepIndex", written[0])
        self.assertNotIn("caption", written[0])
        self.assertNotIn("durationMs", written[0])
        self.assertEqual(set(written[0]), {"phase", "type", "text", "status", "createdAt"})
        # 也不许在 feedback/ 下多出别的文件
        self.assertEqual([p.name for p in (self.project / "feedback").glob("*.jsonl")],
                         [FEEDBACK.OVERALL_FILE])

    def test_overall_and_per_step_records_can_land_in_the_same_batch(self):
        """两条路各写各的文件，互不冒充。"""
        post_submissions(self.project, [
            {"phase": "overall", "type": "timing", "text": "整片偏慢", "createdAt": "2026-09-26T00:00:00.000Z"},
            dict(RECORD, text="这一屏太挤"),
        ])
        receipt = INBOX.import_submissions(self.project)
        self.assertTrue(receipt["ok"], receipt)
        self.assertEqual(sorted(one["file"] for one in receipt["imported"]),
                         ["feedback/intro.jsonl", f"feedback/{FEEDBACK.OVERALL_FILE}"])
        self.assertEqual(self.lines(FEEDBACK.OVERALL_FILE)[0]["text"], "整片偏慢")
        self.assertEqual(self.lines("intro.jsonl")[0]["stepId"], "intro-003")

    def test_a_real_chapter_is_not_treated_as_the_storyboard_checkpoint(self):
        """一个真名叫 `storyboard` 的章节：旧代码经 `/api/feedback` 进来时**不补** `phase`。
        文件名两条路本来就都是 `storyboard.jsonl`，所以不看 chapterId 不会走错文件 ——
        但补字段就是改形状，不许。"""
        post_submissions(self.project, [dict(RECORD, chapterId="storyboard")])
        INBOX.import_submissions(self.project)
        written = self.lines("storyboard.jsonl")
        self.assertEqual(len(written), 1)
        self.assertNotIn("phase", written[0])
        self.assertEqual(set(written[0]), set(RECORD))

    def test_an_opinion_without_text_is_refused_and_not_written(self):
        post_submissions(self.project, [dict(RECORD, text="   "), dict(RECORD, chapterId="")])
        receipt = INBOX.import_submissions(self.project)
        self.assertFalse(receipt["ok"])
        self.assertEqual(len(receipt["rejected"]), 2)
        self.assertIn("反馈内容为空", receipt["rejected"][0]["reason"])
        self.assertIn("chapterId", receipt["rejected"][1]["reason"])
        # 拒了就不许落文件 —— 静默丢一条意见是这套东西最坏的失败方式
        self.assertFalse((self.project / "feedback").exists())

    def test_garbage_submissions_are_refused_not_written(self):
        path = post_submissions(self.project, [])
        path.write_text("not json", encoding="utf-8")
        with self.assertRaises(ValueError):
            INBOX.import_submissions(self.project)
        self.assertFalse((self.project / "feedback").exists())

        path.write_text(json.dumps({"contract_version": "x"}), encoding="utf-8")
        with self.assertRaises(ValueError):
            INBOX.import_submissions(self.project)
        self.assertFalse((self.project / "feedback").exists())

    def test_dry_run_writes_nothing_and_moves_no_cursor(self):
        post_submissions(self.project, [RECORD])
        receipt = INBOX.import_submissions(self.project, dry_run=True)
        self.assertEqual(len(receipt["imported"]), 1)
        self.assertFalse((self.project / "feedback").exists())
        self.assertFalse(INBOX.cursor_path(self.project).exists())
        self.assertEqual(len(INBOX.import_submissions(self.project)["imported"]), 1)

    def test_missing_surface_is_an_error_not_an_empty_success(self):
        (self.project / SURFACE.SURFACE_REL).unlink(missing_ok=True)
        with self.assertRaises(ValueError):
            INBOX.import_submissions(self.project)


# --- the surface itself -----------------------------------------------------

class SurfaceContractCase(TempProjectCase):
    def test_surface_declares_the_page_the_dir_and_the_submission_file(self):
        doc = SURFACE.surface_document()
        self.assertEqual(doc["contract_version"], "review-surface/2.0.0")
        self.assertEqual(doc["id"], "video-craft/visual")
        # dir 必须是项目根：页面在 review/，而它读 timeline/timeline.json。
        self.assertEqual(doc["dir"], "..")
        self.assertEqual(doc["entry"], "review/index.html")
        self.assertEqual(doc["feedback"], "review-submissions.json")
        # 唤醒走插话：queue 会让提交排到当前回合之后，模型忙时界面同时出现「已送达」与「排队中」。
        self.assertEqual(doc["wake"]["mode"], "steer")
        self.assertEqual(doc["capabilities"], ["draft"])
        self.assertEqual(doc["draft"], "review-draft.json")
        self.assertIn('review_inbox.py', doc['wake']['text'])

    def test_watch_is_relative_to_the_surface_file(self):
        """`watch` 是这份契约里唯一**相对 surface 文件**的路径字段（其余相对 `dir`）。
        本 Skill 的页面在子目录里，两者的差一级会把写错的基准立刻变成校验错误 ——
        这一条正是「第二家」暴露出来、随后被统一掉的那个歧义。"""
        doc = SURFACE.surface_document()
        self.assertEqual(doc["watch"], ["../timeline/timeline.json"])
        self.assertTrue((self.project / SURFACE.SURFACE_REL).parent.joinpath(doc["watch"][0]).is_file())

    def test_surface_wake_text_does_not_lie_about_this_skill(self):
        """ppt-hell 的唤醒语是「只重出这一页」；本 Skill 的返修环是重渲染整片。
        照抄那句话会得到一句在视频侧为假的话，所以把「不许自称只重出一页」钉住。"""
        text = SURFACE.surface_document()["wake"]["text"]
        self.assertIn("{unit}", text)
        self.assertNotIn("只重出", text)

    def test_submissions_path_comes_from_the_surface(self):
        SURFACE.write_surface(self.project)
        self.assertEqual(SURFACE.submissions_path(self.project / SURFACE.SURFACE_REL),
                         (self.project / "review" / "review-submissions.json").resolve())

    def test_write_surface_is_idempotent(self):
        first = SURFACE.write_surface(self.project)
        stamp = first.stat().st_mtime_ns
        second = SURFACE.write_surface(self.project)
        self.assertEqual(first, second)
        self.assertEqual(second.stat().st_mtime_ns, stamp)

    @unittest.skipUnless(have_node(), "needs node for the shared validator")
    def test_surface_passes_the_shared_validator(self):
        SURFACE.write_surface(self.project)
        self.assertTrue(SURFACE.validate_surface(self.project))

    @unittest.skipUnless(have_node(), "needs node for the shared validator")
    def test_validator_rejects_a_surface_whose_dir_escapes_the_project(self):
        SURFACE.write_surface(self.project)
        path = self.project / SURFACE.SURFACE_REL
        doc = json.loads(path.read_text(encoding="utf-8"))
        doc["dir"] = "../../.."
        path.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
        with self.assertRaises(ValueError):
            SURFACE.validate_surface(self.project)


# --- missing pieces and stale copies must be refused before the human sees them ---

class PageGuardCase(SurfaceWrittenCase):
    def test_missing_page_or_timeline_is_reported_before_opening(self):
        empty = Path(tempfile.mkdtemp(prefix="video-craft-review-empty-"))
        problems = FEEDBACK.check_project(empty)
        self.assertEqual(len(problems), 2)
        self.assertTrue(all(str(empty) in one for one in problems))
        # 缺件时不许起宿主/开浏览器：报出来，不兜底
        with self.assertRaises(ValueError) as caught:
            SURFACE.open_review(empty, open_browser=False)
        self.assertIn("现在还不能开审阅", str(caught.exception))

    def test_a_page_without_the_inject_point_is_refused(self):
        """**这是那个守卫在新世界里的形状。** 旧世界它认 `fetch("/api/feedback"`；
        新世界页面不再自己 POST，能送进文件的唯一方式是被宿主 serve 时注入桥 ——
        所以判据是「有没有留注入点」。"""
        (self.project / FEEDBACK.PAGE_REL).write_text(
            '<!doctype html><button id="fb-save">保存反馈</button>'
            '<script>navigator.clipboard.writeText("{}")</script>', encoding="utf-8")
        problems = FEEDBACK.check_project(self.project)
        self.assertEqual(len(problems), 1)
        self.assertIn("剪贴板时代", problems[0])

    def test_the_direct_save_era_page_is_refused_with_its_own_reason(self):
        # 直存时代的副本自己 POST 到已退役的 /api/feedback：留着它比剪贴板时代更坏，
        # 因为页面看起来在工作，而那个服务已经没有了。
        (self.project / FEEDBACK.PAGE_REL).write_text(
            '<!doctype html><button id="fb-save">保存反馈</button>'
            '<script>fetch("/api/feedback", {method: "POST"})</script>', encoding="utf-8")
        problems = FEEDBACK.check_project(self.project)
        self.assertEqual(len(problems), 1)
        self.assertIn("直存时代", problems[0])

    def test_the_shipped_template_is_accepted(self):
        self.assertEqual(FEEDBACK.check_project(self.project), [])


# --- ① the host really serves *this* project -------------------------------

@unittest.skipUnless(have_node(), "needs node to run the review host")
class HostIdentityCase(SurfaceWrittenCase):
    """「不端出旧项目」这条守卫在新宿主下的形状。

    旧的判据是**端口**：服务绑死 8899，被占就报错退出，绝不端出上一个项目的页面。
    新宿主用 `--port 0`，端口不会冲突 —— 能证明身份的只剩**内容**。这里用
    「它 serve 的项目文件逐字节等于磁盘」（默认取 surface 里 `watch` 声明的那个），
    而不是「页面逐字节相等」：页面是几个 Skill 共用的模板，本来也分不出项目。
    """

    def setUp(self):
        super().setUp()
        self.host = SURFACE.open_review(self.project, open_browser=False)
        self.addCleanup(self._stop)

    def _stop(self):
        HOST.stop_host(self.host)

    def get(self, url):
        with urllib.request.urlopen(url, timeout=5) as response:
            return response.status, response.read()

    def origin(self):
        """宿主的 origin（`http://host:port`）。**注意不是** `url.rsplit('/', 1)[0]` ——
        那是 `…/review`，页面在子目录里时两者差一级，正好是这套东西最容易错的地方。"""
        parts = urllib.parse.urlsplit(self.host["url"])
        return f"{parts.scheme}://{parts.netloc}"

    def status_of(self, url):
        try:
            return self.get(url)[0]
        except urllib.error.HTTPError as exc:
            exc.close()
            return exc.code

    def test_host_serves_the_page_with_the_bridge_injected_and_a_project_file(self):
        status, page = self.get(self.host["url"])
        self.assertEqual(status, 200)
        # 桥由宿主注入：注入点已被换掉，页面里没有桥的副本
        self.assertNotIn(b"{{REVIEW_BRIDGE}}", page)
        self.assertTrue(HOST.served_entry_is_ours(self.project / FEEDBACK.PAGE_REL, page), page[:400])
        # 页面读的那个项目文件也必须真的 serve 得到（rel 相对 dir＝项目根，不是相对页面）
        status, body = self.get(self.origin() + "/timeline/timeline.json")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), json.loads(json.dumps(TIMELINE)))

    def test_a_live_host_is_reused_not_restarted(self):
        again = SURFACE.open_review(self.project, open_browser=False)
        self.assertFalse(again["started"])
        self.assertTrue(again["reused"])
        self.assertEqual(again["pid"], self.host["pid"])

    def test_a_dead_host_is_not_reused(self):
        state = HOST.host_state(SURFACE.surface_path(self.project))
        state["pid"] = 999999                      # 一定不存在的 pid
        (self.project / SURFACE.HOST_STATE_REL).write_text(json.dumps(state), encoding="utf-8")
        self.assertIsNone(HOST.host_alive(SURFACE.surface_path(self.project)))
        again = SURFACE.open_review(self.project, open_browser=False)
        self.assertTrue(again["started"])
        self.addCleanup(HOST.stop_host, again)

    def test_a_foreign_host_is_not_mistaken_for_ours(self):
        """**这条就是「不端出旧项目」。** 一个活着的宿主、页面也对，但它的
        `timeline/timeline.json` 不是我们的 → 不许认它。"""
        other = make_project(Path(tempfile.mkdtemp(prefix="video-craft-review-other-")).resolve(),
                             timeline=dict(TIMELINE, totalDurationMs=1,
                                           chapters=[{"id": "someone-else", "title": "别人的", "steps": []}]))
        SURFACE.write_surface(other)
        state = dict(HOST.host_state(SURFACE.surface_path(self.project)))     # 指向**我们这个项目**的宿主
        (other / SURFACE.HOST_STATE_REL).write_text(json.dumps(state), encoding="utf-8")
        self.assertIsNone(HOST.host_alive(SURFACE.surface_path(other)))

    def test_a_statically_served_directory_is_not_taken_for_a_host(self):
        """有人拿 `python -m http.server` 直接把目录端出来：页面在、端口在、pid 在，
        但注入点没被换过 —— 那不是审阅宿主，桥永远不会加载。"""
        class Quiet(http.server.SimpleHTTPRequestHandler):
            def log_message(self, *args):
                pass

        handler = functools.partial(Quiet, directory=str(self.project))
        srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        state = {"pid": os.getpid(), "url": f"http://127.0.0.1:{srv.server_address[1]}/review/index.html"}
        self.assertIsNone(HOST.host_alive(SURFACE.surface_path(self.project), state))

    def test_an_unreachable_host_url_is_not_alive(self):
        state = dict(HOST.host_state(SURFACE.surface_path(self.project)))
        state["url"] = "http://127.0.0.1:1/review/index.html"
        self.assertIsNone(HOST.host_alive(SURFACE.surface_path(self.project), state))

    def test_the_host_refuses_paths_outside_dir(self):
        base = self.host["url"].rsplit("/", 1)[0]
        for path in ("/../../etc/passwd", "/../review-surface.json", "/etc/passwd", "/nope"):
            with self.subTest(path=path):
                self.assertEqual(self.status_of(base + path), 404)

    def test_startup_report_is_parsed_from_a_pretty_printed_log(self):
        # 启动自证是跨多行的 JSON，日志里还混着别的输出 —— 逐行解析永远失败，实测踩到过。
        log = self.project / "review" / "review_host.log"
        self.assertTrue(log.is_file())
        report = HOST._startup_report(log)
        self.assertEqual(report["url"], self.host["url"])
        self.assertEqual(report["feedback_path"], str(self.project / "review" / "review-submissions.json"))

    def test_stop_host_really_stops_it_and_reaps_it(self):
        """`stop_host` 报 true 才算收干净。踩过一次：`os.kill(pid, 0)` 对**僵尸**也返回成功，
        于是宿主明明已经关了，这里却报"没停掉"，还因此以为漏了进程。判死活要看句柄
        （`Popen.poll()` 顺手回收僵尸），必要时升级到 SIGKILL。"""
        pid = self.host["pid"]
        self.assertTrue(HOST.stop_host(self.host))
        self.assertFalse(HOST._pid_alive(pid))

    def test_a_stopped_host_is_not_reused(self):
        HOST.stop_host(self.host)
        self.assertIsNone(HOST.host_alive(SURFACE.surface_path(self.project)))
        again = SURFACE.open_review(self.project, open_browser=False)
        self.addCleanup(HOST.stop_host, again)
        self.assertTrue(again["started"])
        self.assertNotEqual(again["pid"], self.host["pid"])

    def test_the_host_really_answers_on_its_socket(self):
        """GOTCHAS #8: an HTTP 200 is not proof —— 但它也不是零。宿主得真的答。"""
        self.assertIsNotNone(HOST.host_alive(SURFACE.surface_path(self.project)))
        # 进程还在，但状态文件被抹掉 → 不算「活着」，会重起
        (self.project / SURFACE.HOST_STATE_REL).unlink()
        self.assertIsNone(HOST.host_alive(SURFACE.surface_path(self.project)))


# --- telling "our live host" apart, without guessing the injection ----------

class PageIdentityCase(TempProjectCase):
    """`served_entry_is_ours` 的判据必须与"宿主把标记换成了什么"无关。

    踩过一次：第一版把"标记该被换成 `/__review/bridge.js`"写死，宿主改了注入形态之后
    它**静默**永远为假 —— 活着的宿主被判成死的，没有报错，只是每次开审阅多起一个进程。
    """

    @property
    def entry(self):
        return self.project / FEEDBACK.PAGE_REL

    def served(self, injected):
        return self.entry.read_text(encoding="utf-8").replace(
            "{{REVIEW_BRIDGE}}", injected).encode("utf-8")

    def test_accepts_any_injection_shape(self):
        for injected in ('<script src="/__review/bridge.js"></script>',
                         '<script>window.__REVIEW_BASE__="/"</script>\n<script src="/x.js"></script>',
                         '<script>/* 插件内联的桥源码，很长很长 */</script>'):
            with self.subTest(injected=injected[:40]):
                self.assertTrue(HOST.served_entry_is_ours(self.entry, self.served(injected)))

    def test_the_marker_must_actually_have_been_replaced(self):
        # 原样端出来的静态文件（拿目录当 http.server）不算
        self.assertFalse(HOST.served_entry_is_ours(self.entry, self.served("")))
        self.assertFalse(HOST.served_entry_is_ours(self.entry, self.served("{{REVIEW_BRIDGE}}")))

    def test_a_different_page_is_not_ours(self):
        other = make_project(Path(tempfile.mkdtemp(prefix="video-craft-review-other-")).resolve(),
                             page="<!doctype html><html><body>{{REVIEW_BRIDGE}}<p>别人的页</p></body></html>")
        page = (other / FEEDBACK.PAGE_REL).read_text(encoding="utf-8").replace(
            "{{REVIEW_BRIDGE}}", "<script>x</script>").encode("utf-8")
        self.assertFalse(HOST.served_entry_is_ours(self.project / FEEDBACK.PAGE_REL, page))


# --- the page half of the property -----------------------------------------

class ReviewPageTemplateTests(unittest.TestCase):
    """The page half: it must talk to the host through the bridge, not around it."""

    def setUp(self):
        self.html = TEMPLATE.read_text(encoding="utf-8")

    def test_page_leaves_a_bridge_inject_point_and_carries_no_copy(self):
        self.assertIn("{{REVIEW_BRIDGE}}", self.html)
        # 页面里不能有桥的副本（插件模式下页面地址是路由，相对引用会 404）
        self.assertNotIn("review-bridge.js", self.html)

    def test_inject_point_is_a_bare_marker_on_its_own_line(self):
        """标记必须**裸着独占一行**：宿主把整段标签原地换进来，放进 `src=""` 或塞进
        `<script>` 里都会把标签撑破（三种错法都真的炸过，见 GOTCHAS #32）。"""
        self.assertEqual(self.html.count("{{REVIEW_BRIDGE}}"), 1)
        lines = [line for line in self.html.split("\n") if line.strip() == "{{REVIEW_BRIDGE}}"]
        self.assertEqual(len(lines), 1, "标记必须裸着独占一行")
        self.assertNotIn('<script src="{{REVIEW_BRIDGE}}"></script>', self.html)
        self.assertNotIn("<script>{{REVIEW_BRIDGE}}</script>", self.html)

    def test_the_marker_is_not_mentioned_anywhere_else_in_the_page(self):
        """注释里再写一次也是"出现两次" —— 校验器会判 multiple，而且那是真的会注入两遍。
        所以解释写在别的文件里（GOTCHAS / review-ui），不写进页面。"""
        self.assertNotIn("src=\"{{", self.html)

    def test_page_no_longer_posts_to_a_private_endpoint(self):
        # 直存时代的 `/api/feedback` 已经退役：页面不许再自己 POST
        self.assertNotIn('fetch("/api/feedback"', self.html)
        self.assertNotIn('fetch("/api/health"', self.html)

    def test_page_goes_through_the_bridge_for_everything(self):
        self.assertIn("ReviewBridge.connect", self.html)
        self.assertIn("review.write(", self.html)
        self.assertIn("review.wake(", self.html)
        # 时间轴与 surface 都走桥读，不自己 fetch 相对路径
        self.assertIn("review.readText(", self.html)
        self.assertNotIn('fetch("../timeline/timeline.json")', self.html)

    def test_page_no_longer_offers_a_clipboard_step(self):
        self.assertNotIn("navigator.clipboard", self.html)
        self.assertNotIn("生成反馈行", self.html)

    def test_page_keeps_the_save_state_and_the_text_on_failure(self):
        self.assertIn('id="save-state"', self.html)
        self.assertIn("文字仍在输入框", self.html)

    def test_page_waits_for_the_host_before_enabling_save(self):
        self.assertIn('id="fb-save" disabled', self.html)
        self.assertIn("没有加载到审阅桥", self.html)

    def test_page_does_not_claim_the_host_verified_the_wake(self):
        """没有插件时没有人可唤 —— 状态条不许把它说成「模型已经知道」。"""
        self.assertIn("未核对", self.html)

    def test_page_reads_the_record_schema_it_sends(self):
        for field in ("chapterId", "stepId", "stepIndex", "caption", "durationMs",
                      "type", "text", "status", "batchId", "createdAt"):
            with self.subTest(field=field):
                self.assertIn(field, self.html)

    def test_draft_storage_is_guarded_because_opaque_frames_throw(self):
        """有插件时页面在不透明源 iframe 里，`localStorage` 读一下就直接抛
        SecurityError。草稿是便利，不是承诺 —— 不许因此让整页崩掉。"""
        self.assertNotIn("localStorage", self.html)
        self.assertIn("await review.draft(", self.html)
        self.assertIn("await review.readText(DRAFT_REL)", self.html)
        self.assertIn("草稿保存失败", self.html)

    def test_inline_script_is_not_cut_short_by_a_literal_close_tag(self):
        """内联脚本里出现脚本结束标签的**字面量**，HTML 解析器会在那里把脚本切断 → 整页静默白掉
        （实测踩到过：页头照常显示"6 章 · 23 步"，下面一屏都没有，浏览器里只有一句
        `Unexpected end of input`）。注释里写它也不行。"""
        start = self.html.rindex("<script>")
        end = self.html.index("</script>", start)
        self.assertNotIn("</script", self.html[start:end])

    @unittest.skipUnless(have_node(), "needs node to syntax-check the page script")
    def test_inline_script_parses(self):
        import subprocess
        start = self.html.rindex("<script>") + len("<script>")
        end = self.html.index("</script>", start)
        script = Path(tempfile.mkdtemp(prefix="video-craft-page-")) / "page.js"
        script.write_text(self.html[start:end], encoding="utf-8")
        result = subprocess.run([HOST.node_binary(), "--check", str(script)],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr[-800:])

    def test_the_page_offers_both_an_overall_and_a_per_step_entry(self):
        """页面不许把逐单位当成唯一入口（模组 design-and-porting-rules R10）。

        自检问法：「我不想针对任何一个单位，只想说一句整体意见 —— 页面允许吗？」
        """
        self.assertIn('data-mode="overall"', self.html)
        self.assertIn('data-mode="step"', self.html)
        # 默认落在「整片意见」：刚打开什么都没选时，不需要先点任何东西
        self.assertIn('setMode("overall")', self.html)
        # 整片那条的记录形状：带 phase、**不带**单位字段
        self.assertIn('return { phase: "overall", ...stale, ...common };', self.html)
        self.assertNotIn('stepId: null', self.html)
        self.assertNotIn('stepId: ""', self.html)

    def test_the_page_no_longer_requires_a_step_to_save(self):
        """旧行为：保存前先查 `state.step` —— 逐屏成了唯一入口。现在只在"当前屏"那一路查。"""
        start = self.html.index("async function save()")
        body = self.html[start:self.html.index("document.getElementById(\"fb-mode\")", start)]
        self.assertIn('fbMode === "step" && !state.step', body)
        self.assertNotIn('if (!state.step) {', body)

    def test_the_staleness_fingerprint_covers_what_the_record_snapshots(self):
        """只比结构会漏掉 caption —— 而记录抄走的正是 caption。实测踩到过。"""
        start = self.html.index("function fingerprint(data)")
        body = self.html[start:self.html.index("async function loadTimeline()", start)]
        for field in ("caption", "durationMs", "screenIntent", "title"):
            with self.subTest(field=field):
                self.assertIn(field, body)

    def test_every_action_the_page_asks_for_has_a_control_on_the_page(self):
        """**提示里要求人做的动作，必须在页面上做得到。**

        用户报过一次：陈旧提示让人"重新加载这一页"，而页面上根本没有那个按钮 ——
        人被要求按一个不存在的东西。所以这里钉住：说得出「重新加载」，就得有一个真的
        `location.reload()` 控件，而且它跟那句提示在同一块里（出现的那一刻就够得着）。
        """
        html = self.html
        # ① 页面里提到"重新加载"这个动作 → 必须真的有控件
        self.assertIn("重新加载", html)
        self.assertIn("location.reload()", html)
        self.assertIn('id = "stale-reload"', html)
        # ② 控件由渲染提示的那个函数挂上去（不是另找一个地方）
        start = html.index("function noteStaleFree(")
        body = html[start:html.index("async function loadTimeline()", start)]
        self.assertIn("location.reload()", body)
        self.assertIn('withReload', body)
        # ③ 陈旧那两处提示必须带上它
        self.assertIn('{ withReload: true }', html)
        self.assertGreaterEqual(html.count("{ withReload: true }"), 2)

    def test_saving_cannot_re_enter_and_lose_a_record(self):
        """保存是「读回旧的 → 合并 → 整体写」；两次并发会**丢掉一条**（后写的盖掉先写的）。

        按钮在保存期间是 disabled，鼠标点不进来 —— 但 **Cmd-S 也调 save()**，它不看按钮。
        这条守卫是"意见不能丢"那一类。
        """
        start = self.html.index("async function save()")
        body = self.html[start:self.html.index("document.getElementById(\"fb-mode\")", start)]
        self.assertIn("if (saving) return;", body)
        self.assertIn("saving = true;", body)
        self.assertIn("saving = false;", body)
        # 守卫要在读文件之前（否则两次都已经读过了，守卫没意义）
        self.assertLess(body.index("if (saving) return;"), body.index("collectRecords()"))

    def test_the_stale_warning_also_reaches_the_record_not_only_the_human(self):
        """**只给人看的告警 = 机器看不见的告警**（模组规则 R5b）。

        用户当场发现的：橙条挂了、提示也写了，可提交上来的记录干干净净 —— 模型不知道那是
        "对着旧文字说的意见"。所以这个字段必须进记录，而且**只在真陈旧时**出现。
        """
        html = self.html
        self.assertIn('stale: true', html)
        self.assertIn("stale_timeline", html)
        # 条件展开：不是常态字段
        self.assertIn("staleNoted ?", html)
        # 两种形状都要带得上（整片那条也会对着旧版说）
        start = html.index("function buildRecord(")
        body = html[start:html.index("async function save()", start)]
        self.assertEqual(body.count("...stale"), 2, "整片与逐屏两种形状都要带上它")
        # 短 id 同步可算（不依赖 crypto.subtle 的异步/安全上下文）
        self.assertIn("function shortId(", html)
        self.assertIn("Math.imul", html)

    def test_the_page_can_always_refresh_itself_not_only_when_data_changed(self):
        """**页面必须能刷新自己，而且入口不许藏在告警里**（模组规则 R11）。

        用户报的正是这一种：改了页面让他重载拿新版，而他重载不了 —— 因为刷新入口只做在
        橙色告警里（要"数据变了"才出现），而那按钮本来就在他要拿的新版里。先有鸡先有蛋。
        "页面变了"与"数据变了"是两件事。
        """
        html = self.html
        # ① 永久入口存在，而且**不在**告警块里
        self.assertIn('id="page-reload"', html)
        note_at = html.index('id="stale-note"')
        self.assertLess(html.index('id="page-reload"'), note_at, "永久入口不能长在告警块里")
        # ② 它**不依赖页面自己的 JS**：纯 HTML 链接，空 href ＝重新加载当前地址
        #    （"页面自己的脚本是旧的/坏的"这一档，恰恰是最需要它的时候）
        head = html[html.index('id="page-reload"') - 200:html.index('id="page-reload"') + 200]
        self.assertIn('<a', head)
        self.assertIn('href=""', head)
        self.assertNotIn('onclick', head)
        # ③ 告警里那个仍然在（提示出现时出口就在眼前）
        self.assertGreaterEqual(html.count("{ withReload: true }"), 2)
        self.assertIn('id = "stale-reload"', html)

    def test_the_local_draft_is_not_gated_on_the_timeline_loading(self):
        """同一族的第二处：草稿只在时间轴读到时才放回输入框 —— 而那正是最想找回自己那段字的时候。

        （重打一遍还会被 `saveDraft` 覆盖掉，等于丢。）
        """
        start = self.html.index("submissionsRel = await resolveSubmissionsRel()")
        boot = self.html[start:]
        self.assertIn("restoreDraft();", boot)
        self.assertNotIn("if (data) restoreDraft();", boot)
        # Draft retrieval is an independent bridge operation; it runs before timeline loading.
        self.assertIn('await restoreDraft();\n      await loadTimeline();', boot)
        self.assertIn('if (!draft) return;', self.html)

    def test_the_page_does_not_send_people_left_for_something_on_the_right(self):
        """播放器提示曾说"选中左侧对应 step"，而 step 列表在右栏。"""
        start = html_start = self.html.index('class="hint"')
        hint = self.html[start:self.html.index("</div>", start)]
        self.assertIn("右侧列表", hint)
        self.assertNotIn("左侧对应", hint)

    def test_page_reads_the_submission_path_from_the_surface(self):
        """提交文件由 surface 声明，页面读回来 —— 不在页面里再抄一份会漂移的路径。"""
        self.assertIn("REVIEW_SURFACE_REL", self.html)
        self.assertIn("doc.feedback", self.html)


if __name__ == "__main__":
    unittest.main()
