"""주거용 프록시용 로컬 중계기 — 크롬이 인증창 없이 프록시를 쓰게 한다.

왜 필요한가
  · 크롬 --proxy-server 는 URL 에 넣은 id:pw 를 무시하고 인증창을 띄운다.
  · MV3 확장앱은 blocking webRequest 가 막혀 onAuthRequired 로 자동응답이 안 된다.
  → 로컬에서 인증 없는 프록시를 열고, 상위 프록시로 넘길 때만 인증 헤더를 붙인다.

중요 — TLS 를 절대 가로채지 않는다.
  SSG(Akamai)는 TLS 지문으로 브라우저 여부를 판별한다(2026-08-06 실측:
  파이썬·curl_cffi 전부 403, 크롬만 200). mitmproxy 처럼 TLS 를 풀었다 다시
  맺으면 지문이 바뀌어 차단된다. 그래서 CONNECT 를 그대로 relay 만 한다.

사용: python proxy_relay.py <listen_port> <upstream_host:port> <user> <pass>
"""

import base64
import socket
import sys
import threading

BUF = 65536


def pipe(a: socket.socket, b: socket.socket) -> None:
    try:
        while True:
            data = a.recv(BUF)
            if not data:
                break
            b.sendall(data)
    except Exception:
        pass
    finally:
        for s in (a, b):
            try:
                s.shutdown(socket.SHUT_RDWR)
            except Exception:
                pass
            try:
                s.close()
            except Exception:
                pass


def handle(client: socket.socket, up_host: str, up_port: int, auth: str) -> None:
    try:
        client.settimeout(30)
        head = b""
        while b"\r\n\r\n" not in head:
            chunk = client.recv(BUF)
            if not chunk:
                client.close()
                return
            head += chunk
            if len(head) > 65536:
                client.close()
                return

        # 상위 프록시로 그대로 전달하되 Proxy-Authorization 만 주입한다.
        lines = head.split(b"\r\n")
        out = [lines[0]]
        for ln in lines[1:]:
            if ln.lower().startswith(b"proxy-authorization:"):
                continue
            out.append(ln)
        idx = out.index(b"") if b"" in out else len(out)
        out.insert(idx, b"Proxy-Authorization: Basic " + auth.encode())
        payload = b"\r\n".join(out)

        upstream = socket.create_connection((up_host, up_port), timeout=30)
        upstream.sendall(payload)

        threading.Thread(target=pipe, args=(client, upstream), daemon=True).start()
        pipe(upstream, client)
    except Exception:
        try:
            client.close()
        except Exception:
            pass


def main() -> None:
    port = int(sys.argv[1])
    up = sys.argv[2]
    user, pw = sys.argv[3], sys.argv[4]
    up_host, up_port = up.rsplit(":", 1)
    auth = base64.b64encode(f"{user}:{pw}".encode()).decode()

    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", port))
    srv.listen(128)
    print(f"relay ready 127.0.0.1:{port} → {up_host}:{up_port}", flush=True)

    while True:
        try:
            c, _ = srv.accept()
            threading.Thread(
                target=handle, args=(c, up_host, int(up_port), auth), daemon=True
            ).start()
        except Exception:
            continue


main()
