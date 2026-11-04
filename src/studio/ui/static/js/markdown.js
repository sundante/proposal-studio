// Markdown for replies: HTML is escaped first, then a small, safe subset is rendered.
// Router plumbing lines ("→ routed to /x", "Next: `/cmd`") are dropped; the UI has buttons.
import { esc } from './dom.js';

export function inline(text) {
  const keep = [];
  const stash = (html) => `\u0000${keep.push(html) - 1}\u0000`;
  let s = esc(text);
  s = s.replace(/`([^`]+)`/g, (_, c) => stash(`<code>${c}</code>`));
  s = s.replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, (_, label, url) => {
    const raw = url.replace(/&amp;/g, '&');
    if (!/^(https?:\/\/|\/|#)/i.test(raw)) return label;
    return stash(`<a href="${esc(raw)}" target="_blank" rel="noopener noreferrer">${label}</a>`);
  });
  s = s.replace(/\[(\d+(?:[ ,][^\]]{0,80})?)\]/g, (_, c) => stash(`<span class="cite">${c}</span>`));
  s = s.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
  s = s.replace(/(^|[\s(])\*([^*\s][^*]*)\*(?=[\s).,;:!?]|$)/g, '$1<em>$2</em>');
  s = s.replace(/(^|[\s(])_([^_\s][^_]*)_(?=[\s).,;:!?]|$)/g, '$1<em>$2</em>');
  return s.replace(/\u0000(\d+)\u0000/g, (_, i) => keep[Number(i)]);
}

export function md(src) {
  const lines = String(src || '').replace(/\r/g, '').split('\n');
  const out = [];
  let i = 0;
  const isBlockStart = (l) => /^(```|#{1,4}\s|\s*([-*+]|\d+\.)\s+|>\s?|\|.*\|\s*$|(-{3,}|\*{3,})\s*$|→ |Next: )/.test(l);

  while (i < lines.length) {
    const l = lines[i];
    if (/^```/.test(l)) {
      const buf = [];
      i += 1;
      while (i < lines.length && !/^```/.test(lines[i])) buf.push(lines[i++]);
      i += 1;
      out.push(`<pre><code>${esc(buf.join('\n'))}</code></pre>`);
      continue;
    }
    if (!l.trim()) { i += 1; continue; }
    // Router plumbing ("→ routed to /x", "Next: `/cmd`") is for the CLI; buttons replace it here.
    if (/^→ (routed|not routed)/.test(l) || /^Next: /.test(l)) { i += 1; continue; }
    const head = l.match(/^(#{1,4})\s+(.*)$/);
    if (head) { out.push(`<h${head[1].length}>${inline(head[2])}</h${head[1].length}>`); i += 1; continue; }
    if (/^(-{3,}|\*{3,})\s*$/.test(l)) { out.push('<hr>'); i += 1; continue; }
    if (/^\|.*\|\s*$/.test(l) && i + 1 < lines.length && /^\|?\s*:?-{2,}/.test(lines[i + 1])) {
      const cells = (row) => row.trim().replace(/^\||\|$/g, '').split('|').map((c) => inline(c.trim()));
      const headCells = cells(l);
      i += 2;
      const rows = [];
      while (i < lines.length && /^\|.*\|\s*$/.test(lines[i])) rows.push(cells(lines[i++]));
      out.push(`<table><thead><tr>${headCells.map((c) => `<th>${c}</th>`).join('')}</tr></thead><tbody>${
        rows.map((r) => `<tr>${r.map((c) => `<td>${c}</td>`).join('')}</tr>`).join('')}</tbody></table>`);
      continue;
    }
    if (/^\s*([-*+]|\d+\.)\s+/.test(l)) {
      const items = [];
      while (i < lines.length && /^\s*([-*+]|\d+\.)\s+/.test(lines[i])) {
        const m = lines[i].match(/^(\s*)([-*+]|\d+\.)\s+(.*)$/);
        items.push({ depth: Math.floor(m[1].replace(/\t/g, '  ').length / 2), ordered: /\d/.test(m[2]), text: m[3] });
        i += 1;
        while (i < lines.length && /^\s{2,}\S/.test(lines[i]) && !/^\s*([-*+]|\d+\.)\s+/.test(lines[i])) {
          items[items.length - 1].text += ` ${lines[i].trim()}`;
          i += 1;
        }
      }
      let html = '';
      const stack = [];
      for (const it of items) {
        while (stack.length && stack[stack.length - 1].depth > it.depth) html += `</li></${stack.pop().tag}>`;
        const top = stack[stack.length - 1];
        if (!top || top.depth < it.depth) {
          const tag = it.ordered ? 'ol' : 'ul';
          stack.push({ depth: it.depth, tag });
          html += `<${tag}><li>`;
        } else html += '</li><li>';
        const box = it.text.match(/^\[( |x)\]\s+(.*)$/i);
        html += box ? `${box[1].trim() ? '☑' : '☐'} ${inline(box[2])}` : inline(it.text);
      }
      while (stack.length) html += `</li></${stack.pop().tag}>`;
      out.push(html);
      continue;
    }
    if (/^>\s?/.test(l)) {
      const buf = [];
      while (i < lines.length && /^>\s?/.test(lines[i])) buf.push(lines[i++].replace(/^>\s?/, ''));
      out.push(`<blockquote>${md(buf.join('\n'))}</blockquote>`);
      continue;
    }
    const buf = [l];
    i += 1;
    while (i < lines.length && lines[i].trim() && !isBlockStart(lines[i])) buf.push(lines[i++]);
    const text = buf.map(inline).join('<br>');
    out.push(/^\s*⚠/.test(l) ? `<p class="warn">${text}</p>` : `<p>${text}</p>`);
  }
  return out.join('\n');
}
