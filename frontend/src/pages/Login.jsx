import React, { useState } from 'react'
import { api } from '../api'

export default function Login(){
  const [email, setEmail] = useState('admin@pcisere.fr')
  const [password, setPassword] = useState('admin')
  const [result, setResult] = useState(null)
  async function submit(e){
    e.preventDefault()
    try{
      const data = await api('/auth/login', { method: 'POST', json: { email, password } })
      localStorage.setItem('token', data.access_token)
      localStorage.setItem('role', data.role)
      window.location.href = data.role === 'ADMIN' ? '/admin' : '/chef'
    }catch(err){
      setResult('Erreur: ' + err.message)
    }
  }
  return (
    <div className="min-h-screen flex items-center justify-center p-4">
      <div className="card w-full max-w-md">
        <div className="flex items-center gap-3 mb-6">
          <img src="/logo.png" className="w-14" />
          <h1 className="text-2xl font-bold text-pcblue">Connexion</h1>
        </div>
        <form onSubmit={submit} className="space-y-4">
          <input className="w-full border rounded p-2" value={email} onChange={e=>setEmail(e.target.value)} placeholder="Email" />
          <input className="w-full border rounded p-2" type="password" value={password} onChange={e=>setPassword(e.target.value)} placeholder="Mot de passe" />
          <button className="btn btn-primary w-full">Se connecter</button>
        </form>
        {result && <p className="mt-4 text-red-600">{result}</p>}
        <p className="text-xs text-gray-500 mt-4">Admin par défaut : admin@pcisere.fr / admin</p>
      </div>
    </div>
  )
}
