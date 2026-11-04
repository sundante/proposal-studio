// Project files, folder and progress cards (project page and the chat side panel).
import { copyPath, revealProject } from '../actions.js';
import { api, enc } from '../api.js';
import { fileTag, h, icon, natural } from '../dom.js';
import { shortPath } from '../state.js';
import { confirmDialog, toast } from '../ui/overlay.js';

const ACCEPT = '.pdf,.docx,.xlsx,.pptx,.txt,.md';

export function latestRender(project) {
  return (project?.status?.renders || []).slice().sort(natural).pop() || null;
}

export const outUrl = (projectId, name) => `/api/projects/${enc(projectId)}/out/${enc(name)}`;

/** Files with delete, plus an add zone. onAdd(files) uploads + ingests; onChanged(project) after a delete. */
export function filesCard(project, { onAdd, onChanged }) {
  const picker = h('input', { type: 'file', multiple: true, hidden: true, accept: ACCEPT });
  picker.addEventListener('change', () => { const f = [...picker.files]; picker.value = ''; if (f.length) onAdd(f); });
  const zone = h('div', {
    class: 'dropzone', role: 'button', tabindex: '0', onclick: () => picker.click(),
    onkeydown: (e) => { if (e.key === 'Enter') picker.click(); },
  }, icon('upload', 'sm'), h('span', {}, h('strong', { text: 'Add files' }), ' — or drop them here'), h('span', { class: 'hint', text: 'PDF, Word, Excel, PowerPoint, text' }));
  zone.addEventListener('dragover', (e) => { e.preventDefault(); e.stopPropagation(); zone.classList.add('over'); });
  zone.addEventListener('dragleave', () => zone.classList.remove('over'));
  zone.addEventListener('drop', (e) => {
    e.preventDefault(); e.stopPropagation(); zone.classList.remove('over');
    const f = [...(e.dataTransfer?.files || [])];
    if (f.length) onAdd(f);
  });

  const rows = project.files.map((f) => h('div', { class: 'file-row' }, fileTag(f.name),
    h('span', { class: 'nm', text: f.name, title: f.name }),
    h('span', { class: 'sub', text: f.chunks ? `${f.chunks} passages` : 'not indexed' }),
    h('button', {
      class: 'icon-btn sm', type: 'button', title: `Remove ${f.name}`, 'aria-label': `Remove ${f.name}`,
      onclick: async () => {
        const ok = await confirmDialog({ title: `Remove ${f.name}?`, message: 'It is deleted from the project folder and answers will no longer use it.', confirm: 'Remove file', danger: true });
        if (!ok) return;
        try {
          onChanged(await api('DELETE', `/api/projects/${enc(project.id)}/files/${enc(f.name)}`));
          toast(`Removed ${f.name}`);
        } catch (e) { toast(e.message); }
      },
    }, icon('trash', 'sm'))));

  return h('section', { class: 'side-card' },
    h('h4', {}, icon('doc', 'sm'), h('span', { class: 'grow', text: 'Project files' }), h('span', { class: 'badge', text: String(project.files.length) })),
    rows.length ? rows : h('div', { class: 'hint', style: { padding: '2px 2px 4px' }, text: 'No files yet. Add the RFP to get started.' }),
    zone, picker);
}

export function folderCard(project) {
  return h('section', { class: 'side-card' },
    h('h4', {}, icon('folder', 'sm'), h('span', { class: 'grow', text: 'Project folder' })),
    h('div', { class: 'path', text: shortPath(project.path), title: project.path }),
    h('div', { style: { display: 'flex', gap: '8px', marginTop: '10px', flexWrap: 'wrap' } },
      h('button', { class: 'btn sm', type: 'button', onclick: () => revealProject(project) }, icon('open', 'sm'), 'Open folder'),
      h('button', { class: 'btn sm ghost', type: 'button', onclick: () => copyPath(project.path) }, icon('copy', 'sm'), 'Copy path')));
}

export function progressCard(project) {
  const st = project.status;
  const latest = latestRender(project);
  const step = (done, label, stale = false) => h('li', { class: stale ? 'stale' : done ? 'done' : '' },
    h('span', { class: 'dot' }, done || stale ? icon('check') : null), h('span', { text: label }));
  return h('section', { class: 'side-card' },
    h('h4', {}, icon('spark', 'sm'), h('span', { class: 'grow', text: 'Progress' })),
    h('ul', { class: 'steps' },
      step(st.chunks > 0, st.chunks ? `RFP read · ${st.chunks} passages` : 'Add the RFP'),
      step(st.digest && !st.digest_stale, st.digest_stale ? 'RFP analysed — files changed, analyse again' : 'RFP analysed', st.digest_stale),
      step(st.deck, 'Slides written'),
      step(Boolean(latest), latest ? `PowerPoint built · ${latest}` : 'PowerPoint built')),
    latest ? h('a', { class: 'btn sm', href: outUrl(project.id, latest), download: latest, style: { marginTop: '12px' } }, icon('download', 'sm'), 'Download PPTX') : null);
}
