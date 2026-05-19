# -*- coding: utf-8 -*-
from pathlib import Path

p = Path(__file__).resolve().parents[1] / "web" / "static" / "index.html"
t = p.read_text(encoding="utf-8")

old = """          <div class="card video-col-full">
            <h3 class="card-title">����ʶ�� �� �����</h3>
            <label class="check"><input type="checkbox" id="chkJobHistory" checked /> ���롸��¼��</label>
            <label class="check"><input type="checkbox" id="videoJobSpeak" /> ��ɺ��ʶ�</label>
            <button type="button" class="btn btn-accent btn-block" id="btnRunVideoJob" disabled>��ʼ����ʶ��</button>
            <p class="status-line" id="jobStatus"></p>
            <p class="field-label video-result-label">ʶ����</p>
            <div id="jobResult" class="result-box result-box--main" role="status" aria-live="polite">ʶ����ɺ����ֻ���ʾ������</div>"""

new = """          <motion class="card video-col-full video-col-compact">
            <h3 class="card-title">����ʶ�� �� �����</h3>
            <motion class="video-inline-opts">
              <label class="check"><input type="checkbox" id="chkJobHistory" checked /> ���롸��¼��</label>
              <span class="video-speak-label">��ɺ��ʶ�</span>
              <label class="check"><input type="checkbox" id="videoJobSpeakBrowser" /> ����</label>
              <label class="check"><input type="checkbox" id="videoJobSpeakMinimax" /> MiniMax</label>
            </motion>
            <button type="button" class="btn btn-accent btn-block" id="btnRunVideoJob" disabled>��ʼ����ʶ��</button>
            <p class="status-line" id="jobStatus"></p>
            <motion class="video-result-panel">
              <p class="field-label video-result-label">ʶ����</p>
              <motion id="jobResult" class="result-box result-box--main" role="status" aria-live="polite">ʶ����ɺ����ֻ���ʾ������</motion>
            </motion>"""

new = new.replace("motion", "X").replace("X", "div")

if old not in t:
    raise SystemExit("old block not found")
t = t.replace(old, new, 1)

old2 = """            <label class="check"><input type="checkbox" id="videoRtAppendHistory" /> ÿ�μ��롸��¼��</label>
            <label class="check"><input type="checkbox" id="videoRtSpeak" /> ÿ���ʶ�</label>"""

new2 = """            <label class="check"><input type="checkbox" id="videoRtAppendHistory" /> ÿ�μ��롸��¼��</label>
            <span class="video-speak-label">ÿ���ʶ�</span>
            <label class="check"><input type="checkbox" id="videoRtSpeakBrowser" /> ����</label>
            <label class="check"><input type="checkbox" id="videoRtSpeakMinimax" /> MiniMax</label>"""

if old2 not in t:
    raise SystemExit("rt block not found")
t = t.replace(old2, new2, 1)

t = t.replace('class="card video-col-rt"', 'class="card video-col-rt video-col-compact"', 1)
t = t.replace("app.js?v=hybrid7", "app.js?v=hybrid8")

p.write_text(t, encoding="utf-8")
print("patched index.html")
