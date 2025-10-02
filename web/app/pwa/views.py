# app/pwa/views.py — PWA (manifest + service worker) via blueprint
from __future__ import annotations
import json
from flask import Blueprint, Response

bp = Blueprint("pwa", __name__)

@bp.get("/manifest.webmanifest")
def manifest():
    data = {
        "name": "Préparation Matériel - Protection Civile",
        "short_name": "PC Prépa",
        "start_url": "/",
        "display": "standalone",
        "background_color": "#003E6B",
        "theme_color": "#003E6B",
        "icons": [
            {"src": "/static/pc_logo.webp", "sizes": "512x512", "type": "image/webp", "purpose": "any"},
            {"src": "/static/pc_logo.webp", "sizes": "192x192", "type": "image/webp", "purpose": "any"}
        ]
    }
    return Response(json.dumps(data), mimetype="application/manifest+json")

@bp.get("/sw.js")
def service_worker():
    js = f"""const CACHE_NAME = 'pcprep-cache-v1';
const CORE = [
  '/',
  '/dashboard',
  '/static/pc_logo.webp',
  '/manifest.webmanifest'
];

self.addEventListener('install', event => {{
  event.waitUntil(
    caches.open(CACHE_NAME).then(cache => cache.addAll(CORE))
  );
  self.skipWaiting();
}});

self.addEventListener('activate', event => {{
  event.waitUntil(
    caches.keys().then(keys => Promise.all(keys.map(k => k !== CACHE_NAME ? caches.delete(k) : null)))
  );
  self.clients.claim();
}});

self.addEventListener('fetch', event => {{
  const req = event.request;
  if (req.method !== 'GET') return;
  event.respondWith(
    caches.match(req).then(cached => cached || fetch(req).then(resp => {{
      const copy = resp.clone();
      caches.open(CACHE_NAME).then(cache => cache.put(req, copy));
      return resp;
    }}).catch(() => caches.match('/dashboard')))
  );
}});
"""
    return Response(js, mimetype="application/javascript")
