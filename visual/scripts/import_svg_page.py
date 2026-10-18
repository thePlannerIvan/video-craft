#!/usr/bin/env python3
"""Import a static picture page (SVG) into the composition, verbatim.

The video route's static screen is an SVG page and it stays SVG because the
animation layer comes later. Handing over a page therefore hands over a **live
structure whose elements can be named**, not a pile of files.

A page arrives one of two ways, and both are supported:

- the picture package `input/scenes/<page_key>.svg` (one file per screen), or
- the picture project's `_internal/02_svg_source/<page_key>.svg`.

`--pages` takes any of these and resolves them to the same pair of paths
(`resolve_pages`): the picture project's root, that project's
`_internal/02_svg_source` directory, a package root carrying `input/scenes/`, that
`input/scenes/` directory itself, or a plain directory of `*.svg`. **Point it at
the picture project's root when you can** — the pages carry hrefs relative to
their own project, and the root is what those hrefs are written against.

Four rules, each checked:

1. **The page is copied byte for byte.** `_inline_image_hrefs` touches only the
   `href` / `xlink:href` values of `<image>` tags; `import_page` proves it by
   rewriting them back in memory and comparing against the source bytes.
2. **Elements are addressed by `id`.** `audit_page` counts the ids a page
   exposes, and `audit_pages` reports ids that two pages share — inline pages
   land in one DOM, where a repeated id makes `#name` ambiguous and the global
   selector silently picks the first. DOM order is not a substitute either: one
   extra `<text>` in a re-render re-binds `slice(-10)` to a different element.
3. **Page coordinates are video pixels.** Every picture page is
   `viewBox="0 0 1920 1080"`, so animation needs no coordinate transform.
4. **Assets live inside the composition.** Pages reference images as
   `../00_project/...`, which HyperFrames rejects
   (`invalid_parent_traversal_in_asset_path`). The importer copies each asset
   under `composition/assets/pages/<page_key>/` and rewrites the prefix; the
   inlined markup carries the rewritten, root-relative path. The page keeps its
   own href for its PPT exit.

**What `--prove` proves, and what it does not.** `--prove` shows that the round
trip through the importer did not alter the page — the file that came out is the
file that went in. It says nothing about whether the composition renders: the
inlined `<img>` paths, the theme, the timing and the DOM are
`generate-composition.py`'s and HyperFrames' business. Run
`cd composition && npx hyperframes check` for that. Both commands are right;
together they are the whole picture.

Usage:
    python3 visual/scripts/import_svg_page.py <project> --pages <picture-root> --audit
    python3 visual/scripts/import_svg_page.py <project> --page beat-01 --prove
    python3 visual/scripts/import_svg_page.py <project> --emit
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from snapshot_input import load_snapshot, resolve_snapshot, invalidation, asset_records, checked_file

PAGE_ROOT = "_internal/02_svg_source"
DESIGN_DIRECTION = "_internal/01_content/design_direction.md"
PACKAGE_SCENES = "input/scenes"

ROOT_SVG_RE = re.compile(r"<svg\b[^>]*>", re.IGNORECASE | re.DOTALL)
IMAGE_TAG_RE = re.compile(r"<image\b[^>]*>", re.IGNORECASE | re.DOTALL)
HREF_RE = re.compile(r"""((?:xlink:)?href\s*=\s*)(["'])(.*?)\2""", re.IGNORECASE | re.DOTALL)
# `(?<![-\w])` keeps `data-layout-id` and `screen_id` out: those name the page,
# not an element, and counting them would report an addressable page that is not.
ID_RE = re.compile(r"""(?<![-\w])id\s*=\s*(["'])(.*?)\1""", re.IGNORECASE | re.DOTALL)
CLASS_RE = re.compile(r"""(?<![-\w])class\s*=\s*(["'])(.*?)\1""", re.IGNORECASE | re.DOTALL)
VIEWBOX_RE = re.compile(r"""\bviewBox\s*=\s*(["'])(.*?)\1""", re.IGNORECASE | re.DOTALL)
JSON_BLOCK_RE = re.compile(r"```json\s*\n(.*?)```", re.DOTALL | re.IGNORECASE)

EXTERNAL_PREFIXES = ("data:", "http:", "https:", "#", "mailto:")


class PageImportError(Exception):
    """The page cannot be placed inside the composition without changing it."""


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _inline_image_hrefs(svg: str, mapping: dict) -> tuple[str, list[dict]]:
    """Rewrite image href values. Nothing outside those values is touched."""
    substitutions: list[dict] = []

    def rewrite_tag(tag_match: re.Match) -> str:
        def rewrite_href(href_match: re.Match) -> str:
            before = href_match.group(3)
            after = mapping.get(before, before)
            if after != before:
                substitutions.append({"before": before, "after": after})
            return f"{href_match.group(1)}{href_match.group(2)}{after}{href_match.group(2)}"

        return HREF_RE.sub(rewrite_href, tag_match.group(0))

    return IMAGE_TAG_RE.sub(rewrite_tag, svg), substitutions


def image_hrefs(svg: str) -> list[str]:
    """Every href value carried by an `<image>` tag, in document order."""
    found: list[str] = []
    for tag in IMAGE_TAG_RE.finditer(svg):
        found.extend(m.group(3) for m in HREF_RE.finditer(tag.group(0)))
    return found


def audit_pages(results: list) -> dict:
    """Ids shared by more than one page, reported across the whole set.

    Inline pages land in ONE DOM. A repeated id makes `#caption-1` ambiguous —
    the global selector silently resolves to the first match — so "animate the
    element with this id" highlights the wrong screen's element and nothing
    fails. The fix belongs on the picture side (prefix ids with the page key so
    they are unique across the film); rewriting ids here would break the byte
    for byte promise, so this only reports.
    """
    owners: dict = {}
    for result in results:
        for element_id in result.audit.get("element_ids", []):
            owners.setdefault(element_id, []).append(result.page_key)
    collisions = {name: pages for name, pages in owners.items() if len(set(pages)) > 1}
    return {
        "collisions": {name: sorted(set(pages)) for name, pages in sorted(collisions.items())},
        "unique_ids": sorted(name for name, pages in owners.items() if len(set(pages)) == 1),
        "clean": not collisions,
    }


def audit_page(svg: str) -> dict:
    """What the animation layer can name, and what the page already gave up.

    `addressable` is the one that matters: an id on the root `<svg>` names the
    page, not an element. A page with no id below the root has nothing to
    address, and that is the failure this whole seam exists to surface.
    """
    root = ROOT_SVG_RE.search(svg)
    root_tag = root.group(0) if root else ""
    body = svg[root.end():] if root else svg
    body_ids = [m.group(2) for m in ID_RE.finditer(body)]
    viewbox = VIEWBOX_RE.search(root_tag)
    return {
        "viewBox": viewbox.group(2) if viewbox else None,
        "root_ids": [m.group(2) for m in ID_RE.finditer(root_tag)],
        "element_ids": body_ids,
        "addressable": bool(body_ids),
        "elements_with_class": len(CLASS_RE.findall(body)),
        "text_nodes": len(re.findall(r"<text\b", svg, re.IGNORECASE)),
        "path_nodes": len(re.findall(r"<path\b", svg, re.IGNORECASE)),
        "flattened_nodes": len(re.findall(r"<clipPath\b|<mask\b|\btransform\s*=", svg, re.IGNORECASE)),
    }


@dataclass
class ImportResult:
    page_key: str
    source: Path
    source_sha256: str
    inlined_sha256: str
    restored_sha256: str
    inlined: str = ""
    substitutions: list[dict] = field(default_factory=list)
    audit: dict = field(default_factory=dict)
    problems: list[str] = field(default_factory=list)

    @property
    def verbatim(self) -> bool:
        """True when rewriting the hrefs back reproduces the source exactly."""
        return self.source_sha256 == self.restored_sha256

    def as_manifest(self) -> dict:
        merged: dict = {}
        for sub in self.substitutions:
            key = (sub["before"], sub["after"])
            merged.setdefault(key, {"before": sub["before"], "after": sub["after"],
                                    "occurrences": 0})["occurrences"] += 1
        return {
            "pageKey": self.page_key,
            "source": str(self.source),
            "sourceSha256": self.source_sha256,
            "inlinedSha256": self.inlined_sha256,
            "restoredSha256": self.restored_sha256,
            "verbatim": self.verbatim,
            "substitutions": list(merged.values()),
            "audit": self.audit,
            "problems": self.problems,
        }


def plan_href_targets(svg: str, *, source_path: Path, asset_root: Path,
                      page_key: str) -> tuple[dict, dict, list[str]]:
    """href -> composition-relative path, plus the assets to copy and any gaps."""
    mapping: dict[str, str] = {}
    copies: dict[str, Path] = {}
    problems: list[str] = []
    taken: dict[str, str] = {}
    page_dir = source_path.parent

    for href in image_hrefs(svg):
        if href.startswith(EXTERNAL_PREFIXES) or href in mapping:
            continue
        resolved = (page_dir / href).resolve()
        try:
            rel = resolved.relative_to(asset_root).as_posix()
        except ValueError:
            raise PageImportError(
                f"{page_key}: image href {href!r} resolves to {resolved}, outside the "
                f"picture package ({asset_root}).\n"
                f"  Point --pages at the picture project's ROOT — not at its "
                f"{PAGE_ROOT} directory — and the page's own project-relative hrefs "
                f"resolve. The page keeps its href; adapting it is the importer's job."
            ) from None
        if not resolved.is_file():
            problems.append(f"{page_key}: image href points at a missing file: {href}")
        # Flatten to the file name: the package's own tree stays where it is. A
        # name already taken by a different source path gets a short digest
        # rather than silently overwriting the first one.
        name = Path(rel).name
        target = f"assets/pages/{page_key}/{name}"
        if taken.get(target, rel) != rel:
            digest = hashlib.sha256(rel.encode("utf-8")).hexdigest()[:8]
            target = f"assets/pages/{page_key}/{Path(rel).stem}-{digest}{Path(rel).suffix}"
        taken[target] = rel
        mapping[href] = target
        copies[target] = resolved
    return mapping, copies, problems


def import_page(page_key: str, *, page_dir: Path, asset_root: Path, project: Path,
                copy_assets: bool = True) -> ImportResult:
    """Inline one page for the composition. Assets land inside the composition.

    `page_dir` holds the SVGs; `asset_root` is the boundary an image href may
    not leave (the picture project, or the package the scenes arrived in).
    """
    page_dir = Path(page_dir).resolve()
    asset_root = Path(asset_root).resolve()
    project = Path(project).resolve()
    source = page_dir / f"{page_key}.svg"
    snapshot = resolve_snapshot(project, page_dir)
    if snapshot:
        if page_dir != snapshot.root / 'scenes' or asset_root != snapshot.root:
            raise PageImportError('Snapshot import must use its pinned scenes and asset root')
        if page_key not in snapshot.pages:
            raise PageImportError(f'Unknown snapshot page: {page_key}')
    if not source.is_file():
        raise FileNotFoundError(f"no SVG page {source}")

    source_bytes = source.read_bytes()
    svg = source_bytes.decode('utf-8')
    if snapshot and hashlib.sha256(source_bytes).hexdigest() != snapshot.pages[page_key]['svg_sha256']:
        raise PageImportError(f'{page_key}: snapshot SVG changed while importing')

    mapping, copies, problems = plan_href_targets(
        svg, source_path=source, asset_root=asset_root, page_key=page_key)
    pinned_hashes = {}
    if snapshot:
        for asset in asset_records(snapshot.pages[page_key]['assets']):
            if asset.get('embedded'):
                continue
            dependency = checked_file(snapshot.root, asset['path'], asset['sha256'])
            target = f'assets/pages/{page_key}/{dependency.name}'
            if target in copies and copies[target] != dependency:
                raise PageImportError(f'{page_key}: packaged asset filename collision: {dependency.name}')
            copies[target] = dependency
            pinned_hashes[target] = asset['sha256']
    inlined, substitutions = _inline_image_hrefs(svg, mapping)

    if copy_assets:
        for rel, src in copies.items():
            if not src.is_file():
                continue
            dest = project / "composition" / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            if snapshot:
                data = src.read_bytes()
                if hashlib.sha256(data).hexdigest() != pinned_hashes[rel]:
                    raise PageImportError(f'{page_key}: snapshot asset changed while importing: {src.name}')
                dest.write_bytes(data)
            else:
                shutil.copy2(src, dest)

    # The proof: rewriting the hrefs back reproduces the source bytes.
    restored, _ = _inline_image_hrefs(inlined, {s["after"]: s["before"] for s in substitutions})
    if restored.encode("utf-8") != source_bytes:
        problems.append(
            f"{page_key}: round trip is not byte-identical — the import changed the page")

    return ImportResult(
        page_key=page_key,
        source=source,
        source_sha256=hashlib.sha256(source_bytes).hexdigest(),
        inlined_sha256=sha256_text(inlined),
        restored_sha256=sha256_text(restored),
        inlined=inlined,
        substitutions=substitutions,
        audit=audit_page(svg),
        problems=problems,
    )


def list_pages(page_dir: Path) -> list:
    directory = Path(page_dir)
    snapshot = resolve_snapshot(directory, directory)
    if snapshot:
        return snapshot.order
    if not directory.is_dir():
        return []
    return sorted(p.stem for p in directory.glob("*.svg"))


def href_boundary(page_dir: Path) -> Path:
    """Where an image href written by a page is allowed to point.

    Pages carry hrefs relative to their own project: `../00_project/...` from
    `<project>/_internal/02_svg_source/`, `../assets/...` from
    `<package>/input/scenes/`. So the boundary is the page directory's parent —
    or, when that parent is `_internal`, the project above it. Getting this
    wrong is what made the documented call
    (`--pages <project>/_internal/02_svg_source`) fail on the pages it shipped:
    the boundary was the page directory, and every `../` href "escaped" it.
    """
    parent = page_dir.parent
    if parent.name == "_internal":
        return parent.parent
    return parent if parent.is_dir() else page_dir


def resolve_pages(project: Path, explicit: Path | None = None):
    """(directory holding the pages, boundary image hrefs may not leave), or (None, None).

    Every shape below is a valid way to point at the same pages, and each one
    resolves to the same `(page dir, boundary)` pair:

    - the picture project root                    → `<root>/_internal/02_svg_source`, boundary `<root>`
    - that `_internal/02_svg_source` directory    → same pair
    - a package root carrying `input/scenes/`     → that directory, boundary `<package>/input`
    - the package's `input/` directory            → its `scenes/`, boundary that `input/`
    - the `input/scenes/` directory itself        → same pair
    - a plain directory of `*.svg`                → itself, boundary its parent

    Order: the given path or the project's `.pages` pointer, then the package the
    upstream hands over.
    """
    snapshot = resolve_snapshot(project, explicit)
    if snapshot:
        return snapshot.root / 'scenes', snapshot.root
    candidate = explicit
    if candidate is None:
        pointer = project / ".pages"
        if pointer.is_file():
            raw = pointer.read_text(encoding="utf-8").strip()
            if raw:
                path = Path(raw)
                candidate = path if path.is_absolute() else (project / path)
    if candidate is not None:
        root = Path(candidate).resolve()
        if (root / PAGE_ROOT).is_dir():
            page_dir = root / PAGE_ROOT
            return page_dir, href_boundary(page_dir)
        if list_pages(root):
            return root, href_boundary(root)
        for nested in (root / PACKAGE_SCENES, root / "scenes"):
            if nested.is_dir() and list_pages(nested):
                return nested, href_boundary(nested)
        return None, None
    package = (project / PACKAGE_SCENES).resolve()
    if package.is_dir() and list_pages(package):
        return package, href_boundary(package)
    return None, None


def read_composite_default(asset_root: Path, project: Path | None = None) -> dict:
    """The whole-film compositing facts, read from `design_direction.md`.

    The block is a fenced ```json block carrying `composite` (`"replace"`
    full-screen, `"over-person"` alpha over the speaker), plus optional
    `personWindow` and `captionSafe`. A per-screen exception goes on that step
    in `grouping.json` and wins over this default.
    """
    if (Path(asset_root) / 'snapshot.json').is_file():
        snapshot = load_snapshot(asset_root)
        return snapshot.data.get('composite', snapshot.data['upstream'].get('composite', {}))
    candidates = [Path(asset_root) / DESIGN_DIRECTION,
                  Path(asset_root) / "design_direction.md"]
    if project is not None:
        candidates += [Path(project) / "input" / "design_direction.md",
                       Path(project) / "design_direction.md"]
    for direction in candidates:
        if not direction.is_file():
            continue
        for block in JSON_BLOCK_RE.findall(direction.read_text(encoding="utf-8")):
            try:
                data = json.loads(block)
            except json.JSONDecodeError:
                continue
            if isinstance(data, dict) and "composite" in data:
                return data
    return {}


def write_manifest(project: Path, default: dict, results: list,
                   per_screen: dict | None = None, ids: dict | None = None) -> Path:
    """The seam's record: what was imported, and what it proves."""
    out = Path(project) / "composition" / "pages" / "manifest.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "default": default,
        "pages": [r.as_manifest() for r in results],
        "perScreen": per_screen or {},
        "ids": ids if ids is not None else audit_pages(results),
    }
    snapshot = resolve_snapshot(project)
    if results and (results[0].source.parent.parent / 'snapshot.json').is_file():
        snapshot = resolve_snapshot(project, results[0].source.parent.parent)
    if snapshot:
        previous = json.loads(out.read_text()) if out.is_file() else {}
        payload['snapshot'] = snapshot.binding()
        payload['invalidation'] = invalidation(previous.get('snapshot', {}), snapshot)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Import picture pages (SVG) into the composition")
    ap.add_argument("project", type=Path)
    ap.add_argument("--pages", type=Path, default=None,
                    help="picture project root, or a directory of *.svg pages")
    ap.add_argument("--page", action="append", default=None, help="page key (repeatable)")
    ap.add_argument("--audit", action="store_true", help="report what each page lets you address")
    ap.add_argument("--prove", action="store_true", help="print the byte-identical round trip")
    ap.add_argument("--emit", action="store_true", help="write composition/pages/manifest.json")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    project = args.project.resolve()
    page_dir, asset_root = resolve_pages(project, args.pages)
    if page_dir is None:
        raise SystemExit(
            f"no picture pages — pass --pages <path>, write {project / '.pages'}, "
            f"or put one SVG per screen in {project / PACKAGE_SCENES}")
    keys = args.page or list_pages(page_dir)
    if not keys:
        raise SystemExit(f"no *.svg pages under {page_dir}")

    try:
        results = [import_page(k, page_dir=page_dir, asset_root=asset_root, project=project)
                   for k in keys]
    except (PageImportError, FileNotFoundError) as exc:
        raise SystemExit(str(exc)) from None

    if args.emit:
        default = read_composite_default(asset_root, project)
        print(f"manifest -> {write_manifest(project, default, results, ids=audit_pages(results))}")

    if args.json:
        print(json.dumps({"pages": [r.as_manifest() for r in results],
                          "ids": audit_pages(results)},
                         ensure_ascii=False, indent=2))
        return 0

    unaddressable = 0
    for r in results:
        a = r.audit
        print(f"{r.page_key}: {a['viewBox']} · {a['text_nodes']} text · {a['path_nodes']} path"
              f" · {len(a['element_ids'])} element id(s) · {a['elements_with_class']} class")
        if args.prove:
            mark = "byte-identical" if r.verbatim else "CHANGED"
            print(f"  round trip: {mark}  ({len(r.substitutions)} href rewrite(s))")
        if args.audit and not a["addressable"]:
            unaddressable += 1
            print("  ! no element id below <svg>: this page can still be used as a whole-page"
                  "\n    visual. Element-level animation is unavailable until it gets stable ids;"
                  " for larger re-composition use the recompose mode instead.")
        for problem in r.problems:
            print(f"  x {problem}")

    ids = audit_pages(results)
    if args.audit and not ids["clean"]:
        print("\n! ids shared by more than one page — if you do element-level animation, these"
              "\n  pages land in ONE DOM and the global selector resolves a repeated id to the"
              "\n  first match, so \"animate #name\" can highlight another screen's element:")
        for name, owners in ids["collisions"].items():
            print(f"    #{name}  in  {', '.join(owners)}")
        print("  Fix only if you want element-level animation: prefix every id with its"
              "\n  page key so it is unique across the film, then re-render the pages.")

    if args.audit and (unaddressable or not ids["clean"]):
        print(f"\n{unaddressable}/{len(results)} page(s) have no element id · "
              f"{len(ids['collisions'])} id(s) collide across pages."
              "\n  This is capability info, not an import failure: whole-page visuals remain usable.")
    if any(r.problems for r in results):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
