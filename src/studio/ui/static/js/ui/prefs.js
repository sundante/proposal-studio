// Composer choices: working mode, model and effort (Fast / Thinking). Chips + their menus.
import { api } from '../api.js';
import { bytes, h, icon, store } from '../dom.js';
import { popMenu } from './overlay.js';

export const MODES = [
  { id: 'auto', label: 'Auto', desc: 'Routes each message for you', placeholder: 'Ask about the RFP, or drop files here…' },
  { id: 'ask', label: 'Ask the RFP', desc: 'Cited answers from the project files', placeholder: 'Ask a question about the RFP…' },
  { id: 'research', label: 'Research', desc: 'Multi-step, across the RFP and your library', placeholder: 'What should we research?' },
  { id: 'draft', label: 'Draft', desc: 'Write using the RFP summary and deck', placeholder: 'Draft an email, an answer, a slide… (or “platform shorter” to edit a slide)' },
  { id: 'chat', label: 'Chat', desc: 'Talk with the model, no RFP', placeholder: 'Ask the model anything…' },
];
export const modeOf = (id) => MODES.find((m) => m.id === id) || MODES[0];

/** Defaults for new chats, remembered in this browser. */
export function defaultPrefs() {
  const think = store.get('ps.think', '');
  return { mode: store.get('ps.mode', 'auto'), model: store.get('ps.model', ''), think: think === '' ? null : think === '1' };
}
export function rememberDefaults(p) {
  store.set('ps.mode', p.mode);
  store.set('ps.model', p.model || '');
  store.set('ps.think', p.think === null || p.think === undefined ? '' : p.think ? '1' : '0');
}

let modelsCache = null;
let modelsAt = 0;
export async function loadModels(force = false) {
  if (!force && modelsCache && Date.now() - modelsAt < 60000) return modelsCache;
  try { modelsCache = await api('GET', '/api/models'); modelsAt = Date.now(); } catch { modelsCache = null; }
  return modelsCache;
}

/**
 * Mode and model chips bound to a prefs object. onChange(prefs) after every change.
 * Returns { mode: Node, model: Node, refresh() }.
 */
export function prefChips(prefs, onChange) {
  const modeBtn = h('button', { class: 'chip ghost-chip', type: 'button', 'aria-haspopup': 'menu', title: 'How Proposal Studio handles your message' });
  const modelBtn = h('button', { class: 'chip ghost-chip', type: 'button', 'aria-haspopup': 'menu', title: 'Model and effort' });

  const refresh = async () => {
    const m = modeOf(prefs.mode);
    modeBtn.replaceChildren(h('span', { text: m.label }), icon('chevronDown', 'xs'));
    const info = await loadModels();
    const worker = prefs.model || info?.roles?.worker || 'default';
    const thinking = prefs.think === null || prefs.think === undefined ? Boolean(info?.think) : prefs.think;
    modelBtn.replaceChildren(h('span', { class: 'ellipsis', text: worker.replace(/:latest$/, '') }),
      h('span', { class: 'muted', text: thinking ? 'Thinking' : 'Fast' }), icon('chevronDown', 'xs'));
  };

  modeBtn.addEventListener('click', () => popMenu(modeBtn, [
    { heading: 'Mode' },
    ...MODES.map((m) => ({
      label: m.label, desc: m.desc, checked: prefs.mode === m.id, icon: { auto: 'spark', ask: 'doc', research: 'search', draft: 'edit', chat: 'chat' }[m.id],
      run: () => { prefs.mode = m.id; refresh(); onChange(prefs); },
    })),
  ], { align: 'end' }));

  modelBtn.addEventListener('click', async () => {
    const info = await loadModels(true);
    const items = [{ heading: 'Model' }];
    if (!info || info.ollama === false) {
      items.push({ label: 'Ollama is not running', icon: 'info', run: () => {} });
    } else {
      const def = info.roles?.worker;
      items.push({ label: `Default (${(def || '').replace(/:latest$/, '')})`, icon: 'cpu', checked: !prefs.model, run: () => { prefs.model = ''; refresh(); onChange(prefs); } });
      for (const m of info.models.filter((x) => !x.cloud && !/embed/i.test(x.name) && x.name !== def)) {
        const tooBig = m.fits === false;
        items.push({
          label: m.name.replace(/:latest$/, ''),
          desc: tooBig ? 'too big for this machine' : [m.parameters, bytes(m.size), m.loaded ? 'loaded' : ''].filter(Boolean).join(' · '),
          icon: 'cpu', checked: prefs.model === m.name,
          run: () => { if (tooBig) return; prefs.model = m.name; refresh(); onChange(prefs); },
        });
      }
    }
    const thinking = prefs.think === null || prefs.think === undefined ? Boolean(info?.think) : prefs.think;
    items.push('-', { heading: 'Effort' },
      { label: 'Fast', desc: 'Quick answers', icon: 'spark', checked: !thinking, run: () => { prefs.think = false; refresh(); onChange(prefs); } },
      { label: 'Thinking', desc: 'Reasons first — slower, better on hard questions', icon: 'cpu', checked: thinking, run: () => { prefs.think = true; refresh(); onChange(prefs); } });
    popMenu(modelBtn, items, { align: 'end' });
  });

  refresh();
  return { mode: modeBtn, model: modelBtn, refresh };
}
