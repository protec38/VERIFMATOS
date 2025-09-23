(function(){
  const tokenTag = document.querySelector('meta[name="csrf-token"]');
  const CSRF = tokenTag ? tokenTag.getAttribute('content') : '';

  // Live Socket.IO
  const socket = io();

  // Join event room if present
  if (window.EVENT_ID) {
    socket.emit('join', {room: 'event_' + window.EVENT_ID});
  }

  // Listen for item updates
  socket.on('item_update', (payload) => {
    // Update table if present
    const row = document.querySelector(`tr[data-item="${payload.item_id}"]`);
    if (row) {
      const stateTd = row.querySelector('.state');
      if (payload.state === 'checked') {
        stateTd.innerHTML = '<span class="badge text-bg-success">OK</span>';
        row.querySelector('td:last-child').innerHTML = '<button class="btn btn-sm btn-outline-secondary do-uncheck">Annuler</button>';
      } else {
        stateTd.innerHTML = '<span class="badge text-bg-secondary">En attente</span>';
        row.querySelector('td:last-child').innerHTML = '<button class="btn btn-sm btn-success do-check">Cocher</button>';
      }
    }
    // Log area for join page
    const live = document.getElementById('live-area');
    if (live) {
      const div = document.createElement('div');
      div.textContent = `Item #${payload.item_id} → ${payload.state} par ${payload.checked_by || '—'}`;
      live.prepend(div);
    }
  });

  // Click handlers for check/uncheck
  document.addEventListener('click', async (e) => {
    const btnCheck = e.target.closest('.do-check');
    const btnUn = e.target.closest('.do-uncheck');
    if (btnCheck || btnUn) {
      const tr = e.target.closest('tr[data-item]');
      const itemId = tr.getAttribute('data-item');
      const state = btnCheck ? 'checked' : 'pending';
      const eventId = document.getElementById('check-table')?.dataset.event;
      const res = await fetch(`/inventory/event/${eventId}/check`, {
        method: 'POST',
        headers: {'Content-Type': 'application/x-www-form-urlencoded'},
        body: new URLSearchParams({ item_id: itemId, state, 'csrf_token': CSRF })
      });
      if (!res.ok) alert('Erreur réseau');
    }
  });

  // Server tells us which room to join (fallback)
  socket.on('join_room', (room) => socket.emit('join', {room}));

  // Server-side handlers (namespace root)
  socket.on('connect', () => {
    // no-op
  });
})();
