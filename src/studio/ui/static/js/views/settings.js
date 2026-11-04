// Settings: appearance, folders, models, about.
import { copyPath } from '../actions.js';
import { api, loadLists } from '../api.js';
import { bytes, h, icon, store } from '../dom.js';
import { pickFolder } from '../dialogs/folder-picker.js';
import { emit, shortPath, state } from '../state.js';
import { openDialog, toast } from '../ui/overlay.js';

export function applyTheme(theme = store.get('ps.theme', 'system')) {
  if (theme === 'light' || theme === 'dark') document.documentElement.dataset.theme = theme;
  else delete document.documentElement.dataset.theme;
}

export async function renderSettings(view, topbar, section = '') {
  topbar.replaceChildren(h('div', { class: 'title' }, h('span', { class: 'cur', text: 'Settings' })));
  document.title = 'Settings · Proposal Studio';
  state.settings = await api('GET', '/api/settings');
  const st = state.settings;
  const nav = [['general', 'General'], ['folders', 'Folders'], ['models', 'Models'], ['about', 'About']];

  const theme = store.get('ps.theme', 'system');
  const seg = h('div', { class: 'seg', role: 'radiogroup', 'aria-label': 'Theme' }, [['system', 'System'], ['light', 'Light'], ['dark', 'Dark']].map(([k, label]) => h('button', {
    class: theme === k ? 'on' : '', type: 'button', role: 'radio', 'aria-checked': String(theme === k),
    onclick: () => { store.set('ps.theme', k); applyTheme(k); renderSettings(view, topbar, 'general'); },
  }, label)));

  const row = (t, d, right, path) => h('div', { class: 's-row' },
    h('div', {}, h('div', { class: 't', text: t }), d ? h('div', { class: 'd', text: d }) : null),
    right ? h('div', { class: 'btns' }, right) : h('span'),
    path ? h('div', { class: 'path', text: shortPath(path), title: path }) : null);

  const models = h('div', {}, h('div', { class: 'status' }, h('span', { class: 'dots' }, h('i'), h('i'), h('i')), h('span', { class: 'muted', text: 'Loading models…' })));

  const page = h('div', { class: 'page' },
    h('div', { class: 'page-head' }, h('h1', { text: 'Settings' })),
    h('div', { class: 'settings' },
      h('nav', { class: 'settings-nav', 'aria-label': 'Settings sections' }, nav.map(([k, label]) => h('a', {
        href: `#/settings/${k}`, class: section === k ? 'active' : '',
        onclick: (e) => { e.preventDefault(); history.replaceState(null, '', `#/settings/${k}`); document.getElementById(`s-${k}`)?.scrollIntoView({ behavior: 'smooth' }); },
      }, label))),
      h('div', {},
        h('section', { class: 's-section', id: 's-general' },
          h('h2', { text: 'General' }), h('p', { text: 'How Proposal Studio looks on this computer.' }),
          row('Theme', 'Follow the system, or always light or dark.', seg),
          row('Keyboard shortcuts', 'Ctrl/⌘+B sidebar · Ctrl/⌘+J project panel · Enter send · Shift+Enter new line · Esc close')),
        h('section', { class: 's-section', id: 's-folders' },
          h('h2', { text: 'Folders' }), h('p', { text: 'Where your files live. Each project keeps everything in its own folder — see the path on the project page.' }),
          row('Proposal Studio folder', 'New projects are created here by default. It also holds the shared library and the list of your projects.', [
            h('button', { class: 'btn sm', type: 'button', onclick: () => api('POST', '/api/home/reveal').catch((e) => toast(e.message)) }, icon('open', 'sm'), 'Open'),
            h('button', { class: 'btn sm ghost', type: 'button', onclick: () => copyPath(st.home) }, icon('copy', 'sm'), 'Copy'),
            h('button', { class: 'btn sm', type: 'button', onclick: () => changeHome(view, topbar) }, 'Change…')], st.home),
          row('Library', 'Past proposals (library/proposals), reference documents (library/reference) and curated content blocks (library/blocks), shared by all projects.', [
            h('button', { class: 'btn sm', type: 'button', onclick: () => api('POST', '/api/library/reveal').catch((e) => toast(e.message)) }, icon('open', 'sm'), 'Open')], st.library),
          row('App settings', 'Where Proposal Studio remembers these settings. No project files are stored here.', null, st.user_dir)),
        h('section', { class: 's-section', id: 's-models' },
          h('h2', { text: 'Models' }), h('p', { text: 'Local models in Ollama. One runs at a time; “fits” leaves about 4 GB for everything else.' }),
          models),
        h('section', { class: 's-section', id: 's-about' },
          h('h2', { text: 'About' }),
          row('Proposal Studio', `Version ${state.health?.version || ''} · runs only on this computer (127.0.0.1). Nothing is sent to the internet.`)))));
  view.replaceChildren(page);
  if (section) requestAnimationFrame(() => document.getElementById(`s-${section}`)?.scrollIntoView());
  renderModels(models);
}

async function changeHome(view, topbar) {
  const picked = await pickFolder({ title: 'Choose the Proposal Studio folder', start: state.settings.home, confirm: 'Use' });
  if (!picked) return;
  const trust = h('input', { type: 'checkbox' });
  const ok = h('button', { class: 'btn primary', type: 'button', disabled: true }, 'Use this folder');
  trust.addEventListener('change', () => { ok.disabled = !trust.checked; });
  const d = openDialog({
    title: 'Use this as the Proposal Studio folder?', size: 'narrow',
    body: h('div', {}, h('div', { class: 'path', text: picked.path, style: { marginBottom: '12px' } }),
      h('p', { class: 'hint', style: { margin: '0 0 12px' }, text: 'Existing projects stay where they are, but the project list starts fresh here (add projects back from their folders). Move library/ yourself if you want it here.' }),
      h('label', { class: 'note trust check' }, trust, h('span', {}, h('strong', { text: 'I trust this folder.' }), ' Proposal Studio may read and write files inside it.'))),
    actions: [h('button', { class: 'btn', type: 'button', onclick: () => d.close() }, 'Cancel'), ok],
  });
  ok.addEventListener('click', async () => {
    try {
      state.settings = await api('POST', '/api/settings/home', { path: picked.path, trust: true });
      d.close();
      await loadLists();
      toast('Proposal Studio folder changed');
      renderSettings(view, topbar, 'folders');
    } catch (e) { d.setError(e.message); }
  });
}

async function renderModels(box) {
  let info;
  try { info = await api('GET', '/api/models'); } catch (e) { box.replaceChildren(h('div', { class: 'note danger' }, e.message)); return; }
  if (info.ollama === false) {
    box.replaceChildren(h('div', { class: 'note warn' }, icon('info', 'sm'), h('span', {}, h('strong', { text: 'Ollama is not running. ' }), 'Start it (scripts/start.* does), then reload this page.')));
    return;
  }
  const pulled = info.models.filter((m) => !m.cloud);
  const roles = [['worker', 'Main model', 'Answers, summaries and slides'], ['router', 'Fast model', 'Routing your messages'], ['embed', 'Embeddings', 'The search index']];
  const roleGrid = h('div', { class: 'role-grid' }, roles.flatMap(([role, label, what]) => {
    const select = h('select', { class: 'select', 'aria-label': label }, pulled.map((m) => h('option', { value: m.name, selected: m.name === info.roles[role] ? true : null }, m.name)));
    if (!pulled.some((m) => m.name === info.roles[role])) select.prepend(h('option', { value: info.roles[role], selected: true }, `${info.roles[role]} (not installed)`));
    select.addEventListener('change', async () => {
      try { await api('POST', '/api/models/role', { role, model: select.value }); toast(`${label}: ${select.value}`); emit('health-refresh'); } catch (e) { toast(e.message); select.value = info.roles[role]; }
    });
    return [h('div', {}, h('div', { style: { fontWeight: '600' }, text: label }), h('div', { class: 'hint', text: what })), select];
  }));
  const rows = info.models.map((m) => h('tr', {},
    h('td', { class: 'nm', text: m.name }),
    h('td', { text: [m.parameters, m.quantization].filter(Boolean).join(' · ') || '—' }),
    h('td', { text: bytes(m.size) }),
    h('td', {},
      m.loaded ? h('span', { class: 'badge ok', text: 'loaded' }) : null,
      m.fits === true ? h('span', { class: 'badge', text: 'fits' }) : m.fits === false ? h('span', { class: 'badge danger', text: 'too big' }) : null,
      m.cloud ? h('span', { class: 'badge danger', text: 'cloud — blocked' }) : null,
      (m.roles || []).map((r) => h('span', { class: 'badge accent', text: r })))));
  box.replaceChildren(
    h('div', { class: 'hint', style: { marginBottom: '14px' }, text: `Memory: ${info.ram ? bytes(info.ram) : 'unknown'} · Ollama: ${info.ollama ? 'running' : 'unknown'}` }),
    roleGrid,
    info.models.length
      ? h('div', { style: { overflowX: 'auto' } }, h('table', { class: 'mtable' },
        h('thead', {}, h('tr', {}, h('th', { text: 'Model' }), h('th', { text: 'Size' }), h('th', { text: 'Disk' }), h('th', { text: 'Status' }))),
        h('tbody', {}, rows)))
      : h('div', { class: 'empty', text: 'No models installed. While online, run: ollama pull qwen3:8b' }));
}

