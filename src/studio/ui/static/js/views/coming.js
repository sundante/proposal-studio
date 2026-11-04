// Placeholder pages for features scheduled in the next phase.
import { h, icon } from '../dom.js';

const PAGES = {
  outputs: ['slides', 'Outputs', 'Every deck, RFP summary, requirements matrix and research report across your projects, as cards with previews.'],
  templates: ['palette', 'Templates', 'Add your PowerPoint template, see its layouts, map each slide type to a layout and test-render it.'],
  customize: ['sliders', 'Customize', 'Choose which storyline slides go in every deck, curate content blocks from past proposals, and tune routing.'],
};

export function renderComing(view, topbar, key) {
  const [ic, title, text] = PAGES[key];
  document.title = `${title} · Proposal Studio`;
  topbar.replaceChildren(h('div', { class: 'title' }, h('span', { class: 'cur', text: title })));
  view.replaceChildren(h('div', { class: 'page' }, h('div', { class: 'coming' },
    icon(ic), h('h1', { text: title }), h('p', { text }), h('span', { class: 'badge accent', text: 'Coming in the next update' }))));
}
