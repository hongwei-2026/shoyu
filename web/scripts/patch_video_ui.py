# -*- coding: utf-8 -*-
from pathlib import Path
import re

NEW = """      <section id="view-video" class="view" aria-labelledby="lbl-video">
        <h2 class="view-title" id="lbl-video">上传手语视频</h2>
        <p class="lede">先上传；<strong>左侧整段识别</strong>是主结果，<strong>右侧边播</strong>仅作预览（分段只用本地 ONNX）。识别方式请自行选择。</p>

        <div class="card video-setup-card">
          <label class="upload-zone">
            <span class="upload-icon" aria-hidden="true">⬆</span>
            <span class="field-label">选择视频文件</span>
            <input type="file" id="fileVideo" accept="video/*" class="visually-hidden" />
            <span id="filePickLabel" class="muted">未选择文件</span>
          </label>
          <p class="status-line" id="uploadStatus"></p>
          <div class="btn-row">
            <button type="button" class="btn btn-primary" id="btnUpload">上传视频</button>
          </div>
          <div class="video-settings-row">
            <label class="field">
              <span class="field-label">手语模型</span>
              <div class="model-quick-pick" role="group" aria-label="手语语种">
                <button type="button" class="btn btn-quiet model-quick-pick-btn is-active" data-target="video" data-lang="zh">中文</button>
                <button type="button" class="btn btn-quiet model-quick-pick-btn" data-target="video" data-lang="en">英文</button>
              </div>
              <select id="modelSelect" class="input-lg" aria-describedby="modelHintVideo">
                <optgroup label="中文手语">
                  <option value="openesl" selected>OpenESL/VECSL</option>
                  <option value="csl_daily">CSL-Daily</option>
                </optgroup>
                <optgroup label="英文手语">
                  <option value="openasl">OpenASL</option>
                  <option value="how2sign">How2Sign</option>
                </optgroup>
              </select>
            </label>
            <label class="field">
              <span class="field-label">识别方式</span>
              <select id="recognitionMode" class="input-lg" aria-describedby="recognitionModeHint">
                <option value="onnx" selected>仅本地 ONNX（默认）</option>
                <option value="ocr">仅画面字幕 OCR（有硬字幕时）</option>
                <option value="hybrid">混合（ONNX + OCR + Kimi + DeepSeek）</option>
              </select>
            </label>
          </div>
          <p id="modelHintVideo" class="model-hint field-hint" aria-live="polite"></p>
          <p id="recognitionModeHint" class="field-hint">带底部硬字幕的新闻/教程可试「仅 OCR」或「混合」；标准手语拍摄用 ONNX。边播预览固定 ONNX，不走云端。</p>
        </div>

        <div class="layout-split video-layout-split">
          <div class="card video-col-full">
            <h3 class="card-title">整段识别 · 主结果</h3>
            <label class="check"><input type="checkbox" id="chkJobHistory" checked /> 记入「记录」</label>
            <label class="check"><input type="checkbox" id="videoJobSpeak" /> 完成后朗读</label>
            <button type="button" class="btn btn-accent btn-block" id="btnRunVideoJob" disabled>开始整段识别</button>
            <p class="status-line" id="jobStatus"></p>
            <p class="field-label video-result-label">识别结果</p>
            <div id="jobResult" class="result-box result-box--main" role="status" aria-live="polite">识别完成后，文字会显示在这里</div>
            <details id="jobMetaDetails" class="recognition-meta" hidden>
              <summary>技术详情（OCR / ONNX / 混合说明）</summary>
              <p id="jobBurnedSubtitle" class="result-box result-box--subtitle" hidden></p>
              <p id="jobHybridDetail" class="field-hint job-hybrid-detail" hidden></p>
              <p id="jobQualityNote" class="field-hint job-quality-note" hidden></p>
            </details>
            <p id="jobError" class="error-line" hidden></p>
          </div>

          <div class="card video-col-rt">
            <h3 class="card-title">边播边出字 · 预览</h3>
            <p class="lede small muted">分段本地识别，可能漏句；正式结果以左侧为准。</p>
            <video id="videoFilePreview" class="preview-video" playsinline controls muted></video>
            <label class="field">
              <span class="field-label">每段时长（秒）</span>
              <input id="videoSliceMs" class="input-lg" type="number" value="5000" min="4000" max="8000" step="500" />
            </label>
            <label class="check"><input type="checkbox" id="videoRtAppendHistory" /> 每段记入「记录」</label>
            <label class="check"><input type="checkbox" id="videoRtSpeak" /> 每段朗读</label>
            <div class="btn-row">
              <button type="button" class="btn btn-primary btn-block" id="btnVideoRtStart">开始边播</button>
              <button type="button" class="btn btn-danger btn-block" id="btnVideoRtStop" disabled>停止</button>
            </div>
            <p class="status-line" id="videoRtStatus"></p>
            <p id="videoSubtitleCurrent" class="rt-current" role="status" aria-live="polite"></p>
            <div id="videoSubtitleLines" class="rt-lines log-box" role="log" aria-relevant="additions"></div>
          </div>
        </div>

        <details class="card video-manual-card">
          <summary class="card-title">补录 / 手写保存</summary>
          <p class="lede small">漏掉的句子可手写或打字后存进「记录」。</p>
          <div class="handwrite-canvas-wrap handwrite-canvas-wrap--compact">
            <canvas id="manualHandCanvas" class="handwrite-canvas" width="480" height="160" aria-label="手写区"></canvas>
          </div>
          <div class="btn-row handwrite-actions">
            <button type="button" class="btn btn-primary" id="btnManualHandRecognize">识别填入</button>
            <button type="button" class="btn btn-quiet" id="btnManualHandClear">清空</button>
          </div>
          <label class="field">
            <span class="field-label">写下来的话</span>
            <textarea id="manualText" class="input-lg" rows="3" required></textarea>
          </label>
          <label class="field">
            <span class="field-label">备注（可不填）</span>
            <input id="manualNote" class="input-lg" maxlength="500" />
          </label>
          <button type="button" class="btn btn-primary btn-block" id="btnSaveManual">存到记录</button>
        </details>

      </section>
"""

def main() -> None:
    new = NEW.replace("<motion ", "<TAG ").replace("</motion>", "</TAG>")
    new = new.replace("TAG", "motion")
    new = re.sub(r"</?motion\b[^>]*>", lambda m: m.group(0).replace("motion", "motion"), new)
    # final fix: motion -> div
    new = new.replace("motion", "div")
    if "motion" in new:
        raise SystemExit("still has motion tags")
    p = Path(__file__).resolve().parents[1] / "web" / "static" / "index.html"
    text = p.read_text(encoding="utf-8")
    start = text.index('      <section id="view-video"')
    end = text.index('      <section id="view-history"')
    p.write_text(text[:start] + new + text[end:], encoding="utf-8")
    print("patched video section", len(new))


if __name__ == "__main__":
    main()
