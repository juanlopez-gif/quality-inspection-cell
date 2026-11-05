/* =============================================================================
 * Quality Inspection Cell - dashboard front-end (vanilla JS, no dependencies)
 *
 * Talks to dashboard_node.py through a tiny JSON API:
 *   GET /api/config  (once)   GET /api/state (~7 Hz)   GET /api/graph (1 Hz)
 *   GET /api/events?since=N   POST /api/spawn   POST /api/reset
 * ========================================================================== */
'use strict';

const S = {
  cfg: null, state: null, graph: null, lastSeq: 0, events: [],
  prevCounts: {}, paused: false, selTopic: null, selArch: null, queue: [],
};
const $ = (id) => document.getElementById(id);
const T = (topic) => (S.state && S.state.topics[topic] ? S.state.topics[topic].last : null);

const COLORS = {
  RED: [220, 45, 45], GREEN: [40, 170, 75], BLUE: [40, 95, 225],
  YELLOW: [235, 205, 40], ORANGE: [240, 140, 30], PURPLE: [140, 60, 200],
};
const ROBOT_STATES = ['IDLE', 'WAITING_TO_PICK', 'PICKING_CONVEYOR', 'PICKING_DONE', 'PLACING', 'RETURNING_HOME'];

// ------------------------------------------------------------------ helpers
async function getJSON(url) {
  const r = await fetch(url, { cache: 'no-store' });
  if (!r.ok) throw new Error(r.status);
  return r.json();
}
async function post(url, body) {
  const r = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body || {}) });
  return r.json();
}
function toast(text) {
  const t = $('toast'); t.textContent = text; t.classList.add('show');
  clearTimeout(toast._t); toast._t = setTimeout(() => t.classList.remove('show'), 2200);
}
function fmtTime(t) {
  const d = new Date(t * 1000);
  return d.toLocaleTimeString([], { hour12: false }) + '.' + String(d.getMilliseconds()).padStart(3, '0').slice(0, 1);
}
function esc(s) { return String(s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c])); }
function rgbStr(r, g, b, a) { return a === undefined ? `rgb(${r},${g},${b})` : `rgba(${r},${g},${b},${a})`; }

// ------------------------------------------------------------------ tabs
document.querySelectorAll('#tabs button').forEach((b) => b.addEventListener('click', () => {
  document.querySelectorAll('#tabs button').forEach((x) => x.classList.toggle('active', x === b));
  document.querySelectorAll('.tab').forEach((x) => x.classList.toggle('active', x.id === 'tab-' + b.dataset.tab));
  if (b.dataset.tab === 'arch') drawArch(true);
  resizeCanvas();
}));

// ========================================================================== OPERATOR FORM
const form = { shape: 'CIRCLE', color: 'RED', rgb: COLORS.RED, mark: 'NONE' };
function initForm() {
  const sw = $('f-color');
  Object.entries(COLORS).forEach(([name, c]) => {
    const d = document.createElement('div');
    d.className = 'sw' + (name === 'RED' ? ' on' : '');
    d.style.background = rgbStr(...c); d.title = name;
    d.innerHTML = `<small>${name.slice(0, 3)}</small>`;
    d.onclick = () => { form.color = name; form.rgb = c; sw.querySelectorAll('.sw').forEach((x) => x.classList.toggle('on', x === d)); };
    sw.appendChild(d);
  });
  const pick = document.createElement('input');
  pick.type = 'color'; pick.value = '#8a5a2b'; pick.title = 'Custom color';
  pick.oninput = () => {
    const v = pick.value; form.color = 'CUSTOM';
    form.rgb = [1, 3, 5].map((i) => parseInt(v.substr(i, 2), 16));
    sw.querySelectorAll('.sw').forEach((x) => x.classList.remove('on'));
  };
  sw.appendChild(pick);
  const seg = (id, key) => $(id).querySelectorAll('button').forEach((b) => b.onclick = () => {
    form[key] = b.dataset.v; $(id).querySelectorAll('button').forEach((x) => x.classList.toggle('on', x === b));
  });
  seg('f-shape', 'shape'); seg('f-mark', 'mark');
  [['f-size', 'f-size-v', (v) => (+v).toFixed(1)], ['f-y', 'f-y-v', (v) => v], ['f-yaw', 'f-yaw-v', (v) => v]]
    .forEach(([i, o, f]) => { $(i).oninput = () => { $(o).textContent = f($(i).value); }; });

  $('btn-spawn').onclick = () => enqueue([{
    shape: form.shape, color_name: form.color, r: form.rgb[0], g: form.rgb[1], b: form.rgb[2],
    size_mm: +$('f-size').value, mark: form.mark, y_offset_mm: +$('f-y').value, yaw_deg: +$('f-yaw').value,
  }]);
  $('btn-good').onclick = () => enqueue([randomPiece(false)]);
  $('btn-bad').onclick = () => enqueue([randomPiece(true)]);
  $('btn-batch').onclick = () => enqueue([0, 1, 2, 3, 4, 5].map((i) => randomPiece(i % 3 === 2)));
  $('btn-reset').onclick = async () => { S.queue = []; await post('/api/reset'); toast('World reset'); };
}
function rnd(a) { return a[Math.floor(Math.random() * a.length)]; }
function randomPiece(defective) {
  let color = rnd(['RED', 'GREEN', 'BLUE']), size = 42 + (Math.random() - 0.5) * 2, mark = 'NONE';
  if (defective) {
    const kind = rnd(['mark', 'color', 'size']);
    if (kind === 'mark') mark = rnd(['CROSS', 'SMILEY', 'SCRATCH', 'DOT', 'GROOVE']);
    if (kind === 'color') color = rnd(['YELLOW', 'ORANGE', 'PURPLE']);
    if (kind === 'size') size = rnd([33, 36, 48, 52]);
  }
  const c = COLORS[color];
  return { shape: rnd(['CIRCLE', 'SQUARE']), color_name: color, r: c[0], g: c[1], b: c[2], size_mm: size,
    mark, y_offset_mm: Math.round((Math.random() - 0.5) * 30), yaw_deg: Math.round(Math.random() * 40) };
}
// The operator can only drop a piece when the start of the belt is free -> queue.
function enqueue(list) { S.queue.push(...list); pumpQueue(); }
function startIsFree() {
  const w = T('/sim/world_state'); if (!w || !S.cfg) return false;
  const limit = S.cfg.conveyor.spawn_x_mm + 70;
  return !w.pieces.some((p) => p.location === 'BELT' && p.x_mm < limit);
}
async function pumpQueue() {
  $('queue-info').textContent = S.queue.length ? `${S.queue.length} piece(s) waiting for free space at the start of the belt…` : '';
  if (!S.queue.length || pumpQueue.busy || !startIsFree()) return;
  pumpQueue.busy = true;
  try { await post('/api/spawn', S.queue.shift()); } finally { setTimeout(() => { pumpQueue.busy = false; }, 600); }
}

// ========================================================================== CELL CANVAS
const cv = $('cell-canvas'); const ctx = cv.getContext('2d');
const VIEW = { xmin: -60, xmax: 1010, ymin: -130, ymax: 730 };
let scale = 1;
function resizeCanvas() {
  const w = cv.parentElement.clientWidth; if (!w) return;
  const h = w * (VIEW.ymax - VIEW.ymin) / (VIEW.xmax - VIEW.xmin);
  const dpr = window.devicePixelRatio || 1;
  cv.width = w * dpr; cv.height = h * dpr; cv.style.height = h + 'px';
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  scale = w / (VIEW.xmax - VIEW.xmin);
}
window.addEventListener('resize', () => { resizeCanvas(); drawArch(true); });
const px = (x) => (x - VIEW.xmin) * scale;
const py = (y) => (VIEW.ymax - y) * scale;
const mm = (d) => d * scale;
function robotToCell(x, y, z) {
  const b = S.cfg.camera.robot_base_in_cell, a = (b.yaw_deg || 0) * Math.PI / 180;
  return [Math.cos(a) * x - Math.sin(a) * y + b.x, Math.sin(a) * x + Math.cos(a) * y + b.y, z + b.z];
}
function roundRect(x, y, w, h, r) { ctx.beginPath(); ctx.roundRect(x, y, w, h, r); }
function label(text, x, y, opt = {}) {
  ctx.font = `${opt.bold ? '700 ' : ''}${opt.size || 11}px Inter, system-ui, sans-serif`;
  ctx.fillStyle = opt.color || '#8b9aab'; ctx.textAlign = opt.align || 'center'; ctx.textBaseline = opt.base || 'middle';
  ctx.fillText(text, x, y);
}

function drawPiece(p, opt = {}) {
  const lift = opt.lift || 0;                       // z height -> bigger + shadow
  const k = 1 + lift / 900;
  const s = mm(p.size_mm) * k * (opt.shrink || 1);
  const x = px(p.x_mm), y = py(p.y_mm);
  ctx.save();
  if (lift > 1) {                                   // shadow on the ground
    ctx.fillStyle = 'rgba(0,0,0,0.35)';
    ctx.beginPath(); ctx.ellipse(x + lift * scale * 0.15, y + lift * scale * 0.15, s / 2, s / 2, 0, 0, 7); ctx.fill();
  }
  ctx.translate(x, y); ctx.rotate(-(p.yaw_deg || 0) * Math.PI / 180);
  ctx.fillStyle = rgbStr(p.r, p.g, p.b);
  ctx.strokeStyle = 'rgba(0,0,0,.45)'; ctx.lineWidth = 1.2;
  ctx.beginPath();
  if (p.shape === 'CIRCLE') ctx.arc(0, 0, s / 2, 0, Math.PI * 2); else ctx.rect(-s / 2, -s / 2, s, s);
  ctx.fill(); ctx.stroke();
  // light highlight
  ctx.fillStyle = 'rgba(255,255,255,.12)'; ctx.beginPath();
  if (p.shape === 'CIRCLE') ctx.arc(-s * 0.12, -s * 0.12, s * 0.3, 0, 7); else ctx.rect(-s / 2, -s / 2, s, s * 0.35);
  ctx.fill();
  drawMark(p.mark, s);
  ctx.restore();
  if (opt.id) label('#' + p.id, x, y + s / 2 + 8, { size: 9, color: '#b8c4d2' });
}
function drawMark(mark, s) {
  if (!mark || mark === 'NONE') return;
  ctx.strokeStyle = '#111'; ctx.fillStyle = '#111'; ctx.lineWidth = Math.max(1.2, s * 0.07); ctx.lineCap = 'round';
  const q = s * 0.25;
  ctx.beginPath();
  if (mark === 'CROSS') { ctx.moveTo(-q, -q); ctx.lineTo(q, q); ctx.moveTo(q, -q); ctx.lineTo(-q, q); ctx.stroke(); }
  else if (mark === 'SMILEY') {
    ctx.arc(-q * 0.6, -q * 0.4, s * 0.04, 0, 7); ctx.fill(); ctx.beginPath(); ctx.arc(q * 0.6, -q * 0.4, s * 0.04, 0, 7); ctx.fill();
    ctx.beginPath(); ctx.arc(0, 0, q * 0.9, 0.2 * Math.PI, 0.8 * Math.PI); ctx.stroke();
  } else if (mark === 'SCRATCH') {
    ctx.lineWidth = Math.max(1, s * 0.04); ctx.moveTo(-q * 1.3, -q * 0.6);
    for (let i = 1; i <= 6; i++) ctx.lineTo(-q * 1.3 + i * q * 0.45, -q * 0.6 + (i % 2 ? q * 0.35 : 0) + i * q * 0.12);
    ctx.stroke();
  } else if (mark === 'DOT') { ctx.arc(q * 0.4, q * 0.3, s * 0.08, 0, 7); ctx.fill(); }
  else if (mark === 'GROOVE') { ctx.lineWidth = Math.max(1.5, s * 0.06); ctx.moveTo(-s * 0.45, s * 0.1); ctx.lineTo(s * 0.45, -s * 0.05); ctx.stroke(); }
}

function drawCell() {
  if (!S.cfg) return;
  const W = cv.clientWidth, H = cv.clientHeight;
  ctx.clearRect(0, 0, W, H);
  const c = S.cfg, conv = c.conveyor;
  const world = T('/sim/world_state'), ir = T('/ir_sensor/status'), cs = T('/conveyor/status');
  const det = T('/camera/detections'), rs = T('/robot/status');

  // floor grid (100 mm)
  ctx.strokeStyle = '#141c24'; ctx.lineWidth = 1;
  for (let x = 0; x <= 1000; x += 100) { ctx.beginPath(); ctx.moveTo(px(x), 0); ctx.lineTo(px(x), H); ctx.stroke(); }
  for (let y = -100; y <= 700; y += 100) { ctx.beginPath(); ctx.moveTo(0, py(y)); ctx.lineTo(W, py(y)); ctx.stroke(); }
  // frame axes
  ctx.strokeStyle = '#ff5d5d'; ctx.lineWidth = 2; ctx.beginPath(); ctx.moveTo(px(0), py(-100)); ctx.lineTo(px(60), py(-100)); ctx.stroke();
  ctx.strokeStyle = '#3ccf7a'; ctx.beginPath(); ctx.moveTo(px(0), py(-100)); ctx.lineTo(px(0), py(-40)); ctx.stroke();
  label('X', px(70), py(-100), { size: 10, color: '#ff5d5d' }); label('Y', px(0), py(-30), { size: 10, color: '#3ccf7a' });
  label('CELL frame', px(10), py(-118), { size: 10, align: 'left' });

  // ----- conveyor
  const L = conv.length_mm, Wd = conv.width_mm;
  const running = cs && cs.state === 'RUNNING';
  ctx.fillStyle = '#20262d'; roundRect(px(-20), py(Wd / 2 + 12), mm(L + 40), mm(Wd + 24), 8); ctx.fill();
  ctx.fillStyle = '#2b333c'; ctx.fillRect(px(0), py(Wd / 2), mm(L), mm(Wd));
  // moving slats
  const off = world ? world.belt_position_mm % 40 : 0;
  ctx.strokeStyle = '#353f4a'; ctx.lineWidth = Math.max(1, mm(4));
  for (let x = off; x < L; x += 40) { ctx.beginPath(); ctx.moveTo(px(x), py(Wd / 2)); ctx.lineTo(px(x), py(-Wd / 2)); ctx.stroke(); }
  // rollers
  ctx.fillStyle = '#56616d';
  [0, L].forEach((x) => { roundRect(px(x) - mm(10), py(Wd / 2 + 6), mm(20), mm(Wd + 12), 5); ctx.fill(); });
  // load zone
  ctx.strokeStyle = 'rgba(124,140,255,.6)'; ctx.setLineDash([5, 4]); ctx.lineWidth = 1.5;
  ctx.strokeRect(px(conv.spawn_x_mm - 45), py(Wd / 2 - 4), mm(90), mm(Wd - 8)); ctx.setLineDash([]);
  label('LOAD', px(conv.spawn_x_mm), py(-Wd / 2 - 22), { color: '#7c8cff', bold: true });
  label(running ? '▶ RUNNING ' + cs.speed_mm_s.toFixed(0) + ' mm/s' : '■ STOPPED', px(L / 2 - 120), py(-Wd / 2 - 22),
    { color: running ? '#3ccf7a' : '#ff9a3c', bold: true, size: 12 });

  // ----- camera FOV + pick ROI
  const fov = c.camera.fov, roi = c.camera.pick_roi;
  ctx.strokeStyle = 'rgba(245,197,66,.35)'; ctx.setLineDash([8, 6]); ctx.lineWidth = 1.2;
  ctx.strokeRect(px(fov.x_min), py(fov.y_max + 25), mm(fov.x_max - fov.x_min), mm(fov.y_max - fov.y_min + 50));
  ctx.setLineDash([]);
  label('📷 overhead camera field of view', px(fov.x_min + 8), py(fov.y_max + 38), { align: 'left', color: '#f5c542', size: 11 });
  const inspecting = det && det.camera_state === 'INSPECTING';
  ctx.fillStyle = inspecting ? 'rgba(245,197,66,.18)' : 'rgba(245,197,66,.05)';
  ctx.fillRect(px(roi.x_min), py(roi.y_max), mm(roi.x_max - roi.x_min), mm(roi.y_max - roi.y_min));
  ctx.strokeStyle = inspecting ? '#f5c542' : 'rgba(245,197,66,.6)'; ctx.lineWidth = inspecting ? 2.5 : 1.5;
  ctx.strokeRect(px(roi.x_min), py(roi.y_max), mm(roi.x_max - roi.x_min), mm(roi.y_max - roi.y_min));
  label(inspecting ? 'PICK ROI · INSPECTING…' : 'PICK ROI', px((roi.x_min + roi.x_max) / 2), py(roi.y_min - 14),
    { color: '#f5c542', bold: true, size: 10 });

  // ----- IR sensor
  const xi = c.ir_sensor.x_mm, occ = ir && ir.state === 'OCCUPIED';
  ctx.strokeStyle = occ ? '#ff5d5d' : 'rgba(60,207,122,.8)'; ctx.lineWidth = occ ? 3 : 2;
  ctx.shadowColor = occ ? '#ff5d5d' : '#3ccf7a'; ctx.shadowBlur = 10;
  ctx.beginPath(); ctx.moveTo(px(xi), py(Wd / 2 + 10)); ctx.lineTo(px(xi), py(-Wd / 2 - 10)); ctx.stroke();
  ctx.shadowBlur = 0;
  ctx.fillStyle = '#444f5b';
  ctx.fillRect(px(xi) - mm(9), py(Wd / 2 + 26), mm(18), mm(16));
  ctx.fillRect(px(xi) - mm(9), py(-Wd / 2 - 10), mm(18), mm(16));
  label('IR ' + (ir ? ir.state : '?'), px(xi), py(-Wd / 2 - 40), { color: occ ? '#ff5d5d' : '#3ccf7a', bold: true, size: 11 });

  // ----- bins
  const bs = c.bins.size_mm;
  const counts = {};
  (world ? world.pieces : []).forEach((p) => { if (p.location === 'BIN') counts[p.bin_id] = (counts[p.bin_id] || 0) + 1; });
  const placingBin = rs && ['PLACING', 'PICKING_CONVEYOR', 'PICKING_DONE'].includes(rs.state) ? rs.target_bin : '';
  c.bins.list.forEach((b) => {
    const good = b.kind === 'good';
    const col = good ? COLORS[b.color] : [255, 93, 93];
    ctx.fillStyle = '#161d24'; roundRect(px(b.x - bs / 2), py(b.y + bs / 2), mm(bs), mm(bs), 6); ctx.fill();
    ctx.strokeStyle = b.id === placingBin ? '#fff' : rgbStr(...col, good ? 0.8 : 0.6);
    ctx.lineWidth = b.id === placingBin ? 3 : 2; ctx.setLineDash(good ? [] : [5, 3]);
    roundRect(px(b.x - bs / 2), py(b.y + bs / 2), mm(bs), mm(bs), 6); ctx.stroke(); ctx.setLineDash([]);
    label(b.label, px(b.x), py(b.y + bs / 2 + 9), { size: 10, color: good ? '#b8c4d2' : '#ff9c9c' });
    if (good) {                                        // icon of the expected piece
      ctx.fillStyle = rgbStr(...col, 0.25); ctx.beginPath();
      if (b.shape === 'CIRCLE') ctx.arc(px(b.x), py(b.y), mm(14), 0, 7); else ctx.rect(px(b.x) - mm(13), py(b.y) - mm(13), mm(26), mm(26));
      ctx.fill();
    }
    label(String(counts[b.id] || 0), px(b.x + bs / 2 - 10), py(b.y - bs / 2 + 10), { bold: true, size: 11, color: '#e6edf3' });
  });

  // ----- pieces in bins / floor, then on belt
  if (world) {
    world.pieces.filter((p) => p.location === 'BIN').forEach((p) => drawPiece(p, { shrink: 0.8 }));
    world.pieces.filter((p) => p.location === 'FLOOR').forEach((p) => drawPiece(p));
    world.pieces.filter((p) => p.location === 'BELT').forEach((p) => drawPiece(p, { id: true }));
  }
  // ----- camera detections overlay
  if (det) det.pieces.forEach((d) => {
    const s = mm(52);
    ctx.strokeStyle = '#f5c542'; ctx.lineWidth = 1.2; ctx.setLineDash([4, 3]);
    ctx.strokeRect(px(d.x_mm) - s / 2, py(d.y_mm) - s / 2, s, s); ctx.setLineDash([]);
    label(`#${d.track_id} ${d.color} ${d.shape} ${(d.confidence * 100).toFixed(0)}%`, px(d.x_mm), py(d.y_mm) - s / 2 - 7,
      { size: 9, color: '#f5c542' });
  });

  // ----- robot
  if (rs) drawRobot(rs, world);
  else {
    const b = c.camera.robot_base_in_cell;
    label('robot offline', px(b.x), py(b.y), { color: '#ff5d5d' });
  }
}

function drawRobot(rs, world) {
  const base = S.cfg.camera.robot_base_in_cell;
  const [tx, ty, tz] = robotToCell(rs.tcp_x_mm, rs.tcp_y_mm, rs.tcp_z_mm);
  const bx = px(base.x), by = py(base.y), X = px(tx), Y = py(ty);
  // planar 2-link drawing (top view, just for looks)
  const L1 = mm(230), L2 = mm(230);
  let dx = X - bx, dy = Y - by, d = Math.hypot(dx, dy); d = Math.min(Math.max(d, 1), L1 + L2 - 1);
  const a = Math.atan2(dy, dx), cosb = (L1 * L1 + d * d - L2 * L2) / (2 * L1 * d);
  const b = Math.acos(Math.max(-1, Math.min(1, cosb)));
  const ex = bx + L1 * Math.cos(a + b), ey = by + L1 * Math.sin(a + b);
  // reach circle
  ctx.strokeStyle = 'rgba(31,181,168,.12)'; ctx.setLineDash([3, 6]); ctx.lineWidth = 1;
  ctx.beginPath(); ctx.arc(bx, by, mm(S.cfg.robot.max_reach_mm), 0, 7); ctx.stroke(); ctx.setLineDash([]);
  // links
  ctx.lineCap = 'round';
  ctx.strokeStyle = '#d9dee4'; ctx.lineWidth = mm(46); ctx.beginPath(); ctx.moveTo(bx, by); ctx.lineTo(ex, ey); ctx.stroke();
  ctx.strokeStyle = '#c3cad2'; ctx.lineWidth = mm(36); ctx.beginPath(); ctx.moveTo(ex, ey); ctx.lineTo(X, Y); ctx.stroke();
  ctx.strokeStyle = '#1fb5a8'; ctx.lineWidth = mm(8);
  ctx.beginPath(); ctx.moveTo(bx, by); ctx.lineTo(ex, ey); ctx.lineTo(X, Y); ctx.stroke();
  // joints and base
  ctx.fillStyle = '#9aa5b1'; ctx.beginPath(); ctx.arc(ex, ey, mm(26), 0, 7); ctx.fill();
  ctx.fillStyle = '#e6edf3'; ctx.beginPath(); ctx.arc(bx, by, mm(55), 0, 7); ctx.fill();
  ctx.fillStyle = '#1fb5a8'; ctx.beginPath(); ctx.arc(bx, by, mm(30), 0, 7); ctx.fill();
  label('UR7e · vacuum', bx, by + mm(75), { size: 10, color: '#1fb5a8', bold: true });
  // held piece
  if (world) world.pieces.filter((p) => p.location === 'GRIPPER').forEach((p) => drawPiece(p, { lift: tz }));
  // vacuum suction cup (scaled by height, glows when vacuum is ON)
  const k = 1 + tz / 600;
  ctx.save(); ctx.translate(X, Y);
  if (rs.vacuum_on) { ctx.shadowColor = '#3fa7ff'; ctx.shadowBlur = 14; }
  ctx.fillStyle = '#505c68'; ctx.beginPath(); ctx.arc(0, 0, mm(20) * k, 0, 7); ctx.fill();
  ctx.shadowBlur = 0;
  ctx.strokeStyle = rs.vacuum_on ? '#3fa7ff' : '#e6edf3'; ctx.lineWidth = Math.max(2, mm(5));
  ctx.beginPath(); ctx.arc(0, 0, mm(13) * k, 0, 7); ctx.stroke();
  ctx.fillStyle = rs.vacuum_on ? '#3fa7ff' : '#2b333c'; ctx.beginPath(); ctx.arc(0, 0, mm(6) * k, 0, 7); ctx.fill();
  ctx.restore();
  label(`z=${tz.toFixed(0)}`, X + mm(45), Y - mm(25), { size: 9, color: '#8b9aab' });
}

// ========================================================================== STATUS CARDS
function card(name, val, cls, det, topic, wide) {
  return `<div class="card${wide ? ' wide' : ''}"><div class="name"><span>${name}</span><span>${topic}</span></div>
    <div class="val ${cls}">${esc(val)}</div><div class="det">${esc(det || '')}</div></div>`;
}
function updatePanels() {
  const st = S.state; if (!st) return;
  const cs = T('/conveyor/status'), ir = T('/ir_sensor/status'), det = T('/camera/detections');
  const rs = T('/robot/status'), sup = T('/supervisor/status');
  const hz = (t) => (st.topics[t] ? st.topics[t].hz : 0);
  let h = '';
  h += card('Conveyor', cs ? cs.state : 'offline', cs ? (cs.state === 'RUNNING' ? 'v-ok' : 'v-warn') : 'v-bad',
    cs ? `speed ${cs.speed_mm_s.toFixed(0)} mm/s · last cmd ${cs.last_command || '—'}` : '', '/conveyor');
  h += card('IR sensor (reactive)', ir ? ir.state : 'offline', ir ? (ir.state === 'FREE' ? 'v-ok' : 'v-bad') : 'v-bad',
    `${hz('/ir_sensor/status')} Hz · no command topic`, '/ir_sensor');
  h += card('Camera', det ? det.camera_state : 'offline', det ? 'v-acc' : 'v-bad',
    det ? `${det.pieces.length} in transport · pick zone ${det.pick_zone_occupied ? 'OCCUPIED' : 'empty'} · belt ${det.belt_motion_detected ? 'moving' : 'still'}` : '', '/camera');
  h += card('Robot', rs ? rs.state + (rs.target_bin ? ' → ' + rs.target_bin.replace('BIN_', '') : '') : 'offline',
    rs ? (rs.state === 'ERROR' ? 'v-bad' : rs.state === 'IDLE' ? '' : 'v-acc') : 'v-bad',
    rs ? `${rs.detail} · vacuum ${rs.vacuum_on ? 'ON' : 'OFF'}` : '', '/robot');
  h += card('Supervisor', sup ? sup.cell_state : 'offline', sup ? 'v-acc' : 'v-bad',
    sup ? `last: ${sup.last_rule} ${sup.last_command}` : '', '/supervisor', true);
  $('cards').innerHTML = h;

  if (sup) {
    $('kpi-state').textContent = sup.cell_state;
    $('kpi-belt').textContent = sup.pieces_on_belt;
    $('kpi-done').textContent = sup.pieces_processed;
    $('kpi-rej').textContent = sup.pieces_rejected;
  }
  // last inspection
  const r = st.inspections[0];
  if (r) {
    $('last-insp').className = 'insp';
    $('last-insp').innerHTML = `
      <div class="verdict ${r.verdict}">${r.verdict}${r.defect !== 'NONE' ? ' · ' + r.defect : ''} → ${r.destination_bin || '—'}</div>
      <span class="k">Request / piece</span><span>#${r.request_id} / piece ${r.track_id}</span>
      <span class="k">Shape · color</span><span>${r.shape} · ${r.color}</span>
      <span class="k">Measured size</span><span>${r.measured_size_mm.toFixed(2)} mm</span>
      <span class="k">Mark</span><span>${r.mark_detected ? r.mark_type : 'none'}</span>
      <span class="k">Pick pose (robot base)</span><span>x ${r.pick_x_mm.toFixed(1)} · y ${r.pick_y_mm.toFixed(1)} · z ${r.pick_z_mm.toFixed(1)} mm · yaw ${r.pick_yaw_deg.toFixed(1)}°</span>
      <span class="k">Pose confidence</span><span>${(r.pose_confidence * 100).toFixed(0)}%</span>`;
  }
  // robot strip
  const cur = rs ? rs.state : '';
  $('robot-strip').innerHTML = '<span class="lbl">Robot state machine:</span>' + ROBOT_STATES.map((s) =>
    `<span class="st ${s === cur ? 'on' : ''}">${s === 'PLACING' && cur === 'PLACING' ? 'PLACING → ' + rs.target_bin.replace('BIN_', '') : s}</span>`
  ).join('<span class="ar">→</span>') + (cur === 'ERROR' ? '<span class="st on" style="background:#ff5d5d">ERROR</span>' : '');
}

// ========================================================================== EVENT LOG
function evRow(e) {
  return `<div class="ev ${e.kind}"><span class="t">${fmtTime(e.t)}</span><span class="k">${e.kind.toUpperCase()}</span>
    <span class="tp">${esc(e.topic)}</span><span>${esc(e.text)}</span></div>`;
}
function renderLogs() {
  $('mini-log').innerHTML = S.events.slice(-30).reverse().map(evRow).join('');
  if (S.paused) return;
  const kinds = [...document.querySelectorAll('.lf')].filter((c) => c.checked).map((c) => c.value);
  $('full-log').innerHTML = S.events.filter((e) => kinds.includes(e.kind) && e.seq > (S.clearedAt || 0))
    .slice(-400).reverse().map(evRow).join('');
}
$('btn-pause').onclick = () => { S.paused = !S.paused; $('btn-pause').textContent = S.paused ? 'Resume' : 'Pause'; };
$('btn-clear').onclick = () => { S.clearedAt = S.lastSeq; renderLogs(); };
document.querySelectorAll('.lf').forEach((c) => c.onchange = renderLogs);

// ========================================================================== TOPICS TAB
const TOPIC_INFO = {
  '/conveyor/command': ['command', 'cell_interfaces/msg/ConveyorCommand', 'supervisor → conveyor'],
  '/conveyor/status': ['status', 'cell_interfaces/msg/ConveyorStatus', 'conveyor → supervisor'],
  '/ir_sensor/status': ['status', 'cell_interfaces/msg/IRSensorStatus', 'ir_sensor → supervisor'],
  '/camera/command': ['command', 'cell_interfaces/msg/CameraCommand', 'supervisor → camera'],
  '/camera/detections': ['status', 'cell_interfaces/msg/CameraDetections', 'camera → supervisor'],
  '/camera/inspection_result': ['status', 'cell_interfaces/msg/InspectionResult', 'camera → supervisor'],
  '/robot/command': ['command', 'cell_interfaces/msg/RobotCommand', 'supervisor → robot'],
  '/robot/status': ['status', 'cell_interfaces/msg/RobotStatus', 'robot → supervisor'],
  '/supervisor/status': ['info', 'cell_interfaces/msg/SupervisorStatus', 'supervisor → dashboard'],
  '/sim/world_state': ['sim', 'cell_interfaces/msg/SimWorldState', 'world_sim → ir_sensor, camera'],
  '/sim/spawn_piece': ['sim', 'cell_interfaces/msg/SpawnPiece', 'dashboard → world_sim'],
  '/sim/events': ['sim', 'std_msgs/msg/String', 'world_sim → dashboard'],
  '/camera/debug_image': ['info', 'sensor_msgs/msg/CompressedImage', 'camera → dashboard (JPEG)'],
};
function renderTopics() {
  const st = S.state; if (!st) return;
  $('topics-tbl').innerHTML = '<tr><th>Topic</th><th>Kind</th><th>Flow</th><th>Hz</th><th>Msgs</th></tr>' +
    Object.keys(TOPIC_INFO).map((t) => {
      const i = TOPIC_INFO[t], s = st.topics[t] || { hz: 0, count: 0 };
      return `<tr data-t="${t}" class="${S.selTopic === t ? 'sel' : ''}"><td><code>${t}</code><br><span class="hint">${i[1]}</span></td>
        <td><span class="pill ${i[0] === 'command' ? 'cat-camera' : i[0] === 'status' ? 'cat-conveyor' : 'cat-cycle'}">${i[0]}</span></td>
        <td>${i[2]}</td><td>${s.hz}</td><td>${s.count}</td></tr>`;
    }).join('');
  $('topics-tbl').querySelectorAll('tr[data-t]').forEach((r) => r.onclick = () => { S.selTopic = r.dataset.t; renderTopics(); });
  if (S.selTopic) {
    $('msg-topic').textContent = S.selTopic + ' (' + TOPIC_INFO[S.selTopic][1] + ')';
    let m = st.topics[S.selTopic] && st.topics[S.selTopic].last;
    if (m && S.selTopic === '/sim/world_state') m = Object.assign({}, m, { pieces: m.pieces.slice(0, 6) });
    $('msg-view').textContent = m ? JSON.stringify(m, null, 2) : 'no message received yet';
  }
}

// ========================================================================== RULES TAB
const RULE_CAT = { R1: 'safety', R2: 'safety', R3: 'safety', R4: 'conveyor', R5: 'conveyor', R6: 'camera', R7: 'camera', R8: 'robot', R9: 'robot', R10: 'cycle', R11: 'cycle' };
const RULE_CMD = {
  R1: '/conveyor/command STOP', R2: '/conveyor/command STOP', R3: '/conveyor/command STOP', R4: '/conveyor/command RUN',
  R5: '/conveyor/command STOP', R6: '/camera/command INSPECT', R7: '/camera/command INSPECT (retry)',
  R8: '/robot/command PREPARE_PICK', R9: '/robot/command PICK_AND_PLACE', R10: '(internal) reset cycle memory, count piece',
  R11: '(internal) discard the stale inspection result',
};
const lastFired = {};
function renderRules() {
  if (!S.cfg) return;
  const sup = T('/supervisor/status'), active = sup ? sup.active_rules : [];
  const now = Date.now() / 1000;
  active.forEach((r) => { lastFired[r] = now; });
  $('rules-tbl').innerHTML = '<tr><th>Rule</th><th>Group</th><th>Condition → action</th><th>Command</th></tr>' +
    Object.entries(S.cfg.rules).map(([id, txt]) => `<tr class="${active.includes(id) ? 'fired' : ''}">
      <td><b>${id}</b></td><td><span class="pill cat-${RULE_CAT[id]}">${RULE_CAT[id]}</span></td>
      <td>${esc(txt)}</td><td><code>${RULE_CMD[id]}</code></td></tr>`).join('');
  // state machines
  const cs = T('/conveyor/status'), ir = T('/ir_sensor/status'), rs = T('/robot/status'), det = T('/camera/detections');
  const sm = (title, sub, states, cur, color, note) => `<div class="smbox"><h4>${title}<span>${sub}</span></h4><div class="smrow">` +
    states.map((s) => `<span class="st ${s === cur ? 'on' : ''}" style="${s === cur ? 'background:' + color + ';border-color:' + color : ''}">${s}</span>`).join('<span class="ar">⇄</span>') +
    `</div><div class="smnote">${note}</div></div>`;
  $('sm').innerHTML =
    sm('Conveyor', '/conveyor/status', ['STOPPED', 'RUNNING'], cs && cs.state, '#3fa7ff',
      'RUNNING only when the IR sensor is FREE and there are pieces on the belt. IR OCCUPIED ⇒ ALWAYS STOPPED.') +
    sm('IR sensor', '/ir_sensor/status (reactive, no commands)', ['FREE', 'OCCUPIED'], ir && ir.state, ir && ir.state === 'OCCUPIED' ? '#ff5d5d' : '#3ccf7a',
      'Reports at 20 Hz and immediately on every change. Nobody commands it.') +
    sm('Camera', '/camera/detections', ['STREAMING', 'INSPECTING'], det && det.camera_state, '#f5c542',
      'STREAMING: preliminary detections of pieces in transport. INSPECTING: final inspection in the pick ROI after INSPECT.') +
    `<div class="smbox"><h4>Robot<span>/robot/status</span></h4><div class="smrow">` +
    ROBOT_STATES.map((s) => `<span class="st ${rs && rs.state === s ? 'on' : ''}" style="${rs && rs.state === s ? 'background:#1fb5a8;border-color:#1fb5a8' : ''}">${s}</span>`).join('<span class="ar">→</span>') +
    `<span class="ar">→ IDLE</span></div><div class="smnote">PREPARE_PICK: IDLE → WAITING_TO_PICK · PICK_AND_PLACE: → PICKING_CONVEYOR → PICKING_DONE → PLACING (bin) → RETURNING_HOME → IDLE.
      ${rs && rs.target_bin ? '<br>Current target: <b>' + rs.target_bin + '</b>' : ''}</div></div>` +
    sm('Supervisor (cell)', '/supervisor/status', ['IDLE', 'TRANSPORTING', 'INSPECTING', 'WAITING_ROBOT', 'ROBOT_PICKING', 'ROBOT_PLACING'],
      sup && sup.cell_state, '#8b6cff', 'High level label derived from the supervisor view. FAULT_* states need an operator.');
}

// ========================================================================== ARCHITECTURE (pretty rqt_graph)
const NS = 'http://www.w3.org/2000/svg';
// Layout: one horizontal LANE per device.  device ──status──► supervisor  /  supervisor ──command──► device
// Every topic pill sits at the height of its own lane, so all edges are straight horizontal
// lines and never cross. The simulation layer (optional) is drawn in a column on the left.
const LAYOUT = {
  nodes: {
    '/supervisor': { x: 1180, y: 445, w: 230, h: 760, color: '#8b6cff', title: 'supervisor', sub: 'THE BRAIN · rules R1–R11', role: 'core' },
    '/conveyor': { x: 330, y: 150, w: 230, h: 120, color: '#1fb5a8', title: 'conveyor', sub: 'RUN / STOP', role: 'device' },
    '/ir_sensor': { x: 330, y: 335, w: 230, h: 96, color: '#1fb5a8', title: 'ir_sensor', sub: 'REACTIVE: status only', role: 'device' },
    '/camera': { x: 330, y: 530, w: 230, h: 170, color: '#1fb5a8', title: 'camera', sub: 'detect + final inspection', role: 'device' },
    '/robot': { x: 330, y: 740, w: 230, h: 120, color: '#1fb5a8', title: 'robot', sub: 'UR7e + vacuum', role: 'device' },
    '/arduino_io': { x: 330, y: 245, w: 170, h: 40, color: '#d08b3e', title: 'arduino_io', sub: '', role: 'helper' },
    '/world_sim': { x: -190, y: 500, w: 220, h: 120, color: '#7d8896', title: 'world_sim', sub: 'physics (sim only)', role: 'sim' },
    '/cell_dashboard': { x: -190, y: 870, w: 220, h: 70, color: '#56616d', title: 'cell_dashboard', sub: 'web UI · operator', role: 'monitor' },
  },
  topics: {
    '/conveyor/status': { x: 755, y: 120, kind: 'status' },
    '/conveyor/command': { x: 755, y: 180, kind: 'command' },
    '/ir_sensor/status': { x: 755, y: 335, kind: 'status' },
    '/camera/detections': { x: 755, y: 480, kind: 'status' },
    '/camera/inspection_result': { x: 755, y: 530, kind: 'status' },
    '/camera/command': { x: 755, y: 580, kind: 'command' },
    '/robot/status': { x: 755, y: 710, kind: 'status' },
    '/robot/command': { x: 755, y: 770, kind: 'command' },
    '/supervisor/status': { x: 1180, y: 880, kind: 'info' },
    '/camera/debug_image': { x: 755, y: 630, kind: 'info', w: 230 },
    '/sim/world_state': { x: -190, y: 335, kind: 'sim', w: 200 },
    '/sim/spawn_piece': { x: -280, y: 690, kind: 'sim', w: 170 },
    '/sim/reset': { x: -100, y: 690, kind: 'sim', w: 140 },
  },
};
// Topics never drawn (debug chatter) and subscriptions not drawn as edges (they would cross the
// whole graph); both are still listed when you click the node / topic and in the contract table.
const HIDDEN_ARCH_TOPICS = ['/sim/events'];
const UNDRAWN_EDGES = [['/conveyor/status', '/world_sim'], ['/robot/status', '/world_sim']];
const NODE_DOC = {
  '/supervisor': ['quality_cell/nodes/supervisor_node.py', 'The ONLY node that sends commands. Every status message triggers a rule evaluation (supervisor_rules.py). Rules are ordered, safety first.'],
  '/conveyor': ['quality_cell/nodes/conveyor_node.py', 'Executes RUN / STOP and reports RUNNING / STOPPED. No logic inside.'],
  '/ir_sensor': ['quality_cell/nodes/ir_sensor_node.py', 'Purely reactive: no command topic. Publishes FREE / OCCUPIED at 20 Hz and immediately on every change.'],
  '/camera': ['quality_cell/nodes/camera_node.py', 'Streams preliminary detections (transport zone). On INSPECT runs the final inspection in the pick ROI: color, size, marks → verdict, destination bin and pick pose (robot base frame).'],
  '/robot': ['quality_cell/nodes/robot_node.py', 'State machine IDLE → WAITING_TO_PICK → PICKING_CONVEYOR → PICKING_DONE → PLACING → RETURNING_HOME → IDLE. Knows bin coordinates from the config.'],
  '/world_sim': ['quality_cell/nodes/world_sim_node.py', 'SIMULATION ONLY. Ground-truth physics: moves pieces with the belt, attaches them to the suction cup, drops them in bins. Removed in the real cell.'],
  '/arduino_io': ['quality_cell/nodes/arduino_io_node.py', 'REAL HARDWARE ONLY. Owns the Arduino serial port and holds the parameters; the /conveyor and /ir_sensor nodes of the same process talk to the Arduino through it.'],
  '/cell_dashboard': ['quality_cell/nodes/dashboard_node.py', 'This web page. Reads every topic (monitor) and acts as the operator who places pieces (/sim/spawn_piece). Never commands devices.'],
};
function topicKind(name) {
  if (LAYOUT.topics[name]) return LAYOUT.topics[name].kind;
  if (name.startsWith('/sim/')) return 'sim';
  if (name.endsWith('/command')) return 'command';
  return 'status';
}
// Expected contract: [topic, publishers, subscribers]  (dashboard excluded)
const CONTRACT = [
  ['/conveyor/command', ['/supervisor'], ['/conveyor']],
  ['/conveyor/status', ['/conveyor'], ['/supervisor', '/world_sim']],
  ['/ir_sensor/status', ['/ir_sensor'], ['/supervisor']],
  ['/camera/command', ['/supervisor'], ['/camera']],
  ['/camera/detections', ['/camera'], ['/supervisor']],
  ['/camera/inspection_result', ['/camera'], ['/supervisor']],
  ['/robot/command', ['/supervisor'], ['/robot']],
  ['/robot/status', ['/robot'], ['/supervisor', '/world_sim']],
  ['/supervisor/status', ['/supervisor'], []],
  ['/sim/world_state', ['/world_sim'], ['/ir_sensor', '/camera']],
  ['/sim/spawn_piece', ['/cell_dashboard'], ['/world_sim']],
];
function svg(tag, attrs, parent) {
  const e = document.createElementNS(NS, tag);
  for (const k in attrs) e.setAttribute(k, attrs[k]);
  if (parent) parent.appendChild(e);
  return e;
}
let archSig = '';
function drawArch(force) {
  const g = S.graph; const root = $('arch-svg');
  if (!g || !root || !$('tab-arch').classList.contains('active')) return;
  const showSim = $('t-sim').checked, showMon = $('t-mon').checked;
  const sig = JSON.stringify([g.nodes, g.topics.map((t) => [t.name, t.publishers, t.subscribers]), showSim, showMon, S.selArch]);
  if (sig === archSig && !force) return;
  archSig = sig;
  root.innerHTML = '';
  const defs = svg('defs', {}, root);
  [['status', '#3fa7ff'], ['command', '#ff9a3c'], ['sim', '#7d8896'], ['monitor', '#4a5866'], ['info', '#8b6cff'], ['missing', '#ff5d5d']].forEach(([k, c]) => {
    const m = svg('marker', { id: 'ar-' + k, viewBox: '0 0 10 10', refX: 9, refY: 5, markerWidth: 7, markerHeight: 7, orient: 'auto-start-reverse' }, defs);
    svg('path', { d: 'M0,0 L10,5 L0,10 z', fill: c }, m);
  });
  const glow = svg('filter', { id: 'glow', x: '-30%', y: '-30%', width: '160%', height: '160%' }, defs);
  svg('feGaussianBlur', { stdDeviation: 6, result: 'b' }, glow);
  const fm = svg('feMerge', {}, glow); svg('feMergeNode', { in: 'b' }, fm); svg('feMergeNode', { in: 'SourceGraphic' }, fm);

  // viewBox grows to the left when the simulation column is shown
  const X0 = showSim ? -420 : 120;
  root.setAttribute('viewBox', `${X0} 0 ${1340 - X0} 935`);
  // background columns
  const band = (x, w, text, col) => {
    svg('rect', { x, y: 18, width: w, height: 905, rx: 16, fill: col, opacity: 0.05 }, root);
    const t = svg('text', { x: x + w / 2, y: 46, fill: col, 'font-size': 14, 'font-weight': 700, 'text-anchor': 'middle', 'letter-spacing': '3' }, root);
    t.textContent = text;
  };
  if (showSim) band(-400, 420, 'SIMULATION ONLY', '#9aa5b1');
  band(190, 280, 'DEVICES', '#1fb5a8');
  band(590, 330, 'TOPICS', '#3fa7ff');
  band(1045, 270, 'SUPERVISOR', '#8b6cff');
  // lane labels between the columns
  [['status  →', 520, '#3fa7ff'], ['→  status', 980, '#3fa7ff']].forEach(([txt, x, c]) => {
    const t = svg('text', { x, y: 75, fill: c, 'font-size': 11, 'text-anchor': 'middle', opacity: 0.7 }, root); t.textContent = txt;
  });

  const live = new Set(g.nodes);
  const nodePos = {}, topicPos = {};
  Object.entries(LAYOUT.nodes).forEach(([n, l]) => { if (live.has(n) || ['core', 'device', 'sim'].includes(l.role)) nodePos[n] = Object.assign({}, l); });
  // without the simulation column the dashboard (monitor) sits under the topics
  if (nodePos['/cell_dashboard'] && !showSim) Object.assign(nodePos['/cell_dashboard'], { x: 755, y: 880 });
  // unknown nodes -> bottom row
  let ux = 520;
  g.nodes.forEach((n) => { if (!nodePos[n] && !n.startsWith('/_') && !n.includes('rqt') && !n.includes('ros2cli')) { nodePos[n] = { x: ux, y: 905, w: 170, h: 44, color: '#a67c52', title: n, sub: 'unknown node', role: 'other' }; ux += 190; } });
  const isSimNode = (n) => nodePos[n] && (nodePos[n].role === 'sim');
  const visibleNode = (n) => nodePos[n] && (showSim || !isSimNode(n)) && (showMon || n !== '/cell_dashboard' || showSim);

  const topics = g.topics.filter((t) => (!t.name.startsWith('/sim/') || showSim) &&
    !HIDDEN_ARCH_TOPICS.includes(t.name) && (t.name !== '/camera/debug_image' || showMon));
  // known topics at their lane; unknown topics stacked in the topic column below the lanes
  let uy = 940;
  topics.forEach((t) => {
    topicPos[t.name] = LAYOUT.topics[t.name] || { x: 755, y: (uy += 44), kind: topicKind(t.name) };
  });
  if (uy > 940) root.setAttribute('viewBox', `${X0} 0 ${1340 - X0} ${uy + 40}`);

  // ---- edges
  const edges = svg('g', {}, root);
  const flows = svg('g', {}, root);
  const anchor = (p, w, h, tx, ty) => {
    const dx = tx - p.x, dy = ty - p.y;
    if (Math.abs(dx) * h > Math.abs(dy) * w) return [p.x + Math.sign(dx) * w / 2, Math.max(p.y - h / 2 + 12, Math.min(p.y + h / 2 - 12, ty))];
    return [p.x, p.y + Math.sign(dy) * h / 2];
  };
  const curve = (a, b) => {
    const dx = b[0] - a[0], dy = b[1] - a[1];
    if (Math.abs(dx) > Math.abs(dy) * 0.4) return `M${a[0]},${a[1]} C${a[0] + dx * 0.5},${a[1]} ${b[0] - dx * 0.5},${b[1]} ${b[0]},${b[1]}`;
    return `M${a[0]},${a[1]} C${a[0]},${a[1] + dy * 0.5} ${b[0]},${b[1] - dy * 0.5} ${b[0]},${b[1]}`;
  };
  const TW = 270, TH = 36;
  const tw = (p) => p.w || TW;
  S.archEdges = [];
  const addEdge = (from, to, kind, topic, missing) => {
    if (UNDRAWN_EDGES.some(([a, b]) => a === from && b === to)) return;
    const fn = nodePos[from] || null, tn = nodePos[to] || null;
    const fp = fn ? fn : topicPos[from], tp = tn ? tn : topicPos[to];
    if (!fp || !tp) return;
    const a = anchor(fp, fn ? fn.w : tw(fp), fn ? fn.h : TH, tp.x, tp.y);
    const b = anchor(tp, tn ? tn.w : tw(tp), tn ? tn.h : TH, fp.x, fp.y);
    const d = curve(a, b);
    const cls = missing ? 'missing' : kind;
    const sel = S.selArch && (S.selArch === from || S.selArch === to || S.selArch === topic);
    const p = svg('path', { d, class: 'edge ' + cls, 'marker-end': `url(#ar-${cls})`, 'data-topic': topic,
      opacity: S.selArch && !sel ? 0.12 : 0.9 }, edges);
    if (!missing && kind !== 'monitor') {
      const f = svg('path', { d, class: 'flow ' + (kind === 'info' ? 'status' : kind), 'data-topic': topic, opacity: 0 }, flows);
      S.archEdges.push({ topic, base: p, flow: f, dimmed: S.selArch && !sel });
    }
  };
  topics.forEach((t) => {
    const kind = topicKind(t.name);
    t.publishers.forEach((n) => { if (visibleNode(n) && (n !== '/cell_dashboard' || showSim)) addEdge(n, t.name, n === '/cell_dashboard' ? 'sim' : kind === 'info' ? 'info' : kind, t.name); });
    t.subscribers.forEach((n) => {
      if (!visibleNode(n)) return;
      if (n === '/cell_dashboard' && !showMon) return;
      const k = n === '/cell_dashboard' ? 'monitor' : (isSimNode(n) || t.name.startsWith('/sim/')) ? 'sim' : kind === 'info' ? 'info' : kind;
      addEdge(t.name, n, k, t.name);
    });
  });
  // expected-but-missing edges
  CONTRACT.forEach(([tn, pubs, subs]) => {
    if (!topicPos[tn]) return;
    const t = g.topics.find((x) => x.name === tn);
    pubs.forEach((n) => { if (nodePos[n] && visibleNode(n) && !(t && t.publishers.includes(n))) addEdge(n, tn, 'missing', tn, true); });
    subs.forEach((n) => { if (nodePos[n] && visibleNode(n) && !(t && t.subscribers.includes(n))) addEdge(tn, n, 'missing', tn, true); });
  });
  // expected topics that do not exist at all
  CONTRACT.forEach(([tn]) => { if (!topicPos[tn] && LAYOUT.topics[tn] && (showSim || !tn.startsWith('/sim/'))) topicPos[tn] = Object.assign({ ghost: true }, LAYOUT.topics[tn]); });

  // ---- topics
  const colorOf = { status: '#3fa7ff', command: '#ff9a3c', sim: '#7d8896', info: '#8b6cff' };
  Object.entries(topicPos).forEach(([name, p]) => {
    const c = colorOf[p.kind] || '#3fa7ff';
    const W = tw(p);
    const grp = svg('g', { class: 'topic' + (S.selArch === name ? ' selected' : ''), transform: `translate(${p.x - W / 2},${p.y - TH / 2})`,
      opacity: S.selArch && S.selArch !== name && !(S.archEdges.some((e) => e.topic === name && !e.dimmed)) ? 0.35 : 1 }, root);
    svg('rect', { width: W, height: TH, rx: TH / 2, fill: '#121a22', stroke: p.ghost ? '#ff5d5d' : c, 'stroke-width': 1.8, 'stroke-dasharray': p.ghost ? '3 4' : '' }, grp);
    const tx = svg('text', { x: W / 2 - (W > 200 ? 14 : 0), y: TH / 2 + 1, fill: '#dbe4ee', 'font-size': W > 200 ? 13.5 : 12, 'text-anchor': 'middle', 'dominant-baseline': 'middle', 'font-family': 'JetBrains Mono, monospace' }, grp);
    tx.textContent = name;
    const hz = svg('text', { x: W - 12, y: TH / 2 + 1, fill: c, 'font-size': 9.5, 'text-anchor': 'end', 'dominant-baseline': 'middle', class: 'hz', 'data-topic': name }, grp);
    hz.textContent = '';
    grp.onclick = () => { S.selArch = S.selArch === name ? null : name; showArchInfo(); drawArch(true); };
  });
  // ---- nodes
  Object.entries(nodePos).forEach(([name, n]) => {
    if (!visibleNode(name)) return;
    const alive = live.has(name);
    const grp = svg('g', { class: 'node' + (S.selArch === name ? ' selected' : ''), transform: `translate(${n.x - n.w / 2},${n.y - n.h / 2})` }, root);
    svg('rect', { width: n.w, height: n.h, rx: 12, fill: '#141c25', stroke: alive ? n.color : '#ff5d5d', 'stroke-dasharray': alive ? '' : '6 4',
      filter: n.role === 'core' ? 'url(#glow)' : '' }, grp);
    svg('rect', { width: n.w, height: 6, rx: 3, fill: alive ? n.color : '#ff5d5d' }, grp);
    const cy = n.role === 'core' ? 70 : n.role === 'helper' ? n.h / 2 + 5 : n.h / 2 - 4;
    const t1 = svg('text', { x: n.w / 2, y: cy, fill: '#fff', 'font-size': n.role === 'core' ? 26 : n.role === 'helper' ? 13 : 18, 'font-weight': 700, 'text-anchor': 'middle' }, grp);
    t1.textContent = n.title;
    const t2 = svg('text', { x: n.w / 2, y: cy + (n.role === 'core' ? 28 : 22), fill: '#9aa5b1', 'font-size': 12.5, 'text-anchor': 'middle' }, grp);
    t2.textContent = n.sub;
    svg('circle', { cx: n.w - 14, cy: 18, r: 5, fill: alive ? '#3ccf7a' : '#ff5d5d' }, grp);
    if (n.role === 'core') {
      const lines = ['status in → update view', '→ evaluate rules (safety first)', '→ publish commands', '', 'R1–R3 safety stops', 'R4–R5 conveyor', 'R6–R7 camera', 'R8–R9 robot', 'R10–R11 cycle'];
      lines.forEach((l, i) => { const t = svg('text', { x: n.w / 2, y: n.h / 2 - 60 + i * 26, fill: i < 3 ? '#c9bfff' : '#9aa5b1', 'font-size': 14, 'text-anchor': 'middle' }, grp); t.textContent = l; });
    }
    if (name === '/ir_sensor') {
      const t = svg('text', { x: n.w / 2, y: n.h / 2 + 38, fill: '#ff9a3c', 'font-size': 11.5, 'text-anchor': 'middle' }, grp);
      t.textContent = 'no command topic (by design)';
    }
    if (name === '/world_sim') {
      ['also listens to', '/conveyor/status, /robot/status'].forEach((l, i) => {
        const t = svg('text', { x: n.w / 2, y: n.h - 26 + i * 14, fill: '#7d8896', 'font-size': 10.5, 'text-anchor': 'middle' }, grp); t.textContent = l;
      });
    }
    grp.onclick = () => { S.selArch = S.selArch === name ? null : name; showArchInfo(); drawArch(true); };
  });
  renderContract();
  animateArch(true);
}
function showArchInfo() {
  const k = S.selArch, el = $('arch-info'); const g = S.graph;
  if (!k) { el.innerHTML = '<h3>How to read this graph</h3><p><b>Rectangles</b> are ROS 2 nodes, <b>pills</b> are topics. The <b>supervisor</b> is the only node that sends commands. Devices only execute commands and report status. The <b>IR sensor has no command topic</b>: it is purely reactive.</p><p>Click any node or topic for details.</p>'; return; }
  if (k.startsWith('/') && NODE_DOC[k] !== undefined || LAYOUT.nodes[k]) {
    const pubs = g.topics.filter((t) => t.publishers.includes(k)).map((t) => t.name);
    const subs = g.topics.filter((t) => t.subscribers.includes(k)).map((t) => t.name);
    const d = NODE_DOC[k] || ['', ''];
    el.innerHTML = `<h3>Node ${k}</h3><p>${d[1]}</p><p><code>${d[0]}</code></p>
      <b>Publishes</b><ul>${pubs.map((p) => `<li><code>${p}</code></li>`).join('') || '<li>—</li>'}</ul>
      <b>Subscribes</b><ul>${subs.map((p) => `<li><code>${p}</code></li>`).join('') || '<li>—</li>'}</ul>`;
  } else {
    const t = g.topics.find((x) => x.name === k);
    const st = S.state && S.state.topics[k];
    el.innerHTML = `<h3>Topic ${k}</h3><p><code>${t ? t.type : (TOPIC_INFO[k] || [])[1] || '?'}</code></p>
      <p>${st ? st.hz + ' Hz · ' + st.count + ' messages' : ''}</p>
      <b>Publishers</b><ul>${(t ? t.publishers : []).map((p) => `<li><code>${p}</code></li>`).join('') || '<li>—</li>'}</ul>
      <b>Subscribers</b><ul>${(t ? t.subscribers : []).map((p) => `<li><code>${p}</code></li>`).join('') || '<li>—</li>'}</ul>
      <p class="note">Inspect it from a terminal:<br><code>ros2 topic echo ${k}</code><br><code>ros2 topic info -v ${k}</code></p>`;
  }
}
function animateArch() {
  if (!S.archEdges || !S.state) return;
  const anim = $('t-anim').checked;
  S.archEdges.forEach((e) => {
    const st = S.state.topics[e.topic];
    const hz = st ? st.hz : 0;
    e.flow.setAttribute('opacity', anim && hz > 0 && !e.dimmed ? 0.9 : 0);
    if (hz > 0) e.flow.style.animationDuration = Math.max(0.25, 1.6 - Math.min(hz, 50) / 35) + 's';
    const c = st ? st.count : 0;
    if (anim && S.prevCounts[e.topic] !== undefined && c > S.prevCounts[e.topic] && (e.topic.endsWith('/command') || e.topic.endsWith('inspection_result'))) {
      e.base.classList.remove('pulse'); void e.base.getBBox(); e.base.classList.add('pulse');
    }
  });
  document.querySelectorAll('#arch-svg text.hz').forEach((t) => {
    const st = S.state.topics[t.dataset.topic]; t.textContent = st && st.hz ? st.hz + ' Hz' : '';
  });
}
function renderContract() {
  const g = S.graph; if (!g) return;
  const has = (list, n) => list.includes(n);
  $('contract-tbl').innerHTML = '<tr><th>Topic</th><th>Type</th><th>Expected publishers</th><th>Expected subscribers</th></tr>' +
    CONTRACT.map(([tn, pubs, subs]) => {
      const t = g.topics.find((x) => x.name === tn) || { publishers: [], subscribers: [], type: '(not found)' };
      const chip = (n, ok) => `<span class="pill ${ok ? 'ok' : 'bad'}">${ok ? '✓' : '✗'} ${n}</span>`;
      return `<tr><td><code>${tn}</code></td><td><code>${t.type}</code></td>
        <td>${pubs.map((n) => chip(n, has(t.publishers, n))).join('')}</td>
        <td>${subs.map((n) => chip(n, has(t.subscribers, n))).join('') || '<span class="hint">monitoring only</span>'}</td></tr>`;
    }).join('');
}
['t-sim', 't-mon'].forEach((id) => $(id).onchange = () => drawArch(true));

// ========================================================================== POLLING
async function pollState() {
  try {
    const st = await getJSON('/api/state');
    if (S.state) Object.entries(S.state.topics).forEach(([k, v]) => { S.prevCounts[k] = v.count; });
    S.state = st;
    $('conn').classList.add('ok'); $('conn-text').textContent = 'connected to ROS 2';
    updatePanels(); renderTopics(); renderRules(); animateArch(); pumpQueue();
  } catch (e) {
    $('conn').classList.remove('ok'); $('conn-text').textContent = 'dashboard_node not reachable';
  }
  setTimeout(pollState, 140);
}
async function pollEvents() {
  try {
    const ev = await getJSON('/api/events?since=' + S.lastSeq);
    if (ev.length) {
      if (ev[0].seq < S.lastSeq) S.events = [];
      S.events.push(...ev); S.lastSeq = ev[ev.length - 1].seq;
      if (S.events.length > 600) S.events = S.events.slice(-600);
      renderLogs();
      ev.filter((e) => e.kind === 'sim' && /REJECTED|WARNING|OUTSIDE/.test(e.text)).forEach((e) => toast(e.text));
    }
  } catch (e) { /* ignore */ }
  setTimeout(pollEvents, 300);
}
async function pollGraph() {
  try { S.graph = await getJSON('/api/graph'); drawArch(false); } catch (e) { /* ignore */ }
  setTimeout(pollGraph, 1000);
}
function frame() { drawCell(); requestAnimationFrame(frame); }
// Camera image: reload only when the previous one has arrived (no request pile-up)
function pollCamera() {
  const img = $('cam-img');
  const next = new Image();
  next.onload = () => { img.src = next.src; $('cam-img').style.display = ''; $('cam-note').textContent = ''; setTimeout(pollCamera, 200); };
  next.onerror = () => {
    $('cam-img').style.display = 'none';
    $('cam-note').textContent = 'No camera image: the camera uses the "sim" backend (ground truth, no images). Set camera.backend: opencv to see the real vision pipeline.';
    setTimeout(pollCamera, 2000);
  };
  next.src = '/api/camera.jpg?t=' + Date.now();
}

(async function init() {
  initForm();
  for (;;) {
    try { S.cfg = await getJSON('/api/config'); break; } catch (e) { await new Promise((r) => setTimeout(r, 1000)); }
  }
  resizeCanvas();
  pollState(); pollEvents(); pollGraph(); pollCamera();
  requestAnimationFrame(frame);
}());
