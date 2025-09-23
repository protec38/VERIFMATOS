
let currentEventId = null;
let socket = null;

async function loadEvents(){
  const res = await fetch('/events/');
  const list = await res.json();
  const ul = document.getElementById('events-list');
  ul.innerHTML = list.map(e => `
    <li class="list-group-item list-group-item-action d-flex justify-content-between align-items-center" onclick="openEvent(${e.id})">
      <span>${e.title}</span>
      <span class="badge bg-dark">${e.status}</span>
    </li>
  `).join('');
}

async function openEvent(id){
  currentEventId = id;
  const res = await fetch('/events/'+id);
  const e = await res.json();
  document.getElementById('ev-title').textContent = e.title;
  document.getElementById('ev-status').textContent = e.status;
  document.getElementById('ev-meta').textContent = `${e.location || ''} ${e.date || ''}`;
  await loadItems();
  await loadLogs();
  connectSocket();
}

async function loadItems(){
  const res = await fetch(`/events/${currentEventId}/items`);
  const tree = await res.json();
  document.getElementById('items-tree').innerHTML = renderNodes(tree);
  bindChecks();
}

async function loadLogs(){
  const res = await fetch(`/events/${currentEventId}/logs`);
  const logs = await res.json();
  const ul = document.getElementById('logs');
  ul.innerHTML = logs.map(l => `<li class="list-group-item">${l.created_at} — <code>${l.action}</code> node=${l.node_id ?? ''}</li>`).join('');
}

function renderNodes(nodes){
  return nodes.map(n => `
    <div class="border rounded-4 p-2 ${n.is_leaf && n.state==='checked' ? 'bg-success-subtle' : 'bg-white'}">
      <div class="d-flex align-items-center justify-content-between">
        <div><i class="fa-solid ${n.icon || 'fa-box'} me-2"></i>${n.name}</div>
        <div>
          ${n.is_leaf && n.included ? `
            <div class="form-check form-switch m-0">
              <input class="form-check-input js-check" type="checkbox" data-node-id="${n.id}" ${n.state==='checked'?'checked':''}>
            </div>` : ''}
        </div>
      </div>
      ${n.children ? `<div class="ms-3 mt-2 vstack gap-2">${renderNodes(n.children)}</div>` : ''}
    </div>
  `).join('');
}

function bindChecks(){
  document.querySelectorAll('.js-check').forEach(el => {
    el.addEventListener('change', async (e) => {
      const nodeId = e.target.getAttribute('data-node-id');
      const checked = e.target.checked;
      await fetch(`/events/${currentEventId}/items/${nodeId}/check`, {
        method: 'POST',
        headers: {'Content-Type':'application/json','X-CSRFToken': window.CSRF_TOKEN },
        body: JSON.stringify({ checked })
      });
    });
  });
}

function connectSocket(){
  if (socket) socket.disconnect();
  socket = io();
  socket.emit('join_event', { event_id: currentEventId });
  setInterval(() => socket.emit('presence:ping', { event_id: currentEventId }), 5000);

  socket.on('item:checked', (payload) => {
    // naive refresh for V1
    if (payload && payload.node_id) loadItems();
  });
  socket.on('presence:update', (_) => {
    // In V1, just indicate someone is active
    document.getElementById('presence').innerHTML = '<span class="badge bg-primary rounded-pill">En ligne</span>';
  });
  socket.on('event:status_changed', (p) => {
    document.getElementById('ev-status').textContent = p.status;
  });
}

document.addEventListener('DOMContentLoaded', loadEvents);
