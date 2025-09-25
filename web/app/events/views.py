{% extends "base.html" %}
{% from "base.html" import icon %}
{% set title = "Événement" %}
{% block content %}
  <div class="grid cols-2">
    <div class="card">
      <div class="row">
        <div class="title">{{ event.name }}</div>
        <span class="badge" id="status-badge">Statut : {{ event.status if event.status is string else event.status.name }}</span>
      </div>
      <div class="muted">Date : {{ event.date or "—" }}</div>
      <div class="row" style="margin-top:10px;">
        <button class="btn primary" id="btn-share">Générer un lien pour les secouristes</button>
        <button class="btn" id="btn-close">Clôturer l'événement</button>
      </div>
    </div>
    <div class="card">
      <div class="title">Progression</div>
      <div class="progress" style="margin-top:8px;"><div id="progress-bar" style="width:0%"></div></div>
      <div class="muted" id="progress-text" style="margin-top:6px;">0 / 0 vérifiés</div>
    </div>
  </div>

  <div class="card" style="margin-top:12px;">
    <div class="title">Matériel à vérifier</div>
    <div id="tree" class="tree" style="margin-top:10px;">
      <!-- Le backend injecte {{ tree|tojson }} sous forme de liste de racines avec enfants -->
    </div>
  </div>

  <script>
    const EVENT_ID = {{ event.id }};
    const TREE = {{ tree|tojson }}; // [{id,name,level,type,quantity,children:[...]}]

    // Forcer WebSocket pour éviter les problèmes de transport
    const socket = io({ transports: ['websocket'] });
    socket.emit("join_event", {event_id: EVENT_ID});

    function el(tag, attrs={}, ...children){
      const e = document.createElement(tag);
      for(const [k,v] of Object.entries(attrs)){
        if(k==="class") e.className = v;
        else if(k.startsWith("on") && typeof v==="function") e.addEventListener(k.slice(2), v);
        else if(k==="html") e.innerHTML = v;
        else e.setAttribute(k,v);
      }
      for(const c of children){ if(c!=null) e.append(c.nodeType?c:document.createTextNode(c)); }
      return e;
    }

    function renderTree(root) {
      const group = root.type === "GROUP";
      const nodeEl = el("div", {class:"node", id:"node-"+root.id},
        el("div", {class:"header"},
          el("div", {class:"name"}, root.name),
          group
            ? el("label", {class:"check"},
                el("input", {type:"checkbox", id:"charged-"+root.id, onchange: e => setCharged(root.id, e.target.checked)}),
                el("span", null, "Chargé dans le véhicule")
              )
            : el("span", {class:"qty"}, `Qté: ${root.quantity ?? 0}`)
        ),
        el("div", {class:"childs"},
          ...root.children.map(renderTree),
          ...(!group ? [renderItemActions(root)] : [])
        )
      );
      return nodeEl;
    }

    function renderItemActions(item) {
      const wrap = el("div", {class:"item"},
        el("div", null, el("span", {class:"muted"}, "Vérification")),
        el("div", {class:"row"},
          el("input", {type:"text", placeholder:"Nom & prénom", id:"name-"+item.id}),
          el("button", {class:"btn", onclick: () => verifyItem(item.id, "OK")}, "OK"),
          el("button", {class:"btn ghost", onclick: () => verifyItem(item.id, "NOT_OK")}, "Non conforme"),
        )
      );
      return wrap;
    }

    function flattenItems(nodes) {
      const out = [];
      (function rec(n){
        if(n.type==="ITEM") out.push(n.id);
        (n.children||[]).forEach(rec);
      })( {children: nodes} );
      return out;
    }

    const totalItems = flattenItems(TREE).length;
    let okCount = 0;

    function setProgress(ok){
      const pct = totalItems ? Math.min(100, Math.round(ok/totalItems*100)) : 0;
      document.getElementById("progress-bar").style.width = pct + "%";
      document.getElementById("progress-text").textContent = `${ok} / ${totalItems} vérifiés`;
    }

    function recomputeProgressInitial(){
      // Si tu as un endpoint de stats, remplace par un fetch et renseigne okCount initial.
      // Ici on part à 0 et on incremente en live via socket.
      setProgress(okCount);
    }

    function setCharged(nodeId, checked){
      fetch(`/events/${EVENT_ID}/parent-status`, {
        method:"POST", headers:{"Content-Type":"application/json"}, credentials:"include",
        body: JSON.stringify({node_id: nodeId, charged_vehicle: checked})
      }).catch(()=>{});
    }

    function verifyItem(nodeId, status){
      const name = document.getElementById("name-"+nodeId).value.trim();
      if(!name){ alert("Merci de renseigner votre nom et prénom"); return; }
      fetch(`/events/${EVENT_ID}/verify`, {
        method:"POST", headers:{"Content-Type":"application/json"}, credentials:"include",
        body: JSON.stringify({node_id: nodeId, status, verifier_name: name})
      }).then(async r=>{
        if(!r.ok){ const t = await r.text().catch(()=> ""); alert(t||"Erreur"); }
      }).catch(()=>{});
    }

    function buildUI(){
      const treeEl = document.getElementById("tree");
      treeEl.innerHTML = "";
      TREE.forEach(root => treeEl.appendChild(renderTree(root)));
      recomputeProgressInitial();
    }
    buildUI();

    // Live updates depuis le serveur
    socket.on("event_update", (payload) => {
      if(payload && payload.type === "item_verified"){
        okCount = Math.max(0, okCount + 1); // NOTE: simpliste; pour du distinct, tenir un Set de node_ids OK
        setProgress(okCount);
      }
      if(payload && payload.type === "event_closed"){
        document.getElementById("status-badge").textContent = "Statut : CLOSED";
      }
    });

    // Actions haut de page
    document.getElementById("btn-share").addEventListener("click", () => {
      fetch(`/events/${EVENT_ID}/share-link`, {method:"POST", credentials:"include"})
      .then(r=>r.json()).then(res=>{
        if(res.url){
          const absolute = res.url.startsWith("http") ? res.url : (location.origin + res.url);
          navigator.clipboard.writeText(absolute).catch(()=>{});
          alert("Lien copié : " + absolute);
        } else {
          alert("Lien généré.");
        }
      }).catch(()=>{});
    });

    document.getElementById("btn-close").addEventListener("click", () => {
      fetch(`/events/${EVENT_ID}/status`, {
        method:"PATCH",
        headers:{"Content-Type":"application/json"},
        credentials:"include",
        body: JSON.stringify({status:"CLOSED"})
      }).then(()=> location.reload()).catch(()=>{});
    });
  </script>
{% endblock %}
