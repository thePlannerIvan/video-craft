#!/usr/bin/env python3
"""Wrap static visual-reference SVG slides into a Remotion 4 scene with gentle motion.

Replaces the retired HyperFrames keyframe importer for new projects while
preserving existing projects untouched. Copies SVG + local image assets under
`remotion/public/assets/pages/` and emits a deterministic Remotion TypeScript
component (`remotion/src/scenes/StaticSvgReference.tsx`).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path

from _geometry import resolve_project_frame  # noqa: E402

SVG_IMAGE_HREF_RE = re.compile(r'(<image\b[^>]*?(?:xlink:)?href\s*=\s*["\'])([^"\']+)(["\'])', re.I)


def _rewrite_and_copy_svg_assets(svg_path: Path, public_assets_dir: Path, page_key: str) -> str:
    raw = svg_path.read_text(encoding="utf-8")
    copied: dict[str, str] = {}
    used_dest_names: dict[str, Path] = {}
    asset_sub = public_assets_dir / page_key

    def _replace(match: re.Match) -> str:
        prefix, href, suffix = match.group(1), match.group(2), match.group(3)
        if href.startswith(("data:", "blob:", "#", "http://", "https://")):
            return match.group(0)
        if href not in copied:
            src = (svg_path.parent / href).resolve()
            if src.is_file():
                asset_sub.mkdir(parents=True, exist_ok=True)
                dest_name = src.name
                if dest_name in used_dest_names and used_dest_names[dest_name] != src:
                    short_h = hashlib.sha256(str(src).encode("utf-8")).hexdigest()[:6]
                    dest_name = f"{src.stem}-{short_h}{src.suffix}"
                    counter = 1
                    while dest_name in used_dest_names and used_dest_names[dest_name] != src:
                        dest_name = f"{src.stem}-{short_h}-{counter}{src.suffix}"
                        counter += 1
                used_dest_names[dest_name] = src
                dest = asset_sub / dest_name
                shutil.copy2(src, dest)
                copied[href] = f"{page_key}/{dest_name}"
            else:
                copied[href] = href
        return f"{prefix}{copied[href]}{suffix}"

    return SVG_IMAGE_HREF_RE.sub(_replace, raw)


def import_svg_pages_to_remotion(
    project: Path,
    sources: list[Path],
    *,
    remotion_dir: Path | None = None,
    fps: int | None = None,
    seconds_per_slide: float = 4.0,
) -> dict:
    """Import one or more static SVG pages into `<project>/remotion/` as a Remotion scene."""
    project = project.expanduser().resolve()
    rem_dir = (remotion_dir or (project / "remotion")).expanduser().resolve()
    geo = resolve_project_frame(project)
    use_fps = int(fps or geo["fps"] or 30)
    w, h = int(geo["width"]), int(geo["height"])

    svg_files: list[Path] = []
    for src in sources:
        p = Path(src).expanduser().resolve()
        if p.is_dir():
            svg_files.extend(sorted(p.glob("*.svg")))
        elif p.is_file() and p.suffix.lower() == ".svg":
            svg_files.append(p)
    if not svg_files:
        raise ValueError("No .svg files found to import into Remotion")

    public_pages = rem_dir / "public" / "assets" / "pages"
    public_pages.mkdir(parents=True, exist_ok=True)
    src_dir = rem_dir / "src"
    scenes_dir = src_dir / "scenes"
    scenes_dir.mkdir(parents=True, exist_ok=True)

    frames_per_slide = max(1, int(round(seconds_per_slide * use_fps)))
    slides: list[dict] = []
    used_keys: set[str] = set()
    cursor = 0
    for idx, svg_path in enumerate(svg_files, 1):
        # Validate XML parseability early
        try:
            ET.fromstring(svg_path.read_text(encoding="utf-8"))
        except ET.ParseError as exc:
            raise ValueError(f"Invalid SVG XML in {svg_path}: {exc}") from exc
        base_key = re.sub(r"[^A-Za-z0-9._-]+", "-", svg_path.stem).strip("-") or f"slide-{idx:02d}"
        key = base_key
        if key in used_keys:
            short_h = hashlib.sha256(str(svg_path).encode("utf-8")).hexdigest()[:6]
            key = f"{base_key}-{short_h}"
            if key in used_keys:
                key = f"{key}-{idx}"
        used_keys.add(key)
        rewritten = _rewrite_and_copy_svg_assets(svg_path, public_pages, key)
        dest_svg = public_pages / f"{key}.svg"
        dest_svg.write_text(rewritten, encoding="utf-8")
        slides.append({
            "key": key,
            "asset": f"assets/pages/{key}.svg",
            "from": cursor,
            "durationInFrames": frames_per_slide,
        })
        cursor += frames_per_slide

    total_frames = max(1, cursor)
    scene_tsx = scenes_dir / "StaticSvgReference.tsx"
    scene_tsx.write_text(
        """import React from "react";
import {
  AbsoluteFill,
  Img,
  Sequence,
  interpolate,
  spring,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";

export interface StaticSlideSpec {
  key: string;
  asset: string;
  from: number;
  durationInFrames: number;
}

export const STATIC_SLIDES: StaticSlideSpec[] = __SLIDES_JSON__;

const SlideLayer: React.FC<{ asset: string; durationInFrames: number }> = ({
  asset,
  durationInFrames,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const enter = spring({ frame, fps, config: { damping: 18, stiffness: 120, mass: 0.8 } });
  const push = interpolate(frame, [0, Math.max(1, durationInFrames)], [1.0, 1.035], {
    extrapolateRight: "clamp",
  });
  const fadeOut = interpolate(
    frame,
    [Math.max(0, durationInFrames - 8), durationInFrames],
    [1, 0],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" }
  );

  return (
    <AbsoluteFill
      style={{
        alignItems: "center",
        justifyContent: "center",
        backgroundColor: "#0d0f14",
        opacity: Math.min(enter, fadeOut),
      }}
    >
      <Img
        src={staticFile(asset)}
        style={{
          width: "100%",
          height: "100%",
          objectFit: "contain",
          transform: `scale(${0.96 + 0.04 * enter}) scale(${push})`,
        }}
      />
    </AbsoluteFill>
  );
};

export const StaticSvgReference: React.FC = () => {
  return (
    <AbsoluteFill style={{ backgroundColor: "#0d0f14" }}>
      {STATIC_SLIDES.map((s) => (
        <Sequence key={s.key} from={s.from} durationInFrames={s.durationInFrames}>
          <SlideLayer asset={s.asset} durationInFrames={s.durationInFrames} />
        </Sequence>
      ))}
    </AbsoluteFill>
  );
};
""".replace("__SLIDES_JSON__", json.dumps(slides, ensure_ascii=False, indent=2)),
        encoding="utf-8",
    )

    root_tsx = src_dir / "Root.tsx"
    if not root_tsx.is_file():
        root_tsx.write_text(
            f"""import React from "react";
import {{ Composition }} from "remotion";
import {{ StaticSvgReference }} from "./scenes/StaticSvgReference";

export const RemotionRoot: React.FC = () => (
  <Composition
    id="StaticReferenceFilm"
    component={{StaticSvgReference}}
    durationInFrames={{{total_frames}}}
    fps={{{use_fps}}}
    width={{{w}}}
    height={{{h}}}
  />
);
""",
            encoding="utf-8",
        )

    index_ts = src_dir / "index.ts"
    if not index_ts.is_file():
        index_ts.write_text(
            'import { registerRoot } from "remotion";\n'
            'import { RemotionRoot } from "./Root";\n\n'
            "registerRoot(RemotionRoot);\n",
            encoding="utf-8",
        )

    tsconfig = rem_dir / "tsconfig.json"
    if not tsconfig.is_file():
        tsconfig.write_text(
            json.dumps(
                {
                    "compilerOptions": {
                        "target": "ES2022",
                        "module": "ES2022",
                        "moduleResolution": "bundler",
                        "jsx": "react-jsx",
                        "strict": True,
                        "esModuleInterop": True,
                        "skipLibCheck": True,
                        "resolveJsonModule": True,
                        "noEmit": True,
                    },
                    "include": ["src"],
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

    return {
        "ok": True,
        "remotionDir": os.path.relpath(rem_dir, project).replace(os.sep, "/"),
        "slides": slides,
        "fps": use_fps,
        "width": w,
        "height": h,
        "totalFrames": total_frames,
        "sceneFile": os.path.relpath(scene_tsx, project).replace(os.sep, "/"),
    }
