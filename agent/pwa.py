"""Installable web app (PWA) bits for the harness pages: manifest, icons (the app logo, agent/icon_data.py), a
service worker that caches ONLY the page shell (never API answers, approvals or events)."""
from __future__ import annotations

import base64
import functools
import json

THEME = "#1D1F23"

# Paths the service worker may cache (network first, cache as offline fallback). Nothing else.
SHELL = ["/", "/dashboard", "/connect", "/manifest.webmanifest", "/icon-192.png", "/icon-512.png",
         "/apple-touch-icon.png", "/icon.svg"]

HEAD = """<meta name="theme-color" content="#1D1F23">
<link rel="manifest" href="/manifest.webmanifest">
<link rel="icon" href="/icon.svg" type="image/svg+xml">
<link rel="icon" href="/favicon.png" sizes="32x32" type="image/png">
<link rel="apple-touch-icon" href="/apple-touch-icon.png">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="Agent">"""

REGISTER_JS = """if("serviceWorker" in navigator && (location.protocol==="https:" || ["localhost","127.0.0.1"].includes(location.hostname)))
  navigator.serviceWorker.register("/sw.js").catch(()=>{});"""

SW_JS = """// autonomous-agent service worker: page shell only. API calls, approvals, events and streams always
// go to the network and are never stored.
const CACHE = "aa-shell-v1";
const SHELL = %s;
self.addEventListener("install", e => { e.waitUntil(caches.open(CACHE).then(c => c.addAll(SHELL)).catch(()=>{})); self.skipWaiting(); });
self.addEventListener("activate", e => { e.waitUntil(caches.keys().then(ks => Promise.all(ks.filter(k => k !== CACHE).map(k => caches.delete(k))))); self.clients.claim(); });
self.addEventListener("fetch", e => {
  const req = e.request, url = new URL(req.url);
  if (req.method !== "GET" || url.origin !== location.origin || !SHELL.includes(url.pathname)) return;   // network only
  e.respondWith(fetch(req).then(r => { if (r.ok && !url.search.includes("pair=")) { const copy = r.clone(); caches.open(CACHE).then(c => c.put(url.pathname, copy)); } return r; })
    .catch(() => caches.match(url.pathname)));
});
""" % json.dumps(SHELL)


def manifest() -> bytes:
    return json.dumps({
        "name": "autonomous-agent", "short_name": "Agent", "id": "/", "start_url": "/", "scope": "/",
        "display": "standalone", "orientation": "any", "background_color": THEME, "theme_color": THEME,
        "description": "Local autonomous agent: chat, approvals, IDC / Agent autonome local : chat, validations, IDC",
        "icons": [{"src": "/icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any maskable"},
                  {"src": "/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any maskable"},
                  {"src": "/icon.svg", "sizes": "any", "type": "image/svg+xml"}]}, ensure_ascii=False).encode()


# Icon: the app logo (a ring around a rounded square), drawn by packaging/make_icons.py -> agent/icon_data.py.
from . import icon_data as _icons

ICON_SVG = _icons.SVG
_PNG = {32: _icons.PNG_32, 180: _icons.PNG_180, 192: _icons.PNG_192, 512: _icons.PNG_512}


@functools.lru_cache(maxsize=8)
def icon_png(size: int) -> bytes:
    """The logo as PNG bytes (sizes 32, 180, 192 and 512 are stored)."""
    return base64.b64decode(_PNG[size])


def asset(path: str) -> tuple[str, bytes, str] | None:
    """(content type, body, Cache-Control) for a PWA path, or None."""
    if path == "/manifest.webmanifest":
        return "application/manifest+json", manifest(), "no-cache"
    if path == "/sw.js":
        return "text/javascript; charset=utf-8", SW_JS.encode(), "no-cache"
    if path == "/icon.svg":
        return "image/svg+xml", ICON_SVG, "max-age=86400"
    sizes = {"/favicon.png": 32, "/favicon.ico": 32, "/icon-192.png": 192, "/icon-512.png": 512, "/apple-touch-icon.png": 180}
    if path in sizes:
        return "image/png", icon_png(sizes[path]), "max-age=86400"
    return None
