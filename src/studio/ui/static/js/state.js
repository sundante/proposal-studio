// Shared app state and tiny event bus.
import { store } from './dom.js';

export const state = {
  settings: null, // { home, library, user_dir, user_home, sep }
  projects: [], // sidebar / grid summaries
  recent: [], // recent chats across projects
  project: null, // detail of the open project
  chat: null, // open chat (with messages)
  streaming: null, // AbortController while a reply streams
  health: null,
  panelTab: store.get('ps.panelTab', 'files'),
  panelOpen: store.get('ps.panelOpen', '1') === '1',
  activeComposer: null, // receives dropped files
};

const bus = new EventTarget();
/** Notify listeners: 'lists' (projects/recents changed), 'route', 'busy'. */
export const emit = (name, detail) => bus.dispatchEvent(new CustomEvent(name, { detail }));
export const on = (name, fn) => bus.addEventListener(name, (e) => fn(e.detail));

/** Navigate to a hash route (pushState, then re-render). */
export function go(hash) {
  if (location.hash !== hash) history.pushState(null, '', hash);
  emit('route');
}

/** ``~/Documents/Proposal Studio`` style paths. */
export function shortPath(p) {
  const home = state.settings?.user_home;
  return home && p && p.startsWith(home) ? `~${p.slice(home.length)}` : p || '';
}

/** Path split into folder names (works for / and \\ paths). */
export const pathParts = (p) => (p || '').split(/[\\/]/).filter(Boolean);

/** ``…/Proposal Studio/Acme`` — the last two folders. */
export function compactPath(p) {
  const parts = pathParts(shortPath(p));
  return parts.length > 2 ? `…/${parts.slice(-2).join('/')}` : shortPath(p);
}

export function joinPath(dir, name) {
  const sep = state.settings?.sep || '/';
  return dir.endsWith('/') || dir.endsWith('\\') ? dir + name : `${dir}${sep}${name}`;
}

export const safeFolderName = (name) => name.replace(/[<>:"/\\|?*\u0000-\u001f]+/g, '-')
  .replace(/^[ .-]+|[ .]+$/g, '').slice(0, 80) || 'Project';
