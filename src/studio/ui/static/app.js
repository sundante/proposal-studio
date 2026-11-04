/* Proposal Studio UI — vanilla JS, no build step, no external requests. */
'use strict';

// ---------------------------------------------------------------- helpers
const $ = (sel, el = document) => el.querySelector(sel);
const $$ = (sel, el = document) => [...el.querySelectorAll(sel)];

function h(tag, props = {}, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(props || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === 'class') el.className = v;
    else if (k === 'text') el.textContent = v;
    else if (k === 'html') el.innerHTML = v; // only ever given output of md()/esc()
    else if (k.startsWith('on')) el.addEventListener(k.slice(2), v);
    else el.setAttribute(k, v === true ? '' : v);
  }
  for (const kid of kids.flat()) {
    if (kid === null || kid === undefined || kid === false) continue;
    el.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
  }
  return el;
}

const svg = (paths) => {
  const el = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  el.setAttribute('viewBox', '0 0 20 20');
  el.innerHTML = paths;
  return el;
};
const ICON = {
  folder: '<path d="M2.5 5.5a1 1 0 011-1h4l2 2h7a1 1 0 011 1v8a1 1 0 01-1 1h-13a1 1 0 01-1-1z"/>',
  chat: '<path d="M4 4.5h12a1 1 0 011 1v7a1 1 0 01-1 1H9l-4 3v-3H4a1 1 0 01-1-1v-7a1 1 0 011-1z"/>',
  plus: '<path d="M10 4v12M4 10h12"/>',
  x: '<path d="M5 5l10 10M15 5L5 15"/>',
  copy: '<rect x="6.5" y="6.5" width="10" height="10" rx="2"/><path d="M13.5 6.5V4.5a1 1 0 00-1-1h-8a1 1 0 00-1 1v8a1 1 0 001 1h2"/>',
  check: '<path d="M4 10.5l4 4 8-9"/>',
  send: '<path d="M10 16V4M5 9l5-5 5 5"/>',
  stop: '<rect x="5" y="5" width="10" height="10" rx="2"/>',
  download: '<path d="M10 3v10M6 9l4 4 4-4M4 16h12"/>',
  trash: '<path d="M4 6h12M8 6V4h4v2M6 6l1 10h6l1-10"/>',
  more: '<circle cx="5" cy="10" r="1.2"/><circle cx="10" cy="10" r="1.2"/><circle cx="15" cy="10" r="1.2"/>',
  open: '<path d="M11 3.5h5.5V9M16.5 3.5L9 11M14 12v3.5a1 1 0 01-1 1H4.5a1 1 0 01-1-1V7a1 1 0 011-1H8"/>',
  edit: '<path d="M13.5 3.5l3 3L7 16H4v-3z"/>',
  link: '<rect x="6.5" y="6.5" width="10" height="10" rx="2"/><path d="M13.5 6.5V4.5a1 1 0 00-1-1h-8a1 1 0 00-1 1v8a1 1 0 001 1h2"/>',
};

const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => (
  { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

const store = {
  get(k, d) { try { return localStorage.getItem(k) ?? d; } catch { return d; } },
  set(k, v) { try { localStorage.setItem(k, v); } catch { /* private mode */ } },
};

function toast(text, ms = 3500) {
  const el = $('#toast');
  el.textContent = text;
  el.hidden = false;
  clearTimeout(toast.t);
  toast.t = setTimeout(() => { el.hidden = true; }, ms);
}

async function api(method, url, body) {
  const opts = { method, headers: { 'X-Studio': '1' } };
  if (body instanceof Blob) opts.body = body;
  else if (body !== undefined) {
    opts.headers['Content-Type'] = 'application/json';
    opts.body = JSON.stringify(body);
  }
  const res = await fetch(url, opts);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const err = new Error(data.error || `HTTP ${res.status}`);
    err.status = res.status;
    err.data = data;
    if (data.needs_login) showLogin();
    throw err;
  }
  return data;
}

const ext = (name) => (name.includes('.') ? name.split('.').pop().slice(0, 4) : 'file');
const stem = (name) => name.replace(/\.[^.]+$/, '').replace(/[_-]+/g, ' ').trim();
const natural = (a, b) => a.localeCompare(b, undefined, { numeric: true });
const outUrl = (project, name) => `/api/projects/${encodeURIComponent(project)}/out/${encodeURIComponent(name)}`;

// ---------------------------------------------------------------- markdown
function inline(text) {
  const keep = [];
  const stash = (html) => `\u0000${keep.push(html) - 1}\u0000`;
  let s = esc(text);
  s = s.replace(/`([^`]+)`/g, (_, c) => stash(`<code>${c}</code>`));
  s = s.replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, (_, label, url) => {
    const raw = url.replace(/&amp;/g, '&');
    if (!/^(https?:\/\/|\/|#)/i.test(raw)) return label;
    return stash(`<a href="${esc(raw)}" target="_blank" rel="noopener noreferrer">${label}</a>`);
  });
  s = s.replace(/\[(\d+(?:[ ,][^\]]{0,80})?)\]/g, (_, c) => stash(`<span class="cite">${c}</span>`));
  s = s.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
  s = s.replace(/(^|[\s(])\*([^*\s][^*]*)\*(?=[\s).,;:!?]|$)/g, '$1<em>$2</em>');
  s = s.replace(/(^|[\s(])_([^_\s][^_]*)_(?=[\s).,;:!?]|$)/g, '$1<em>$2</em>');
  return s.replace(/\u0000(\d+)\u0000/g, (_, i) => keep[Number(i)]);
}

function md(src) {
  const lines = String(src || '').replace(/\r/g, '').split('\n');
  const out = [];
  let i = 0;
  const isBlockStart = (l) => /^(```|#{1,4}\s|\s*([-*+]|\d+\.)\s+|>\s?|\|.*\|\s*$|(-{3,}|\*{3,})\s*$|→ |Next: )/.test(l);

  while (i < lines.length) {
    const l = lines[i];
    if (/^```/.test(l)) {
      const buf = [];
      i += 1;
      while (i < lines.length && !/^```/.test(lines[i])) buf.push(lines[i++]);
      i += 1;
      out.push(`<pre><code>${esc(buf.join('\n'))}</code></pre>`);
      continue;
    }
    if (!l.trim()) { i += 1; continue; }
    // Router plumbing ("→ routed to /x", "Next: `/cmd`") is for the CLI; buttons replace it here.
    if (/^→ (routed|not routed)/.test(l) || /^Next: /.test(l)) { i += 1; continue; }
    const head = l.match(/^(#{1,4})\s+(.*)$/);
    if (head) { out.push(`<h${head[1].length}>${inline(head[2])}</h${head[1].length}>`); i += 1; continue; }
    if (/^(-{3,}|\*{3,})\s*$/.test(l)) { out.push('<hr>'); i += 1; continue; }
    if (/^\|.*\|\s*$/.test(l) && i + 1 < lines.length && /^\|?\s*:?-{2,}/.test(lines[i + 1])) {
      const cells = (row) => row.trim().replace(/^\||\|$/g, '').split('|').map((c) => inline(c.trim()));
      const headCells = cells(l);
      i += 2;
      const rows = [];
      while (i < lines.length && /^\|.*\|\s*$/.test(lines[i])) rows.push(cells(lines[i++]));
      out.push(`<table><thead><tr>${headCells.map((c) => `<th>${c}</th>`).join('')}</tr></thead><tbody>${
        rows.map((r) => `<tr>${r.map((c) => `<td>${c}</td>`).join('')}</tr>`).join('')}</tbody></table>`);
      continue;
    }
    if (/^\s*([-*+]|\d+\.)\s+/.test(l)) {
      const items = [];
      while (i < lines.length && /^\s*([-*+]|\d+\.)\s+/.test(lines[i])) {
        const m = lines[i].match(/^(\s*)([-*+]|\d+\.)\s+(.*)$/);
        items.push({ depth: Math.floor(m[1].replace(/\t/g, '  ').length / 2), ordered: /\d/.test(m[2]), text: m[3] });
        i += 1;
        while (i < lines.length && /^\s{2,}\S/.test(lines[i]) && !/^\s*([-*+]|\d+\.)\s+/.test(lines[i])) {
          items[items.length - 1].text += ` ${lines[i].trim()}`;
          i += 1;
        }
      }
      let html = '';
      const stack = [];
      for (const it of items) {
        while (stack.length && stack[stack.length - 1].depth > it.depth) html += `</li></${stack.pop().tag}>`;
        const top = stack[stack.length - 1];
        if (!top || top.depth < it.depth) {
          const tag = it.ordered ? 'ol' : 'ul';
          stack.push({ depth: it.depth, tag });
          html += `<${tag}><li>`;
        } else html += '</li><li>';
        const box = it.text.match(/^\[( |x)\]\s+(.*)$/i);
        html += box ? `${box[1].trim() ? '☑' : '☐'} ${inline(box[2])}` : inline(it.text);
      }
      while (stack.length) html += `</li></${stack.pop().tag}>`;
      out.push(html);
      continue;
    }
    if (/^>\s?/.test(l)) {
      const buf = [];
      while (i < lines.length && /^>\s?/.test(lines[i])) buf.push(lines[i++].replace(/^>\s?/, ''));
      out.push(`<blockquote>${md(buf.join('\n'))}</blockquote>`);
      continue;
    }
    const buf = [l];
    i += 1;
    while (i < lines.length && lines[i].trim() && !isBlockStart(lines[i])) buf.push(lines[i++]);
    const text = buf.map(inline).join('<br>');
    out.push(/^\s*⚠/.test(l) ? `<p class="warn">${text}</p>` : `<p>${text}</p>`);
  }
  return out.join('\n');
}

// ---------------------------------------------------------------- state
const state = {
  projects: [],
  recent: [],
  project: null, // detail of the open project
  chat: null, // open chat (with messages)
  streaming: null, // AbortController while a reply streams
  panelTab: store.get('ps.panelTab', 'files'),
  panelOpen: store.get('ps.panelOpen', '1') === '1',
  settings: null, // { home, library, user_dir, user_home, sep }
};

// ---------------------------------------------------------------- composer
class Composer {
  constructor(slot, onSend) {
    this.el = $('#composer-tpl').content.firstElementChild.cloneNode(true);
    slot.append(this.el);
    this.ta = $('textarea', this.el);
    this.chips = $('.chips', this.el);
    this.input = $('input[type=file]', this.el);
    this.sendBtn = $('.send', this.el);
    this.files = [];
    this.onSend = onSend;
    this.ta.addEventListener('input', () => this.sync());
    this.ta.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); this.submit(); }
    });
    $('.attach', this.el).addEventListener('click', () => this.input.click());
    this.input.addEventListener('change', () => { this.add([...this.input.files]); this.input.value = ''; });
    this.el.addEventListener('submit', (e) => { e.preventDefault(); this.submit(); });
    this.ta.addEventListener('paste', (e) => {
      const files = [...(e.clipboardData?.files || [])];
      if (files.length) { e.preventDefault(); this.add(files); }
    });
    this.sync();
  }

  add(files) {
    for (const f of files) {
      if (!this.files.some((x) => x.name === f.name)) this.files.push(f);
    }
    this.renderChips();
    this.sync();
    this.ta.focus();
  }

  renderChips() {
    this.chips.replaceChildren(...this.files.map((f) => h('span', { class: 'file-chip' },
      h('span', { class: 'ext', text: ext(f.name) }),
      h('span', { class: 'nm', text: f.name, title: f.name }),
      h('button', {
        type: 'button', title: `Remove ${f.name}`, 'aria-label': `Remove ${f.name}`,
        onclick: () => { this.files = this.files.filter((x) => x !== f); this.renderChips(); this.sync(); },
      }, svg(ICON.x)))));
  }

  sync() {
    this.ta.style.height = 'auto';
    if (this.ta.scrollHeight) this.ta.style.height = `${this.ta.scrollHeight}px`; // 0 while hidden
    const busy = Boolean(state.streaming);
    this.sendBtn.classList.toggle('stop', busy);
    this.sendBtn.replaceChildren(svg(busy ? ICON.stop : ICON.send));
    this.sendBtn.title = busy ? 'Stop' : 'Send';
    this.sendBtn.disabled = !busy && !this.ta.value.trim() && !this.files.length;
  }

  submit() {
    if (state.streaming) { state.streaming.abort(); return; }
    const text = this.ta.value.trim();
    if (!text && !this.files.length) return;
    const files = this.files;
    this.files = [];
    this.ta.value = '';
    this.renderChips();
    this.sync();
    this.onSend({ text, files });
  }

  fill(text) { this.ta.value = text; this.sync(); this.ta.focus(); }
}

let homeComposer;
let chatComposer;
const syncComposers = () => { homeComposer.sync(); chatComposer.sync(); };

// ---------------------------------------------------------------- navigation
function go(hash) {
  if (location.hash !== hash) history.pushState(null, '', hash);
  route();
}

async function route() {
  closeSidebar();
  const m = location.hash.match(/^#\/chat\/([0-9a-f]{12})$/);
  if (m) {
    try { await openChat(m[1]); return; } catch (err) { toast(err.message); }
  }
  showHome();
}

function showHome() {
  state.chat = null;
  state.project = null;
  $('#home').hidden = false;
  $('#chat').hidden = true;
  $('#panel').hidden = true;
  $('#toggle-panel').hidden = true;
  $('#crumbs').replaceChildren();
  document.title = 'Proposal Studio';
  renderSidebar();
  homeComposer.ta.focus();
}

async function openChat(id) {
  const chat = await api('GET', `/api/chats/${id}`);
  state.chat = chat;
  await loadProject(chat.project);
  $('#home').hidden = true;
  $('#chat').hidden = false;
  $('#toggle-panel').hidden = false;
  renderCrumbs();
  renderThread();
  renderPanel();
  renderSidebar();
  chatComposer.ta.focus();
}

async function loadProject(id) {
  state.project = await api('GET', `/api/projects/${encodeURIComponent(id)}`);
  renderActions();
}

async function refreshLists() {
  [state.projects, state.recent] = await Promise.all([api('GET', '/api/projects'), api('GET', '/api/chats')]);
  renderSidebar();
}

// ---------------------------------------------------------------- sidebar
function renderSidebar() {
  const activeProject = state.project?.id;
  const activeChat = state.chat?.id;
  const list = $('#project-list');
  if (!state.projects.length) {
    list.replaceChildren(h('li', { class: 'side-empty', text: 'No projects yet — use New project' }));
  } else {
    list.replaceChildren(...state.projects.map((p) => {
      const open = p.id === activeProject;
      const row = h('li', {},
        h('div', {
          class: `side-item project${open && !activeChat ? ' active' : ''}${p.missing ? ' missing' : ''}`,
          role: 'button', tabindex: '0', title: p.path,
          onclick: () => (p.missing ? projectMenu(p, row.firstChild) : openProject(p)),
          onkeydown: (e) => { if (e.key === 'Enter') openProject(p); },
        },
        svg(ICON.folder),
        h('span', { class: 't' }, p.title,
          h('span', { class: 'where', text: p.missing ? 'Folder missing — click to remove' : compactPath(p.path) })),
        h('button', {
          class: 'add', title: 'Project options', 'aria-label': `Options for ${p.title}`,
          onclick: (e) => { e.stopPropagation(); projectMenu(p, e.currentTarget); },
        }, svg(ICON.more))));
      if (open) {
        const chats = p.chats.filter((c) => c.id === activeChat || c.title !== 'New chat' || p.chats.length === 1);
        row.append(h('ul', { class: 'side-chats' }, chats.map((c) => chatItem(c, false))));
      }
      return row;
    }));
  }
  const recent = $('#recent-list');
  recent.replaceChildren(...(state.recent.length
    ? state.recent.slice(0, 15).map((c) => chatItem(c, true))
    : [h('li', { class: 'side-empty', text: 'Your chats will appear here' })]));
}

/** The last two folders of a path: ``…/Proposal Studio/Acme 2026`` (full path in the tooltip). */
const compactPath = (p) => {
  const parts = shortPath(p).split(/[\\/]/).filter(Boolean);
  return parts.length > 2 ? `…/${parts.slice(-2).join('/')}` : shortPath(p);
};

const shortPath = (p) => {
  const home = state.settings?.user_home;
  return home && p.startsWith(home) ? `~${p.slice(home.length)}` : p;
};

// ---------------------------------------------------------------- popover menu
function popMenu(anchor, items) {
  closeMenu();
  const menu = h('div', { class: 'menu', role: 'menu' }, items.map((it) => (it === '-' ? h('div', { class: 'menu-sep' })
    : h('button', {
      class: `menu-item${it.danger ? ' danger' : ''}`, role: 'menuitem', type: 'button',
      onclick: () => { closeMenu(); it.run(); },
    }, svg(it.icon), it.label))));
  document.body.append(menu);
  const r = anchor.getBoundingClientRect();
  const left = Math.min(r.left, window.innerWidth - menu.offsetWidth - 8);
  const top = r.bottom + menu.offsetHeight + 8 > window.innerHeight ? r.top - menu.offsetHeight - 4 : r.bottom + 4;
  menu.style.left = `${Math.max(8, left)}px`;
  menu.style.top = `${Math.max(8, top)}px`;
  popMenu.el = menu;
  setTimeout(() => document.addEventListener('click', closeMenu, { once: true }), 0);
  menu.querySelector('button')?.focus();
}
function closeMenu() {
  popMenu.el?.remove();
  popMenu.el = null;
}

function projectMenu(p, anchor) {
  const items = p.missing ? [
    { label: 'Remove from Proposal Studio', icon: ICON.trash, danger: true, run: () => removeProject(p, false) },
  ] : [
    { label: 'New chat', icon: ICON.plus, run: () => newChat(p.id) },
    { label: 'Rename', icon: ICON.edit, run: () => renameProject(p) },
    { label: 'Open folder', icon: ICON.open, run: () => revealProject(p) },
    { label: 'Copy folder path', icon: ICON.link, run: () => copyText(p.path, 'Folder path copied') },
    '-',
    { label: 'Remove from list (keep files)', icon: ICON.x, run: () => removeProject(p, false) },
    { label: 'Delete project and its folder…', icon: ICON.trash, danger: true, run: () => removeProject(p, true) },
  ];
  popMenu(anchor, items);
}

async function copyText(text, done) {
  try { await navigator.clipboard.writeText(text); toast(done); } catch { toast(text, 8000); }
}

async function revealProject(p) {
  try { await api('POST', `/api/projects/${encodeURIComponent(p.id)}/reveal`); } catch (e) { toast(e.message); }
}

async function renameProject(p) {
  const title = prompt('Project name', p.title);
  if (!title || title.trim() === p.title) return;
  try {
    await api('PATCH', `/api/projects/${encodeURIComponent(p.id)}`, { title: title.trim() });
    await refreshLists();
    if (state.project?.id === p.id) { await loadProject(p.id); renderCrumbs(); }
  } catch (e) { toast(e.message); }
}

async function removeProject(p, deleteFiles) {
  const msg = deleteFiles
    ? `Delete “${p.title}” and everything in its folder?\n\n${p.path}\n\nUploaded files, chats, summaries and decks in that folder are permanently deleted.`
    : `Remove “${p.title}” from Proposal Studio?\n\nThe folder and its files stay on your computer:\n${p.path}\n\nYou can add it back later with New project → Open an existing project folder.`;
  if (!confirm(msg)) return;
  try {
    await api('DELETE', `/api/projects/${encodeURIComponent(p.id)}${deleteFiles ? '?files=delete' : ''}`);
    toast(deleteFiles ? `Deleted ${p.title}` : `Removed ${p.title} (files kept)`);
    if (state.project?.id === p.id) go('#/');
    await refreshLists();
  } catch (e) { toast(e.message); }
}

function chatItem(c, withProject) {
  const project = state.projects.find((p) => p.id === c.project);
  return h('li', {}, h('div', {
    class: `side-item${c.id === state.chat?.id ? ' active' : ''}`, role: 'button', tabindex: '0',
    onclick: () => go(`#/chat/${c.id}`),
    onkeydown: (e) => { if (e.key === 'Enter') go(`#/chat/${c.id}`); },
  },
  withProject ? svg(ICON.chat) : null,
  h('span', { class: 't', title: c.title }, c.title,
    withProject && project ? h('span', { class: 'sub', text: ` · ${project.title}` }) : null),
  h('button', {
    class: 'add', title: 'Delete chat', 'aria-label': `Delete chat ${c.title}`,
    onclick: (e) => { e.stopPropagation(); deleteChat(c); },
  }, svg(ICON.trash))));
}

function openProject(p) {
  if (p.chats.length) go(`#/chat/${p.chats[0].id}`);
  else newChat(p.id);
}

async function newChat(projectId) {
  try {
    const chat = await api('POST', `/api/projects/${encodeURIComponent(projectId)}/chats`);
    await refreshLists();
    go(`#/chat/${chat.id}`);
  } catch (err) { toast(err.message); }
}

async function deleteChat(c) {
  if (!confirm(`Delete the chat “${c.title}”? The project and its files stay.`)) return;
  try {
    await api('DELETE', `/api/chats/${c.id}`);
    await refreshLists();
    if (state.chat?.id === c.id) go('#/');
  } catch (err) { toast(err.message); }
}

function closeSidebar() { $('#app').classList.remove('sidebar-open'); }

// ---------------------------------------------------------------- crumbs (rename in place)
function renderCrumbs() {
  const p = state.project;
  const c = state.chat;
  document.title = `${c.title} · ${p.title}`;
  $('#crumbs').replaceChildren(
    editable(p.title, 'Rename project', async (title) => {
      await api('PATCH', `/api/projects/${encodeURIComponent(p.id)}`, { title });
      p.title = title;
    }),
    h('span', { class: 'sep', text: '/' }),
    editable(c.title, 'Rename chat', async (title) => {
      await api('PATCH', `/api/chats/${c.id}`, { title });
      c.title = title;
    }),
  );
}

function editable(value, label, save) {
  const span = h('span', { class: 'title', text: value, title: label, tabindex: '0', role: 'button' });
  const start = () => {
    const input = h('input', { value, 'aria-label': label });
    let done = false;
    const finish = async (keep) => {
      if (done) return;
      done = true;
      const next = input.value.trim();
      if (keep && next && next !== value) {
        try { await save(next); await refreshLists(); } catch (err) { toast(err.message); }
      }
      renderCrumbs();
    };
    input.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') finish(true);
      if (e.key === 'Escape') finish(false);
    });
    input.addEventListener('blur', () => finish(true));
    span.replaceWith(input);
    input.focus();
    input.select();
  };
  span.addEventListener('click', start);
  span.addEventListener('keydown', (e) => { if (e.key === 'Enter') start(); });
  return span;
}

// ---------------------------------------------------------------- thread
function renderThread() {
  const thread = $('#thread');
  const msgs = state.chat.messages;
  thread.replaceChildren(...msgs.map((m, idx) => (m.role === 'user'
    ? userMsg(m.content, m.files)
    : assistantMsg(m.content, m.outputs, idx === msgs.length - 1 ? state.chat.pending : null))));
  if (!msgs.length) thread.append(emptyChat());
  scrollDown(true);
}

function emptyChat() {
  const files = state.project?.files || [];
  return h('div', { class: 'msg assistant' }, h('div', { class: 'md' }, h('p', {},
    files.length
      ? `This project has ${files.length} file${files.length > 1 ? 's' : ''}. Ask a question, or use Analyse RFP / Build slides below.`
      : 'Drop the RFP files here (or use the paperclip) to get started.')));
}

function userMsg(text, files = []) {
  return h('div', { class: 'msg user' },
    files.length ? h('div', { class: 'files' }, files.map((n) => h('span', { class: 'file-chip' },
      h('span', { class: 'ext', text: ext(n) }), h('span', { class: 'nm', text: n, title: n })))) : null,
    text ? h('div', { class: 'bubble', text }) : null);
}

function assistantMsg(text, outputs = [], pending = null) {
  const body = h('div', { class: 'md', html: md(text) });
  const el = h('div', { class: 'msg assistant' }, body);
  if (outputs?.length) el.append(outputChips(outputs));
  if (pending) el.append(confirmRow(pending));
  el.append(h('div', { class: 'meta-row' }, copyButton(() => text)));
  return el;
}

function outputChips(names) {
  return h('div', { class: 'outputs' }, names.map((n) => h('a', {
    class: 'file-chip', href: outUrl(state.project.id, n), download: n, title: `Download ${n}`,
  }, h('span', { class: 'ext', text: ext(n) }), h('span', { class: 'nm', text: n }), svg(ICON.download))));
}

function confirmRow(command) {
  const row = h('div', { class: 'confirm' },
    h('button', { class: 'btn primary', onclick: () => { row.remove(); send({ text: '/approve', display: `Yes, run /${command}` }); } }, `Run /${command}`),
    h('button', { class: 'btn', onclick: () => { row.remove(); send({ text: '/reject', display: 'Cancel' }); } }, 'Cancel'));
  return row;
}

function copyButton(getText) {
  const btn = h('button', { class: 'icon-btn', title: 'Copy', 'aria-label': 'Copy reply' }, svg(ICON.copy));
  btn.addEventListener('click', async () => {
    try {
      await navigator.clipboard.writeText(getText());
      btn.replaceChildren(svg(ICON.check));
      setTimeout(() => btn.replaceChildren(svg(ICON.copy)), 1200);
    } catch { toast('Copy failed'); }
  });
  return btn;
}

function nearBottom() {
  const s = $('#thread-scroll');
  return s.scrollHeight - s.scrollTop - s.clientHeight < 120;
}
function scrollDown(force) {
  const s = $('#thread-scroll');
  if (force || nearBottom()) s.scrollTop = s.scrollHeight;
}

// ---------------------------------------------------------------- sending
async function sendFromHome({ text, files }) {
  const name = files.length ? stem(files[0].name) : text.split(/\s+/).slice(0, 6).join(' ');
  openNewProject({
    name: name || 'Untitled project',
    onCreated: async (chat) => { await send({ text, files }); },
    restore: () => { homeComposer.add(files); if (text) homeComposer.fill(text); },
  });
}

async function uploadAll(files) {
  const names = [];
  for (const f of files) {
    setStatus(`Uploading ${f.name}…`);
    const res = await api('PUT', `/api/projects/${encodeURIComponent(state.project.id)}/uploads/${encodeURIComponent(f.name)}`, f);
    names.push(res.name);
  }
  return names;
}

let statusEl = null;
function setStatus(text) {
  if (!statusEl) return;
  statusEl.replaceChildren(h('span', { class: 'dots' }, h('i'), h('i'), h('i')), h('span', { text }));
}

async function send({ text = '', files = [], display, steps }) {
  if (state.streaming || !state.chat) return;
  const chat = state.chat;
  const controller = new AbortController();
  state.streaming = controller;
  syncComposers();
  renderActions();

  $('#thread').querySelector('.msg.assistant:only-child')?.remove(); // the empty-chat hint
  $$('.confirm', $('#thread')).forEach((el) => el.remove());
  const shown = display ?? text;
  $('#thread').append(userMsg(shown, files.map((f) => f.name)));
  const body = h('div', { class: 'md' });
  statusEl = h('div', { class: 'status' });
  const msgEl = h('div', { class: 'msg assistant' }, body, statusEl);
  $('#thread').append(msgEl);
  setStatus('Thinking…');
  scrollDown(true);

  let reply = '';
  let outputs = [];
  let pending = null;
  let frame = 0;
  const paint = () => {
    frame = 0;
    const stick = nearBottom();
    body.innerHTML = md(reply);
    if (stick) scrollDown(true);
  };

  try {
    const names = files.length ? await uploadAll(files) : [];
    setStatus('Thinking…');
    const res = await fetch(`/api/chats/${chat.id}/messages`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Studio': '1' },
      body: JSON.stringify({ text, display: shown, steps, files: names }),
      signal: controller.signal,
    });
    if (!res.ok || !res.body) {
      const data = await res.json().catch(() => ({}));
      throw new Error(data.error || `HTTP ${res.status}`);
    }
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buf = '';
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      let cut;
      while ((cut = buf.indexOf('\n\n')) >= 0) {
        const block = buf.slice(0, cut);
        buf = buf.slice(cut + 2);
        const event = (block.match(/^event: (.*)$/m) || [])[1];
        const raw = (block.match(/^data: (.*)$/m) || [])[1];
        if (!event || raw === undefined) continue;
        const data = JSON.parse(raw);
        if (event === 'chunk') {
          reply += data.text;
          if (!frame) frame = requestAnimationFrame(paint);
        } else if (event === 'status') setStatus(data.text);
        else if (event === 'pending') pending = data.command;
        else if (event === 'done') outputs = data.outputs || [];
        else if (event === 'error') msgEl.append(h('div', { class: 'error-line', text: `⚠ ${data.text}` }));
      }
    }
  } catch (err) {
    if (err.name === 'AbortError') {
      msgEl.append(h('div', { class: 'error-line', text: 'Stopped. Work already started finishes in the background; reopen the chat to see it.' }));
    } else {
      msgEl.append(h('div', { class: 'error-line', text: `⚠ ${err.message}` }));
    }
  } finally {
    if (frame) cancelAnimationFrame(frame);
    paint();
    statusEl.remove();
    statusEl = null;
    if (outputs.length) msgEl.append(outputChips(outputs));
    if (pending) msgEl.append(confirmRow(pending));
    msgEl.append(h('div', { class: 'meta-row' }, copyButton(() => reply)));
    state.streaming = null;
    syncComposers();
    scrollDown();
    if (state.chat?.id === chat.id) {
      try {
        state.chat = await api('GET', `/api/chats/${chat.id}`);
        await loadProject(chat.project);
        renderCrumbs();
        renderPanel();
      } catch { /* keep what is shown */ }
    }
    refreshLists().catch(() => {});
  }
}

// ---------------------------------------------------------------- actions
function latestRender() {
  const renders = state.project?.status?.renders || [];
  return renders.slice().sort(natural).pop() || null;
}

function renderActions() {
  const busy = Boolean(state.streaming);
  $$('#actions .action[data-action]').forEach((b) => { b.disabled = busy; });
  const link = $('#download-pptx');
  const latest = latestRender();
  link.hidden = !latest;
  if (latest) {
    link.href = outUrl(state.project.id, latest);
    link.setAttribute('download', latest);
    link.title = `Download ${latest}`;
  }
}

function runAction(action) {
  const st = state.project?.status || {};
  if (!st.chunks) {
    toast('Add the RFP files first: drop them into the chat.');
    return;
  }
  if (action === 'analyse') {
    showPanel('summary');
    send({ text: '/digest', display: 'Analyse the RFP', steps: ['/digest'] });
  } else if (action === 'slides') {
    showPanel('slides');
    const steps = [...(st.digest ? [] : ['/digest']), '/deck', '/render'];
    send({ text: steps[0], display: 'Build the slides', steps });
  }
}

// ---------------------------------------------------------------- side panel
function showPanel(tab) {
  if (tab) state.panelTab = tab;
  state.panelOpen = true;
  store.set('ps.panelTab', state.panelTab);
  store.set('ps.panelOpen', '1');
  renderPanel();
}

function renderPanel() {
  const panel = $('#panel');
  const wide = window.matchMedia('(min-width: 861px)').matches;
  panel.hidden = !state.chat || !state.panelOpen || (!wide && !renderPanel.mobileOpen);
  $('#panel-resizer').hidden = panel.hidden || !wide;
  if (panel.hidden) return;
  $$('.tab', panel).forEach((t) => t.classList.toggle('active', t.dataset.tab === state.panelTab));
  const body = $('#panel-body');
  const tab = state.panelTab;
  if (tab === 'files') body.replaceChildren(filesTab());
  else if (tab === 'summary') loadInto(body, summaryTab);
  else loadInto(body, slidesTab);
}
renderPanel.mobileOpen = false;

async function loadInto(body, fn) {
  const token = (loadInto.token = (loadInto.token || 0) + 1);
  body.replaceChildren(h('div', { class: 'status' }, h('span', { class: 'dots' }, h('i'), h('i'), h('i')), 'Loading…'));
  const node = await fn().catch((err) => h('div', { class: 'empty', text: err.message }));
  if (token === loadInto.token) body.replaceChildren(node);
}

function filesTab() {
  const p = state.project;
  const frag = h('div', {},
    h('div', { class: 'folder-head' },
      h('div', { class: 'lbl', text: 'Project folder' }),
      h('div', { class: 'path', text: p.path, title: p.path }),
      h('div', { class: 'row-btns' },
        h('button', { class: 'btn', type: 'button', onclick: () => revealProject(p) }, svg(ICON.open), 'Open folder'),
        h('button', { class: 'btn', type: 'button', onclick: () => copyText(p.path, 'Folder path copied') }, 'Copy path'))),
    h('h3', { text: 'Project files' }));
  if (!p.files.length) frag.append(h('div', { class: 'empty', text: 'No files yet.' }));
  for (const f of p.files) {
    frag.append(h('div', { class: 'file-row' },
      h('span', { class: 'file-chip' }, h('span', { class: 'ext', text: ext(f.name) })),
      h('span', { class: 'nm', text: f.name, title: f.name }),
      h('span', { class: 'sub', text: f.chunks ? `${f.chunks} passages` : 'not indexed' }),
      h('button', {
        class: 'icon-btn', title: `Remove ${f.name}`, 'aria-label': `Remove ${f.name}`,
        onclick: async () => {
          if (!confirm(`Remove ${f.name} from this project? Answers will no longer use it.`)) return;
          try {
            state.project = await api('DELETE', `/api/projects/${encodeURIComponent(p.id)}/files/${encodeURIComponent(f.name)}`);
            renderPanel();
          } catch (err) { toast(err.message); }
        },
      }, svg(ICON.trash))));
  }
  const picker = h('input', { type: 'file', multiple: true, hidden: true, accept: '.pdf,.docx,.xlsx,.pptx,.txt,.md' });
  picker.addEventListener('change', () => {
    const files = [...picker.files];
    if (files.length) send({ text: '', files });
  });
  frag.append(picker, h('div', {
    class: 'dropzone', role: 'button', tabindex: '0', onclick: () => picker.click(),
    onkeydown: (e) => { if (e.key === 'Enter') picker.click(); },
  }, 'Add files — PDF, Word, Excel, PowerPoint, text'));
  const st = p.status;
  frag.append(h('h3', { text: 'Progress' }), h('ul', { class: 'items' },
    h('li', {}, `${st.chunks ? '✅' : '⬜'} Files read (${st.chunks || 0} passages)`),
    h('li', {}, `${st.digest ? (st.digest_stale ? '🟡' : '✅') : '⬜'} RFP analysed${st.digest_stale ? ' — files changed since, analyse again' : ''}`),
    h('li', {}, `${st.deck ? '✅' : '⬜'} Slides written`),
    h('li', {}, `${st.renders.length ? '✅' : '⬜'} PowerPoint built${st.renders.length ? ` (${latestRender()})` : ''}`)));
  return frag;
}

const citeText = (cites) => (cites || []).map((c) => (c.page ? `${c.section}, p.${c.page}` : c.section)).join('; ');

async function summaryTab() {
  let data;
  try {
    data = await api('GET', `/api/projects/${encodeURIComponent(state.project.id)}/digest`);
  } catch (err) {
    if (err.status !== 404) throw err;
    return h('div', { class: 'empty' }, 'No RFP summary yet.', h('br'),
      h('button', { class: 'btn primary', onclick: () => runAction('analyse'), disabled: Boolean(state.streaming) }, 'Analyse RFP'));
  }
  const d = data.digest;
  const o = d.opportunity || {};
  const root = h('div', {});
  if (data.stale) root.append(h('div', { class: 'notice', text: 'Files changed since this summary. Analyse again to refresh it.' }));
  if (o.due_date) root.append(h('div', { class: 'due' }, h('div', { class: 'lbl', text: 'Proposal due' }), h('div', { class: 'val', text: o.due_date })));
  const kv = [['Client', o.client], ['Title', o.title], ['Format', o.submission_format], ['Limits', o.page_or_slide_limits]].filter(([, v]) => v);
  if (kv.length) root.append(h('dl', { class: 'kv' }, kv.flatMap(([k, v]) => [h('dt', { text: k }), h('dd', { text: v })])));

  const section = (title, items, render) => {
    if (!items?.length) return;
    root.append(h('h3', { text: `${title} (${items.length})` }), h('ul', { class: 'items' }, items.map((it) => h('li', {}, ...render(it)))));
  };
  const src = (c) => (c?.length ? h('div', { class: 'src', text: citeText(c) }) : null);
  section('Requirements', d.requirements, (r) => [
    h('span', { class: `badge${r.mandatory ? ' must' : ''}`, text: r.mandatory ? 'MUST' : 'should' }),
    h('span', { class: 'badge', text: r.type }), r.text, src(r.cite)]);
  section('Evaluation criteria', d.evaluation_criteria, (e) => [e.criterion, e.weight ? h('strong', { text: ` — ${e.weight}` }) : null, src(e.cite)]);
  section('Business problems', d.business_problems, (x) => [x.statement, src(x.evidence)]);
  section('Technical problems', d.technical_problems, (x) => [x.statement, src(x.evidence)]);
  section('Current state', d.current_state, (x) => [x.item, src(x.evidence)]);
  section('Desired outcomes', d.desired_outcomes, (x) => [x.item, src(x.evidence)]);
  section('Compliance', d.compliance, (x) => [h('strong', { text: `${x.framework}: ` }), x.detail, src(x.cite)]);
  section('Systems mentioned', d.systems_mentioned, (x) => [h('strong', { text: x.name }), x.role ? ` — ${x.role}` : '']);
  section('Risks and red flags', d.risks_and_red_flags, (x) => [x.item, src(x.cite)]);
  section('Open questions', d.open_questions, (x) => [x]);
  return root;
}

const SKIP = new Set(['id', 'slide_type', 'title', 'speaker_notes', 'sources', 'review']);
const label = (k) => k.replace(/_/g, ' ').replace(/^\w/, (c) => c.toUpperCase());

function slideContent(s) {
  const frame = h('div', { class: 'slide-frame' }, h('div', { class: 'st', text: s.title }));
  if (s.slide_type === 'before_after') {
    frame.append(h('div', { class: 'cols' },
      h('div', {}, h('div', { class: 'colh', text: s.before_title || 'Today' }), h('ul', {}, (s.before || []).map((b) => h('li', { text: b })))),
      h('div', {}, h('div', { class: 'colh', text: s.after_title || 'With us' }), h('ul', {}, (s.after || []).map((b) => h('li', { text: b }))))));
    return frame;
  }
  for (const [k, v] of Object.entries(s)) {
    if (SKIP.has(k) || v === null || v === '' || (Array.isArray(v) && !v.length)) continue;
    if (typeof v === 'string') frame.append(h('div', { text: v }));
    else if (Array.isArray(v)) {
      frame.append(h('ul', {}, v.map((item) => {
        if (typeof item === 'string') return h('li', { text: item });
        if (item.components) return h('li', {}, h('strong', { text: `${item.name}: ` }), item.components.join(', '));
        if (item.when) return h('li', {}, h('strong', { text: `${item.when}: ` }), item.what);
        if (item.description) return h('li', {}, h('strong', { text: `${item.name}: ` }), item.description);
        return h('li', { text: Object.values(item).join(' — ') });
      })));
    } else frame.append(h('div', { class: 'src', text: `${label(k)}: ${JSON.stringify(v)}` }));
  }
  return frame;
}

async function slidesTab() {
  let deck;
  try {
    deck = await api('GET', `/api/projects/${encodeURIComponent(state.project.id)}/deck`);
  } catch (err) {
    if (err.status !== 404) throw err;
    return h('div', { class: 'empty' }, 'No slides yet.', h('br'),
      h('button', { class: 'btn primary', onclick: () => runAction('slides'), disabled: Boolean(state.streaming) }, 'Build slides'));
  }
  const root = h('div', {});
  const latest = latestRender();
  if (latest) {
    root.append(h('a', { class: 'btn primary', href: outUrl(state.project.id, latest), download: latest, style: 'display:inline-flex;gap:8px;align-items:center;text-decoration:none;margin-bottom:14px' },
      svg(ICON.download), `Download ${latest}`));
  } else {
    root.append(h('div', { class: 'notice', text: 'Slides are written but not built into PowerPoint yet. Use Build slides.' }));
  }
  const slides = deck.slides || [];
  root.append(h('h3', { text: `${slides.length} slides` }));
  slides.forEach((s, n) => {
    const card = h('div', { class: 'slide' }, slideContent(s),
      h('div', { class: 'slide-foot' }, h('span', { text: `${n + 1} · ${label(s.slide_type)}` }), h('span', { text: s.id })));
    if (s.review?.length) card.append(h('div', { class: 'slide-review' }, h('strong', { text: 'Please review' }), h('ul', {}, s.review.map((r) => h('li', { text: r })))));
    root.append(card);
  });
  return root;
}

// ---------------------------------------------------------------- drag and drop
function setupDrop() {
  let depth = 0;
  const overlay = $('#drop');
  const hasFiles = (e) => [...(e.dataTransfer?.types || [])].includes('Files');
  window.addEventListener('dragenter', (e) => { if (!hasFiles(e)) return; e.preventDefault(); depth += 1; overlay.hidden = false; });
  window.addEventListener('dragover', (e) => { if (hasFiles(e)) e.preventDefault(); });
  window.addEventListener('dragleave', (e) => { if (!hasFiles(e)) return; depth = Math.max(0, depth - 1); if (!depth) overlay.hidden = true; });
  window.addEventListener('drop', (e) => {
    if (!hasFiles(e)) return;
    e.preventDefault();
    depth = 0;
    overlay.hidden = true;
    const files = [...e.dataTransfer.files];
    if (!files.length) return;
    (state.chat ? chatComposer : homeComposer).add(files);
  });
}

// ---------------------------------------------------------------- theme, health, boot
function applyTheme(theme) {
  if (theme === 'light' || theme === 'dark') document.documentElement.dataset.theme = theme;
  else delete document.documentElement.dataset.theme;
}

async function checkHealth() {
  const el = $('#health');
  const label = $('span', el);
  try {
    const hdata = await api('GET', '/api/health');
    el.classList.toggle('ok', hdata.ollama === true);
    el.classList.toggle('bad', hdata.ollama === false);
    label.textContent = hdata.ollama === false ? 'Ollama is not running'
      : hdata.loaded?.length ? `${hdata.loaded[0]} ready` : hdata.ollama ? 'Local model ready' : `v${hdata.version}`;
    el.title = hdata.ollama === false ? 'Start Ollama, then reload. Answers need the local model.' : `Proposal Studio v${hdata.version}`;
  } catch {
    el.classList.add('bad');
    label.textContent = 'Studio server stopped';
  }
}

function boot() {
  applyTheme(store.get('ps.theme', ''));
  homeComposer = new Composer($('#home-composer-slot'), sendFromHome);
  chatComposer = new Composer($('#chat-composer-slot'), (msg) => send(msg));
  $('#home-composer-slot .composer textarea').placeholder = 'Drop an RFP or ask a question…';

  $('#new-chat').addEventListener('click', () => openNewProject({}));
  $('#open-settings').addEventListener('click', openSettings);
  $('#health').addEventListener('click', openModels);
  $('#modal-close').addEventListener('click', closeModal);
  $('#modal').addEventListener('click', (e) => { if (e.target.id === 'modal') closeModal(); });
  $$('.hint').forEach((b) => b.addEventListener('click', () => homeComposer.fill(b.dataset.fill)));
  $$('#actions .action[data-action]').forEach((b) => b.addEventListener('click', () => runAction(b.dataset.action)));
  $$('.tab').forEach((t) => t.addEventListener('click', () => showPanel(t.dataset.tab)));
  $('#toggle-panel').addEventListener('click', () => {
    const wide = window.matchMedia('(min-width: 861px)').matches;
    if (wide) {
      state.panelOpen = $('#panel').hidden;
      store.set('ps.panelOpen', state.panelOpen ? '1' : '0');
    } else {
      renderPanel.mobileOpen = $('#panel').hidden;
      state.panelOpen = true;
    }
    renderPanel();
  });
  $('#close-panel').addEventListener('click', () => {
    if (window.matchMedia('(min-width: 861px)').matches) {
      state.panelOpen = false;
      store.set('ps.panelOpen', '0');
    }
    renderPanel.mobileOpen = false;
    renderPanel();
  });
  $('#open-sidebar').addEventListener('click', () => $('#app').classList.add('sidebar-open'));
  $('#close-sidebar').addEventListener('click', closeSidebar);
  $('#scrim').addEventListener('click', closeSidebar);
  $('#theme-toggle').addEventListener('click', () => {
    const dark = document.documentElement.dataset.theme === 'dark'
      || (!document.documentElement.dataset.theme && window.matchMedia('(prefers-color-scheme: dark)').matches);
    const next = dark ? 'light' : 'dark';
    applyTheme(next);
    store.set('ps.theme', next);
  });
  window.addEventListener('popstate', route);
  setupDrop();
  setupLayout();
  checkHealth();
  setInterval(checkHealth, 30000);
  startApp();
}

async function startApp() {
  try {
    state.settings = await api('GET', '/api/settings');
  } catch {
    return; // 401 → login screen already shown
  }
  await refreshLists().catch((err) => toast(err.message));
  route();
}

// ---------------------------------------------------------------- modal
function openModal(title, body, { locked = false } = {}) {
  $('#modal-title').textContent = title;
  $('#modal-body').replaceChildren(body);
  $('#modal').classList.toggle('locked', locked);
  $('#modal').hidden = false;
}
function closeModal() {
  if ($('#modal').classList.contains('locked')) return;
  $('#modal').hidden = true;
  $('#modal-body').replaceChildren();
}

function showLogin() {
  openModal('Open Proposal Studio from its link', h('div', {},
    h('p', { class: 'lead' }, 'For your security this page only works when opened from the link that ',
      h('code', { text: 'studio ui' }), ' prints in the terminal (it starts with ',
      h('code', { text: 'http://127.0.0.1:…/?t=' }), ').'),
    h('p', { class: 'lead', text: 'Restart it with `studio ui` if you closed the terminal; your projects are safe.' })),
  { locked: true });
}

// ---------------------------------------------------------------- folders: browser, new project, settings
const sep = () => state.settings?.sep || '/';
const joinPath = (dir, name) => (dir.endsWith('/') || dir.endsWith('\\') ? dir + name : `${dir}${sep()}${name}`);
const safeFolderName = (name) => name.replace(/[<>:"/\\|?*\u0000-\u001f]+/g, '-').replace(/^[ .-]+|[ .]+$/g, '').slice(0, 80) || 'Project';
const parentOf = (path) => path.replace(/[\\/][^\\/]*$/, '') || path;

/** A folder browser: path box, sub-folder list, "New folder". Calls onChange(info) on every move. */
function folderBrowser(start, onChange) {
  const pathInput = h('input', { value: start, 'aria-label': 'Folder path', spellcheck: 'false' });
  const list = h('ul', { class: 'dir-list' });
  const err = h('div', { class: 'err' });
  let current = start;
  async function browse(path) {
    err.textContent = '';
    try {
      const data = await api('GET', `/api/fs?path=${encodeURIComponent(path)}`);
      current = data.path;
      pathInput.value = data.path;
      const items = [];
      if (data.parent) items.push(h('li', {}, h('button', { type: 'button', onclick: () => browse(data.parent) }, svg('<path d="M12 5l-5 5 5 5"/>'), '..')));
      for (const d of data.dirs) items.push(h('li', {}, h('button', { type: 'button', onclick: () => browse(joinPath(data.path, d)) }, svg(ICON.folder), d)));
      if (!data.dirs.length) items.push(h('li', { class: 'side-empty', text: 'No sub-folders' }));
      list.replaceChildren(...items);
      onChange(data);
    } catch (e) {
      err.textContent = e.status === 404 ? `${path} doesn't exist yet — it will be created.` : e.message;
      onChange({ path, missing: true });
    }
  }
  pathInput.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); browse(pathInput.value.trim()); } });
  const newFolder = h('button', {
    class: 'btn', type: 'button',
    onclick: async () => {
      const name = prompt('New folder name');
      if (!name) return;
      try { const r = await api('POST', '/api/fs/mkdir', { path: current, name }); browse(r.path); } catch (e) { err.textContent = e.message; }
    },
  }, 'New folder');
  const el = h('div', { class: 'browser' },
    h('div', { class: 'browser-bar' }, pathInput, h('button', { class: 'btn', type: 'button', onclick: () => browse(pathInput.value.trim()) }, 'Go'), newFolder),
    list, err);
  browse(start);
  return { el, path: () => current };
}

/** New project: a name, a folder (default: <Proposal Studio folder>/<name>) and explicit trust. */
async function openNewProject({ name = '', onCreated = null, restore = null } = {}) {
  if (!state.settings) state.settings = await api('GET', '/api/settings').catch(() => null);
  const home = state.settings?.home || '';
  const nameInput = h('input', { class: 'field', value: name, placeholder: 'e.g. Acme Health Plan 2026', 'aria-label': 'Project name' });
  const trustBox = h('input', { type: 'checkbox', id: 'trust-folder' });
  const err = h('div', { class: 'err' });
  const create = h('button', { class: 'btn primary', type: 'button', disabled: true }, 'Create project');
  let custom = null; // a folder picked in the browser; null = default location
  let existing = false;
  const where = h('div', { class: 'path' });
  const hint = h('div', { class: 'muted small' });
  const location = () => custom || joinPath(home, safeFolderName(nameInput.value.trim() || 'Untitled project'));
  const refresh = () => {
    where.textContent = location();
    hint.textContent = existing
      ? 'This folder already holds a Proposal Studio project — it will be added back with its chats.'
      : custom ? 'The project files go directly into this folder.' : 'A new folder is created here for this project.';
    create.textContent = existing ? 'Add project' : 'Create project';
    create.disabled = !trustBox.checked || (!existing && !nameInput.value.trim());
  };
  nameInput.addEventListener('input', refresh);
  trustBox.addEventListener('change', refresh);

  const browserSlot = h('div', {});
  const chooseBtn = h('button', {
    class: 'btn', type: 'button',
    onclick: () => {
      const start = custom || home;
      const fb = folderBrowser(start, (info) => {
        custom = info.path;
        existing = Boolean(info.project);
        refresh();
      });
      browserSlot.replaceChildren(fb.el, h('div', { class: 'row-btns', style: 'margin-top:8px' },
        h('button', { class: 'btn', type: 'button', onclick: () => { custom = null; existing = false; browserSlot.replaceChildren(); refresh(); } }, 'Use the default location')));
    },
  }, 'Choose another folder…');

  create.addEventListener('click', async () => {
    err.textContent = '';
    create.disabled = true;
    try {
      const res = await api('POST', '/api/projects', { name: nameInput.value.trim(), folder: custom || '', trust: true });
      restore = null;
      closeModal();
      history.pushState(null, '', `#/chat/${res.chat.id}`);
      await refreshLists();
      await openChat(res.chat.id);
      toast(`Project folder: ${shortPath(res.project.path)}`, 5000);
      if (onCreated) await onCreated(res.chat);
    } catch (e) {
      err.textContent = e.message;
      refresh();
    }
  });

  refresh();
  openModal('New project', h('div', {},
    h('label', { class: 'lbl', text: 'Project name' }), nameInput,
    h('label', { class: 'lbl', text: 'Project folder' }), where, hint,
    h('div', { class: 'row-btns', style: 'margin:8px 0 4px' }, chooseBtn),
    browserSlot,
    h('div', { class: 'trust-box', style: 'margin-top:14px' },
      h('label', { class: 'check', for: 'trust-folder', style: 'margin:0' }, trustBox,
        h('span', {}, h('strong', { text: 'I trust this folder. ' }),
          'Proposal Studio may read and write files only inside it: uploaded RFPs, chats, the search index, summaries and decks.'))),
    h('div', { class: 'row-btns', style: 'margin-top:14px' }, create,
      h('button', { class: 'btn', type: 'button', onclick: closeModal }, 'Cancel')),
    err));
  const obs = new MutationObserver(() => {
    if ($('#modal').hidden) { obs.disconnect(); if (restore) restore(); }
  });
  obs.observe($('#modal'), { attributes: true, attributeFilter: ['hidden'] });
  nameInput.focus();
  nameInput.select();
}

async function openSettings() {
  let st;
  try { st = state.settings = await api('GET', '/api/settings'); } catch (e) { toast(e.message); return; }
  const body = h('div', {});
  const row = (title, path, desc, ...actions) => h('div', { class: 'setting' },
    h('div', { class: 'lbl', text: title }), h('div', { class: 'path', text: path }), h('div', { class: 'muted small', text: desc }),
    h('div', { class: 'row-btns' }, ...actions));
  const render = () => body.replaceChildren(
    row('Proposal Studio folder', st.home,
      'New projects are created here by default. It also holds your shared library.',
      h('button', { class: 'btn', type: 'button', onclick: () => api('POST', '/api/home/reveal').catch((e) => toast(e.message)) }, svg(ICON.open), 'Open folder'),
      h('button', { class: 'btn', type: 'button', onclick: () => copyText(st.home, 'Path copied') }, 'Copy path'),
      h('button', { class: 'btn', type: 'button', onclick: changeHome }, 'Change…')),
    row('Library', st.library,
      'Past proposals (library/proposals), reference documents (library/reference) and curated content blocks (library/blocks). Shared by all projects.',
      h('button', { class: 'btn', type: 'button', onclick: () => api('POST', '/api/library/reveal').catch((e) => toast(e.message)) }, svg(ICON.open), 'Open folder')),
    row('Projects', `${state.projects.filter((p) => !p.missing).length} project folder(s)`,
      'Each project lives in the folder you chose when creating it — see the path under each project in the sidebar, or use ⋯ → Open folder.'),
    row('App settings', st.user_dir, 'Where Proposal Studio remembers these settings (no project files here).'));
  async function changeHome() {
    let picked = st.home;
    const trustBox = h('input', { type: 'checkbox', id: 'trust-home' });
    const err = h('div', { class: 'err' });
    const fb = folderBrowser(parentOf(st.home), (info) => { picked = info.path; });
    body.replaceChildren(h('p', { class: 'lead', text: 'Choose the new Proposal Studio folder. Existing projects stay where they are; the library list starts fresh in the new folder (move library/ yourself if you want it there).' }),
      fb.el,
      h('label', { class: 'check', for: 'trust-home', style: 'margin-top:12px' }, trustBox, 'I trust this folder'),
      h('div', { class: 'row-btns' },
        h('button', {
          class: 'btn primary', type: 'button',
          onclick: async () => {
            if (!trustBox.checked) { err.textContent = 'Tick “I trust this folder” first.'; return; }
            try {
              st = state.settings = await api('POST', '/api/settings/home', { path: picked, trust: true });
              await refreshLists();
              go('#/');
              render();
            } catch (e) { err.textContent = e.message; }
          },
        }, 'Use this folder'),
        h('button', { class: 'btn', type: 'button', onclick: render }, 'Back')),
      err);
  }
  render();
  openModal('Settings', body);
}

// ---------------------------------------------------------------- models
const gb = (bytes) => (bytes ? `${(bytes / 1024 ** 3).toFixed(1)} GB` : '—');

async function openModels() {
  const body = h('div', {}, h('div', { class: 'status' }, h('span', { class: 'dots' }, h('i'), h('i'), h('i')), 'Loading models…'));
  openModal('Models', body);
  let info;
  try { info = await api('GET', '/api/models'); } catch (e) { body.replaceChildren(h('div', { class: 'err', text: e.message })); return; }
  const head = h('div', { class: 'models-head' },
    h('span', {}, h('strong', { text: 'Ollama: ' }), info.ollama === false ? 'not running' : info.ollama ? 'running' : 'unknown'),
    h('span', {}, h('strong', { text: 'Memory: ' }), info.ram ? gb(info.ram) : 'unknown'),
    h('span', { text: 'One model runs at a time; “fits” leaves ~4 GB for everything else.' }));
  if (info.ollama === false) {
    body.replaceChildren(head, h('div', { class: 'empty', text: 'Start Ollama, then reopen this window.' }));
    return;
  }
  const pulled = info.models.filter((m) => !m.cloud);
  const roleLabels = { worker: 'Main model (answers, summaries, slides)', router: 'Fast model (routing)', embed: 'Embeddings (search index)' };
  const roles = h('div', { class: 'roles' }, Object.entries(roleLabels).flatMap(([role, labelText]) => {
    const select = h('select', { 'aria-label': labelText },
      pulled.map((m) => h('option', { value: m.name, selected: m.name === info.roles[role] ? true : null }, m.name)));
    if (!pulled.some((m) => m.name === info.roles[role])) select.prepend(h('option', { value: info.roles[role], selected: true }, `${info.roles[role]} (not pulled)`));
    select.addEventListener('change', async () => {
      try {
        await api('POST', '/api/models/role', { role, model: select.value });
        toast(`${labelText.split(' (')[0]} → ${select.value}`);
        checkHealth();
      } catch (e) { toast(e.message); select.value = info.roles[role]; }
    });
    return [h('label', { text: labelText }), select];
  }));
  const rows = info.models.map((m) => h('tr', {},
    h('td', { class: 'nm', text: m.name }),
    h('td', { text: [m.parameters, m.quantization].filter(Boolean).join(' · ') || '—' }),
    h('td', { text: gb(m.size) }),
    h('td', {},
      m.loaded ? h('span', { class: 'pill ok', text: 'loaded' }) : null,
      m.fits === true ? h('span', { class: 'pill', text: 'fits' }) : m.fits === false ? h('span', { class: 'pill bad', text: 'too big' }) : null,
      m.cloud ? h('span', { class: 'pill bad', text: 'cloud — blocked' }) : null,
      (m.roles || []).map((r) => h('span', { class: 'pill role', text: r })))));
  body.replaceChildren(head,
    h('h3', { class: 'side-label', style: 'padding:0 0 8px', text: 'Which model does what' }), roles,
    h('h3', { class: 'side-label', style: 'padding:0 0 8px', text: `Installed models (${info.models.length})` }),
    info.models.length
      ? h('div', { class: 'mtable-wrap' }, h('table', { class: 'mtable' },
        h('thead', {}, h('tr', {}, h('th', { text: 'Model' }), h('th', { text: 'Size class' }), h('th', { text: 'Disk' }), h('th', { text: 'Status' }))),
        h('tbody', {}, rows)))
      : h('div', { class: 'empty', text: 'No models yet. While online, run: ollama pull qwen3:8b' }),
    h('p', { class: 'lead', style: 'margin-top:14px', text: 'Coming next: suggestions for the best model per task.' }));
}

// ---------------------------------------------------------------- layout: collapsible sidebar, resizable panel
const isWide = () => window.matchMedia('(min-width: 861px)').matches;

function applySidebar() {
  const collapsed = store.get('ps.sideCollapsed', '0') === '1';
  $('#app').classList.toggle('side-collapsed', collapsed && isWide());
  const btn = $('#collapse-sidebar');
  btn.title = collapsed ? 'Expand sidebar (Ctrl+B)' : 'Collapse sidebar (Ctrl+B)';
  btn.setAttribute('aria-label', collapsed ? 'Expand sidebar' : 'Collapse sidebar');
}
function toggleSidebar() {
  if (!isWide()) { $('#app').classList.toggle('sidebar-open'); return; }
  store.set('ps.sideCollapsed', store.get('ps.sideCollapsed', '0') === '1' ? '0' : '1');
  applySidebar();
}

function setPanelWidth(px) {
  const max = Math.round(window.innerWidth * 0.75);
  const w = Math.max(320, Math.min(max, Math.round(px)));
  document.documentElement.style.setProperty('--panel-w', `${w}px`);
  return w;
}

function setupLayout() {
  applySidebar();
  const saved = Number(store.get('ps.panelW', '0'));
  if (saved) setPanelWidth(saved);
  $('#collapse-sidebar').addEventListener('click', toggleSidebar);
  window.addEventListener('resize', () => {
    applySidebar();
    const w = Number(store.get('ps.panelW', '0'));
    if (w) setPanelWidth(w);
    renderPanel();
  });

  const resizer = $('#panel-resizer');
  resizer.addEventListener('pointerdown', (e) => {
    e.preventDefault();
    resizer.setPointerCapture(e.pointerId);
    resizer.classList.add('dragging');
    document.body.classList.add('resizing');
    const move = (ev) => setPanelWidth(window.innerWidth - ev.clientX);
    const up = (ev) => {
      resizer.releasePointerCapture(ev.pointerId);
      resizer.classList.remove('dragging');
      document.body.classList.remove('resizing');
      resizer.removeEventListener('pointermove', move);
      resizer.removeEventListener('pointerup', up);
      store.set('ps.panelW', String(setPanelWidth(window.innerWidth - ev.clientX)));
    };
    resizer.addEventListener('pointermove', move);
    resizer.addEventListener('pointerup', up);
  });
  resizer.addEventListener('dblclick', () => {
    const now = $('#panel').getBoundingClientRect().width;
    const wide = Math.round(window.innerWidth * 0.6);
    store.set('ps.panelW', String(setPanelWidth(now < wide - 20 ? wide : 440)));
  });
  resizer.addEventListener('keydown', (e) => {
    const now = $('#panel').getBoundingClientRect().width;
    if (e.key === 'ArrowLeft') store.set('ps.panelW', String(setPanelWidth(now + 40)));
    if (e.key === 'ArrowRight') store.set('ps.panelW', String(setPanelWidth(now - 40)));
  });
  resizer.tabIndex = 0;

  window.addEventListener('keydown', (e) => {
    const mod = e.ctrlKey || e.metaKey;
    if (mod && e.key.toLowerCase() === 'b') { e.preventDefault(); toggleSidebar(); }
    if (mod && e.key.toLowerCase() === 'j' && state.chat) { e.preventDefault(); $('#toggle-panel').click(); }
    if (e.key === 'Escape' && !$('#modal').hidden) closeModal();
  });
}

boot();
