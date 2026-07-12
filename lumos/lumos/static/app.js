const messagesEl = document.querySelector('#messages');
const emptyState = document.querySelector('#emptyState');
const form = document.querySelector('#composer');
const input = document.querySelector('#messageInput');
const sendButton = document.querySelector('#sendButton');
const requestState = document.querySelector('#requestState');
const routeSelect = document.querySelector('#routeSelect');
const notesToggle = document.querySelector('#notesToggle');
const webToggle = document.querySelector('#webToggle');
const modelBadge = document.querySelector('#modelBadge');
const runtimeStatus = document.querySelector('#runtimeStatus');
const conversationTitle = document.querySelector('#conversationTitle');
const graphToggle = document.querySelector('#openGraph');
const graphDrawer = document.querySelector('#graphDrawer');
const graphBody = document.querySelector('#graphBody');
const graphCounts = document.querySelector('#graphCounts');
const graphBack = document.querySelector('#graphBack');
const graphSearchForm = document.querySelector('#graphSearch');
const graphQuery = document.querySelector('#graphQuery');

let conversationId = localStorage.getItem('lumosConversationId');
let busy = false;
// Filled in by /api/health. Until it answers, the graph affordances stay out of
// the way: a note is only offered as a doorway into a graph that can be read.
let graphStatus = { enabled: false, nodes: 0, edges: 0, detail: null };

function setBusy(value, label = '') {
  busy = value;
  sendButton.disabled = value;
  input.disabled = value;
  requestState.textContent = label;
}

function resizeInput() {
  input.style.height = 'auto';
  input.style.height = `${Math.min(input.scrollHeight, 190)}px`;
}

function clearConversation() {
  conversationId = null;
  localStorage.removeItem('lumosConversationId');
  messagesEl.innerHTML = '';
  messagesEl.appendChild(emptyState);
  emptyState.hidden = false;
  conversationTitle.textContent = 'New conversation';
  modelBadge.textContent = 'No model used yet';
  input.focus();
}

function addMessage(role, content, options = {}) {
  if (emptyState?.isConnected) emptyState.remove();
  const template = document.querySelector('#messageTemplate');
  const node = template.content.firstElementChild.cloneNode(true);
  node.classList.add(role);
  if (options.error) node.classList.add('error');
  node.querySelector('.avatar').textContent = role === 'user' ? 'YOU' : 'L';
  node.querySelector('.message-header').textContent = role === 'user' ? 'You' : 'Lumos';
  node.querySelector('.message-content').textContent = content;

  const sourcesEl = node.querySelector('.sources');
  for (const source of options.sources || []) {
    const card = document.createElement('div');
    card.className = 'source-card';
    const heading = sourceHeading(source);
    const snippet = document.createElement('p');
    snippet.textContent = source.snippet;
    card.append(heading, snippet);
    sourcesEl.appendChild(card);
  }

  // Several cited notes are several seeds, which is the one question the graph
  // answers that a single note's neighbours do not: what do they all point at?
  const cited = [...new Set((options.sources || []).filter((item) => item.kind === 'note').map((item) => item.location))];
  if (graphStatus.enabled && cited.length > 1) {
    const button = Object.assign(document.createElement('button'), {
      type: 'button',
      className: 'pill-button',
      textContent: '◈ Related notes',
      title: 'Notes one link away from the ones this answer cited',
    });
    button.addEventListener('click', () => openDrawer({ kind: 'graph', paths: cited }));
    sourcesEl.appendChild(button);
  }

  messagesEl.appendChild(node);
  window.scrollTo({ top: document.body.scrollHeight, behavior: 'smooth' });
}

function sourceHeading(source) {
  if (source.kind === 'web' && /^https?:\/\//.test(source.location)) {
    return Object.assign(document.createElement('a'), { href: source.location, target: '_blank', rel: 'noreferrer', textContent: source.title });
  }
  const label = `${source.title} · ${source.location}`;
  if (source.kind !== 'note' || !graphStatus.enabled) {
    return Object.assign(document.createElement('strong'), { textContent: label });
  }
  const button = Object.assign(document.createElement('button'), {
    type: 'button',
    className: 'source-open',
    textContent: label,
    title: 'Open this note in the graph',
  });
  button.addEventListener('click', () => openDrawer(noteView(source.location)));
  return button;
}

async function sendMessage(text) {
  if (busy || !text.trim()) return;
  const message = text.trim();
  addMessage('user', message);
  input.value = '';
  resizeInput();
  setBusy(true, 'Thinking…');

  try {
    const response = await fetch('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        message,
        conversation_id: conversationId,
        route: routeSelect.value,
        use_notes: notesToggle.checked,
        use_web: webToggle.checked,
      }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || 'The request failed.');

    conversationId = data.conversation_id;
    localStorage.setItem('lumosConversationId', conversationId);
    conversationTitle.textContent = message.length > 48 ? `${message.slice(0, 48)}…` : message;
    modelBadge.textContent = `${data.provider} · ${data.model}`;
    addMessage('assistant', data.answer, { sources: data.sources });
  } catch (error) {
    addMessage('assistant', error.message, { error: true });
  } finally {
    setBusy(false, '');
    input.focus();
  }
}

async function loadConversation() {
  if (!conversationId) return;
  try {
    const response = await fetch(`/api/conversations/${encodeURIComponent(conversationId)}`);
    if (!response.ok) return;
    const data = await response.json();
    if (!data.messages.length) return;
    if (emptyState?.isConnected) emptyState.remove();
    for (const message of data.messages) addMessage(message.role, message.content);
    const firstUser = data.messages.find((item) => item.role === 'user');
    if (firstUser) conversationTitle.textContent = firstUser.content.slice(0, 48);
    const lastAssistant = [...data.messages].reverse().find((item) => item.role === 'assistant');
    if (lastAssistant?.provider) modelBadge.textContent = `${lastAssistant.provider} · ${lastAssistant.model}`;
  } catch (_) {
    // Starting with an empty screen is safer than blocking the UI on history failure.
  }
}

function escapeHtml(text) {
  return String(text).replace(/[&<>"']/g, (ch) => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]
  ));
}

const DOT_BY_STATE = {
  available: 'ok',
  reachable: 'warn',
  auth_failed: 'warn',
  unreachable: 'bad',
  error: 'bad',
  not_configured: 'off',
};
const STATE_NOTES = {
  reachable: 'key unverified',
  auth_failed: 'auth failed',
  unreachable: 'unreachable',
  error: 'error',
};

async function refreshHealth() {
  try {
    const response = await fetch('/api/health');
    const data = await response.json();
    const rows = [];
    for (const [name, status] of Object.entries(data.providers)) {
      const dot = DOT_BY_STATE[status.state] || (status.configured ? 'bad' : 'off');
      let label = `${name}: not configured`;
      if (status.configured) {
        label = `${name}: ${status.provider} · ${status.model}`;
        if (STATE_NOTES[status.state]) label += ` · ${STATE_NOTES[status.state]}`;
      }
      const title = status.detail ? ` title="${escapeHtml(status.detail)}"` : '';
      rows.push(`<div${title}><span class="dot ${dot}"></span>${escapeHtml(label)}</div>`);
    }
    const webState = data.web_search.available ? 'ok' : 'off';
    rows.push(`<div><span class="dot ${webState}"></span>web: ${escapeHtml(data.web_search.provider)}</div>`);

    graphStatus = data.graph;
    graphCounts.textContent = `${data.graph.nodes} nodes · ${data.graph.edges} edges`;
    // Ingest writes the graph either way, so the counts stand even when reads
    // are off; the dot and the tooltip are what say whether anything reads them.
    const graphLabel = `graph: ${data.graph.nodes} nodes · ${data.graph.edges} edges`;
    const graphTitle = data.graph.detail ? ` title="${escapeHtml(data.graph.detail)}"` : '';
    rows.push(`<div${graphTitle}><span class="dot ${data.graph.enabled ? 'ok' : 'off'}"></span>${escapeHtml(graphLabel)}${data.graph.enabled ? '' : ' · reads off'}</div>`);

    runtimeStatus.innerHTML = rows.join('');
  } catch (_) {
    runtimeStatus.innerHTML = '<div><span class="dot bad"></span>API unavailable</div>';
  }
}

// --- Graph -----------------------------------------------------------------
// A view over GET /api/graph and nothing else: a centre node, the nodes one
// edge away, and — when several notes are the seed — what they link to. It only
// reads the graph, so no prompt, model, or retrieval behaviour changes here.

// The rel/direction pairs the API can return, in the order they read best.
const NEIGHBOR_LABELS = {
  'links_to:out': 'Links to',
  'links_to:in': 'Backlinks',
  'tagged:out': 'Tags',
  'tagged:in': 'Tagged notes',
  'mentions:out': 'Mentions', // a [[target]] no note backs yet
  'mentions:in': 'Mentioned by',
};

// Notes travel by path — it is what search and the sources hand around, and it
// is what seeds `related`. Tags and entities back no file, so they go by slug.
const noteView = (path) => ({ kind: 'graph', paths: [path] });
const slugView = (slug) => ({ kind: 'graph', slug });

let currentView = null;
let viewHistory = [];
let renderToken = 0; // only the newest request may write into the drawer

function drawerNote(text) {
  const note = document.createElement('p');
  note.className = 'drawer-note';
  note.textContent = text;
  return note;
}

function graphGroup(label, items) {
  const group = document.createElement('section');
  group.className = 'graph-group';
  const heading = document.createElement('h3');
  heading.textContent = label;
  group.append(heading, ...items);
  return group;
}

function nodeButton(node, meta = null) {
  const button = document.createElement('button');
  button.type = 'button';
  button.className = 'graph-item';
  const title = document.createElement('strong');
  title.textContent = node.title;
  const where = document.createElement('span');
  where.textContent = node.path || node.slug;
  button.append(title, where);
  if (meta) {
    const count = document.createElement('span');
    count.className = 'count';
    count.textContent = meta;
    button.append(count);
  }
  button.addEventListener('click', () => showGraphView(node.path ? noteView(node.path) : slugView(node.slug)));
  return button;
}

function centreCard(node) {
  const card = document.createElement('div');
  card.className = 'graph-centre';
  const kind = document.createElement('span');
  kind.className = 'kind-badge';
  kind.textContent = node.kind;
  const title = document.createElement('h3');
  title.textContent = node.title;
  const where = document.createElement('p');
  where.textContent = node.path || node.slug;
  card.append(kind, title, where);
  return card;
}

function renderGraph(data, seeds) {
  const parts = [];
  if (data.detail) parts.push(drawerNote(data.detail)); // reads are off, or no such node
  if (data.node) parts.push(centreCard(data.node));

  const groups = new Map();
  for (const neighbor of data.neighbors) {
    const key = `${neighbor.rel}:${neighbor.direction}`;
    groups.set(key, [...(groups.get(key) || []), neighbor.node]);
  }
  for (const [key, label] of Object.entries(NEIGHBOR_LABELS)) {
    if (groups.has(key)) parts.push(graphGroup(label, groups.get(key).map((node) => nodeButton(node))));
  }
  if (data.node && !data.neighbors.length) parts.push(drawerNote('No links, tags, or mentions on this node yet.'));

  // With one seed, `related` is the notes already listed above under links and
  // backlinks. With several it is the answer's own expansion, ranked by how
  // many of the cited notes reach each one — which is worth its own section.
  if (data.enabled && seeds > 1) {
    const items = data.related.map((note) => {
      const button = nodeButton(note, `${note.connections} of ${seeds} sources`);
      button.title = `Linked with ${note.via.join(', ')}`;
      return button;
    });
    parts.push(items.length
      ? graphGroup('Related notes', items)
      : drawerNote('The notes this answer cited link nowhere else yet.'));
  }

  if (!parts.length) parts.push(drawerNote('Nothing to show for this node.'));
  graphBody.replaceChildren(...parts);
}

function renderSearch(query, notes) {
  if (!notes.length) {
    graphBody.replaceChildren(drawerNote(`No notes match “${query}”.`));
    return;
  }
  const items = notes.map((row) => nodeButton({ title: row.title, path: row.location }));
  graphBody.replaceChildren(graphGroup(`Notes matching “${query}”`, items));
}

function renderEmpty() {
  const parts = [];
  if (graphStatus.detail) parts.push(drawerNote(graphStatus.detail)); // why reads are off, in the server's words
  parts.push(drawerNote('Search for a note, or open one from an answer’s sources. Click any node to walk the graph from there.'));
  graphBody.replaceChildren(...parts);
}

async function fetchGraph(view) {
  const params = new URLSearchParams();
  if (view.slug) params.set('slug', view.slug);
  for (const path of view.paths || []) params.append('path', path);
  const response = await fetch(`/api/graph?${params}`);
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || 'The graph request failed.');
  return data;
}

async function searchGraphNotes(query) {
  const response = await fetch('/api/search/notes', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ query, limit: 10 }),
  });
  const data = await response.json();
  if (!response.ok) throw new Error('The note search failed.');
  const notes = new Map(); // search hits are chunks, and a note has many
  for (const row of data) if (!notes.has(row.location)) notes.set(row.location, row);
  return [...notes.values()];
}

async function showGraphView(view, { push = true } = {}) {
  if (push && currentView) viewHistory.push(currentView);
  currentView = view;
  graphBack.hidden = !viewHistory.length;

  const token = ++renderToken;
  try {
    if (view.kind === 'empty') {
      await healthReady; // the empty state is health's to explain
      if (token === renderToken) renderEmpty();
    } else if (view.kind === 'search') {
      const notes = await searchGraphNotes(view.query);
      if (token === renderToken) renderSearch(view.query, notes);
    } else {
      const data = await fetchGraph(view);
      if (token === renderToken) renderGraph(data, (view.paths || []).length);
    }
  } catch (error) {
    if (token === renderToken) graphBody.replaceChildren(drawerNote(error.message));
  }
}

function openDrawer(view) {
  const opening = graphDrawer.hidden;
  graphDrawer.hidden = false;
  document.body.classList.add('graph-open');
  graphToggle.setAttribute('aria-expanded', 'true');
  if (opening) {
    viewHistory = [];
    currentView = null;
  }
  showGraphView(view);
  if (opening) graphQuery.focus();
}

function closeDrawer() {
  graphDrawer.hidden = true;
  document.body.classList.remove('graph-open');
  graphToggle.setAttribute('aria-expanded', 'false');
}

graphToggle.addEventListener('click', () => {
  if (graphDrawer.hidden) openDrawer({ kind: 'empty' });
  else closeDrawer();
});
document.querySelector('#graphClose').addEventListener('click', closeDrawer);
graphBack.addEventListener('click', () => {
  const previous = viewHistory.pop();
  if (previous) showGraphView(previous, { push: false });
});
graphSearchForm.addEventListener('submit', (event) => {
  event.preventDefault();
  const query = graphQuery.value.trim();
  if (query) showGraphView({ kind: 'search', query });
});
document.addEventListener('keydown', (event) => {
  if (event.key === 'Escape' && !graphDrawer.hidden) closeDrawer();
});

form.addEventListener('submit', (event) => {
  event.preventDefault();
  sendMessage(input.value);
});
input.addEventListener('input', resizeInput);
input.addEventListener('keydown', (event) => {
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault();
    form.requestSubmit();
  }
});
document.querySelector('#newChat').addEventListener('click', clearConversation);
document.querySelector('#reindexNotes').addEventListener('click', async () => {
  setBusy(true, 'Indexing notes…');
  try {
    const response = await fetch('/api/notes/reindex', { method: 'POST' });
    const data = await response.json();
    requestState.textContent = `Indexed ${data.indexed} files / ${data.chunks} chunks`;
  } catch (_) {
    requestState.textContent = 'Reindex failed';
  } finally {
    setBusy(false, requestState.textContent);
    setTimeout(() => { requestState.textContent = ''; }, 3500);
  }
});
document.querySelectorAll('[data-prompt]').forEach((button) => {
  button.addEventListener('click', () => sendMessage(button.dataset.prompt));
});

resizeInput();
const healthReady = refreshHealth(); // the graph drawer waits on this to say why it is empty
loadConversation();
input.focus();
