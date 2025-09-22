function copyShare(){
  let input = document.getElementById('share');
  input.select();
  input.setSelectionRange(0,99999);
  document.execCommand('copy');
  alert('Lien copié');
}

function startLive(){
  let live = document.getElementById('live');
  if(!live) return;
  let eventId = live.dataset.event;
  async function refresh(){
    let r = await fetch(`/events/api/${eventId}/status`);
    let data = await r.json();
    for(let pid in data.parents_complete){
      let card = document.getElementById('parent-'+pid);
      if(card){
        if(data.parents_complete[pid]) card.classList.add('complete');
        else card.classList.remove('complete');
      }
    }
    for(let iid in data.verifications){
      let v = data.verifications[iid];
      let li = document.querySelector(`[data-item="${iid}"] input`);
      if(li){ li.checked = v.verified; }
    }
    for(let pid in data.loaded){
      let card = document.getElementById('parent-'+pid);
      if(card){
        if(data.loaded[pid]) card.classList.add('loaded');
        else card.classList.remove('loaded');
      }
    }
    let hist = document.getElementById('history');
    if(hist){
      hist.innerHTML = '';
      data.history.forEach(h=>{
        let li = document.createElement('li');
        li.textContent = `[${h.at}] ${h.actor} → ${h.action} ${h.item_id}`;
        hist.appendChild(li);
      });
    }
  }
  setInterval(refresh, 2000);
  refresh();
}

async function markVerified(token, itemId, state){
  await fetch(`/events/api/${token}/verify`, {
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body: JSON.stringify({item_id:itemId, verified:state})
  });
}

async function toggleLoaded(eventId, itemId, state){
  await fetch(`/events/api/${eventId}/load`, {
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body: JSON.stringify({item_id:itemId, loaded:state})
  });
}
