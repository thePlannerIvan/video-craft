"""Transport a compiled HyperFrames composition through ReviewBridge.

Build-time HTTP is loopback-only. Browser playback uses srcdoc + bridge-owned
blob assets, so an opaque DSH frame never fetches a loopback URL. This module
owns transport, not animation, media clocks, or rendering.
"""
from __future__ import annotations
import hashlib
import html
from html.parser import HTMLParser
import re
from pathlib import Path
from urllib.parse import urljoin, urlparse, unquote
from urllib.request import urlopen


def fetch_local(url):
    parsed = urlparse(url)
    if parsed.scheme != 'http' or parsed.hostname not in ('127.0.0.1', 'localhost', '::1'):
        raise ValueError('HyperFrames preview must be a loopback HTTP server')
    with urlopen(url, timeout=15) as response:
        if urlparse(response.geturl()).netloc != parsed.netloc:
            raise ValueError('Preview redirect changed origin')
        return response.read().decode('utf-8')


class CompositionTransport(HTMLParser):
    def __init__(self, project, stage_url, fetch=fetch_local, composition_dir=None):
        super().__init__(convert_charrefs=False)
        self.project = Path(project).resolve()
        self.composition = (Path(composition_dir) if composition_dir else self.project / "composition").resolve()
        self.stage_url = stage_url
        self.fetch = fetch
        self.out, self.assets = [], {}
        # Byte accounting for the live stage's asset map. The review page turns
        # every entry into a base64 data URL inside the player's srcdoc, so the
        # map's total size — not the composition's — is what the page has to chew
        # through before `hyperframes-player` can report ready. Measured: ~19 MB
        # of media (25 MB once base64) blew an 8-second watchdog and the stage
        # showed "预览暂时无法连接" while every other part of the page worked.
        # Reporting is this module's job; deciding what to do about it (a review
        # proxy) belongs to build_review.py.
        self.asset_bytes = 0
        self.asset_sizes: dict = {}
        self.skip_script = False
        self.in_style = False
        self.scripts = set()

    def asset(self, value):
        if not value or value.startswith(('#', 'data:', 'blob:')):
            return value
        parsed = urlparse(value)
        base = urlparse(self.stage_url)
        if parsed.scheme or value.startswith('//'):
            if parsed.netloc != base.netloc:
                raise ValueError('External asset must be imported into composition: ' + value)
            prefix = urlparse(self.stage_url).path.rsplit('/', 1)[0] + '/'
            if not parsed.path.startswith(prefix):
                raise ValueError('Asset is outside the composition route')
            value = parsed.path[len(prefix):]
        path = (self.composition / unquote(urlparse(value).path)).resolve()
        if not path.is_relative_to(self.composition) or not path.is_file():
            raise ValueError('Missing or escaping composition asset: ' + value)
        rel = path.relative_to(self.project).as_posix()
        self.asset_sizes[rel] = path.stat().st_size
        for token, existing in self.assets.items():
            if existing == rel:
                return token
        token = '__VC_ASSET_' + str(len(self.assets)) + '__'
        self.assets[token] = rel
        self.asset_bytes += self.asset_sizes[rel]
        return token

    def css(self, text):
        return re.sub(r'url\(\s*[\'"]?([^\)\'"\s]+)[\'"]?\s*\)',
                      lambda m: 'url("' + self.asset(m[1]) + '")', text)

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag == 'base':
            return
        if tag == 'script' and values.get('src'):
            self.skip_script = True
            src = values['src']
            if 'composition-embed-bridge.js' in src or src in self.scripts:
                return
            self.scripts.add(src)
            url = urljoin(self.stage_url, src)
            if urlparse(url).netloc != urlparse(self.stage_url).netloc:
                raise ValueError('External script must be local: ' + src)
            if src.startswith('/'):
                code = self.fetch(url)
            else:
                local = (self.composition / unquote(urlparse(src).path)).resolve()
                if not local.is_relative_to(self.composition) or not local.is_file():
                    raise ValueError('Missing or escaping composition script: ' + src)
                code = local.read_text(encoding='utf-8')
            if code.lstrip().lower().startswith(('<!doctype', '<html')):
                raise ValueError('Script route returned HTML: ' + src)
            code = code.replace('</script', '<\\/script')
            self.out.append('<script>' + code + '</script>')
            return
        if tag == 'link' and values.get('rel') == 'stylesheet':
            href = values['href']
            css_path = (self.composition / unquote(urlparse(href).path)).resolve()
            if urlparse(href).scheme or not css_path.is_relative_to(self.composition) or not css_path.is_file():
                raise ValueError('Stylesheet must be local to composition: ' + href)
            css = css_path.read_text(encoding='utf-8')
            css = re.sub(r'url\(\s*[\'"]?([^\)\'"\s]+)[\'"]?\s*\)',
                         lambda m: 'url("' + (m[1] if m[1].startswith(('data:', '#')) else (css_path.parent / m[1]).relative_to(self.composition).as_posix()) + '")', css)
            self.out.append('<style>' + self.css(css) + '</style>')
            return
        converted = []
        for key, value in attrs:
            if key in ('src', 'poster', 'href', 'xlink:href') and tag not in ('a', 'script'):
                value = self.asset(value)
            if key == 'style' and value:
                value = self.css(value)
            converted.append(key if value is None else key + '="' + html.escape(value, quote=True) + '"')
        self.out.append('<' + tag + (' ' + ' '.join(converted) if converted else '') + '>')
        if tag == 'style':
            self.in_style = True

    def handle_endtag(self, tag):
        if tag == 'script' and self.skip_script:
            self.skip_script = False
            return
        if tag == 'style': self.in_style = False
        self.out.append('</' + tag + '>')

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if self.out and self.out[-1].endswith('>'):
            self.out[-1] = self.out[-1][:-1] + '/>'

    def handle_data(self, text):
        if not self.skip_script: self.out.append(self.css(text) if self.in_style else text)

    def handle_entityref(self, name): self.out.append('&' + name + ';')
    def handle_charref(self, name): self.out.append('&#' + name + ';')
    def handle_comment(self, text): self.out.append('<!--' + text + '-->')
    def handle_decl(self, text): self.out.append('<!' + text + '>')


def compile_preview(project, stage_url, fetch=fetch_local, composition_dir=None):
    source = fetch(stage_url)
    if 'data-hyperframes-preview-runtime' not in source or 'data-composition-id' not in source:
        raise ValueError('Preview route did not return a compiled composition')
    transport = CompositionTransport(project, stage_url, fetch, composition_dir=composition_dir)
    transport.feed(source)
    compiled = ''.join(transport.out)
    digest = hashlib.sha256(compiled.encode())
    for rel in transport.assets.values():
        digest.update(rel.encode())
        with (Path(project) / rel).open('rb') as media:
            for chunk in iter(lambda: media.read(1024 * 1024), b''): digest.update(chunk)
    return {'html': compiled, 'assets': transport.assets,
            'assetBytes': transport.asset_bytes,
            'assetSizes': transport.asset_sizes,
            'sourceHash': digest.hexdigest()}
