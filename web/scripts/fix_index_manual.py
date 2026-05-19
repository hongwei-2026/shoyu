# -*- coding: utf-8 -*-
from pathlib import Path

p = Path(__file__).resolve().parents[1] / "web" / "static" / "index.html"
t = p.read_text(encoding="utf-8")
t = t.replace("motion", "div")
dup = '<details class="card video-manual-card">'
if dup in t and "video-manual-inline" in t:
    i = t.index(dup)
    j = t.index("</details>", i) + len("</details>")
    t = t[:i] + t[j:]
p.write_text(t, encoding="utf-8")
print("fixed", dup in t)
