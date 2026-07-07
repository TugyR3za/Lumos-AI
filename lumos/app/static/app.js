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

let conversationId = localStorage.getItem('lumosConversationId');
let busy = false;

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
    const heading = source.kind === 'web' && /^https?:\/\//.test(source.location)
      ? Object.assign(document.createElement('a'), { href: source.location, target: '_blank', rel: 'noreferrer', textContent: source.title })
      : Object.assign(document.createElement('strong'), { textContent: `${source.title} · ${source.location}` });
    const snippet = document.createElement('p');
    snippet.textContent = source.snippet;
    card.append(heading, snippet);
    sourcesEl.appendChild(card);
  }

  messagesEl.appendChild(node);
  window.scrollTo({ top: document.body.scrollHeight, behavior: 'smooth' });
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

async function refreshHealth() {
  try {
    const response = await fetch('/api/health');
    const data = await response.json();
    const rows = [];
    for (const [name, status] of Object.entries(data.providers)) {
      const state = status.available ? 'ok' : (status.configured ? 'bad' : 'off');
      const label = status.configured ? `${name}: ${status.model}` : `${name}: not configured`;
      rows.push(`<div><span class="dot ${state}"></span>${label}</div>`);
    }
    const webState = data.web_search.available ? 'ok' : 'off';
    rows.push(`<div><span class="dot ${webState}"></span>web: ${data.web_search.provider}</div>`);
    runtimeStatus.innerHTML = rows.join('');
  } catch (_) {
    runtimeStatus.innerHTML = '<div><span class="dot bad"></span>API unavailable</div>';
  }
}

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
refreshHealth();
loadConversation();
input.focus();
