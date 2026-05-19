# -*- coding: utf-8 -*-
from pathlib import Path

p = Path(__file__).resolve().parents[1] / "web" / "static" / "index.html"
text = p.read_text(encoding="utf-8")
start = text.index('      <section id="view-video"')
end = text.index('      <section id="view-history"')
new_section = Path(__file__).resolve().parent / "_view_video_section.html"
new = new_section.read_text(encoding="utf-8")
p.write_text(text[:start] + new + text[end:], encoding="utf-8")
print("video section rebuilt", len(new))
