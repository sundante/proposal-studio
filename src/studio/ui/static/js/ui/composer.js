// The message composer: auto-growing textarea, attachment cards, send/stop.
import { bytes, fileTag, h, icon } from '../dom.js';
import { state } from '../state.js';

const ACCEPT = '.pdf,.docx,.xlsx,.pptx,.txt,.md';

export class Composer {
  /**
   * @param {{placeholder?: string, onSubmit: Function, onStop?: Function, extras?: Node[]}} opts
   * `extras` sit next to the paperclip (e.g. the project chip on the home screen).
   */
  constructor({ placeholder = 'Ask about the RFP…', onSubmit, onStop = null, extras = [] }) {
    this.files = [];
    this.onSubmit = onSubmit;
    this.onStop = onStop;
    this.ta = h('textarea', { rows: 1, placeholder, 'aria-label': 'Message' });
    this.list = h('div', { class: 'composer-files' });
    this.input = h('input', { type: 'file', multiple: true, hidden: true, accept: ACCEPT });
    this.sendBtn = h('button', { class: 'send-btn', type: 'submit', 'aria-label': 'Send' });
    this.el = h('form', { class: 'composer', onsubmit: (e) => { e.preventDefault(); this.submit(); } },
      this.list, this.ta,
      h('div', { class: 'composer-row' },
        h('button', { class: 'icon-btn', type: 'button', title: 'Attach files (PDF, Word, Excel, PowerPoint, text)', 'aria-label': 'Attach files', onclick: () => this.input.click() }, icon('clip')),
        ...extras,
        h('span', { class: 'grow' }),
        this.input, this.sendBtn));
    this.ta.addEventListener('input', () => this.sync());
    this.ta.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); this.submit(); }
    });
    this.ta.addEventListener('paste', (e) => {
      const files = [...(e.clipboardData?.files || [])];
      if (files.length) { e.preventDefault(); this.add(files); }
    });
    this.ta.addEventListener('focus', () => { state.activeComposer = this; });
    this.input.addEventListener('change', () => { this.add([...this.input.files]); this.input.value = ''; });
    state.activeComposer = this;
    this.sync();
  }

  add(files) {
    for (const f of files) if (!this.files.some((x) => x.name === f.name)) this.files.push(f);
    this.renderFiles();
    this.sync();
    this.ta.focus();
  }

  renderFiles() {
    this.list.replaceChildren(...this.files.map((f) => h('div', { class: 'attach-card' }, fileTag(f.name),
      h('div', { class: 'meta' }, h('span', { class: 'nm', text: f.name, title: f.name }), h('span', { class: 'sz', text: bytes(f.size) })),
      h('button', {
        class: 'icon-btn sm', type: 'button', 'aria-label': `Remove ${f.name}`, title: 'Remove',
        onclick: () => { this.files = this.files.filter((x) => x !== f); this.renderFiles(); this.sync(); },
      }, icon('x', 'xs')))));
  }

  sync() {
    this.ta.style.height = 'auto';
    if (this.ta.scrollHeight) this.ta.style.height = `${this.ta.scrollHeight}px`;
    const busy = Boolean(state.streaming);
    this.sendBtn.classList.toggle('stop', busy);
    this.sendBtn.replaceChildren(icon(busy ? 'stop' : 'up'));
    this.sendBtn.title = busy ? 'Stop' : 'Send (Enter)';
    this.sendBtn.setAttribute('aria-label', busy ? 'Stop' : 'Send');
    this.sendBtn.disabled = !busy && !this.ta.value.trim() && !this.files.length;
  }

  submit() {
    if (state.streaming) { (this.onStop || (() => state.streaming.abort()))(); return; }
    const text = this.ta.value.trim();
    if (!text && !this.files.length) return;
    const files = this.files;
    this.files = [];
    this.ta.value = '';
    this.renderFiles();
    this.sync();
    this.onSubmit({ text, files });
  }

  /** Put text/files back (e.g. when the user cancels creating a project). */
  restore({ text = '', files = [] }) {
    this.ta.value = text;
    this.files = files;
    this.renderFiles();
    this.sync();
  }

  fill(text) { this.ta.value = text; this.sync(); this.ta.focus(); }
  focus() { this.ta.focus(); }
}
