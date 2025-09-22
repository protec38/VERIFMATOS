import React, { useEffect, useState } from 'react'
import { api } from '../api'

export default function Chef(){
  const token = localStorage.getItem('token')
  const [events, setEvents] = useState([])
  const [items, setItems] = useState([])
  const [kitIds, setKitIds] = useState([])
  const [eventForm, setEventForm] = useState({ title:'', location:'' })

  useEffect(()=>{ load() },[])
  async function load(){
    try{
      setItems((await api('/admin/items', { token })).filter(i => i.type === 'KIT'))
      setEvents(await api('/events', { token }))
    }catch(e){
      // not logged -> go login
      window.location.href = '/login'
    }
  }

  async function createEvent(e){
    e.preventDefault()
    const body = { title:eventForm.title, location:eventForm.location, kit_ids: kitIds }
    const ev = await api('/events', { method:'POST', token, json: body })
    await load()
    navigator.clipboard.writeText(window.location.origin + '/#/join/' + ev.access_code); alert('Événement créé. Lien copié dans le presse-papier.')
  }

  return (
    <div className="p-6 space-y-8">
      <header className="flex items-center gap-3">
        <img src="/logo.png" className="w-12" />
        <h1 className="text-3xl font-bold text-pcblue">Chef de poste</h1>
      </header>

      <section className="card">
        <h2 className="font-semibold text-lg mb-4">Créer un événement</h2>
        <form onSubmit={createEvent} className="grid md:grid-cols-2 gap-3">
          <input className="border rounded p-2" placeholder="Titre" value={eventForm.title} onChange={e=>setEventForm({...eventForm, title:e.target.value})} />
          <input className="border rounded p-2" placeholder="Lieu" value={eventForm.location} onChange={e=>setEventForm({...eventForm, location:e.target.value})} />
          <div className="md:col-span-2">
            <p className="mb-2 text-sm text-gray-600">Sélectionner les KITS (objets parents) à vérifier / charger</p>
            <div className="grid md:grid-cols-3 gap-2">
              {items.map(k => (
                <label key={k.id} className="border rounded p-2 flex items-center gap-2">
                  <input type="checkbox" checked={kitIds.includes(k.id)} onChange={e=>{
                    if(e.target.checked) setKitIds([...kitIds, k.id])
                    else setKitIds(kitIds.filter(x => x !== k.id))
                  }} />
                  {k.name}
                </label>
              ))}
            </div>
          </div>
          <button className="btn btn-orange md:col-span-2">Créer</button>
        </form>
      </section>

      <section className="card">
        <h2 className="font-semibold text-lg mb-4">Événements</h2>
        <ul className="space-y-2">
          {events.map(e => (
            <li key={e.id} className="border rounded p-3 flex items-center justify-between">
              <div>
                <div className="font-semibold">{e.title}</div>
                <div className="text-sm text-gray-600">{e.location}</div>
                <div className="text-xs mt-1">Lien secouristes : <span className="font-mono">{window.location.origin}/#/join/{e.access_code}</span></div>
              </div>
              <div className="flex gap-2"><a className="btn btn-primary" href={`/#/event/${e.id}/verify`}>Suivi</a><button className="btn bg-red-600 text-white" onClick={async ()=>{ if(confirm('Supprimer cet événement ?')) { await api(`/events/${e.id}`, { method:'DELETE', token }); await load() } }}>Supprimer</button></div>
            </li>
          ))}
        </ul>
      </section>
    </div>
  )
}
