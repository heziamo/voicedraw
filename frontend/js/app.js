'use strict';
/* =================================================================
 * 声笔 VoiceDraw — 前端（瘦客户端）
 * 职责：麦克风采集 + Web Speech 识别 + 调后端 API + 渲染场景 + TTS 播报
 * NLU 解析、状态、撤销/重做全部在 Python 后端完成。
 * 画布坐标系：后端逻辑坐标 1200×750，前端按 contain 方式等比缩放渲染。
 * ================================================================= */

const API = location.origin;
let sessionId = null;
let scene = { shapes: [], bg: '#fafafa' };
let selected = [];
let flags = { muted: false, tts_on: true };
let LOGICAL = { w: 1200, h: 750 };
const ui = {
  started: false, listening: false, speaking: false,
};

/* ============ 渲染层 ============ */
const boardEl = document.getElementById('board');
const ctx = boardEl.getContext('2d');
let W = 0, H = 0, DPR = 1;
// 逻辑坐标 → 画布像素的变换（contain：等比缩放并居中）
let view = { scale: 1, ox: 0, oy: 0 };

function resizeBoard() {
  const r = boardEl.parentElement.getBoundingClientRect();
  DPR = window.devicePixelRatio || 1;
  W = Math.max(100, r.width); H = Math.max(100, r.height);
  boardEl.width = W * DPR; boardEl.height = H * DPR;
  ctx.setTransform(DPR, 0, 0, DPR, 0, 0);
  const scale = Math.min(W / LOGICAL.w, H / LOGICAL.h);
  view = { scale, ox: (W - LOGICAL.w * scale) / 2, oy: (H - LOGICAL.h * scale) / 2 };
  render();
}
window.addEventListener('resize', resizeBoard);

function isDark(hex) {
  const n = parseInt(hex.slice(1), 16);
  const lum = .299 * ((n >> 16) & 255) + .587 * ((n >> 8) & 255) + .114 * (n & 255);
  return lum < 128;
}

function render() {
  ctx.clearRect(0, 0, W, H);
  // 画布外区域（letterbox）填工具底色，逻辑画布区域填场景背景色
  ctx.fillStyle = '#0b0b0c'; ctx.fillRect(0, 0, W, H);
  ctx.save();
  ctx.translate(view.ox, view.oy); ctx.scale(view.scale, view.scale);
  ctx.fillStyle = scene.bg; ctx.fillRect(0, 0, LOGICAL.w, LOGICAL.h);
  // 点阵网格
  ctx.fillStyle = isDark(scene.bg) ? 'rgba(255,255,255,.10)' : 'rgba(1,1,2,.10)';
  for (let x = 24; x < LOGICAL.w; x += 32)
    for (let y = 24; y < LOGICAL.h; y += 32) ctx.fillRect(x, y, 1.6, 1.6);
  for (const s of scene.shapes) drawShape(ctx, s);
  for (const s of scene.shapes) if (selected.includes(s.id)) drawSelection(s);
  ctx.restore();
  updateChrome();
}

function drawShape(c, s) {
  c.save();
  c.translate(s.x, s.y); c.rotate((s.rot || 0) * Math.PI / 180);
  c.fillStyle = s.color; c.strokeStyle = s.color;
  c.lineWidth = Math.max(3, s.size * .09);
  const r = s.size, fill = s.style !== 'stroke';
  const done = () => fill ? c.fill() : c.stroke();
  switch (s.type) {
    case 'circle': c.beginPath(); c.arc(0, 0, r, 0, Math.PI * 2); done(); break;
    case 'ellipse': c.beginPath(); c.ellipse(0, 0, r * 1.3, r * .8, 0, 0, Math.PI * 2); done(); break;
    case 'square': { const a = r * 1.7; c.beginPath(); c.rect(-a / 2, -a / 2, a, a); done(); break; }
    case 'rect': { const w = r * 2.4, h = r * 1.4; c.beginPath(); c.rect(-w / 2, -h / 2, w, h); done(); break; }
    case 'triangle':
      c.beginPath(); c.moveTo(0, -r); c.lineTo(r * .87, r * .5); c.lineTo(-r * .87, r * .5);
      c.closePath(); done(); break;
    case 'star':
      c.beginPath();
      for (let i = 0; i < 10; i++) {
        const rad = i % 2 === 0 ? r : r * .45, a = -Math.PI / 2 + i * Math.PI / 5;
        const x = Math.cos(a) * rad, y = Math.sin(a) * rad;
        i === 0 ? c.moveTo(x, y) : c.lineTo(x, y);
      }
      c.closePath(); done(); break;
    case 'heart':
      c.beginPath(); c.moveTo(0, r * .95);
      c.bezierCurveTo(-r * 1.1, r * .15, -r * .95, -r * .8, 0, -r * .25);
      c.bezierCurveTo(r * .95, -r * .8, r * 1.1, r * .15, 0, r * .95);
      c.closePath(); done(); break;
    case 'line': { const L = r * 3, h = Math.max(4, r * .12); c.fillRect(-L / 2, -h / 2, L, h); break; }
    case 'vline': { const L = r * 3, w = Math.max(4, r * .12); c.fillRect(-w / 2, -L / 2, w, L); break; }
    case 'arrow': {
      const L = r * 3, sh = Math.max(5, r * .22), hw = r * .7, hl = r * .8;
      c.beginPath();
      c.moveTo(-L / 2, -sh / 2); c.lineTo(L / 2 - hl, -sh / 2); c.lineTo(L / 2 - hl, -hw / 2);
      c.lineTo(L / 2, 0); c.lineTo(L / 2 - hl, hw / 2); c.lineTo(L / 2 - hl, sh / 2); c.lineTo(-L / 2, sh / 2);
      c.closePath(); c.fill(); break;
    }
    case 'text':
      c.font = '600 ' + (s.size * 1.2) + "px Inter,'PingFang SC','Microsoft YaHei',sans-serif";
      c.textAlign = 'center'; c.textBaseline = 'middle';
      fill ? c.fillText(s.text, 0, 0) : c.strokeText(s.text, 0, 0);
      break;
  }
  c.restore();
}

function bbox(s) {
  const r = s.size;
  switch (s.type) {
    case 'circle': return { w: r, h: r };
    case 'ellipse': return { w: r * 1.3, h: r * .8 };
    case 'square': return { w: r * .85, h: r * .85 };
    case 'rect': return { w: r * 1.2, h: r * .7 };
    case 'triangle': case 'star': return { w: r, h: r };
    case 'heart': return { w: r * 1.1, h: r };
    case 'line': return { w: r * 1.5, h: Math.max(4, r * .12) };
    case 'vline': return { w: Math.max(4, r * .12), h: r * 1.5 };
    case 'arrow': return { w: r * 1.5, h: r * .4 };
    case 'text': {
      ctx.font = '600 ' + (s.size * 1.2) + "px Inter,'PingFang SC',sans-serif";
      return { w: ctx.measureText(s.text || '').width / 2 + 6, h: s.size * .75 };
    }
    default: return { w: r, h: r };
  }
}

function drawSelection(s) {
  const b = bbox(s), pad = 9;
  ctx.save();
  ctx.translate(s.x, s.y);
  ctx.strokeStyle = '#5e6ad2'; ctx.lineWidth = 1.5 / view.scale; ctx.setLineDash([5, 4]);
  ctx.strokeRect(-b.w - pad, -b.h - pad, (b.w + pad) * 2, (b.h + pad) * 2);
  ctx.setLineDash([]);
  ctx.fillStyle = '#5e6ad2';
  const hs = 6 / view.scale;
  for (const [hx, hy] of [[-1, -1], [1, -1], [-1, 1], [1, 1]])
    ctx.fillRect(hx * (b.w + pad) - hs / 2, hy * (b.h + pad) - hs / 2, hs, hs);
  ctx.restore();
}

/* ============ API 通信 ============ */
async function api(method, path, body) {
  const opt = { method, headers: { 'Content-Type': 'application/json' } };
  if (body) opt.body = JSON.stringify(body);
  const res = await fetch(API + path, opt);
  if (!res.ok) throw new Error('HTTP ' + res.status);
  return res.json();
}

async function ensureSession() {
  const saved = localStorage.getItem('voicedraw_session');
  if (saved) {
    try {
      const data = await api('GET', '/api/sessions/' + saved);
      applyState(data); sessionId = saved;
      setSessionPill(true, '会话已恢复');
      return;
    } catch (_) { /* 会话过期，新建 */ }
  }
  const data = await api('POST', '/api/sessions');
  sessionId = data.session_id;
  localStorage.setItem('voicedraw_session', sessionId);
  applyState(data);
  setSessionPill(true, '会话就绪');
}

function applyState(data) {
  scene = data.scene; selected = data.selected || [];
  flags = data.flags || flags;
  if (data.logical) LOGICAL = { w: data.logical.w, h: data.logical.h };
  resizeBoard();
}

/* ============ 指令执行（经后端） ============ */
async function handleUtterance(raw) {
  if (!sessionId) return;
  const t0 = performance.now();
  let data;
  try {
    data = await api('POST', '/api/sessions/' + sessionId + '/commands', { text: raw });
  } catch (e) {
    logItem(raw, '后端请求失败：' + e.message, 'err');
    return;
  }
  const ms = Math.round(performance.now() - t0);
  applyState(data);
  const results = data.results || [];
  // 静音模式下后端会返回空 results
  if (!results.length) return;
  const msgs = [];
  for (const r of results) {
    msgs.push(r.msg);
    logItem(r.clause || raw, r.msg, r.ok ? 'ok' : 'err', ms);
    handleAction(r.action);
  }
  setLatency(ms);
  const summary = msgs.join('；');
  speak(summary.length > 56 ? summary.slice(0, 54) + '…' : summary);
}

function handleAction(action) {
  if (!action) return;
  if (action === 'help_open') helpEl.classList.remove('hidden');
  else if (action === 'help_close') helpEl.classList.add('hidden');
  else if (action === 'export') exportPNG();
  else if (action === 'tts_off') flags.tts_on = false;
  else if (action === 'tts_on') flags.tts_on = true;
}

/* ============ PNG 导出（前端按场景重绘 2× 分辨率） ============ */
function exportPNG() {
  const sc = 2;
  const tmp = document.createElement('canvas');
  tmp.width = LOGICAL.w * sc; tmp.height = LOGICAL.h * sc;
  const c = tmp.getContext('2d'); c.scale(sc, sc);
  c.fillStyle = scene.bg; c.fillRect(0, 0, LOGICAL.w, LOGICAL.h);
  for (const s of scene.shapes) drawShape(c, s);
  tmp.toBlob(b => {
    const a = document.createElement('a');
    a.href = URL.createObjectURL(b); a.download = 'voicedraw-' + Date.now() + '.png';
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 5000);
  });
}

/* ============ 语音识别 + 合成 ============ */
const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
let rec = null;

function startRecognition() {
  rec = new SR();
  rec.lang = 'zh-CN'; rec.continuous = true; rec.interimResults = true;
  rec.onresult = e => {
    if (ui.speaking) return; // 回声抑制：播报期间忽略识别
    let interim = '', final = '';
    for (let i = e.resultIndex; i < e.results.length; i++) {
      const r = e.results[i];
      if (r.isFinal) final += r[0].transcript; else interim += r[0].transcript;
    }
    if (interim) showTranscript(interim, false);
    if (final.trim()) { showTranscript(final, true); handleUtterance(final); }
  };
  rec.onerror = e => {
    if (e.error === 'not-allowed' || e.error === 'service-not-allowed') {
      ui.listening = false;
      setMicState('err', '麦克风被拒绝', '请在浏览器允许麦克风后刷新页面');
    }
  };
  rec.onend = () => {
    if (ui.listening && !ui.speaking) setTimeout(() => { try { rec.start(); } catch (_) {} }, 200);
  };
  try { rec.start(); ui.listening = true; } catch (_) {}
}

function speak(text) {
  if (!flags.tts_on || !text) return;
  speechSynthesis.cancel();
  const u = new SpeechSynthesisUtterance(text);
  u.lang = 'zh-CN'; u.rate = 1.15; u.volume = .9;
  const v = speechSynthesis.getVoices().find(v => /zh|Chinese/i.test(v.lang));
  if (v) u.voice = v;
  ui.speaking = true; updateChrome();
  try { rec && rec.abort(); } catch (_) {} // 防止 TTS 被麦克风听见形成回声循环
  const resume = () => {
    ui.speaking = false; updateChrome();
    if (ui.listening) setTimeout(() => { try { rec.start(); } catch (_) {} }, 250);
  };
  u.onend = resume; u.onerror = resume;
  speechSynthesis.speak(u);
}

/* ============ UI 反馈 ============ */
const helpEl = document.getElementById('help-overlay');
const logEl = document.getElementById('log');
const transcriptEl = document.getElementById('transcript');
const hintEl = document.getElementById('hint');
const hintCmdEl = document.getElementById('hint-cmd');
let lastLatency = 0;

const HINTS = ['“画一个红色的圆”', '“画三个并排的蓝色方块”', '“在左上角画一个五角星”',
  '“写上你好世界”', '“把背景换成黑色”', '“画一个空心的绿色三角形”'];
let hintIdx = 0;
setInterval(() => {
  if (!scene.shapes.length) { hintIdx = (hintIdx + 1) % HINTS.length; hintCmdEl.textContent = HINTS[hintIdx]; }
}, 4000);

function showTranscript(text, isFinal) {
  transcriptEl.textContent = text;
  transcriptEl.classList.toggle('final', isFinal);
}

function logItem(said, res, kind, ms) {
  const empty = logEl.querySelector('.log-empty'); if (empty) empty.remove();
  const el = document.createElement('div');
  el.className = 'log-item ' + kind;
  const time = new Date().toTimeString().slice(0, 8);
  const lat = ms != null ? ' · ' + ms + 'ms' : '';
  el.innerHTML = '<span class="log-time">' + time + lat + '</span>'
    + '<div class="log-said">“' + escapeHtml(said) + '”</div>'
    + '<div class="log-res">' + escapeHtml(res) + '</div>';
  logEl.prepend(el);
  while (logEl.children.length > 120) logEl.lastChild.remove();
}
function escapeHtml(s) { return String(s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c])); }

function setMicState(mode, label, desc) {
  document.getElementById('mic-state').textContent = label;
  document.getElementById('mic-desc').textContent = desc;
  document.getElementById('mic-ring').classList.toggle('on', mode === 'on');
  document.getElementById('bars').classList.toggle('on', mode === 'on');
  const pill = document.getElementById('pill-mic');
  pill.className = 'pill' + (mode === 'on' ? ' accent' : mode === 'live' ? ' live' : mode === 'err' ? ' err' : '');
  pill.innerHTML = '<span class="dot"></span>' + label;
}
function setSessionPill(ok, label) {
  const pill = document.getElementById('pill-session');
  pill.className = 'pill' + (ok ? ' live' : ' err');
  pill.innerHTML = '<span class="dot"></span>' + label;
}
function setLatency(ms) { lastLatency = ms; }

function updateChrome() {
  const n = scene.shapes.length;
  document.getElementById('pill-shapes').innerHTML = '<span class="dot"></span>' + n + ' 个图形';
  document.getElementById('pill-tts').innerHTML = '<span class="dot"></span>播报' + (flags.tts_on ? '开' : '关');
  document.getElementById('canvas-meta').textContent =
    (n ? n + ' 个图形 · ' + selected.length + ' 个选中' : '') + (lastLatency ? '　·　后端 ' + lastLatency + 'ms' : '');
  hintEl.style.display = n ? 'none' : 'flex';
  hintEl.classList.toggle('dark-bg', isDark(scene.bg));
  if (!ui.started) return;
  if (ui.speaking) setMicState('live', '播报中', '语音反馈播放中，暂停识别');
  else if (flags.muted) setMicState('idle', '已暂停', '说「继续聆听」恢复');
  else if (ui.listening) setMicState('on', '聆听中', '请说出绘图指令');
}

/* ============ 启动 ============ */
const startOverlay = document.getElementById('start-overlay');
const startBtn = document.getElementById('btn-start');
const startWarn = document.getElementById('start-warn');

if (!SR) {
  startBtn.disabled = true;
  startWarn.style.display = 'block';
  startWarn.textContent = '当前浏览器不支持 Web Speech API 语音识别，请改用桌面版 Chrome 或 Edge。';
}
startBtn.addEventListener('click', () => {
  ui.started = true;
  startOverlay.classList.add('hidden');
  startRecognition();
  setMicState('on', '聆听中', '请说出绘图指令');
  speak('你好，我在听。试试说：画一个红色的圆');
});

// 页面加载即建立/恢复会话（不需要麦克风权限）
ensureSession().catch(e => {
  setSessionPill(false, '后端未连接');
  startWarn.style.display = 'block';
  startWarn.textContent = '无法连接后端服务：' + e.message;
});
resizeBoard();
