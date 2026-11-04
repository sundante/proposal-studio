// Search (Ctrl/⌘+K): projects and chats, with snippets; keyboard navigation.
import { api, enc } from '../api.js';
import { h, icon, timeAgo } from '../dom.js';
import { go, state } from '../state.js';
import { openDialog } from '../ui/overlay.js';

let open = null;

export function openSearch() {
  if (open) return;
  const input = h('input', { class: 'search-input', placeholder: 'Search chats and projects…', 'aria-label': 'Search', autofocus: true });
  const results = h('div', { class: 'search-results', role: 'listbox' });
  let items = [];
  let active = 0;
  let timer = null;
  let seq = 0;

  const choose = (it) => { d.close(); go(it.hash); };
  const paint = () => {
    results.querySelectorAll('.result').forEach((el, i) => el.classList.toggle('active', i === active));
    results.querySelector('.result.active')?.scrollIntoView({ block: 'nearest' });
  };
  const render = (q, data) => {
    items = [];
    const groups = [];
    if (!q) {
      const recent = state.recent.slice(0, 8).map((c) => ({ hash: `#/chat/${c.id}`, title: c.title, sub: state.projects.find((p) => p.id === c.project)?.title || '', icon: 'chat', when: c.updated }));
      if (recent.length) groups.push(['Recent chats', recent]);
    } else {
      const projects = data.projects.map((p) => ({ hash: `#/project/${p.id}`, title: p.title, sub: p.path, icon: 'folder' }));
      const chats = data.chats.map((c) => ({ hash: `#/chat/${c.id}`, title: c.title, sub: c.snippet || c.project_title, icon: 'chat', when: c.updated }));
      if (projects.length) groups.push(['Projects', projects]);
      if (chats.length) groups.push(['Chats', chats]);
    }
    const nodes = [];
    for (const [label, list] of groups) {
      nodes.push(h('div', { class: 'menu-label', text: label }));
      for (const it of list) {
        const i = items.length;
        items.push(it);
        nodes.push(h('button', {
          class: 'result', type: 'button', role: 'option',
          onclick: () => choose(it), onmousemove: () => { if (active !== i) { active = i; paint(); } },
        }, icon(it.icon, 'sm'), h('span', { class: 'two' }, h('span', { class: 'ellipsis t', text: it.title }), it.sub ? h('span', { class: 'desc', text: it.sub }) : null),
        it.when ? h('span', { class: 'when', text: timeAgo(it.when) }) : null));
      }
    }
    if (!nodes.length) nodes.push(h('div', { class: 'pop-empty', text: q ? `Nothing matches “${q}”.` : 'No chats yet.' }));
    results.replaceChildren(...nodes);
    active = 0;
    paint();
  };
  const run = async () => {
    const q = input.value.trim();
    const mine = ++seq;
    if (!q) { render('', null); return; }
    try {
      const data = await api('GET', `/api/search?q=${enc(q)}`);
      if (mine === seq) render(q, data);
    } catch { /* keep the last results */ }
  };
  input.addEventListener('input', () => { clearTimeout(timer); timer = setTimeout(run, 140); });
  input.addEventListener('keydown', (e) => {
    if (e.key === 'ArrowDown') { e.preventDefault(); active = Math.min(items.length - 1, active + 1); paint(); }
    if (e.key === 'ArrowUp') { e.preventDefault(); active = Math.max(0, active - 1); paint(); }
    if (e.key === 'Enter' && items[active]) { e.preventDefault(); choose(items[active]); }
  });

  const d = openDialog({
    title: 'Search', size: 'search-dlg',
    body: h('div', {}, h('div', { class: 'search-box' }, icon('search'), input), results),
    onClose: () => { open = null; },
  });
  open = d;
  render('', null);
}
