const API_BASE = import.meta.env.VITE_API_BASE || '/api'

export async function api(path, { method='GET', token=null, json=null } = {}){
  const headers = {}
  if (token) headers['Authorization'] = `Bearer ${token}`
  if (json) headers['Content-Type'] = 'application/json'
  const res = await fetch(`${API_BASE}${path}`, { method, headers, body: json ? JSON.stringify(json) : undefined })
  if (!res.ok) throw new Error(await res.text())
  const ct = res.headers.get('content-type') || ''
  return ct.includes('application/json') ? res.json() : res.text()
}
