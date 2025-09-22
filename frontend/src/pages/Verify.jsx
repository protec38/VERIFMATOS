import React, { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { api } from '../api'

export default function Verify(){
  const { eventId } = useParams()
  const [data, setData] = useState(null)
  const [poll, setPoll] = useState(0)
  const participant = localStorage.getItem('participant_name') || 'Inconnu'

  useEffect(()=>{
    load()
    const t = setInterval(()=> setPoll(p => p+1), 2000) // actualisation AJAX
    return ()=> clearInterval(t)
  },[eventId])

  useEffect(()=>{ load() },[poll])

  async function load(){
    try{
      // we use the public event-by-code endpoint to get kits and components
      const evs = await api(`/events/${eventId}`, { token: localStorage.getItem('token') })
    }catch{}
    const status = await api(`/events/${eventId}/status`, { token: localStorage.getItem('token') || undefined })
    setData(status)
  }

  async function check(item_id, kit_id, required_qty){
    const qty = prompt('Quantité vérifiée', required_qty) ?? required_qty
    await api(`/public/${eventId}/verify?participant=${encodeURIComponent(participant)}`, {
      method:'POST', json:{ item_id, kit_id, qty_checked: +qty, status:'OK', comment:'' }
    })
    await load()
  }

  async function toggleLoaded(event_kit_id, loaded){
    await api(`/events/${eventId}/kits/${event_kit_id}/loaded?loaded=${!loaded}`, { method:'POST', token: localStorage.getItem('token') })
    await load()
  }

  if(!data) return <div className="p-6">Chargement…</div>

  return (
    <div className="p-6 space-y-6">
      <header className="flex items-center gap-3">
        <img src="/logo.png" className="w-12" />
        <h1 className="text-2xl font-bold text-pcblue">Vérification & Chargement</h1>
        <div className="ml-auto text-sm text-gray-600">Connecté : {participant}</div>
      </header>

      <section className="grid md:grid-cols-2 gap-6">
        <div className="card">
          <h2 className="font-semibold mb-2">Kits sélectionnés</h2>
          <ul className="space-y-2">
            {data.kits.map(k => (
              <li key={k.event_kit_id} className="border rounded p-2 flex items-center justify-between">
                <span>{k.kit_name}</span>
                <button className={"btn " + (k.loaded ? "btn-primary" : "btn-orange")} onClick={()=>toggleLoaded(k.event_kit_id, k.loaded)}>
                  {k.loaded ? "Chargé" : "Marquer chargé"}
                </button>
              </li>
            ))}
          </ul>
        </div>

        <div className="card">
          <h2 className="font-semibold mb-2">Historique des vérifications (temps réel)</h2>
          <ul className="space-y-2 max-h-96 overflow-auto text-sm">
            {data.verifications.map(v => (
              <li key={v.id} className="border rounded p-2">
                <div className="font-medium">{v.verified_by}</div>
                <div className="text-xs text-gray-600">{new Date(v.verified_at).toLocaleString()}</div>
                <div className="text-sm">Item #{v.item_id} — Qté : {v.qty_checked} — {v.status}</div>
                {v.comment && <div className="text-xs">Note: {v.comment}</div>}
              </li>
            ))}
          </ul>
        </div>
      </section>

      <section className="card">
        <h2 className="font-semibold mb-4">Vérifier un item (saisie rapide)</h2>
        <QuickCheck eventId={eventId} onDone={load} />
      </section>
    </div>
  )
}

function QuickCheck({ eventId, onDone }){
  const [kitId, setKitId] = useState('')
  const [itemId, setItemId] = useState('')
  const [qty, setQty] = useState(1)
  const participant = localStorage.getItem('participant_name') || 'Inconnu'

  async function submit(e){
    e.preventDefault()
    await api(`/public/${eventId}/verify?participant=${encodeURIComponent(participant)}`, { method:'POST', json:{ item_id: itemId, kit_id: kitId || null, qty_checked: +qty, status:'OK', comment:'' } })
    setItemId(''); setQty(1)
    onDone()
  }

  return (
    <form onSubmit={submit} className="grid md:grid-cols-4 gap-2">
      <input className="border rounded p-2" placeholder="Kit ID (optionnel)" value={kitId} onChange={e=>setKitId(e.target.value)} />
      <input className="border rounded p-2" placeholder="Item ID" value={itemId} onChange={e=>setItemId(e.target.value)} />
      <input type="number" className="border rounded p-2" placeholder="Quantité" value={qty} onChange={e=>setQty(e.target.value)} />
      <button className="btn btn-primary">Valider</button>
    </form>
  )
}
