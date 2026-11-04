// Chat: thread, streaming replies, action chips and the resizable side panel.
import { chatMenu, renameChat } from '../actions.js';
import { api, enc, loadLists, streamMessage, uploadFile } from '../api.js';
import { $, copyText, fileTag, h, icon, store } from '../dom.js';
import { md } from '../markdown.js';
import { filesCard, folderCard, latestRender, outUrl, progressCard } from '../panels/files.js';
import { slidesView, summaryView } from '../panels/insights.js';
import { openDocument, renderViewer } from '../panels/viewer.js';
import { emit, go, on, state } from '../state.js';
import { Composer } from '../ui/composer.js';
import { toast } from '../ui/overlay.js';
import { modeOf, prefChips, rememberDefaults } from '../ui/prefs.js';
import { isWide } from './sidebar.js';

let composer = null;
let actionsEl = null;
let mobilePanel = false;
let prefs = null; // this chat's mode / model / think

/** Called by the router when leaving a chat: temporary chats are deleted then. */
export async function leaveChat(nextHash) {
  const chat = state.chat;
  if (chat?.temporary && !nextHash.endsWith(chat.id)) {
    try { await api('DELETE', `/api/chats/${chat.id}`); } catch { /* already gone */ }
  }
}

export async function renderChat(view, topbar, id) {
  let chat;
  let project;
  try {
    chat = await api('GET', `/api/chats/${id}`);
    project = await api('GET', `/api/projects/${enc(chat.project)}`);
  } catch (e) {
    toast(e.message);
    go('#/');
    return;
  }
  state.chat = chat;
  state.project = project;
  state.projectPage = false;
  if (state.viewer && state.viewer.project !== project.id) state.viewer = null;
  document.title = `${chat.title} · ${project.title}`;
  emit('lists');

  const more = h('button', { class: 'icon-btn', type: 'button', 'aria-haspopup': 'menu', title: 'Chat options', 'aria-label': 'Chat options' }, icon('more'));
  more.addEventListener('click', () => chatMenu(chat, more));
  topbar.replaceChildren(h('div', { class: 'title' },
    h('a', { href: `#/project/${project.id}`, title: 'Open project', onclick: (e) => { e.preventDefault(); go(`#/project/${project.id}`); } }, project.title),
    h('span', { class: 'sep', text: '/' }),
    h('button', { class: 'cur', type: 'button', title: 'Rename chat', onclick: () => renameChat(chat) }, chat.title)),
  h('button', { class: 'icon-btn', type: 'button', id: 'panel-toggle', title: 'Project panel (Ctrl+J)', 'aria-label': 'Toggle project panel', onclick: togglePanel }, icon('panel')),
  more);

  prefs = { mode: chat.prefs?.mode || 'auto', model: chat.prefs?.model || '', think: chat.prefs?.think ?? null };
  const chips = prefChips(prefs, (p) => { rememberDefaults(p); composer.setPlaceholder(modeOf(p.mode).placeholder); });
  composer = new Composer({ placeholder: modeOf(prefs.mode).placeholder, right: [chips.mode, chips.model], onSubmit: (msg) => send(msg) });
  const tempBar = chat.temporary ? h('div', { class: 'note temp-note' }, icon('ghost', 'sm'),
    h('span', { style: { flex: '1' } }, h('strong', { text: 'Temporary chat. ' }), 'Not saved or listed; deleted when you leave.'),
    h('button', {
      class: 'btn sm', type: 'button',
      onclick: async () => {
        try { await api('PATCH', `/api/chats/${chat.id}`, { temporary: false }); chat.temporary = false; tempBar.remove(); await loadLists(); toast('Chat kept'); } catch (e) { toast(e.message); }
      },
    }, 'Keep this chat')) : null;
  actionsEl = h('div', { class: 'actions' });
  view.replaceChildren(h('div', { class: 'chat' },
    h('div', { class: 'thread-scroll', id: 'thread-scroll' }, h('div', { class: 'thread', id: 'thread' })),
    h('div', { class: 'dock' }, tempBar, actionsEl, composer.el,
      h('p', { class: 'disclaimer', text: 'Runs entirely on this computer. Answers can be wrong — check the cited sources.' }))));
  renderThread();
  renderActions();
  renderPanel();
  composer.focus();

  if (state.pendingFill) { composer.fill(state.pendingFill); state.pendingFill = null; }
  if (state.pendingSend) {
    const msg = state.pendingSend;
    state.pendingSend = null;
    if (msg.prefs) { Object.assign(prefs, msg.prefs); chips.refresh(); composer.setPlaceholder(modeOf(prefs.mode).placeholder); }
    send(msg);
  }
}

// ---------------------------------------------------------------- thread
function renderThread() {
  const thread = $('#thread');
  const msgs = state.chat.messages;
  if (!msgs.length) {
    const files = state.project.files.length;
    thread.replaceChildren(h('div', { class: 'chat-hint' },
      h('h2', { text: files ? 'What would you like to know?' : 'Add the RFP to begin' }),
      files ? `${state.project.title} has ${files} file${files > 1 ? 's' : ''}. Ask a question, or use Analyse RFP and Build slides below.`
        : 'Drop the RFP onto this window, or use the paperclip. It is read, checked for patient data and indexed.'));
    return;
  }
  thread.replaceChildren(...msgs.map((m, i) => (m.role === 'user'
    ? userMsg(m.content, m.files)
    : assistantMsg(m.content, m.outputs, i === msgs.length - 1 ? state.chat.pending : null, m.sources))));
  scrollDown(true);
}

function userMsg(text, files = []) {
  return h('div', { class: 'msg user' },
    files.length ? h('div', { class: 'files' }, files.map((n) => h('button', {
      class: 'attach-card openable', type: 'button', title: `Open ${n}`,
      onclick: () => openDocument(n),
    }, fileTag(n), h('span', { class: 'nm ellipsis', text: n })))) : null,
    text ? h('div', { class: 'bubble', text }) : null);
}

/** Make citation chips open the cited passage in the viewer. */
function wireCites(el, sources) {
  if (!sources?.length) return;
  for (const chip of el.querySelectorAll('.cite')) {
    const label = chip.textContent.trim();
    const src = sources.find((s) => s.label === label) || sources.find((s) => String(s.n) === label);
    if (!src) continue;
    chip.classList.add('link');
    chip.setAttribute('role', 'button');
    chip.tabIndex = 0;
    chip.title = `Open ${src.file}${src.page ? `, page ${src.page}` : ''}`;
    const open = () => openDocument(src.file, { page: src.page, text: src.text, section: src.section });
    chip.addEventListener('click', open);
    chip.addEventListener('keydown', (e) => { if (e.key === 'Enter') open(); });
  }
}

function assistantMsg(text, outputs = [], pending = null, sources = []) {
  const el = h('div', { class: 'msg assistant' }, h('div', { class: 'prose', html: md(text) }));
  wireCites(el, sources);
  if (outputs?.length) el.append(outputCards(outputs));
  if (pending) el.append(confirmRow(pending));
  el.append(tools(() => text));
  return el;
}

function tools(getText) {
  const copy = h('button', { class: 'icon-btn sm', type: 'button', title: 'Copy', 'aria-label': 'Copy reply' }, icon('copy', 'sm'));
  copy.addEventListener('click', async () => {
    if (await copyText(getText())) { copy.replaceChildren(icon('check', 'sm')); setTimeout(() => copy.replaceChildren(icon('copy', 'sm')), 1200); }
  });
  return h('div', { class: 'tools' }, copy);
}

function outputCards(names) {
  return h('div', { class: 'outputs' }, names.map((n) => h('a', { class: 'out-card', href: outUrl(state.project.id, n), download: n, title: `Download ${n}` },
    fileTag(n), h('div', {}, h('div', { class: 'nm', text: n }), h('div', { class: 'sz', text: 'Download' })), icon('download', 'sm'))));
}

function confirmRow(command) {
  const row = h('div', { class: 'confirm-row' },
    h('button', { class: 'btn primary sm', type: 'button', onclick: () => { row.remove(); send({ text: '/approve', display: `Run /${command}` }); } }, `Run /${command}`),
    h('button', { class: 'btn sm', type: 'button', onclick: () => { row.remove(); send({ text: '/reject', display: 'Cancel' }); } }, 'Cancel'));
  return row;
}

function nearBottom() {
  const s = $('#thread-scroll');
  return !s || s.scrollHeight - s.scrollTop - s.clientHeight < 140;
}
function scrollDown(force) {
  const s = $('#thread-scroll');
  if (s && (force || nearBottom())) s.scrollTop = s.scrollHeight;
}

// ---------------------------------------------------------------- sending
export async function send({ text = '', files = [], display, steps }) {
  if (state.streaming || !state.chat) return;
  const chat = state.chat;
  const controller = new AbortController();
  state.streaming = controller;
  composer?.sync();
  renderActions();

  const thread = $('#thread');
  thread.querySelector('.chat-hint')?.remove();
  thread.querySelectorAll('.confirm-row').forEach((el) => el.remove());
  const shown = display ?? text;
  thread.append(userMsg(shown, files.map((f) => f.name)));
  const body = h('div', { class: 'prose' });
  const status = h('div', { class: 'status' }, h('span', { class: 'dots' }, h('i'), h('i'), h('i')), h('span', { class: 'shimmer', text: 'Thinking…' }));
  const msgEl = h('div', { class: 'msg assistant' }, body, status);
  thread.append(msgEl);
  scrollDown(true);
  const setStatus = (t) => { status.lastChild.textContent = t; };

  let reply = '';
  let outputs = [];
  let pending = null;
  let sources = [];
  let frame = 0;
  const paint = () => {
    frame = 0;
    const stick = nearBottom();
    body.innerHTML = md(reply);
    if (stick) scrollDown(true);
  };

  try {
    const names = [];
    for (const f of files) { setStatus(`Uploading ${f.name}…`); names.push((await uploadFile(chat.project, f)).name); }
    setStatus(files.length ? 'Reading the files…' : 'Thinking…');
    const choice = steps ? {} : { mode: prefs?.mode, model: prefs?.model || '', think: prefs?.think ?? null };
    await streamMessage(chat.id, { text, display: shown, steps, files: names, ...choice }, {
      chunk: (t) => { reply += t; if (!frame) frame = requestAnimationFrame(paint); },
      status: setStatus,
      pending: (cmd) => { pending = cmd; },
      sources: (d) => { sources = d.sources || []; },
      done: (d) => { outputs = d.outputs || []; },
      error: (t) => msgEl.append(h('div', { class: 'err-line', text: t })),
    }, controller.signal);
  } catch (err) {
    msgEl.append(h('div', { class: 'err-line', text: err.name === 'AbortError'
      ? 'Stopped. Work already started finishes in the background; reopen the chat to see it.' : err.message }));
  } finally {
    if (frame) cancelAnimationFrame(frame);
    paint();
    wireCites(msgEl, sources);
    status.remove();
    if (outputs.length) msgEl.append(outputCards(outputs));
    if (pending) msgEl.append(confirmRow(pending));
    msgEl.append(tools(() => reply));
    state.streaming = null;
    composer?.sync();
    scrollDown();
    if (state.chat?.id === chat.id) {
      try {
        state.chat = await api('GET', `/api/chats/${chat.id}`);
        state.project = await api('GET', `/api/projects/${enc(chat.project)}`);
        const title = document.querySelector('.topbar .title .cur');
        if (title) title.textContent = state.chat.title;
        renderActions();
        renderPanel();
      } catch { /* keep what is shown */ }
    }
    loadLists().catch(() => {});
  }
}

// ---------------------------------------------------------------- actions
function renderActions() {
  if (!actionsEl || !state.project) return;
  const busy = Boolean(state.streaming);
  const latest = latestRender(state.project);
  const chips = [
    h('button', { class: 'chip', type: 'button', disabled: busy || null, onclick: () => runAction('analyse') }, icon('doc', 'sm'), 'Analyse RFP'),
    h('button', { class: 'chip', type: 'button', disabled: busy || null, onclick: () => runAction('slides') }, icon('slides', 'sm'), 'Build slides'),
  ];
  if (latest) chips.push(h('a', { class: 'chip', href: outUrl(state.project.id, latest), download: latest, title: `Download ${latest}` }, icon('download', 'sm'), 'Download PPTX'));
  actionsEl.replaceChildren(...chips);
}

export function runAction(action) {
  const st = state.project?.status || {};
  if (!st.chunks) { toast('Add the RFP first — drop it into the chat.'); return; }
  if (action === 'analyse') {
    showTab('summary');
    send({ text: '/digest', display: 'Analyse the RFP', steps: ['/digest'] });
  } else {
    showTab('slides');
    const steps = [...(st.digest ? [] : ['/digest']), '/deck', '/render'];
    send({ text: steps[0], display: 'Build the slides', steps });
  }
}

// ---------------------------------------------------------------- side panel
export function showTab(tab) {
  state.panelTab = tab;
  state.panelOpen = true;
  mobilePanel = !isWide();
  store.set('ps.panelTab', tab);
  store.set('ps.panelOpen', '1');
  renderPanel();
}

export function togglePanel() {
  if (!state.chat) return;
  if (isWide()) {
    state.panelOpen = $('#panel').hidden;
    store.set('ps.panelOpen', state.panelOpen ? '1' : '0');
  } else {
    mobilePanel = $('#panel').hidden;
    state.panelOpen = true;
  }
  renderPanel();
}

export function hidePanel() {
  $('#panel').hidden = true;
  $('#resizer').hidden = true;
}

let panelToken = 0;
export function renderPanel() {
  const panel = $('#panel');
  const wide = isWide();
  const onChat = Boolean(state.chat);
  const onProject = !onChat && state.projectPage && Boolean(state.viewer);
  const open = ((onChat && state.panelOpen) || onProject) && (wide || mobilePanel);
  panel.hidden = !open;
  $('#resizer').hidden = !open || !wide;
  $('#panel-toggle')?.classList.toggle('active', open);
  if (!open) return;
  const p = state.project;
  const tabs = onChat ? [['files', 'Files'], ['document', 'Document'], ['summary', 'RFP summary'], ['slides', 'Slides']] : [['document', 'Document']];
  if (!onChat) state.panelTab = 'document';
  const body = h('div', { class: 'panel-body' });
  panel.replaceChildren(
    h('div', { class: 'panel-head' },
      h('div', { class: 'tabs', role: 'tablist' }, tabs.map(([k, label]) => h('button', {
        class: `tab${state.panelTab === k ? ' active' : ''}`, type: 'button', role: 'tab', 'aria-selected': String(state.panelTab === k),
        onclick: () => showTab(k),
      }, label))),
      h('span', { class: 'grow' }),
      h('button', { class: 'icon-btn', type: 'button', title: 'Close panel', 'aria-label': 'Close panel', onclick: () => {
        mobilePanel = false;
        if (!onChat) state.viewer = null;
        else if (wide) { state.panelOpen = false; store.set('ps.panelOpen', '0'); }
        renderPanel();
      } }, icon('x'))),
    body);
  const busy = Boolean(state.streaming);
  if (state.panelTab === 'document') {
    renderViewer(body, { onAsk: onChat ? (t) => composer?.fill(t) : (t) => askInChat(t) });
    return;
  }
  if (state.panelTab === 'files') {
    body.append(
      filesCard(p, { onAdd: (files) => send({ text: '', files }), onChanged: (proj) => { state.project = proj; renderPanel(); renderActions(); }, onOpen: (n) => openDocument(n) }),
      folderCard(p), progressCard(p));
    return;
  }
  const token = ++panelToken;
  body.append(h('div', { class: 'status' }, h('span', { class: 'dots' }, h('i'), h('i'), h('i')), h('span', { class: 'muted', text: 'Loading…' })));
  const fn = state.panelTab === 'summary'
    ? summaryView(p, { busy, onAnalyse: () => runAction('analyse') })
    : slidesView(p, { busy, onBuild: () => runAction('slides') });
  fn.then((node) => { if (token === panelToken) body.replaceChildren(node); })
    .catch((e) => { if (token === panelToken) body.replaceChildren(h('div', { class: 'empty', text: e.message })); });
}

/** From the project page: open the newest chat with `text` in its composer. */
async function askInChat(text) {
  try {
    const chat = state.project.chats[0] || await api('POST', `/api/projects/${enc(state.project.id)}/chats`);
    state.pendingFill = text;
    go(`#/chat/${chat.id}`);
  } catch (e) { toast(e.message); }
}

on('show-document', () => showTab('document'));

export function setupResizer() {
  const resizer = $('#resizer');
  const setW = (px) => {
    const w = Math.max(340, Math.min(Math.round(window.innerWidth * 0.75), Math.round(px)));
    document.documentElement.style.setProperty('--panel-w', `${w}px`);
    return w;
  };
  const saved = Number(store.get('ps.panelW', '0'));
  if (saved) setW(saved);
  resizer.addEventListener('pointerdown', (e) => {
    e.preventDefault();
    resizer.setPointerCapture(e.pointerId);
    resizer.classList.add('dragging');
    document.body.classList.add('resizing');
    const move = (ev) => setW(window.innerWidth - ev.clientX);
    const up = (ev) => {
      resizer.releasePointerCapture(ev.pointerId);
      resizer.classList.remove('dragging');
      document.body.classList.remove('resizing');
      resizer.removeEventListener('pointermove', move);
      resizer.removeEventListener('pointerup', up);
      store.set('ps.panelW', String(setW(window.innerWidth - ev.clientX)));
    };
    resizer.addEventListener('pointermove', move);
    resizer.addEventListener('pointerup', up);
  });
  resizer.addEventListener('dblclick', () => {
    const now = $('#panel').getBoundingClientRect().width;
    const big = Math.round(window.innerWidth * 0.6);
    store.set('ps.panelW', String(setW(now < big - 20 ? big : 460)));
  });
  resizer.addEventListener('keydown', (e) => {
    const now = $('#panel').getBoundingClientRect().width;
    if (e.key === 'ArrowLeft') store.set('ps.panelW', String(setW(now + 40)));
    if (e.key === 'ArrowRight') store.set('ps.panelW', String(setW(now - 40)));
  });
  window.addEventListener('resize', () => { const w = Number(store.get('ps.panelW', '0')); if (w) setW(w); });
}
