// Projects: a searchable grid of project cards.
import { projectMenu } from '../actions.js';
import { h, icon, timeAgo } from '../dom.js';
import { openNewProject } from '../dialogs/new-project.js';
import { compactPath, go, state } from '../state.js';

let query = '';

export function renderProjects(view, topbar) {
  topbar.replaceChildren(h('div', { class: 'title' }));
  document.title = 'Projects · Proposal Studio';
  const grid = h('div', { class: 'grid' });
  const search = h('input', { class: 'input', type: 'search', placeholder: 'Search projects…', value: query, 'aria-label': 'Search projects' });

  const draw = () => {
    const q = query.toLowerCase();
    const items = state.projects.filter((p) => !q || p.title.toLowerCase().includes(q) || (p.description || '').toLowerCase().includes(q));
    if (!state.projects.length) {
      grid.replaceChildren(h('div', { class: 'empty', style: { gridColumn: '1 / -1' } },
        h('h3', { text: 'No projects yet' }),
        'A project is one bid. Its RFP files, chats, summary and slides live in a folder you choose.',
        h('br'),
        h('button', { class: 'btn primary', type: 'button', onclick: () => openNewProject({}) }, icon('plus', 'sm'), 'New project')));
      return;
    }
    if (!items.length) { grid.replaceChildren(h('div', { class: 'empty', style: { gridColumn: '1 / -1' } }, `No projects match “${query}”.`)); return; }
    grid.replaceChildren(...items.map(card));
  };
  search.addEventListener('input', () => { query = search.value; draw(); });

  view.replaceChildren(h('div', { class: 'page' },
    h('div', { class: 'page-head' },
      h('div', { style: { flex: '1' } }, h('h1', { text: 'Projects' }), h('p', { class: 'sub', text: 'One project per bid, each in its own folder on this computer.' })),
      h('button', { class: 'btn primary lg', type: 'button', onclick: () => openNewProject({}) }, icon('plus', 'sm'), 'New project')),
    h('div', { class: 'toolbar' }, h('div', { class: 'search' }, icon('search', 'sm'), search)),
    grid));
  draw();
}

function card(p) {
  const more = h('button', {
    class: 'icon-btn sm more', type: 'button', 'aria-haspopup': 'menu', 'aria-label': `Options for ${p.title}`, title: 'More',
    onclick: (e) => { e.stopPropagation(); projectMenu(p, more); },
  }, icon('more', 'sm'));
  const open = () => { if (!p.missing) go(`#/project/${p.id}`); else projectMenu(p, more); };
  return h('article', {
    class: `pcard${p.missing ? ' missing' : ''}`, tabindex: '0', role: 'link', title: p.path,
    onclick: open, onkeydown: (e) => { if (e.key === 'Enter') open(); },
  },
  more,
  h('h3', { text: p.title }),
  p.missing
    ? h('div', { class: 'desc' }, h('span', { class: 'badge danger', text: 'Folder missing' }), ' It was moved or deleted outside the app.')
    : p.description ? h('div', { class: 'desc', text: p.description }) : null,
  h('div', { class: 'foot' },
    icon('folder', 'xs'), h('span', { class: 'loc', text: compactPath(p.path) }),
    p.missing ? null : h('span', { text: `${p.files || 0} file${p.files === 1 ? '' : 's'} · ${timeAgo(p.updated)}` })));
}
