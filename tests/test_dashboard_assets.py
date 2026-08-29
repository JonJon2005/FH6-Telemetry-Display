from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path
import re


STATIC = Path(__file__).parents[1] / "app" / "web" / "static"


class DashboardParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.ids: list[str] = []
        self.buttons_without_type: list[str] = []
        self.images_without_alt: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if attributes.get("id"):
            self.ids.append(attributes["id"] or "")
        if tag == "button" and not attributes.get("type"):
            self.buttons_without_type.append(attributes.get("id") or "anonymous")
        if tag == "img" and attributes.get("alt") is None:
            self.images_without_alt.append(attributes.get("src") or "unknown")


def test_dashboard_markup_has_unique_ids_and_safe_controls() -> None:
    parser = DashboardParser()
    parser.feed((STATIC / "dashboard.html").read_text(encoding="utf-8"))
    assert len(parser.ids) == len(set(parser.ids))
    assert not parser.buttons_without_type
    assert not parser.images_without_alt
    assert {"speed-value", "gear-value", "rev-lights", "g-dot", "stale-overlay"} <= set(parser.ids)


def test_dashboard_javascript_only_references_existing_element_ids() -> None:
    markup = (STATIC / "dashboard.html").read_text(encoding="utf-8")
    script = (STATIC / "dashboard.js").read_text(encoding="utf-8")
    markup_ids = set(re.findall(r'id="([^"]+)"', markup))
    direct_references = set(re.findall(r'byId\("([^"]+)"\)', script))
    array_match = re.search(r"Object\.fromEntries\(\[(.*?)\]\.map", script, re.DOTALL)
    assert array_match is not None
    array_references = set(re.findall(r'"([a-z][a-z0-9-]+)"', array_match.group(1)))
    assert direct_references | array_references <= markup_ids


def test_dashboard_visual_system_avoids_requested_tropes() -> None:
    markup = (STATIC / "dashboard.html").read_text(encoding="utf-8").lower()
    styles = (STATIC / "dashboard.css").read_text(encoding="utf-8").lower()
    assert "eyebrow" not in markup
    assert "gradient" not in styles
    assert "backdrop-filter" not in styles
    assert "border-radius:999" not in styles
    assert "linear-gradient" not in styles


def test_dashboard_has_desktop_mobile_landscape_and_reduced_motion_rules() -> None:
    styles = (STATIC / "dashboard.css").read_text(encoding="utf-8")
    assert 'grid-template-areas:"main main race"' in styles
    assert "@media(max-width:1100px)" in styles
    assert "@media(max-width:680px)" in styles
    assert "@media(max-width:390px)" in styles
    assert "@media(orientation:landscape)" in styles
    assert "@media(prefers-reduced-motion:reduce)" in styles


def test_dashboard_uses_production_stream_and_animation_frame_smoothing() -> None:
    script = (STATIC / "dashboard.js").read_text(encoding="utf-8")
    assert "/ws/telemetry" in script
    assert "/ws/debug" not in script
    assert "requestAnimationFrame(animate)" in script
    assert "setTimeout(connect,state.retry)" in script
    assert 'fetch("/api/telemetry"' in script


def test_inactive_waiting_notice_is_not_left_peeking_into_viewport() -> None:
    script = (STATIC / "dashboard.js").read_text(encoding="utf-8")
    assert 'style.display=live?"none":"flex"' in script
