// RFP summary and slide previews for the side panel.
import { api, enc } from '../api.js';
import { h, icon } from '../dom.js';
import { latestRender, outUrl } from './files.js';

const citeText = (cites) => (cites || []).map((c) => (c.page ? `${c.section}, p.${c.page}` : c.section)).join(' · ');

function empty(title, text, button) {
  return h('div', { class: 'empty' }, h('h3', { text: title }), text, button ? h('br') : null, button);
}

export async function summaryView(project, { onAnalyse, busy }) {
  let data;
  try {
    data = await api('GET', `/api/projects/${enc(project.id)}/digest`);
  } catch (err) {
    if (err.status !== 404) throw err;
    return empty('No RFP summary yet', 'Analyse the RFP to pull out the due date, requirements, evaluation criteria, compliance and risks — all with citations.',
      project.status.chunks ? h('button', { class: 'btn primary', type: 'button', disabled: busy || null, onclick: onAnalyse }, icon('doc', 'sm'), 'Analyse RFP') : h('div', { class: 'hint', text: 'Add the RFP first.' }));
  }
  const d = data.digest;
  const o = d.opportunity || {};
  const root = h('div', {});
  if (data.stale) root.append(h('div', { class: 'note warn', style: { marginBottom: '14px' } }, icon('info', 'sm'), 'Files changed since this summary. Analyse again to refresh it.'));
  if (o.due_date) root.append(h('div', { class: 'due' }, icon('doc'), h('div', {}, h('div', { class: 'lbl', text: 'Proposal due' }), h('div', { class: 'val', text: o.due_date }))));
  const kv = [['Client', o.client], ['Title', o.title], ['Format', o.submission_format], ['Limits', o.page_or_slide_limits]].filter(([, v]) => v);
  if (kv.length) root.append(h('dl', { class: 'kv' }, kv.flatMap(([k, v]) => [h('dt', { text: k }), h('dd', { text: v })])));

  const section = (title, items, render) => {
    if (!items?.length) return;
    root.append(h('h3', { class: 'section-title', style: { marginTop: '20px' }, text: `${title} · ${items.length}` }),
      h('ul', { class: 'items' }, items.map((it) => h('li', {}, ...render(it)))));
  };
  const src = (c) => (c?.length ? h('span', { class: 'src', text: citeText(c) }) : null);
  section('Requirements', d.requirements, (r) => [
    h('span', { class: `badge ${r.mandatory ? 'accent' : ''}`, text: r.mandatory ? 'Must' : 'Should' }),
    h('span', { class: 'badge', text: r.type }), r.text, src(r.cite)]);
  section('Evaluation criteria', d.evaluation_criteria, (e) => [e.criterion, e.weight ? h('strong', { text: ` — ${e.weight}` }) : null, src(e.cite)]);
  section('Business problems', d.business_problems, (x) => [x.statement, src(x.evidence)]);
  section('Technical problems', d.technical_problems, (x) => [x.statement, src(x.evidence)]);
  section('Current state', d.current_state, (x) => [x.item, src(x.evidence)]);
  section('Desired outcomes', d.desired_outcomes, (x) => [x.item, src(x.evidence)]);
  section('Compliance', d.compliance, (x) => [h('strong', { text: `${x.framework}: ` }), x.detail, src(x.cite)]);
  section('Systems mentioned', d.systems_mentioned, (x) => [h('strong', { text: x.name }), x.role ? ` — ${x.role}` : '']);
  section('Risks and red flags', d.risks_and_red_flags, (x) => [x.item, src(x.cite)]);
  section('Open questions', d.open_questions, (x) => [x]);
  return root;
}

const SKIP = new Set(['id', 'slide_type', 'title', 'speaker_notes', 'sources', 'review']);
const label = (k) => k.replace(/_/g, ' ').replace(/^\w/, (c) => c.toUpperCase());

function slideContent(s) {
  const frame = h('div', { class: 'slide-frame' }, h('div', { class: 'st', text: s.title }));
  if (s.slide_type === 'before_after') {
    frame.append(h('div', { class: 'cols' },
      h('div', {}, h('div', { class: 'colh', text: s.before_title || 'Today' }), h('ul', {}, (s.before || []).map((b) => h('li', { text: b })))),
      h('div', {}, h('div', { class: 'colh', text: s.after_title || 'With us' }), h('ul', {}, (s.after || []).map((b) => h('li', { text: b }))))));
    return frame;
  }
  for (const [k, v] of Object.entries(s)) {
    if (SKIP.has(k) || v === null || v === '' || (Array.isArray(v) && !v.length)) continue;
    if (typeof v === 'string') frame.append(h('div', { text: v }));
    else if (Array.isArray(v)) {
      frame.append(h('ul', {}, v.map((item) => {
        if (typeof item === 'string') return h('li', { text: item });
        if (item.components) return h('li', {}, h('strong', { text: `${item.name}: ` }), item.components.join(', '));
        if (item.when) return h('li', {}, h('strong', { text: `${item.when}: ` }), item.what);
        if (item.description) return h('li', {}, h('strong', { text: `${item.name}: ` }), item.description);
        return h('li', { text: Object.values(item).join(' — ') });
      })));
    }
  }
  return frame;
}

export async function slidesView(project, { onBuild, busy }) {
  let deck;
  try {
    deck = await api('GET', `/api/projects/${enc(project.id)}/deck`);
  } catch (err) {
    if (err.status !== 404) throw err;
    return empty('No slides yet', 'Build slides writes a tailored deck from the RFP and your content library, then renders it on your template.',
      project.status.chunks ? h('button', { class: 'btn primary', type: 'button', disabled: busy || null, onclick: onBuild }, icon('slides', 'sm'), 'Build slides') : h('div', { class: 'hint', text: 'Add the RFP first.' }));
  }
  const root = h('div', {});
  const latest = latestRender(project);
  root.append(latest
    ? h('a', { class: 'btn primary', href: outUrl(project.id, latest), download: latest, style: { marginBottom: '16px' } }, icon('download', 'sm'), `Download ${latest}`)
    : h('div', { class: 'note warn', style: { marginBottom: '16px' } }, icon('info', 'sm'), 'Slides are written but not built into PowerPoint yet. Use Build slides.'));
  const slides = deck.slides || [];
  root.append(h('h3', { class: 'section-title', text: `${slides.length} slides` }));
  slides.forEach((s, n) => {
    const card = h('div', { class: 'slide' }, slideContent(s),
      h('div', { class: 'slide-foot' }, h('span', { text: `${n + 1} · ${label(s.slide_type)}` }), h('span', { class: 'mono', text: s.id })));
    if (s.review?.length) card.append(h('div', { class: 'slide-review' }, h('strong', { text: 'Please review' }), h('ul', {}, s.review.map((r) => h('li', { text: r })))));
    root.append(card);
  });
  return root;
}
