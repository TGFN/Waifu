# server.py
import ipaddress
import socket
import time
from urllib.parse import urlparse

import requests
from flask import Flask, Response, request

app = Flask(__name__)

# ================== CẤU HÌNH ==================
ALLOWED = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/gif": "gif",
    "image/webp": "webp",
}
MAX_SIZE = 20 * 1024 * 1024          # 20MB
CONNECT_TIMEOUT = 5
READ_TIMEOUT = 30
CHUNK_SIZE = 8192
# ==============================================


def is_safe_url(url: str) -> bool:
    """Chặn SSRF: chỉ cho http/https, resolve DNS, chặn private/loopback/link-local/reserved."""
    try:
        p = urlparse(url)
        if p.scheme not in ("http", "https") or not p.hostname:
            return False

        # resolve tất cả IP (IPv4 + IPv6) để tránh bypass qua record phụ
        infos = socket.getaddrinfo(p.hostname, None)
        for info in infos:
            ip = ipaddress.ip_address(info[4][0])
            if (
                ip.is_private
                or ip.is_loopback
                or ip.is_link_local
                or ip.is_reserved
                or ip.is_multicast
                or ip.is_unspecified
            ):
                return False
        return True
    except Exception:
        return False


def short_ts() -> str:
    """Timestamp ngắn: YYYYMMDD-HHMMSS."""
    return time.strftime("%Y%m%d-%H%M%S")


@app.route("/download")
def download():
    url = request.args.get("url")
    if not url:
        return "No URL", 400

    if not is_safe_url(url):
        return "Invalid or unsafe URL", 400

    try:
        r = requests.get(
            url,
            stream=True,
            timeout=(CONNECT_TIMEOUT, READ_TIMEOUT),
            allow_redirects=False,          # tránh bypass SSRF qua redirect
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

    # filename có timestamp short
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


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000)


# ================== TIMESTAMP SHORT (cuối file) ==================
if __name__ == "__main__":
    print(f"[server] started at {short_ts()}")
