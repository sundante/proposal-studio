// A Finder-style folder picker. Resolves {path, project} for the chosen folder, or null.
import { api, enc } from '../api.js';
import { h, icon } from '../dom.js';
import { joinPath, pathParts, state } from '../state.js';
import { openDialog, promptDialog } from '../ui/overlay.js';

const PLACE_ICONS = { Home: 'home', Documents: 'doc', Desktop: 'desktop', Downloads: 'inbox', 'Proposal Studio': 'book' };

export function pickFolder({ title = 'Choose a folder', start = '', confirm = 'Choose' } = {}) {
  return new Promise((resolve) => {
    let current = null; // listing of the open folder
    let selected = null; // name of the highlighted sub-folder (or null = the open folder)
    let result = null;

    const places = h('nav', { class: 'picker-places', 'aria-label': 'Places' });
    const crumbs = h('div', { class: 'picker-crumbs' });
    const list = h('ul', { class: 'picker-list', role: 'listbox', 'aria-label': 'Folders' });
    const goto = h('input', { class: 'input', placeholder: 'Or type a path and press Enter', spellcheck: 'false', 'aria-label': 'Folder path' });
    const choose = h('button', { class: 'btn primary', type: 'button' }, confirm);
    const newFolder = h('button', { class: 'btn ghost sm', type: 'button', title: 'New folder here' }, icon('folderPlus', 'sm'), 'New folder');

    const target = () => (selected ? joinPath(current.path, selected) : current?.path);

    function syncChoose() {
      const name = selected || pathParts(current?.path).pop() || current?.path;
      choose.textContent = `${confirm} “${name}”`;
      choose.disabled = !current;
    }

    async function open(path) {
      d.setError('');
      try {
        current = await api('GET', `/api/fs?path=${enc(path)}`);
      } catch (e) {
        d.setError(e.status === 404 ? `There's no folder at ${path}.` : e.message);
        return;
      }
      selected = null;
      goto.value = '';
      renderPlaces();
      renderCrumbs();
      renderList();
      syncChoose();
    }

    function renderPlaces() {
      places.replaceChildren(...(current.places || []).map((p) => h('button', {
        class: `picker-place${current.path === p.path ? ' active' : ''}`, type: 'button', title: p.path,
        onclick: () => open(p.path),
      }, icon(PLACE_ICONS[p.label] || 'folder', 'sm'), p.label)));
    }

    function renderCrumbs() {
      const parts = pathParts(current.path);
      const isWin = /^[A-Za-z]:/.test(current.path);
      const items = [];
      let acc = isWin ? '' : '/';
      parts.forEach((part, i) => {
        acc = i === 0 && isWin ? `${part}\\` : joinPath(acc, part);
        const to = acc;
        if (i) items.push(h('span', { class: 'sep' }, icon('chevron', 'xs')));
        items.push(h('button', { type: 'button', onclick: () => open(to) }, part));
      });
      crumbs.replaceChildren(...items);
      requestAnimationFrame(() => { crumbs.scrollLeft = crumbs.scrollWidth; });
    }

    function renderList() {
      if (!current.dirs.length) {
        list.replaceChildren(h('li', { class: 'picker-empty' }, 'No folders here.', h('br'), 'Use “New folder”, or choose this folder.'));
        return;
      }
      list.replaceChildren(...current.dirs.map((name) => {
        const row = h('li', {}, h('button', {
          class: `picker-row${selected === name ? ' selected' : ''}`, type: 'button', role: 'option', 'aria-selected': String(selected === name),
          onclick: () => { selected = selected === name ? null : name; renderList(); syncChoose(); },
          ondblclick: () => open(joinPath(current.path, name)),
          onkeydown: (e) => { if (e.key === 'Enter') { e.preventDefault(); open(joinPath(current.path, name)); } },
          title: 'Click to select · double-click to open',
        }, icon('folder', 'sm'), h('span', { class: 'ellipsis', text: name })));
        return row;
      }));
    }

    newFolder.addEventListener('click', async () => {
      const name = await promptDialog({ title: 'New folder', label: `Inside ${pathParts(current.path).pop() || current.path}`, placeholder: 'Folder name', confirm: 'Create' });
      if (!name) return;
      try {
        await api('POST', '/api/fs/mkdir', { path: current.path, name });
        await open(current.path);
        selected = name;
        renderList();
        syncChoose();
      } catch (e) { d.setError(e.message); }
    });
    goto.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); if (goto.value.trim()) open(goto.value.trim()); } });

    choose.addEventListener('click', async () => {
      const path = target();
      try {
        const info = await api('GET', `/api/fs?path=${enc(path)}`);
        result = { path: info.path, project: Boolean(info.project) };
        d.close();
      } catch (e) { d.setError(e.message); }
    });

    const body = h('div', { class: 'picker' }, places,
      h('div', { class: 'picker-main' },
        h('div', { class: 'picker-bar' }, crumbs, newFolder),
        list,
        h('div', { class: 'picker-goto' }, goto)));
    const d = openDialog({
      title, size: 'wide', body,
      actions: [h('button', { class: 'btn', type: 'button', onclick: () => d.close() }, 'Cancel'), choose],
      onClose: () => resolve(result),
    });
    open(start || state.settings?.user_home || '');
  });
}
