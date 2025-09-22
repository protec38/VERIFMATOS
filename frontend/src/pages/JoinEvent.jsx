import React, { useEffect, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { api } from '../api'

export default function JoinEvent(){
  const { code } = useParams()
  const nav = useNavigate()
  const [info, setInfo] = useState(null)
  const [first_name, setFirst] = useState('')
  const [last_name, setLast] = useState('')

  useEffect(()=>{
    api(`/public/event_by_code/${code}`).then(setInfo).catch(()=> alert('Code invalide'))
  },[code])

  async function join(e){
    e.preventDefault()
    const j = await api(`/public/${info.event.id}/join`, { method:'POST', json:{ first_name, last_name } })
    localStorage.setItem('participant_name', j.display_name)
    nav(`/event/${info.event.id}/verify`)
  }

  if(!info) return <div className="p-6">Chargement…</div>

  return (
    <div className="min-h-screen p-6 max-w-xl mx-auto">
      <div className="card">
        <div className="flex items-center gap-3 mb-4">
          <img src="/logo.png" className="w-12" />
          <h1 className="text-xl font-bold text-pcblue">Rejoindre : {info.event.title}</h1>
        </div>
        <form className="grid gap-2" onSubmit={join}>
          <input className="border rounded p-2" placeholder="Prénom" value={first_name} onChange={e=>setFirst(e.target.value)} />
          <input className="border rounded p-2" placeholder="Nom" value={last_name} onChange={e=>setLast(e.target.value)} />
          <button className="btn btn-primary">Entrer</button>
        </form>

        <div className="mt-6">
          <h2 className="font-semibold">Kits à vérifier</h2>
          <ul className="list-disc ml-6 text-sm mt-2">
            {info.kits.map(k => <li key={k.kit_id}>{k.kit_name}</li>)}
          </ul>
        </div>
      </div>
    </div>
  )
}
