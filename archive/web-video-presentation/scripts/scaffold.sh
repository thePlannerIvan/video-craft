#!/usr/bin/env bash
# Scaffold a web-video-presentation v2 project (HyperFrames composition).
# Run after Phase 1-2 (timeline/timeline.json exists); or run early to
# create input/ + composition/ and generate the skeleton later.
set -euo pipefail

SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
THEMES_DIR="$SKILL_DIR/themes"
DEFAULT_THEME="midnight-press"

list_themes() {
  echo "可用主题（来自 ${THEMES_DIR}）:"
  echo
  for dir in "$THEMES_DIR"/*/; do
    [[ -d "$dir" ]] || continue
    local meta="$dir/theme.json"
    [[ -f "$meta" ]] || continue
    local id name desc
    id=$(grep -E '"id"' "$meta" | head -n1 | sed -E 's/.*"id":[[:space:]]*"([^"]+)".*/\1/')
    name=$(grep -E '"nameZh"' "$meta" | head -n1 | sed -E 's/.*"nameZh":[[:space:]]*"([^"]+)".*/\1/')
    desc=$(grep -E '"descriptionZh"' "$meta" | head -n1 | sed -E 's/.*"descriptionZh":[[:space:]]*"([^"]+)".*/\1/')
    printf "  • %-18s %s\n      %s\n\n" "$id" "$name" "$desc"
  done
  echo "用 --theme=<id> 选定一个。默认：${DEFAULT_THEME}。"
}

TARGET=""
THEME="$DEFAULT_THEME"
LAYOUT="landscape"
for arg in "$@"; do
  case "$arg" in
    --list-themes)
      list_themes
      exit 0
      ;;
    --theme=*)
      THEME="${arg#--theme=}"
      ;;
    --portrait)
      LAYOUT="portrait"
      ;;
    --overlay)
      LAYOUT="overlay"
      ;;
    --*)
      echo "✗ 未知参数: $arg" >&2
      exit 1
      ;;
    *)
      if [[ -z "$TARGET" ]]; then TARGET="$arg"; fi
      ;;
  esac
done

TARGET="${TARGET:-presentation}"
THEME_DIR="$THEMES_DIR/$THEME"
THEME_TOKENS="$THEME_DIR/tokens.css"

if [[ ! -d "$THEME_DIR" || ! -f "$THEME_TOKENS" ]]; then
  echo "✗ 找不到主题 '${THEME}'。可用主题：" >&2
  for dir in "$THEMES_DIR"/*/; do
    [[ -d "$dir" ]] || continue
    echo "    • $(basename "$dir")" >&2
  done
  exit 1
fi

if [[ -e "$TARGET" && -n "$(ls -A "$TARGET" 2>/dev/null || true)" ]]; then
  # Refuse only when the target is a non-empty dir that has no v2 markers
  # (composition/ input/ timeline/ .theme) — i.e. it is some other project.
  if [[ ! -d "$TARGET/composition" && ! -d "$TARGET/input" && ! -d "$TARGET/timeline" && ! -f "$TARGET/.theme" ]]; then
    echo "✗ $TARGET 已存在且非空，且看起来不是 v2 项目（无 composition/ input/ timeline/ .theme）" >&2
    exit 1
  fi
fi

mkdir -p "$TARGET/input" "$TARGET/timeline"

echo "◆ 初始化 HyperFrames 项目（composition/）…"
npx --yes hyperframes init "$TARGET/composition" --example blank --non-interactive --skip-skills

echo "$THEME" > "$TARGET/.theme"
echo "$LAYOUT" > "$TARGET/.layout"

if [[ -f "$TARGET/timeline/timeline.json" ]]; then
  echo "◆ 生成组成品骨架…"
  python3 "$SKILL_DIR/scripts/generate-composition.py" "$TARGET" --theme="$THEME" --layout="$LAYOUT"
else
  echo "◆ timeline/timeline.json 还不存在——Phase 1-2 完成后运行："
  echo "    python3 $SKILL_DIR/scripts/generate-composition.py $TARGET --theme=$THEME --layout=$LAYOUT"
fi

echo
echo "完成。目录："
echo "  $TARGET/input/      放 audio.mp3 / subtitles.srt / assets/（或运行 video-use-handoff.py）"
echo "  $TARGET/timeline/   SRT 解析产物"
echo "  $TARGET/composition/  HyperFrames 组成品（cd 进去 npm run check / npm run render）"
echo "  .layout = $LAYOUT（landscape 1920x1080 / portrait 1080x1920 / overlay 1080x1920 透明底）"
