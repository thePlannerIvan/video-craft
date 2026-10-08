"""Strict, read-only workbench snapshot resolution for every SVG consumer."""
from __future__ import annotations

import hashlib
import json
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

VERSION = 'svg-workbench-snapshot/1'
KEY = re.compile(r'[A-Za-z][A-Za-z0-9_-]{0,63}')
HASH = re.compile(r'[a-f0-9]{64}')


class SnapshotError(ValueError):
    pass


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def local_file(root: Path, relative: str) -> Path:
    if not isinstance(relative, str) or Path(relative).is_absolute():
        raise SnapshotError('Snapshot file paths must be relative')
    path = (root / relative).resolve()
    if root not in path.parents or any(part.startswith('.env') for part in path.parts):
        raise SnapshotError(f'Unsafe snapshot path: {relative}')
    if not path.is_file():
        raise SnapshotError(f'Missing pinned snapshot file: {relative}')
    return path


def checked_file(root: Path, relative: str, expected: str) -> Path:
    if not isinstance(expected, str) or not HASH.fullmatch(expected):
        raise SnapshotError(f'Missing SHA256 binding: {relative}')
    path = local_file(root, relative)
    if sha256(path.read_bytes()) != expected:
        raise SnapshotError(f'Mutated snapshot file: {relative}')
    return path


def asset_records(items):
    if not isinstance(items, list):
        raise SnapshotError('Pinned dependencies must be an array')
    for asset in items:
        if not isinstance(asset, dict) or not HASH.fullmatch(str(asset.get('sha256', ''))):
            raise SnapshotError('Invalid pinned asset record')
        yield asset
        yield from asset_records(asset.get('dependencies', []))


def svg_tree(raw: bytes):
    text = raw.decode('utf-8')
    if re.search(r'<!DOCTYPE|<!ENTITY', text, re.I):
        raise SnapshotError('Unsupported SVG declarations')
    tree = ET.fromstring(text)
    if tree.tag.split('}')[-1] != 'svg':
        raise SnapshotError('Expected SVG root')
    return tree


def validate_images(root, tree, owner, records, nested=False):
    pinned, embedded = {}, {}
    for asset in records:
        if asset.get('embedded'):
            embedded[asset.get('element_id')] = asset['sha256']
        else:
            pinned[local_file(root, asset['path'])] = asset['sha256']
    for node in tree.iter():
        if node.tag.split('}')[-1] != 'image':
            continue
        hrefs = [value for attribute, value in node.attrib.items() if attribute.split('}')[-1] == 'href']
        if not hrefs:
            raise SnapshotError(f'{owner}: image has no pinned href')
        for href in hrefs:
            if href.startswith('data:'):
                if href.lower().startswith('data:image/svg+xml'):
                    raise SnapshotError('Embedded SVG assets require a local pinned SVG file')
                identity = node.get('data-workbench-id') or node.get('id')
                if embedded.get(identity) != sha256(href.encode()):
                    raise SnapshotError(f'{owner}: unpinned embedded image')
            else:
                target = local_file(root, str(Path(owner).parent / href))
                if target not in pinned:
                    raise SnapshotError(f'{owner}: image is not in pinned assets: {href}')
                if nested and target.parent != (root / owner).parent:
                    raise SnapshotError('Nested SVG assets must reference packaged sibling files')


def validate_assets(root, records, visiting=frozenset()):
    # Validate the complete dependency tree before any consumer writes an output.
    list(asset_records(records))
    for asset in records:
        dependencies = asset.get('dependencies', [])
        if asset.get('embedded'):
            if dependencies:
                raise SnapshotError('Embedded assets cannot carry external dependencies')
            continue
        path = checked_file(root, asset.get('path'), asset['sha256'])
        if path in visiting:
            raise SnapshotError('Cyclic nested SVG dependency')
        validate_assets(root, dependencies, visiting | {path})
        if path.suffix.lower() == '.svg':
            validate_images(root, svg_tree(path.read_bytes()), asset['path'], dependencies, nested=True)
        elif dependencies:
            raise SnapshotError('Only SVG assets can carry image dependencies')


@dataclass
class Snapshot:
    root: Path
    path: Path
    digest: str
    data: dict
    pages: dict

    @property
    def order(self) -> list[str]:
        return self.data['order']

    def fingerprints(self) -> dict:
        return {key: {
            'revision': page['revision'], 'svg_sha256': page['svg_sha256'],
            'assets': sorted({asset['sha256'] for asset in asset_records(page['assets'])}),
            'steps': step_identity(local_file(self.root, page['svg'])),
            'elements': [node.get('id') for node in ET.fromstring(local_file(self.root, page['svg']).read_bytes()).iter()
                         if node.get('id')],
        } for key, page in self.pages.items()}

    def binding(self) -> dict:
        return {'path': str(self.path), 'sha256': self.digest,
                'snapshot_id': self.data['snapshot_id'],
                'upstream': self.data['upstream'], 'screens': self.fingerprints(),
                'content_binding': self.data.get('content_binding'),
                'content_deltas': {key: page.get('content_delta', []) for key, page in self.pages.items()},
                'script_semantics_verified': False}


def step_identity(path: Path) -> list:
    tree = ET.fromstring(path.read_bytes())
    return [[node.get('data-step'), node.get('id')]
            for node in tree.iter() if node.get('data-step') is not None]


def load_snapshot(path: Path) -> Snapshot:
    path = Path(path).resolve()
    if path.is_dir():
        path /= 'snapshot.json'
    root = path.parent
    if any(part.startswith('.env') for part in path.parts):
        raise SnapshotError('Environment files are not snapshot inputs')
    if not path.is_file():
        raise SnapshotError(f'Missing snapshot manifest: {path}')
    raw = path.read_bytes()
    fingerprint = sha256(raw)
    if not (root / 'snapshot.sha256').is_file() or (root / 'snapshot.sha256').read_text().strip() != fingerprint:
        raise SnapshotError('Missing or mutated snapshot manifest SHA256')
    data = json.loads(raw)
    if data.get('version') != VERSION or data.get('route') != 'video':
        raise SnapshotError('Craft needs a video svg-workbench-snapshot/1')
    if data.get('content_binding') not in ('baseline', 'changed_needs_check'):
        raise SnapshotError('Snapshot must declare baseline or changed_needs_check content provenance')
    if not KEY.fullmatch(str(data.get('snapshot_id', ''))) or data['snapshot_id'] != root.name:
        raise SnapshotError('Snapshot identity does not match directory')
    order, records = data.get('order'), data.get('pages')
    if not isinstance(order, list) or not order or any(not isinstance(key, str) or not KEY.fullmatch(key) for key in order):
        raise SnapshotError('Invalid snapshot page order')
    if len(set(order)) != len(order) or not isinstance(records, list):
        raise SnapshotError('Duplicate snapshot page identity')
    pages = {}
    for page in records:
        if not isinstance(page, dict):
            raise SnapshotError('Snapshot page records must be objects')
        key = page.get('page_key')
        if key not in order or key in pages or not KEY.fullmatch(str(page.get('revision', ''))):
            raise SnapshotError('Invalid page/revision identity')
        if page.get('svg') != f'scenes/{key}.svg':
            raise SnapshotError(f'{key}: SVG path does not match page identity')
        svg_path = checked_file(root, page['svg'], page.get('svg_sha256'))
        tree = svg_tree(svg_path.read_bytes())
        for field in ('data-page-key', 'data-screen-id', 'screen_id'):
            if tree.get(field) is not None and tree.get(field) != key:
                raise SnapshotError(f'{key}: SVG screen identity mismatch')
        assets = page.get('assets')
        if not isinstance(assets, list):
            raise SnapshotError(f'{key}: missing pinned assets')
        validate_assets(root, assets)
        validate_images(root, tree, page['svg'], assets)
        pages[key] = page
    if set(pages) != set(order):
        raise SnapshotError('Snapshot page records do not cover order')
    if data['content_binding'] == 'baseline' and any(page.get('content_delta') for page in pages.values()):
        raise SnapshotError('Changed SVG text cannot claim baseline content')
    upstream = data.get('upstream')
    if not isinstance(upstream, dict):
        raise SnapshotError('Missing original upstream binding')
    contract = upstream.get('visual_contract')
    if not isinstance(contract, dict):
        raise SnapshotError('Missing original visual contract binding')
    plan_path = checked_file(root, upstream.get('visual_plan_snapshot'), contract.get('sha256'))
    script_path = checked_file(root, upstream.get('script_snapshot'), contract.get('script_hash'))
    if upstream.get('script_sha256') != sha256(script_path.read_bytes()):
        raise SnapshotError('Original script SHA256 changed')
    plan = json.loads(plan_path.read_bytes())
    if plan.get('script_hash') != contract['script_hash']:
        raise SnapshotError('Original visual-plan script_hash changed')
    declarations = plan.get('screens', plan.get('blueprints', []))
    if not isinstance(declarations, list) or any(not isinstance(record, dict) for record in declarations):
        raise SnapshotError('Invalid original visual-plan screen declarations')
    declared = [record.get('screen_id', record.get('blueprint_id')) for record in declarations]
    if len(set(declared)) != len(declared) or set(declared) != set(order):
        raise SnapshotError('Snapshot screen identities differ from original visual plan')
    for name, value in upstream.items():
        if name.endswith('_snapshot') and name not in ('visual_plan_snapshot', 'script_snapshot'):
            checked_file(root, value, upstream.get(name[:-9] + '_sha256'))
    return Snapshot(root, path, fingerprint, data, pages)


def resolve_snapshot(project: Path, explicit: Path | None = None) -> Snapshot | None:
    project = Path(project).resolve()
    candidate = explicit
    if candidate is None:
        for name in ('.snapshot', '.pages'):
            pointer = project / name
            if pointer.is_file() and pointer.read_text().strip():
                candidate = Path(pointer.read_text().strip())
                if not candidate.is_absolute():
                    candidate = project / candidate
                break
    if candidate is None:
        candidate = project / 'input'
    path = Path(candidate).resolve()
    root = path.parent if path.name in ('snapshot.json', 'snapshot.sha256', 'scenes') else path
    workbench_path = any(
        ancestor.name == 'snapshots' and ancestor.parent.name == '06_workbench'
        and ancestor.parent.parent.name == '_internal' for ancestor in (root, *root.parents))
    snapshot_expected = (path.name in ('snapshot.json', 'snapshot.sha256') or workbench_path
                         or (root / 'snapshot.sha256').exists()
                         or (project / '.snapshot').exists() and explicit is None)
    if snapshot_expected and not (root / 'snapshot.json').is_file():
        raise SnapshotError(f'Missing snapshot manifest: {root / "snapshot.json"}')
    snapshot = None
    if snapshot_expected:
        snapshot = load_snapshot(root)
    elif path.name == 'snapshot.json' or (path / 'snapshot.json').exists():
        snapshot = load_snapshot(path)
    elif path.name == 'scenes' and (path.parent / 'snapshot.json').exists():
        snapshot = load_snapshot(path.parent)
    if snapshot:
        for receipt in (project / 'composition/pages/manifest.json', project / 'timeline/choreography.json'):
            if receipt.is_file():
                prior = json.loads(receipt.read_text()).get('snapshot', {})
                if prior.get('snapshot_id') == snapshot.data['snapshot_id'] and prior.get('sha256') != snapshot.digest:
                    raise SnapshotError('Previously consumed snapshot identity was mutated')
        return snapshot
    if (project / '.snapshot').exists() and explicit is None:
        raise SnapshotError('Explicit snapshot pointer is missing its manifest')
    return None


def invalidation(previous: dict, current: Snapshot) -> dict:
    old = previous.get('screens', {})
    new = current.fingerprints()
    changed = [key for key in current.order
               if any(old.get(key, {}).get(field) != new[key][field] for field in ('svg_sha256', 'assets'))]
    removed = sorted(set(old) - set(new))
    steps = [key for key in changed if old.get(key, {}).get('steps') != new[key]['steps']
             or old.get(key, {}).get('elements') != new[key]['elements']]
    return {'static_screens': changed, 'animation_screens': steps, 'removed_screens': removed,
            'content_review_screens': [key for key in current.order if current.pages[key].get('content_delta')],
            'upstream_changed': bool(previous and previous.get('upstream') != current.data['upstream']),
            'audio_retimed': False, 'reverse_sync': False}
