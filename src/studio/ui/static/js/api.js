// JSON API client, uploads and the Server-Sent Events reader for chat replies.
import { emit, state } from './state.js';

/** Call the API. Writes carry X-Studio (the server requires it with the session cookie). */
export async function api(method, url, body) {
  const opts = { method, headers: { 'X-Studio': '1' } };
  if (body instanceof Blob) opts.body = body;
  else if (body !== undefined) {
    opts.headers['Content-Type'] = 'application/json';
    opts.body = JSON.stringify(body);
  }
  const res = await fetch(url, opts);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const err = new Error(data.error || `Request failed (${res.status})`);
    err.status = res.status;
    err.data = data;
    if (data.needs_login) emit('login');
    throw err;
  }
  return data;
}

export const enc = encodeURIComponent;

export async function loadLists() {
  [state.projects, state.recent] = await Promise.all([api('GET', '/api/projects'), api('GET', '/api/chats')]);
  emit('lists');
}

export async function uploadFile(projectId, file) {
  return api('PUT', `/api/projects/${enc(projectId)}/uploads/${enc(file.name)}`, file);
}

/**
 * POST a chat message and read the SSE reply.
 * handlers: { chunk(text), status(text), pending(cmd), done({outputs}), error(text), chat(summary) }
 */
export async function streamMessage(chatId, payload, handlers, signal) {
  const res = await fetch(`/api/chats/${chatId}/messages`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-Studio': '1' },
    body: JSON.stringify(payload),
    signal,
  });
  if (!res.ok || !res.body) {
    const data = await res.json().catch(() => ({}));
    if (data.needs_login) emit('login');
    throw new Error(data.error || `Request failed (${res.status})`);
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buf = '';
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    let cut;
    while ((cut = buf.indexOf('\n\n')) >= 0) {
      const block = buf.slice(0, cut);
      buf = buf.slice(cut + 2);
      const event = (block.match(/^event: (.*)$/m) || [])[1];
      const raw = (block.match(/^data: (.*)$/m) || [])[1];
      if (!event || raw === undefined) continue;
      const data = JSON.parse(raw);
      if (event === 'chunk') handlers.chunk?.(data.text);
      else handlers[event]?.(event === 'status' || event === 'error' ? data.text : event === 'pending' ? data.command : data);
    }
  }
}
