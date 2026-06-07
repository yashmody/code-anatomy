"""render_runbook — turn a filled Excel runbook template into a STATIC page.

Content-author flow for runbooks (reliable, static — no API, no DB):

    1. Download the template:  GET /api/runbooks/template  (or backend/data/runbook-template.xlsx)
    2. Fill the 'Runbook' (metadata) + 'Content' (phases→sections→tasks) sheets.
    3. Publish it:
         cd backend && python -m scripts.render_runbook /path/to/filled.xlsx
       → writes  resources/runbooks/<slug>.html  and rebuilds  resources/runbooks/index.html

The page is served statically at /resources/runbooks/<slug>.html and listed on the
landing. Reuses the runbooks parser (Excel → structured tree) so the template
layout is the single contract.
"""
import html
import re
import sys
from pathlib import Path

sys.path.append(__import__("os").path.abspath(__import__("os").path.join(__import__("os").path.dirname(__file__), "..")))

from app.modules.runbooks.parser import parse_excel

RB_DIR = Path(__file__).resolve().parents[1].parent / "resources" / "runbooks"
LOGO = "https://www.deptagency.com/wp-content/uploads/2025/10/logo-dept.svg"

CSS = """
:root{--paper:#fff;--paper-2:#f6f5f1;--ink:#0a0a0a;--ink-soft:#3f3f3f;--ink-faint:#6f6f6f;
--rule:#e6e3dc;--card:#fff;--ochre:#FF4900;--ochre-deep:#cc3a00;--serif:'Syne',serif;
--sans:'DM Sans',system-ui,sans-serif;--mono:'JetBrains Mono',monospace;}
html[data-theme="dark"]{--paper:#080808;--paper-2:#131211;--ink:#fff;--ink-soft:#cfcdc8;
--ink-faint:#8a8780;--rule:#2a2825;--card:#0e0d0c;--ochre-deep:#FFA279;}
*{margin:0;padding:0;box-sizing:border-box}html{scroll-behavior:smooth}
body{font-family:var(--sans);background:var(--paper);color:var(--ink);line-height:1.6;font-size:15px}
a{color:var(--ink)}
.brand-bar{position:sticky;top:0;z-index:50;background:var(--paper);border-bottom:1px solid var(--rule);display:flex;align-items:center;gap:14px;padding:13px 28px}
.brand-bar .back{font-family:var(--mono);font-size:11px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;color:var(--ink-soft);border:1px solid var(--rule);padding:7px 12px;text-decoration:none}
.brand-bar .back:hover{border-color:var(--ochre);color:var(--ochre)}
.brand-bar img{height:30px}html[data-theme="dark"] .brand-bar img{filter:invert(1)}
.brand-bar .tag{font-family:var(--mono);font-size:10.5px;letter-spacing:.14em;text-transform:uppercase;color:var(--ink-soft);font-weight:700}
.brand-bar .spacer{flex:1}
.tt{background:transparent;border:1px solid var(--rule);padding:7px 12px;font-family:var(--mono);font-size:10.5px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:var(--ink);cursor:pointer}
.tt:hover{border-color:var(--ochre);color:var(--ochre)}
main{max-width:900px;margin:0 auto;padding:48px 28px 90px}
.eyebrow{font-family:var(--mono);font-size:11px;letter-spacing:.16em;text-transform:uppercase;color:var(--ochre-deep);font-weight:700;margin-bottom:12px}
h1{font-family:var(--serif);font-weight:800;font-size:40px;line-height:1.04;margin-bottom:12px}
.lede{font-size:16px;color:var(--ink-soft);max-width:62ch;margin-bottom:18px}
.meta{display:flex;flex-wrap:wrap;gap:18px;font-family:var(--mono);font-size:10.5px;letter-spacing:.08em;text-transform:uppercase;color:var(--ink-faint);border-top:1px solid var(--rule);padding-top:16px;margin-bottom:8px}
.meta b{color:var(--ochre)}
.phase{margin-top:40px}
.phase>h2{font-family:var(--serif);font-weight:800;font-size:27px;border-left:4px solid var(--ochre);padding-left:14px;margin-bottom:6px}
.phase>.pd{color:var(--ink-soft);padding-left:18px;margin-bottom:14px}
.section{margin:22px 0 0 0;padding-left:18px}
.section>h3{font-family:var(--mono);font-size:12px;letter-spacing:.12em;text-transform:uppercase;color:var(--ink);margin-bottom:4px}
.section>.sd{color:var(--ink-soft);font-size:14px;margin-bottom:12px}
.task{background:var(--card);border:1px solid var(--rule);border-left:3px solid var(--ochre);padding:16px 20px;margin:12px 0}
.task h4{font-family:var(--serif);font-weight:700;font-size:18px;margin-bottom:6px}
.task .td{color:var(--ink-soft);font-size:14px;margin-bottom:10px}
.task .tmeta{font-family:var(--mono);font-size:10.5px;color:var(--ink-faint);text-transform:uppercase;letter-spacing:.06em;margin-bottom:10px}
.task .tmeta b{color:var(--ochre)}
.task ul{list-style:none;margin:8px 0}
.task ul.steps li{position:relative;padding-left:20px;margin:6px 0;font-size:14px;color:var(--ink-soft)}
.task ul.steps li::before{content:"→";color:var(--ochre);position:absolute;left:0;font-weight:700}
.task ul.check li{position:relative;padding-left:24px;margin:6px 0;font-size:14px;color:var(--ink-soft)}
.task ul.check li::before{content:"\\2610";color:var(--ochre);position:absolute;left:0;font-size:15px}
.task .links a{display:inline-block;margin:6px 10px 0 0;font-family:var(--mono);font-size:11px;color:var(--ochre-deep);text-decoration:none}
.task .links a:hover{text-decoration:underline}
.foot{font-family:var(--mono);font-size:11px;color:var(--ink-faint);text-align:center;padding:40px 0 0;border-top:1px solid var(--rule);margin-top:48px}
.cards{display:grid;gap:16px}
.card{display:block;background:var(--card);border:1px solid var(--rule);border-left:3px solid var(--ochre);padding:22px 24px;text-decoration:none}
.card:hover{box-shadow:6px 6px 0 var(--ochre)}
.card-title{font-family:var(--serif);font-weight:800;font-size:21px;margin-bottom:7px}
.card-desc{color:var(--ink-soft);font-size:14.5px;margin-bottom:14px}
.card-meta{font-family:var(--mono);font-size:11px;color:var(--ink-faint);display:flex;justify-content:space-between}
.card-meta .arrow{color:var(--ochre);font-size:16px}
"""


def shell(title, body, back_href="/resources/runbooks/", back_label="← Runbooks", desc=""):
    meta_desc = f'<meta name="rb-desc" content="{html.escape(desc)}">' if desc else ""
    return f"""<!DOCTYPE html>
<html lang="en" data-theme="light">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{html.escape(title)} · DEPT®</title>
{meta_desc}
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Syne:wght@700;800&family=DM+Sans:wght@400;500;700&family=JetBrains+Mono:wght@400;500;700&display=swap" rel="stylesheet">
<script src="/resources/theme-boot.js"></script>
<style>{CSS}</style>
</head>
<body>
<header class="brand-bar">
  <a href="{back_href}" class="back">{back_label}</a>
  <a href="/app/"><img src="{LOGO}" alt="DEPT®"></a>
  <span class="tag">Anatomy of Code</span><span class="spacer"></span>
  <button class="tt" type="button" onclick="window.toggleAppTheme && window.toggleAppTheme()">Theme</button>
</header>
<main>
{body}
<div class="foot">DEPT® · Anatomy of Code — field runbooks</div>
</main>
</body>
</html>
"""


def _task_html(t):
    parts = [f"<h4>{html.escape(t.title)}</h4>"]
    if t.description:
        parts.append(f'<div class="td">{html.escape(t.description)}</div>')
    tm = []
    if t.owner:  tm.append(f"<b>Owner</b> {html.escape(t.owner)}")
    if t.timing: tm.append(f"<b>When</b> {html.escape(t.timing)}")
    if t.tools:  tm.append("<b>Tools</b> " + html.escape(", ".join(t.tools)))
    if tm:
        parts.append(f'<div class="tmeta">{" &nbsp;·&nbsp; ".join(tm)}</div>')
    if t.steps:
        parts.append('<ul class="steps">' + "".join(f"<li>{html.escape(s)}</li>" for s in t.steps) + "</ul>")
    if t.checklist:
        parts.append('<ul class="check">' + "".join(f"<li>{html.escape(c)}</li>" for c in t.checklist) + "</ul>")
    if t.links:
        safe = [l for l in t.links if str(l.url).startswith(("http://", "https://", "/"))]
        if safe:
            parts.append('<div class="links">' + "".join(
                f'<a href="{html.escape(l.url)}" rel="noopener">{html.escape(l.label or l.url)} ↗</a>' for l in safe) + "</div>")
    if t.notes:
        parts.append(f'<div class="td"><em>{html.escape(t.notes)}</em></div>')
    return f'<div class="task">{"".join(parts)}</div>'


def render(rc) -> str:
    body = [f'<div class="eyebrow">Runbook</div><h1>{html.escape(rc.title)}</h1>']
    if rc.description:
        body.append(f'<p class="lede">{html.escape(rc.description)}</p>')
    body.append(f'<div class="meta"><span><b>Role</b> {html.escape(rc.role)}</span>'
                f'<span><b>Domain</b> {html.escape(rc.domain)}</span>'
                f'<span><b>Type</b> {html.escape(rc.type)}</span></div>')
    for ph in rc.phases:
        body.append('<section class="phase">')
        body.append(f"<h2>{html.escape(ph.title)}</h2>")
        if ph.description:
            body.append(f'<div class="pd">{html.escape(ph.description)}</div>')
        for sec in ph.sections:
            body.append('<div class="section">')
            body.append(f"<h3>{html.escape(sec.title)}</h3>")
            if sec.description:
                body.append(f'<div class="sd">{html.escape(sec.description)}</div>')
            for t in sec.tasks:
                body.append(_task_html(t))
            body.append("</div>")
        body.append("</section>")
    return shell(rc.title, "\n".join(body), desc=(rc.description or ""))


def regen_index():
    """Rebuild resources/runbooks/index.html from every *.html page present."""
    cards = []
    for f in sorted(RB_DIR.glob("*.html")):
        if f.name == "index.html":
            continue
        txt = f.read_text(encoding="utf-8")
        tm = re.search(r"<title>(.*?)(?:\s·\sDEPT®)?</title>", txt, re.S)
        dm = re.search(r'<meta name="rb-desc" content="([^"]*)"', txt)
        title = html.unescape((tm.group(1) if tm else f.stem).strip())
        desc = html.unescape(dm.group(1)) if dm else ""
        cards.append(f"""<a class="card" href="{f.name}">
  <div class="card-title">{html.escape(title)}</div>
  <div class="card-desc">{html.escape(desc)}</div>
  <div class="card-meta"><span>Runbook</span><span class="arrow">→</span></div>
</a>""")
    body = (f'<div class="eyebrow">Resources · Runbooks</div><h1>Engagement Runbooks</h1>'
            f'<p class="lede">Step-by-step runbooks for running a DEPT® Adobe engagement.</p>'
            f'<div class="cards">{"".join(cards)}</div>')
    (RB_DIR / "index.html").write_text(shell("Runbooks", body, back_href="/app/", back_label="← App"))


def main():
    if len(sys.argv) < 2:
        sys.exit("usage: python -m scripts.render_runbook <filled-template.xlsx>")
    path = Path(sys.argv[1])
    if not path.exists():
        sys.exit(f"[render_runbook] file not found: {path}")
    rc = parse_excel(path.read_bytes())
    out = RB_DIR / f"{rc.slug}.html"
    out.write_text(render(rc))
    print(f"[render_runbook] wrote {out.relative_to(RB_DIR.parents[1])}  ({rc.title})")
    regen_index()
    print("[render_runbook] rebuilt resources/runbooks/index.html")


if __name__ == "__main__":
    main()
