// DOM helpers, icons and small utilities. No dependencies.

export const $ = (sel, el = document) => el.querySelector(sel);
export const $$ = (sel, el = document) => [...el.querySelectorAll(sel)];

/** Build an element: h('div', { class: 'x', onclick }, child, …). `html` only for md()/esc() output. */
export function h(tag, props = {}, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(props || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === 'class') el.className = v;
    else if (k === 'text') el.textContent = v;
    else if (k === 'html') el.innerHTML = v;
    else if (k === 'style' && typeof v === 'object') Object.assign(el.style, v);
    else if (k.startsWith('on')) el.addEventListener(k.slice(2), v);
    else el.setAttribute(k, v === true ? '' : v);
  }
  for (const kid of kids.flat(Infinity)) {
    if (kid === null || kid === undefined || kid === false) continue;
    el.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
  }
  return el;
}

const P = {
  plus: '<path d="M10 4v12M4 10h12"/>',
  chat: '<path d="M4 4.5h12a1 1 0 011 1v7a1 1 0 01-1 1H9l-4 3v-3H4a1 1 0 01-1-1v-7a1 1 0 011-1z"/>',
  folder: '<path d="M2.5 5.5a1 1 0 011-1h4l2 2h7a1 1 0 011 1v8a1 1 0 01-1 1h-13a1 1 0 01-1-1z"/>',
  folderPlus: '<path d="M2.5 5.5a1 1 0 011-1h4l2 2h7a1 1 0 011 1v8a1 1 0 01-1 1h-13a1 1 0 01-1-1z"/><path d="M10 9.5v4M8 11.5h4"/>',
  grid: '<rect x="3" y="3" width="6" height="6" rx="1.5"/><rect x="11" y="3" width="6" height="6" rx="1.5"/><rect x="3" y="11" width="6" height="6" rx="1.5"/><rect x="11" y="11" width="6" height="6" rx="1.5"/>',
  x: '<path d="M5 5l10 10M15 5L5 15"/>',
  more: '<circle cx="5" cy="10" r="1.1"/><circle cx="10" cy="10" r="1.1"/><circle cx="15" cy="10" r="1.1"/>',
  copy: '<rect x="6.5" y="6.5" width="10" height="10" rx="2"/><path d="M13.5 6.5V4.5a1 1 0 00-1-1h-8a1 1 0 00-1 1v8a1 1 0 001 1h2"/>',
  check: '<path d="M4 10.5l4 4 8-9"/>',
  up: '<path d="M10 16V4M5 9l5-5 5 5"/>',
  stop: '<rect x="5.5" y="5.5" width="9" height="9" rx="1.5" fill="currentColor" stroke="none"/>',
  download: '<path d="M10 3v10M6 9l4 4 4-4M4 16.5h12"/>',
  trash: '<path d="M4 6h12M8 6V4.5h4V6M6 6l.8 10h6.4L14 6"/>',
  open: '<path d="M11 3.5h5.5V9M16.5 3.5L9 11M14 12v3.5a1 1 0 01-1 1H4.5a1 1 0 01-1-1V7a1 1 0 011-1H8"/>',
  edit: '<path d="M13.5 3.5l3 3L7 16H4v-3z"/>',
  clip: '<path d="M14.5 9.5l-5.6 5.6a3.5 3.5 0 01-5-5l6.4-6.4a2.3 2.3 0 013.3 3.3l-6.3 6.3a1.2 1.2 0 01-1.7-1.7l5.6-5.6"/>',
  doc: '<path d="M5 2.5h7l3.5 3.5v11a1 1 0 01-1 1h-9.5a1 1 0 01-1-1v-13.5a1 1 0 011-1z"/><path d="M12 2.5V6h3.5M7 10h6M7 13h4"/>',
  slides: '<rect x="2.5" y="4" width="15" height="10" rx="1.5"/><path d="M10 14v3M7 17h6"/>',
  sidebar: '<rect x="2.5" y="3.5" width="15" height="13" rx="2"/><path d="M7.5 3.5v13"/>',
  panel: '<rect x="2.5" y="3.5" width="15" height="13" rx="2"/><path d="M12.5 3.5v13"/>',
  menu: '<path d="M3 5.5h14M3 10h14M3 14.5h14"/>',
  sliders: '<path d="M3 6h8M15 6h2M3 14h2M9 14h8"/><circle cx="13" cy="6" r="2"/><circle cx="7" cy="14" r="2"/>',
  search: '<circle cx="9" cy="9" r="5.5"/><path d="M13.2 13.2L17 17"/>',
  home: '<path d="M3.5 9L10 3.5 16.5 9v7.5a1 1 0 01-1 1h-3v-5h-5v5h-3a1 1 0 01-1-1z"/>',
  desktop: '<rect x="2.5" y="3.5" width="15" height="10" rx="1.5"/><path d="M7 17h6M10 13.5V17"/>',
  inbox: '<path d="M3 11l2-6.5h10L17 11v4.5a1 1 0 01-1 1H4a1 1 0 01-1-1z"/><path d="M3 11h4l1 2h4l1-2h4"/>',
  book: '<path d="M4 3.5h9a2 2 0 012 2v11H6a2 2 0 01-2-2z"/><path d="M4 14.5a2 2 0 012-2h9"/>',
  chevron: '<path d="M7.5 5l5 5-5 5"/>',
  chevronDown: '<path d="M5 7.5l5 5 5-5"/>',
  back: '<path d="M12.5 5l-5 5 5 5"/>',
  info: '<circle cx="10" cy="10" r="7"/><path d="M10 9v4.5M10 6.5v.1"/>',
  shield: '<path d="M10 2.5l6 2.5v4.5c0 4-2.6 6.6-6 8-3.4-1.4-6-4-6-8V5z"/><path d="M7.5 10l2 2 3.5-4"/>',
  sun: '<circle cx="10" cy="10" r="3.5"/><path d="M10 2v1.8M10 16.2V18M2 10h1.8M16.2 10H18M4.3 4.3l1.3 1.3M14.4 14.4l1.3 1.3M4.3 15.7l1.3-1.3M14.4 5.6l1.3-1.3"/>',
  moon: '<path d="M16 12.5A6.5 6.5 0 017.5 4a6.5 6.5 0 108.5 8.5z"/>',
  cpu: '<rect x="5" y="5" width="10" height="10" rx="1.5"/><path d="M8 8h4v4H8zM8 2.5V5M12 2.5V5M8 15v2.5M12 15v2.5M2.5 8H5M2.5 12H5M15 8h2.5M15 12h2.5"/>',
  upload: '<path d="M10 13V3M6 7l4-4 4 4M4 13.5v2a1 1 0 001 1h10a1 1 0 001-1v-2"/>',
  spark: '<path d="M10 2.5l1.6 4.6 4.9.2-3.9 3 1.4 4.7L10 12.3 6 15l1.4-4.7-3.9-3 4.9-.2z"/>',
};

/** An icon as an inline SVG element. size: '' | 'sm' | 'xs'. */
export function icon(name, size = '') {
  const el = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  el.setAttribute('viewBox', '0 0 20 20');
  el.setAttribute('class', `i${size ? ` ${size}` : ''}`);
  el.setAttribute('aria-hidden', 'true');
  el.innerHTML = P[name] || '';
  return el;
}

export const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => (
  { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

export const store = {
  get(k, d) { try { return localStorage.getItem(k) ?? d; } catch { return d; } },
  set(k, v) { try { localStorage.setItem(k, v); } catch { /* private mode */ } },
};

export const ext = (name) => (name.includes('.') ? name.split('.').pop().toLowerCase().slice(0, 4) : 'file');
export const stem = (name) => name.replace(/\.[^.]+$/, '').replace(/[_-]+/g, ' ').trim();
export const natural = (a, b) => a.localeCompare(b, undefined, { numeric: true });
export const fileTag = (name) => h('span', { class: `ftype ${ext(name)}`, text: ext(name) });

export function bytes(n) {
  if (!n && n !== 0) return '';
  if (n < 1024) return `${n} B`;
  if (n < 1024 ** 2) return `${(n / 1024).toFixed(0)} KB`;
  if (n < 1024 ** 3) return `${(n / 1024 ** 2).toFixed(1)} MB`;
  return `${(n / 1024 ** 3).toFixed(1)} GB`;
}

export function timeAgo(iso) {
  if (!iso) return '';
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (s < 60) return 'just now';
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  if (s < 7 * 86400) return `${Math.floor(s / 86400)} d ago`;
  return new Date(iso).toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' });
}

export function greeting() {
  const hr = new Date().getHours();
  if (hr < 5) return 'Working late';
  if (hr < 12) return 'Good morning';
  if (hr < 18) return 'Good afternoon';
  return 'Good evening';
}

export async function copyText(text) {
  try { await navigator.clipboard.writeText(text); return true; } catch { return false; }
}
