# -*- coding: utf-8 -*-
from pathlib import Path

p = Path(__file__).resolve().parents[1] / "web" / "static" / "index.html"
text = p.read_text(encoding="utf-8")
marker_start = '            <label class="field">\n              <span class="field-label">识别方式</span>'
marker_end = '      </section>\n<section id="view-history"'
start = text.index(marker_start)
end = text.index(marker_end)
new = Path(__file__).with_name("_video_ui_snippet.html").read_text(encoding="utf-8")
p.write_text(text[:start] + new + text[end:], encoding="utf-8")
print("patched ok")
