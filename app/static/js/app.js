// Basic helpers for copy/share + live updates + AJAX verification
function copyShare(){
  const el = document.getElementById('share');
  el.select(); el.setSelectionRange(0, 99999);
  document.execCommand('copy');
  alert('Lien copié !');
}

async function markVerified(token, itemId){
  try{
    await fetch(`/events/api/${token}/verify`, {
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({item_id:itemId})
    });
  }catch(e){ console.error(e); }
}

async function toggleLoaded(eventId, itemId, loaded){
  try{
    await fetch(`/events/api/${eventId}/load`, {
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({item_id:itemId, loaded:loaded})
    });
  }catch(e){ console.error(e); }
}

function startLive(){
  const live = document.getElementById('live');
  if(!live) return;
  const eventId = live.dataset.event;
  async function refresh(){
    try{
      const r = await fetch(`/events/api/${eventId}/status`);
      const data = await r.json();
      // Update child checkboxes
      Object.keys(data.loaded).forEach(pid => {
        const card = document.getElementById(`parent-${pid}`);
        // skip; loaded state is reflected by the toggle (not persisted visually after reload).
      });
      const verified = new Set(data.verified);
      document.querySelectorAll('ul[id^="children-"] li').forEach(li => {
        const id = parseInt(li.dataset.item);
        const cb = li.querySelector('input[type="checkbox"]');
        if(verified.has(id)){
          cb.checked = true;
        }
      });
      // History
      const hist = document.getElementById('history');
      hist.innerHTML = '';
      data.verifications.slice().reverse().forEach(v => {
        const d = new Date(v.at);
        const li = document.createElement('li');
        li.textContent = `#${v.item_id} vérifié par ${v.by} à ${d.toLocaleTimeString()}`;
        hist.appendChild(li);
      });
    }catch(e){ console.error(e); }
  }
  refresh();
  setInterval(refresh, 2500); // "AJAX" refresh every 2.5s
}
