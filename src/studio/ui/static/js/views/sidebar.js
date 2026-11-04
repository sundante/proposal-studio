// Sidebar: New chat, Search, Projects, Outputs, Templates, Customize; Pinned + Recents; profile.
import { chatMenu } from '../actions.js';
import { openSearch } from '../dialogs/search.js';
import { $, h, icon, store } from '../dom.js';
import { go, on, state } from '../state.js';

export function isWide() { return window.matchMedia('(min-width: 901px)').matches; }

export function applyRail() {
  const rail = store.get('ps.rail', '0') === '1' && isWide();
  $('#app').classList.toggle('rail', rail);
  const btn = $('#rail-toggle');
  if (btn) {
    btn.title = rail ? 'Expand sidebar (Ctrl+B)' : 'Collapse sidebar (Ctrl+B)';
    btn.setAttribute('aria-label', rail ? 'Expand sidebar' : 'Collapse sidebar');
  }
}

export function toggleSidebar() {
  if (!isWide()) { $('#app').classList.toggle('drawer'); return; }
  store.set('ps.rail', store.get('ps.rail', '0') === '1' ? '0' : '1');
  applyRail();
}

export function closeDrawer() { $('#app').classList.remove('drawer'); }

const isMac = /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent);
export const modKey = isMac ? '⌘' : 'Ctrl+';

function chatRow(c) {
  const project = state.projects.find((p) => p.id === c.project);
  const more = h('button', {
    class: 'icon-btn sm more', type: 'button', 'aria-label': `Options for ${c.title}`, 'aria-haspopup': 'menu', title: 'More',
    onclick: (e) => { e.stopPropagation(); chatMenu(c, more); },
  }, icon('more', 'sm'));
  return h('li', {
    class: `sb-item${state.chat?.id === c.id ? ' active' : ''}`, tabindex: '0', role: 'link',
    title: project ? `${c.title} — ${project.title}` : c.title,
    onclick: () => { closeDrawer(); go(`#/chat/${c.id}`); },
    onkeydown: (e) => { if (e.key === 'Enter') go(`#/chat/${c.id}`); },
  }, h('span', { class: 't', text: c.title }),
  c.has_files ? h('span', { class: 'mark', title: 'Has files or outputs' }, icon('clipMark', 'xs')) : null,
  more);
}

function section(key, label, rows, emptyText) {
  const open = store.get(`ps.sec.${key}`, '1') === '1';
  const head = h('button', {
    class: 'sb-section', type: 'button', 'aria-expanded': String(open),
    onclick: () => { store.set(`ps.sec.${key}`, open ? '0' : '1'); renderSidebar(); },
  }, h('span', { text: label }), icon(open ? 'chevronDown' : 'chevron', 'xs'));
  if (!open) return [head];
  return [head, rows.length ? h('ul', { class: 'sb-list' }, rows) : h('div', { class: 'sb-empty', text: emptyText })];
}

export function renderSidebar() {
  const sb = $('#sidebar');
  const r = location.hash || '#/';
  const link = (hash, iconName, label, extra = '', hint = '') => h('a', {
    class: `sb-link${extra}${r === hash || (hash !== '#/' && r.startsWith(hash)) ? ' active' : ''}`,
    href: hash, title: hint || label, onclick: (e) => { e.preventDefault(); closeDrawer(); go(hash); },
  }, iconName === 'plus' ? h('span', { class: 'plus' }, icon('plus')) : icon(iconName), h('span', { text: label }));

  const pinned = state.recent.filter((c) => c.pinned);
  const recents = state.recent.filter((c) => !c.pinned).slice(0, 30);
  const health = state.health;
  const modelText = health?.ollama === false ? 'Ollama is not running'
    : health?.loaded?.length ? `${health.loaded[0]} loaded` : health?.ollama ? 'Local model ready' : 'Checking model…';
  const name = state.settings?.name || '';

  sb.replaceChildren(
    h('div', { class: 'sb-top' },
      h('a', { class: 'brand', href: '#/', onclick: (e) => { e.preventDefault(); closeDrawer(); go('#/'); } },
        h('img', { src: 'logo.svg', alt: '' }), h('span', { text: 'Proposal Studio' })),
      h('button', { class: 'icon-btn desktop-only', id: 'rail-toggle', type: 'button', onclick: toggleSidebar }, icon('sidebar')),
      h('button', { class: 'icon-btn mobile-only', type: 'button', 'aria-label': 'Close menu', onclick: closeDrawer }, icon('x'))),
    h('nav', { class: 'sb-nav', 'aria-label': 'Main' },
      link('#/', 'plus', 'New chat', ' primary'),
      h('button', { class: 'sb-link', type: 'button', title: `Search (${modKey}K)`, onclick: () => { closeDrawer(); openSearch(); } },
        icon('search'), h('span', { text: 'Search' }), h('span', { class: 'kbd sb-kbd', text: `${modKey}K` })),
      link('#/projects', 'grid', 'Projects'),
      link('#/outputs', 'slides', 'Outputs', '', 'Decks, summaries, matrices and research reports'),
      link('#/templates', 'palette', 'Templates', '', 'Your PowerPoint templates'),
      link('#/customize', 'sliders', 'Customize', '', 'Storyline, content blocks and routing')),
    h('div', { class: 'sb-scroll' },
      ...(pinned.length ? section('pinned', 'Pinned', pinned.map(chatRow), '') : []),
      ...section('recents', 'Recents', recents.map(chatRow), 'Your chats will appear here.')),
    h('div', { class: 'sb-foot' },
      h('button', {
        class: 'profile', type: 'button', title: name ? 'Profile and settings' : 'Set your name in Settings',
        onclick: () => { closeDrawer(); go('#/settings/profile'); },
      }, h('span', { class: 'avatar', text: (name || '?').slice(0, 1).toUpperCase() }),
      h('span', { class: 'who' }, h('span', { class: 'ellipsis', text: name || 'Set your name' }),
        h('span', { class: `model-line${health?.ollama === true ? ' ok' : health?.ollama === false ? ' bad' : ''}` }, h('i'), h('span', { class: 'ellipsis', text: modelText })))),
      h('a', {
        class: `icon-btn${r.startsWith('#/settings') ? ' active' : ''}`, href: '#/settings', title: 'Settings', 'aria-label': 'Settings',
        onclick: (e) => { e.preventDefault(); closeDrawer(); go('#/settings'); },
      }, icon('cog'))));
  applyRail();
}

on('lists', renderSidebar);
on('health', renderSidebar);
