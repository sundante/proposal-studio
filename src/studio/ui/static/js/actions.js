// Project and chat actions shared by the sidebar, the projects grid and the project page.
import { api, enc, loadLists } from './api.js';
import { copyText } from './dom.js';
import { go, shortPath, state } from './state.js';
import { confirmDialog, popMenu, promptDialog, toast } from './ui/overlay.js';

export async function newChat(projectId) {
  try {
    const chat = await api('POST', `/api/projects/${enc(projectId)}/chats`);
    await loadLists();
    go(`#/chat/${chat.id}`);
  } catch (e) { toast(e.message); }
}

export async function revealProject(p) {
  try { await api('POST', `/api/projects/${enc(p.id)}/reveal`); } catch (e) { toast(e.message); }
}

export async function copyPath(path) {
  toast((await copyText(path)) ? 'Folder path copied' : path, { ms: 6000 });
}

export async function renameProject(p) {
  const title = await promptDialog({ title: 'Rename project', label: 'Project name', value: p.title, confirm: 'Rename' });
  if (!title || title === p.title) return;
  try {
    await api('PATCH', `/api/projects/${enc(p.id)}`, { title });
    await loadLists();
    if (state.project?.id === p.id) state.project.title = title;
    go(location.hash || '#/');
  } catch (e) { toast(e.message); }
}

export async function removeProject(p, deleteFiles) {
  const ok = await confirmDialog(deleteFiles ? {
    title: `Delete “${p.title}”?`,
    message: 'This permanently deletes the project folder and everything in it: uploaded files, chats, summaries and decks.',
    detail: p.path, confirm: 'Delete project and folder', danger: true,
  } : {
    title: `Remove “${p.title}” from the list?`,
    message: 'The folder and its files stay on your computer. You can add it back later with New project → Change… → this folder.',
    detail: p.path, confirm: 'Remove from list',
  });
  if (!ok) return;
  try {
    await api('DELETE', `/api/projects/${enc(p.id)}${deleteFiles ? '?files=delete' : ''}`);
    toast(deleteFiles ? `Deleted “${p.title}”` : `Removed “${p.title}” — files kept in ${shortPath(p.path)}`, { ms: 5000 });
    if (state.project?.id === p.id) { state.project = null; state.chat = null; go('#/projects'); }
    await loadLists();
  } catch (e) { toast(e.message); }
}

export function projectMenu(p, anchor, { align = 'end' } = {}) {
  if (p.missing) {
    popMenu(anchor, [
      { heading: 'Folder not found' },
      { label: 'Remove from list', icon: 'x', run: () => removeProject(p, false) },
    ], { align });
    return;
  }
  popMenu(anchor, [
    { label: 'New chat', icon: 'plus', run: () => newChat(p.id) },
    { label: 'Rename', icon: 'edit', run: () => renameProject(p) },
    '-',
    { label: 'Open folder', icon: 'open', run: () => revealProject(p) },
    { label: 'Copy folder path', icon: 'copy', run: () => copyPath(p.path) },
    '-',
    { label: 'Remove from list', icon: 'x', sub: 'keeps files', run: () => removeProject(p, false) },
    { label: 'Delete project…', icon: 'trash', danger: true, run: () => removeProject(p, true) },
  ], { align });
}

export async function renameChat(c) {
  const title = await promptDialog({ title: 'Rename chat', label: 'Chat name', value: c.title, confirm: 'Rename' });
  if (!title || title === c.title) return;
  try {
    await api('PATCH', `/api/chats/${c.id}`, { title });
    if (state.chat?.id === c.id) state.chat.title = title;
    await loadLists();
    go(location.hash);
  } catch (e) { toast(e.message); }
}

export async function deleteChat(c) {
  const ok = await confirmDialog({ title: 'Delete this chat?', message: `“${c.title}” will be deleted. The project and its files stay.`, confirm: 'Delete chat', danger: true });
  if (!ok) return;
  try {
    await api('DELETE', `/api/chats/${c.id}`);
    await loadLists();
    if (state.chat?.id === c.id) { state.chat = null; go(c.project ? `#/project/${c.project}` : '#/'); }
    toast('Chat deleted');
  } catch (e) { toast(e.message); }
}

export function chatMenu(c, anchor, { align = 'end' } = {}) {
  popMenu(anchor, [
    { label: 'Rename', icon: 'edit', run: () => renameChat(c) },
    { label: 'Delete chat', icon: 'trash', danger: true, run: () => deleteChat(c) },
  ], { align });
}
