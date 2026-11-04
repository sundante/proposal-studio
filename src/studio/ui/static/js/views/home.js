// Home: greeting, composer (mode + model chips), project-or-folder picker, temporary chat.
import { api, enc, loadLists } from '../api.js';
import { greeting, h, icon, stem } from '../dom.js';
import { pickFolder } from '../dialogs/folder-picker.js';
import { openNewProject } from '../dialogs/new-project.js';
import { compactPath, go, state } from '../state.js';
import { Composer } from '../ui/composer.js';
import { closeMenu, popPanel, toast } from '../ui/overlay.js';
import { defaultPrefs, modeOf, prefChips, rememberDefaults } from '../ui/prefs.js';

let target = null; // project id the next message goes to (null = start a new project)
let temporary = false;

export function renderHome(view, topbar) {
  document.title = 'Proposal Studio';
  if (target && !state.projects.some((p) => p.id === target && !p.missing)) target = null;
  const prefs = defaultPrefs();

  const ghost = h('button', {
    class: `icon-btn${temporary ? ' active' : ''}`, type: 'button', 'aria-pressed': String(temporary),
    title: temporary ? 'Temporary chat is on — it won’t be saved' : 'Start a temporary chat (not saved)',
    onclick: () => { temporary = !temporary; renderHome(view, topbar); },
  }, icon('ghost'));
  topbar.replaceChildren(h('div', { class: 'title' }), ghost);

  // project-or-folder picker
  const pick = h('button', { class: 'chip project-chip', type: 'button', 'aria-haspopup': 'dialog' });
  const syncPick = () => {
    const p = state.projects.find((x) => x.id === target);
    pick.replaceChildren(icon(p ? 'folder' : 'folderPlus', 'sm'), h('span', { class: 'ellipsis', text: p ? p.title : 'Project or folder' }), icon('chevronDown', 'xs'));
    pick.title = p ? `Messages go to “${p.title}” (${compactPath(p.path)})` : 'Choose a project, or your message starts a new one';
  };
  pick.addEventListener('click', () => openProjectPicker(pick, (id) => { target = id; syncPick(); }));
  syncPick();

  const chips = prefChips(prefs, (p) => { rememberDefaults(p); composer.setPlaceholder(modeOf(p.mode).placeholder); });
  const composer = new Composer({
    placeholder: modeOf(prefs.mode).placeholder,
    right: [chips.mode, chips.model],
    onSubmit: (msg) => send({ ...msg, prefs: { ...prefs } }, composer),
  });

  const name = state.settings?.name?.split(' ')[0];
  const quick = [
    ['When is the proposal due?', 'doc'],
    ['What are the mandatory requirements?', 'check'],
    ['Which compliance frameworks are mentioned?', 'shield'],
  ];
  view.replaceChildren(h('section', { class: 'home' },
    h('h1', { class: 'greeting' }, h('img', { src: 'logo.svg', alt: '' }), name ? `${greeting()}, ${name}` : greeting()),
    temporary ? h('div', { class: 'note temp-note' }, icon('ghost', 'sm'), h('span', {}, h('strong', { text: 'Temporary chat. ' }), 'It isn’t saved, listed or searchable, and is deleted when you leave it. Pick a project for its files.')) : null,
    h('div', { class: 'composer-wrap' }, composer.el),
    h('div', { class: 'below-composer' }, pick),
    h('div', { class: 'quick' }, quick.map(([text, ic]) => h('button', { class: 'chip', type: 'button', onclick: () => composer.fill(text) }, icon(ic, 'sm'), text)))));
  composer.focus();
}

/** Searchable project list with "Create …", New project and Add folder. onPick(id|null). */
export function openProjectPicker(anchor, onPick) {
  const input = h('input', { placeholder: 'Search or create a project', 'aria-label': 'Search or create a project' });
  const list = h('div', { class: 'pop-list', role: 'listbox' });
  const item = (iconName, label, run, extra = '') => h('button', { class: `menu-item${extra}`, type: 'button', role: 'option', onclick: () => { closeMenu(); run(); } },
    icon(iconName, 'sm'), h('span', { class: 'ellipsis', text: label }));
  const draw = () => {
    const q = input.value.trim().toLowerCase();
    const live = state.projects.filter((p) => !p.missing && (!q || p.title.toLowerCase().includes(q)));
    const rows = live.slice(0, 20).map((p) => item('folder', p.title, () => onPick(p.id)));
    if (!rows.length && !q) rows.push(h('div', { class: 'pop-empty', text: 'No projects yet.' }));
    const exact = state.projects.some((p) => p.title.toLowerCase() === q);
    list.replaceChildren(...rows,
      h('div', { class: 'menu-sep' }),
      q && !exact ? item('plus', `Create “${input.value.trim()}”`, () => openNewProject({ name: input.value.trim(), onCreated: (r) => { onPick(r.project.id); } })) : item('plus', 'New project', () => openNewProject({ onCreated: (r) => onPick(r.project.id) })),
      item('folderPlus', 'Add folder…', () => addFolder(onPick)),
      item('x', 'No project (start a new one when I send)', () => onPick(null)));
  };
  input.addEventListener('input', draw);
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') { e.preventDefault(); list.querySelector('.menu-item')?.click(); }
    if (e.key === 'ArrowDown') { e.preventDefault(); list.querySelector('.menu-item')?.focus(); }
  });
  draw();
  popPanel(anchor, h('div', {}, h('div', { class: 'pop-search' }, icon('search', 'sm'), input), list), { width: 320 });
  setTimeout(() => input.focus(), 0);
}

/** "Add folder": choose a folder; an existing project is added back, otherwise create one there. */
async function addFolder(onPick) {
  const picked = await pickFolder({ title: 'Add a folder', confirm: 'Add' });
  if (!picked) return;
  if (picked.project) {
    try {
      const res = await api('POST', '/api/projects', { name: '', folder: picked.path, trust: true });
      await loadLists();
      toast(`Added “${res.project.title}”`);
      onPick(res.project.id);
    } catch (e) { toast(e.message); }
    return;
  }
  const name = picked.path.split(/[\\/]/).filter(Boolean).pop() || 'Project';
  openNewProject({ name, onCreated: (r) => onPick(r.project.id) });
}

async function send(msg, composer) {
  const open = async (projectId) => {
    const chat = await api('POST', `/api/projects/${enc(projectId)}/chats`, { temporary });
    if (!temporary) await loadLists();
    state.pendingSend = msg;
    go(`#/chat/${chat.id}`);
  };
  if (target) {
    try { await open(target); } catch (e) { toast(e.message); composer.restore(msg); }
    return;
  }
  if (temporary) {
    toast('Choose a project for the temporary chat (it uses that project’s files).');
    composer.restore(msg);
    return;
  }
  const name = msg.files.length ? stem(msg.files[0].name) : msg.text.split(/\s+/).slice(0, 6).join(' ');
  openNewProject({
    name,
    onCreated: (res) => { state.pendingSend = msg; go(`#/chat/${res.chat.id}`); },
    onCancel: () => composer.restore(msg),
  });
}
