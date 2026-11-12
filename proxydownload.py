# server.py
import ipaddress
import socket
import time
from collections import defaultdict
from urllib.parse import urlparse, quote

import requests
from flask import Flask, Response, request, render_template_string

app = Flask(__name__)

# ================== CẤU HÌNH ==================
ALLOWED = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/gif": "gif",
    "image/webp": "webp",
    "image/svg+xml": "svg",
}
MAX_SIZE = 20 * 1024 * 1024          # 20MB
CONNECT_TIMEOUT = 5
READ_TIMEOUT = 30
CHUNK_SIZE = 8192

HOST = "0.0.0.0"
PORT = 5000

# Glitch effects server
GLITCH_BASE = "https://gor-mez8.onrender.com"

# Rate limit
RATE_LIMIT = 60          # request
RATE_WINDOW = 60         # / 60 giây / IP
_hits = defaultdict(list)
# ==============================================


# ================== HELPERS ==================
def is_safe_url(url: str) -> bool:
    try:
        p = urlparse(url)
        if p.scheme not in ("http", "https") or not p.hostname:
            return False
        infos = socket.getaddrinfo(p.hostname, None)
        for info in infos:
            ip = ipaddress.ip_address(info[4][0])
            if (ip.is_private or ip.is_loopback or ip.is_link_local
                    or ip.is_reserved or ip.is_multicast or ip.is_unspecified):
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
# =============================================


# ================== TRANG CHỦ (GLITCH EFFECT) ==================
INDEX_HTML = r"""
<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Proxy Download — Glitch</title>
<style>
  :root{
    --bg:#0b0b0d; --fg:#d6d3d1; --pink:#ff2e88; --cyan:#00e5ff;
  }
  *{box-sizing:border-box}
  html,body{margin:0;height:100%;background:var(--bg);color:var(--fg);
    font-family: ui-monospace, "SF Mono", Menlo, Consolas, monospace;
    overflow-x:hidden}
  body{display:flex;flex-direction:column;align-items:center;
    padding:48px 20px;gap:32px}

  /* === GLITCH TITLE === */
  .glitch{
    position:relative;
    font-size:clamp(32px,8vw,96px);
    font-weight:800;
    letter-spacing:.05em;
    color:var(--fg);
    text-transform:uppercase;
    line-height:1;
    user-select:none;
  }
  .glitch::before,.glitch::after{
    content:attr(data-text);
    position:absolute;left:0;top:0;width:100%;
    overflow:hidden;
  }
  .glitch::before{
    color:var(--pink);
    animation:glitch-a 2.2s infinite steps(2,end);
    clip-path:inset(0 0 55% 0);
  }
  .glitch::after{
    color:var(--cyan);
    animation:glitch-b 1.8s infinite steps(2,end);
    clip-path:inset(45% 0 0 0);
  }
  @keyframes glitch-a{
    0%,90%,100%{transform:translate(0,0)}
    92%{transform:translate(-3px,-2px)}
    94%{transform:translate(3px,2px)}
    96%{transform:translate(-2px,1px)}
  }
  @keyframes glitch-b{
    0%,88%,100%{transform:translate(0,0)}
    90%{transform:translate(3px,2px)}
    93%{transform:translate(-3px,-1px)}
    95%{transform:translate(2px,-2px)}
  }
  .scanlines{
    position:fixed;inset:0;pointer-events:none;z-index:2;
    background:repeating-linear-gradient(
      to bottom,
      rgba(255,255,255,0.03) 0px,
      rgba(255,255,255,0.03) 1px,
      transparent 1px,
      transparent 3px
    );
    mix-blend-mode:overlay;
    animation:scan 8s linear infinite;
  }
  @keyframes scan{
    0%{background-position:0 0}
    100%{background-position:0 100px}
  }
  .noise{
    position:fixed;inset:0;pointer-events:none;z-index:1;opacity:.06;
    background-image:
      radial-gradient(circle at 20% 30%, #fff 1px, transparent 1px),
      radial-gradient(circle at 80% 70%, #fff 1px, transparent 1px);
    background-size:7px 7px, 11px 11px;
    animation:noise 0.4s steps(3) infinite;
  }
  @keyframes noise{
    0%{transform:translate(0,0)}
    33%{transform:translate(-1px,1px)}
    66%{transform:translate(1px,-1px)}
    100%{transform:translate(0,0)}
  }

  /* === CARD === */
  .card{
    position:relative;z-index:3;
    background:rgba(255,255,255,0.03);
    border:1px solid rgba(255,255,255,0.08);
    border-radius:14px;
    padding:24px 28px;
    max-width:720px;width:100%;
    backdrop-filter:blur(6px);
    box-shadow:0 0 40px rgba(255,46,136,0.08);
  }
  .card h2{
    margin:0 0 6px;font-size:14px;font-weight:600;
    color:var(--pink);letter-spacing:.15em;text-transform:uppercase;
  }
  .card p{margin:6px 0 16px;font-size:13px;opacity:.7;line-height:1.6}
  .row{display:flex;gap:10px;flex-wrap:wrap}
  input[type=text]{
    flex:1;min-width:220px;
    background:#000;color:var(--fg);
    border:1px solid rgba(255,255,255,0.15);
    border-radius:8px;padding:11px 14px;
    font-family:inherit;font-size:13px;outline:none;
    transition:border-color .2s;
  }
  input[type=text]:focus{border-color:var(--pink)}
  button,a.btn{
    background:var(--pink);color:#0b0b0d;border:0;
    border-radius:8px;padding:11px 18px;
    font-family:inherit;font-weight:700;font-size:13px;
    cursor:pointer;text-decoration:none;display:inline-block;
    transition:transform .1s, box-shadow .2s;
  }
  button:hover,a.btn:hover{
    transform:translateY(-1px);
    box-shadow:0 0 20px rgba(255,46,136,0.5);
  }
  .out{
    margin-top:14px;font-size:12px;opacity:.6;word-break:break-all;
    font-family:inherit;
  }
  .out a{color:var(--cyan);text-decoration:none}
  .badge{
    display:inline-block;font-size:10px;padding:3px 8px;
    border-radius:99px;background:rgba(0,229,255,0.12);
    color:var(--cyan);margin-left:8px;letter-spacing:.1em;
    vertical-align:middle;
  }
  footer{
    position:relative;z-index:3;font-size:11px;opacity:.35;
    letter-spacing:.2em;text-transform:uppercase;
  }
  a{color:var(--cyan)}
</style>
</head>
<body>

  <div class="noise"></div>
  <div class="scanlines"></div>

  <div class="glitch" data-text="PROXY DOWNLOAD">PROXY DOWNLOAD</div>

  <div class="card">
    <h2>Download qua Proxy <span class="badge">v1</span></h2>
    <p>
      Nhập URL ảnh cần tải. Server sẽ fetch và trả file kèm
      timestamp ngắn <code>waifu_YYYYMMDD-HHMMSS.ext</code>.
    </p>
    <div class="row">
      <input id="u" type="text" placeholder="https://example.com/cat.png">
      <button onclick="go()">Download</button>
      <a class="btn" href="/docs">API Docs</a>
    </div>
    <div class="out" id="o"></div>
  </div>

  <footer>glitch effects // proxy download</footer>

<script>
function go(){
  const u = document.getElementById('u').value.trim();
  const o = document.getElementById('o');
  if(!u){ o.textContent = 'Nhập URL trước đã.'; return; }
  const link = '/download?url=' + encodeURIComponent(u);
  o.innerHTML = '→ <a href="'+link+'" target="_blank">'+link+'</a>';
  window.location.href = link;
}
</script>
</body>
</html>
"""


@app.route("/")
def index():
    return Response(INDEX_HTML, mimetype="text/html; charset=utf-8")
# ================================================================


# ================== DOWNLOAD PROXY ==================
@app.route("/download")
def download():
    ip = client_ip()
    if not rate_ok(ip):
        return "Too many requests", 429

    url = request.args.get("url")
    if not url:
        return "No URL", 400
    if not is_safe_url(url):
        return "Invalid or unsafe URL", 400

    try:
        r = requests.get(
            url, stream=True,
            timeout=(CONNECT_TIMEOUT, READ_TIMEOUT),
            allow_redirects=False,
            headers={"User-Agent": "waifu-downloader/1.0"},
        )
    except requests.RequestException:
        return "Failed to fetch image", 502

    if r.status_code != 200:
        r.close()
        return "Failed to fetch image", 502

    mime = r.headers.get("Content-Type", "").split(";")[0].strip().lower()
    if mime not in ALLOWED:
        r.close()
        return "Unsupported content type", 400

    filename = f"waifu_{short_ts()}.{ALLOWED[mime]}"

    def generate():
        total = 0
        try:
            for chunk in r.iter_content(CHUNK_SIZE):
                if not chunk:
                    continue
                total += len(chunk)
                if total > MAX_SIZE:
                    break
                yield chunk
        finally:
            r.close()

    return Response(
        generate(),
        headers={
            "Content-Type": mime,
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "no-store",
        },
    )
# ====================================================


# ================== GLITCH RENDER PROXY ==================
@app.route("/render.gif")
@app.route("/render")
def glitch_render():
    """Proxy sang gor-mez8.onrender.com/render.gif giữ nguyên query string."""
    ip = client_ip()
    if not rate_ok(ip):
        return "Too many requests", 429

    qs = request.query_string.decode("utf-8")
    target = f"{GLITCH_BASE}/render.gif"
    if qs:
        target += "?" + qs

    try:
        r = requests.get(target, timeout=(8, 30), stream=True,
                         headers={"User-Agent": "waifu-proxy/1.0"})
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
        return Response(r.content,
                        status=r.status_code,
                        content_type=r.headers.get("Content-Type", "text/plain"))
    except requests.RequestException:
        return "Upstream error", 502
# =========================================================


# ================== DOC API ==================
DOCS_HTML = r"""
<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>API Docs — Proxy Download</title>
<style>
  :root{--bg:#0b0b0d;--fg:#d6d3d1;--pink:#ff2e88;--cyan:#00e5ff;--dim:#8a8a8a}
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--fg);
    font-family:ui-monospace,"SF Mono",Menlo,Consolas,monospace;
    padding:48px 20px;line-height:1.7}
  .wrap{max-width:880px;margin:0 auto}
  h1{font-size:clamp(28px,6vw,48px);margin:0 0 8px;letter-spacing:.04em}
  h1 .g{color:var(--pink)}
  h2{color:var(--pink);font-size:16px;letter-spacing:.15em;
    text-transform:uppercase;margin:40px 0 12px;border-bottom:1px solid #222;padding-bottom:8px}
  h3{color:var(--cyan);font-size:13px;letter-spacing:.1em;
    text-transform:uppercase;margin:24px 0 6px}
  p{opacity:.85;font-size:14px}
  code,pre{font-family:inherit}
  code{background:#151518;padding:2px 6px;border-radius:4px;font-size:12.5px;color:var(--cyan)}
  pre{background:#111114;border:1px solid #222;border-radius:10px;
    padding:16px;overflow-x:auto;font-size:12.5px;line-height:1.6}
  table{width:100%;border-collapse:collapse;margin:12px 0;font-size:13px}
  th,td{padding:9px 10px;text-align:left;border-bottom:1px solid #1c1c20;vertical-align:top}
  th{color:var(--cyan);font-weight:600;font-size:11.5px;
    text-transform:uppercase;letter-spacing:.08em}
  tr:hover td{background:#101013}
  a{color:var(--cyan)}
  .badge{display:inline-block;font-size:10px;padding:2px 8px;border-radius:99px;
    background:rgba(255,46,136,0.15);color:var(--pink);
    letter-spacing:.1em;margin-left:8px;vertical-align:middle}
  .back{display:inline-block;margin-bottom:24px;font-size:12px;
    text-decoration:none;opacity:.7}
  .back:hover{opacity:1}
  ul{padding-left:20px}
  li{margin:4px 0;font-size:13.5px;opacity:.85}
</style>
</head>
<body>
<div class="wrap">

  <a class="back" href="/">← về trang chủ</a>

  <h1>API <span class="g">Docs</span></h1>
  <p>Proxy Download — tải ảnh qua server, kèm hiệu ứng glitch text GIF.</p>

  <!-- ============ DOWNLOAD ============ -->
  <h2>1. Download Proxy</h2>
  <p>Tải file ảnh từ URL bên ngoài. File trả về có timestamp ngắn.</p>

  <h3>Endpoint</h3>
  <pre>GET /download?url=&lt;URL&gt;</pre>

  <h3>Parameters</h3>
  <table>
    <tr><th>Tên</th><th>Bắt buộc</th><th>Mô tả</th></tr>
    <tr><td><code>url</code></td><td>✓</td><td>URL ảnh (http/https). Phải encode.</td></tr>
  </table>

  <h3>Giới hạn</h3>
  <ul>
    <li>Chỉ nhận <code>image/png</code>, <code>image/jpeg</code>, <code>image/gif</code>,
        <code>image/webp</code>, <code>image/svg+xml</code></li>
    <li>Kích thước tối đa: <b>20MB</b></li>
    <li>Timeout: connect 5s, read 30s</li>
    <li>Rate limit: 60 req / 60s / IP</li>
    <li>SSRF protected — chặn private IP, loopback, link-local</li>
  </ul>

  <h3>Response Headers</h3>
  <pre>Content-Type: image/png
Content-Disposition: attachment; filename="waifu_20260101-120000.png"
X-Content-Type-Options: nosniff
Cache-Control: no-store</pre>

  <h3>Ví dụ</h3>
  <pre>curl -OJ "http://localhost:5000/download?url=https://example.com/cat.png"</pre>

  <!-- ============ GLITCH ============ -->
  <h2>2. Glitch Render</h2>
  <p>Proxy sang <a href="https://gor-mez8.onrender.com" target="_blank">gor-mez8.onrender.com</a>
     — tạo text GIF hiệu ứng glitch. Giữ nguyên query string.</p>

  <h3>Endpoint</h3>
  <pre>GET /render.gif?text=...&amp;effect=...   (khuyến nghị — dùng cho Discord)
GET /render?text=...&amp;effect=...       (alias)
GET /fonts                            (danh sách font)</pre>

  <h3>Parameters</h3>
  <table>
    <tr><th>Tên</th><th>Mặc định</th><th>Mô tả</th></tr>
    <tr><td><code>text</code></td><td>—</td><td>Nội dung (dùng <code>+</code> hoặc <code>%20</code> cho space)</td></tr>
    <tr><td><code>effect</code></td><td>vhs</td><td>vhs, static, dropout, rgb, flicker, ghost, roll, glitch, type, scan, wave, slice, invert, pixelate, bloom, shake, zoom</td></tr>
    <tr><td><code>font</code></td><td>monobold</td><td>Xem <code>/fonts</code></td></tr>
    <tr><td><code>w</code></td><td>520</td><td>width, 16–800</td></tr>
    <tr><td><code>h</code></td><td>60</td><td>height, 16–400</td></tr>
    <tr><td><code>size</code></td><td>h−20</td><td>font size px (min 12)</td></tr>
    <tr><td><code>c1</code></td><td>ff2e88</td><td>màu chữ (hex, không #)</td></tr>
    <tr><td><code>bg</code></td><td>transparent</td><td>màu nền hoặc <code>transparent</code></td></tr>
    <tr><td><code>fps</code></td><td>15</td><td>2–30</td></tr>
    <tr><td><code>dur</code></td><td>2.5</td><td>giây, max 10 (max 120 frames)</td></tr>
    <tr><td><code>seed</code></td><td>random</td><td><b>Nên set</b> để cache ổn định (vd <code>seed=7</code>)</td></tr>
  </table>

  <h3>Ví dụ</h3>
  <pre>GET /render.gif?text=I+miss&amp;effect=glitch&amp;font=bolditalic&amp;w=700&amp;h=130&amp;size=76&amp;c1=d6d3d1&amp;bg=0b0b0d&amp;fps=15&amp;dur=3&amp;seed=7</pre>

  <pre>&lt;img src="http://localhost:5000/render.gif?text=I+miss&amp;effect=glitch&amp;font=bolditalic&amp;w=700&amp;h=130&amp;size=76&amp;c1=d6d3d1&amp;bg=0b0b0d&amp;fps=15&amp;dur=3&amp;seed=7" alt="I miss" /&gt;</pre>

  <h3>Fonts</h3>
  <p><code>bold</code>, <code>bolditalic</code>, <code>italic</code>, <code>mono</code>,
     <code>monobold</code>, <code>monobolditalic</code>, <code>monoitalic</code>,
     <code>regular</code>, <code>smallcaps</code>, <code>smallcapsitalic</code></p>

  <h3>Lưu ý</h3>
  <ul>
    <li><b>Luôn set <code>seed</code></b> để tránh render mới mỗi lần load.</li>
    <li>Lần render đầu chậm hơn — hit URL 1 lần trước khi embed.</li>
    <li>Render free tier ngủ sau ~15 phút không traffic.</li>
    <li>Discord: dùng URL <code>/render.gif</code> (có đuôi .gif).</li>
  </ul>

  <!-- ============ MISC ============ -->
  <h2>3. Khác</h2>
  <table>
    <tr><th>Endpoint</th><th>Mô tả</th></tr>
    <tr><td><code>GET /</code></td><td>Trang chủ glitch UI</td></tr>
    <tr><td><code>GET /docs</code></td><td>Trang này</td></tr>
    <tr><td><code>GET /fonts</code></td><td>Proxy danh sách font từ upstream</td></tr>
  </table>

  <p style="margin-top:40px;opacity:.4;font-size:12px">
    Proxy Download · glitch effects · <span id="ts"></span>
  </p>
</div>
<script>document.getElementById('ts').textContent=new Date().toISOString().slice(0,16).replace('T',' ');</script>
</body>
</html>
"""


@app.route("/docs")
def docs():
    return Response(DOCS_HTML, mimetype="text/html; charset=utf-8")
# ================================================


# ================== MAIN ==================
if __name__ == "__main__":
    ip = lan_ip()
    print("=" * 56)
    print(f"[server] started at {short_ts()}")
    print(f"[local]  http://127.0.0.1:{PORT}")
    print(f"[LAN]    http://{ip}:{PORT}")
    print(f"[docs]   http://{ip}:{PORT}/docs")
    print(f"[test]   http://{ip}:{PORT}/download?url=<image_url>")
    print("=" * 56)
    app.run(host=HOST, port=PORT)
