
async function load(parent_id){
  const q = parent_id ? ('?parent_id='+parent_id) : '';
  const res = await fetch('/inventory/'+q);
  const nodes = await res.json();
  const root = document.getElementById('tree');
  root.innerHTML = nodes.map(renderNode).join('');
}
function renderNode(n){
  return `
    <div class="border rounded-4 p-2 bg-white">
      <div class="d-flex align-items-center justify-content-between">
        <div>
          <i class="fa-solid ${n.icon || 'fa-box'} me-2"></i>
          <strong>${n.name}</strong>
          ${n.is_leaf ? `<span class="badge bg-secondary ms-2">x${n.expected_qty ?? '-'}</span>` : ''}
        </div>
        <div class="btn-group btn-group-sm">
          <button class="btn btn-outline-secondary" onclick="editNode(${n.id})"><i class="fa-solid fa-pen"></i></button>
          <button class="btn btn-outline-danger" onclick="delNode(${n.id})"><i class="fa-solid fa-trash"></i></button>
        </div>
      </div>
    </div>
  `;
}
async function delNode(id){
  if (!confirm('Supprimer ce nœud ?')) return;
  const res = await fetch('/inventory/'+id, { method: 'DELETE', headers: {'X-CSRFToken': window.CSRF_TOKEN } });
  if (res.ok) load(); else alert('Erreur suppression');
}
document.addEventListener('DOMContentLoaded', () => load());
