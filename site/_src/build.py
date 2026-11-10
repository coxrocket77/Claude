"""Assemble inner pages from index.html's shared shell (head, icon sprite, header, footer).

Run from anywhere:  python3 site/_src/build.py
Edit page bodies in _src/*.main.html, then rebuild.
"""
from pathlib import Path
import re

SITE = Path(__file__).resolve().parent.parent
index = (SITE / "index.html").read_text(encoding="utf-8")

head_end = index.index("<main id=\"main\">")
foot_start = index.index("</main>")
shell_top, shell_bottom = index[:head_end], index[foot_start:]

PAGES = {
    "services": {
        "title": "Construction Services in Dallas–Fort Worth | Extreme Construction &amp; Rehab",
        "desc": "Commercial build-outs, apartment rehab, home remodeling, roofing, and licensed trades across DFW. Fixed, itemized bids. Free site walkthrough: (214) 559-5799.",
        "nav": "services.html",
    },
    "about": {
        "title": "About Us | Extreme Construction &amp; Rehab, Addison TX Since 1991",
        "desc": "An Addison, Texas contractor building and renovating across Dallas–Fort Worth since 1991. One team, honest pricing, and work we stand behind.",
        "nav": "about.html",
    },
}

for name, meta in PAGES.items():
    top = shell_top
    top = re.sub(r"<title>.*?</title>", f"<title>{meta['title']}</title>", top, flags=re.S)
    top = re.sub(r'(<meta name="description" content=")[^"]*', r"\g<1>" + meta["desc"], top)
    top = top.replace('href="https://extremec.com/"', f'href="https://extremec.com/{name}.html"', 1)
    # Same-page anchors in the header point back to the homepage
    for anchor in ("#work", "#faq", "#quote"):
        top = top.replace(f'href="{anchor}"', f'href="index.html{anchor}"')
    top = top.replace(f'<a href="{meta["nav"]}">', f'<a href="{meta["nav"]}" aria-current="page">')
    bottom = shell_bottom.replace('href="#quote"', 'href="index.html#quote"')
    body = (SITE / "_src" / f"{name}.main.html").read_text(encoding="utf-8")
    (SITE / f"{name}.html").write_text(top + '<main id="main">\n' + body + "\n" + bottom, encoding="utf-8")
    print("built", name + ".html")
