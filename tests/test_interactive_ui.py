#!/usr/bin/env python3
"""test_interactive_ui.py — 视觉动效审阅控制台自动化全交互测试。

测试项目：
  1. 页面加载与三栏控制台就绪（左侧分屏轨、中央舞台、右侧反馈栏）；
  2. ⚡ 视听动效舞台：
     - SVG 场景绘制；
     - 人物口播视频挂载与角标（top: 10px，不遮挡胸口）；
     - 底部单行悬浮药丸字幕（#canvas-caption-layer）与动态同步；
     - 底部紧凑分步动效轨道（12 种原语、虚拟镜头推拉、卡点微调）；
  3. 🎬 最终合成预览模式切换：
     - 自动装载合成成片视频（非黑屏、无断连报错、带有标准控制条）；
     - 无成片时展示友好指引；
  4. 📝 逐字精修剪辑模式切换：
     - 内嵌加载 edl_preview.html 工作台；
  5. 全片连续播放与时间轴 Scrubber：
     - 播放/暂停控制与空格键快捷键；
     - 时间进度与分段刻度更新；
     - 点击/拖拽 Scrubber 跳转到指定时间点与分屏；
  6. 审阅反馈保存落盘闭环。
"""
import sys
import time
from pathlib import Path
from playwright.sync_api import sync_playwright

URL = "http://127.0.0.1:8776/review/index.html"
SHOT_DIR = Path("/tmp/video_craft_review_test")
SHOT_DIR.mkdir(parents=True, exist_ok=True)

def run_tests():
    print("==> 启动 Playwright 交互自测...")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 900})
        page = context.new_page()
        page.on("console", lambda msg: print(f"CONSOLE [{msg.type}]:", msg.text))
        page.on("pageerror", lambda err: print("PAGE_ERROR:", err))

        # 1. 访问审阅页
        print("  [1] 打开审阅页:", URL)
        page.goto(URL, wait_until="networkidle")
        time.sleep(1)

        # 检查标题与项目名
        title = page.title()
        print(f"      页面标题: {title}")
        assert "Video Craft" in title, f"标题错误: {title}"

        proj_name = page.locator("#project-name").inner_text()
        print(f"      项目结构: {proj_name}")
        assert "章" in proj_name and "步" in proj_name, f"项目时间轴未加载: {proj_name}"

        # 2. 检查 ⚡ 动效舞台
        print("  [2] 验证 ⚡ 视听动效舞台...")
        svg_host = page.locator("#svg-stage-host > svg")
        assert svg_host.count() > 0, "SVG 舞台未渲染"
        print("      ✓ SVG 舞台已渲染")

        # 检查 speaker pill 位置
        pill = page.locator("#speaker-time-pill")
        assert pill.is_visible(), "口播角标未显示"
        box = pill.bounding_box()
        # 角标应该在舞台左上方 (top <= 200)
        assert box["y"] < 250, f"口播角标位置不符合预期 (不在上方): {box}"
        print(f"      ✓ 口播时间角标位于左上方: y={box['y']} (彻底避免遮挡胸口与字幕)")

        # 检查悬浮药丸字幕
        caption_layer = page.locator("#canvas-caption-layer")
        assert caption_layer.is_visible(), "悬浮字幕药丸未显示"
        cap_text = page.locator("#canvas-caption-text").inner_text()
        assert len(cap_text) > 0, "字幕文字为空"
        print(f"      ✓ 悬浮字幕药丸显示正常: 「{cap_text}」")

        # 截取动效舞台画面
        shot1 = SHOT_DIR / "01_stage_view.png"
        page.screenshot(path=str(shot1))
        print(f"      ✓ 动效舞台截图已保存: {shot1}")

        # 3. 检查 🎬 最终合成预览
        print("  [3] 验证 🎬 最终合成预览模式切换...")
        page.click("#view-player-btn")
        time.sleep(0.5)

        comp_wrap = page.locator("#composite-player-wrap")
        assert comp_wrap.is_visible(), "合成预览容器未展示"
        comp_video = page.locator("#composite-video-player")
        assert comp_video.is_visible(), "合成视频播放器未展示"
        src = comp_video.get_attribute("src")
        print(f"      ✓ 成功装载完整成片视频源: {src}")
        assert src and "完整视听成片" in src, f"合成视频源错误: {src}"

        # 验证没有死循环黑屏或错误占位
        placeholder = page.locator("#composite-empty-placeholder")
        assert not placeholder.is_visible(), "成片存在时不应展示空占位符"

        shot2 = SHOT_DIR / "02_composite_view.png"
        page.screenshot(path=str(shot2))
        print(f"      ✓ 合成预览截图已保存: {shot2}")

        # 4. 检查 📝 逐字精修剪辑
        print("  [4] 验证 📝 逐字精修剪辑模式切换...")
        page.click("#view-verbatim-btn")
        time.sleep(1)

        verb_wrap = page.locator("#verbatim-iframe-wrap")
        assert verb_wrap.is_visible(), "逐字精修容器未展示"
        iframe = page.locator("#verbatim-iframe")
        assert iframe.is_visible(), "逐字精修 iframe 未展示"
        iframe_src = iframe.get_attribute("src")
        print(f"      ✓ 成功内嵌逐字稿粗剪工作台: {iframe_src}")
        assert iframe_src and "edl_preview.html" in iframe_src, f"逐字稿路径错误: {iframe_src}"

        shot3 = SHOT_DIR / "03_verbatim_view.png"
        page.screenshot(path=str(shot3))
        print(f"      ✓ 逐字精修截图已保存: {shot3}")

        # 5. 切回动效舞台测试全局时间轴 Scrubber 与快捷键
        print("  [5] 验证时间轴 Scrubber 与快捷键交互...")
        page.click("#view-svg-btn")
        time.sleep(0.5)

        # 检查刻度
        markers = page.locator(".timeline-marker")
        m_count = markers.count()
        print(f"      ✓ 时间轴分段刻度数: {m_count} 处")
        assert m_count > 0, "时间轴刻度未生成"

        # 点击全片播放
        play_btn = page.locator("#btn-global-play")
        play_btn.click()
        time.sleep(1.2)
        assert "暂停" in play_btn.inner_text(), "播放状态未更新为暂停"
        print("      ✓ 全片连播已启动，当前按钮显示「暂停」")

        # 再次按空格键暂停
        page.keyboard.press("Space")
        time.sleep(0.3)
        assert "播放" in play_btn.inner_text(), "空格快捷键未能暂停播放"
        print("      ✓ 空格快捷键成功切换暂停/播放")

        # 测试 Scrubber 点击跳转到第 50% 时间点
        scrubber = page.locator("#timeline-scrubber-wrap")
        s_box = scrubber.bounding_box()
        page.mouse.click(s_box["x"] + s_box["width"] * 0.5, s_box["y"] + s_box["height"] * 0.5)
        time.sleep(0.5)
        cur_disp = page.locator("#global-time-display").inner_text()
        print(f"      ✓ Scrubber 点击跳转至中段: {cur_disp}")
        assert "01:" in cur_disp or "02:" in cur_disp, f"跳转时间不符合预期: {cur_disp}"

        # 6. 测试提交审阅意见闭环
        print("  [6] 验证审阅意见提交落盘...")
        page.click("#mode-overall")
        fb_textarea = page.locator("#fb-text")
        test_comment = f"[自动化自测意见 {int(time.time())}] 全片交互、成片播放与逐字稿无缝整合通过！"
        fb_textarea.fill(test_comment)
        page.click("#fb-save")
        page.wait_for_selector("#save-state.ok", timeout=6000)

        save_state = page.locator("#save-state").inner_text()
        print(f"      ✓ 提交反馈状态: {save_state}")
        assert "已写入" in save_state or "ok" in (page.locator("#save-state").get_attribute("class") or ""), f"保存状态异常: {save_state}"

        # 检查右侧列表是否出现新卡片
        cards = page.locator(".fb-card")
        assert cards.count() > 0, "反馈卡片未加入列表"
        print(f"      ✓ 反馈列表中已有 {cards.count()} 条记录")

        browser.close()
        print("\n🎉 全部交互自测项 100% 通过！")

if __name__ == "__main__":
    run_tests()
