function formatApiDetail(data) {
  const d = data?.detail;
  if (typeof d === "string" && d.trim()) return d.trim();
  if (Array.isArray(d)) {
    const parts = d
      .map((x) => {
        if (typeof x === "string") return x;
        if (x && typeof x === "object" && x.msg) {
          const loc = Array.isArray(x.loc) ? x.loc.filter((p) => p !== "body").join(".") : "";
          return loc ? `${loc}：${x.msg}` : x.msg;
        }
        return "";
      })
      .filter(Boolean);
    if (parts.length) return parts.join("；");
  }
  if (d && typeof d === "object" && typeof d.msg === "string") return d.msg;
  if (data?.message) return String(data.message);
  return "";
}

const api = (path, opts = {}) => {
  const { signal, headers, ...rest } = opts;
  return fetch(path, {
    credentials: "include",
    headers: { "Content-Type": "application/json", ...(headers || {}) },
    signal,
    ...rest,
  })
    .catch((e) => {
      if (isAbortError(e) || opts.signal?.aborted) {
        const err = new Error("已停止");
        err.name = "AbortError";
        err.aborted = true;
        throw err;
      }
      throw e;
    })
    .then(async (r) => {
    const text = await r.text();
    let data;
    try {
      data = text ? JSON.parse(text) : null;
    } catch {
      data = { raw: text };
    }
    if (!r.ok) {
      let msg = formatApiDetail(data) || r.statusText;
      if (r.status === 503 && (!msg || msg === "Service Unavailable")) {
        msg =
          "服务未配置（503）。云语音需 MINIMAX_API_KEY，朗读翻译需 DEEPSEEK_API_KEY；请在项目根 .env 填写后重启 uvicorn。";
      }
      const where = path && path !== "/" ? ` [${path}]` : "";
      throw new Error(msg + where);
    }
    return data;
  });
};

/** 分场景取消轮询，避免边播与传视频整段任务互相 abort。 */
const jobPollControllers = {};

function takeJobPollSignal(scope = "full") {
  jobPollControllers[scope]?.abort();
  const ac = new AbortController();
  jobPollControllers[scope] = ac;
  return ac.signal;
}

function cancelJobPoll(scope) {
  const c = jobPollControllers[scope];
  if (c) {
    c.abort();
    delete jobPollControllers[scope];
  }
}

function cancelJobPolls(...scopes) {
  for (const s of scopes) cancelJobPoll(s);
}

function takeTranslatePollSignal() {
  return takeJobPollSignal("full");
}

function cancelActiveTranslatePoll() {
  cancelJobPoll("full");
}

function isAbortError(e) {
  const s = String(e?.message || e || "");
  return (
    e?.name === "AbortError" ||
    e?.aborted === true ||
    /signal is aborted/i.test(s) ||
    /aborted without reason/i.test(s) ||
    /the user aborted/i.test(s)
  );
}

function delay(ms, signal) {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) {
      reject(Object.assign(new Error("aborted"), { name: "AbortError" }));
      return;
    }
    const t = setTimeout(resolve, ms);
    const onAbort = () => {
      clearTimeout(t);
      reject(Object.assign(new Error("aborted"), { name: "AbortError" }));
    };
    signal?.addEventListener("abort", onAbort, { once: true });
  });
}

const $ = (sel) => document.querySelector(sel);

/** MiniMax `voice_id`，名称与官方「系统音色列表」一致：https://platform.minimaxi.com/docs/faq/system-voice-id */
const MINIMAX_VOICE_CHOICES = [
  { id: "female-tianmei", label: "中文·甜美女声" },
  { id: "female-chengshu", label: "中文·成熟女声" },
  { id: "female-shaonv", label: "中文·少女音" },
  { id: "female-yujie", label: "中文·御姐音" },
  { id: "Chinese (Mandarin)_Sweet_Lady", label: "中文·甜美女声（抒情）" },
  { id: "Chinese (Mandarin)_News_Anchor", label: "中文·新闻女声" },
  { id: "Chinese (Mandarin)_HK_Flight_Attendant", label: "中文·港式空姐" },
  { id: "male-qn-qingse", label: "中文·青涩青年男声" },
  { id: "Chinese (Mandarin)_Lyrical_Voice", label: "中文·抒情男声" },
  { id: "English_radiant_girl", label: "英文·清甜少女（正常音量，荐）" },
  { id: "English_LovelyGirl", label: "英文·可爱少女" },
  { id: "English_Graceful_Lady", label: "英文·Graceful Lady" },
  { id: "English_Whispering_girl", label: "英文·耳语少女（极轻，长句常听不清）" },
  { id: "English_Soft-spokenGirl", label: "英文·柔声少女" },
  { id: "English_Persuasive_Man", label: "英文·沉稳男声" },
];

/** 旧版误标：把「抒情男声」当成女声默认，自动迁到甜美女声 */
const MINIMAX_VOICE_LEGACY_MAP = {
  "Chinese (Mandarin)_Lyrical_Voice": "female-tianmei",
  "moss_audio_ce44fc67-7ce3-11f0-8de5-96e35d26fb85": "female-tianmei",
};

const MINIMAX_DEFAULT_VOICE_ID = "female-tianmei";
const MINIMAX_DEFAULT_VOICE_EN = "English_Graceful_Lady";
const MINIMAX_VOICES_ZH = MINIMAX_VOICE_CHOICES.filter((v) => !v.id.startsWith("English_"));
const MINIMAX_VOICES_EN = MINIMAX_VOICE_CHOICES.filter((v) => v.id.startsWith("English_"));

function normalizeSpeechLang(lang) {
  const l = String(lang || "zh-CN").trim().toLowerCase().replace("_", "-");
  if (l.startsWith("en")) return "en-US";
  if (l.startsWith("zh-tw") || l === "zh-hk") return "zh-TW";
  if (l.startsWith("zh")) return "zh-CN";
  return lang || "zh-CN";
}

/** 卡片标题留空时，用朗读正文前几字 */
function distillPhraseLabel(speakText) {
  const s = String(speakText || "").trim().replace(/\s+/g, " ");
  if (!s) return "常用语";
  return s.length > 24 ? `${s.slice(0, 23)}…` : s;
}

function phraseTileTitle(row) {
  const l = String(row?.label || "").trim();
  if (l) return l;
  return distillPhraseLabel(row?.speakText);
}

/** 左侧「朗读语言」：卡片「听」与点卡片朗读都跟随此项（不必每条重写） */
function currentComposerSpeechLang() {
  return normalizeSpeechLang($("#pLang")?.value || localStorage.getItem("ttsLang") || "zh-CN");
}

function voicesForLang(lang) {
  return normalizeSpeechLang(lang).toLowerCase().startsWith("en") ? MINIMAX_VOICES_EN : MINIMAX_VOICES_ZH;
}

/** 根据正文判断更适合中文还是英文朗读（看汉字 vs 拉丁字母比例） */
function detectTextLang(text) {
  const t = String(text || "").trim();
  if (!t) return "zh-CN";
  let han = 0;
  let latin = 0;
  for (const ch of t) {
    const c = ch.codePointAt(0) || 0;
    if (c >= 0x4e00 && c <= 0x9fff) han += 1;
    else if (/[A-Za-z]/.test(ch)) latin += 1;
  }
  const sig = han + latin;
  if (!sig) return "zh-CN";
  if (han / sig >= 0.2) return "zh-CN";
  if (latin / sig >= 0.45) return "en-US";
  return "zh-CN";
}

let deepseekTranslateConfigured = false;
let kimiConfigured = false;
let zhipuConfigured = false;
let handwritingZhipuReady = false;
let hybridReady = false;

function ttsTranslateBeforeSpeak() {
  return localStorage.getItem("ttsTranslateBeforeSpeak") !== "0";
}

function speechLangMismatch(uiLang, text) {
  const ui = normalizeSpeechLang(uiLang);
  const fromText = detectTextLang(text);
  return (
    (ui.startsWith("en") && fromText.startsWith("zh")) ||
    (ui.startsWith("zh") && fromText.startsWith("en"))
  );
}

/**
 * 按「朗读语言」准备正文：不一致且开启翻译时走 DeepSeek，再交给 TTS。
 * @returns {Promise<{ text: string, lang: string, translated: boolean }>}
 */
async function prepareSpeechText(text, uiLang, opts = {}) {
  const t = String(text || "").trim();
  const ui = normalizeSpeechLang(uiLang);
  const fromText = detectTextLang(t);
  const notify = !!opts.notify;
  if (!speechLangMismatch(uiLang, t)) {
    return { text: t, lang: ui, translated: false };
  }
  const wantTranslate = opts.translate !== false && ttsTranslateBeforeSpeak();
  if (!wantTranslate) {
    if (notify) {
      showToast("朗读语言与正文不一致。请勾选「朗读前自动翻译」或改朗读语言。", "warn", 5500);
    }
    return { text: t, lang: fromText, translated: false };
  }
  if (!deepseekTranslateConfigured) {
    await refreshTtsStatus();
  }
  if (!deepseekTranslateConfigured) {
    if (notify) {
      showToast(
        "未检测到 DeepSeek 配置。请确认项目根目录 .env 有 DEEPSEEK_API_KEY、已重启 uvicorn，并 Ctrl+F5 强刷页面。",
        "warn",
        6500
      );
    }
    return { text: t, lang: fromText, translated: false };
  }
  const targetLang = ui.startsWith("en") ? "en-US" : "zh-CN";
  try {
    const r = await api("/api/speech/translate", {
      method: "POST",
      body: JSON.stringify({ text: t, targetLang }),
    });
    const out = String(r.text || "").trim();
    if (!out) throw new Error("翻译结果为空");
    if (notify) {
      const label = targetLang.startsWith("en") ? "已译为英文后朗读" : "已译为中文后朗读";
      const preview = out.length > 56 ? `${out.slice(0, 56)}…` : out;
      showToast(`${label}：${preview}`, "warn", 5200);
    }
    return { text: out, lang: targetLang, translated: true };
  } catch (e) {
    if (notify) {
      showToast(`${e?.message || "翻译失败"}；将按正文语种朗读。`, "error", 5500);
    }
    return { text: t, lang: fromText, translated: false };
  }
}

function phraseVoiceMatchesLang(voiceId, lang) {
  const v = String(voiceId || "").trim();
  if (!v) return true;
  const l = normalizeSpeechLang(lang).toLowerCase();
  if (l.startsWith("en")) return v.startsWith("English_");
  return !v.startsWith("English_");
}

function isChineseMinimaxVoiceId(voiceId) {
  const v = String(voiceId || "");
  if (!v || v.startsWith("English_")) return false;
  return (
    v.startsWith("female-") ||
    v.startsWith("male-qn") ||
    v.includes("Mandarin") ||
    v.includes("Cantonese") ||
    v.startsWith("Chinese ")
  );
}

function getBaseMinimaxVoiceFromUi(lang) {
  const speechLang = normalizeSpeechLang(lang);
  const list = voicesForLang(speechLang);
  const storageKey = speechLang.toLowerCase().startsWith("en") ? "ttsMinimaxVoiceEn" : "ttsMinimaxVoice";
  const sel = $("#ttsMinimaxVoice");
  let saved = resolveMinimaxVoiceId(localStorage.getItem(storageKey));
  if (!list.some((x) => x.id === saved)) {
    saved = speechLang.toLowerCase().startsWith("en") ? MINIMAX_DEFAULT_VOICE_EN : MINIMAX_DEFAULT_VOICE_ID;
  }
  if (sel?.value && list.some((x) => x.id === sel.value)) {
    saved = resolveMinimaxVoiceId(sel.value);
    localStorage.setItem(storageKey, saved);
  }
  return saved;
}

let minimaxAudioEl = null;
let ttsPlayQueue = Promise.resolve();
let lastMinimaxBlobUrl = null;

let modelCatalogCache = null;

function modelLabelForUser(key) {
  const fromCat = modelCatalogCache?.recognition?.find((m) => m.key === key);
  if (fromCat?.shortLabel) return fromCat.shortLabel;
  const m = {
    openesl: "中文·OpenESL",
    csl_daily: "中文·CSL-Daily",
    how2sign: "英文·How2Sign",
    openasl: "英文·OpenASL",
    wlasl_islr: "词级·WLASL",
  };
  return m[key] || "—";
}

function modelByKey(key) {
  return modelCatalogCache?.recognition?.find((m) => m.key === key) || null;
}

function appendModelOption(parent, m) {
  const opt = document.createElement("option");
  opt.value = m.key;
  let label = m.label;
  if (!m.selectable) label += "（网页暂未支持）";
  else if (!m.ready) label += "（模型未安装）";
  opt.textContent = label;
  opt.disabled = !m.selectable || (!m.ready && m.selectable);
  parent.appendChild(opt);
  return opt;
}

function fillModelSelect(selectEl, { includeWlasl = false, groupByLanguage = false, defaultLang = "" } = {}) {
  if (!selectEl || !modelCatalogCache?.recognition) return;
  const prev = selectEl.value;
  const items = modelCatalogCache.recognition.filter((m) => includeWlasl || m.selectable);
  selectEl.innerHTML = "";

  if (groupByLanguage) {
    const zhItems = items.filter((m) => m.language === "zh" && m.selectable);
    const enItems = items.filter((m) => m.language === "en" && m.selectable);
    const other = items.filter((m) => !m.selectable || (m.language !== "zh" && m.language !== "en"));

    const ogZh = document.createElement("optgroup");
    ogZh.label = "中文手语视频（输出中文）";
    zhItems.forEach((m) => appendModelOption(ogZh, m));
    selectEl.appendChild(ogZh);

    const ogEn = document.createElement("optgroup");
    ogEn.label = "英文手语视频（输出英文）";
    enItems.forEach((m) => appendModelOption(ogEn, m));
    selectEl.appendChild(ogEn);

    if (other.length) {
      const ogO = document.createElement("optgroup");
      ogO.label = "其他";
      other.forEach((m) => appendModelOption(ogO, m));
      selectEl.appendChild(ogO);
    }
  } else {
    items.forEach((m) => appendModelOption(selectEl, m));
  }

  if (prev && items.some((m) => m.key === prev)) {
    selectEl.value = prev;
  } else if (defaultLang === "zh") {
    const k = items.find((m) => m.defaultFor === "zh_video" && m.selectable)?.key || "openesl";
    selectEl.value = k;
  } else if (defaultLang === "en") {
    const k = items.find((m) => m.defaultFor === "en_video" && m.selectable)?.key || "openasl";
    selectEl.value = k;
  } else if (!selectEl.value && items.length) {
    const def =
      items.find((m) => m.defaultFor === "zh_video" && m.selectable) ||
      items.find((m) => m.defaultFor === "en_video" && m.selectable) ||
      items.find((m) => m.selectable);
    if (def) selectEl.value = def.key;
  }
}

function setVideoModelLang(lang) {
  const sel = $("#modelSelect");
  const hint = $("#modelHintVideo");
  if (!sel) return;
  fillModelSelect(sel, { includeWlasl: false, groupByLanguage: true, defaultLang: lang });
  updateModelHint(sel, hint);
  document.querySelectorAll(".model-quick-pick-btn").forEach((b) => {
    b.classList.toggle("is-active", b.dataset.lang === lang);
  });
}

function setLiveModelLang(lang) {
  const sel = $("#modelSelectLive");
  const hint = $("#modelHintLive");
  if (!sel) return;
  fillModelSelect(sel, { includeWlasl: false, groupByLanguage: true, defaultLang: lang });
  updateModelHint(sel, hint);
  document.querySelectorAll(".model-quick-pick-btn[data-target='live']").forEach((b) => {
    b.classList.toggle("is-active", b.dataset.lang === lang);
  });
}

function updateModelHint(selectEl, hintEl) {
  if (!hintEl) return;
  const m = modelByKey(selectEl?.value);
  if (!m) {
    hintEl.textContent = modelCatalogCache?.frameworkNote || "";
    return;
  }
  const parts = [m.taskLabel, m.useWhen];
  if (m.fallbackNote) parts.push(m.fallbackNote);
  if (!m.ready && m.selectable) parts.push("模型文件未就绪，请将 ONNX 压缩包放入 models/ 后重启服务。");
  if (!m.selectable) parts.push("当前页面仅支持连续整句识别，词级 WLASL 请查阅「模型」说明。");
  hintEl.textContent = parts.filter(Boolean).join(" ");
}

function bindModelSelect(selectId, hintId, opts) {
  const sel = $(selectId);
  const hint = $(hintId);
  if (!sel) return;
  fillModelSelect(sel, opts);
  updateModelHint(sel, hint);
  if (!sel.dataset.modelBound) {
    sel.dataset.modelBound = "1";
    sel.addEventListener("change", () => updateModelHint(sel, hint));
  }
}

document.querySelectorAll(".model-quick-pick-btn[data-target='video']").forEach((btn) => {
  btn.addEventListener("click", () => setVideoModelLang(btn.dataset.lang || "zh"));
});
document.querySelectorAll(".model-quick-pick-btn[data-target='live']").forEach((btn) => {
  btn.addEventListener("click", () => setLiveModelLang(btn.dataset.lang || "zh"));
});

function renderModelsGuide() {
  const intro = $("#modelsGuideIntro");
  const dep = $("#modelsGuideDeployed");
  const ref = $("#modelsGuideReference");
  if (!modelCatalogCache || !intro || !dep || !ref) return;
  intro.textContent = `${modelCatalogCache.frameworkNote} ${modelCatalogCache.openeslVsOpenasl}`;
  dep.innerHTML = "";
  const h3 = document.createElement("h3");
  h3.className = "models-guide-heading";
  h3.textContent = "本应用已部署（Uni-Sign ONNX）";
  dep.appendChild(h3);
  const ul = document.createElement("ul");
  ul.className = "dialog-list";
  for (const m of modelCatalogCache.recognition) {
    const li = document.createElement("li");
    const status = m.ready ? "已安装" : "未安装";
    const use = m.selectable ? "可在拍视频/传视频中选择" : "仅文档/备查";
    li.innerHTML = `<strong>${escapeHtml(m.label)}</strong>（${escapeHtml(m.framework)} · ${escapeHtml(
      m.dataset
    )}）— ${escapeHtml(m.taskLabel)}。${escapeHtml(m.useWhen)} <span class="muted">[${status} · ${use}]</span>`;
    ul.appendChild(li);
  }
  dep.appendChild(ul);
  ref.innerHTML = "";
  const h3r = document.createElement("h3");
  h3r.className = "models-guide-heading";
  h3r.textContent = "参考项目（未接入或仅索引）";
  ref.appendChild(h3r);
  const ulr = document.createElement("ul");
  ulr.className = "dialog-list";
  for (const t of modelCatalogCache.reference || []) {
    const li = document.createElement("li");
    const deployed =
      t.deployed === true ? "已用于本应用" : t.deployed === "partial" ? "部分（词级 ONNX）" : "未接入";
    let note = t.note ? ` ${t.note}` : "";
    li.innerHTML = `<strong>${escapeHtml(t.name)}</strong>：${escapeHtml(t.role)}。${escapeHtml(
      deployed
    )}.${escapeHtml(note)} <button type="button" class="btn btn-quiet btn-inline" data-doc-id="${escapeHtml(
      t.id
    )}">查看说明</button>`;
    ulr.appendChild(li);
  }
  ref.appendChild(ulr);
  ulr.querySelectorAll("[data-doc-id]").forEach((btn) => {
    btn.addEventListener("click", () => void openModelDoc(btn.dataset.docId));
  });
}

async function openModelDoc(docId) {
  try {
    const r = await fetch(`/api/models/docs/${encodeURIComponent(docId)}`, { credentials: "include" });
    if (!r.ok) throw new Error("无法打开文档");
    const text = await r.text();
    const w = window.open("", "_blank", "noopener,noreferrer");
    if (w) {
      w.document.write(`<pre style="white-space:pre-wrap;font-family:system-ui;padding:1rem">${escapeHtml(
        text
      )}</pre>`);
      w.document.close();
    } else showToast("请允许弹出窗口以查看文档。", "warn");
  } catch (e) {
    showToast(e.message || "文档打开失败", "error");
  }
}

async function loadModelCatalog() {
  try {
    modelCatalogCache = await api("/api/models/catalog");
    bindModelSelect("#modelSelectLive", "#modelHintLive", {
      includeWlasl: false,
      groupByLanguage: true,
      defaultLang: "zh",
    });
    bindModelSelect("#modelSelect", "#modelHintVideo", {
      includeWlasl: false,
      groupByLanguage: true,
      defaultLang: "zh",
    });
    setVideoModelLang("zh");
    renderModelsGuide();
  } catch (e) {
    console.error(e);
  }
}

function sourceLabel(path) {
  if (!path) return "—";
  const p = String(path).replace(/\\/g, "/");
  const i = p.lastIndexOf("/");
  return i >= 0 ? p.slice(i + 1) : p;
}

function setHealth(ok, msg) {
  const el = $("#healthPill");
  if (!el) return;
  el.textContent = msg;
  el.classList.toggle("err", !ok);
}

function showView(name) {
  const prevDock = document.querySelector(".dock-btn.is-active")?.dataset?.view || "";
  const isRec = (v) => v === "live" || v === "video";
  document.querySelectorAll(".view").forEach((v) => {
    v.classList.toggle("is-active", v.id === `view-${name}`);
  });
  document.querySelectorAll(".dock-btn").forEach((b) => {
    b.classList.toggle("is-active", b.dataset.view === name);
  });
  if (name !== prevDock && (isRec(name) || isRec(prevDock))) {
    cancelJobPolls("liveSeg", "liveRt", "videoRt");
    if (isRec(name)) resetSharedRecognitionChrome();
  }
  if (name === "video" || name === "live") {
    void showRecognitionReminders("tab");
  }
}

document.querySelectorAll(".dock-btn").forEach((btn) => {
  btn.addEventListener("click", () => showView(btn.dataset.view));
});

function escapeHtml(s) {
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

/* ----- 认证 ----- */
function setAuthError(msg) {
  const el = $("#authError");
  if (!el) return;
  if (!msg) {
    el.hidden = true;
    el.textContent = "";
    return;
  }
  el.hidden = false;
  el.textContent = msg;
}

function setAuthTab(which) {
  const login = which === "login";
  const tabL = $("#tabLogin");
  const tabR = $("#tabRegister");
  const pL = $("#panelLogin");
  const pR = $("#panelRegister");
  if (!tabL || !tabR || !pL || !pR) return;
  tabL.setAttribute("aria-selected", login ? "true" : "false");
  tabR.setAttribute("aria-selected", login ? "false" : "true");
  tabL.tabIndex = login ? 0 : -1;
  tabR.tabIndex = login ? -1 : 0;
  pL.hidden = !login;
  pR.hidden = login;
  setAuthError("");
  resetPasswordField($("#loginPass"), $("#btnLoginShowPass"), "显示密码");
  resetPasswordField($("#regPass"), $("#btnRegShowPass"), "显示密码");
  resetPasswordField($("#regPass2"), $("#btnReg2ShowPass"), "显示确认密码");
  requestAnimationFrame(() => {
    if (login) $("#loginUser")?.focus();
    else $("#regUser")?.focus();
  });
}

function wirePasswordToggle(btn, input, labels) {
  if (!btn || !input) return;
  const { show, hide } = labels;
  btn.addEventListener("click", () => {
    const isHidden = input.type === "password";
    input.type = isHidden ? "text" : "password";
    btn.setAttribute("aria-pressed", isHidden ? "true" : "false");
    btn.setAttribute("aria-label", isHidden ? hide : show);
    btn.textContent = isHidden ? "隐藏" : "显示";
  });
}

function resetPasswordField(input, btn, ariaShowLabel) {
  if (!input || !btn) return;
  input.type = "password";
  btn.setAttribute("aria-pressed", "false");
  btn.setAttribute("aria-label", ariaShowLabel);
  btn.textContent = "显示";
}

let _authBusy = false;
function setAuthBusy(busy) {
  _authBusy = busy;
  const gate = $("#authGate");
  if (gate) gate.setAttribute("aria-busy", busy ? "true" : "false");
  const ids = ["btnLoginSubmit", "btnRegisterSubmit", "tabLogin", "tabRegister", "linkToLogin", "linkToRegister", "btnGuestEnter"];
  for (const id of ids) {
    const el = document.getElementById(id);
    if (el) el.disabled = busy;
  }
  const bL = $("#btnLoginSubmit");
  const bR = $("#btnRegisterSubmit");
  if (bL) {
    if (!bL.dataset.labelIdle) bL.dataset.labelIdle = bL.textContent;
    bL.textContent = busy ? "请稍候…" : bL.dataset.labelIdle;
  }
  if (bR) {
    if (!bR.dataset.labelIdle) bR.dataset.labelIdle = bR.textContent;
    bR.textContent = busy ? "请稍候…" : bR.dataset.labelIdle;
  }
}

function validateUsername(u) {
  const s = (u || "").trim();
  if (s.length < 2 || s.length > 24) return "用户名请填写 2～24 个字符。";
  return "";
}

function validateRegisterPassword(p1, p2) {
  if ((p1 || "").length < 6) return "密码请至少 6 位。";
  if (p1 !== p2) return "两次输入的密码不一致，请检查。";
  return "";
}

function applyFontFromStorage() {
  const v = localStorage.getItem("handFontScale") || "118";
  document.documentElement.style.setProperty("--fs", v);
  const r = $("#fontRange");
  if (r) r.value = v;
}

let _infraWarnShown = false;

let _healthCache = {
  translateScriptReady: true,
  modelsOnDisk: true,
  translateHint: "",
};

let _lastTabReminderAt = 0;
const TAB_REMINDER_COOLDOWN_MS = 90000;

/** 小贴士（绿）与模型/脚本提示（黄）：短时 toast，不在顶栏常驻 */
function showToast(message, variant = "info", durationMs = 5200) {
  const text = String(message || "").trim();
  if (!text) return;
  const stack = $("#toastStack");
  if (!stack) return;
  const el = document.createElement("div");
  el.className = `toast toast--${variant}`;
  el.setAttribute("role", "status");
  el.innerHTML = `<button type="button" class="toast-close" aria-label="关闭">×</button><p class="toast-msg"></p>`;
  el.querySelector(".toast-msg").textContent = text;
  const close = () => {
    el.classList.add("toast-out");
    setTimeout(() => el.remove(), 280);
  };
  el.querySelector(".toast-close")?.addEventListener("click", close);
  stack.appendChild(el);
  setTimeout(close, durationMs);
}

async function showRecognitionReminders(trigger) {
  const now = Date.now();
  if (trigger === "tab" && now - _lastTabReminderAt < TAB_REMINDER_COOLDOWN_MS) return;
  if (trigger === "tab") _lastTabReminderAt = now;

  try {
    const t = await api("/api/tips/today");
    if (t?.tip) showToast(t.tip, "info", 5500);
  } catch {
    /* ignore */
  }
  const ready = _healthCache.translateScriptReady && _healthCache.modelsOnDisk;
  if (!ready && _healthCache.translateHint) {
    const delay = trigger === "job" ? 400 : 550;
    setTimeout(() => showToast(_healthCache.translateHint, "warn", 7800), delay);
  }
}

async function enterApp() {
  $("#authGate").hidden = true;
  $("#appShell").hidden = false;
  fillPhraseForm(null);
  const me = await fetch("/api/auth/me", { credentials: "include" }).then((r) => r.json());
  const ud = $("#userDisplay");
  const gb = $("#guestBadge");
  if (ud) ud.textContent = me.username || "";
  if (gb) gb.hidden = !me.guest;
  setAuthError("");
  applyFontFromStorage();
  await refreshTtsStatus();
  await refreshHealth();
  await loadModelCatalog();
  await loadPhrases();
  await loadSignVocab();
  initHandwritingPads();
  await loadHistory();
  setRunJobEnabled(!!lastUploadPath);
  warmupBrowserTts();
}

async function initSession() {
  initTtsControls();
  try {
    const me = await fetch("/api/auth/me", { credentials: "include" }).then((r) => r.json());
    await refreshTtsStatus();
    if (!me.loggedIn) {
      $("#authGate").hidden = false;
      $("#appShell").hidden = true;
      setAuthTab("login");
      return;
    }
    await enterApp();
  } catch (e) {
    console.error(e);
    $("#authGate").hidden = false;
    $("#appShell").hidden = true;
    setAuthTab("login");
    setAuthError("连不上服务器，请稍后再试。");
  }
}

$("#tabLogin")?.addEventListener("click", () => {
  if (_authBusy) return;
  setAuthTab("login");
});
$("#tabRegister")?.addEventListener("click", () => {
  if (_authBusy) return;
  setAuthTab("register");
});
$("#tabLogin")?.addEventListener("keydown", (e) => {
  if (e.key === "ArrowRight") {
    e.preventDefault();
    $("#tabRegister")?.click();
  }
});
$("#tabRegister")?.addEventListener("keydown", (e) => {
  if (e.key === "ArrowLeft") {
    e.preventDefault();
    $("#tabLogin")?.click();
  }
});
$("#linkToRegister")?.addEventListener("click", () => setAuthTab("register"));
$("#linkToLogin")?.addEventListener("click", () => setAuthTab("login"));

$("#btnGuestEnter")?.addEventListener("click", async () => {
  setAuthError("");
  setAuthBusy(true);
  try {
    await api("/api/auth/guest", { method: "POST", body: "{}" });
    await enterApp();
  } catch (err) {
    setAuthError(err.message || "暂时无法进入游客模式，请稍后再试。");
  } finally {
    setAuthBusy(false);
  }
});

wirePasswordToggle($("#btnLoginShowPass"), $("#loginPass"), { show: "显示密码", hide: "隐藏密码" });
wirePasswordToggle($("#btnRegShowPass"), $("#regPass"), { show: "显示密码", hide: "隐藏密码" });
wirePasswordToggle($("#btnReg2ShowPass"), $("#regPass2"), { show: "显示确认密码", hide: "隐藏确认密码" });

$("#formLogin")?.addEventListener("submit", async (e) => {
  e.preventDefault();
  setAuthError("");
  const u = $("#loginUser").value.trim();
  const errU = validateUsername(u);
  if (errU) {
    setAuthError(errU);
    $("#loginUser").focus();
    return;
  }
  if (!($("#loginPass").value || "").length) {
    setAuthError("请填写密码。");
    $("#loginPass").focus();
    return;
  }
  setAuthBusy(true);
  try {
    await api("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({
        username: u,
        password: $("#loginPass").value,
      }),
    });
    $("#loginPass").value = "";
    await enterApp();
  } catch (err) {
    setAuthError(err.message || "登录失败，请稍后再试。");
    $("#loginPass").focus();
  } finally {
    setAuthBusy(false);
  }
});

$("#formRegister")?.addEventListener("submit", async (e) => {
  e.preventDefault();
  setAuthError("");
  const u = $("#regUser").value.trim();
  const p1 = $("#regPass").value;
  const p2 = $("#regPass2").value;
  const errU = validateUsername(u);
  if (errU) {
    setAuthError(errU);
    $("#regUser").focus();
    return;
  }
  const errP = validateRegisterPassword(p1, p2);
  if (errP) {
    setAuthError(errP);
    if (p1.length < 6) $("#regPass").focus();
    else $("#regPass2").focus();
    return;
  }
  setAuthBusy(true);
  try {
    await api("/api/auth/register", {
      method: "POST",
      body: JSON.stringify({ username: u, password: p1 }),
    });
    $("#regPass").value = "";
    $("#regPass2").value = "";
    await enterApp();
  } catch (err) {
    setAuthError(err.message || "注册失败，请稍后再试。");
    $("#regUser").focus();
  } finally {
    setAuthBusy(false);
  }
});

$("#btnLogout")?.addEventListener("click", async () => {
  try {
    await api("/api/auth/logout", { method: "POST", body: "{}" });
  } catch {
    /* ignore */
  }
  lastUploadPath = "";
  fillPhraseForm(null);
  $("#authGate").hidden = false;
  $("#appShell").hidden = true;
  setAuthTab("login");
  requestAnimationFrame(() => $("#loginUser")?.focus());
});

$("#fontRange")?.addEventListener("input", (e) => {
  const v = e.target.value;
  document.documentElement.style.setProperty("--fs", v);
  localStorage.setItem("handFontScale", v);
});

/* ----- 给对方看大字 ----- */
function partnerMirrorEnabled() {
  const el = $("#chkPartnerMirror");
  return !!(el && el.checked);
}

function showPartnerMirror(text) {
  const wrap = $("#partnerMirror");
  const p = $("#partnerMirrorText");
  if (!wrap || !p) return;
  p.textContent = String(text || "").trim();
  wrap.hidden = false;
}

function closePartnerMirror() {
  const wrap = $("#partnerMirror");
  if (wrap) wrap.hidden = true;
}

function maybePartnerMirror(text) {
  if (partnerMirrorEnabled() && String(text || "").trim()) showPartnerMirror(text);
}

$("#partnerMirror")?.addEventListener("click", () => closePartnerMirror());
$("#btnPartnerClose")?.addEventListener("click", (ev) => {
  ev.stopPropagation();
  closePartnerMirror();
});

/* ----- 帮助 / 高对比 ----- */
const helpDlg = $("#helpDialog");
$("#btnModelsOpen")?.addEventListener("click", () => {
  if (!modelCatalogCache) void loadModelCatalog().then(renderModelsGuide);
  else renderModelsGuide();
  const dlg = $("#modelsGuideDialog");
  if (dlg) dlg.hidden = false;
  $("#btnModelsGuideClose")?.focus();
});
$("#btnModelsGuideClose")?.addEventListener("click", () => {
  const dlg = $("#modelsGuideDialog");
  if (dlg) dlg.hidden = true;
});

$("#btnHelpOpen")?.addEventListener("click", () => {
  if (!helpDlg) return;
  helpDlg.hidden = false;
  $("#btnHelpClose")?.focus();
});
$("#btnHelpClose")?.addEventListener("click", () => {
  if (helpDlg) helpDlg.hidden = true;
});
helpDlg?.addEventListener("click", (e) => {
  if (e.target === helpDlg) helpDlg.hidden = true;
});

$("#btnContrast")?.addEventListener("click", () => {
  const on = document.documentElement.classList.toggle("theme-high-contrast");
  $("#btnContrast")?.setAttribute("aria-pressed", on ? "true" : "false");
});

/* ----- 健康检查 ----- */
async function refreshHealth() {
  try {
    const h = await api("/api/health");
    setHealth(true, "已连接");
    const npBad = h.numpyOnnxOk === false;
    _healthCache = {
      translateScriptReady: !!h.translateScriptReady,
      modelsOnDisk: !!h.modelsOnDisk,
      translateHint: String(h.translateHint || "").trim(),
    };
    if (!_infraWarnShown) {
      if (npBad && h.numpyOnnxNote) {
        showToast(h.numpyOnnxNote, "error", 9000);
        _infraWarnShown = true;
      } else if (h.ffmpegAvailable === false && /ffmpeg/i.test(h.translateHint || "")) {
        showToast(h.translateHint, "warn", 6500);
        _infraWarnShown = true;
      }
    }
  } catch (e) {
    setHealth(false, "连不上");
    _healthCache = {
      translateScriptReady: false,
      modelsOnDisk: false,
      translateHint: "",
    };
    showToast("暂时连不上服务器，请稍后再试。", "error", 5200);
    console.error(e);
  }
}

/* ----- TTS：本机 Web Speech 或 MiniMax（经 /api/tts/minimax，密钥只在服务器） ----- */
function resolveMinimaxVoiceId(stored) {
  let id = (stored || "").trim();
  if (MINIMAX_VOICE_LEGACY_MAP[id]) id = MINIMAX_VOICE_LEGACY_MAP[id];
  if (id && MINIMAX_VOICE_CHOICES.some((x) => x.id === id)) return id;
  return MINIMAX_DEFAULT_VOICE_ID;
}

function getSelectedMinimaxVoiceId(phraseVoiceId, lang) {
  const speechLang = normalizeSpeechLang(lang);
  let fromPhrase = (phraseVoiceId && String(phraseVoiceId).trim()) || "";
  if (fromPhrase && !phraseVoiceMatchesLang(fromPhrase, speechLang)) {
    fromPhrase = "";
  }
  let vid = fromPhrase || getBaseMinimaxVoiceFromUi(speechLang);
  if (speechLang.toLowerCase().startsWith("en")) {
    if (!vid.startsWith("English_")) {
      vid = MINIMAX_DEFAULT_VOICE_EN;
    }
  } else if (vid.startsWith("English_")) {
    vid = getBaseMinimaxVoiceFromUi("zh-CN");
  }
  return vid;
}

function populateGlobalVoiceSelect() {
  const sel = $("#ttsMinimaxVoice");
  if (!sel) return;
  const speechLang = normalizeSpeechLang($("#pLang")?.value || localStorage.getItem("ttsLang") || "zh-CN");
  const list = voicesForLang(speechLang);
  const storageKey = speechLang.toLowerCase().startsWith("en") ? "ttsMinimaxVoiceEn" : "ttsMinimaxVoice";
  let saved = resolveMinimaxVoiceId(localStorage.getItem(storageKey));
  if (!list.some((x) => x.id === saved)) {
    saved = speechLang.toLowerCase().startsWith("en") ? MINIMAX_DEFAULT_VOICE_EN : MINIMAX_DEFAULT_VOICE_ID;
  }
  sel.innerHTML = "";
  for (const { id, label } of list) {
    const o = document.createElement("option");
    o.value = id;
    o.textContent = label;
    sel.appendChild(o);
  }
  sel.value = list.some((x) => x.id === saved) ? saved : list[0]?.id || saved;
  localStorage.setItem(storageKey, sel.value);
}

function populatePhraseVoiceSelect() {
  const sel = $("#pTtsVoice");
  if (!sel) return;
  let preserve = sel.value;
  const speechLang = normalizeSpeechLang($("#pLang")?.value || "zh-CN");
  if (preserve && preserve !== "" && !phraseVoiceMatchesLang(preserve, speechLang)) {
    preserve = "";
  }
  sel.innerHTML = "";
  const z = document.createElement("option");
  z.value = "";
  z.textContent = "跟全局默认音色一致";
  sel.appendChild(z);
  const list = voicesForLang(speechLang);
  for (const { id, label } of list) {
    const o = document.createElement("option");
    o.value = id;
    o.textContent = label;
    sel.appendChild(o);
  }
  if (preserve && (preserve === "" || list.some((x) => x.id === preserve))) sel.value = preserve;
  else sel.value = "";
}

function syncTtsVoiceHint() {
  const hint = $("#ttsMinimaxVoiceHint");
  if (!hint) return;
  const lang = normalizeSpeechLang($("#pLang")?.value || "zh-CN");
  if (lang.toLowerCase().startsWith("en")) {
    hint.innerHTML =
      "朗读<strong>英文</strong>时请选「英文·」音色；「耳语少女」极轻，长句建议用「清甜少女」或 Graceful Lady。";
  } else {
    hint.innerHTML =
      "朗读<strong>中文</strong>时请选「中文·」音色；默认「甜美女声」即可。「英文·」音色不能用于中文朗读。";
  }
}

function syncTtsMinimaxWraps() {
  const eng = $("#ttsEngineSelect")?.value || localStorage.getItem("ttsEngine") || "browser";
  const gWrap = $("#ttsMinimaxVoiceWrap");
  if (gWrap) gWrap.hidden = eng !== "minimax";
  const pWrap = $("#pTtsVoiceWrap");
  if (pWrap) pWrap.hidden = eng !== "minimax";
}

async function refreshRecognitionStatus() {
  try {
    const s = await api("/api/tts/status");
    kimiConfigured = !!s.kimiConfigured;
    zhipuConfigured = !!s.zhipuConfigured;
    handwritingZhipuReady = !!s.handwritingZhipuReady;
    hybridReady = !!s.hybridReady;
    const hintText = (() => {
      const base =
        "主路径：手语 ONNX 模型（How2Sign/OpenASL 等）。Kimi/DeepSeek 仅辅助判断与清洗，不替代 ONNX。";
      if (kimiConfigured && deepseekTranslateConfigured) {
        return `${base} 已配置 Kimi + DeepSeek。`;
      }
      if (kimiConfigured) {
        return `${base} 已配置 Kimi；建议再配 DEEPSEEK_API_KEY。`;
      }
      if (deepseekTranslateConfigured) {
        return `${base} 未配 Kimi 时整段混合无视频理解。`;
      }
      return `${base} 混合需 .env：DEEPSEEK_API_KEY（合议）+ 可选 MOONSHOT / ZHIPU_API_KEY。`;
    })();
    syncRecognitionModeHints(hintText);
    const sel = getRecognitionModeSelect();
    if (sel && sel.value === "hybrid" && !hybridReady && !kimiConfigured && !deepseekTranslateConfigured) {
      /* 无任何云端密钥时仍允许 hybrid（仅 ONNX+OCR+启发式） */
    }
  } catch {
    kimiConfigured = false;
    zhipuConfigured = false;
    hybridReady = false;
  }
}

async function refreshTtsStatus() {
  try {
    const s = await api("/api/tts/status");
    deepseekTranslateConfigured = !!s.deepseekConfigured;
    kimiConfigured = !!s.kimiConfigured;
    zhipuConfigured = !!s.zhipuConfigured;
    handwritingZhipuReady = !!s.handwritingZhipuReady;
    hybridReady = !!s.hybridReady;
    const te = $("#ttsEngineSelect");
    const mmOpt = te?.querySelector?.('option[value="minimax"]');
    if (mmOpt) mmOpt.disabled = !s.minimaxConfigured;
    if (!s.minimaxConfigured && te?.value === "minimax") {
      te.value = "browser";
      localStorage.setItem("ttsEngine", "browser");
    }
    const tr = $("#chkTtsTranslate");
    if (tr) {
      tr.disabled = !deepseekTranslateConfigured;
      tr.title = deepseekTranslateConfigured
        ? ""
        : "请在项目根 .env 配置 DEEPSEEK_API_KEY 后重启服务";
    }
  } catch {
    deepseekTranslateConfigured = false;
    kimiConfigured = false;
    zhipuConfigured = false;
    hybridReady = false;
    /* 未登录等情况下忽略 */
  }
  syncTtsMinimaxWraps();
  await refreshRecognitionStatus();
}

function getRecognitionModeSelect() {
  return $("#recognitionMode") || $("#recognitionModeLive");
}

function syncRecognitionModeHints(hybridHintText) {
  const mode = getRecognitionMode();
  let text = hybridHintText || "";
  if (mode === "onnx") {
    text =
      "仅 ONNX：识别手语动作，不读画面硬字幕。视频有底部字幕（新闻/教程）请改「仅 OCR」或「混合」。边播会自动尝试读字幕，整段+混合最准。";
  } else if (mode === "ocr") {
    text = "仅 OCR：读取画面底部硬字幕，不识别手语动作。适合有烧录字幕的新闻/教程。";
  } else if (!text) {
    text =
      "混合：ONNX + 画面字幕 OCR + DeepSeek 仲裁。有硬字幕且与手语 ONNX 冲突时优先字幕；无字幕片以 ONNX 为主。";
  }
  for (const id of ["recognitionModeHint", "recognitionModeHintLive"]) {
    const hint = $(`#${id}`);
    if (hint) hint.textContent = text;
  }
}

function syncRecognitionModeSelects(fromEl) {
  const v =
    fromEl?.value ||
    $("#recognitionMode")?.value ||
    $("#recognitionModeLive")?.value ||
    localStorage.getItem("recognitionMode") ||
    "onnx";
  for (const id of ["recognitionMode", "recognitionModeLive"]) {
    const el = $(`#${id}`);
    if (el && el.querySelector(`option[value="${v}"]`)) el.value = v;
  }
  localStorage.setItem("recognitionMode", v);
  syncRecognitionModeHints();
}

function getRecognitionMode() {
  const saved = localStorage.getItem("recognitionMode");
  const sel = getRecognitionModeSelect();
  return sel?.value || saved || "onnx";
}

function ttsSoundOn() {
  return localStorage.getItem("ttsSoundEnabled") !== "0";
}

function initTtsControls() {
  const pl = $("#pLang");
  const savedLang = localStorage.getItem("ttsLang");
  if (pl && savedLang) pl.value = savedLang;
  populateGlobalVoiceSelect();
  populatePhraseVoiceSelect();
  syncTtsVoiceHint();
  const te = $("#ttsEngineSelect");
  if (te) te.value = localStorage.getItem("ttsEngine") || "browser";
  const snd = $("#chkTtsSound");
  if (snd) snd.checked = ttsSoundOn();
  const tr = $("#chkTtsTranslate");
  if (tr) tr.checked = ttsTranslateBeforeSpeak();
  syncRecognitionModeSelects();
  syncTtsMinimaxWraps();
}

$("#recognitionMode")?.addEventListener("change", (e) => syncRecognitionModeSelects(e.target));
$("#recognitionModeLive")?.addEventListener("change", (e) => syncRecognitionModeSelects(e.target));

function draftPhraseVoiceId(lang) {
  const wrap = $("#pTtsVoiceWrap");
  const raw = (wrap && !wrap.hidden && $("#pTtsVoice")?.value?.trim()) || "";
  if (!raw) return "";
  if (!phraseVoiceMatchesLang(raw, lang)) return "";
  return raw;
}

function stopActiveTtsPlayback() {
  window.speechSynthesis.cancel();
  if (minimaxAudioEl) {
    minimaxAudioEl.pause();
    minimaxAudioEl.removeAttribute("src");
    minimaxAudioEl = null;
  }
  if (lastMinimaxBlobUrl) {
    URL.revokeObjectURL(lastMinimaxBlobUrl);
    lastMinimaxBlobUrl = null;
  }
}

function stopAllTts() {
  stopActiveTtsPlayback();
  ttsPlayQueue = Promise.resolve();
}

function enqueueTts(task) {
  const run = ttsPlayQueue.then(() => task());
  ttsPlayQueue = run.catch(() => {});
  return run;
}

/** 多行/多句拆成逐句朗读，避免 MiniMax 一次请求或并发播放叠在一起 */
function splitIntoSpeechLines(text) {
  const raw = String(text || "").trim();
  if (!raw) return [];
  const lines = [];
  for (const block of raw.split(/\n+/)) {
    const b = block.trim();
    if (!b) continue;
    const parts = b
      .split(/(?<=[。！？；!?])\s*/u)
      .map((s) => s.trim())
      .filter(Boolean);
    if (parts.length) lines.push(...parts);
    else lines.push(b);
  }
  return lines.length ? lines : [raw];
}

function waitForMinimaxPlayback() {
  return new Promise((resolve) => {
    const el = minimaxAudioEl;
    if (!el) {
      resolve();
      return;
    }
    const finish = () => resolve();
    if (el.ended) {
      finish();
      return;
    }
    el.addEventListener("ended", finish, { once: true });
    el.addEventListener("error", finish, { once: true });
  });
}

function warmupBrowserTts() {
  if (!window.speechSynthesis) return;
  window.speechSynthesis.getVoices();
  window.speechSynthesis.onvoiceschanged = () => {
    window.speechSynthesis.getVoices();
  };
}

/** Windows/Chrome 上语音列表常晚于首屏加载，轮询等待避免偶发「无音色」 */
function waitForBrowserVoices(maxMs = 4500) {
  const syn = window.speechSynthesis;
  if (!syn) return Promise.resolve();
  if (syn.getVoices().length > 0) return Promise.resolve();
  return new Promise((resolve) => {
    const t0 = Date.now();
    const id = window.setInterval(() => {
      syn.getVoices();
      if (syn.getVoices().length > 0 || Date.now() - t0 >= maxMs) {
        clearInterval(id);
        resolve();
      }
    }, 90);
  });
}

function pickBrowserVoice(lang) {
  const voices = window.speechSynthesis.getVoices();
  if (!voices.length) return null;
  const norm = normalizeSpeechLang(lang).toLowerCase();
  const lc = (s) => String(s || "").toLowerCase().replace("_", "-");
  const prefer = norm.startsWith("en")
    ? ["en-us", "en-gb", "en-au", "en-ie", "en-in", "en"]
    : ["zh-cn", "zh-tw", "zh-hk", "zh"];
  for (const p of prefer) {
    const hit = voices.find((v) => lc(v.lang).startsWith(p));
    if (hit) return hit;
  }
  if (norm.startsWith("en")) {
    return voices.find((v) => lc(v.lang).startsWith("en")) || null;
  }
  return voices.find((v) => lc(v.lang).startsWith("zh")) || null;
}

function speakTextBrowser(text, lang) {
  const t = String(text || "").trim();
  if (!t) return Promise.resolve();
  if (!window.speechSynthesis) {
    showToast("当前浏览器不支持本机朗读。", "error", 4000);
    return Promise.resolve();
  }
  const speechLang = normalizeSpeechLang(lang);
  const needEn = speechLang.toLowerCase().startsWith("en");
  return waitForBrowserVoices(4500).then(
    () =>
      new Promise((resolve) => {
        window.speechSynthesis.cancel();
        window.setTimeout(() => {
          const v = pickBrowserVoice(speechLang);
          if (needEn && !v) {
            showToast(
              "电脑里没有英文语音包，无法用本机朗读英文。请改用「云语音 MiniMax」，或在 Windows 设置 → 语言 → 语音里添加 English 语音。",
              "error",
              6500
            );
            resolve();
            return;
          }
          const u = new SpeechSynthesisUtterance(t);
          u.lang = speechLang;
          u.rate = 1;
          if (v) u.voice = v;
          const done = () => resolve();
          u.onend = done;
          u.onerror = () => {
            showToast("本机朗读失败，请改用「云语音 MiniMax」或稍后再试一次。", "error", 4800);
            done();
          };
          try {
            window.speechSynthesis.resume?.();
          } catch {
            /* ignore */
          }
          window.speechSynthesis.speak(u);
        }, 120);
      })
  );
}

/** 部分浏览器在 await 网络后丢失「用户激活」，双 rAF 有助于恢复 speak 成功率 */
function yieldForSpeechActivation() {
  return new Promise((resolve) => {
    window.requestAnimationFrame(() => {
      window.requestAnimationFrame(() => resolve());
    });
  });
}

function speakRecognitionAloud(text, lang = "zh-CN") {
  const raw = String(text || "").trim();
  if (!raw) return Promise.resolve();
  const browser =
    $("#videoJobSpeakBrowser")?.checked ||
    $("#videoRtSpeakBrowser")?.checked ||
    $("#liveRtSpeakBrowser")?.checked ||
    $("#liveSegSpeakBrowser")?.checked;
  const minimax =
    $("#videoJobSpeakMinimax")?.checked ||
    $("#videoRtSpeakMinimax")?.checked ||
    $("#liveRtSpeakMinimax")?.checked ||
    $("#liveSegSpeakMinimax")?.checked;
  if (!browser && !minimax) return Promise.resolve();
  return enqueueTts(async () => {
    for (const line of splitIntoSpeechLines(raw)) {
      if (browser) await speakUtteranceOnce(line, lang, "", { engine: "browser" });
      if (minimax) await speakUtteranceOnce(line, lang, "", { engine: "minimax" });
    }
  });
}

/** 单句朗读（由队列按句调用，勿并发） */
async function speakUtteranceOnce(text, lang, phraseVoiceId, opts = {}) {
  const raw = String(text || "").trim();
  if (!raw) return;
  const engineEarly = (
    opts.engine ||
    $("#ttsEngineSelect")?.value ||
    localStorage.getItem("ttsEngine") ||
    "browser"
  ).trim();
  if (engineEarly === "browser") {
    try {
      window.speechSynthesis?.resume?.();
    } catch {
      /* ignore */
    }
  }
  const { text: t, lang: speechLang } = await prepareSpeechText(raw, lang, {
    notify: !!opts.requireSound,
    translate: opts.translate,
  });
  if (!ttsSoundOn()) {
    if (opts.requireSound) {
      showToast("已关闭「朗读时播放声音」，请先勾选该项再播放。", "warn", 4200);
    }
    return;
  }
  const engine = (
    opts.engine ||
    $("#ttsEngineSelect")?.value ||
    localStorage.getItem("ttsEngine") ||
    "browser"
  ).trim();
  const voiceId = getSelectedMinimaxVoiceId(phraseVoiceId, speechLang);
  if (engine === "minimax") {
    try {
      stopActiveTtsPlayback();
      const res = await fetch("/api/tts/minimax", {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: t, voiceId, lang: speechLang }),
      });
      if (!res.ok) {
        let msg = res.statusText;
        try {
          const j = await res.json();
          msg = formatApiDetail(j) || msg;
        } catch {
          /* ignore */
        }
        throw new Error(msg);
      }
      const ct = (res.headers.get("content-type") || "").toLowerCase();
      if (ct.includes("json")) {
        const j = await res.json();
        throw new Error(formatApiDetail(j) || "云语音合成失败");
      }
      const blob = await res.blob();
      if (blob.size < 256) {
        throw new Error("云语音返回数据过短，请检查音色是否与语言匹配（英文请选 English 音色）");
      }
      lastMinimaxBlobUrl = URL.createObjectURL(blob);
      minimaxAudioEl = new Audio(lastMinimaxBlobUrl);
      minimaxAudioEl.addEventListener("ended", () => {
        if (lastMinimaxBlobUrl) URL.revokeObjectURL(lastMinimaxBlobUrl);
        lastMinimaxBlobUrl = null;
        minimaxAudioEl = null;
      });
      try {
        await minimaxAudioEl.play();
        await waitForMinimaxPlayback();
      } catch (playErr) {
        console.error(playErr);
        showToast("无法播放音频，请再点一次播放按钮。", "warn", 4000);
      }
    } catch (e) {
      console.error(e);
      const msg = e?.message || "云语音合成失败";
      showToast(msg, "error", 5200);
      if (!speechLang.toLowerCase().startsWith("en")) {
        await yieldForSpeechActivation();
        stopActiveTtsPlayback();
        await speakTextBrowser(t, speechLang);
      }
    }
    return;
  }
  await yieldForSpeechActivation();
  stopActiveTtsPlayback();
  await speakTextBrowser(t, speechLang);
}

/** @param {string} [phraseVoiceId] 常用语里单独选的 MiniMax voice_id，空则用全局默认 */
function speakUtterance(text, lang, phraseVoiceId, opts = {}) {
  const raw = String(text || "").trim();
  if (!raw) return Promise.resolve();
  if (opts._single) {
    return speakUtteranceOnce(raw, lang, phraseVoiceId, opts);
  }
  return enqueueTts(async () => {
    for (const line of splitIntoSpeechLines(raw)) {
      await speakUtteranceOnce(line, lang, phraseVoiceId, { ...opts, _single: true });
    }
  });
}

$("#btnStopTts")?.addEventListener("click", () => stopAllTts());

$("#ttsEngineSelect")?.addEventListener("change", () => {
  localStorage.setItem("ttsEngine", $("#ttsEngineSelect").value);
  syncTtsMinimaxWraps();
});

$("#ttsMinimaxVoice")?.addEventListener("change", () => {
  const id = $("#ttsMinimaxVoice").value;
  localStorage.setItem("ttsMinimaxVoice", id);
  if (id.startsWith("English_")) localStorage.setItem("ttsMinimaxVoiceEn", id);
});

$("#pLang")?.addEventListener("change", () => {
  const lang = normalizeSpeechLang($("#pLang")?.value || "zh-CN");
  localStorage.setItem("ttsLang", lang);
  populateGlobalVoiceSelect();
  populatePhraseVoiceSelect();
  syncTtsVoiceHint();
  if (($("#ttsEngineSelect")?.value || "") === "minimax") {
    const msg = lang.toLowerCase().startsWith("en")
      ? "已切换为英文音色列表，请点「播放声音」试听。"
      : "已切换为中文音色列表，请点「播放声音」试听。";
    showToast(msg, "warn", 3500);
  }
});

$("#chkTtsSound")?.addEventListener("change", () => {
  const on = !!$("#chkTtsSound")?.checked;
  localStorage.setItem("ttsSoundEnabled", on ? "1" : "0");
  if (!on) stopAllTts();
});

$("#chkTtsTranslate")?.addEventListener("change", () => {
  localStorage.setItem("ttsTranslateBeforeSpeak", $("#chkTtsTranslate")?.checked ? "1" : "0");
});

$("#btnTestTranslate")?.addEventListener("click", async () => {
  const box = $("#translateTestResult");
  const show = (msg, ok) => {
    if (box) {
      box.hidden = false;
      box.textContent = msg;
      box.classList.toggle("translate-test-result--ok", !!ok);
      box.classList.toggle("translate-test-result--err", !ok);
    }
    showToast(msg.slice(0, 120) + (msg.length > 120 ? "…" : ""), ok ? "info" : "error", 6000);
  };
  if (box) {
    box.hidden = false;
    box.textContent = "正在测试翻译…";
  }
  try {
    await refreshTtsStatus();
    if (!deepseekTranslateConfigured) {
      show("DeepSeek 未配置：请在项目根 .env 填写 DEEPSEEK_API_KEY 并重启 uvicorn。", false);
      return;
    }
    const r = await api("/api/speech/translate", {
      method: "POST",
      body: JSON.stringify({ text: "谢谢", targetLang: "en-US" }),
    });
    const line = JSON.stringify(r, null, 2);
    show(`翻译接口正常：\n${line}`, true);
  } catch (e) {
    show(`翻译失败：${e?.message || e}`, false);
  }
});

/* ----- 常用语：预览 / 展示 / 搜索筛选 ----- */
let phraseListCache = [];
let signVocabCache = [];
let libraryTab = "phrases";

function getDraftSpeakText() {
  return ($("#pSpeak")?.value || "").trim();
}

/**
 * 展示给对方：与「朗读语言」一致，必要时先翻译（如中文→英文）再显示；译出时附带一行原文。
 * @param {string} rawText
 * @param {{ uiLang?: string }} [opts]
 */
async function showPhraseShowDialog(rawText, opts = {}) {
  const raw = String(rawText || "").trim();
  if (!raw) {
    showToast("请先写上要展示的内容。", "warn", 3200);
    return;
  }
  const lang =
    opts.uiLang != null
      ? normalizeSpeechLang(opts.uiLang)
      : currentComposerSpeechLang();
  const prep = await prepareSpeechText(raw, lang, { notify: false, translate: true });
  const p = $("#phraseShowText");
  const sub = $("#phraseShowSub");
  const dlg = $("#phraseShowDialog");
  if (p) p.textContent = prep.text;
  if (sub) {
    if (prep.translated) {
      sub.hidden = false;
      sub.textContent = `原文：${raw}`;
    } else {
      sub.hidden = true;
      sub.textContent = "";
    }
  }
  if (dlg) dlg.hidden = false;
}

function closePhraseShowDialog() {
  const dlg = $("#phraseShowDialog");
  if (dlg) dlg.hidden = true;
  const sub = $("#phraseShowSub");
  if (sub) {
    sub.hidden = true;
    sub.textContent = "";
  }
}

$("#btnPreviewSpeak")?.addEventListener("click", () => {
  const t = getDraftSpeakText();
  if (!t) {
    showToast("请先写上「读出来的内容」。", "warn", 3200);
    return;
  }
  void speakUtterance(t, $("#pLang")?.value || "zh-CN", draftPhraseVoiceId($("#pLang")?.value), {
    requireSound: true,
  });
});

$("#btnPreviewShow")?.addEventListener("click", () => {
  void showPhraseShowDialog(getDraftSpeakText(), { uiLang: $("#pLang")?.value });
});

$("#btnPhraseShowClose")?.addEventListener("click", closePhraseShowDialog);
$("#phraseShowDialog")?.addEventListener("click", (e) => {
  if (e.target.id === "phraseShowDialog") closePhraseShowDialog();
});

const TEXT_PEEK_SKIP = new Set([
  "",
  "识别完成后，文字会显示在这里",
  "每段识别结果会显示在这里",
  "（未识别出文字）",
  "正在识别，请稍候…",
]);

function isTextPeekSkippable(text) {
  const t = String(text || "").trim();
  return TEXT_PEEK_SKIP.has(t) || /^正在识别/.test(t);
}

function openTextPeekDialog(title, body, meta) {
  const raw = String(body || "").trim();
  if (!raw || isTextPeekSkippable(raw)) return;
  const dlg = $("#textPeekDialog");
  const titleEl = $("#textPeekTitle");
  const metaEl = $("#textPeekMeta");
  const bodyEl = $("#textPeekBody");
  if (!dlg || !bodyEl) return;
  if (titleEl) titleEl.textContent = title || "完整文稿";
  bodyEl.textContent = raw;
  if (metaEl) {
    const m = String(meta || "").trim();
    if (m) {
      metaEl.hidden = false;
      metaEl.textContent = m;
    } else {
      metaEl.hidden = true;
      metaEl.textContent = "";
    }
  }
  dlg.hidden = false;
  bodyEl.focus();
}

function closeTextPeekDialog() {
  const dlg = $("#textPeekDialog");
  if (dlg) dlg.hidden = true;
  const metaEl = $("#textPeekMeta");
  if (metaEl) {
    metaEl.hidden = true;
    metaEl.textContent = "";
  }
  const bodyEl = $("#textPeekBody");
  if (bodyEl) bodyEl.textContent = "";
}

function collectRtLinesText(linesEl) {
  if (!linesEl) return "";
  const parts = [];
  for (const node of linesEl.querySelectorAll(".rt-line .rt-txt")) {
    const t = node.textContent.trim();
    if (t) parts.push(t);
  }
  return parts.join("\n");
}

function bindPeekableResultBox(el, title) {
  if (!el) return;
  const open = () => openTextPeekDialog(title, el.textContent);
  el.addEventListener("click", open);
  el.addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      open();
    }
  });
}

function bindRtTextPeek(currentEl, linesEl, titles = {}) {
  const { curTitle = "当前句", lineTitle = "本段识别", allTitle = "识别全文" } = titles;
  if (currentEl) {
    currentEl.addEventListener("click", () => {
      openTextPeekDialog(curTitle, currentEl.textContent.trim());
    });
  }
  if (!linesEl) return;
  if (linesEl) {
    linesEl.addEventListener("click", (e) => {
      const line = e.target.closest(".rt-line");
      if (line) {
        const txt = line.querySelector(".rt-txt")?.textContent?.trim() || "";
        const lbl = line.querySelector(".rt-lbl")?.textContent?.trim() || "";
        openTextPeekDialog(lineTitle, txt, lbl);
        return;
      }
      const all = collectRtLinesText(linesEl);
      openTextPeekDialog(allTitle, all);
    });
  }
}

function initTextPeekTriggers() {
  bindPeekableResultBox($("#liveSegmentResult"), "本段识别结果");
  bindRtTextPeek(null, $("#videoRecognitionLog"), {
    lineTitle: "识别内容",
    allTitle: "识别全文",
  });
  bindRtTextPeek($("#liveSubtitleCurrent"), $("#liveSubtitleLines"), {
    curTitle: "当前句",
    lineTitle: "本段识别",
    allTitle: "连续出字全文",
  });
  const log = $("#liveLog");
  if (log) {
    log.addEventListener("click", () => {
      const t = log.textContent.trim();
      if (t) openTextPeekDialog("识别日志", t);
    });
  }
}

$("#btnTextPeekClose")?.addEventListener("click", closeTextPeekDialog);
$("#textPeekDialog")?.addEventListener("click", (e) => {
  if (e.target.id === "textPeekDialog") closeTextPeekDialog();
});
document.addEventListener("keydown", (e) => {
  if (e.key !== "Escape") return;
  const dlg = $("#textPeekDialog");
  if (dlg && !dlg.hidden) closeTextPeekDialog();
});

initTextPeekTriggers();

function phraseMatchesFilter(row, q, catFilter) {
  if (catFilter) {
    const c = (row.category || "").trim();
    if (catFilter === "__none__" && c) return false;
    if (catFilter !== "__none__" && c !== catFilter) return false;
  }
  if (!q) return true;
  const hay = `${row.label || ""} ${row.speakText || ""} ${row.category || ""}`.toLowerCase();
  return hay.includes(q);
}

function updatePhraseCategoryFilterOptions(items) {
  const sel = $("#phraseCategoryFilter");
  if (!sel) return;
  const prev = sel.value;
  const cats = new Set();
  for (const row of items) {
    const c = (row.category || "").trim();
    cats.add(c || "__none__");
  }
  const sorted = [...cats].sort((a, b) => {
    if (a === "__none__") return 1;
    if (b === "__none__") return -1;
    return a.localeCompare(b, "zh");
  });
  sel.innerHTML = '<option value="">全部分类</option>';
  for (const key of sorted) {
    const o = document.createElement("option");
    o.value = key;
    o.textContent = key === "__none__" ? "未填分类" : key;
    sel.appendChild(o);
  }
  if (prev && [...sel.options].some((o) => o.value === prev)) sel.value = prev;
  else sel.value = "";
}

function sortPhraseRows(rows) {
  return [...rows].sort((a, b) => {
    const ua = (a.tag || "").trim() === "紧急" ? 0 : 1;
    const ub = (b.tag || "").trim() === "紧急" ? 0 : 1;
    if (ua !== ub) return ua - ub;
    return (Number(a.sortOrder) || 0) - (Number(b.sortOrder) || 0);
  });
}

function buildPhraseTile(row) {
  const urgent = (row.tag || "").trim() === "紧急";
  const tile = document.createElement("div");
  tile.className = urgent ? "phrase-tile is-urgent" : "phrase-tile";
  tile.setAttribute("role", "listitem");
  tile.tabIndex = 0;
  const badge = urgent ? `<span class="urgent-badge" aria-label="紧急">紧急</span>` : "";
  tile.innerHTML = `
    <span class="big">${escapeHtml(phraseTileTitle(row))}</span>
    ${badge}
    <div class="tile-actions">
      <button type="button" class="btn btn-quiet" data-pspeak="${row.id}">听</button>
      <button type="button" class="btn btn-quiet" data-pshow="${row.id}">展示</button>
      <button type="button" class="btn btn-quiet" data-pedit="${row.id}">改</button>
      <button type="button" class="btn btn-danger" data-pdel="${row.id}">删</button>
    </div>
    <p class="sub">${escapeHtml(row.speakText)}</p>`;
  tile.addEventListener("click", (ev) => {
    if (ev.target.closest("[data-pedit],[data-pdel],[data-pspeak],[data-pshow]")) return;
    void speakUtterance(row.speakText, currentComposerSpeechLang(), row.ttsVoiceId);
  });
  tile.addEventListener("keydown", (ev) => {
    if (ev.key === "Enter" || ev.key === " ") {
      ev.preventDefault();
      if (!ev.target.closest("[data-pedit],[data-pdel],[data-pspeak],[data-pshow]")) {
        void speakUtterance(row.speakText, currentComposerSpeechLang(), row.ttsVoiceId);
      }
    }
  });
  return tile;
}

function wirePhraseBoardActions(board) {
  board.querySelectorAll("[data-pspeak]").forEach((b) =>
    b.addEventListener("click", (ev) => {
      ev.stopPropagation();
      const row = phraseListCache.find((x) => x.id === b.dataset.pspeak);
      if (row) void speakUtterance(row.speakText, currentComposerSpeechLang(), row.ttsVoiceId);
    })
  );
  board.querySelectorAll("[data-pshow]").forEach((b) =>
    b.addEventListener("click", (ev) => {
      ev.stopPropagation();
      const row = phraseListCache.find((x) => x.id === b.dataset.pshow);
      if (row) void showPhraseShowDialog(row.speakText);
    })
  );
  board.querySelectorAll("[data-pedit]").forEach((b) =>
    b.addEventListener("click", (ev) => {
      ev.stopPropagation();
      const row = phraseListCache.find((x) => x.id === b.dataset.pedit);
      fillPhraseForm(row);
      $("#pLabel")?.focus();
    })
  );
  board.querySelectorAll("[data-pdel]").forEach((b) =>
    b.addEventListener("click", async (ev) => {
      ev.stopPropagation();
      if (!confirm("要删掉这句话吗？")) return;
      await api(`/api/phrases/${b.dataset.pdel}`, { method: "DELETE" });
      await loadPhrases();
    })
  );
}

function renderPhraseBoard() {
  const board = $("#phraseBoard");
  const emptyEl = $("#phraseListEmpty");
  const metaEl = $("#phraseListMeta");
  if (!board) return;

  const q = ($("#phraseSearch")?.value || "").trim().toLowerCase();
  const catFilter = $("#phraseCategoryFilter")?.value || "";
  const items = phraseListCache.filter((row) => phraseMatchesFilter(row, q, catFilter));
  board.innerHTML = "";

  if (metaEl && libraryTab === "phrases") {
    if (!phraseListCache.length) metaEl.textContent = "还没有常用语，写好内容后可点「存起来」";
    else if (!items.length) metaEl.textContent = `共 ${phraseListCache.length} 条，当前筛选无结果`;
    else metaEl.textContent = `显示 ${items.length} / ${phraseListCache.length} 条`;
  }
  if (emptyEl && libraryTab === "phrases") emptyEl.hidden = items.length > 0 || !phraseListCache.length;

  const groups = new Map();
  for (const row of items) {
    const catRaw = (row.category || "").trim();
    const catKey = catRaw || "__none__";
    if (!groups.has(catKey)) {
      groups.set(catKey, { label: catRaw || "未填分类", rows: [] });
    }
    groups.get(catKey).rows.push(row);
  }

  const groupOrder = [...groups.keys()].sort((a, b) => {
    if (a === "__none__") return 1;
    if (b === "__none__") return -1;
    return a.localeCompare(b, "zh");
  });

  for (const catKey of groupOrder) {
    const group = groups.get(catKey);
    const section = document.createElement("section");
    section.className = "phrase-group";

    const collapsed = localStorage.getItem(`phraseCatCollapsed:${catKey}`) === "1";
    const head = document.createElement("button");
    head.type = "button";
    head.className = "phrase-group-head";
    head.setAttribute("aria-expanded", collapsed ? "false" : "true");
    head.innerHTML = `<span class="phrase-group-label">${escapeHtml(group.label)}</span><span class="phrase-group-count">${group.rows.length} 条</span><span class="phrase-group-chevron" aria-hidden="true">${collapsed ? "▶" : "▼"}</span>`;

    const body = document.createElement("div");
    body.className = "phrase-group-body";
    body.hidden = collapsed;

    head.addEventListener("click", () => {
      const nowCollapsed = !body.hidden;
      body.hidden = nowCollapsed;
      head.setAttribute("aria-expanded", nowCollapsed ? "false" : "true");
      const chev = head.querySelector(".phrase-group-chevron");
      if (chev) chev.textContent = nowCollapsed ? "▶" : "▼";
      localStorage.setItem(`phraseCatCollapsed:${catKey}`, nowCollapsed ? "1" : "0");
    });

    for (const row of sortPhraseRows(group.rows)) {
      body.appendChild(buildPhraseTile(row));
    }
    section.appendChild(head);
    section.appendChild(body);
    board.appendChild(section);
  }

  wirePhraseBoardActions(board);
}

$("#phraseSearch")?.addEventListener("input", () => renderPhraseBoard());
$("#phraseCategoryFilter")?.addEventListener("change", () => renderPhraseBoard());

/* ----- 常用语 ----- */
function fillPhraseForm(row) {
  const titleEl = $("#formPhraseTitle");
  if (titleEl) titleEl.textContent = row ? "修改常用语" : "存到我的话";
  const phraseIdEl = $("#phraseId");
  if (phraseIdEl) phraseIdEl.value = row?.id || "";
  const vocabEditEl = $("#vocabEditId");
  if (vocabEditEl) vocabEditEl.value = "";
  if ($("#chkAlsoSignVocab")) $("#chkAlsoSignVocab").checked = false;
  if ($("#pSignNoteWrap")) $("#pSignNoteWrap").hidden = true;
  if ($("#pSignNote")) $("#pSignNote").value = "";
  const pLabel = $("#pLabel");
  if (pLabel) pLabel.value = row?.label || "";
  const pSpeak = $("#pSpeak");
  if (pSpeak) pSpeak.value = row?.speakText || "";
  const pOrder = $("#pOrder");
  if (pOrder) pOrder.value = row?.sortOrder ?? 0;
  const pTag = $("#pTag");
  if (pTag) pTag.value = (row?.tag || "").trim() === "紧急" ? "紧急" : "";
  const catEl = $("#pCategory");
  if (catEl) catEl.value = row?.category || "";
  const speechLang = row?.ttsLang || $("#pLang")?.value || "zh-CN";
  if ($("#pLang") && row?.ttsLang) $("#pLang").value = normalizeSpeechLang(row.ttsLang);
  populateGlobalVoiceSelect();
  populatePhraseVoiceSelect();
  syncTtsVoiceHint();
  const vid = (row?.ttsVoiceId || "").trim();
  const psel = $("#pTtsVoice");
  const langForVoice = $("#pLang")?.value || speechLang;
  if (
    vid &&
    phraseVoiceMatchesLang(vid, langForVoice) &&
    psel &&
    !Array.from(psel.options).some((o) => o.value === vid)
  ) {
    const o = document.createElement("option");
    o.value = vid;
    o.textContent = vid.length > 28 ? `${vid.slice(0, 28)}…（自定义）` : `${vid}（自定义）`;
    psel.appendChild(o);
  }
  if (psel) {
    psel.value =
      vid && phraseVoiceMatchesLang(vid, langForVoice) ? vid : "";
  }
  syncTtsMinimaxWraps();
}

$("#btnResetPhrase")?.addEventListener("click", () => fillPhraseForm(null));

$("#formVocab")?.addEventListener("submit", (e) => {
  e.preventDefault();
  const w = ($("#vWord")?.value || "").trim();
  if (!w) {
    showToast("请先填写手语词", "warn", 3500);
    $("#vWord")?.focus();
    return;
  }
  showToast("手语词本面板已停用，请在右侧「手语词」或勾选「同时记入手语词」保存。", "warn", 5000);
});

$("#formPhrase")?.addEventListener("submit", async (e) => {
  e.preventDefault();
  const id = $("#phraseId").value;
  const tagVal = $("#pTag").value || "";
  const speakRaw = (getDraftSpeakText() || $("#pSpeak")?.value || "").trim();
  if (!speakRaw) {
    showToast("请先填写或手写识别朗读内容", "warn", 4000);
    const kb = !$("#speakHandwritePanel")?.hidden;
    if (kb) $("#speakHandwritePanel")?.querySelector("canvas")?.focus?.();
    else $("#pSpeak")?.focus();
    return;
  }
  const labelRaw = ($("#pLabel").value || "").trim();
  const body = {
    label: labelRaw,
    speakText: speakRaw,
    ttsLang: $("#pLang").value,
    sortOrder: Number($("#pOrder").value) || 0,
    tag: tagVal,
    category: ($("#pCategory").value || "").trim(),
    ttsVoiceId: ($("#pTtsVoice").value || "").trim(),
  };
  if (id) {
    try {
      await api(`/api/phrases/${id}`, { method: "PUT", body: JSON.stringify(body) });
    } catch (err) {
      const msg = String(err?.message || "");
      if (msg.includes("短语不存在") || msg.includes("404")) {
        $("#phraseId").value = "";
        await api("/api/phrases", { method: "POST", body: JSON.stringify(body) });
        showToast("原条目已失效，已作为新常用语保存。", "warn", 4500);
      } else {
        throw err;
      }
    }
  } else await api("/api/phrases", { method: "POST", body: JSON.stringify(body) });
  if ($("#chkAlsoSignVocab")?.checked) {
    try {
      await saveSignVocabFromComposer((body.speakText || "").trim());
    } catch (err) {
      showToast(`常用语已保存，手语词未写入：${err.message}`, "warn", 6000);
    }
  }
  fillPhraseForm(null);
  await loadPhrases();
  await loadSignVocab();
});

async function saveSignVocabFromComposer(speakText) {
  const vid = ($("#vocabEditId")?.value || "").trim();
  const lang = ($("#pLang")?.value || "zh-CN").startsWith("en") ? "en" : "zh";
  const body = {
    word: speakText.slice(0, 120),
    language: lang,
    category: ($("#pCategory")?.value || "").trim(),
    description: ($("#pSignNote")?.value || "").trim(),
    videoHint: "",
  };
  if (vid) await api(`/api/vocabulary/${vid}`, { method: "PUT", body: JSON.stringify(body) });
  else await api("/api/vocabulary", { method: "POST", body: JSON.stringify(body) });
  const vocabEditEl = $("#vocabEditId");
  if (vocabEditEl) vocabEditEl.value = "";
}

$("#chkAlsoSignVocab")?.addEventListener("change", () => {
  const wrap = $("#pSignNoteWrap");
  if (wrap) wrap.hidden = !$("#chkAlsoSignVocab").checked;
});

/** 列表刷新后：若正在编辑的 id 已不在当前账号数据里，改为新建以免 PUT 404 */
function syncPhraseFormWithList() {
  const id = ($("#phraseId")?.value || "").trim();
  if (!id) return;
  const exists = phraseListCache.some((x) => x.id === id);
  if (exists) return;
  $("#phraseId").value = "";
  const titleEl = $("#formPhraseTitle");
  if (titleEl) titleEl.textContent = "存到我的话";
  showToast("该条常用语已不存在或属于其他账号，已改为「新建」保存。", "warn", 5200);
}

async function loadPhrases() {
  const data = await api("/api/phrases");
  phraseListCache = [...(data.items || [])];
  updatePhraseCategoryFilterOptions(phraseListCache);
  syncPhraseFormWithList();
  renderPhraseBoard();
}

/* ----- 手语词（融合在「我的话」右侧） ----- */
function signVocabSpeakText(row) {
  const w = (row.word || "").trim();
  const d = (row.description || "").trim();
  return d ? `${w}。${d}` : w;
}

function buildSignTile(row) {
  const tile = document.createElement("div");
  tile.className = "phrase-tile phrase-tile--sign";
  tile.setAttribute("role", "listitem");
  tile.tabIndex = 0;
  const sub = [row.category, row.language === "en" ? "英文" : "中文"].filter(Boolean).join(" · ");
  tile.innerHTML = `
    <span class="big">${escapeHtml(row.word)}</span>
    <div class="tile-actions">
      <button type="button" class="btn btn-quiet" data-sspeak="${row.id}">听</button>
      <button type="button" class="btn btn-quiet" data-sshow="${row.id}">展示</button>
      <button type="button" class="btn btn-quiet" data-sedit="${row.id}">改</button>
      <button type="button" class="btn btn-danger" data-sdel="${row.id}">删</button>
    </div>
    <p class="sub">${escapeHtml(row.description || sub || "手语词")}</p>`;
  tile.addEventListener("click", (ev) => {
    if (ev.target.closest("[data-sedit],[data-sdel],[data-sspeak],[data-sshow]")) return;
    void speakUtterance(signVocabSpeakText(row), row.language === "en" ? "en-US" : "zh-CN");
  });
  return tile;
}

function wireSignBoardActions(board) {
  board.querySelectorAll("[data-sspeak]").forEach((b) =>
    b.addEventListener("click", (ev) => {
      ev.stopPropagation();
      const row = signVocabCache.find((x) => x.id === b.dataset.sspeak);
      if (row) void speakUtterance(signVocabSpeakText(row), row.language === "en" ? "en-US" : "zh-CN");
    })
  );
  board.querySelectorAll("[data-sshow]").forEach((b) =>
    b.addEventListener("click", (ev) => {
      ev.stopPropagation();
      const row = signVocabCache.find((x) => x.id === b.dataset.sshow);
      if (row) void showPhraseShowDialog(signVocabSpeakText(row));
    })
  );
  board.querySelectorAll("[data-sedit]").forEach((b) =>
    b.addEventListener("click", (ev) => {
      ev.stopPropagation();
      const row = signVocabCache.find((x) => x.id === b.dataset.sedit);
      if (!row) return;
      const vocabEditEl = $("#vocabEditId");
      if (vocabEditEl) vocabEditEl.value = row.id;
      const pSpeak = $("#pSpeak");
      if (pSpeak) pSpeak.value = row.word || "";
      const pSignNote = $("#pSignNote");
      if (pSignNote) pSignNote.value = row.description || "";
      const pCategory = $("#pCategory");
      if (pCategory) pCategory.value = row.category || "";
      const pLang = $("#pLang");
      if (pLang) pLang.value = row.language === "en" ? "en-US" : "zh-CN";
      $("#chkAlsoSignVocab").checked = true;
      $("#pSignNoteWrap").hidden = false;
      setLibraryTab("phrases");
      $("#pSpeak")?.focus();
      showToast("已载入左侧，改完后点「存起来」更新。", "info", 4000);
    })
  );
  board.querySelectorAll("[data-sdel]").forEach((b) =>
    b.addEventListener("click", async (ev) => {
      ev.stopPropagation();
      if (!confirm("删除这条手语词？")) return;
      await api(`/api/vocabulary/${b.dataset.sdel}`, { method: "DELETE" });
      await loadSignVocab();
    })
  );
}

function renderSignBoard() {
  const board = $("#signBoard");
  const emptyEl = $("#phraseListEmpty");
  const metaEl = $("#phraseListMeta");
  if (!board) return;
  const q = ($("#signSearch")?.value || "").trim().toLowerCase();
  const items = signVocabCache.filter((row) => {
    if (!q) return true;
    const hay = `${row.word} ${row.description} ${row.category}`.toLowerCase();
    return hay.includes(q);
  });
  board.innerHTML = "";
  if (libraryTab === "sign" && metaEl) {
    metaEl.textContent = items.length
      ? `手语词 ${items.length} 条（点「听」朗读字义）`
      : "勾选左侧「同时记入手语词」即可添加";
  }
  if (libraryTab === "sign" && emptyEl) emptyEl.hidden = items.length > 0;
  for (const row of items) {
    const tile = buildSignTile(row);
    board.appendChild(tile);
  }
  wireSignBoardActions(board);
}

async function loadSignVocab() {
  const data = await api("/api/vocabulary");
  signVocabCache = [...(data.items || [])];
  renderSignBoard();
  if (libraryTab === "phrases") renderPhraseBoard();
}

function setLibraryTab(tab) {
  libraryTab = tab;
  const isPhrase = tab === "phrases";
  $("#tabLibraryPhrases")?.classList.toggle("is-active", isPhrase);
  $("#tabLibrarySign")?.classList.toggle("is-active", !isPhrase);
  $("#libraryToolbarPhrases").hidden = !isPhrase;
  $("#libraryToolbarSign").hidden = isPhrase;
  $("#phraseBoardWrap").hidden = !isPhrase;
  $("#signBoardWrap").hidden = isPhrase;
  if (isPhrase) renderPhraseBoard();
  else renderSignBoard();
}

$("#tabLibraryPhrases")?.addEventListener("click", () => setLibraryTab("phrases"));
$("#tabLibrarySign")?.addEventListener("click", () => setLibraryTab("sign"));
$("#signSearch")?.addEventListener("input", () => renderSignBoard());

async function loadVocab() {
  await loadSignVocab();
}

/* ----- 记录 ----- */
function recognitionResultText(res) {
  const t = String(res?.text || "").trim();
  if (t) return t;
  const segs = Array.isArray(res?.segmentTexts) ? res.segmentTexts : [];
  return segs
    .map((s) => String(s?.text || "").trim())
    .filter(Boolean)
    .join("\n");
}

/** 勾选「记入记录」时：服务端未写入则前端补存，并提示用户。 */
async function ensureRecognitionHistory(res, { want, sourceFile, modelKey, note = "" }) {
  if (!want || res?.status !== "done") return;
  const text = recognitionResultText(res);
  if (!text) return;
  if (res.historyId) {
    showToast("已记入「记录」", "info", 3200);
    return;
  }
  try {
    const row = await api("/api/history", {
      method: "POST",
      body: JSON.stringify({
        text,
        note: note || "job-auto-fallback",
        modelKey: modelKey || "",
        sourceFile: sourceFile || "",
      }),
    });
    if (row?.id) res.historyId = row.id;
    showToast("已记入「记录」", "info", 3200);
  } catch (e) {
    showToast(`记入「记录」失败：${e.message || e}`, "warn", 6500);
  }
}

async function loadHistory() {
  const data = await api("/api/history");
  const tb = $("#tableHist tbody");
  tb.innerHTML = "";
  for (const row of data.items || []) {
    const tr = document.createElement("tr");
    const tdTime = document.createElement("td");
    tdTime.textContent = row.createdAt || "";
    const tdModel = document.createElement("td");
    tdModel.textContent = modelLabelForUser(row.modelKey);
    const tdSrc = document.createElement("td");
    tdSrc.textContent = sourceLabel(row.sourceFile);
    const tdText = document.createElement("td");
    tdText.textContent = row.text;
    const tdAct = document.createElement("td");
    const bSpeak = document.createElement("button");
    bSpeak.type = "button";
    bSpeak.className = "btn btn-quiet";
    bSpeak.textContent = "读";
    bSpeak.addEventListener("click", () => void speakUtterance(row.text, "zh-CN"));
    const bDel = document.createElement("button");
    bDel.type = "button";
    bDel.className = "btn btn-danger";
    bDel.textContent = "删";
    bDel.addEventListener("click", async () => {
      await api(`/api/history/${row.id}`, { method: "DELETE" });
      await loadHistory();
    });
    tdAct.appendChild(bSpeak);
    tdAct.appendChild(bDel);
    tr.appendChild(tdTime);
    tr.appendChild(tdModel);
    tr.appendChild(tdSrc);
    tr.appendChild(tdText);
    tr.appendChild(tdAct);
    tb.appendChild(tr);
  }
}

/* ----- 上传 / 识别 ----- */
let lastUploadPath = "";

function setRunJobEnabled(on) {
  const btn = $("#btnRunVideoJob");
  if (btn) btn.disabled = !on;
}

function videoRecognitionLogEl() {
  return $("#videoRecognitionLog");
}

function syncVideoLogPlaceholder() {
  const el = videoRecognitionLogEl();
  if (!el) return;
  const ph = el.querySelector(".video-log-placeholder");
  if (ph) ph.hidden = !!el.querySelector(".rt-line");
}

function clearVideoRecognitionLog() {
  const el = videoRecognitionLogEl();
  if (!el) return;
  el.querySelectorAll(".rt-line").forEach((n) => n.remove());
  const ph = el.querySelector(".video-log-placeholder");
  if (ph) {
    ph.hidden = false;
    ph.textContent = "识别完成后，文字会显示在这里";
  }
}

/** 切换「传视频 / 拍一下」或离开识别 Tab 时清掉共享黄框与输出，避免模式1进度刷在模式2 */
function resetSharedRecognitionChrome() {
  resetJobPollPartial();
  setJobProgressBoxVisible(false);
  for (const [msgId, fillId] of [
    ["jobProgressMessage", "jobProgressBarFill"],
    ["videoJobProgressMessage", "videoJobProgressBarFill"],
  ]) {
    const m = $(`#${msgId}`);
    const f = $(`#${fillId}`);
    if (m) m.textContent = "";
    if (f) {
      f.style.width = "0%";
      const track = f.parentElement;
      if (track) track.hidden = true;
    }
  }
  const jst = $("#jobStatus");
  if (jst) jst.textContent = "";
  clearVideoRecognitionLog();
}

function clearVideoRtLines() {
  const el = videoRecognitionLogEl();
  if (!el) return;
  el.querySelectorAll(".rt-line:not(.rt-line--job)").forEach((n) => n.remove());
  syncVideoLogPlaceholder();
}

function formatSegTime(sec) {
  const s = Math.max(0, Number(sec) || 0);
  const m = Math.floor(s / 60);
  const r = Math.floor(s % 60);
  return `${m}:${String(r).padStart(2, "0")}`;
}

function setVideoFullJobLine(text, ok = true, segmentTexts, recognitionMode = "") {
  const linesEl = videoRecognitionLogEl();
  if (!linesEl) return;
  linesEl.querySelectorAll(".rt-line--job").forEach((n) => n.remove());
  const mode = String(recognitionMode || "").trim().toLowerCase();
  const segLabelPrefix =
    mode === "hybrid" ? "混合识别" : mode === "ocr" ? "字幕 OCR" : "整段识别";
  const segs = Array.isArray(segmentTexts) ? segmentTexts : [];
  if (segs.length >= 1) {
    for (const seg of segs) {
      const tx = String(seg.text || "").trim();
      const err = String(seg.error || "").trim();
      if (!tx && !err) continue;
      const t0 = seg.startSec;
      const t1 = seg.endSec;
      const timeR =
        t0 != null && t1 != null
          ? ` ${formatSegTime(t0)}–${formatSegTime(t1)}`
          : "";
      const label = `${segLabelPrefix} 第 ${seg.index ?? "?"} 句${timeR}`;
      appendSubtitleLine(linesEl, null, label, tx || `（本段无译文${err ? `：${err}` : ""}）`, ok && !!tx);
    }
  } else {
    const t = String(text || "").trim();
    if (!t) {
      appendSubtitleLine(
        linesEl,
        null,
        "整段识别",
        ok ? "（未识别出文字）" : "识别完成后，文字会显示在这里",
        false,
      );
    } else {
      const parts = t.split(/\n+/).map((p) => p.trim()).filter(Boolean);
      if (parts.length > 1) {
        parts.forEach((p, i) => {
          appendSubtitleLine(linesEl, null, `整段识别 第 ${i + 1} 句`, p, ok);
        });
      } else {
        appendSubtitleLine(linesEl, null, "整段识别", t, ok);
      }
    }
  }
  const allLines = linesEl.querySelectorAll(".rt-line");
  const jobCount =
    segs.length > 1
      ? segs.filter((s) => String(s?.text || "").trim()).length
      : Math.max(1, String(text || "").trim().split(/\n+/).filter(Boolean).length);
  for (let i = Math.max(0, allLines.length - jobCount); i < allLines.length; i += 1) {
    allLines[i].classList.add("rt-line--job");
  }
  syncVideoLogPlaceholder();
  linesEl.scrollTop = linesEl.scrollHeight;
}

function showJobFeedback(res) {
  setJobProgressBoxVisible(false);
  resetJobPollPartial();
  const ok = res.status === "done";
  const errEl = $("#jobError");
  const subEl = $("#jobBurnedSubtitle");
  const hybridEl = $("#jobHybridDetail");
  const noteEl = $("#jobQualityNote");
  const metaDetails = $("#jobMetaDetails");
  if (errEl) errEl.hidden = ok;
  const out = ok ? String(res.text || "").trim() : "";
  if (ok) setVideoFullJobLine(out, true, res.segmentTexts, res.recognitionMode);
  else if (!out) setVideoFullJobLine("", false, res.segmentTexts, res.recognitionMode);
  const burned = ok ? String(res.burnedSubtitle || "").trim() : "";
  if (subEl) {
    const dupOcr = burned && out && (burned === out || out.includes(burned) || burned.includes(out));
    subEl.hidden = !burned || dupOcr;
    subEl.textContent = burned && !dupOcr ? `画面字幕（OCR）：${burned}` : "";
  }
  const onnxT = ok ? String(res.onnxText || "").trim() : "";
  const kimiT = ok ? String(res.visionText || "").trim() : "";
  const mode = ok ? String(res.recognitionMode || "").trim() : "";
  if (hybridEl) {
    const parts = [];
    if (onnxT) {
      parts.push(`ONNX 模型：${onnxT}`);
    }
    if (mode === "hybrid" || mode === "ocr") {
      const agents = Array.isArray(res.agentsUsed) ? res.agentsUsed : [];
      const rounds = Array.isArray(res.reviewRounds) ? res.reviewRounds : [];
      if (agents.length) parts.push(`多 Agent：${agents.join(" → ")}`);
      if (rounds.length) parts.push(`复查轮次：${rounds.join(" → ")}`);
      if (res.glmText) parts.push(`智谱 GLM：${String(res.glmText).slice(0, 80)}…`);
      if (res.arbitrator) parts.push(`仲裁：${res.arbitrator}`);
      const note = String(res.hybridNote || "").trim();
      if (note) parts.push(note);
      const ast = String(res.agentStatus || "").trim();
      if (ast) parts.push(ast);
    }
    hybridEl.hidden = !parts.length;
    hybridEl.textContent = parts.join(" · ");
  }
  const qn = ok ? String(res.qualityNote || "").trim() : "";
  const plan = res.segmentPlan || {};
  const segList = Array.isArray(res.segmentTexts) ? res.segmentTexts : [];
  const segN = segList.length;
  const segWithText = segList.filter((s) => String(s?.text || "").trim()).length;
  let planNote = "";
  const planSegmentCount =
    Number(plan.segmentCount || plan.onnxSegmentCount || 0) || 0;
  if (plan.videoDurationSec && (segN || planSegmentCount)) {
    if (segN) {
      planNote = `视频 ${plan.videoDurationSec} 秒 → 共 ${segN} 段（${segWithText} 段有译文）。`;
    } else if (planSegmentCount) {
      planNote = `视频 ${plan.videoDurationSec} 秒 → ONNX 分 ${planSegmentCount} 段识别后合并仲裁。`;
    }
  }
  const sd = plan.splitDebug;
  if (sd && typeof sd === "object") {
    const extra = `分段：有效时长 ${sd.effectiveDurationSec ?? "?"}s，切成 ${sd.chunkCount ?? "?"} 段。`;
    planNote = planNote ? `${planNote} ${extra}` : extra;
  }
  if (noteEl) {
    const combined = [planNote, qn].filter(Boolean).join(" ");
    noteEl.hidden = !combined;
    noteEl.textContent = combined;
  }
  if (metaDetails) {
    const showMeta = !!(burned || qn || (hybridEl && !hybridEl.hidden));
    metaDetails.hidden = !showMeta;
  }
  if (errEl) {
    errEl.textContent = ok
      ? ""
      : res.message || res.agentStatus || "没有识别出来，请换一段视频再试。";
  }
  const st = $("#jobStatus");
  if (st) {
    const lineCount =
      segN > 0 ? segN : out ? out.split(/\n/).filter(Boolean).length : 0;
    st.textContent = ok
      ? out || segN > 0
        ? `识别完成（${mode || "onnx"}，共 ${lineCount} 段${segWithText !== lineCount ? `，${segWithText} 段有译文` : ""}）`
        : "识别完成，但没有文字"
      : "没识别出来";
  }
  if (ok && out) {
    videoRecognitionLogEl()?.scrollIntoView({ behavior: "smooth", block: "nearest" });
    const speakText = out;
    maybePartnerMirror(speakText);
    void speakRecognitionAloud(speakText, "zh-CN");
  }
}

function clearJobFeedback() {
  const errEl = $("#jobError");
  if (errEl) {
    errEl.hidden = true;
    errEl.textContent = "";
  }
  videoRecognitionLogEl()?.querySelectorAll(".rt-line--job").forEach((n) => n.remove());
  syncVideoLogPlaceholder();
  const subEl = $("#jobBurnedSubtitle");
  const noteEl = $("#jobQualityNote");
  if (subEl) subEl.hidden = true;
  const hybridEl = $("#jobHybridDetail");
  if (hybridEl) hybridEl.hidden = true;
  if (noteEl) noteEl.hidden = true;
  const metaDetails = $("#jobMetaDetails");
  if (metaDetails) metaDetails.hidden = true;
  if ($("#jobBurnedSubtitle")) $("#jobBurnedSubtitle").textContent = "";
  if ($("#jobHybridDetail")) $("#jobHybridDetail").textContent = "";
  if ($("#jobQualityNote")) $("#jobQualityNote").textContent = "";
}

async function uploadBlob(blob, filename) {
  const fd = new FormData();
  fd.append("file", blob, filename || "clip.webm");
  const r = await fetch("/api/upload", { method: "POST", credentials: "include", body: fd });
  const j = await r.json();
  if (!r.ok) throw new Error(j.detail || r.statusText);
  return j;
}

let _jobPollPartialCount = 0;

function resetJobPollPartial() {
  _jobPollPartialCount = 0;
}

function formatJobProgress(j) {
  let msg = String(j.progressMessage || "").trim();
  if (isRealtimeJobProgress(j)) {
    msg = msg.replace(/整段识别/g, "边播识别");
  }
  if (msg) return msg;
  const cur = Number(j.progressCurrent) || 0;
  const tot = Number(j.progressTotal) || 0;
  if (tot > 0 && cur > 0) return `识别中（第 ${cur}/${tot} 段）…`;
  return "正在识别，请稍等…";
}

function isRealtimeJobProgress(j) {
  return !!(videoRtSessionActive || j?.realtimeSegment || j?.jobKind === "rt");
}

/** 模式2 进行时：左侧模式1 黄框必须保持隐藏 */
function hideMode1JobProgressBox() {
  const box = $("#jobProgressBox");
  if (box) box.hidden = true;
  const m = $("#jobProgressMessage");
  if (m) m.textContent = "";
  const fill = $("#jobProgressBarFill");
  if (fill) fill.style.width = "0%";
}

function setJobProgressBoxVisible(show, scope = "both") {
  if (videoRtSessionActive) {
    hideMode1JobProgressBox();
    scope = "rt";
  }
  const ids =
    scope === "rt"
      ? ["videoJobProgressBox"]
      : scope === "full"
        ? ["jobProgressBox"]
        : ["jobProgressBox", "videoJobProgressBox"];
  for (const id of ids) {
    const box = $(`#${id}`);
    if (box) box.hidden = !show;
  }
  if (videoRtSessionActive) hideMode1JobProgressBox();
}

function paintJobProgress(msg, tot, cur, pct, scope = "both") {
  if (videoRtSessionActive) {
    hideMode1JobProgressBox();
    scope = "rt";
  }
  const targets =
    scope === "rt"
      ? [["videoJobProgressBox", "videoJobProgressMessage", "videoJobProgressBarFill"]]
      : scope === "full"
        ? [["jobProgressBox", "jobProgressMessage", "jobProgressBarFill"]]
        : [
            ["jobProgressBox", "jobProgressMessage", "jobProgressBarFill"],
            ["videoJobProgressBox", "videoJobProgressMessage", "videoJobProgressBarFill"],
          ];
  for (const [boxId, msgId, fillId] of targets) {
    const box = $(`#${boxId}`);
    const msgEl = $(`#${msgId}`);
    const fill = $(`#${fillId}`);
    if (box && msgEl) {
      box.hidden = false;
      msgEl.textContent = msg;
    }
    if (fill) {
      const track = fill.parentElement;
      if (track) track.hidden = !(tot > 1);
      const w =
        tot > 1 && cur > 0
          ? Math.min(100, Math.round((100 * cur) / tot))
          : Number.isFinite(pct)
            ? pct
            : 12;
      fill.style.width = `${w}%`;
    }
  }
  if (videoRtSessionActive) hideMode1JobProgressBox();
}

function updateJobProgressUi(j) {
  const rt = isRealtimeJobProgress(j);
  const msg = formatJobProgress(j);
  const tot = Number(j.progressTotal) || 0;
  const st = $("#jobStatus");
  if (st) {
    st.textContent = rt ? "" : tot > 1 ? "进度见上方识别输出区黄框" : "";
  }
  const cur = Number(j.progressCurrent) || 0;
  const pct = Number(j.progressPercent);
  paintJobProgress(msg, tot, cur, pct, rt ? "rt" : "both");
  if (!rt) appendPartialJobSegments(j.partialSegmentTexts);
  syncVideoLogPlaceholder();
}

function appendPartialJobSegments(partial) {
  if (!Array.isArray(partial) || !partial.length) return;
  const linesEl = videoRecognitionLogEl();
  if (!linesEl) return;
  for (let i = _jobPollPartialCount; i < partial.length; i += 1) {
    const seg = partial[i];
    const tx = String(seg?.text || "").trim();
    if (!tx) continue;
    const t0 = seg.startSec;
    const t1 = seg.endSec;
    const timeR =
      t0 != null && t1 != null
        ? ` ${formatSegTime(t0)}–${formatSegTime(t1)}`
        : "";
    appendSubtitleLine(
      linesEl,
      null,
      `整段识别 第 ${seg.index ?? i + 1} 句${timeR}`,
      tx,
      true,
    );
    const line = linesEl.querySelector(".rt-line:last-child");
    if (line) line.classList.add("rt-line--job", "rt-line--partial");
  }
  _jobPollPartialCount = partial.length;
  syncVideoLogPlaceholder();
}

async function pollJobUntilDone(jobId, pollMs = 1500, onProgress, signal) {
  for (;;) {
    if (signal?.aborted) {
      return { status: "error", message: "已停止", aborted: true };
    }
    let j;
    try {
      j = await api(`/api/jobs/${jobId}`, { signal });
    } catch (e) {
      if (isAbortError(e) || signal?.aborted) {
        return { status: "error", message: "已停止", aborted: true };
      }
      throw e;
    }
    if (j.status === "running" || j.status === "queued") {
      updateJobProgressUi(j);
      if (typeof onProgress === "function") onProgress(j);
    }
    if (j.status === "done" || j.status === "error") return j;
    const wait =
      Number(j.progressTotal) > 1 ? Math.min(1000, pollMs) : pollMs;
    try {
      await delay(wait, signal);
    } catch (e) {
      if (isAbortError(e) || signal?.aborted) {
        return { status: "error", message: "已停止", aborted: true };
      }
      throw e;
    }
  }
}

function getVideoPreviewDurationSec() {
  const v = $("#videoFilePreview");
  const d = Number(v?.duration);
  return Number.isFinite(d) && d > 0 ? d : 0;
}

async function startTranslateJobForPath(
  relPath,
  modelKey,
  appendHistory,
  pollMs = 1500,
  recognitionMode,
  onProgress,
  expectedOverrideSec = 0,
  signal,
  realtimeSegment = false,
) {
  const mode = recognitionMode || getRecognitionMode();
  const fromPreview = getVideoPreviewDurationSec();
  const ov = Number(expectedOverrideSec) || 0;
  const expectedDurationSec = realtimeSegment && ov > 0 ? ov : ov > 0 ? ov : fromPreview;
  const job = await api("/api/jobs/translate", {
    method: "POST",
    body: JSON.stringify({
      modelKey,
      videoRelativePath: relPath,
      appendHistory,
      recognitionMode: mode,
      realtimeSegment: !!realtimeSegment,
      expectedDurationSec: expectedDurationSec > 0 ? expectedDurationSec : undefined,
    }),
    signal,
  });
  return pollJobUntilDone(job.jobId, pollMs, onProgress, signal);
}

let videoPreviewObjectUrl = null;

$("#fileVideo")?.addEventListener("change", () => {
  const f = $("#fileVideo").files?.[0];
  $("#filePickLabel").textContent = f ? f.name : "未选择文件";
  const prev = $("#videoFilePreview");
  if (videoPreviewObjectUrl) {
    URL.revokeObjectURL(videoPreviewObjectUrl);
    videoPreviewObjectUrl = null;
  }
  if (!f) {
    if (prev) prev.removeAttribute("src");
    return;
  }
  if (!prev) return;
  videoPreviewObjectUrl = URL.createObjectURL(f);
  prev.src = videoPreviewObjectUrl;
});

$("#btnUpload")?.addEventListener("click", async () => {
  const input = $("#fileVideo");
  if (!input.files?.length) {
    $("#uploadStatus").textContent = "请先选视频";
    return;
  }
  $("#uploadStatus").textContent = "正在上传…";
  $("#jobStatus").textContent = "";
  clearVideoRecognitionLog();
  clearJobFeedback();
  const fd = new FormData();
  fd.append("file", input.files[0]);
  const res = await fetch("/api/upload", { method: "POST", credentials: "include", body: fd }).then(async (r) => {
    const j = await r.json();
    if (!r.ok) throw new Error(j.detail || r.statusText);
    return j;
  });
  lastUploadPath = res.savedPath;
  $("#uploadStatus").textContent = "传好了。请选「模式一 · 整段识别」或「模式二 · 边播边出字」。";
  setRunJobEnabled(true);
});

$("#btnRunVideoJob")?.addEventListener("click", async () => {
  if (!lastUploadPath) return;
  void showRecognitionReminders("job");
  clearJobFeedback();
  resetJobPollPartial();
  videoRecognitionLogEl()?.querySelectorAll(".rt-line--partial, .rt-line--job").forEach((n) => n.remove());
  const browserDur = getVideoPreviewDurationSec();
  if (!browserDur) {
    const prev = $("#videoFilePreview");
    if (prev) {
      try {
        prev.currentTime = 0.01;
        await new Promise((r) => {
          prev.addEventListener("loadedmetadata", r, { once: true });
          setTimeout(r, 400);
        });
      } catch {
        /* ignore */
      }
    }
  }
  const durFinal = getVideoPreviewDurationSec();
  const estSeg = durFinal > 8 ? Math.max(1, Math.ceil(durFinal / 10)) : 1;
  const startMsg =
    durFinal > 8
      ? `视频约 ${durFinal.toFixed(0)} 秒，将分约 ${estSeg} 段识别（每段约 10 秒）…`
      : durFinal > 0
        ? `视频约 ${durFinal.toFixed(0)} 秒，整段识别中（约 1～3 分钟）…`
        : "正在识别（若视频很长却只出一句，请先用下方预览播放一下再识别）…";
  $("#jobStatus").textContent = "进度见上方识别输出区黄框";
  setJobProgressBoxVisible(true, "both");
  paintJobProgress(startMsg, estSeg, 0, 5, "both");
  setVideoFullJobLine(
    "识别进行中…\n进度与「第 N/M 段」见上方黄框；每完成一段译文会多一行出现在本区。",
    true,
  );
  videoRecognitionLogEl()?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  const onJobProgress = (j) => updateJobProgressUi(j);
  const pollSig = takeTranslatePollSignal();
  const wantHist = !!$("#chkJobHistory")?.checked;
  try {
    const res = await startTranslateJobForPath(
      lastUploadPath,
      $("#modelSelect").value,
      wantHist,
      800,
      getRecognitionMode(),
      onJobProgress,
      0,
      pollSig,
    );
    showJobFeedback(res);
    await ensureRecognitionHistory(res, {
      want: wantHist,
      sourceFile: lastUploadPath,
      modelKey: $("#modelSelect").value,
      note: `job-auto; mode=${getRecognitionMode()}`,
    });
    if (wantHist) await loadHistory();
  } catch (err) {
    if (isAbortError(err)) {
      setJobProgressBoxVisible(false);
      $("#jobStatus").textContent = "已停止";
      return;
    }
    $("#jobStatus").textContent = "出错了";
    $("#jobError").hidden = false;
    $("#jobError").textContent = err.message || "请稍后再试。";
  }
});

$("#btnSaveManual")?.addEventListener("click", async () => {
  const text = $("#manualText").value.trim();
  if (!text) return;
  await api("/api/history", {
    method: "POST",
    body: JSON.stringify({
      text,
      note: $("#manualNote").value,
      modelKey: $("#modelSelect").value,
      sourceFile: lastUploadPath,
    }),
  });
  $("#manualText").value = "";
  $("#manualNote").value = "";
  await loadHistory();
  showView("history");
});

/* ----- 摄像头 ----- */
let liveAbort = false;
let mediaStream = null;
let liveLoopPromise = null;
let activeSegmentRecorder = null;

/** 停止/切流时浏览器常见提示，不必展示给用户 */
function isIgnorableMediaStreamError(message) {
  const s = String(message || "");
  return (
    /tracks in mediastream were removed/i.test(s) ||
    /the operation was aborted/i.test(s) ||
    /signal is aborted/i.test(s) ||
    /aborted without reason/i.test(s) ||
    /aborterror/i.test(s) ||
    /mediarecorder.*not.*active/i.test(s) ||
    /invalidstateerror.*mediarecorder/i.test(s)
  );
}

/** 先断开预览再 stop，避免 Chrome 报 Tracks in MediaStream were removed */
function releaseUserMediaStream(stream, videoEl) {
  if (!stream) return;
  const v = videoEl || $("#liveVideo");
  if (v) {
    try {
      v.pause();
    } catch {
      /* ignore */
    }
    if (v.srcObject === stream) v.srcObject = null;
  }
  for (const t of stream.getTracks()) {
    if (t.readyState === "live") {
      try {
        t.stop();
      } catch {
        /* ignore */
      }
    }
  }
}

/** captureStream() 的轨道属于视频元素，不能 stop，否则会触发上述警告 */
function releaseCaptureStreamRef() {
  videoContStream = null;
}

function pickMime() {
  const c = ["video/webm;codecs=vp9", "video/webm;codecs=vp8", "video/webm"];
  for (const m of c) {
    if (MediaRecorder.isTypeSupported(m)) return m;
  }
  return "";
}

function abortActiveSegmentRecording() {
  const rec = activeSegmentRecorder;
  if (!rec) return;
  try {
    if (rec.state === "recording") rec.stop();
  } catch {
    /* ignore */
  }
  activeSegmentRecorder = null;
}

function recordOneSegment(stream, ms, mimeType) {
  return new Promise((resolve, reject) => {
    const liveTracks = stream?.getVideoTracks?.() || [];
    if (!liveTracks.length || liveTracks.every((t) => t.readyState === "ended")) {
      reject(new Error("摄像头已关闭"));
      return;
    }
    const opts = mimeType ? { mimeType } : {};
    let rec;
    let settled = false;
    const finish = (fn, val) => {
      if (settled) return;
      settled = true;
      if (activeSegmentRecorder === rec) activeSegmentRecorder = null;
      fn(val);
    };
    try {
      rec = new MediaRecorder(stream, opts);
    } catch (e) {
      reject(e);
      return;
    }
    activeSegmentRecorder = rec;
    const chunks = [];
    rec.ondataavailable = (e) => {
      if (e.data && e.data.size) chunks.push(e.data);
    };
    rec.onerror = (ev) => {
      const err = ev.error || new Error("录像出错");
      if (isIgnorableMediaStreamError(err.message)) {
        finish(resolve, new Blob(chunks, { type: rec.mimeType || mimeType || "video/webm" }));
        return;
      }
      finish(reject, err);
    };
    rec.onstop = () => {
      const type = rec.mimeType || mimeType || "video/webm";
      finish(resolve, new Blob(chunks, { type }));
    };
    try {
      rec.start();
    } catch (e) {
      finish(reject, e);
      return;
    }
    setTimeout(() => {
      if (rec.state === "recording") {
        try {
          rec.stop();
        } catch {
          /* 停止时轨道可能已释放 */
        }
      }
    }, ms);
  });
}

function appendLiveLog(line) {
  const el = $("#liveLog");
  el.textContent = `${line}\n${el.textContent}`.slice(0, 12000);
}

function setLiveSegmentResult(text, opts = {}) {
  const el = $("#liveSegmentResult");
  if (!el) return;
  const loading = !!opts.loading;
  const t = String(text || "").trim();
  el.hidden = false;
  el.classList.toggle("is-loading", loading);
  if (loading) {
    el.classList.remove("is-empty");
    el.textContent = t || "正在识别本段…";
    return;
  }
  if (!t) {
    el.classList.add("is-empty");
    el.textContent = "本段未识别出文字，请双手入镜、光线充足后重试";
    return;
  }
  el.classList.remove("is-empty", "is-loading");
  el.textContent = t;
}

function getLiveCameraConstraints() {
  return {
    video: {
      facingMode: "user",
      width: { ideal: 1280, min: 640 },
      height: { ideal: 720, min: 480 },
    },
    audio: false,
  };
}

function cleanupLive() {
  abortActiveSegmentRecording();
  teardownLiveContinuousStream();
  if (mediaStream) {
    releaseUserMediaStream(mediaStream, $("#liveVideo"));
    mediaStream = null;
  }
  $("#btnLiveStop").disabled = true;
  $("#btnLiveStart").disabled = false;
  $("#liveStatus").textContent = "已停";
}

/* ----- 拍一下：连续实时字幕（每段完整录像再上传，避免 WebM 分片损坏） ----- */
let liveContAbort = false;
let liveContToken = 0;
let liveContStream = null;
let liveContQueue = Promise.resolve();
let liveRtLastNorm = "";

function teardownLiveContinuousStream() {
  if (!liveContStream) return;
  releaseUserMediaStream(liveContStream, $("#liveVideo"));
  liveContStream = null;
}

function stopLiveContinuousUser() {
  liveContAbort = true;
  liveContQueue = Promise.resolve();
  liveRtLastNorm = "";
  abortActiveSegmentRecording();
  $("#btnLiveStop").disabled = true;
  if (liveLoopPromise) {
    $("#liveStatus").textContent = "已停止录制，正在收尾已录片段…";
  } else {
    cancelJobPoll("liveRt");
    $("#btnLiveStart").disabled = false;
    $("#liveStatus").textContent = "已停";
  }
}

function syncLiveContinuousUi() {
  const on = !!$("#liveContinuousRt")?.checked;
  const opt = $("#liveRtOptions");
  const pan = $("#liveSubtitlePanel");
  if (opt) opt.hidden = !on;
  if (pan) pan.hidden = !on;
  const segRes = $("#liveSegmentResult");
  if (segRes && on) segRes.hidden = true;
  document.querySelectorAll(".live-segment-only, .live-segment-field").forEach((el) => {
    el.classList.toggle("is-disabled", on);
    el.querySelectorAll("input").forEach((inp) => {
      inp.disabled = on;
    });
  });
}
$("#liveContinuousRt")?.addEventListener("change", syncLiveContinuousUi);
syncLiveContinuousUi();

function appendRtRecognitionLines(linesEl, currentEl, clipLabel, text, ok, useLiveNorm = false) {
  const raw = String(text || "").trim();
  if (!raw) return;
  for (const part of splitIntoSpeechLines(raw)) {
    const norm = part.replace(/\s+/g, "");
    const last = useLiveNorm ? liveRtLastNorm : videoRtLastNorm;
    if (!norm || norm === last) continue;
    if (useLiveNorm) liveRtLastNorm = norm;
    else videoRtLastNorm = norm;
    appendSubtitleLine(linesEl, currentEl, clipLabel, part, ok);
  }
}

function appendSubtitleLine(linesEl, currentEl, clipLabel, text, ok) {
  if (!linesEl) return;
  const div = document.createElement("div");
  div.className = ok ? "rt-line rt-line--ok" : "rt-line rt-line--err";
  const t = new Date().toLocaleTimeString();
  div.innerHTML = `<span class="rt-ts">${escapeHtml(t)}</span> <span class="rt-lbl">${escapeHtml(clipLabel)}</span><div class="rt-txt">${escapeHtml(text)}</div>`;
  linesEl.appendChild(div);
  linesEl.scrollTop = linesEl.scrollHeight;
  if (currentEl) currentEl.textContent = ok ? text : `（${text}）`;
  if (linesEl.id === "videoRecognitionLog") syncVideoLogPlaceholder();
}

function shortenTranslateJobError(msg) {
  const s = String(msg || "");
  if (/numpy\.dtype size changed|binary incompatibility/i.test(s)) {
    return "本地 ONNX 与 NumPy 不兼容。请在项目目录执行：pip install \"numpy>=1.26,<2\" 后重启服务。";
  }
  if (/未安装 ffmpeg|ffmpeg.*跳过 Kimi/i.test(s)) {
    return "未安装 ffmpeg（混合会跳过 Kimi）。无硬字幕请用「仅 ONNX」或安装 ffmpeg。";
  }
  if (/识别结果为空/.test(s) && /ONNX|OCR|Kimi/.test(s)) {
    return "本段未识别出文字（无硬字幕时 OCR 无效；请保证双手入画，或改用仅 ONNX）。";
  }
  if (/EBML header|无法打开视频|fail to open/i.test(s)) {
    return "本段录像无效，请 Ctrl+F5 刷新后再试（已修复分片格式问题）。";
  }
  const lines = s
    .split(/\r?\n/)
    .map((ln) => ln.trim())
    .filter(
      (ln) =>
        ln &&
        !ln.includes("onnxruntime") &&
        !ln.includes("Removing initializer") &&
        !ln.startsWith("File ") &&
        !ln.startsWith("Traceback")
    );
  const last = lines[lines.length - 1];
  if (last && last.length < 280) return last.replace(/^RuntimeError:\s*/i, "");
  return s.length > 220 ? `${s.slice(0, 220)}…` : s;
}

async function runLiveContChunk(blob, clipLabel) {
  if (!blob || blob.size < 512) return;
  const modelKey = $("#modelSelectLive")?.value || "csl_daily";
  const appendHist = !!$("#liveRtAppendHistory")?.checked;
  const linesEl = $("#liveSubtitleLines");
  const curEl = $("#liveSubtitleCurrent");
  const mode = getRecognitionMode();
  const pollMs = mode === "hybrid" ? 1500 : mode === "ocr" ? 800 : 1000;
  try {
    const up = await uploadBlob(blob, `live-rt-${Date.now()}.webm`);
    const sliceSec = Math.max(3, (Number($("#liveSliceMs")?.value) || 4000) / 1000);
    const pollSig = takeJobPollSignal("liveRt");
    const res = await startTranslateJobForPath(
      up.savedPath,
      modelKey,
      appendHist,
      pollMs,
      mode,
      (j) => updateJobProgressUi(j),
      sliceSec,
      pollSig,
      true,
    );
    if (res.aborted) return;
    if (res.status === "done" && recognitionResultText(res)) {
      const tx = recognitionResultText(res);
      appendRtRecognitionLines(linesEl, curEl, clipLabel, tx, true, true);
      void speakRecognitionAloud(tx, "zh-CN");
      maybePartnerMirror(tx);
      if (appendHist) {
        await ensureRecognitionHistory(res, {
          want: true,
          sourceFile: up.savedPath,
          modelKey,
          note: "live-rt",
        });
        await loadHistory();
      }
      const st = $("#liveStatus");
      if (st) st.textContent = "识别中…";
    } else {
      appendSubtitleLine(
        linesEl,
        curEl,
        clipLabel,
        shortenTranslateJobError(res.message || "本段未识别出文字"),
        false
      );
    }
  } catch (e) {
    if (liveContAbort || isAbortError(e)) return;
    appendSubtitleLine(linesEl, curEl, clipLabel, shortenTranslateJobError(e.message), false);
  }
}

function enqueueLiveContChunk(blob, clipLabel) {
  liveContQueue = liveContQueue.then(() => runLiveContChunk(blob, clipLabel));
}

/* ----- 传视频：边播边实时字幕（每段完整录像） ----- */
let videoContAbort = false;
let videoContToken = 0;
let videoContLoopPromise = null;
let videoContStream = null;
let videoContQueue = Promise.resolve();
const videoRtJobQueue = [];
let videoRtDrainRunning = false;
let videoRtLastNorm = "";
let videoRtSessionActive = false;

function syncVideoRtControls() {
  const sessionOn = videoRtSessionActive;
  $("#btnVideoRtStart").disabled = sessionOn;
  $("#btnVideoRtStop").disabled = !sessionOn;
}

function maybeFinishVideoRtSession() {
  if (!videoRtSessionActive) return;
  if (videoContLoopPromise || videoRtDrainRunning || videoRtJobQueue.length) return;
  videoRtSessionActive = false;
  setJobProgressBoxVisible(false, "rt");
  syncVideoRtControls();
}

function teardownVideoContinuousStream() {
  releaseCaptureStreamRef();
}

function stopVideoContinuousUser() {
  videoContAbort = true;
  videoContToken += 1;
  videoContQueue = Promise.resolve();
  videoRtJobQueue.length = 0;
  videoRtDrainRunning = false;
  videoRtLastNorm = "";
  videoRtSessionActive = false;
  abortActiveSegmentRecording();
  cancelJobPoll("videoRt");
  teardownVideoContinuousStream();
  const fv = $("#videoFilePreview");
  if (fv) {
    fv.onended = null;
    fv.pause();
  }
  setJobProgressBoxVisible(false, "rt");
  hideMode1JobProgressBox();
  syncVideoRtControls();
  $("#videoRtStatus").textContent = "已停止";
}

async function runVideoContChunk(blob, clipLabel) {
  if (videoContAbort) return;
  if (!blob || blob.size < 512) return;
  const modelKey = $("#modelSelect")?.value || "csl_daily";
  const appendHist = !!$("#videoRtAppendHistory")?.checked;
  const linesEl = videoRecognitionLogEl();
  const mode = getRecognitionMode();
  const pollMs = mode === "hybrid" ? 1500 : mode === "ocr" ? 800 : 1000;
  try {
    const up = await uploadBlob(blob, `video-rt-${Date.now()}.webm`);
    if (videoContAbort) return;
    const raw = Number($("#videoSliceMs")?.value) || 5;
    const sliceSec = raw > 45 ? raw / 1000 : Math.max(6, Math.min(10, raw));
    const pollSig = takeJobPollSignal("videoRt");
    const onRtProgress = (j) => {
      if (videoContAbort) return;
      setJobProgressBoxVisible(true, "rt");
      updateJobProgressUi(j);
    };
    const res = await startTranslateJobForPath(
      up.savedPath,
      modelKey,
      appendHist,
      pollMs,
      mode,
      onRtProgress,
      sliceSec,
      pollSig,
      true,
    );
    if (videoContAbort) return;
    if (res.status === "done" && recognitionResultText(res)) {
      const tx = recognitionResultText(res);
      appendRtRecognitionLines(linesEl, null, clipLabel, tx, true);
      void speakRecognitionAloud(tx, "zh-CN");
      maybePartnerMirror(tx);
      if (appendHist) {
        await ensureRecognitionHistory(res, {
          want: true,
          sourceFile: up.savedPath,
          modelKey,
          note: "video-rt",
        });
        await loadHistory();
      }
      const st = $("#videoRtStatus");
      if (st) st.textContent = "识别中…";
    } else {
      appendSubtitleLine(
        linesEl,
        null,
        clipLabel,
        shortenTranslateJobError(res.message || "本段未识别出文字"),
        false
      );
    }
  } catch (e) {
    if (videoContAbort || isAbortError(e)) return;
    appendSubtitleLine(linesEl, null, clipLabel, shortenTranslateJobError(e.message), false);
  }
}

async function drainVideoRtJobQueue() {
  if (videoRtDrainRunning) return;
  videoRtDrainRunning = true;
  const st = $("#videoRtStatus");
  while (videoRtJobQueue.length && !videoContAbort) {
    const job = videoRtJobQueue.shift();
    if (st) {
      const left = videoRtJobQueue.length;
      st.textContent = left ? `识别中（排队还剩 ${left} 段）…` : "识别中…";
    }
    try {
      await runVideoContChunk(job.blob, job.clipLabel);
    } catch {
      /* runVideoContChunk 已处理错误展示 */
    }
  }
  videoRtDrainRunning = false;
  if (!videoContAbort && st && !videoRtJobQueue.length) {
    const fv = $("#videoFilePreview");
    if (fv?.ended) st.textContent = "视频播完了";
  }
  maybeFinishVideoRtSession();
}

function enqueueVideoContChunk(blob, clipLabel) {
  videoRtJobQueue.push({ blob, clipLabel });
  void drainVideoRtJobQueue();
}

$("#btnLiveStart")?.addEventListener("click", async () => {
  if ($("#liveContinuousRt")?.checked) {
    if (liveLoopPromise) return;
    stopLiveContinuousUser();
    liveContAbort = false;
    liveContToken += 1;
    const token = liveContToken;
    liveContQueue = Promise.resolve();
    const lines = $("#liveSubtitleLines");
    const cur = $("#liveSubtitleCurrent");
    if (lines) lines.innerHTML = "";
    if (cur) cur.textContent = "";
    liveRtLastNorm = "";
    $("#liveLog").textContent = "";
    setLiveSegmentResult("");
    resetSharedRecognitionChrome();
    const sliceMs = Math.max(3000, Math.min(8000, Number($("#liveSliceMs")?.value) || 4000));

    $("#btnLiveStart").disabled = true;
    $("#btnLiveStop").disabled = false;
    $("#liveStatus").textContent = "开摄像头…";

    liveLoopPromise = (async () => {
      let idx = 0;
      try {
        const stream = await navigator.mediaDevices.getUserMedia(getLiveCameraConstraints());
        if (token !== liveContToken || liveContAbort) return;
        liveContStream = stream;
        $("#liveVideo").srcObject = stream;
        void showRecognitionReminders("job");
        const mime = pickMime();
        $("#liveStatus").textContent = `识别中（每约 ${(sliceMs / 1000).toFixed(1)} 秒一小段）…`;
        while (!liveContAbort && token === liveContToken) {
          const blob = await recordOneSegment(stream, sliceMs, mime);
          if (liveContAbort || token !== liveContToken) break;
          if (!blob || blob.size < 512) continue;
          idx += 1;
          enqueueLiveContChunk(blob, `第 ${idx} 段`);
        }
        if (!liveContAbort && token === liveContToken) $("#liveStatus").textContent = "本轮结束";
      } catch (e) {
        if (!liveContAbort && !isIgnorableMediaStreamError(e.message)) {
          appendSubtitleLine(lines, cur, "系统", e.message || "摄像头或录像出错", false);
          $("#liveStatus").textContent = e.message || String(e);
        }
      } finally {
        cancelJobPoll("liveRt");
        teardownLiveContinuousStream();
        $("#btnLiveStart").disabled = false;
        $("#btnLiveStop").disabled = true;
        if (liveContAbort) $("#liveStatus").textContent = "已停";
        liveLoopPromise = null;
      }
    })();
    return;
  }

  if (liveLoopPromise) return;
  liveAbort = false;
  stopLiveContinuousUser();
  resetSharedRecognitionChrome();
  $("#btnLiveStart").disabled = true;
  $("#liveStatus").textContent = "开摄像头…";
  $("#liveLog").textContent = "";
  setLiveSegmentResult("");
  try {
    const stream = await navigator.mediaDevices.getUserMedia(getLiveCameraConstraints());
    mediaStream = stream;
    $("#liveVideo").srcObject = stream;
    $("#btnLiveStop").disabled = false;
    const mime = pickMime();
    const sec = Math.max(4, Math.min(30, Number($("#liveSegmentSec").value) || 6));
    const ms = sec * 1000;
    $("#liveStatus").textContent = `录画中（每段 ${sec} 秒，录完自动识别）`;
    setLiveSegmentResult("等待本段录满后自动识别…", { loading: true });
    void showRecognitionReminders("job");

    liveLoopPromise = (async () => {
      try {
        do {
          if (liveAbort) break;
          const blob = await recordOneSegment(stream, ms, mime);
          if (!blob || blob.size < 512) {
            if (liveAbort) break;
            continue;
          }
          appendLiveLog(`[${new Date().toLocaleTimeString()}] 录好一小段，正在识别…`);
          const up = await uploadBlob(blob, `rt-live-${Date.now()}.webm`);
          const mode = getRecognitionMode();
          const pollMs = mode === "ocr" ? 400 : 600;
          setLiveSegmentResult(
            mode === "ocr"
              ? "正在读画面字幕（通常 5～15 秒）…"
              : "正在识别（纯手语约 20～60 秒；有硬字幕请选「字幕 OCR」更快）…",
            { loading: true }
          );
          $("#liveStatus").textContent = "识别中…";
          const pollSig = takeJobPollSignal("liveSeg");
          const res = await startTranslateJobForPath(
            up.savedPath,
            $("#modelSelectLive").value,
            !!$("#liveAutoJob")?.checked,
            pollMs,
            mode,
            (j) => {
              const msg = String(j.message || j.progressMessage || "").trim();
              if (msg) {
                $("#liveStatus").textContent = msg.length > 36 ? `${msg.slice(0, 35)}…` : msg;
              }
              setLiveSegmentResult(
                msg ? `${msg}…` : "识别进行中，请稍候…",
                { loading: true }
              );
            },
            sec,
            pollSig,
            true,
          );
          if (res.aborted) {
            appendLiveLog("识别已中断");
            break;
          }
          const wantHist = !!$("#liveAutoJob")?.checked;
          if (res.status === "done" && recognitionResultText(res)) {
            const tx = recognitionResultText(res);
            appendLiveLog(`译文：${tx}`);
            setLiveSegmentResult(tx);
            $("#liveStatus").textContent = "本段识别完成";
            void speakRecognitionAloud(tx, "zh-CN");
            maybePartnerMirror(tx);
            if (wantHist) {
              await ensureRecognitionHistory(res, {
                want: true,
                sourceFile: up.savedPath,
                modelKey: $("#modelSelectLive").value,
                note: "live-segment",
              });
            }
          } else {
            const err = res.message || "这次没认出字";
            appendLiveLog(err);
            setLiveSegmentResult(err);
            $("#liveStatus").textContent = "未识别出文字";
          }
          if (wantHist) await loadHistory();
          if (liveAbort || !$("#liveLoop").checked) break;
        } while (!liveAbort);
      } catch (e) {
        if (isAbortError(e)) {
          appendLiveLog("识别已中断");
        } else if (!isIgnorableMediaStreamError(e.message)) {
          appendLiveLog(`出错：${e.message || e}`);
        }
      } finally {
        cancelJobPoll("liveSeg");
        cleanupLive();
        liveLoopPromise = null;
      }
    })();
  } catch (e) {
    $("#liveStatus").textContent = `摄像头打不开：${e.message || e}`;
    $("#btnLiveStart").disabled = false;
    liveLoopPromise = null;
  }
});

$("#btnLiveStop")?.addEventListener("click", () => {
  if ($("#liveContinuousRt")?.checked) {
    liveContToken += 1;
    stopLiveContinuousUser();
    return;
  }
  liveAbort = true;
  abortActiveSegmentRecording();
  $("#btnLiveStop").disabled = true;
  if (liveLoopPromise) {
    $("#liveStatus").textContent = "已停止录制，正在识别本段…";
    appendLiveLog("已停止录制，等待本段识别完成…");
  } else {
    cancelJobPoll("liveSeg");
    cleanupLive();
    $("#btnLiveStart").disabled = false;
    $("#liveStatus").textContent = "已停";
  }
});

$("#btnVideoRtStart")?.addEventListener("click", async () => {
  if (videoContLoopPromise) return;
  const fv = $("#videoFilePreview");
  if (!fv?.src) {
    $("#videoRtStatus").textContent = "请先在上方选择视频文件";
    return;
  }
  stopVideoContinuousUser();
  videoContAbort = false;
  videoContToken += 1;
  const token = videoContToken;
  videoContQueue = Promise.resolve();
  videoRtJobQueue.length = 0;
  videoRtLastNorm = "";
  resetSharedRecognitionChrome();
  clearVideoRtLines();

  videoRtSessionActive = true;
  hideMode1JobProgressBox();
  setJobProgressBoxVisible(true, "rt");
  paintJobProgress("边播识别准备中…", 1, 0, 8, "rt");
  syncVideoRtControls();
  $("#videoRtStatus").textContent = "播放并抓流…";
  const recMode = getRecognitionMode();
  if (recMode === "onnx") {
    showToast(
      "当前为「仅 ONNX」。视频若有底部硬字幕，请改选「仅 OCR」或「混合」；边播已会自动尝试读字幕。",
      "info",
      7500,
    );
  } else if (recMode === "hybrid") {
    showToast("混合模式：边播每段会 ONNX + 读画面字幕，有硬字幕时更准。", "info", 5000);
  }

  videoContLoopPromise = (async () => {
    let idx = 0;
    const linesEl = videoRecognitionLogEl();
    try {
      await fv.play();
      const stream = fv.captureStream();
      if (!stream || !stream.getVideoTracks().length) {
        $("#videoRtStatus").textContent = "当前浏览器无法从视频抓流，请换 Edge 或 Chrome 试试。";
        return;
      }
      if (token !== videoContToken || videoContAbort) return;
      videoContStream = stream;
      void showRecognitionReminders("job");
      const rawSec = Number($("#videoSliceMs")?.value) || 5;
      const secRt = rawSec > 45 ? rawSec / 1000 : Math.max(6, Math.min(10, rawSec));
      const sliceMs = Math.round(secRt * 1000);
      const mime = pickMime();
      $("#videoRtStatus").textContent = `识别中（每约 ${(sliceMs / 1000).toFixed(1)} 秒一小段）…`;
      while (!videoContAbort && token === videoContToken && !fv.ended) {
        const blob = await recordOneSegment(stream, sliceMs, mime);
        if (videoContAbort || token !== videoContToken || fv.ended) break;
        if (!blob || blob.size < 512) continue;
        idx += 1;
        enqueueVideoContChunk(blob, `第 ${idx} 段`);
      }
      if (!videoContAbort && token === videoContToken) {
        $("#videoRtStatus").textContent = fv.ended ? "视频播完了" : "已停止";
      }
    } catch (e) {
      if (!videoContAbort && !isIgnorableMediaStreamError(e.message)) {
        appendSubtitleLine(linesEl, null, "系统", e.message || "播放或录像出错", false);
        $("#videoRtStatus").textContent = e.message || String(e);
      }
    } finally {
      fv.onended = null;
      teardownVideoContinuousStream();
      videoContLoopPromise = null;
      maybeFinishVideoRtSession();
    }
  })();
});

$("#btnVideoRtStop")?.addEventListener("click", () => {
  stopVideoContinuousUser();
});

function attachHandwritingCanvas(canvas) {
  const ctx = canvas.getContext("2d");
  let drawing = false;
  let hasInk = false;
  const resize = () => {
    const rect = canvas.getBoundingClientRect();
    const dpr = window.devicePixelRatio || 1;
    canvas.width = Math.max(1, Math.floor(rect.width * dpr));
    canvas.height = Math.max(1, Math.floor(rect.height * dpr));
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.lineWidth = 3;
    ctx.lineCap = "round";
    ctx.lineJoin = "round";
    ctx.strokeStyle = "#1a1a1a";
  };
  resize();
  new ResizeObserver(resize).observe(canvas);
  const pos = (e) => {
    const r = canvas.getBoundingClientRect();
    const t = e.touches?.[0];
    const cx = t ? t.clientX : e.clientX;
    const cy = t ? t.clientY : e.clientY;
    return { x: cx - r.left, y: cy - r.top };
  };
  const start = (e) => {
    drawing = true;
    const p = pos(e);
    ctx.beginPath();
    ctx.moveTo(p.x, p.y);
    e.preventDefault();
  };
  const move = (e) => {
    if (!drawing) return;
    const p = pos(e);
    ctx.lineTo(p.x, p.y);
    ctx.stroke();
    hasInk = true;
    e.preventDefault();
  };
  const end = () => {
    drawing = false;
  };
  canvas.addEventListener("mousedown", start);
  canvas.addEventListener("mousemove", move);
  window.addEventListener("mouseup", end);
  canvas.addEventListener("touchstart", start, { passive: false });
  canvas.addEventListener("touchmove", move, { passive: false });
  canvas.addEventListener("touchend", end);
  return {
    clear() {
      const r = canvas.getBoundingClientRect();
      ctx.clearRect(0, 0, r.width, r.height);
      hasInk = false;
    },
    isBlank() {
      return !hasInk;
    },
    toDataUrl() {
      return canvas.toDataURL("image/png");
    },
  };
}

let speakHandPad = null;
let manualHandPad = null;

async function recognizeHandPad(pad, statusEl) {
  if (!pad) return "";
  if (pad.isBlank?.()) {
    showToast("请先在手写区写字", "warn", 3500);
    return "";
  }
  try {
    const st = await api("/api/handwriting/status");
    if (st.engine === "none") {
      showToast(
        "手写未就绪：请在 .env 配置 ZHIPU_API_KEY 并 pip install zai-sdk，然后重启 uvicorn。",
        "error",
        7000
      );
      return "";
    }
  } catch {
    /* 旧服务无此接口时继续尝试识别 */
  }
  if (statusEl) statusEl.textContent = "识别中…";
  try {
    const data = await api("/api/handwriting/recognize", {
      method: "POST",
      body: JSON.stringify({ imageBase64: pad.toDataUrl() }),
    });
    return (data.text || "").trim();
  } catch (e) {
    showToast(e?.message || "手写识别失败", "error", 5500);
    return "";
  } finally {
    if (statusEl) statusEl.textContent = "";
  }
}

function setSpeakInputMode(mode) {
  const kb = mode === "keyboard";
  $("#speakInputKeyboard").hidden = !kb;
  $("#speakHandwritePanel").hidden = kb;
  $("#btnInputKeyboard")?.classList.toggle("is-active", kb);
  $("#btnInputHandwrite")?.classList.toggle("is-active", !kb);
  $("#btnInputKeyboard")?.setAttribute("aria-selected", kb ? "true" : "false");
  $("#btnInputHandwrite")?.setAttribute("aria-selected", kb ? "false" : "true");
}

function syncHandwriteHint() {
  const el = $("#handwriteHint");
  if (!el) return;
  if (handwritingZhipuReady) {
    el.textContent =
      "在下方写字，点「识别填入」。本地 OCR 不清时会自动用智谱 GLM 识图（已配置）。";
  } else {
    el.textContent =
      "在下方写字，点「识别填入」。若常失败，请在 .env 配置 ZHIPU_API_KEY 并重启服务。";
  }
}

function initHandwritingPads() {
  void refreshTtsStatus().then(() => syncHandwriteHint());
  const speakCanvas = $("#speakHandCanvas");
  if (speakCanvas && !speakHandPad) {
    speakHandPad = attachHandwritingCanvas(speakCanvas);
    $("#btnInputKeyboard")?.addEventListener("click", () => setSpeakInputMode("keyboard"));
    $("#btnInputHandwrite")?.addEventListener("click", () => setSpeakInputMode("handwrite"));
    $("#btnHandClear")?.addEventListener("click", () => speakHandPad?.clear());
    $("#btnHandRecognize")?.addEventListener("click", async () => {
      try {
        const text = await recognizeHandPad(speakHandPad, $("#handwriteStatus"));
        if (!text) {
          showToast("未识别到文字，请写大一些再试。", "warn");
          return;
        }
        const ta = $("#pSpeak");
        if (ta) ta.value = ((ta.value || "") + text).trim();
        setSpeakInputMode("keyboard");
        showToast(`已填入：${text}`, "info", 2800);
      } catch (e) {
        showToast(e.message || "识别失败", "error", 6000);
      }
    });
    $("#btnHandSpeak")?.addEventListener("click", async () => {
      try {
        const text = await recognizeHandPad(speakHandPad, $("#handwriteStatus"));
        if (!text) {
          showToast("请先手写并识别成功。", "warn");
          return;
        }
        const ta = $("#pSpeak");
        if (ta) ta.value = text;
        setSpeakInputMode("keyboard");
        await speakUtterance(text, currentComposerSpeechLang());
      } catch (e) {
        showToast(e.message || "朗读失败", "error", 6000);
      }
    });
  }
  const manualCanvas = $("#manualHandCanvas");
  if (manualCanvas && !manualHandPad) {
    manualHandPad = attachHandwritingCanvas(manualCanvas);
    $("#btnManualHandClear")?.addEventListener("click", () => manualHandPad?.clear());
    $("#btnManualHandRecognize")?.addEventListener("click", async () => {
      try {
        const text = await recognizeHandPad(manualHandPad, null);
        if (!text) {
          showToast("未识别到文字。", "warn");
          return;
        }
        $("#manualText").value = text;
        showToast(`已填入：${text}`, "info", 2800);
      } catch (e) {
        showToast(e.message || "识别失败", "error", 6000);
      }
    });
  }
  setSpeakInputMode("keyboard");
}

applyFontFromStorage();
initSession().catch((e) => {
  console.error(e);
  setHealth(false, "加载失败");
});
