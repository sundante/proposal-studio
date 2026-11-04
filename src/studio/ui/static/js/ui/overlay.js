// Menus, dialogs (with in-app confirm/prompt) and toasts.
import { $$, h, icon } from '../dom.js';

// ---------------------------------------------------------------- menu
let openMenu = null;

/** Show a menu under `anchor`. items: {label, icon, run, danger, sub, checked} | '-' | {heading}. */
export function popMenu(anchor, items, { align = 'start' } = {}) {
  closeMenu();
  const menu = h('div', { class: 'menu', role: 'menu' }, items.map((it) => {
    if (it === '-') return h('div', { class: 'menu-sep', role: 'separator' });
    if (it.heading) return h('div', { class: 'menu-label', text: it.heading });
    return h('button', {
      class: `menu-item${it.danger ? ' danger' : ''}${it.checked ? ' checked' : ''}`, role: 'menuitem', type: 'button',
      onclick: (e) => { e.stopPropagation(); closeMenu(); it.run(); },
    }, it.icon ? icon(it.icon, 'sm') : null, h('span', { class: 'ellipsis', text: it.label }), it.sub ? h('span', { class: 'sub', text: it.sub }) : null);
  }));
  document.body.append(menu);
  const r = anchor.getBoundingClientRect();
  const w = menu.offsetWidth;
  let left = align === 'end' ? r.right - w : r.left;
  left = Math.max(8, Math.min(left, window.innerWidth - w - 8));
  const below = r.bottom + 6;
  const top = below + menu.offsetHeight > window.innerHeight - 8 ? Math.max(8, r.top - menu.offsetHeight - 6) : below;
  Object.assign(menu.style, { left: `${left}px`, top: `${top}px` });
  anchor.setAttribute('aria-expanded', 'true');
  const buttons = $$('button', menu);
  buttons[0]?.focus();
  menu.addEventListener('keydown', (e) => {
    const i = buttons.indexOf(document.activeElement);
    if (e.key === 'ArrowDown') { e.preventDefault(); buttons[(i + 1) % buttons.length].focus(); }
    if (e.key === 'ArrowUp') { e.preventDefault(); buttons[(i - 1 + buttons.length) % buttons.length].focus(); }
    if (e.key === 'Escape') { closeMenu(); anchor.focus(); }
    if (e.key === 'Tab') closeMenu();
  });
  const outside = (e) => { if (!menu.contains(e.target)) closeMenu(); };
  setTimeout(() => document.addEventListener('pointerdown', outside), 0);
  openMenu = { menu, anchor, outside };
}

export function closeMenu() {
  if (!openMenu) return;
  openMenu.menu.remove();
  openMenu.anchor.setAttribute('aria-expanded', 'false');
  document.removeEventListener('pointerdown', openMenu.outside);
  openMenu = null;
}

// ---------------------------------------------------------------- dialog
const stack = [];

/**
 * Open a dialog. Returns { el, body, foot, close, setError }.
 * opts: title, sub, body (Node), actions (Node[]), size ('narrow'|'wide'), locked, onClose
 */
export function openDialog({ title, sub = '', body, actions = [], size = '', locked = false, onClose = null, left = null }) {
  closeMenu();
  const err = h('div', { class: 'err', role: 'alert' });
  const foot = h('div', { class: 'dialog-foot' }, left ? h('div', { class: 'left' }, left) : null, ...actions);
  const titleId = `dlg-${Date.now()}-${stack.length}`;
  const dialog = h('div', { class: `dialog ${size}`, role: 'dialog', 'aria-modal': 'true', 'aria-labelledby': titleId },
    h('div', { class: 'dialog-head' },
      h('div', { style: { flex: '1', minWidth: '0' } }, h('h2', { id: titleId, text: title }), sub ? h('p', { class: 'sub', text: sub }) : null),
      locked ? null : h('button', { class: 'icon-btn', 'aria-label': 'Close', title: 'Close (Esc)', onclick: () => close() }, icon('x'))),
    h('div', { class: 'dialog-body' }, body, err),
    actions.length || left ? foot : null);
  const overlay = h('div', { class: `overlay${stack.length ? ' stacked' : ''}` }, dialog);
  overlay.addEventListener('pointerdown', (e) => { if (e.target === overlay && !locked) close(); });
  const prevFocus = document.activeElement;
  document.body.append(overlay);
  let closed = false;
  function close(result) {
    if (closed) return;
    closed = true;
    overlay.remove();
    stack.splice(stack.indexOf(handle), 1);
    prevFocus?.focus?.();
    onClose?.(result);
  }
  const handle = { el: dialog, body: dialog.querySelector('.dialog-body'), foot, close, locked, setError: (m) => { err.textContent = m || ''; } };
  stack.push(handle);
  setTimeout(() => (dialog.querySelector('[autofocus]') || dialog.querySelector('input, textarea, select, .btn.primary') || dialog).focus?.(), 0);
  return handle;
}

window.addEventListener('keydown', (e) => {
  if (e.key !== 'Escape') return;
  if (openMenu) { closeMenu(); return; }
  const top = stack[stack.length - 1];
  if (top && !top.locked) { e.preventDefault(); top.close(); }
});

/** Close every open dialog and menu (used when navigating). */
export function closeAllDialogs() {
  closeMenu();
  [...stack].reverse().forEach((d) => d.close());
}

/** In-app confirm. Resolves true/false. */
export function confirmDialog({ title, message, detail = '', confirm = 'OK', danger = false }) {
  return new Promise((resolve) => {
    let ok = false;
    const yes = h('button', { class: `btn ${danger ? 'danger' : 'primary'}`, type: 'button', onclick: () => { ok = true; d.close(); } }, confirm);
    const no = h('button', { class: 'btn', type: 'button', onclick: () => d.close() }, 'Cancel');
    const d = openDialog({
      title, size: 'narrow',
      body: h('div', {}, h('p', { style: { margin: '0 0 12px', color: 'var(--text-2)' }, text: message }), detail ? h('div', { class: 'path', text: detail }) : null),
      actions: [no, yes],
      onClose: () => resolve(ok),
    });
    setTimeout(() => yes.focus(), 0);
  });
}

/** In-app prompt. Resolves the trimmed text, or null when cancelled. */
export function promptDialog({ title, label = '', value = '', placeholder = '', confirm = 'Save', multiline = false }) {
  return new Promise((resolve) => {
    let result = null;
    const input = multiline
      ? h('textarea', { class: 'textarea', placeholder, rows: 4 })
      : h('input', { class: 'input', placeholder, autofocus: true });
    input.value = value;
    const save = () => { result = input.value.trim(); d.close(); };
    input.addEventListener('keydown', (e) => { if (e.key === 'Enter' && (!multiline || e.metaKey || e.ctrlKey)) { e.preventDefault(); save(); } });
    const d = openDialog({
      title, size: 'narrow',
      body: h('div', { class: 'field' }, label ? h('label', { text: label }) : null, input),
      actions: [h('button', { class: 'btn', type: 'button', onclick: () => d.close() }, 'Cancel'), h('button', { class: 'btn primary', type: 'button', onclick: save }, confirm)],
      onClose: () => resolve(result),
    });
    setTimeout(() => { input.focus(); input.select?.(); }, 0);
  });
}

// ---------------------------------------------------------------- toast
let toasts = null;
export function toast(text, { action = null, ms = 3800 } = {}) {
  if (!toasts) { toasts = h('div', { class: 'toasts', role: 'status', 'aria-live': 'polite' }); document.body.append(toasts); }
  const el = h('div', { class: 'toast' }, h('span', { text }),
    action ? h('button', { type: 'button', onclick: () => { action.run(); el.remove(); } }, action.label) : null);
  toasts.append(el);
  setTimeout(() => el.remove(), ms);
}
