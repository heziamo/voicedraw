'use strict';
/* =================================================================
 * 声笔 VoiceDraw — 前端（瘦客户端）
 * 浏览器：麦克风 + Web Speech 识别 + 渲染 + TTS；NLU/状态全在后端。
 * 画布逻辑坐标 1200×750，前端 contain 等比缩放 + 用户缩放。
 * 工具栏按钮是「冗余可达性」——点击走与语音完全相同的指令路径；语音才是主路径。
 * ================================================================= */

const API = location.origin;
let sessionId = null;
let scene = { shapes: [], bg: '#fafafa' };
let selected = [];
let flags = { muted: false, tts_on: true, can_undo: false, can_redo: false };
let LOGICAL = { w: 1200, h: 750 };
const ui = { started: false, listening: false, speaking: false };
const viewCfg = { userZoom: 1, showGrid: true };
// 画布绘制配色（浅色主题：白板浮在浅灰工作区）
const CANVAS = {
  area: '#eef0f3', shadow: 'rgba(20,22,30,.16)', border: 'rgba(0,0,0,.10)',
  accent: '#3b6cf6', imgPh: '#eef0f3', imgPhText: '#9aa0a6',
};

const LABELS = {
  circle: '圆形', square: '正方形', rect: '长方形', triangle: '三角形', star: '五角星',
  heart: '心形', line: '直线', vline: '竖线', arrow: '箭头', ellipse: '椭圆', text: '文字',
  hexagon: '六边形', pentagon: '五边形', diamond: '菱形', ring: '圆环', moon: '月亮',
  cloud: '云朵', lightning: '闪电', cross: '十字', speech: '对话气泡', smile: '笑容',
  image: 'AI 图片',
};

/* 生成图片的位图缓存：src → HTMLImageElement（加载完触发重绘） */
const imgCache = new Map();
function getImage(src) {
  let rec = imgCache.get(src);
  if (!rec) {
    rec = { img: new Image(), ready: false };
    rec.img.onload = () => { rec.ready = true; render(); };
    rec.img.src = src;
    imgCache.set(src, rec);
  }
  return rec;
}
const SHAPE_LIB = ['圆', '方块', '三角形', '五角星', '六边形', '菱形', '心形', '圆环',
  '月亮', '云朵', '闪电', '箭头', '笑脸', '房子', '太阳', '树', '花'];

/* ============ 画布与视图 ============ */
const boardEl = document.getElementById('board');
const ctx = boardEl.getContext('2d');
let W = 0, H = 0, DPR = 1, containScale = 1;
let view = { scale: 1, ox: 0, oy: 0 };

function resizeBoard() {
  const r = boardEl.parentElement.getBoundingClientRect();
  DPR = window.devicePixelRatio || 1;
  W = Math.max(100, r.width); H = Math.max(100, r.height);
  boardEl.width = W * DPR; boardEl.height = H * DPR;
  ctx.setTransform(DPR, 0, 0, DPR, 0, 0);
  containScale = Math.min(W / LOGICAL.w, H / LOGICAL.h) * 0.92;
  const scale = containScale * viewCfg.userZoom;
  view = { scale, ox: (W - LOGICAL.w * scale) / 2, oy: (H - LOGICAL.h * scale) / 2 };
  document.getElementById('zoom-val').textContent = Math.round(scale * 100) + '%';
  render();
}
window.addEventListener('resize', resizeBoard);

function isDark(hex) {
  const n = parseInt(hex.slice(1), 16);
  return (.299 * ((n >> 16) & 255) + .587 * ((n >> 8) & 255) + .114 * (n & 255)) < 128;
}

function render() {
  ctx.clearRect(0, 0, W, H);
  ctx.fillStyle = CANVAS.area; ctx.fillRect(0, 0, W, H);
  ctx.save();
  ctx.translate(view.ox, view.oy); ctx.scale(view.scale, view.scale);
  // 画板阴影 + 背景
  ctx.shadowColor = CANVAS.shadow; ctx.shadowBlur = 26 / view.scale; ctx.shadowOffsetY = 6 / view.scale;
  ctx.fillStyle = scene.bg; ctx.fillRect(0, 0, LOGICAL.w, LOGICAL.h);
  ctx.shadowColor = 'transparent'; ctx.shadowBlur = 0; ctx.shadowOffsetY = 0;
  if (viewCfg.showGrid) {
    ctx.fillStyle = isDark(scene.bg) ? 'rgba(255,255,255,.10)' : 'rgba(1,1,2,.08)';
    for (let x = 30; x < LOGICAL.w; x += 36)
      for (let y = 30; y < LOGICAL.h; y += 36) ctx.fillRect(x, y, 1.6, 1.6);
  }
  for (const s of scene.shapes) drawShape(ctx, s);
  for (const s of scene.shapes) if (selected.includes(s.id)) drawSelection(s);
  // 画板边框
  ctx.strokeStyle = CANVAS.border; ctx.lineWidth = 1 / view.scale;
  ctx.strokeRect(0, 0, LOGICAL.w, LOGICAL.h);
  ctx.restore();
}

function drawShape(c, s) {
  c.save();
  c.globalAlpha = s.opacity == null ? 1 : s.opacity;
  c.translate(s.x, s.y);
  c.rotate((s.rot || 0) * Math.PI / 180);
  c.scale(s.flipX ? -1 : 1, s.flipY ? -1 : 1);
  c.fillStyle = s.color; c.strokeStyle = s.color;
  c.lineWidth = Math.max(3, s.size * .09) * (s.weight || 1);
  c.lineJoin = 'round'; c.lineCap = 'round';
  const r = s.size, fill = s.style !== 'stroke';
  const done = () => fill ? c.fill() : c.stroke();
  const poly = (n, rot) => {
    c.beginPath();
    for (let i = 0; i < n; i++) {
      const a = rot + i * 2 * Math.PI / n;
      const x = Math.cos(a) * r, y = Math.sin(a) * r;
      i ? c.lineTo(x, y) : c.moveTo(x, y);
    }
    c.closePath(); done();
  };
  switch (s.type) {
    case 'circle': c.beginPath(); c.arc(0, 0, r, 0, 7); done(); break;
    case 'ellipse': c.beginPath(); c.ellipse(0, 0, r * 1.3, r * .8, 0, 0, 7); done(); break;
    case 'square': { const a = r * 1.7; c.beginPath(); c.rect(-a / 2, -a / 2, a, a); done(); break; }
    case 'rect': { const w = r * 2.4, h = r * 1.4; c.beginPath(); c.rect(-w / 2, -h / 2, w, h); done(); break; }
    case 'triangle': c.beginPath(); c.moveTo(0, -r); c.lineTo(r * .87, r * .5); c.lineTo(-r * .87, r * .5); c.closePath(); done(); break;
    case 'pentagon': poly(5, -Math.PI / 2); break;
    case 'hexagon': poly(6, -Math.PI / 2); break;
    case 'diamond': c.beginPath(); c.moveTo(0, -r); c.lineTo(r * .8, 0); c.lineTo(0, r); c.lineTo(-r * .8, 0); c.closePath(); done(); break;
    case 'star':
      c.beginPath();
      for (let i = 0; i < 10; i++) {
        const rad = i % 2 ? r * .45 : r, a = -Math.PI / 2 + i * Math.PI / 5;
        const x = Math.cos(a) * rad, y = Math.sin(a) * rad; i ? c.lineTo(x, y) : c.moveTo(x, y);
      }
      c.closePath(); done(); break;
    case 'heart':
      c.beginPath(); c.moveTo(0, r * .95);
      c.bezierCurveTo(-r * 1.1, r * .15, -r * .95, -r * .8, 0, -r * .25);
      c.bezierCurveTo(r * .95, -r * .8, r * 1.1, r * .15, 0, r * .95);
      c.closePath(); done(); break;
    case 'ring':
      c.beginPath(); c.arc(0, 0, r, 0, 7);
      if (fill) { c.arc(0, 0, r * .55, 0, 7, true); c.fill('evenodd'); }
      else c.stroke();
      break;
    case 'moon':
      c.beginPath(); c.arc(0, 0, r, 0, 7);
      c.arc(r * .45, -r * .15, r * .85, 0, 7, true); c.fill('evenodd'); break;
    case 'cloud': {
      c.beginPath();
      c.arc(-r * .55, r * .1, r * .5, 0, 7); c.arc(0, -r * .25, r * .62, 0, 7);
      c.arc(r * .55, r * .1, r * .5, 0, 7); c.rect(-r * 1.05, r * .1, r * 2.1, r * .5);
      fill ? c.fill() : c.stroke(); break;
    }
    case 'lightning':
      c.beginPath();
      c.moveTo(r * .15, -r); c.lineTo(-r * .5, r * .15); c.lineTo(-r * .02, r * .15);
      c.lineTo(-r * .2, r); c.lineTo(r * .55, -r * .2); c.lineTo(r * .05, -r * .2);
      c.closePath(); done(); break;
    case 'cross': {
      const a = r * .32;
      c.beginPath();
      c.moveTo(-a, -r); c.lineTo(a, -r); c.lineTo(a, -a); c.lineTo(r, -a); c.lineTo(r, a);
      c.lineTo(a, a); c.lineTo(a, r); c.lineTo(-a, r); c.lineTo(-a, a); c.lineTo(-r, a);
      c.lineTo(-r, -a); c.lineTo(-a, -a); c.closePath(); done(); break;
    }
    case 'speech': {
      const w = r * 1.2, h = r, rad = r * .28;
      c.beginPath();
      c.moveTo(-w + rad, -h);
      c.arcTo(w, -h, w, -h + rad, rad); c.arcTo(w, h, w - rad, h, rad);
      c.lineTo(-w * .3, h); c.lineTo(-w * .55, h + r * .45); c.lineTo(-w * .62, h);
      c.arcTo(-w, h, -w, h - rad, rad); c.arcTo(-w, -h, -w + rad, -h, rad);
      c.closePath(); done(); break;
    }
    case 'smile':
      c.beginPath(); c.arc(0, -r * .25, r, Math.PI * .18, Math.PI * .82); c.stroke(); break;
    case 'line': { const L = r * 3, h = Math.max(4, r * .12) * (s.weight || 1); c.fillRect(-L / 2, -h / 2, L, h); break; }
    case 'vline': { const L = r * 3, w = Math.max(4, r * .12) * (s.weight || 1); c.fillRect(-w / 2, -L / 2, w, L); break; }
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
      fill ? c.fillText(s.text, 0, 0) : c.strokeText(s.text, 0, 0); break;
    case 'image': {
      const w = r * 2, h = w / (s.aspect || 1), rec = getImage(s.src);
      if (rec.ready) {
        c.drawImage(rec.img, -w / 2, -h / 2, w, h);
      } else {
        c.fillStyle = CANVAS.imgPh; c.fillRect(-w / 2, -h / 2, w, h);
        c.fillStyle = CANVAS.imgPhText; c.font = '600 ' + (r * .14) + "px Inter,sans-serif";
        c.textAlign = 'center'; c.textBaseline = 'middle'; c.fillText('图片加载中…', 0, 0);
      }
      break;
    }
  }
  c.restore();
}

function bbox(s) {
  const r = s.size, t = s.type;
  if (t === 'ellipse') return { w: r * 1.3, h: r * .8 };
  if (t === 'square') return { w: r * .85, h: r * .85 };
  if (t === 'rect') return { w: r * 1.2, h: r * .7 };
  if (t === 'heart') return { w: r * 1.1, h: r };
  if (t === 'cloud') return { w: r * 1.3, h: r * .8 };
  if (t === 'speech') return { w: r * 1.2, h: r };
  if (t === 'line') return { w: r * 1.5, h: Math.max(4, r * .12) };
  if (t === 'vline') return { w: Math.max(4, r * .12), h: r * 1.5 };
  if (t === 'arrow') return { w: r * 1.5, h: r * .4 };
  if (t === 'image') return { w: r, h: r / (s.aspect || 1) };
  if (t === 'text') { ctx.font = '600 ' + (s.size * 1.2) + "px Inter,'PingFang SC',sans-serif"; return { w: ctx.measureText(s.text || '').width / 2 + 6, h: s.size * .75 }; }
  return { w: r, h: r };
}

function drawSelection(s) {
  const b = bbox(s), pad = 9;
  ctx.save(); ctx.translate(s.x, s.y);
  ctx.strokeStyle = CANVAS.accent; ctx.lineWidth = 1.5 / view.scale; ctx.setLineDash([5, 4]);
  ctx.strokeRect(-b.w - pad, -b.h - pad, (b.w + pad) * 2, (b.h + pad) * 2);
  ctx.setLineDash([]); ctx.fillStyle = CANVAS.accent;
  const hs = 6 / view.scale;
  for (const [hx, hy] of [[-1, -1], [1, -1], [-1, 1], [1, 1]])
    ctx.fillRect(hx * (b.w + pad) - hs / 2, hy * (b.h + pad) - hs / 2, hs, hs);
  ctx.restore();
}

/* ============ 图层面板 + 检查器 ============ */
const GLYPH = {
  circle: '<circle cx="12" cy="12" r="7"/>', ellipse: '<ellipse cx="12" cy="12" rx="8" ry="5.5"/>',
  square: '<rect x="5.5" y="5.5" width="13" height="13" rx="1.5"/>',
  rect: '<rect x="4" y="7" width="16" height="10" rx="1.5"/>',
  triangle: '<path d="M12 5 19 18H5Z"/>', diamond: '<path d="M12 4 19 12 12 20 5 12Z"/>',
  pentagon: '<path d="M12 4 20 10 17 19H7L4 10Z"/>', hexagon: '<path d="M8 5h8l4 7-4 7H8l-4-7Z"/>',
  star: '<path d="M12 4 14 10h6l-5 4 2 6-5-4-5 4 2-6-5-4h6Z"/>',
  heart: '<path d="M12 19S4 14 4 9a4 4 0 0 1 8-1 4 4 0 0 1 8 1c0 5-8 10-8 10Z"/>',
  ring: '<path fill-rule="evenodd" d="M12 4a8 8 0 1 0 0 16 8 8 0 0 0 0-16Zm0 5a3 3 0 1 1 0 6 3 3 0 0 1 0-6Z"/>',
  moon: '<path d="M16 4a8 8 0 1 0 0 16A9 9 0 0 1 16 4Z"/>',
  cloud: '<path d="M7 17a4 4 0 0 1 0-8 5 5 0 0 1 9.5 1A3.5 3.5 0 0 1 16 17Z"/>',
  lightning: '<path d="M13 3 6 13h4l-1 8 7-11h-4Z"/>',
  cross: '<path d="M9.5 4h5v5h5v5h-5v5h-5v-5h-5v-5h5Z"/>',
  speech: '<path d="M4 6h16v9H10l-3 3v-3H4Z"/>',
  smile: '<path d="M7 13a5 5 0 0 0 10 0" fill="none" stroke="currentColor" stroke-width="2"/>',
  arrow: '<path d="M3 12h14M13 7l5 5-5 5" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/>',
  line: '<rect x="4" y="11" width="16" height="2.4" rx="1.2"/>',
  vline: '<rect x="11" y="4" width="2.4" height="16" rx="1.2"/>',
  text: '<path d="M6 6h12M12 6v12" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"/>',
  image: '<path d="M4 5h16v14H4Z" fill="none" stroke="currentColor" stroke-width="1.8"/><circle cx="9" cy="10" r="1.6"/><path d="M5 18l5-5 4 3 3-2 2 2v2H5Z"/>',
};
function glyph(type) {
  return '<svg viewBox="0 0 24 24" fill="currentColor" style="color:' + 'var(--ink-subtle)">' + (GLYPH[type] || GLYPH.square) + '</svg>';
}

function renderLayers() {
  const el = document.getElementById('layers');
  document.getElementById('layer-count').textContent = scene.shapes.length;
  if (!scene.shapes.length) {
    el.innerHTML = '<div class="rail-empty">还没有图层。<br>说一句「画一个红色的圆」试试。</div>';
    return;
  }
  // 顶层在上：倒序遍历；同组合并为一行
  const rows = []; const seen = new Set();
  for (let i = scene.shapes.length - 1; i >= 0; i--) {
    const s = scene.shapes[i];
    if (s.group) {
      if (seen.has(s.group)) continue;
      seen.add(s.group);
      const members = scene.shapes.filter(x => x.group === s.group);
      const selCount = members.filter(m => selected.includes(m.id)).length;
      rows.push({ glyph: s.name || '组', type: s.type, name: (s.name || '组合') + '', color: members[0].color, op: 1, badge: members.length + ' 部件', sel: selCount > 0 });
    } else {
      rows.push({ type: s.type, name: LABELS[s.type] || '图形', color: s.color, op: s.opacity == null ? 1 : s.opacity, sel: selected.includes(s.id) });
    }
  }
  el.innerHTML = rows.map(r =>
    '<div class="layer' + (r.sel ? ' sel' : '') + '">'
    + '<span class="layer-glyph">' + glyph(r.type) + '</span>'
    + '<span class="layer-name">' + escapeHtml(r.name) + '</span>'
    + '<span class="layer-meta">'
    + (r.badge ? '<span class="layer-badge">' + r.badge + '</span>' : '')
    + (r.op < 1 ? '<span class="layer-op">' + Math.round(r.op * 100) + '%</span>' : '')
    + '<span class="layer-swatch" style="background:' + r.color + '"></span>'
    + '</span></div>').join('');
}

function renderInspector() {
  const el = document.getElementById('inspector');
  const badge = document.getElementById('sel-badge');
  const sel = scene.shapes.filter(s => selected.includes(s.id));
  if (!sel.length) {
    badge.textContent = '';
    el.innerHTML = '<div class="insp-empty">未选中对象。<br>新画的图形会自动选中。</div>';
    return;
  }
  if (sel.length > 1) {
    badge.textContent = sel.length + ' 个';
    const types = {};
    sel.forEach(s => { const l = LABELS[s.type] || s.type; types[l] = (types[l] || 0) + 1; });
    const list = Object.entries(types).map(([k, v]) => k + '×' + v).join('、');
    el.innerHTML = '<div class="insp-multi">已选中 <b>' + sel.length + '</b> 个对象<br>' + escapeHtml(list)
      + '<br><span style="color:var(--ink-tertiary)">可对其对齐、分布、整体移动或缩放</span></div>';
    return;
  }
  const s = sel[0];
  badge.textContent = '';
  let rows;
  if (s.type === 'image') {
    rows = [
      ['类型', 'AI 图片'],
      ['描述', escapeHtml(s.prompt || '—')],
      ['位置', 'X ' + Math.round(s.x) + '  Y ' + Math.round(s.y)],
      ['尺寸', Math.round(s.size * 2) + ' px 宽'],
      ['旋转', Math.round(s.rot || 0) + '°'],
      ['透明度', Math.round((s.opacity == null ? 1 : s.opacity) * 100) + '%'],
    ];
  } else {
    rows = [
      ['类型', (s.name ? s.name + ' · ' : '') + (LABELS[s.type] || s.type)],
      ['位置', 'X ' + Math.round(s.x) + '  Y ' + Math.round(s.y)],
      ['尺寸', Math.round(s.size) + (s.type === 'text' ? ' pt' : ' px')],
      ['颜色', '<span class="insp-swatch" style="background:' + s.color + '"></span>' + s.color],
      ['旋转', Math.round(s.rot || 0) + '°'],
      ['透明度', Math.round((s.opacity == null ? 1 : s.opacity) * 100) + '%'],
      ['填充', s.style === 'stroke' ? '空心 · 描边×' + (s.weight || 1).toFixed(1) : '实心'],
    ];
    if (s.flipX || s.flipY) rows.push(['翻转', [s.flipX ? '水平' : '', s.flipY ? '垂直' : ''].filter(Boolean).join(' ')]);
  }
  el.innerHTML = rows.map(([k, v]) =>
    '<div class="insp-row"><span class="insp-key">' + k + '</span><span class="insp-val">' + v + '</span></div>').join('');
}

/* ============ API ============ */
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
    try { applyState(await api('GET', '/api/sessions/' + saved)); sessionId = saved; setSessionPill(true, '已恢复'); return; }
    catch (_) {}
  }
  const data = await api('POST', '/api/sessions');
  sessionId = data.session_id; localStorage.setItem('voicedraw_session', sessionId);
  applyState(data); setSessionPill(true, '已连接');
}
function applyState(data) {
  scene = data.scene; selected = data.selected || []; flags = data.flags || flags;
  if (data.logical) LOGICAL = { w: data.logical.w, h: data.logical.h };
  document.getElementById('art-dim').textContent = LOGICAL.w + ' × ' + LOGICAL.h;
  resizeBoard(); renderLayers(); renderInspector(); updateChrome();
}

async function handleUtterance(raw) {
  if (!sessionId) return;
  setPending(true);
  const t0 = performance.now();
  let data;
  try { data = await api('POST', '/api/sessions/' + sessionId + '/commands', { text: raw }); }
  catch (e) { logItem(raw, '后端请求失败：' + e.message, 'err'); setPending(false); return; }
  const ms = Math.round(performance.now() - t0);
  setPending(false);
  applyState(data);
  const results = data.results || [];
  if (!results.length) return;
  const msgs = [];
  for (const r of results) {
    msgs.push(r.msg);
    const said = (r.via === 'ai' && r.original) ? r.original : (r.clause || raw);
    logItem(said, r.msg, r.ok ? 'ok' : 'err', ms, r.via === 'ai' ? (r.corrected || r.clause) : null);
    handleAction(r.action, r);
  }
  document.getElementById('lat-badge').textContent = '后端 ' + ms + 'ms';
  const summary = msgs.join('；');
  speak(summary.length > 56 ? summary.slice(0, 54) + '…' : summary);
}

let pendingTimer = null;
function setPending(on) {
  // 后端 >300ms（多半在调 LLM 纠错）才提示，避免快指令闪烁
  clearTimeout(pendingTimer);
  if (on) {
    pendingTimer = setTimeout(() => {
      if (ui.started && !ui.speaking) {
        document.getElementById('mic-state').textContent = '理解中…';
        document.getElementById('mic-desc').textContent = 'AI 正在理解这句话';
      }
    }, 300);
  } else {
    updateChrome();
  }
}

function handleAction(action, r) {
  if (!action) return;
  if (action === 'generate_image') { generateImage(r.prompt); return; }
  const m = {
    help_open: () => helpEl.classList.remove('hidden'),
    help_close: () => helpEl.classList.add('hidden'),
    export: exportPNG,
    tts_off: () => flags.tts_on = false, tts_on: () => flags.tts_on = true,
    zoom_in: () => applyZoom('in'), zoom_out: () => applyZoom('out'),
    zoom_fit: () => applyZoom('fit'), zoom_reset: () => applyZoom('reset'),
    grid_on: () => setGrid(true), grid_off: () => setGrid(false),
  };
  if (m[action]) m[action]();
}

/* 文生图：耗时数秒，独立端点 + 加载遮罩 */
let generating = false;
async function generateImage(prompt) {
  if (generating || !sessionId) return;
  generating = true;
  const ov = document.getElementById('gen-overlay');
  document.getElementById('gen-prompt').textContent = '“' + prompt + '”';
  ov.classList.remove('hidden');
  const t0 = performance.now();
  try {
    const data = await api('POST', '/api/sessions/' + sessionId + '/generate', { prompt });
    const ms = Math.round(performance.now() - t0);
    applyState(data);
    for (const r of (data.results || [])) {
      logItem(r.clause || prompt, r.msg, r.ok ? 'ok' : 'err', ms);
      speak(r.msg.length > 54 ? r.msg.slice(0, 52) + '…' : r.msg);
    }
  } catch (e) {
    logItem(prompt, '生成请求失败：' + e.message, 'err');
    speak('生成失败');
  } finally {
    generating = false;
    ov.classList.add('hidden');
  }
}

/* ============ 视图操作 ============ */
function applyZoom(kind) {
  if (kind === 'in') viewCfg.userZoom = Math.min(4, viewCfg.userZoom * 1.25);
  else if (kind === 'out') viewCfg.userZoom = Math.max(.25, viewCfg.userZoom / 1.25);
  else if (kind === 'fit') viewCfg.userZoom = 1;
  else if (kind === 'reset') viewCfg.userZoom = 1 / containScale;
  resizeBoard();
}
function setGrid(on) {
  viewCfg.showGrid = on;
  document.getElementById('grid-toggle').dataset.on = on ? '1' : '0';
  render();
}

/* ============ PNG 导出 ============ */
function exportPNG() {
  const sc = 2, tmp = document.createElement('canvas');
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
    if (ui.speaking) return;
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
      ui.listening = false; setMicState('err', '麦克风被拒绝', '请允许麦克风后刷新');
    }
  };
  rec.onend = () => { if (ui.listening && !ui.speaking) setTimeout(() => { try { rec.start(); } catch (_) {} }, 200); };
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
  try { rec && rec.abort(); } catch (_) {}
  const resume = () => { ui.speaking = false; updateChrome(); if (ui.listening) setTimeout(() => { try { rec.start(); } catch (_) {} }, 250); };
  u.onend = resume; u.onerror = resume;
  speechSynthesis.speak(u);
}

/* ============ UI 反馈 ============ */
const helpEl = document.getElementById('help-overlay');
const logEl = document.getElementById('log');
const transcriptEl = document.getElementById('transcript');
const hintEl = document.getElementById('hint');
const hintCmdEl = document.getElementById('hint-cmd');

const HINTS = ['“生成一张星空下的城堡的图片”', '“画一个笑脸放在中间”', '“画三个并排的方块然后全部左对齐”',
  '“画一个空心的六边形”', '“把它透明度设为一半”', '“生成一只戴帽子的猫”'];
let hintIdx = 0;
setInterval(() => { if (!scene.shapes.length) { hintIdx = (hintIdx + 1) % HINTS.length; hintCmdEl.textContent = HINTS[hintIdx]; } }, 4000);

function showTranscript(text, isFinal) { transcriptEl.textContent = text; transcriptEl.classList.toggle('final', isFinal); }
function logItem(said, res, kind, ms, aiCorrected) {
  const empty = logEl.querySelector('.rail-empty'); if (empty) empty.remove();
  const el = document.createElement('div'); el.className = 'log-item ' + kind;
  const time = new Date().toTimeString().slice(0, 8), lat = ms != null ? ' · ' + ms + 'ms' : '';
  let html = '<span class="log-time">' + time + lat + '</span>'
    + '<div class="log-said">“' + escapeHtml(said) + '”</div>';
  if (aiCorrected) html += '<div class="log-ai"><span class="ai-tag">AI</span>理解为「' + escapeHtml(aiCorrected) + '」</div>';
  html += '<div class="log-res">' + escapeHtml(res) + '</div>';
  el.innerHTML = html;
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
function updateChrome() {
  document.getElementById('pill-mic'); // 状态在 setMicState 更新
  document.getElementById('tb-undo').disabled = !flags.can_undo;
  document.getElementById('tb-redo').disabled = !flags.can_redo;
  hintEl.style.display = scene.shapes.length ? 'none' : 'flex';
  if (!ui.started) return;
  if (ui.speaking) setMicState('live', '播报中', '语音反馈中，暂停识别');
  else if (flags.muted) setMicState('idle', '已暂停', '说「继续聆听」恢复');
  else if (ui.listening) setMicState('on', '聆听中', '请说出指令');
}

/* ============ 启动 + 冗余可达性按钮 ============ */
const startOverlay = document.getElementById('start-overlay');
const startBtn = document.getElementById('btn-start');
const startWarn = document.getElementById('start-warn');

document.getElementById('shape-lib').innerHTML =
  SHAPE_LIB.map(s => '<span class="chip">' + s + '</span>').join('');

if (!SR) {
  startBtn.disabled = true; startWarn.style.display = 'block';
  startWarn.textContent = '当前浏览器不支持 Web Speech API，请改用桌面版 Chrome 或 Edge。';
}
startBtn.addEventListener('click', () => {
  ui.started = true; startOverlay.classList.add('hidden');
  startRecognition(); setMicState('on', '聆听中', '请说出指令');
  speak('你好，我在听。试试说：画一个笑脸');
});

// 工具栏按钮 = 语音指令的冗余入口（点击走同一指令路径）
document.getElementById('tb-undo').addEventListener('click', () => handleUtterance('撤销'));
document.getElementById('tb-redo').addEventListener('click', () => handleUtterance('重做'));
document.getElementById('zoom-in').addEventListener('click', () => applyZoom('in'));
document.getElementById('zoom-out').addEventListener('click', () => applyZoom('out'));
document.getElementById('zoom-fit').addEventListener('click', () => applyZoom('fit'));
document.getElementById('grid-toggle').addEventListener('click', () => setGrid(!viewCfg.showGrid));

ensureSession().catch(e => {
  setSessionPill(false, '后端未连接');
  startWarn.style.display = 'block'; startWarn.textContent = '无法连接后端：' + e.message;
});
resizeBoard();
