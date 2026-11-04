// Boot, routing, global shortcuts, drag-and-drop and the login screen.
import { api, loadLists } from './api.js';
import { $, h, icon } from './dom.js';
import { emit, on, state } from './state.js';
import { closeAllDialogs, openDialog, toast } from './ui/overlay.js';
import { hidePanel, renderChat, renderPanel, setupResizer, togglePanel } from './views/chat.js';
import { renderHome } from './views/home.js';
import { renderProject } from './views/project.js';
import { renderProjects } from './views/projects.js';
import { applyTheme, renderSettings } from './views/settings.js';
import { applyRail, closeDrawer, renderSidebar, toggleSidebar } from './views/sidebar.js';

const view = () => $('#view');
const topbar = () => $('#topbar');

async function route() {
  if (!showLogin.open) closeAllDialogs();
  closeDrawer();
  const hash = location.hash || '#/';
  let m;
  const leaveChat = () => { state.chat = null; hidePanel(); };
  try {
    if ((m = hash.match(/^#\/chat\/([0-9a-f]{12})$/))) {
      await renderChat(view(), topbar(), m[1]);
    } else if ((m = hash.match(/^#\/project\/([a-z0-9-]+)$/))) {
      leaveChat();
      await renderProject(view(), topbar(), m[1]);
    } else if (hash === '#/projects') {
      leaveChat(); state.project = null;
      renderProjects(view(), topbar());
    } else if ((m = hash.match(/^#\/settings(?:\/(\w+))?$/))) {
      leaveChat(); state.project = null;
      await renderSettings(view(), topbar(), m[1] || '');
    } else {
      leaveChat(); state.project = null;
      renderHome(view(), topbar());
    }
  } catch (e) {
    toast(e.message);
  }
  topbar().prepend(h('button', { class: 'icon-btn mobile-only', type: 'button', 'aria-label': 'Open menu', onclick: () => $('#app').classList.add('drawer') }, icon('menu')));
  view().scrollTop = 0;
  renderSidebar();
}

async function checkHealth() {
  try {
    state.health = await api('GET', '/api/health');
  } catch {
    state.health = { ollama: false };
  }
  emit('health');
}

function showLogin() {
  if (showLogin.open) return;
  showLogin.open = true;
  openDialog({
    title: 'Open Proposal Studio from its link',
    locked: true,
    size: 'narrow',
    body: h('div', {},
      h('p', { style: { margin: '0 0 10px', color: 'var(--text-2)' } }, 'For your security, this page only works when opened from the link that ', h('code', { class: 'mono', text: 'studio ui' }), ' prints in the terminal. It starts with ', h('code', { class: 'mono', text: 'http://127.0.0.1:…/?t=' }), '.'),
      h('p', { class: 'hint', style: { margin: 0 } }, 'Closed the terminal? Start it again with scripts/start (your projects are safe).')),
  });
}

function setupDrop() {
  let depth = 0;
  const overlay = h('div', { class: 'drop', hidden: true }, h('div', {}, icon('upload'), 'Drop files to add them'));
  document.body.append(overlay);
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
    if (state.activeComposer && document.body.contains(state.activeComposer.el)) state.activeComposer.add(files);
    else toast('Open a chat or the home screen to add files.');
  });
}

function setupKeys() {
  window.addEventListener('keydown', (e) => {
    const mod = e.ctrlKey || e.metaKey;
    if (mod && e.key.toLowerCase() === 'b') { e.preventDefault(); toggleSidebar(); }
    if (mod && e.key.toLowerCase() === 'j' && state.chat) { e.preventDefault(); togglePanel(); }
  });
  window.addEventListener('resize', () => { applyRail(); if (state.chat) renderPanel(); });
}

async function boot() {
  applyTheme();
  setupResizer();
  setupDrop();
  setupKeys();
  on('route', route);
  on('login', showLogin);
  on('health-refresh', checkHealth);
  window.addEventListener('popstate', route);
  $('#scrim').addEventListener('click', closeDrawer);
  renderSidebar();
  checkHealth();
  setInterval(checkHealth, 30000);
  try {
    state.settings = await api('GET', '/api/settings');
    await loadLists();
  } catch (e) {
    if (e.status !== 401) toast(e.message);
    return;
  }
  route();
}

boot();
