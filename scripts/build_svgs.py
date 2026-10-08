"""Usage: GH_TOKEN=... build_svgs.py <geist dist/fonts> <simple-icons icons dir> <assets dir> <README.md>

Renders the profile README as SVGs with Geist glyphs converted to paths (GitHub can't load
webfonts inside <img>). Stats and languages are aggregated over all owned repos, private
included; only totals are rendered, never repo names. GH_TOKEN needs `repo` + `read:user`.
"""
import collections
import hashlib
import io
import json
import os
import re
import sys
import urllib.request
from html import escape
from pathlib import Path

import uharfbuzz as hb
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont

FONTS_DIR, ICONS_DIR, OUT, README = map(Path, sys.argv[1:5])
USER = "dekrezz"
TOKEN = os.environ.get("GH_TOKEN")
if not TOKEN:
    sys.exit("GH_TOKEN is not set: stats need a token with `repo` + `read:user` scopes")

W = 830
THEMES = {
    "dark": {"fg": "#FAFAFA", "muted": "#8B8B8B", "line": "#262626"},
    "light": {"fg": "#0A0A0A", "muted": "#6B6B6B", "line": "#E5E5E5"},
}


# ---------- GitHub data ----------
def gh(path, body=None):
    req = urllib.request.Request(
        f"https://api.github.com/{path}",
        data=json.dumps(body).encode() if body else None,
        headers={"Authorization": f"Bearer {TOKEN}", "Accept": "application/vnd.github+json"},
    )
    with urllib.request.urlopen(req) as r:
        data = json.load(r)
    if "errors" in data:
        raise RuntimeError(f"GitHub API error: {data['errors']}")
    return data


def fetch_stats():
    repos, cursor = [], None
    while True:
        q = """query($c: String) { viewer {
            repositories(ownerAffiliations: OWNER, first: 100, after: $c) {
              totalCount pageInfo { hasNextPage endCursor }
              nodes { isFork languages(first: 20) { edges { size node { name } } } } }
            contributionsCollection { contributionCalendar { totalContributions } } } }"""
        v = gh("graphql", {"query": q, "variables": {"c": cursor}})["data"]["viewer"]
        page = v["repositories"]
        repos += page["nodes"]
        if not page["pageInfo"]["hasNextPage"]:
            break
        cursor = page["pageInfo"]["endCursor"]

    langs = collections.Counter()
    for r in repos:
        if not r["isFork"]:
            for e in r["languages"]["edges"]:
                langs[e["node"]["name"]] += e["size"]

    # GraphQL hides private commits as "restricted"; search with a `repo` token counts them.
    return {
        "commits": gh(f"search/commits?q=author:{USER}")["total_count"],
        "contributions": v["contributionsCollection"]["contributionCalendar"]["totalContributions"],
        "prs": gh(f"search/issues?q=author:{USER}+type:pr")["total_count"],
        "repos": page["totalCount"],
        "langs": langs,
    }


# ---------- type ----------
class Font:
    def __init__(self, path):
        self.tt = TTFont(io.BytesIO(path.read_bytes()))
        buf = io.BytesIO()  # harfbuzz can't read woff2; hand it the decompressed sfnt
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
        return sum(p.x_advance for p in pos) * size / self.upem + tracking * size * len(pos)

    def path(self, text, size, x, y, tracking=0.0):
        infos, pos = self.shape(text)
        s = size / self.upem
        pen = SVGPathPen(self.glyphs, ntos=lambda v: f"{v:.1f}".rstrip("0").rstrip("."))
        cx = x
        for info, p in zip(infos, pos):
            t = TransformPen(pen, (s, 0, 0, -s, cx + p.x_offset * s, y - p.y_offset * s))
            self.glyphs[self.order[info.codepoint]].draw(t)
            cx += p.x_advance * s + tracking * size
        return pen.getCommands()


SANS = Font(FONTS_DIR / "geist-sans/Geist-Regular.woff2")
SANS_MED = Font(FONTS_DIR / "geist-sans/Geist-Medium.woff2")


def text(font, s, size, x, y, fill, tracking=0.0, anchor="start"):
    if anchor == "end":
        x -= font.width(s, size, tracking)
    return f'<path fill="{fill}" d="{font.path(s, size, x, y, tracking)}"/>'


def rule(y, c):
    return f'<rect x="0" y="{y}" width="{W}" height="1" fill="{c["line"]}"/>'


def heading(c, label, note=None):
    out = text(SANS_MED, label, 20, 0, 40, c["fg"], -0.02)
    if note:
        out += text(SANS, note, 15, W, 40, c["muted"], -0.005, "end")
    return out + rule(64, c)


# ---------- output ----------
FILES = {}  # (name, theme) -> filename; content hash in the name busts GitHub's camo cache


def svg(name, h, body, title):
    title = escape(title)
    for theme, c in THEMES.items():
        doc = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{h}" viewBox="0 0 {W} {h}" '
               f'role="img" aria-label="{title}"><title>{title}</title>{body(c)}</svg>\n')
        fn = f"{name}-{theme}-{hashlib.sha1(doc.encode()).hexdigest()[:8]}.svg"
        (OUT / fn).write_text(doc)
        FILES[(name, theme)] = fn


# ---------- sections ----------
def hero(c):
    out = [text(SANS_MED, "dekrezz", 30, 0, 31, c["fg"], -0.03), rule(68, c)]
    y = 156
    for line in ["Agent infrastructure,", "MCP tooling & dev tools."]:
        out.append(text(SANS, line, 54, -2, y, c["fg"], -0.045))
        y += 60
    y += 8
    for line in ["I build tools for coding agents — orchestration, MCP servers, voice and",
                 "desktop utilities. Ship fast, verify everything."]:
        out.append(text(SANS, line, 18, 0, y, c["muted"], -0.01))
        y += 28
    return "".join(out)


def stats_svg(st):
    cells = [
        (f"{st['commits']:,}", "Commits"),
        (f"{st['contributions']:,}", "Contributions this year"),
        (f"{st['prs']:,}", "Pull requests"),
        (f"{st['repos']:,}", "Repositories"),
    ]
    cw = W / len(cells)

    def body(c):
        out = [heading(c, "Numbers", "Public and private, combined")]
        for i, (num, label) in enumerate(cells):
            x = i * cw + (24 if i else 0)
            if i:
                out.append(f'<rect x="{i * cw:.1f}" y="64" width="1" height="120" fill="{c["line"]}"/>')
            out.append(text(SANS, num, 48, x - 2, 136, c["fg"], -0.045))
            out.append(text(SANS, label, 15, x, 166, c["muted"], -0.005))
        out.append(rule(184, c))
        return "".join(out)

    svg("stats", 185, body, "Numbers: " + ", ".join(f"{n} {l.lower()}" for n, l in cells) + " (public and private combined)")


# GitHub language name -> simple-icons slug
ICON = {
    "TypeScript": "typescript", "JavaScript": "javascript", "Swift": "swift", "Shell": "gnubash",
    "CSS": "css", "Rust": "rust", "HTML": "html5", "PLpgSQL": "postgresql", "Go": "go",
    "Python": "python", "Ruby": "ruby", "Makefile": "gnu", "Kotlin": "kotlin", "C": "c",
    "C++": "cplusplus", "Lua": "lua", "Dockerfile": "docker", "Vue": "vuedotjs", "Svelte": "svelte",
    "Zig": "zig", "Java": "openjdk", "C#": "dotnet", "PHP": "php", "Dart": "dart", "Nix": "nixos",
}


def icon_path(lang):
    slug = ICON.get(lang)
    if slug is None:
        raise KeyError(f"no icon mapped for language {lang!r}: add it to ICON")
    return re.search(r'<path d="([^"]+)"', (ICONS_DIR / f"{slug}.svg").read_text()).group(1)


def langs_svg(langs, top=8):
    total = sum(langs.values())
    items = [(k, v / total * 100) for k, v in langs.most_common(top)]
    cols, rh, bar_y = 4, 56, 92
    cw = W / cols
    rows = -(-len(items) // cols)
    h = bar_y + 6 + 32 + rows * rh

    def body(c):
        out = [heading(c, "Languages", "By bytes of code across all repositories")]
        # proportional bar, segments fade with rank
        x, shown = 0.0, sum(p for _, p in items)
        for i, (_, pct) in enumerate(items):
            w = W * pct / shown
            out.append(f'<rect x="{x:.1f}" y="{bar_y}" width="{max(w - 3, 2):.1f}" height="6" rx="3" '
                       f'fill="{c["fg"]}" opacity="{max(0.18, 1 - i * 0.13):.2f}"/>')
            x += w
        for i, (name, pct) in enumerate(items):
            x0, y0 = (i % cols) * cw, bar_y + 6 + 32 + (i // cols) * rh
            out.append(f'<g transform="translate({x0} {y0}) scale({22 / 24})" fill="{c["fg"]}"><path d="{icon_path(name)}"/></g>')
            out.append(text(SANS_MED, name, 16, x0 + 34, y0 + 16, c["fg"], -0.01))
            nx = x0 + 34 + SANS_MED.width(name, 16, -0.01) + 8
            out.append(text(SANS, f"{pct:.1f}%", 15, nx, y0 + 16, c["muted"], -0.005))
        out.append(rule(h - 1, c))
        return "".join(out)

    svg("languages", h, body, "Languages: " + ", ".join(f"{n} {p:.1f}%" for n, p in items))


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
            rule(91, c),
        ])
    svg(f"work-{name.lower()}", 92, body, f"{name} — {desc}")


# ---------- build ----------
stats = fetch_stats()
OUT.mkdir(parents=True, exist_ok=True)
for old in OUT.glob("*.svg"):
    old.unlink()

svg("hero", 340, hero, "dekrezz — Agent infrastructure, MCP tooling and dev tools")
stats_svg(stats)
langs_svg(stats["langs"])
svg("projects", 65, lambda c: heading(c, "Projects"), "Projects")
for p in PROJECTS:
    project(*p)

BASE = f"https://raw.githubusercontent.com/{USER}/{USER}/main/assets"


def pic(name, alt):
    return (f'<picture>\n  <source media="(prefers-color-scheme: dark)" srcset="{BASE}/{FILES[(name, "dark")]}" />\n'
            f'  <img src="{BASE}/{FILES[(name, "light")]}" width="100%" alt="{escape(alt)}" />\n</picture>')


parts = [
    pic("hero", "dekrezz — agent infrastructure, MCP tooling and dev tools"), "",
    pic("stats", "Commits, contributions, pull requests and repositories"), "", "<br />", "",
    pic("languages", "Languages"), "", "<br />", "",
    pic("projects", "Projects"), "",
]
for name, desc in PROJECTS:
    parts += [f'<a href="https://github.com/{USER}/{name}">\n{pic(f"work-{name.lower()}", f"{name} — {desc}")}\n</a>', ""]
README.write_text("\n".join(parts))
print("ok", {k: v for k, v in stats.items() if k != "langs"})
