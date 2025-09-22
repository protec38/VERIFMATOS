import React from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter, Routes, Route, Navigate, Link } from 'react-router-dom'
import './index.css'
import Login from './pages/Login'
import Admin from './pages/Admin'
import Chef from './pages/Chef'
import JoinEvent from './pages/JoinEvent'
import Verify from './pages/Verify'

function App(){
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Navigate to="/chef" />} />
        <Route path="/login" element={<Login />} />
        <Route path="/admin" element={<Admin />} />
        <Route path="/chef" element={<Chef />} />
        <Route path="/join/:code" element={<JoinEvent />} />
        <Route path="/event/:eventId/verify" element={<Verify />} />
      </Routes>
    </BrowserRouter>
  )
}

createRoot(document.getElementById('root')).render(<App />)
