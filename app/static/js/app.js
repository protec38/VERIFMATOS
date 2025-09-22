// Copy link
function copyShare(){
  const el = document.getElementById('share');
  if(!el) return;
  el.select(); el.setSelectionRange(0, 99999);
  document.execCommand('copy');
  alert('Lien copié !');
}

// API calls
async function markVerified(token, itemId, state){
  try{
    await fetch(`/events/api/${token}/verify`, {
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({item_id:itemId, verified: !!state})
    });
  }catch(e){ console.error(e); }
}

async function toggleLoaded(eventId, itemId, loaded){
  try{
    await fetch(`/events/api/${eventId}/load`, {
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({item_id:itemId, loaded:!!loaded})
    });
  }catch(e){ console.error(e); }
}

// Admin/Chef live (by event id)
function startLive(){
  const live = document.getElementById('live');
  if(!live) return;
  const eventId = live.dataset.event;
  async function refresh(){
    try{
      const r = await fetch(`/events/api/${eventId}/status`);
      const data = await r.json();
      applyStatus(data);
    }catch(e){ console.error(e); }
  }
  refresh();
  setInterval(refresh, 2000);
}

// Secouriste live (by token)
function startVerifyLive(){
  const box = document.getElementById('verify-live');
  if(!box) return;
  const token = box.dataset.token;
  async function refresh(){
    try{
      const r = await fetch(`/events/api/token/${token}/status`);
      const data = await r.json();
      applyStatus(data);
    }catch(e){ console.error(e); }
  }
  refresh();
  setInterval(refresh, 2000);
}

// Apply status to any page (admin detail or volunteer verify)
function applyStatus(data){
  // mark loaded parents
  Object.entries(data.loaded || {}).forEach(([pid, isLoaded]) => {
    const card = document.getElementById(`parent-${pid}`);
    if(card) card.classList.toggle('loaded', !!isLoaded);
  });
  // children verified + who
  const vmap = data.verifications || {};
  document.querySelectorAll('[data-item]').forEach(li => {
    const id = li.getAttribute('data-item');
    const info = vmap[id];
    const cb = li.querySelector('input[type="checkbox"]');
    const who = document.querySelector(`.who[data-who="${id}"]`);
    const state = !!(info && info.verified);
    if(cb) cb.checked = state;
    li.classList.toggle('ok', state);
    if(who) who.textContent = (info && info.by) ? info.by : '—';
  });
  // parents completion
  Object.entries(data.parents_complete || {}).forEach(([pid, complete]) => {
    const card = document.getElementById(`parent-${pid}`);
    if(card) card.classList.toggle('complete', !!complete);
  });
  // history
  const hist = document.getElementById('history');
  if(hist){
    hist.innerHTML = '';
    (data.history || []).forEach(h => {
      const d = new Date(h.at);
      const li = document.createElement('li');
      li.textContent = `${h.actor} → ${h.action.toUpperCase()} ${h.item_id || ''} à ${d.toLocaleTimeString()}`;
      hist.appendChild(li);
    });
  }
}
