# 制作阶段契约（九个动作）

> **用途**：把人做一支片子时"固定的那几段活"写成契约。模型调用的入口以这里为准；将来每个阶段变成一个脚本后，
> **契约的权威版本随脚本的 `--help` 走**，本文件降为索引（现在脚本还没建，本文件就是权威）。
> 判断标准：凡"有唯一正确做法、做错要返工"的，属于阶段脚本；凡"要在两个都对的做法里选一个"的，属于模型判断，不写进契约。

## 总表

| # | 动作 | 一句话 | 现在由哪些脚本承担 | 将来 |
|---|---|---|---|---|
| 1 | 接手 intake | 拿到上游的东西、核对版本、建项目记录 | `check-handoff-artifacts.mjs`、`check_script_hash.py` | `craft intake` |
| 2 | 剪口播 cut | 转写 → 取舍 → 剪点 → 逐字审阅 → 应用选择 | `transcribe*.py`、`refine_transcript`、`pack_transcripts`、`edl_from_keep`、`edl_edit`、`edl_preview_build`、`edl_review_surface`、`apply_selection`、`check_edl`、`audio_diag/fix` | **`stage_cut.py`（已落地）** |
| 3 | 时间与字幕 time | 时长预算与实测、字幕锁、唯一时间脊柱 | `duration_plan`、`render --preview`、`srt_export`、`timeline_derive`、`align-visual-plan`、`import_srt_timeline`、`recompose_plan` | `craft time` |
| 4 | 画面 film | 拆原页 → 写 composition → 活舞台可演 | `film.py`、`check_live_stage`、`live_stage` | `craft film` |
| 5 | 审阅 review | 出审阅页、运行时校验、收件与定点返修 | `review.py`、`check_review_playable`、`review_surface`、`review_inbox` | `craft review` |
| 6 | 交付 deliver | 闸门 → 出片 → 核验 → 包装 → 指纹 | `render_gate`、`deliver`、`verify_delivery`、`export_deliverables`、`export_video`、`state_fingerprint` | **`stage_deliver.py`（已落地）** |
| 7 | 检查 check | 单项检查（每项只证明一件事） | `check_*` 共 13 个、`probe_env`、`check_render_env`、`verify_av` | 不单独成阶段；各阶段内部按需调用 |
| 8 | 收尾 spec | 沉淀候选、规范校验 | `spec_lint` | `craft spec` |
| 9 | 杂务 admin | 环境、清理、诊断、多机位/调色等按需工具 | `clean_edit_dir`、`timeline_view`、`studio_notes`、`serve_review`、`measure_offset`、`mirror_edl`、`grade` | 不进阶段脚本，按需直接用 |

---

## 1. 接手 intake

- **做什么**：确认这一版用的是哪份稿、哪份画面、哪条声音；记下作者不可自行改变的决定；建 `edit/project.md`。
- **什么时候用**：所有新项目、恢复项目、收到返修。
- **输入**：上游内容包（脚本、内容契约、资产、制作说明）或现成素材。
- **产出**：`edit/project.md`、`production-plan.md` 的起点；缺口清单。
- **坏了怎么认**：脚本指纹对不上、画面快照不全、资产越界 → **停下来问作者**，不静默继续。
- **不做**：不改稿、不改内容、不判断风格。

## 2. 剪口播 cut

- **做什么**：把口播剪成确定的取舍——转写、逐字取词、删气口、改错字、EDL 表达、逐字审阅、应用选择。
- **什么时候用**：拿到原始视频/录音之后，**画面之前**。
- **输入**：原始媒体、作者的选择（逐字面上的删/留/改字）。
- **产出**：`transcripts/`、`takes_packed.md`、`edl.json`、`selections.json`（如用）。
- **坏了怎么认**：转写是整句粒度（页面只能整句删）就先补词级；EDL 停顿超预算；页面提交了但没应用。
- **不做**：不渲染正式底片（留到时间阶段）；不动画面。

## 3. 时间与字幕 time

- **做什么**：定"这一版到底多长"、把字幕锁住、派生出全片唯一的时间脊柱。
- **什么时候用**：剪点确认之后；画面开工之前。
- **输入**：`edl.json`、实测渲染记录、字幕正文与语义行、上游内容契约（外部 SRT 时）。
- **产出**：`segment_durations.json`、`caption*` 系列、`subtitles.srt`、`timeline/timeline.json`、`recompose.json`（recompose 项目）。
- **单一时间源**：画面时间轴是唯一定义，字幕与交付核验都跟它走；`srt_export --check` 在字幕末条与时间轴末段相差 >0.1s 时退非零。
- **坏了怎么认**：
  - 找不到与当前剪辑指纹一致的渲染记录 → 时间轴按名义/推定时长，**输出里标 `!`、交付报告 notes 里标"推定"**；
  - 字幕锁与 EDL 版本不一致 → 拒绝构建，不沿用旧锁。
- **不做**：不猜作者要留哪句（那是 cut）；不改画面内容。

## 4. 画面 film

- **做什么**：读懂原页（元素清单）→ 按清单重画一屏 → 排动画 → 让它在活舞台上能演。
- **什么时候用**：时间脊柱就绪之后。
- **输入**：参考页快照/原页、`timeline/timeline.json`、词级锚点、`recompose.json` 的画布与人物位。
- **产出**：`pages/<page>.md`（元素清单）、`composition/`、可演的活舞台地址。
- **坏了怎么认**：拆解没填满（`film.py verify` 退 1）；活舞台契约不成立（`check_live_stage` 退 1）；时间从手写数字而不是时间轴来。
- **不做**：不改口播与内容；不把画面像素当契约（默认遵循原构图，不适合动画时才重排并写理由）。

## 5. 审阅 review

- **做什么**：把工程变成人能看能听的页面；收作者的意见；只重建受影响的部分。
- **什么时候用**：任何画面/动效/密度改动之后；交人审之前。
- **输入**：`composition/`、`timeline.json`、`recompose/lines.json`、`feedback/`。
- **产出**：`review/index.html`、`review/review_data.json`、`review-submissions.json`、`feedback/*.jsonl`。
- **坏了怎么认**：页面能开但不能播、没声音、时长不对（`check_review_playable` 退非零）；提交了但收件 rejected。
- **不做**：不替代念稿审阅与静态页面审阅（那两个在上下游）。

## 6. 交付 deliver

- **做什么**：闸门 → 出片 → 逐项核验 → 按交付形态包装 → 记来源指纹。
- **什么时候用**：人审通过之后。
- **输入**：人审提交（覆盖当前快照）、画面层、人物轨、声音、字幕。
- **产出**：**成片**（以及按需的**人物成片**、**画面成片**）、`<片名>_核验报告.json`、来源指纹。
- **坏了怎么认**：没人审覆盖当前快照 → 拒绝出片；核验报告有红项 → 回修对应层；指纹与当前工程不一致 → 不能发送。
- **不做**：不替代渲染；不在没有人工提交时出片。

## 7. 检查 check（不单独成阶段）

- **做什么**：每个检查只证明一件事，互不蕴含；由各阶段按需调用。
- **坏了怎么认**：退出码非零，并指出"该修哪一层"。没有执行点的检查不算数。
- **不做**：不合并成一个"全部检查"的大动作（合并会丢掉"每个只证明一件事"）。

## 8. 收尾 spec

- **做什么**：从本轮返修与核验红项里挑重复项，给作者 ≤3 条候选；写入后校验规范上限。
- **什么时候用**：交付之后。
- **输入**：`feedback/*.jsonl`、项目偏好记录、核验报告。
- **产出**：候选处置记录（收了哪条/放哪/替代了谁，或明确没收）；`spec_lint` 退 0。
- **坏了怎么认**：条目超上限、执行点悬空、规范里有引文 → `spec_lint` 退非零。
- **不做**：不把一次性反馈写成永久规则；不静默新增。

## 9. 杂务 admin

- **做什么**：环境探测、清理、诊断、多机位对齐、调色等按需动作。
- **什么时候用**：只在需要时；不是每支片子的必经之路。
- **坏了怎么认**：每个脚本各自报告；不通过就停。
- **不做**：不混进固定流程，不替作者做决定。

---

# 合并地图：哪些脚本在做同一件事

> 原则：**先加一处新的、让新代码只调它；旧副本逐个迁；一次只迁一处；迁完跑同一支真实项目对照。**
> 任何一次合并都不改行为；要改行为就单独另做一步。

| 顺序 | 重复的是什么 | 现在的副本 | 先做什么 | 红线 |
|---|---|---|---|---|
| M1/M2 | 字幕/时间码解析与换算 | 5 份解析 + 2 份起止秒换算 | **已完成**：`helpers/_timecode.py` 是唯一实现；`check_edl` / `verify_delivery` 用它的宽松读取，保留旧的跳过语义；5 个老项目 602 条字幕逐条一致 | 宽松读取只服务旧调用方，新代码用严格读取 |
| M2 | 设计/时间换算（同 M1 的时间轴侧） | `check_edl` / `verify_delivery` / `srt_export` / `build_review` / `recompose_plan` / `align-visual-plan` | 并入 M1 的适配器 | 与 M1 同一步，不拆两次 |
| M3 | 找项目目录、编辑目录 | 5 套推断（`render_gate` / `live_stage` / `studio_notes` / `export_video` / `build_review`） | **已完成**：`helpers/_paths.py` 的 `resolve()` 是唯一实现，五处全部迁入；`live_stage` / `studio_notes` 仍额外要求项目下有 `composition/` | 已用 4 条路径用例 + 49 条相关用例验证；错目录现在由各调用方按原语义报错 |
| M4 | ffprobe 探测 | 26 调用点；`_probe` 只覆盖少数 | **第一步已完成**：`_probe.probe_media` 提供“格式+全部流”，`verify_delivery` 已迁并用真实成片对照一致；其余调用点按语义差异留在原处（下次按需迁） | 坏文件的行为要统一，不能有的抛有的返回 0 |
| M5 | 交付判据 | `deliver` 与 `verify_delivery` 两套判据 | **A 已完成**：`deliver` 末尾调用 `verify_delivery` 并把结论记进报告；严格度=**记录+提示**，硬门在 `stage_deliver.py verify`。判据仍分两层：`deliver` 验合成事实，`verify_delivery` 验\“这一版能不能发\”。无声画面轨用 `--no-audio` 声明，不误报 | 不把审美决定写进脚本；不合并两层判据 |
| M6 | 审阅构建链 | `check_live_stage` / `live_stage` / `build_review` / `review_surface` / `check_review_playable` | **已完成（入口层）**：文档与阶段表只暴露 `review.py`；其余五件标注为内部步骤，只在调试或持久舞台时单跑。代码未合并（它们本就是 review.py 的实现细节） | 不合并两个审阅面（念稿 vs 画面） |
| M7 | 遗留入口 | `check_parity` / `import_svg_page` / `generate-composition` 三个顶层 shim | **第一步已完成**：`build_review` 改为按需惰性 import（live 路径不再加载遗留适配器）；`generate-composition` 的 CLI 改为明确报"已归档"并退 2。三个 shim 文件保留为**兼容别名**（测试与旧项目仍在用），搬走要改 4 个测试文件，暂不做 | 迁移前先确认已无活代码在模块导入期引用遗留 |
| M8 | 实测时长 | 已在本轮收敛（`_edl.measured_total_ms` 唯一入口） | — | 已完成；后续新增读取方只准调它 |

**每一步的验收**：`Ran N tests` 不低于前一步；同一支真实项目跑前跑后结果一致（或差异有解释）；文档同一步更新；不发布。

---

# 已落地的阶段脚本

壳只串既有命令、统一退出码与"下一步"，不重新实现任何制作逻辑；旧命令继续可用。

| 阶段 | 命令 | 已实现动作 |
|---|---|---|
| 剪口播 | `python3 helpers/stage_cut.py <动作> --project <项目>` | `status` 看进度与下一步 · `prepare` 转写+打包+剪点检查 · `review` 出逐字审阅页 · `apply` 应用作者选择 |
| 审阅 | `python3 helpers/review.py <项目>`（深模块，唯一公共入口；内部步骤见 tools.md） | 出审阅页 + 运行时判据（能播 / 有画面 / 有声音） | **前置 `recompose.json`**（旧十步 page 审阅页已退休；先 `recompose_plan.py init`）。**默认必须是工程态**：有 composition 时活舞台优先；`build_review` 在没活舞台时退 2，只允许 `--allow-static` 显式降级 |
| 交付 | `python3 helpers/stage_deliver.py run --render --project <项目>`（默认不渲染；`--render` 是显式交付动作） | `status` 看进度与下一步 · `run` 闸门+出片 · `verify` 交付核验 · `export` 包装 · `fingerprint` capture/verify |

退出码统一：`0` 完成 · `1` 某条命令失败（含闸门拒绝）· `2` 前置条件不满足（还没到这一步）。
加 `--json` 得到机器可读结果，包含 `steps`（每条命令的退出码）与 `next`（下一步该跑什么）。
