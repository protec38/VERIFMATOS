// Helpers
function qs(sel, root=document){ return root.querySelector(sel); }
function qsa(sel, root=document){ return Array.from(root.querySelectorAll(sel)); }

function formatWhen(iso){
  if(!iso) return '';
  try{
    const d = new Date(iso);
    const pad = n => String(n).padStart(2,'0');
    return `— ${pad(d.getDate())}/${pad(d.getMonth()+1)} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
  }catch(e){ return ''; }
}

// applyStatus
function applyStatus(status){
  if(!status) return;

  // enfants
  const verifs = status.verifications || {};
  Object.keys(verifs).forEach(k=>{
    const childId = parseInt(k);
    const v = verifs[k] || {};
    const li = qs(`li.child-row[data-item="${childId}"]`);
    if(!li) return;

    const cb = li.querySelector('input[type="checkbox"]');
    if(cb){ cb.checked = !!v.verified; }

    li.classList.toggle('ok', !!v.verified);

    const who = qs(`.who[data-who="${childId}"]`);
    const when = qs(`.when[data-when="${childId}"]`);
    if(who){ who.textContent = v.by ? v.by : '—'; }
    if(when){ when.textContent = v.at ? formatWhen(v.at) : ''; }
  });

  // parents
  const parentsComplete = status.parents_complete || {};
  const loaded = status.loaded || {};
  Object.keys(parentsComplete).forEach(pidStr=>{
    const pid = parseInt(pidStr);
    const card = qs(`.parent-card[data-parent="${pid}"], #parent-${pid}`);
    if(!card) return;

    card.classList.toggle('complete', !!parentsComplete[pid]);

    const cbLoaded = qs(`input[data-loaded-for="${pid}"]`);
    if(cbLoaded){
      const isLoaded = !!loaded[pid];
      cbLoaded.checked = isLoaded;
    }

    const busyDiv = qs(`#busy-${pid}`);
    if(busyDiv){
      const list = status.busy && status.busy[pid] ? status.busy[pid] : [];
      if(list.length){
        busyDiv.innerHTML = `<i class="fa-solid fa-user-group"></i> En cours : ${list.join(', ')}`;
      }else{
        busyDiv.textContent = '';
      }
    }
  });
}

// polling verify
let _verifyTimer = null;
function startVerifyLive(intervalMs=1000){
  const root = qs('#verify-live');
  if(!root) return;
  const token = root.dataset.token;
  if(!token) return;
  const tick = async ()=>{
    try{
      const r = await fetch(`/events/api/token/${token}/status`, {cache: 'no-store'});
      if(!r.ok) return;
      const data = await r.json();
      applyStatus(data);
    }catch(e){}
  };
  tick();
  if(_verifyTimer) clearInterval(_verifyTimer);
  _verifyTimer = setInterval(tick, intervalMs);
}

// polling admin
let _adminTimer = null;
function startLive(intervalMs=1000){
  const root = qs('#live');
  if(!root) return;
  const eventId = root.dataset.event;
  if(!eventId) return;
  const tick = async ()=>{
    try{
      const r = await fetch(`/events/api/${eventId}/status`, {cache:'no-store'});
      if(!r.ok) return;
      const data = await r.json();
      applyStatus(data);
    }catch(e){}
  };
  tick();
  if(_adminTimer) clearInterval(_adminTimer);
  _adminTimer = setInterval(tick, intervalMs);
}

// actions
async function markVerified(token, itemId, state){
  try{
    const r = await fetch(`/events/api/${token}/verify`, {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({ item_id: itemId, verified: !!state })
    });
    if(!r.ok){
      const data = await r.json().catch(()=>({}));
      if(data && data.error === 'auth'){
        alert("Session expirée. Revenez à l’écran d’accès et saisissez votre nom.");
      }else if(data && data.error){
        alert("Erreur: " + data.error);
      }else{
        alert("Erreur réseau.");
      }
    }
  }catch(e){
    alert("Erreur réseau.");
  }
}

async function toggleLoaded(eventId, parentId, state){
  try{
    const r = await fetch(`/events/api/${eventId}/load`, {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({ item_id: parentId, loaded: !!state })
    });
    if(!r.ok){
      const data = await r.json().catch(()=>({}));
      if(data && data.error === 'not_all_children_verified'){
        alert("Impossible de marquer 'Chargé' : tous les enfants de ce parent ne sont pas vérifiés.");
      }else if(data && data.error){
        alert("Erreur: " + data.error);
      }else{
        alert("Erreur réseau.");
      }
      const cb = qs(`input[data-loaded-for="${parentId}"]`);
      if(cb){ cb.checked = !state; }
    }
  }catch(e){
    const cb = qs(`input[data-loaded-for="${parentId}"]`);
    if(cb){ cb.checked = !state; }
    alert("Erreur réseau.");
  }
}

// partage
async function copyShare(){
  const el = document.getElementById('share');
  if(!el) return;
  const text = el.value || el.placeholder || '';
  try{
    if(navigator.clipboard && window.isSecureContext){
      await navigator.clipboard.writeText(text);
    }else{
      el.select(); el.setSelectionRange(0, 99999);
      document.execCommand('copy');
    }
    alert('Lien copié !');
  }catch(e){
    alert("Impossible de copier automatiquement.");
  }
}

window.startVerifyLive = startVerifyLive;
window.startLive = startLive;
window.markVerified = markVerified;
window.toggleLoaded = toggleLoaded;
window.copyShare = copyShare;
