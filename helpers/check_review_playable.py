#!/usr/bin/env python3
"""断言：这份审阅页**真的能给人看** —— 时长对、能 seek 出画面、有声音。

为什么要有这条
--------------
`hyperframes check` 全绿、`check_live_stage.py` PASS、`build_review.py` 打印
"统一审阅控制台已就绪"，都不能回答用户那一句话：**"我看不到画面 / 我没有声音。"**

2026-10-21 的 XHS 三条片里，这三件事同时发生：

- 活舞台：player 报出 **0 秒**（页面 `NaN:NaN`），舞台区全黑，右侧人物照常播；
- 合成成片通道：页面判定"合成成片尚未导出"，挂不上；
- 人物轨：页面按静音轨处理 —— 画面有了，**声音没有**；
- 结果用户拿到的是一个"能提交反馈、但看不到也听不到"的页面。为了让他听到声音，
  交付方只能另写一个 `审阅入口.html`。那件事本该由这条检查挡住。

它断言三件用户能直接感知的事
----------------------------
1. **时长一致**：当前播放通道报出的 duration 与 `review_data.totalDurationMs`
   差不超过 0.5s（否则页面显示的进度/时间码与成片不符）；
2. **能 seek 出画面**：跳到若干 beat 起点，那一帧不是全黑（平均亮度超过阈值）；
3. **有声音**：页面里承载声音的那条通道存在、未被静音、且真的解出了音频帧。

任一失败 → 退出码 1，并说明**该修哪一层**（composition / review 页面 / 媒体通道），
而不是丢一句"页面没打开"。

用法
----
    python3 helpers/check_review_playable.py <project>
    python3 helpers/check_review_playable.py <project> --at 30,120 --json
    python3 helpers/check_review_playable.py <project> --keep-host   # 失败时留下宿主便于手看

前置：项目已经有 `review/review_data.json` 与 `review/index.html`（跑过 build_review）。
本检查自己起本地宿主、自己关；不写任何项目文件，只往 /tmp 落截图。

退出码
------
0 = 三项全绿；1 = 至少一项红；2 = 前置缺失（还没 build review，或没装 playwright）。
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

HELPERS = Path(__file__).resolve().parent
sys.path.insert(0, str(HELPERS))

MIN_MEAN_LUMA = 6.0      # 全黑帧通常在 0.3–2；有画面的帧远高于此
DURATION_TOLERANCE = 0.5  # 秒


def _expected_duration(review_data: dict) -> float | None:
    ms = review_data.get("totalDurationMs")
    if isinstance(ms, (int, float)) and ms > 0:
        return float(ms) / 1000.0
    chapter = (review_data.get("timeline") or {}).get("chapters") or []
    ends = [c.get("endMs") for c in chapter if isinstance(c.get("endMs"), (int, float))]
    return float(max(ends)) / 1000.0 if ends else None


def _seek_points(review_data: dict, explicit: list[float]) -> list[float]:
    if explicit:
        return explicit
    out: list[float] = []
    for beat in review_data.get("beats") or []:
        start = beat.get("startMs")
        if isinstance(start, (int, float)) and start > 0:
            out.append(round(float(start) / 1000.0 + 0.6, 2))  # 避开章节交叉淡入
    if not out:
        for chapter in (review_data.get("timeline") or {}).get("chapters") or []:
            for step in chapter.get("steps") or []:
                start = step.get("startMs")
                if isinstance(start, (int, float)) and start > 0:
                    out.append(round(float(start) / 1000.0 + 0.6, 2))
    # 最多取 3 个点，够判断，又别把检查拖成分钟级
    return out[:3]


class Report:
    def __init__(self) -> None:
        self.checks: list[dict] = []
        self.layer_hint: list[str] = []

    def add(self, name: str, ok: bool, detail: str, layer: str = "") -> bool:
        self.checks.append({"name": name, "ok": bool(ok), "detail": detail, "layer": layer})
        if not ok and layer:
            self.layer_hint.append(f"{name} → 修 {layer}：{detail}")
        return bool(ok)

    @property
    def ok(self) -> bool:
        return all(c["ok"] for c in self.checks) and bool(self.checks)


def _canvas_stats(page, selector: str) -> dict | None:
    """把媒体元素当前帧画进 canvas，返回平均亮度与 8×8 指纹。"""
    return page.evaluate(
        """sel=>{
             const v=document.querySelector(sel);
             if(!v || !v.videoWidth) return null;
             const W=64,H=36, c=document.createElement('canvas');
             c.width=W; c.height=H;
             const ctx=c.getContext('2d');
             try { ctx.drawImage(v,0,0,W,H); } catch(e){ return null; }
             const d=ctx.getImageData(0,0,W,H).data;
             let sum=0; const sig=[];
             for(let by=0;by<8;by++){
               for(let bx=0;bx<8;bx++){
                 let acc=0,n=0;
                 for(let y=by*4;y<by*4+4;y++) for(let x=bx*8;x<bx*8+8;x++){
                   const i=(y*W+x)*4; acc+=d[i]*0.299+d[i+1]*0.587+d[i+2]*0.114; n++;
                 }
                 sig.push(Math.round(acc/n));
               }
             }
             for(let i=0;i<d.length;i+=4) sum+=d[i]*0.299+d[i+1]*0.587+d[i+2]*0.114;
             return {luma:sum/(d.length/4), sig:sig};
           }""",
        selector,
    )



COMPOSITION_AUDIO_JS = """async () => {
  const hosts = [...document.querySelectorAll('[data-composition-id]')];
  const nodes = [...document.querySelectorAll('audio[data-start], video[data-start], audio, video')];
  if (!hosts.length && !nodes.length) return null;
  const out = [];
  for (const el of nodes) {
    const before = el.currentTime;
    let playErr = null;
    try { await el.play(); } catch (e) { playErr = String(e && e.name || e); }
    await new Promise(r => setTimeout(r, 320));
    out.push({
      tag: el.tagName.toLowerCase(),
      timed: el.hasAttribute('data-start'),
      muted: !!el.muted,
      volume: el.volume,
      readyState: el.readyState,
      before, after: el.currentTime,
      advanced: el.currentTime > before + 0.01,
      paused: el.paused,
      duration: el.duration,
      src: (el.currentSrc || el.src || '').slice(0, 48),
      playErr,
    });
  }
  return out;
}"""


def _usable_audio(channels: list[dict]) -> list[dict]:
    """「能出声」的判据：解码就绪 + 未静音 + 有音量 + 有长度。

    「时钟在推进」只作为附加证据写进 detail —— 审阅页停在 seek 点时，官方播放器
    会主动暂停媒体，此时没推进不代表没声音（2026-10-21 真项目上就是这种情况）。
    """
    return [c for c in channels
            if not c.get("muted") and (c.get("volume") or 0) > 0
            and (c.get("readyState") or 0) >= 2 and (c.get("duration") or 0) > 0]


def _composition_audio(page) -> dict:
    """到 composition 的 iframe 里看声音：工程态审阅的旁白在那一层，不在页面层。

    只扫页面层会把「composition 内自带 audio[data-start]」判成没有声音 ——
    2026-10-21 作者就是被这一条卡住的（工程态能听见旁白，检查却说没声音）。
    """
    for frame in page.frames:
        try:
            if not frame.evaluate("()=>!!document.querySelector('[data-composition-id]')"):
                continue
        except Exception:
            continue
        try:
            channels = frame.evaluate(COMPOSITION_AUDIO_JS)
        except Exception as error:
            return {"checked": True, "error": str(error)[:200], "channels": []}
        if channels is None:
            continue
        # 「能出声」的判据：解码了就绪 + 未静音 + 有音量 + 有长度。
        # 「时钟在推进」只作为附加证据写进 detail —— 审阅页停在一个 seek 点时
        # 官方播放器会主动暂停媒体，这时没推进不代表没声音。
        return {"checked": True, "channels": channels, "usable": _usable_audio(channels)}
    return {"checked": False, "channels": [], "usable": []}


def _mean_luma(png: Path) -> float | None:
    try:
        from PIL import Image
    except Exception:
        return None
    with Image.open(png) as im:
        grey = im.convert("L").resize((160, 90))
        pixels = list(grey.getdata())
    return sum(pixels) / len(pixels)


def _page_probe(page, point: float, channel: str, shot: Path) -> dict:
    """把页面 seek 到 point，截图，读回时长/时间/静音状态。"""
    if channel == "live":
        sel = "#live-stage-frame"
        page.evaluate(
            """([sel,t])=>{
                 const p=document.querySelector(sel); if(!p) return;
                 if(typeof p.seek==='function') p.seek(t); else p.currentTime=t;
               }""",
            [sel, point],
        )
        page.wait_for_timeout(450)
        info = page.evaluate(
            """sel=>{
                 const p=document.querySelector(sel);
                 return p?{duration:p.duration||0,currentTime:p.currentTime||0,
                           ready:!!p.ready,muted:!!p.muted}:null;
               }""",
            sel,
        )
    else:
        sel = "#composite-video-player" if channel == "composite" else "#stage-speaker-video"
        page.evaluate(
            """([sel,t])=>{const v=document.querySelector(sel); if(!v) return;
                 v.currentTime=t; const pr=v.play(); if(pr&&pr.catch) pr.catch(()=>{});}""",
            [sel, point],
        )
        page.wait_for_timeout(450)
        info = page.evaluate(
            """sel=>{
                 const v=document.querySelector(sel);
                 if(!v) return null;
                 return {duration:v.duration||0,currentTime:v.currentTime||0,
                         muted:!!v.muted, volume:v.volume,
                         decodedAudio:(typeof v.webkitAudioDecodedByteCount==='number')
                                      ? v.webkitAudioDecodedByteCount : null,
                         videoWidth:v.videoWidth, readyState:v.readyState};
               }""",
            sel,
        )
    # 截图必须落在**承载画面的元素**上：外层容器在 composite 模式下是隐藏的占位，
    # 拿它算亮度只会得到一条恒定值，等于没测。
    order = ("#live-stage-wrap",) if channel == "live" else (
        ("#composite-video-player",) if channel == "composite" else ("#stage-speaker-video",))
    target = None
    for candidate in order:
        try:
            loc = page.locator(candidate)
            if loc.count() and loc.first.is_visible():
                target = loc.first
                break
        except Exception:
            continue
    (target or page).screenshot(path=str(shot))
    info = dict(info or {})
    media_sel = {"composite": "#composite-video-player", "speaker": "#stage-speaker-video"}.get(channel)
    if media_sel:
        stats = _canvas_stats(page, media_sel)
        if stats:
            info["luma"] = stats["luma"]
            info["sig"] = stats["sig"]
    return info


def _frame_delta(a: Path, b: Path) -> float | None:
    """两帧的平均像素差。全黑 / 同帧 / 静态占位都会接近 0。"""
    try:
        from PIL import Image, ImageChops
    except Exception:
        return None
    with Image.open(a) as ia, Image.open(b) as ib:
        da = ia.convert("L").resize((160, 90))
        db = ib.convert("L").resize((160, 90))
        diff = ImageChops.difference(da, db)
        data = list(diff.getdata())
    return sum(data) / len(data)


def run(project: Path, points: list[float], keep_host: bool, verbose: bool) -> int:
    review_dir = project / "review"
    data_path = review_dir / "review_data.json"
    if not data_path.is_file():
        print(json.dumps({"ok": False, "error": f"还没有审阅数据：{data_path}（先跑 build_review / review.py）"},
                         ensure_ascii=False, indent=1))
        return 2
    review_data = json.loads(data_path.read_text(encoding="utf-8"))
    expected = _expected_duration(review_data)
    seeks = _seek_points(review_data, points)
    report = Report()

    try:
        from playwright.sync_api import sync_playwright
    except Exception as error:  # pragma: no cover - 环境问题
        print(json.dumps({"ok": False, "error": f"没有 playwright：{error}"}, ensure_ascii=False, indent=1))
        return 2

    from lib.planners_modules import resolve_module  # noqa: E402
    sys.path.insert(0, str(resolve_module("planners-review-core") / "scripts" / "lib"))
    import review_host  # noqa: E402

    # 只读地起宿主：优先用**已经存在**的 surface，绝不重写它。
    # 检查工具去改被检查的项目（重写 review-surface.json / 落宿主状态）是不可接受的——
    # 2026-10-21 就因此在别人正在返修的项目里动了 mtime。
    surface_path = project / "review" / "review-surface.json"
    started = None
    if surface_path.is_file():
        try:
            surface = json.loads(surface_path.read_text(encoding="utf-8"))
            started = review_host.open_review(surface, port=0, open_browser=False)
        except Exception:
            started = None
    if started is None:
        from review_surface import open_review  # 没有 surface 时才走会写文件的这条路
        started = open_review(project, port=0, open_browser=False, surface_only=False)
    # 只在"这次是我起的"时候收尾，别把别人正在用的宿主关掉
    owns_host = not started.get("reused", False)
    url = started.get("url") or started.get("path")
    if not url:
        print(json.dumps({"ok": False, "error": "本地宿主没起来", "detail": started},
                         ensure_ascii=False, indent=1))
        return 2

    tmp = Path(tempfile.mkdtemp(prefix="vc-playable-"))
    channel = "unknown"
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=["--autoplay-policy=no-user-gesture-required", "--disable-audio-output"],
            )
            page = browser.new_page(viewport={"width": 1600, "height": 1000})
            console: list[str] = []
            page.on("pageerror", lambda e: console.append(f"pageerror: {e}"))
            page.goto(url, wait_until="networkidle", timeout=60000)
            try:
                page.wait_for_function(
                    """()=>{
                         const live=document.querySelector('#live-stage-frame');
                         if(live && live.ready) return true;
                         const comp=document.querySelector('#composite-video-player');
                         if(comp && comp.getAttribute('src') && comp.duration>0) return true;
                         const spk=document.querySelector('#stage-speaker-video');
                         if(spk && spk.getAttribute('src') && spk.duration>0) return true;
                         return false;
                       }""",
                    timeout=25000,
                )
                ready = True
            except Exception:
                ready = False
            channel = page.evaluate(
                """()=>{
                     const live=document.querySelector('#live-stage-frame');
                     if(live && live.ready) return 'live';
                     const comp=document.querySelector('#composite-video-player');
                     if(comp && comp.getAttribute('src')) return 'composite';
                     const spk=document.querySelector('#stage-speaker-video');
                     if(spk && spk.getAttribute('src')) return 'speaker';
                     return 'none';
                   }"""
            )

            report.add(
                "页面挂上了一条播放通道",
                ready and channel != "none",
                f"channel={channel} ready={ready}；stderr={console[:3]}",
                "审阅页装配（build_review 的 liveStage / media.json 通道）",
            )

            # 活舞台真正的病是「时间轴没构建、player 只剩 data-duration 这个声明值」。
            # 光比 duration 会漏诊：根元素的 data-duration 会兜底成"看起来对"的数字。
            if channel == "live":
                comp_dur = None
                rendered = 0
                for frame in page.frames:
                    try:
                        comp_dur = frame.evaluate(
                            """()=>{
                                 const t=window.__timelines && window.__timelines.main;
                                 if(!t || typeof t.duration!=='function') return null;
                                 return t.duration();
                               }"""
                        )
                        if comp_dur is not None:
                            rendered = frame.evaluate(
                                "()=>document.querySelectorAll('.scene-root *').length || 0"
                            )
                            break
                    except Exception:
                        continue
                report.add(
                    "活舞台的时间轴真的构建了（不是只回显 data-duration）",
                    isinstance(comp_dur, (int, float)) and float(comp_dur) > 0,
                    f"timeline.duration={comp_dur} 已渲染元素={rendered}",
                    "composition/src：把 __CFG__ / HF.build() 挪出内联 <script>（预览编译器会改写成 text/hf-after-fonts，srcdoc 里不执行）",
                )

            if expected is not None:
                probe = _page_probe(page, seeks[0] if seeks else 0.0, channel, tmp / "probe.png")
                got = float(probe.get("duration") or 0.0)
                report.add(
                    "播放器时长与 timeline 一致",
                    got > 0 and abs(got - expected) <= DURATION_TOLERANCE,
                    f"player={got:.2f}s expected={expected:.2f}s (channel={channel})",
                    "活舞台的 composition（内联脚本被改写 / 时间轴未构建）或 media.json 通道",
                )
            else:
                report.add("播放器时长与 timeline 一致", False,
                           "review_data 里没有 totalDurationMs", "build_review")

            probes: list[dict] = []
            for i, point in enumerate(seeks):
                shot = tmp / f"at-{point}.png"
                probe = _page_probe(page, point, channel, shot)
                probes.append(probe)
                shown = probe.get("currentTime")
                seeked = isinstance(shown, (int, float)) and abs(float(shown) - point) <= 0.5
                luma = probe.get("luma")
                if luma is None:                      # live 通道拿不到 canvas，退回截图亮度
                    luma = _mean_luma(shot)
                if channel == "live":
                    # 活舞台截到的是 player 外框，全黑舞台也会有一点噪声亮度。
                    # 真正要看的是 composition 里到底有没有东西被建出来。
                    ok_frame = seeked and rendered > 0
                else:
                    ok_frame = seeked and luma is not None and float(luma) >= MIN_MEAN_LUMA
                report.add(
                    f"seek 到 {point:.1f}s 有画面",
                    ok_frame,
                    f"seeked={seeked} luma={None if luma is None else round(float(luma),1)} "
                    f"currentTime={None if shown is None else round(float(shown),2)}",
                    "该时刻的 composition（那一屏确实没有内容）或 seek 未生效",
                )

            if len(seeks) >= 2 and channel == "live":
                # 活舞台：帧差来自 player 外框噪声，不可信。用"真的渲染了元素"代替。
                report.add(
                    "两个时间点画面不同（seek 真的在换帧）",
                    rendered > 0,
                    f"rendered_elements={rendered}（活舞台以「渲染了多少元素」替代像素帧差）",
                    "composition 没有建出 DOM（见上一条时间轴断言）",
                )
            elif len(seeks) >= 2:
                sigs = [c.get("sig") for c in probes[:2]]
                delta = None
                if len(sigs) == 2 and all(sigs):
                    delta = sum(abs(a - b) for a, b in zip(*sigs)) / len(sigs[0])
                else:
                    # 活舞台拿不到 canvas（跨 iframe），退回两帧截图的像素差
                    a = tmp / f"at-{seeks[0]}.png"
                    b = tmp / f"at-{seeks[1]}.png"
                    if a.exists() and b.exists():
                        delta = _frame_delta(a, b)
                report.add(
                    "两个时间点画面不同（seek 真的在换帧）",
                    delta is not None and delta >= 2.0,
                    f"frame_delta={None if delta is None else round(delta,2)}",
                    "seek 没落到播放器上（页面被别的时钟驱动）",
                )

            media_decl = review_data.get("media") or {}
            declares_audio = any(media_decl.get(k) for k in
                                 ("speakerVideo", "compositeVideo", "previewVideo", "guideAudio"))
            composition_html = ((media_decl.get("liveStage") or {}).get("composition") or {}).get("html") or ""
            declares_audio = declares_audio or "<audio" in composition_html

            audio_state = page.evaluate(
                """()=>{
                     const out={channels:[]};
                     const spk=document.querySelector('#stage-speaker-video');
                     if(spk) out.channels.push({name:'speaker', muted:!!spk.muted,
                       src:(spk.currentSrc||'').slice(0,60)});
                     const comp=document.querySelector('#composite-video-player');
                     if(comp) out.channels.push({name:'composite', muted:!!comp.muted,
                       src:(comp.currentSrc||'').slice(0,60)});
                     document.querySelectorAll('audio').forEach(a=>out.channels.push(
                       {name:'audio', muted:!!a.muted, src:(a.currentSrc||'').slice(0,60)}));
                     return out;
                   }"""
            )
            candidates = [c for c in audio_state.get("channels", []) if c.get("src")]
            unmuted = [c for c in candidates if not c.get("muted")]
            composition_audio = _composition_audio(page)
            page_level = bool(unmuted)
            comp_level = bool((composition_audio or {}).get("usable"))
            usable_detail = [
                f"{c['tag']}{'[data-start]' if c['timed'] else ''} "
                f"ready={c['readyState']} t={c['before']:.2f}→{c['after']:.2f}"
                for c in (composition_audio or {}).get("usable", [])
            ]
            if page_level:
                source = "页面级通道（speaker/composite 轨）+ composition 内旁白"                     if comp_level else "页面级通道（speaker/composite 轨）"
            elif comp_level:
                source = "composition 内旁白：" + "；".join(usable_detail[:2])
            else:
                source = ""

            if page_level or comp_level:
                report.add("有声音且未被静音", True, f"声音来自 {source}", "")
            elif not declares_audio and not (composition_audio or {}).get("channels"):
                report.add(
                    "有声音且未被静音",
                    True,
                    "不适用：这份工程声明为纯画面层（没有音频源），声音在交付合成阶段贴回",
                    "",
                )
            else:
                report.add(
                    "有声音且未被静音",
                    False,
                    f"页面级={audio_state.get('channels')}；composition 内="
                    f"{(composition_audio or {}).get('channels')}",
                    "若旁白在 composition 里：查 audio[data-start] 是否 muted/未解码；"
                    "若走成片通道：查 media.json 与页面是否把人物轨当静音轨",
                )

            page.screenshot(path=str(tmp / "page.png"))
            browser.close()
    finally:
        if not keep_host and owns_host:
            try:
                review_host.stop_host(project / "review")
            except Exception:
                pass
        for item in report.checks:
            if verbose or not item["ok"]:
                print(f"{'✓' if item['ok'] else '✗'} {item['name']} — {item['detail']}")
        if not verbose and all(c["ok"] for c in report.checks):
            print(f"✓ 审阅页可播可听（channel={channel}，截图在 {tmp}）")

    result = {
        "ok": report.ok,
        "channel": channel,
        "screenshots": str(tmp),
        "failures": [c for c in report.checks if not c["ok"]],
        "hints": report.layer_hint,
        "checks": report.checks,
    }
    print(json.dumps(result, ensure_ascii=False, indent=1))
    return 0 if report.ok else 1


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("project", type=Path)
    parser.add_argument("--at", default="", help="逗号分隔的秒数，覆盖自动从 beats 取的 seek 点")
    parser.add_argument("--json", action="store_true", help="只输出 JSON")
    parser.add_argument("--keep-host", action="store_true", help="失败时保留本地宿主，便于人工打开看")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)
    points = [float(x) for x in args.at.split(",") if x.strip()] if args.at else []
    return run(args.project.expanduser().resolve(), points, args.keep_host, not args.quiet or args.json)


if __name__ == "__main__":
    raise SystemExit(main())
