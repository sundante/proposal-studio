// Sidebar: brand, New chat, Projects, recent chats, model status and Settings. Collapses to a rail.
import { chatMenu } from '../actions.js';
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

function route() { return location.hash || '#/'; }

export function renderSidebar() {
  const sb = $('#sidebar');
  const r = route();
  const link = (hash, iconName, label, extra = '') => h('a', {
    class: `sb-link${extra}${r === hash || (hash !== '#/' && r.startsWith(hash)) ? ' active' : ''}`,
    href: hash, title: label, onclick: (e) => { e.preventDefault(); closeDrawer(); go(hash); },
  }, iconName === 'plus' ? h('span', { class: 'plus' }, icon('plus')) : icon(iconName), h('span', { text: label }));

  const recents = state.recent.slice(0, 30);
  const health = state.health;
  const modelText = health?.ollama === false ? 'Ollama is not running'
    : health?.loaded?.length ? health.loaded[0] : health?.ollama ? 'Local model ready' : 'Checking model…';

  sb.replaceChildren(
    h('div', { class: 'sb-top' },
      h('a', { class: 'brand', href: '#/', onclick: (e) => { e.preventDefault(); closeDrawer(); go('#/'); } },
        h('img', { src: 'logo.svg', alt: '' }), h('span', { text: 'Proposal Studio' })),
      h('button', { class: 'icon-btn desktop-only', id: 'rail-toggle', type: 'button', onclick: toggleSidebar }, icon('sidebar')),
      h('button', { class: 'icon-btn mobile-only', type: 'button', 'aria-label': 'Close menu', onclick: closeDrawer }, icon('x'))),
    h('nav', { class: 'sb-nav', 'aria-label': 'Main' },
      link('#/', 'plus', 'New chat', ' primary'),
      link('#/projects', 'grid', 'Projects')),
    h('div', { class: 'sb-scroll' },
      h('div', { class: 'sb-section', text: 'Recents' }),
      recents.length
        ? h('ul', { class: 'sb-list' }, recents.map((c) => {
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
          }, h('span', { class: 't', text: c.title }), more);
        }))
        : h('div', { class: 'sb-empty', text: 'Your chats will appear here.' })),
    h('div', { class: 'sb-foot' },
      h('button', {
        class: `model-pill${health?.ollama === true ? ' ok' : health?.ollama === false ? ' bad' : ''}`, type: 'button',
        title: health?.ollama === false ? 'Start Ollama, then reload' : 'Models', onclick: () => { closeDrawer(); go('#/settings/models'); },
      }, h('i'), h('span', { class: 'ellipsis', text: modelText })),
      h('a', {
        class: `icon-btn${r.startsWith('#/settings') ? ' active' : ''}`, href: '#/settings', title: 'Settings', 'aria-label': 'Settings',
        onclick: (e) => { e.preventDefault(); closeDrawer(); go('#/settings'); },
      }, icon('sliders'))));
  applyRail();
}

on('lists', renderSidebar);
on('health', renderSidebar);
