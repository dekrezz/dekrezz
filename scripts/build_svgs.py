"""Render README SVGs with Geist glyphs converted to paths (GitHub can't load webfonts in <img>)."""
import io
from html import escape
import sys
from pathlib import Path

import uharfbuzz as hb
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont

FONTS_DIR = Path(sys.argv[1])
OUT = Path(sys.argv[2])
OUT.mkdir(parents=True, exist_ok=True)

W = 830
THEMES = {
    "dark": {"fg": "#FAFAFA", "muted": "#8B8B8B", "line": "#262626", "pill_bg": "#FAFAFA", "pill_fg": "#0A0A0A"},
    "light": {"fg": "#0A0A0A", "muted": "#6B6B6B", "line": "#E5E5E5", "pill_bg": "#0A0A0A", "pill_fg": "#FAFAFA"},
}


class Font:
    def __init__(self, path):
        data = path.read_bytes()
        self.tt = TTFont(io.BytesIO(data))
        # harfbuzz can't read woff2; hand it the decompressed sfnt
        buf = io.BytesIO()
        self.tt.flavor = None
        self.tt.save(buf)
        self.hb_font = hb.Font(hb.Face(buf.getvalue()))
        self.upem = self.tt["head"].unitsPerEm
        self.glyphs = self.tt.getGlyphSet()
        self.order = self.tt.getGlyphOrder()

    def shape(self, text):
        buf = hb.Buffer()
        buf.add_str(text)
        buf.guess_segment_properties()
        hb.shape(self.hb_font, buf, {"kern": True, "liga": True})
        return buf.glyph_infos, buf.glyph_positions

    def width(self, text, size, tracking=0.0):
        _, pos = self.shape(text)
        s = size / self.upem
        return sum(p.x_advance for p in pos) * s + tracking * size * len(pos)

    def path(self, text, size, x, y, tracking=0.0):
        infos, pos = self.shape(text)
        s = size / self.upem
        pen = SVGPathPen(self.glyphs, ntos=lambda v: f"{v:.1f}".rstrip("0").rstrip("."))
        cx = x
        for info, p in zip(infos, pos):
            name = self.order[info.codepoint]
            t = TransformPen(pen, (s, 0, 0, -s, cx + p.x_offset * s, y - p.y_offset * s))
            self.glyphs[name].draw(t)
            cx += p.x_advance * s + tracking * size
        return pen.getCommands()


SANS = Font(FONTS_DIR / "geist-sans/Geist-Regular.woff2")
SANS_MED = Font(FONTS_DIR / "geist-sans/Geist-Medium.woff2")
MONO = Font(FONTS_DIR / "geist-mono/GeistMono-Regular.woff2")


def text(font, s, size, x, y, fill, tracking=0.0, anchor="start"):
    if anchor == "end":
        x -= font.width(s, size, tracking)
    d = font.path(s, size, x, y, tracking)
    return f'<path fill="{fill}" d="{d}"/>'


def wrap(font, s, size, max_w, tracking=0.0):
    lines, cur = [], ""
    for word in s.split(" "):
        cand = f"{cur} {word}".strip()
        if cur and font.width(cand, size, tracking) > max_w:
            lines.append(cur)
            cur = word
        else:
            cur = cand
    lines.append(cur)
    return lines


def svg(name, h, body, title):
    title = escape(title)
    for theme, c in THEMES.items():
        content = body(c)
        (OUT / f"{name}-{theme}.svg").write_text(
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{h}" viewBox="0 0 {W} {h}" '
            f'role="img" aria-label="{title}"><title>{title}</title>{content}</svg>\n'
        )


# ---------- logo ----------
def mark(x, y, size, fill):
    """Monogram 'd': ring + stem, cut from a square grid of `size`."""
    u = size / 24
    return (f'<g transform="translate({x} {y}) scale({u})" fill="{fill}">'
            '<path fill-rule="evenodd" d="M10 6a9 9 0 1 0 0 18a9 9 0 1 0 0-18zm0 4.5a4.5 4.5 0 1 1 0 9a4.5 4.5 0 1 1 0-9z"/>'
            '<rect x="15" y="0" width="4.5" height="24" rx="0"/></g>')


def logo(c):
    return mark(0, 0, 40, c["fg"]) + text(SANS_MED, "dekrezz", 30, 54, 31, c["fg"], -0.03)


for theme, c in THEMES.items():
    (OUT / f"logo-{theme}.svg").write_text(
        f'<svg xmlns="http://www.w3.org/2000/svg" width="40" height="40" viewBox="0 0 40 40" role="img" '
        f'aria-label="dekrezz logo"><title>dekrezz</title>{mark(0, 0, 40, c["fg"])}</svg>\n')


# ---------- hero ----------
HEAD = ["Agent infrastructure,", "MCP tooling & dev tools."]
HEAD_SIZE, HEAD_TRACK, HEAD_LH = 54, -0.045, 60


def hero(c):
    out = [logo(c), f'<rect x="0" y="68" width="{W}" height="1" fill="{c["line"]}"/>']
    y = 156
    for line in HEAD:
        out.append(text(SANS, line, HEAD_SIZE, -2, y, c["fg"], HEAD_TRACK))
        y += HEAD_LH
    y += 8
    for line in ["I build tools for coding agents — orchestration, MCP servers, voice and",
                 "desktop utilities. TypeScript, Rust, Go, Swift, Python."]:
        out.append(text(SANS, line, 18, 0, y, c["muted"], -0.01))
        y += 28
    out.append(f'<rect x="0" y="{y + 20}" width="{W}" height="1" fill="{c["line"]}"/>')
    return "".join(out)


svg("hero", 361, hero, "dekrezz — Agent infrastructure, MCP tooling and dev tools")

# ---------- project rows ----------
PROJECTS = [
    ("FreeDeepseekAPI", "DeepSeek as an API for your apps and coding agents, no bills."),
    ("updatetools", "One command to update everything on your Mac, without closing apps."),
]


def project(name, desc):
    def body(c):
        ax = W - 4
        return "".join([
            text(SANS_MED, name, 22, 0, 40, c["fg"], -0.02),
            text(SANS, desc, 15, 0, 66, c["muted"], -0.005),
            f'<path d="M{ax - 11} 38 L{ax} 27 M{ax - 8} 27 L{ax} 27 L{ax} 35" '
            f'stroke="{c["fg"]}" stroke-width="1.4" fill="none" stroke-linecap="round" stroke-linejoin="round"/>',
            f'<rect x="0" y="91" width="{W}" height="1" fill="{c["line"]}"/>',
        ])
    svg(f"work-{name.lower()}", 92, body, f"{name} — {desc}")


for p in PROJECTS:
    project(*p)
print("ok", sorted(p.name for p in OUT.iterdir()))
