// New project: a name, where its folder goes, and an explicit "I trust this folder".
import { api, loadLists } from '../api.js';
import { h, icon } from '../dom.js';
import { go, joinPath, pathParts, safeFolderName, shortPath, state } from '../state.js';
import { openDialog, toast } from '../ui/overlay.js';
import { pickFolder } from './folder-picker.js';

/** Folders that can't hold project files directly. */
function reserved(path) {
  const s = state.settings || {};
  return [s.home, s.library, s.user_home].filter(Boolean).includes(path);
}

/**
 * Open the dialog. onCreated(result) runs after the project exists ({project, chat});
 * onCancel() runs if the user closes it without creating anything.
 */
export async function openNewProject({ name = '', onCreated = null, onCancel = null } = {}) {
  if (!state.settings) state.settings = await api('GET', '/api/settings');
  const home = state.settings.home;
  let parent = home; // where a new folder is made
  let mode = 'new'; // 'new' = parent/<name> · 'here' = parent itself · 'existing' = add project in parent
  let created = null;

  const nameInput = h('input', { class: 'input', value: name, placeholder: 'e.g. Acme Health Plan 2026', autofocus: true, maxlength: 120 });
  const trust = h('input', { type: 'checkbox' });
  const create = h('button', { class: 'btn primary', type: 'button' }, 'Create project');
  const location = h('div');

  const folderName = () => safeFolderName(nameInput.value.trim() || 'Untitled project');
  const finalPath = () => (mode === 'new' ? joinPath(parent, folderName()) : parent);

  function crumbs(path, boldLast) {
    const parts = pathParts(shortPath(path));
    const shown = parts.length > 4 ? ['…', ...parts.slice(-3)] : parts;
    return h('div', { class: 'crumbs-path' }, shown.map((p, i) => [
      i ? h('span', { class: 'sep', text: '›' }) : null,
      i === shown.length - 1 && boldLast ? h('b', { text: p }) : h('span', { text: p }),
    ]));
  }

  function choice(value, title, desc, path, disabled = false) {
    const radio = h('input', { type: 'radio', name: 'np-mode', checked: mode === value ? true : null, disabled: disabled ? true : null });
    const el = h('label', { class: `choice${mode === value ? ' on' : ''}`, 'aria-disabled': disabled ? 'true' : null },
      radio, h('div', { style: { minWidth: '0', flex: '1' } }, h('div', { class: 't', text: title }), h('div', { class: 'd', text: desc }), path ? crumbs(path, true) : null));
    if (!disabled) radio.addEventListener('change', () => { mode = value; render(); });
    return el;
  }

  function render() {
    const customParent = parent !== home;
    const blocks = [];
    if (mode === 'existing') {
      blocks.push(h('div', { class: 'note trust' }, icon('folder', 'sm'),
        h('div', {}, h('strong', { text: 'This folder already holds a Proposal Studio project.' }), ' It will be added back with its files and chats.')),
      h('div', { style: { marginTop: '10px' } }, crumbs(parent, true)));
    } else if (!customParent) {
      blocks.push(h('div', { class: 'loc-line' }, crumbs(finalPath(), true), h('div', { class: 'hint', text: 'A new folder, in your Proposal Studio folder.' })));
    } else {
      const here = reserved(parent);
      blocks.push(h('div', { class: 'picker-choice' },
        choice('new', 'Create a new folder inside it', 'Recommended — keeps this project separate.', joinPath(parent, folderName())),
        choice('here', 'Use this folder itself', here ? 'Not allowed for this folder (it is too broad or used by Proposal Studio).' : 'Good for a folder that already holds this bid’s documents.', parent, here)));
    }
    location.replaceChildren(...blocks);
    create.textContent = mode === 'existing' ? 'Add project' : 'Create project';
    create.disabled = !trust.checked || (mode !== 'existing' && !nameInput.value.trim());
  }

  async function change() {
    const picked = await pickFolder({ title: 'Where should the project live?', start: parent, confirm: 'Choose' });
    if (!picked) return;
    parent = picked.path;
    mode = picked.project ? 'existing' : (mode === 'here' && !reserved(parent) ? 'here' : 'new');
    render();
  }

  nameInput.addEventListener('input', render);
  nameInput.addEventListener('keydown', (e) => { if (e.key === 'Enter' && !create.disabled) create.click(); });
  trust.addEventListener('change', render);

  create.addEventListener('click', async () => {
    d.setError('');
    create.disabled = true;
    try {
      const folder = parent === home && mode === 'new' ? '' : finalPath();
      created = await api('POST', '/api/projects', { name: nameInput.value.trim(), folder, trust: true });
      d.close();
      await loadLists();
      toast(`Project folder: ${shortPath(created.project.path)}`, { ms: 6000 });
      if (onCreated) await onCreated(created);
      else go(`#/project/${created.project.id}`);
    } catch (e) {
      d.setError(e.message);
      render();
    }
  });

  const body = h('div', {},
    h('div', { class: 'field' }, h('label', { text: 'Project name' }), nameInput),
    h('div', { class: 'field' },
      h('div', { style: { display: 'flex', alignItems: 'center', gap: '8px' } },
        h('span', { class: 'label', style: { flex: '1' }, text: 'Location' }),
        h('button', { class: 'btn ghost sm', type: 'button', onclick: () => { parent = home; mode = 'new'; render(); }, title: 'Back to the default location' }, 'Default'),
        h('button', { class: 'btn sm', type: 'button', onclick: change }, icon('folder', 'sm'), 'Change…')),
      location),
    h('label', { class: 'note trust check', style: { marginTop: '4px' } }, trust,
      h('span', {}, h('strong', { text: 'I trust this folder.' }), ' Proposal Studio may read and write files only inside it — uploaded RFPs, chats, the search index, summaries and decks.')));

  const d = openDialog({
    title: 'New project',
    sub: 'One project per bid. Everything for it is kept in its own folder.',
    body,
    actions: [h('button', { class: 'btn', type: 'button', onclick: () => d.close() }, 'Cancel'), create],
    onClose: () => { if (!created) onCancel?.(); },
  });
  render();
}
