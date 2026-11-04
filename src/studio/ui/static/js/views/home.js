// Home: greeting + composer. Messages go to a chosen project, or a new one is created first.
import { api, enc, loadLists } from '../api.js';
import { greeting, h, icon, stem } from '../dom.js';
import { openNewProject } from '../dialogs/new-project.js';
import { go, state } from '../state.js';
import { Composer } from '../ui/composer.js';
import { popMenu, toast } from '../ui/overlay.js';

let target = null; // project id the next message goes to (null = create a new project)

export function renderHome(view, topbar) {
  topbar.replaceChildren(h('div', { class: 'title' }));
  document.title = 'Proposal Studio';
  if (target && !state.projects.some((p) => p.id === target && !p.missing)) target = null;

  const chip = h('button', { class: 'chip project-chip', type: 'button', 'aria-haspopup': 'menu' });
  const syncChip = () => {
    const p = state.projects.find((x) => x.id === target);
    chip.replaceChildren(icon('folder', 'sm'), h('span', { class: 'ellipsis', text: p ? p.title : 'New project' }), icon('chevronDown', 'xs'));
    chip.title = p ? `Send to “${p.title}”` : 'Your message starts a new project';
  };
  chip.addEventListener('click', () => {
    const live = state.projects.filter((p) => !p.missing);
    popMenu(chip, [
      { label: 'Start a new project', icon: 'folderPlus', checked: !target, run: () => { target = null; syncChip(); } },
      ...(live.length ? ['-', { heading: 'Add to a project' }] : []),
      ...live.slice(0, 12).map((p) => ({ label: p.title, icon: 'folder', checked: target === p.id, run: () => { target = p.id; syncChip(); } })),
    ]);
  });
  syncChip();

  const composer = new Composer({
    placeholder: 'Drop an RFP or ask a question…',
    extras: [chip],
    onSubmit: (msg) => send(msg, composer),
  });

  const quick = [
    ['When is the proposal due?', 'doc'],
    ['What are the mandatory requirements?', 'check'],
    ['Which compliance frameworks are mentioned?', 'shield'],
  ];
  view.replaceChildren(h('section', { class: 'home' },
    h('h1', { class: 'greeting' }, h('img', { src: 'logo.svg', alt: '' }), `${greeting()}`),
    h('div', { class: 'composer-wrap' }, composer.el),
    h('div', { class: 'quick' }, quick.map(([text, ic]) => h('button', { class: 'chip', type: 'button', onclick: () => composer.fill(text) }, icon(ic, 'sm'), text)),
      h('button', { class: 'chip', type: 'button', onclick: () => openNewProject({}) }, icon('folderPlus', 'sm'), 'New project'))));
  composer.focus();
}

async function send(msg, composer) {
  if (target) {
    try {
      const chat = await api('POST', `/api/projects/${enc(target)}/chats`);
      await loadLists();
      state.pendingSend = msg;
      go(`#/chat/${chat.id}`);
    } catch (e) { toast(e.message); composer.restore(msg); }
    return;
  }
  const name = msg.files.length ? stem(msg.files[0].name) : msg.text.split(/\s+/).slice(0, 6).join(' ');
  openNewProject({
    name,
    onCreated: (res) => { state.pendingSend = msg; go(`#/chat/${res.chat.id}`); },
    onCancel: () => composer.restore(msg),
  });
}
