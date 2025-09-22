// Copy share
function copyShare(){ const el=document.getElementById('share'); if(!el) return; el.select(); el.setSelectionRange(0, 99999); document.execCommand('copy'); alert('Lien copié !'); }

// Polling intervals
let _liveInterval=null;
function startLive(ms=1000){
  const live=document.getElementById('live'); if(!live) return;
  const eventId=live.dataset.event;
  async function refresh(){
    try{ const r=await fetch(`/events/api/${eventId}/status`); const data=await r.json(); applyStatus(data); updateStats(); }catch(e){ console.error(e); }
  }
  refresh(); if(_liveInterval) clearInterval(_liveInterval); _liveInterval=setInterval(refresh, ms);
}

let _verifyInterval=null;
function startVerifyLive(ms=1000){
  const box=document.getElementById('verify-live'); if(!box) return;
  const token=box.dataset.token;
  async function refresh(){
    try{ const r=await fetch(`/events/api/token/${token}/status`); const data=await r.json(); applyStatus(data); }catch(e){ console.error(e); }
  }
  refresh(); if(_verifyInterval) clearInterval(_verifyInterval); _verifyInterval=setInterval(refresh, ms);
}

// Presence
async function pingBusy(token, parentId){
  try{
    await fetch(`/events/api/token/${token}/presence`, {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({parent_id: parentId})});
  }catch(e){}
}

// Apply status
function applyStatus(data){
  // loaded parents
  Object.entries(data.loaded||{}).forEach(([pid, isLoaded])=>{
    const card=document.getElementById(`parent-${pid}`);
    if(card) card.classList.toggle('loaded', !!isLoaded);
  });
  // children verified + who + when
  const vmap=data.verifications||{};
  document.querySelectorAll('[data-item]').forEach(li=>{
    const id=li.getAttribute('data-item'); const info=vmap[id]; const cb=li.querySelector('input[type="checkbox"]'); const who=document.querySelector(`.who[data-who="${id}"]`); const when=document.querySelector(`.when[data-when="${id}"]`);
    const state=!!(info&&info.verified); if(cb) cb.checked=state; li.classList.toggle('ok',state);
    if(who) who.textContent=(info&&info.by)?info.by:'—';
    if(when && info && info.at){ const d=new Date(info.at); when.textContent=' • '+d.toLocaleTimeString(); }
  });
  // parents completion
  Object.entries(data.parents_complete||{}).forEach(([pid, complete])=>{
    const card=document.getElementById(`parent-${pid}`); if(card) card.classList.toggle('complete', !!complete);
  });
  // busy indicator
  if(data.busy){
    Object.entries(data.busy).forEach(([pid, names])=>{
      const el=document.getElementById(`busy-${pid}`); if(el) el.textContent = names.length? ('En vérification: '+names.join(', ')) : '';
    });
  }
}

// Stats header for admin view
function updateStats(){
  const stat=document.getElementById('stat-progress'); if(!stat) return;
  const parents=document.querySelectorAll('.parent-card');
  let total=0, complete=0; parents.forEach(p=>{ total++; if(p.classList.contains('complete')) complete++; });
  stat.textContent = `Parents complétés: ${complete}/${total}`;
}

// Filter on verify page
function applyFilter(){
  const q=(document.getElementById('filter').value||'').toLowerCase();
  document.querySelectorAll('#verify-live .child-name').forEach(el=>{
    const li=el.closest('li'); if(!li) return;
    li.style.display = el.textContent.toLowerCase().includes(q) ? '' : 'none';
  });
}

// API calls
async function markVerified(token, itemId, state){
  try{
    await fetch(`/events/api/${token}/verify`, {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({item_id:itemId, verified: !!state})});
  }catch(e){ console.error(e); }
}
async function toggleLoaded(eventId, itemId, loaded){
  try{
    const r = await fetch(`/events/api/${eventId}/load`, {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({item_id:itemId, loaded: !!loaded})});
    if(r.status===400){
      const data=await r.json(); if(data.error==='not_all_children_verified'){ alert("Impossible de marquer 'Chargé' tant que tous les enfants ne sont pas vérifiés."); }
    }
  }catch(e){ console.error(e); }
}
