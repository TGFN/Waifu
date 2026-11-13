# server.py
import ipaddress
import socket
import time
from collections import defaultdict
from urllib.parse import urlparse

import requests
from flask import Flask, Response, request

app = Flask(__name__)

# ================== CONFIG ==================
ALLOWED_IMAGE = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/gif": "gif",
    "image/webp": "webp",
    "image/svg+xml": "svg",
}
ALLOWED_VIDEO = {
    "video/mp4": "mp4",
    "video/webm": "webm",
    "video/quicktime": "mov",
}
ALLOWED = {**ALLOWED_IMAGE, **ALLOWED_VIDEO}

MAX_IMAGE_SIZE = 20 * 1024 * 1024       # 20 MB
MAX_VIDEO_SIZE = 200 * 1024 * 1024      # 200 MB
CONNECT_TIMEOUT = 5
READ_TIMEOUT = 60
CHUNK_SIZE = 64 * 1024

HOST = "0.0.0.0"
PORT = 5000

GLITCH_BASE = "https://gor-mez8.onrender.com"

RATE_LIMIT = 60
RATE_WINDOW = 60
_hits = defaultdict(list)
# ============================================


# ================== SELF-IP DETECTION ==================
def get_own_ips() -> set:
    """
    Tá»± dĂ² táº¥t cáº£ IP cá»§a mĂ¡y cháº¡y proxy:
    - loopback (127.0.0.1, ::1)
    - IP LAN qua UDP trick
    - IP tá»« hostname resolve
    """
    ips = {"127.0.0.1", "::1"}

    # IP LAN chĂ­nh (UDP trick, khĂ´ng cáº§n internet tháº­t)
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ips.add(s.getsockname()[0])
        s.close()
    except Exception:
        pass

    # Táº¥t cáº£ IP tá»« hostname
    try:
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None):
            ips.add(info[4][0])
    except Exception:
        pass

    # IPv6 loopback + interface riĂªng
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET6):
            ips.add(info[4][0])
    except Exception:
        pass

    return ips


OWN_IPS = get_own_ips()


# Cloud metadata endpoints â€” LUĂ”N cháº·n
BLOCKED_METADATA = {
    ipaddress.ip_address("169.254.169.254"),      # AWS / GCP / Azure / OpenStack
    ipaddress.ip_address("100.100.100.200"),      # Alibaba Cloud
    ipaddress.ip_address("fd00:ec2::254"),        # AWS IPv6
}
# =========================================================


# ================== HELPERS ==================
def is_safe_url(url: str, allow_lan: bool = True) -> bool:
    """
    Kiá»ƒm tra URL an toĂ n:
    - Chá»‰ http/https
    - LUĂ”N cháº·n: metadata cloud, link-local, loopback, chĂ­nh mĂ¡y proxy
    - allow_lan=True  â†’ cho phĂ©p private IP (192.168.x.x, 10.x.x.x, 172.16-31.x.x)
                        miá»…n KHĂ”NG pháº£i self
    - allow_lan=False â†’ cháº·n má»i private IP
    """
    try:
        p = urlparse(url)
        if p.scheme not in ("http", "https") or not p.hostname:
            return False

        infos = socket.getaddrinfo(p.hostname, None)
        for info in infos:
            ip_str = info[4][0]
            ip = ipaddress.ip_address(ip_str)

            # 1. Metadata cloud â€” luĂ´n cháº·n
            if ip in BLOCKED_METADATA:
                return False

            # 2. Link-local (169.254.0.0/16, fe80::/10)
            if ip.is_link_local:
                return False

            # 3. Loopback (127.0.0.0/8, ::1)
            if ip.is_loopback:
                return False

            # 4. ChĂ­nh mĂ¡y proxy (má»i IP cá»§a nĂ³)
            if ip_str in OWN_IPS:
                return False

            # 5. Private IP
            if ip.is_private:
                if not allow_lan:
                    return False
                continue  # allow_lan=True â†’ cho phĂ©p

            # 6. Reserved / multicast / unspecified
            if ip.is_reserved or ip.is_multicast or ip.is_unspecified:
                return False

        return True
    except Exception:
        return False


def short_ts() -> str:
    return time.strftime("%Y%m%d-%H%M%S")


def lan_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def rate_ok(ip: str) -> bool:
    now = time.time()
    _hits[ip] = [t for t in _hits[ip] if now - t < RATE_WINDOW]
    if len(_hits[ip]) >= RATE_LIMIT:
        return False
    _hits[ip].append(now)
    return True


def client_ip() -> str:
    return (request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
            or request.remote_addr or "unknown")


def human_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f}{unit}" if unit == "B" else f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}TB"
# ============================================


# ================== INDEX (GLITCH UI) ==================
INDEX_HTML = r"""
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Proxy Download â€” Glitch</title>
<style>
  :root{--bg:#0b0b0d;--fg:#d6d3d1;--pink:#ff2e88;--cyan:#00e5ff;--dim:#8a8a8a}
  *{box-sizing:border-box}
  html,body{margin:0;min-height:100%;background:var(--bg);color:var(--fg);
    font-family:ui-monospace,"SF Mono",Menlo,Consolas,monospace;overflow-x:hidden}
  body{display:flex;flex-direction:column;align-items:center;
    padding:56px 20px;gap:36px}

  .glitch{position:relative;font-size:clamp(30px,7.5vw,88px);font-weight:800;
    letter-spacing:.05em;color:var(--fg);text-transform:uppercase;line-height:1;
    user-select:none;text-align:center}
  .glitch::before,.glitch::after{content:attr(data-text);position:absolute;
    left:0;top:0;width:100%;overflow:hidden}
  .glitch::before{color:var(--pink);animation:glitch-a 2.2s infinite steps(2,end);
    clip-path:inset(0 0 55% 0)}
  .glitch::after{color:var(--cyan);animation:glitch-b 1.8s infinite steps(2,end);
    clip-path:inset(45% 0 0 0)}
  @keyframes glitch-a{0%,90%,100%{transform:translate(0,0)}
    92%{transform:translate(-3px,-2px)}94%{transform:translate(3px,2px)}
    96%{transform:translate(-2px,1px)}}
  @keyframes glitch-b{0%,88%,100%{transform:translate(0,0)}
    90%{transform:translate(3px,2px)}93%{transform:translate(-3px,-1px)}
    95%{transform:translate(2px,-2px)}}

  .scanlines{position:fixed;inset:0;pointer-events:none;z-index:2;
    background:repeating-linear-gradient(to bottom,
      rgba(255,255,255,0.03) 0px,rgba(255,255,255,0.03) 1px,
      transparent 1px,transparent 3px);
    mix-blend-mode:overlay;animation:scan 8s linear infinite}
  @keyframes scan{0%{background-position:0 0}100%{background-position:0 100px}}
  .noise{position:fixed;inset:0;pointer-events:none;z-index:1;opacity:.06;
    background-image:
      radial-gradient(circle at 20% 30%,#fff 1px,transparent 1px),
      radial-gradient(circle at 80% 70%,#fff 1px,transparent 1px);
    background-size:7px 7px,11px 11px;animation:noise .4s steps(3) infinite}
  @keyframes noise{0%{transform:translate(0,0)}33%{transform:translate(-1px,1px)}
    66%{transform:translate(1px,-1px)}100%{transform:translate(0,0)}}

  .card{position:relative;z-index:3;background:rgba(255,255,255,.03);
    border:1px solid rgba(255,255,255,.08);border-radius:14px;
    padding:24px 28px;max-width:760px;width:100%;backdrop-filter:blur(6px);
    box-shadow:0 0 40px rgba(255,46,136,.08)}
  .card h2{margin:0 0 6px;font-size:13px;font-weight:600;color:var(--pink);
    letter-spacing:.15em;text-transform:uppercase}
  .card p{margin:6px 0 16px;font-size:13px;opacity:.7;line-height:1.6}
  .row{display:flex;gap:10px;flex-wrap:wrap}
  input[type=text]{flex:1;min-width:220px;background:#000;color:var(--fg);
    border:1px solid rgba(255,255,255,.15);border-radius:8px;
    padding:11px 14px;font-family:inherit;font-size:13px;outline:none;
    transition:border-color .2s}
  input[type=text]:focus{border-color:var(--pink)}
  button,a.btn{background:var(--pink);color:#0b0b0d;border:0;border-radius:8px;
    padding:11px 18px;font-family:inherit;font-weight:700;font-size:13px;
    cursor:pointer;text-decoration:none;display:inline-block;
    transition:transform .1s,box-shadow .2s}
  button:hover,a.btn:hover{transform:translateY(-1px);
    box-shadow:0 0 20px rgba(255,46,136,.5)}
  .out{margin-top:14px;font-size:12px;opacity:.6;word-break:break-all}
  .out a{color:var(--cyan);text-decoration:none}
  .badge{display:inline-block;font-size:10px;padding:3px 8px;border-radius:99px;
    background:rgba(0,229,255,.12);color:var(--cyan);margin-left:8px;
    letter-spacing:.1em;vertical-align:middle}
  .limits{display:flex;gap:8px;flex-wrap:wrap;margin-top:14px;font-size:11px}
  .limits span{padding:4px 10px;border-radius:99px;
    background:rgba(255,255,255,.05);border:1px solid rgba(255,255,255,.08);
    color:var(--dim);letter-spacing:.05em}
  .limits span b{color:var(--fg)}
  .toggle{display:flex;align-items:center;gap:8px;margin-top:12px;
    font-size:12px;color:var(--dim);cursor:pointer;user-select:none}
  .toggle input{accent-color:var(--pink)}
  footer{position:relative;z-index:3;font-size:11px;opacity:.35;
    letter-spacing:.2em;text-transform:uppercase}
  a{color:var(--cyan)}
</style>
</head>
<body>

  <div class="noise"></div>
  <div class="scanlines"></div>

  <div class="glitch" data-text="PROXY DOWNLOAD">PROXY DOWNLOAD</div>

  <div class="card">
    <h2>Download via Proxy <span class="badge">v3</span></h2>
    <p>
      Paste any image or video URL. The server fetches it and returns
      the file with a short timestamp: <code>waifu_YYYYMMDD-HHMMSS.ext</code>
    </p>
    <div class="row">
      <input id="u" type="text" placeholder="https://example.com/clip.mp4">
      <button onclick="go()">Download</button>
      <a class="btn" href="/docs">API Docs</a>
    </div>
    <label class="toggle">
      <input type="checkbox" id="lan" checked>
      Allow LAN / DuckDNS â†’ private IP (self IP &amp; metadata still blocked)
    </label>
    <div class="out" id="o"></div>
    <div class="limits">
      <span>Images <b>â‰¤ 20MB</b></span>
      <span>Videos <b>â‰¤ 200MB</b></span>
      <span>Rate <b>60/min</b></span>
      <span>SSRF <b>auto-detect self</b></span>
    </div>
  </div>

  <footer>glitch effects // proxy download</footer>

<script>
function go(){
  const u = document.getElementById('u').value.trim();
  const lan = document.getElementById('lan').checked ? '1' : '0';
  const o = document.getElementById('o');
  if(!u){ o.textContent = 'Enter a URL first.'; return; }
  const link = '/download?url=' + encodeURIComponent(u) + '&lan=' + lan;
  o.innerHTML = 'â†’ <a href="'+link+'" target="_blank">'+link+'</a>';
  window.location.href = link;
}
</script>
</body>
</html>
"""


@app.route("/")
def index():
    return Response(INDEX_HTML, mimetype="text/html; charset=utf-8")
# =======================================================


# ================== DOWNLOAD PROXY ==================
@app.route("/download")
def download():
    ip = client_ip()
    if not rate_ok(ip):
        return "Too many requests", 429

    url = request.args.get("url")
    if not url:
        return "No URL", 400

    # lan=1 (default) â†’ cho phĂ©p private IP, miá»…n khĂ´ng pháº£i self
    allow_lan = request.args.get("lan", "0") != "0"
    if not is_safe_url(url, allow_lan=allow_lan):
        return "Invalid or unsafe URL", 400

    try:
        r = requests.get(
            url, stream=True,
            timeout=(CONNECT_TIMEOUT, READ_TIMEOUT),
            allow_redirects=False,
            headers={"User-Agent": "waifu-downloader/3.0"},
        )
    except requests.RequestException:
        return "Failed to fetch file", 502

    if r.status_code != 200:
        r.close()
        return "Failed to fetch file", 502

    mime = r.headers.get("Content-Type", "").split(";")[0].strip().lower()
    if mime not in ALLOWED:
        r.close()
        return f"Unsupported content type: {mime or 'unknown'}", 400

    is_video = mime in ALLOWED_VIDEO
    limit = MAX_VIDEO_SIZE if is_video else MAX_IMAGE_SIZE

    # Reject early if Content-Length known & too large
    try:
        cl = int(r.headers.get("Content-Length", "0"))
        if cl and cl > limit:
            r.close()
            return f"File too large (limit {human_size(limit)})", 413
    except ValueError:
        pass

    filename = f"waifu_{short_ts()}.{ALLOWED[mime]}"

    def generate():
        total = 0
        try:
            for chunk in r.iter_content(CHUNK_SIZE):
                if not chunk:
                    continue
                total += len(chunk)
                if total > limit:
                    break
                yield chunk
        finally:
            r.close()

    headers = {
        "Content-Type": mime,
        "Content-Disposition": f'attachment; filename="{filename}"',
        "X-Content-Type-Options": "nosniff",
        "Cache-Control": "no-store",
    }
    if is_video and r.headers.get("Content-Length"):
        headers["Content-Length"] = r.headers["Content-Length"]

    return Response(generate(), headers=headers)
# ====================================================


# ================== GLITCH RENDER PROXY ==================
@app.route("/render.gif")
@app.route("/render")
def glitch_render():
    ip = client_ip()
    if not rate_ok(ip):
        return "Too many requests", 429

    qs = request.query_string.decode("utf-8")
    target = f"{GLITCH_BASE}/render.gif"
    if qs:
        target += "?" + qs

    try:
        r = requests.get(target, timeout=(8, 30), stream=True,
                         headers={"User-Agent": "waifu-proxy/3.0"})
    except requests.RequestException:
        return "Glitch render failed", 502

    if r.status_code != 200:
        r.close()
        return f"Upstream error {r.status_code}", 502

    mime = r.headers.get("Content-Type", "image/gif")
    return Response(
        r.iter_content(CHUNK_SIZE),
        headers={
            "Content-Type": mime,
            "Cache-Control": "public, max-age=86400",
            "X-Content-Type-Options": "nosniff",
        },
    )


@app.route("/fonts")
def glitch_fonts():
    try:
        r = requests.get(f"{GLITCH_BASE}/fonts", timeout=(5, 15))
        return Response(r.content, status=r.status_code,
                        content_type=r.headers.get("Content-Type", "text/plain"))
    except requests.RequestException:
        return "Upstream error", 502
# =========================================================


# ================== DOCS ==================
DOCS_HTML = r"""
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>API Docs â€” Proxy Download</title>
<style>
  :root{--bg:#0b0b0d;--fg:#d6d3d1;--pink:#ff2e88;--cyan:#00e5ff;--dim:#8a8a8a}
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--fg);
    font-family:ui-monospace,"SF Mono",Menlo,Consolas,monospace;
    padding:48px 20px;line-height:1.7}
  .wrap{max-width:900px;margin:0 auto}
  h1{font-size:clamp(28px,6vw,48px);margin:0 0 8px;letter-spacing:.04em}
  h1 .g{color:var(--pink)}
  h2{color:var(--pink);font-size:16px;letter-spacing:.15em;text-transform:uppercase;
    margin:40px 0 12px;border-bottom:1px solid #222;padding-bottom:8px}
  h3{color:var(--cyan);font-size:13px;letter-spacing:.1em;text-transform:uppercase;
    margin:24px 0 6px}
  p{opacity:.85;font-size:14px}
  code{background:#151518;padding:2px 6px;border-radius:4px;font-size:12.5px;color:var(--cyan)}
  pre{background:#111114;border:1px solid #222;border-radius:10px;padding:16px;
    overflow-x:auto;font-size:12.5px;line-height:1.6}
  table{width:100%;border-collapse:collapse;margin:12px 0;font-size:13px}
  th,td{padding:9px 10px;text-align:left;border-bottom:1px solid #1c1c20;vertical-align:top}
  th{color:var(--cyan);font-weight:600;font-size:11.5px;text-transform:uppercase;
    letter-spacing:.08em}
  tr:hover td{background:#101013}
  a{color:var(--cyan)}
  .back{display:inline-block;margin-bottom:24px;font-size:12px;
    text-decoration:none;opacity:.7}
  .back:hover{opacity:1}
  ul{padding-left:20px}
  li{margin:4px 0;font-size:13.5px;opacity:.85}
  .pill{display:inline-block;font-size:10px;padding:2px 8px;border-radius:99px;
    background:rgba(255,46,136,.15);color:var(--pink);letter-spacing:.1em;margin-left:8px}
  .ok{color:#4ade80}.no{color:#ff4d6d}
</style>
</head>
<body>
<div class="wrap">

  <a class="back" href="/">â† back to home</a>

  <h1>API <span class="g">Docs</span> <span class="pill">v3</span></h1>
  <p>Proxy Download â€” fetch images and videos through the server, plus glitch text GIFs.</p>

  <!-- ============ DOWNLOAD ============ -->
  <h2>1. Download Proxy</h2>
  <p>Fetches a file from an external URL. Returned filename includes a short timestamp.</p>

  <h3>Endpoint</h3>
  <pre>GET /download?url=&lt;URL&gt;&amp;lan=1</pre>

  <h3>Parameters</h3>
  <table>
    <tr><th>Name</th><th>Default</th><th>Description</th></tr>
    <tr><td><code>url</code></td><td>â€”</td><td>Image or video URL (http/https). Required. URL-encode it.</td></tr>
    <tr><td><code>lan</code></td><td><code>1</code></td><td>
      <code>1</code> = allow private/LAN IPs (DuckDNS â†’ NAS, etc.), still blocks self IP &amp; cloud metadata.<br>
      <code>0</code> = strict public-only (block all private IPs).
    </td></tr>
  </table>

  <h3>Supported types &amp; limits</h3>
  <table>
    <tr><th>Category</th><th>MIME</th><th>Ext</th><th>Max size</th></tr>
    <tr><td>Image</td><td><code>image/png</code></td><td>png</td><td rowspan="5">20 MB</td></tr>
    <tr><td>Image</td><td><code>image/jpeg</code></td><td>jpg</td></tr>
    <tr><td>Image</td><td><code>image/gif</code></td><td>gif</td></tr>
    <tr><td>Image</td><td><code>image/webp</code></td><td>webp</td></tr>
    <tr><td>Image</td><td><code>image/svg+xml</code></td><td>svg</td></tr>
    <tr><td>Video</td><td><code>video/mp4</code></td><td>mp4</td><td rowspan="3"><b>200 MB</b></td></tr>
    <tr><td>Video</td><td><code>video/webm</code></td><td>webm</td></tr>
    <tr><td>Video</td><td><code>video/quicktime</code></td><td>mov</td></tr>
  </table>

  <h3>SSRF protection (auto-detect)</h3>
  <p>The server auto-detects its own IPs at startup and never lets a request reach itself.</p>
  <table>
    <tr><th>Target</th><th>lan=1</th><th>lan=0</th><th>Reason</th></tr>
    <tr><td>Public IP / domain</td><td class="ok">allow</td><td class="ok">allow</td><td>Normal</td></tr>
    <tr><td>192.168.x.x / 10.x.x.x / 172.16-31.x.x</td><td class="ok">allow</td><td class="no">block</td><td>LAN (DuckDNS â†’ NAS)</td></tr>
    <tr><td>Proxy's own IPs (auto-detected)</td><td class="no">block</td><td class="no">block</td><td>Prevent self-request</td></tr>
    <tr><td>127.0.0.0/8 / ::1</td><td class="no">block</td><td class="no">block</td><td>Loopback</td></tr>
    <tr><td>169.254.0.0/16 / fe80::/10</td><td class="no">block</td><td class="no">block</td><td>Link-local</td></tr>
    <tr><td>169.254.169.254 (AWS/GCP/Azure)</td><td class="no">block</td><td class="no">block</td><td>Cloud metadata</td></tr>
    <tr><td>100.100.100.200 (Alibaba)</td><td class="no">block</td><td class="no">block</td><td>Cloud metadata</td></tr>
  </table>

  <h3>Limits</h3>
  <ul>
    <li>Rate limit: <b>60 requests / 60s / IP</b></li>
    <li>Timeout: connect 5s, read 60s</li>
    <li>If upstream sends <code>Content-Length</code> exceeding the limit â†’ rejected with <b>413</b> before download</li>
    <li>Only <code>http</code> and <code>https</code> schemes are accepted</li>
  </ul>

  <h3>Response headers</h3>
  <pre>Content-Type: video/mp4
Content-Disposition: attachment; filename="waifu_20260101-120000.mp4"
Content-Length: 48213022        # only when upstream provides it
X-Content-Type-Options: nosniff
Cache-Control: no-store</pre>

  <h3>Status codes</h3>
  <table>
    <tr><th>Code</th><th>Meaning</th></tr>
    <tr><td>200</td><td>OK â€” streaming the file</td></tr>
    <tr><td>400</td><td>Missing/unsafe URL, or unsupported content type</td></tr>
    <tr><td>413</td><td>File exceeds size limit</td></tr>
    <tr><td>429</td><td>Rate limit exceeded</td></tr>
    <tr><td>502</td><td>Upstream fetch failed</td></tr>
  </table>

  <h3>Examples</h3>
  <pre># Public image
curl -OJ "http://localhost:5000/download?url=https://example.com/cat.png"

# Public video (up to 200MB)
curl -OJ "http://localhost:5000/download?url=https://example.com/clip.mp4"

# DuckDNS â†’ LAN NAS (lan=1 default)
curl -OJ "http://localhost:5000/download?url=http://myhome.duckdns.org:8080/clip.mp4"

# Strict public-only
curl -OJ "http://localhost:5000/download?url=https://example.com/cat.png&amp;lan=0"

# In &lt;video&gt;
&lt;video src="http://localhost:5000/download?url=https://example.com/clip.mp4" controls&gt;&lt;/video&gt;</pre>

  <!-- ============ GLITCH ============ -->
  <h2>2. Glitch Render</h2>
  <p>Proxy to <a href="https://gor-mez8.onrender.com" target="_blank">gor-mez8.onrender.com</a>
     â€” generates glitchy text GIFs. Query string is forwarded as-is.</p>

  <h3>Endpoints</h3>
  <pre>GET /render.gif?text=...&amp;effect=...   (recommended â€” works with Discord)
GET /render?text=...&amp;effect=...       (alias)
GET /fonts                            (list available fonts)</pre>

  <h3>Parameters</h3>
  <table>
    <tr><th>Name</th><th>Default</th><th>Description</th></tr>
    <tr><td><code>text</code></td><td>â€”</td><td>Text content; use <code>+</code> or <code>%20</code> for spaces</td></tr>
    <tr><td><code>effect</code></td><td>vhs</td><td>vhs, static, dropout, rgb, flicker, ghost, roll, glitch, type, scan, wave, slice, invert, pixelate, bloom, shake, zoom</td></tr>
    <tr><td><code>font</code></td><td>monobold</td><td>See <code>/fonts</code></td></tr>
    <tr><td><code>w</code></td><td>520</td><td>width, 16â€“800</td></tr>
    <tr><td><code>h</code></td><td>60</td><td>height, 16â€“400</td></tr>
    <tr><td><code>size</code></td><td>hâˆ’20</td><td>font size in px (min 12)</td></tr>
    <tr><td><code>c1</code></td><td>ff2e88</td><td>text color, hex without #</td></tr>
    <tr><td><code>bg</code></td><td>transparent</td><td>background hex or <code>transparent</code></td></tr>
    <tr><td><code>fps</code></td><td>15</td><td>2â€“30</td></tr>
    <tr><td><code>dur</code></td><td>2.5</td><td>seconds, max 10 (max 120 frames)</td></tr>
    <tr><td><code>seed</code></td><td>random</td><td><b>Always set</b> to reuse cache (e.g. <code>seed=7</code>)</td></tr>
  </table>

  <h3>Fonts</h3>
  <p><code>bold</code>, <code>bolditalic</code>, <code>italic</code>, <code>mono</code>,
     <code>monobold</code>, <code>monobolditalic</code>, <code>monoitalic</code>,
     <code>regular</code>, <code>smallcaps</code>, <code>smallcapsitalic</code></p>

  <h3>Example</h3>
  <pre>GET /render.gif?text=I+miss&amp;effect=glitch&amp;font=bolditalic&amp;w=700&amp;h=130&amp;size=76&amp;c1=d6d3d1&amp;bg=0b0b0d&amp;fps=15&amp;dur=3&amp;seed=7</pre>
  <pre>&lt;img src="http://localhost:5000/render.gif?text=I+miss&amp;effect=glitch&amp;font=bolditalic&amp;w=700&amp;h=130&amp;size=76&amp;c1=d6d3d1&amp;bg=0b0b0d&amp;fps=15&amp;dur=3&amp;seed=7" alt="I miss" /&gt;</pre>

  <h3>Notes</h3>
  <ul>
    <li>Always set <code>seed</code> so the server reuses cached GIFs.</li>
    <li>First render is slower â€” hit the URL once before embedding.</li>
    <li>Render free tier sleeps after ~15 min of no traffic.</li>
    <li>Discord: use the <code>/render.gif</code> URL (with .gif extension).</li>
  </ul>

  <!-- ============ MISC ============ -->
  <h2>3. Misc</h2>
  <table>
    <tr><th>Endpoint</th><th>Description</th></tr>
    <tr><td><code>GET /</code></td><td>Glitch UI home page</td></tr>
    <tr><td><code>GET /docs</code></td><td>This page</td></tr>
    <tr><td><code>GET /fonts</code></td><td>Proxy font list from upstream</td></tr>
  </table>

  <p style="margin-top:40px;opacity:.4;font-size:12px">
    Proxy Download Â· glitch effects Â· <span id="ts"></span>
  </p>
</div>
<script>document.getElementById('ts').textContent=new Date().toISOString().slice(0,16).replace('T',' ');</script>
</body>
</html>
"""


@app.route("/docs")
def docs():
    return Response(DOCS_HTML, mimetype="text/html; charset=utf-8")
# =========================================


# ================== MAIN ==================
if __name__ == "__main__":
    ip = lan_ip()
    print("=" * 64)
    print(f"[server]  started at {short_ts()}")
    print(f"[local]   http://127.0.0.1:{PORT}")
    print(f"[LAN]     http://{ip}:{PORT}")
    print(f"[docs]    http://{ip}:{PORT}/docs")
    print(f"[limit]   images 20MB | videos 200MB | rate 60/min")
    print(f"[self-ip] {sorted(OWN_IPS)}")
    print("=" * 64)
    app.run(host=HOST, port=PORT)
