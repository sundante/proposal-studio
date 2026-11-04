// Project page: title + description, chats, and the files / folder / progress column.
import { chatMenu, newChat, projectMenu } from '../actions.js';
import { api, enc, loadLists } from '../api.js';
import { h, icon, timeAgo } from '../dom.js';
import { filesCard, folderCard, progressCard } from '../panels/files.js';
import { go, state } from '../state.js';
import { promptDialog, toast } from '../ui/overlay.js';

export async function renderProject(view, topbar, id) {
  let project;
  try {
    project = await api('GET', `/api/projects/${enc(id)}`);
  } catch (e) {
    toast(e.message);
    go('#/projects');
    return;
  }
  state.project = project;
  state.chat = null;
  document.title = `${project.title} · Proposal Studio`;

  const more = h('button', { class: 'icon-btn', type: 'button', 'aria-haspopup': 'menu', title: 'Project options', 'aria-label': 'Project options' }, icon('more'));
  more.addEventListener('click', () => projectMenu(project, more));
  topbar.replaceChildren(h('div', { class: 'title' },
    h('a', { href: '#/projects', onclick: (e) => { e.preventDefault(); go('#/projects'); } }, 'Projects'),
    h('span', { class: 'sep', text: '/' }), h('span', { class: 'cur ellipsis', text: project.title })), more);

  const editDesc = async () => {
    const description = await promptDialog({ title: 'Project description', label: 'What is this bid about? (shown on the project card)', value: project.description || '', multiline: true, confirm: 'Save' });
    if (description === null) return;
    try {
      await api('PATCH', `/api/projects/${enc(id)}`, { description });
      await loadLists();
      renderProject(view, topbar, id);
    } catch (e) { toast(e.message); }
  };

  const addFiles = (files) => startChat(project.id, { text: '', files });
  const chats = project.chats.filter((c) => c.title !== 'New chat' || project.chats.length === 1);

  view.replaceChildren(h('div', { class: 'page' },
    h('div', { class: 'page-head' },
      h('div', { style: { flex: '1', minWidth: '0' } },
        h('h1', { text: project.title }),
        h('p', {
          class: `desc-edit${project.description ? '' : ' placeholder'}`, tabindex: '0', role: 'button', title: 'Edit description',
          onclick: editDesc, onkeydown: (e) => { if (e.key === 'Enter') editDesc(); },
        }, project.description || 'Add a short description…')),
      h('button', { class: 'btn primary lg', type: 'button', onclick: () => newChat(project.id) }, icon('plus', 'sm'), 'New chat')),
    h('div', { class: 'project-layout' },
      h('section', {},
        h('h3', { class: 'section-title', text: 'Chats' }),
        chats.length
          ? h('div', { class: 'chat-list' }, chats.map((c) => {
            const m = h('button', { class: 'icon-btn sm', type: 'button', 'aria-haspopup': 'menu', 'aria-label': `Options for ${c.title}`, title: 'More' }, icon('more', 'sm'));
            m.addEventListener('click', (e) => { e.stopPropagation(); chatMenu(c, m); });
            return h('div', {
              class: 'chat-row', tabindex: '0', role: 'link', onclick: () => go(`#/chat/${c.id}`),
              onkeydown: (e) => { if (e.key === 'Enter') go(`#/chat/${c.id}`); },
            }, icon('chat', 'sm'), h('span', { class: 't', text: c.title }), h('span', { class: 'when', text: timeAgo(c.updated) }), m);
          }))
          : h('div', { class: 'empty' }, h('h3', { text: 'No chats yet' }), 'Start a chat to ask about the RFP, analyse it or build slides.')),
      h('aside', {},
        filesCard(project, { onAdd: addFiles, onChanged: () => renderProject(view, topbar, id) }),
        folderCard(project),
        progressCard(project)))));
}

/** Open the project's newest chat (or a new one) and send a message there. */
export async function startChat(projectId, msg) {
  try {
    const p = await api('GET', `/api/projects/${enc(projectId)}`);
    const chat = p.chats[0] || await api('POST', `/api/projects/${enc(projectId)}/chats`);
    state.pendingSend = msg;
    go(`#/chat/${chat.id}`);
  } catch (e) { toast(e.message); }
}
