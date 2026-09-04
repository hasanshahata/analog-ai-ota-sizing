"""Static consistency tests for the web UI (no browser needed).

These catch the stale-markup bug class that once killed the submit button:
JavaScript referencing element ids that no longer exist in the HTML.
"""

from __future__ import annotations

import re
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "web_app" / "static"
JS_IDS = re.compile(r'\$\("([A-Za-z0-9_-]+)"\)')
HTML_IDS = re.compile(r'id="([A-Za-z0-9_-]+)"')


def _html() -> str:
    return (STATIC / "index.html").read_text(encoding="utf-8")


def _js() -> str:
    return (STATIC / "app.js").read_text(encoding="utf-8")


def test_every_js_id_reference_exists_in_html():
    html_ids = set(HTML_IDS.findall(_html()))
    missing = sorted(set(JS_IDS.findall(_js())) - html_ids)
    assert not missing, f"app.js references ids missing from index.html: {missing}"


def test_no_duplicate_ids_in_html():
    ids = HTML_IDS.findall(_html())
    dupes = sorted({i for i in ids if ids.count(i) > 1})
    assert not dupes, f"duplicate element ids in index.html: {dupes}"


def test_assets_are_versioned_for_cache_busting():
    html = _html()
    assert re.search(r'href="tailwind\.css\?v=\d+"', html), \
        "compiled tailwind.css must carry a ?v= cache-busting version"
    assert re.search(r'href="style\.css\?v=\d+"', html), \
        "style.css must carry a ?v= cache-busting version"
    assert re.search(r'src="app\.js\?v=\d+"', html), \
        "app.js must carry a ?v= cache-busting version"


def test_dynamic_ids_used_by_renderers_exist():
    # ids only created dynamically inside JS template strings are checked
    # against the static HTML sections they are injected into
    js = _js()
    html = _html()
    for anchor, container in [
        ("geometry-body", 'id="geometry-body"'),
    ]:
        assert container in html and anchor in js
    # every runtime .innerHTML target must exist statically
    for m in re.finditer(r'\$\("([A-Za-z0-9_-]+)"\)\.innerHTML', js):
        assert f'id="{m.group(1)}"' in html, m.group(1)


def test_ui_has_no_runtime_cdn_dependencies():
    """The local app must retain layout/visibility without internet access."""
    html = _html().lower()
    assert "cdn.tailwindcss.com" not in html
    assert "fonts.googleapis.com" not in html
    assert "fonts.gstatic.com" not in html
    css = STATIC / "tailwind.css"
    assert css.exists() and css.stat().st_size > 10_000
    assert ".hidden" in css.read_text(encoding="utf-8")
