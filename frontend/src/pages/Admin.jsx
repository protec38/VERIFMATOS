import React, { useEffect, useState } from 'react'
import { api } from '../api'

export default function Admin(){
  const token = localStorage.getItem('token')
  const [users, setUsers] = useState([])
  const [items, setItems] = useState([])
  const [form, setForm] = useState({ email:'', full_name:'', password:'', role:'CHEF' })
  const [itemForm, setItemForm] = useState({ name:'', description:'', type:'BULK', stock_qty:0, serial_number:'' })
  const [selectedKit, setSelectedKit] = useState('')
  const [recipe, setRecipe] = useState([]) // [{item_id, required_qty, name}]

  useEffect(()=>{ load() },[])
  async function load(){
    setUsers(await api('/admin/users', { token }))
    setItems(await api('/admin/items', { token }))
    setRecipe([]); setSelectedKit('')
  }
  async function createUser(e){
    e.preventDefault()
    await api('/admin/users', { method:'POST', token, json:form })
    setForm({ email:'', full_name:'', password:'', role:'CHEF' })
    await load()
  }
  async function updateUser(u){
    const full_name = prompt('Nom complet', u.full_name) ?? u.full_name
    await api(`/admin/users/${u.id}`, { method:'PUT', token, json:{ full_name } })
    await load()
  }
  async function deleteUser(u){
    if(!confirm('Supprimer ce compte ?')) return
    await api(`/admin/users/${u.id}`, { method:'DELETE', token })
    await load()
  }

  async function createItem(e){
    e.preventDefault()
    await api('/admin/items', { method:'POST', token, json:itemForm })
    setItemForm({ name:'', description:'', type:'BULK', stock_qty:0, serial_number:'' })
    await load()
  }
  async function editItem(i){
    const name = prompt('Nom', i.name) ?? i.name
    await api(`/admin/items/${i.id}`, { method:'PUT', token, json:{ name } })
    await load()
  }
  async function deleteItem(i){
    if(!confirm('Supprimer cet objet ?')) return
    await api(`/admin/items/${i.id}`, { method:'DELETE', token })
    await load()
  }

  async function openRecipe(kitId){
    setSelectedKit(kitId)
    const r = await api(`/admin/kits/${kitId}/recipe`, { token })
    setRecipe(r.components)
  }
  function addToRecipe(comp){
    const required_qty = +prompt('Quantité requise', 1) || 1
    setRecipe(prev => [...prev, { item_id: comp.id, name: comp.name, required_qty }])
  }
  async function saveRecipe(){
    await api(`/admin/kits/${selectedKit}/recipe`, { method:'POST', token, json:{ kit_id: selectedKit, items: recipe.map(r=>({ component_id:r.item_id, required_qty:r.required_qty })) } })
    alert('Recette enregistrée')
  }

  const kits = items.filter(i => i.type === 'KIT')
  const components = items.filter(i => i.type !== 'KIT')

  return (
    <div className="p-6 space-y-8">
      <header className="flex items-center gap-3">
        <img src="/logo.png" className="w-12" />
        <h1 className="text-3xl font-bold text-pcblue">Administration</h1>
      </header>

      <section className="grid lg:grid-cols-3 gap-6">
        <div className="card lg:col-span-1">
          <h2 className="font-semibold text-lg mb-4">Créer un compte</h2>
          <form className="grid gap-2" onSubmit={createUser}>
            <input className="border rounded p-2" placeholder="Email" value={form.email} onChange={e=>setForm({...form, email:e.target.value})} />
            <input className="border rounded p-2" placeholder="Nom complet" value={form.full_name} onChange={e=>setForm({...form, full_name:e.target.value})} />
            <input className="border rounded p-2" placeholder="Mot de passe" value={form.password} onChange={e=>setForm({...form, password:e.target.value})} />
            <select className="border rounded p-2" value={form.role} onChange={e=>setForm({...form, role:e.target.value})}>
              <option value="CHEF">Chef de poste</option>
              <option value="ADMIN">Admin</option>
            </select>
            <button className="btn btn-primary">Créer</button>
          </form>
          <h3 className="mt-6 font-medium">Comptes</h3>
          <ul className="mt-2 space-y-1 text-sm">
            {users.map(u => (
              <li key={u.id} className="border rounded p-2 flex justify-between items-center">
                <span>{u.full_name} — {u.email}</span>
                <div className="flex gap-2">
                  <button className="btn btn-orange" onClick={()=>updateUser(u)}>Éditer</button>
                  <button className="btn bg-red-600 text-white" onClick={()=>deleteUser(u)}>Supprimer</button>
                </div>
              </li>
            ))}
          </ul>
        </div>

        <div className="card lg:col-span-1">
          <h2 className="font-semibold text-lg mb-4">Stock / Objets</h2>
          <form className="grid gap-2" onSubmit={createItem}>
            <input className="border rounded p-2" placeholder="Nom" value={itemForm.name} onChange={e=>setItemForm({...itemForm, name:e.target.value})} />
            <input className="border rounded p-2" placeholder="Description" value={itemForm.description} onChange={e=>setItemForm({...itemForm, description:e.target.value})} />
            <select className="border rounded p-2" value={itemForm.type} onChange={e=>setItemForm({...itemForm, type:e.target.value})}>
              <option value="BULK">Quantitatif</option>
              <option value="UNIQUE">Unique</option>
              <option value="KIT">KIT (parent)</option>
            </select>
            {itemForm.type === 'UNIQUE' && (
              <input className="border rounded p-2" placeholder="Numéro de série" value={itemForm.serial_number} onChange={e=>setItemForm({...itemForm, serial_number:e.target.value})} />
            )}
            {itemForm.type === 'BULK' && (
              <input className="border rounded p-2" placeholder="Stock" type="number" value={itemForm.stock_qty} onChange={e=>setItemForm({...itemForm, stock_qty:+e.target.value})} />
            )}
            <button className="btn btn-orange">Ajouter</button>
          </form>
          <h3 className="mt-6 font-medium">Objets</h3>
          <ul className="mt-2 space-y-1 text-sm max-h-72 overflow-auto">
            {items.map(i => (
              <li key={i.id} className="border rounded p-2 flex justify-between items-center">
                <span>{i.name} <em className="text-gray-500">({i.type})</em></span>
                <div className="flex gap-2">
                  <button className="btn btn-orange" onClick={()=>editItem(i)}>Éditer</button>
                  <button className="btn bg-red-600 text-white" onClick={()=>deleteItem(i)}>Supprimer</button>
                </div>
              </li>
            ))}
          </ul>
        </div>

        <div className="card lg:col-span-1">
          <h2 className="font-semibold text-lg mb-2">Recette de KIT</h2>
          <div className="flex gap-2 mb-2">
            <select className="border rounded p-2 flex-1" value={selectedKit} onChange={e=>openRecipe(e.target.value)}>
              <option value="">— Choisir un KIT —</option>
              {kits.map(k => <option key={k.id} value={k.id}>{k.name}</option>)}
            </select>
            {selectedKit && <button className="btn btn-primary" onClick={saveRecipe}>Enregistrer</button>}
          </div>
          {selectedKit && (
            <div className="grid grid-cols-2 gap-3">
              <div>
                <h3 className="font-medium mb-1">Composants</h3>
                <ul className="text-sm border rounded max-h-64 overflow-auto">
                  {components.map(c => (
                    <li key={c.id} className="p-2 hover:bg-gray-50 flex justify-between">
                      <span>{c.name}</span>
                      <button className="btn btn-orange" onClick={()=>addToRecipe(c)}>Ajouter</button>
                    </li>
                  ))}
                </ul>
              </div>
              <div>
                <h3 className="font-medium mb-1">Recette</h3>
                <ul className="text-sm border rounded max-h-64 overflow-auto">
                  {recipe.map((r, idx) => (
                    <li key={idx} className="p-2 flex justify-between items-center">
                      <span>{r.name || r.item_id}</span>
                      <input type="number" className="border rounded p-1 w-20" value={r.required_qty} onChange={e=>{
                        const v = [...recipe]; v[idx].required_qty = +e.target.value; setRecipe(v)
                      }} />
                    </li>
                  ))}
                </ul>
              </div>
            </div>
          )}
        </div>
      </section>
    </div>
  )
}
