"""Installable web app (PWA) bits for the harness pages: manifest, icons (PNG drawn here, no files), a
service worker that caches ONLY the page shell (never API answers, approvals or events)."""
from __future__ import annotations

import functools
import json
import math
import struct
import zlib

THEME = "#05050B"
ACCENT = (11, 11, 20)        # icon background (dark)
NEON = (0, 212, 255)        # icon nodes and links (neon blue)

# Paths the service worker may cache (network first, cache as offline fallback). Nothing else.
SHELL = ["/", "/dashboard", "/connect", "/manifest.webmanifest", "/icon-192.png", "/icon-512.png",
         "/apple-touch-icon.png", "/icon.svg"]

HEAD = """<meta name="theme-color" content="#05050B">
<link rel="manifest" href="/manifest.webmanifest">
<link rel="icon" href="/icon.svg" type="image/svg+xml">
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


# Icon: three connected agents (white) on the accent colour, inside the maskable safe zone.
_NODES = [(0.5, 0.33), (0.32, 0.64), (0.68, 0.64)]
_EDGES = [(0, 1), (0, 2), (1, 2)]

ICON_SVG = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><rect width="100" height="100" rx="22" '
            'fill="rgb(11,11,20)"/><g stroke="#00D4FF" stroke-width="5" stroke-linecap="round">'
            + "".join(f'<line x1="{_NODES[a][0]*100:g}" y1="{_NODES[a][1]*100:g}" x2="{_NODES[b][0]*100:g}" '
                      f'y2="{_NODES[b][1]*100:g}"/>' for a, b in _EDGES)
            + '</g>' + "".join(f'<circle cx="{x*100:g}" cy="{y*100:g}" r="9" fill="#00D4FF"/>' for x, y in _NODES)
            + '</svg>').encode()


def _seg_dist(px: float, py: float, a: tuple, b: tuple) -> float:
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


@functools.lru_cache(maxsize=4)
def icon_png(size: int) -> bytes:
    """Full-bleed square (maskable), anti-aliased by 2x2 supersampling."""
    r_node, half_line = 0.09, 0.025
    rows = []
    for y in range(size):
        row = bytearray([0])
        for x in range(size):
            cover = 0
            for sy in (0.25, 0.75):
                for sx in (0.25, 0.75):
                    px, py = (x + sx) / size, (y + sy) / size
                    if (any(math.hypot(px - nx, py - ny) <= r_node for nx, ny in _NODES) or
                            any(_seg_dist(px, py, _NODES[a], _NODES[b]) <= half_line for a, b in _EDGES)):
                        cover += 1
            f = cover / 4
            row += bytes(int(c + (n - c) * f) for c, n in zip(ACCENT, NEON))
        rows.append(bytes(row))
    raw = zlib.compress(b"".join(rows), 9)

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", raw) + chunk(b"IEND", b""))


def asset(path: str) -> tuple[str, bytes, str] | None:
    """(content type, body, Cache-Control) for a PWA path, or None."""
    if path == "/manifest.webmanifest":
        return "application/manifest+json", manifest(), "no-cache"
    if path == "/sw.js":
        return "text/javascript; charset=utf-8", SW_JS.encode(), "no-cache"
    if path == "/icon.svg":
        return "image/svg+xml", ICON_SVG, "max-age=86400"
    sizes = {"/icon-192.png": 192, "/icon-512.png": 512, "/apple-touch-icon.png": 180}
    if path in sizes:
        return "image/png", icon_png(sizes[path]), "max-age=86400"
    return None
