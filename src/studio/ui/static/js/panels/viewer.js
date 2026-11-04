// Document viewer for the side panel: PDF pages (image + selectable text layer) and a reading
// view for Word / Excel / PowerPoint / text. Find, zoom, citation highlights, selection toolbar.
import { api, enc } from '../api.js';
import { copyText, fileTag, h, icon, store } from '../dom.js';
import { emit, state } from '../state.js';
import { toast } from '../ui/overlay.js';

const base = (file) => `/api/projects/${enc(state.project.id)}/files/${enc(file)}`;
const ZOOMS = [0.6, 0.75, 0.9, 1, 1.15, 1.3, 1.5, 1.75, 2];

/** Open `file` in the panel, optionally at `page`, highlighting `text` (a cited passage). */
export function openDocument(file, { page = null, text = '', section = '' } = {}) {
  if (!state.project?.files?.some((f) => f.name === file)) { toast(`${file} isn't in this project.`); return; }
  state.viewer = { project: state.project.id, file, page, text, section, zoom: state.viewer?.file === file ? state.viewer.zoom : 1, query: '' };
  if (store.get('ps.viewerWidened', '0') !== '1') {
    store.set('ps.viewerWidened', '1');
    const w = Math.round(window.innerWidth * 0.55);
    document.documentElement.style.setProperty('--panel-w', `${w}px`);
    store.set('ps.panelW', String(w));
  }
  emit('show-document');
}

/** Render the viewer into `body` (the panel body). */
export function renderViewer(body, { onAsk } = {}) {
  const v = state.viewer;
  const files = state.project?.files || [];
  if (!v || !files.some((f) => f.name === v.file)) {
    body.replaceChildren(files.length
      ? h('div', { class: 'viewer-pick' }, h('h3', { class: 'section-title', text: 'Open a file' }),
        files.map((f) => h('button', { class: 'file-row pick', type: 'button', onclick: () => openDocument(f.name) }, fileTag(f.name), h('span', { class: 'nm', text: f.name }), icon('chevron', 'sm'))))
      : h('div', { class: 'empty' }, h('h3', { text: 'No files yet' }), 'Add the RFP to read it here.'));
    return;
  }
  const isPdf = v.file.toLowerCase().endsWith('.pdf');
  const scroller = h('div', { class: 'viewer-scroll' });
  const pageLabel = h('span', { class: 'muted pg' });
  const findInput = h('input', { class: 'viewer-find', type: 'search', placeholder: 'Find in document', value: v.query || '', 'aria-label': 'Find in document' });
  const findCount = h('span', { class: 'muted small' });
  const fileSel = h('select', { class: 'select viewer-file', 'aria-label': 'File' }, files.map((f) => h('option', { value: f.name, selected: f.name === v.file ? true : null }, f.name)));
  fileSel.addEventListener('change', () => openDocument(fileSel.value));
  const zoomBy = (dir) => {
    const i = Math.max(0, Math.min(ZOOMS.length - 1, ZOOMS.indexOf(v.zoom) + dir));
    v.zoom = ZOOMS[i] ?? 1;
    renderViewer(body, { onAsk });
  };

  body.classList.add('viewer-body');
  body.replaceChildren(
    h('div', { class: 'viewer-bar' },
      fileSel,
      isPdf ? h('div', { class: 'zoom' },
        h('button', { class: 'icon-btn sm', type: 'button', title: 'Zoom out', 'aria-label': 'Zoom out', onclick: () => zoomBy(-1) }, h('span', { text: '−' })),
        h('span', { class: 'muted small', text: `${Math.round(v.zoom * 100)}%` }),
        h('button', { class: 'icon-btn sm', type: 'button', title: 'Zoom in', 'aria-label': 'Zoom in', onclick: () => zoomBy(1) }, h('span', { text: '+' }))) : null,
      pageLabel,
      h('span', { class: 'grow' }),
      h('a', { class: 'icon-btn sm', href: `${base(v.file)}/raw`, download: v.file, title: 'Download', 'aria-label': 'Download' }, icon('download', 'sm')),
      h('button', { class: 'icon-btn sm', type: 'button', title: 'Open in its app', 'aria-label': 'Open in its default app', onclick: () => api('POST', `${base(v.file)}/open`).catch((e) => toast(e.message)) }, icon('open', 'sm'))),
    h('div', { class: 'viewer-findbar' }, icon('search', 'sm'), findInput, findCount),
    scroller);

  const sel = selectionToolbar(scroller, () => ({ file: v.file, page: currentPage() }), onAsk);
  let currentPage = () => null;
  if (isPdf) currentPage = renderPdf(scroller, v, pageLabel);
  else currentPage = renderSections(scroller, v, pageLabel);

  let timer = null;
  findInput.addEventListener('input', () => {
    clearTimeout(timer);
    timer = setTimeout(() => { v.query = findInput.value; runFind(scroller, v, findCount, isPdf); }, 250);
  });
  findInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') { e.preventDefault(); stepFind(scroller, e.shiftKey ? -1 : 1); }
  });
  if (v.query) runFind(scroller, v, findCount, isPdf);
  return sel;
}

// ---------------------------------------------------------------- PDF
function renderPdf(scroller, v, pageLabel) {
  let meta = null;
  const pages = [];
  const holder = h('div', { class: 'pdf-pages' });
  scroller.replaceChildren(holder, h('div', { class: 'status' }, h('span', { class: 'dots' }, h('i'), h('i'), h('i'))));
  const observer = new IntersectionObserver((entries) => {
    for (const e of entries) if (e.isIntersecting) loadPage(e.target);
  }, { root: scroller, rootMargin: '600px 0px' });

  const widthPx = () => Math.max(240, Math.round((scroller.clientWidth - 32) * v.zoom));

  function loadPage(el) {
    if (el.dataset.loaded) return;
    el.dataset.loaded = '1';
    const n = Number(el.dataset.n);
    const w = widthPx();
    const dpr = Math.min(2, window.devicePixelRatio || 1);
    el.append(h('img', { src: `${base(v.file)}/pages/${n}.png?w=${Math.round(w * dpr)}`, alt: `Page ${n}`, draggable: 'false' }));
    api('GET', `${base(v.file)}/pages/${n}/words`).then((data) => {
      const s = w / data.width;
      const layer = h('div', { class: 'text-layer' });
      for (const [x0, y0, x1, y1, word] of data.words) {
        layer.append(h('span', {
          style: { left: `${x0 * s}px`, top: `${y0 * s}px`, width: `${(x1 - x0) * s}px`, height: `${(y1 - y0) * s}px`, fontSize: `${(y1 - y0) * s * 0.92}px` },
        }, `${word} `));
      }
      el.append(layer);
    }).catch(() => {});
  }

  api('GET', `${base(v.file)}/meta`).then((m) => {
    meta = m;
    scroller.querySelector('.status')?.remove();
    const w = widthPx();
    m.page_sizes.forEach(([pw, ph], i) => {
      const el = h('div', { class: 'pdf-page', 'data-n': String(i + 1), style: { width: `${w}px`, height: `${(ph / pw) * w}px` } },
        h('span', { class: 'pg-no', text: String(i + 1) }));
      el.dataset.scale = String(w / pw);
      pages.push(el);
      holder.append(el);
      observer.observe(el);
    });
    pageLabel.textContent = `${m.pages} pages`;
    if (v.page) {
      const target = pages[v.page - 1];
      if (target) {
        loadPage(target);
        requestAnimationFrame(() => { scroller.scrollTop = target.offsetTop - 12; });
        if (v.text) highlightPassage(v, target, Number(v.page));
      }
    }
  }).catch((e) => scroller.replaceChildren(h('div', { class: 'empty', text: e.message })));

  scroller.addEventListener('scroll', () => {
    if (!meta) return;
    const n = currentPage();
    if (n) pageLabel.textContent = `Page ${n} of ${meta.pages}`;
  }, { passive: true });

  return () => {
    const top = scroller.scrollTop + 40;
    let n = 1;
    for (const el of pages) { if (el.offsetTop <= top) n = Number(el.dataset.n); else break; }
    return n;
  };
}

/** Highlight a cited passage on `page`: the passage's first words, else its section heading. */
async function highlightPassage(v, pageEl, page) {
  const words = v.text.split(/\s+/).filter(Boolean);
  const heading = (v.section || '').split('>').pop().trim();
  const tries = [12, 7, 4].map((take) => words.slice(0, take).join(' '));
  if (heading) tries.push(heading);
  for (const q of tries) {
    if (q.length < 4) continue;
    try {
      const { hits } = await api('GET', `${base(v.file)}/find?q=${enc(q)}`);
      const hit = hits.find((x) => x.page === page) || hits[0];
      if (hit) {
        const el = pageEl.parentElement.querySelector(`.pdf-page[data-n="${hit.page}"]`) || pageEl;
        drawRects(el, hit.rects, 'cite-hl');
        el.parentElement.parentElement.scrollTop = el.offsetTop + hit.rects[0][1] * Number(el.dataset.scale) - 80;
        return;
      }
    } catch { return; }
  }
}

function drawRects(pageEl, rects, cls) {
  const s = Number(pageEl.dataset.scale);
  for (const [x0, y0, x1, y1] of rects) {
    pageEl.append(h('div', { class: `hl ${cls}`, style: { left: `${x0 * s - 2}px`, top: `${y0 * s - 1}px`, width: `${(x1 - x0) * s + 4}px`, height: `${(y1 - y0) * s + 2}px` } }));
  }
}

// ---------------------------------------------------------------- reading view
function renderSections(scroller, v, pageLabel) {
  const doc = h('article', { class: 'reading' });
  scroller.replaceChildren(h('div', { class: 'status' }, h('span', { class: 'dots' }, h('i'), h('i'), h('i'))));
  const ext = v.file.split('.').pop().toLowerCase();
  const unit = { pptx: 'Slide', xlsx: 'Sheet', docx: 'Page', pdf: 'Page' }[ext] || 'Part';
  api('GET', `${base(v.file)}/sections`).then(({ sections }) => {
    let lastHead = '';
    let lastPage = null;
    sections.forEach((s, i) => {
      if (s.page !== null && s.page !== lastPage && ext !== 'docx') {
        doc.append(h('div', { class: 'page-sep', text: `${unit} ${s.page}` }));
        lastPage = s.page;
      }
      const head = s.heading.join(' › ');
      if (head && head !== lastHead) {
        doc.append(h(`h${Math.min(4, s.heading.length + 1)}`, { text: s.heading[s.heading.length - 1], title: head }));
        lastHead = head;
      }
      doc.append(s.kind === 'table'
        ? h('pre', { class: 'table-block', 'data-section': String(i), 'data-page': s.page ?? '', text: s.text })
        : h('div', { class: 'para', 'data-section': String(i), 'data-page': s.page ?? '' }, ...s.text.split(/\n{2,}/).map((p) => h('p', { text: p }))));
    });
    scroller.replaceChildren(doc);
    pageLabel.textContent = `${sections.length} sections`;
    if (v.text) {
      const needle = v.text.split(/\s+/).slice(0, 6).join(' ').toLowerCase();
      const el = [...doc.querySelectorAll('[data-section]')].find((x) => x.textContent.toLowerCase().replace(/\s+/g, ' ').includes(needle));
      if (el) { el.classList.add('cite-block'); requestAnimationFrame(() => { scroller.scrollTop = el.offsetTop - 60; }); }
    }
  }).catch((e) => scroller.replaceChildren(h('div', { class: 'empty', text: e.message })));
  return () => {
    const top = scroller.scrollTop + 40;
    let page = null;
    for (const el of scroller.querySelectorAll('[data-section]')) { if (el.offsetTop <= top) page = el.dataset.page || page; else break; }
    return page ? Number(page) : null;
  };
}

// ---------------------------------------------------------------- find
async function runFind(scroller, v, countEl, isPdf) {
  scroller.querySelectorAll('.find-hl').forEach((el) => el.remove());
  scroller.querySelectorAll('mark.find').forEach((m) => m.replaceWith(document.createTextNode(m.textContent)));
  const q = (v.query || '').trim();
  if (q.length < 2) { countEl.textContent = ''; return; }
  if (isPdf) {
    const { hits } = await api('GET', `${base(v.file)}/find?q=${enc(q)}`);
    let n = 0;
    for (const hit of hits) {
      const el = scroller.querySelector(`.pdf-page[data-n="${hit.page}"]`);
      if (el) { drawRects(el, hit.rects, 'find-hl'); n += hit.rects.length; }
    }
    countEl.textContent = n ? `${n} found` : 'No matches';
  } else {
    const low = q.toLowerCase();
    let n = 0;
    for (const p of scroller.querySelectorAll('.reading p, .reading pre')) {
      const text = p.textContent;
      if (!text.toLowerCase().includes(low)) continue;
      const parts = [];
      let i = 0;
      let at;
      while ((at = text.toLowerCase().indexOf(low, i)) >= 0) {
        parts.push(document.createTextNode(text.slice(i, at)), h('mark', { class: 'find', text: text.slice(at, at + q.length) }));
        i = at + q.length;
        n += 1;
      }
      parts.push(document.createTextNode(text.slice(i)));
      p.replaceChildren(...parts);
    }
    countEl.textContent = n ? `${n} found` : 'No matches';
  }
  stepFind(scroller, 0);
}

function stepFind(scroller, dir) {
  const marks = [...scroller.querySelectorAll('.find-hl, mark.find')];
  if (!marks.length) return;
  let i = marks.findIndex((m) => m.classList.contains('current'));
  marks.forEach((m) => m.classList.remove('current'));
  i = i < 0 ? 0 : (i + dir + marks.length) % marks.length;
  const m = marks[i];
  m.classList.add('current');
  const page = m.closest('.pdf-page');
  const y = page ? page.offsetTop + m.offsetTop : m.getBoundingClientRect().top - scroller.getBoundingClientRect().top + scroller.scrollTop;
  scroller.scrollTop = y - scroller.clientHeight / 3;
}

// ---------------------------------------------------------------- selection toolbar
function selectionToolbar(scroller, where, onAsk) {
  const bar = h('div', { class: 'sel-bar', hidden: true });
  scroller.parentElement.append(bar);
  const hide = () => { bar.hidden = true; };
  scroller.addEventListener('mouseup', () => setTimeout(() => {
    const sel = window.getSelection();
    const text = sel ? sel.toString().replace(/\s+/g, ' ').trim() : '';
    if (!text || text.length < 3 || !scroller.contains(sel.anchorNode)) { hide(); return; }
    const rect = sel.getRangeAt(0).getBoundingClientRect();
    const host = scroller.parentElement.getBoundingClientRect();
    const loc = where();
    const ref = `${loc.file}${loc.page ? ` p.${loc.page}` : ''}`;
    bar.replaceChildren(
      onAsk ? h('button', { type: 'button', onclick: () => { hide(); onAsk(`> “${text.slice(0, 600)}” (${ref})\n\n`); } }, icon('chat', 'sm'), 'Ask about this') : null,
      h('button', { type: 'button', onclick: async () => { hide(); toast((await copyText(text)) ? 'Copied' : 'Copy failed'); } }, icon('copy', 'sm'), 'Copy'),
      h('button', { type: 'button', title: 'The notebook arrives in the next update — copied for now', onclick: async () => { hide(); await copyText(`${text}\n— ${ref}`); toast('Copied with its source (notebook coming next)'); } }, icon('book', 'sm'), 'Add to notes'));
    bar.hidden = false;
    const left = Math.max(8, Math.min(rect.left - host.left + rect.width / 2 - bar.offsetWidth / 2, host.width - bar.offsetWidth - 8));
    bar.style.left = `${left}px`;
    bar.style.top = `${Math.max(48, rect.top - host.top - bar.offsetHeight - 8)}px`;
  }, 0));
  scroller.addEventListener('scroll', hide, { passive: true });
  scroller.addEventListener('mousedown', hide);
  return bar;
}
