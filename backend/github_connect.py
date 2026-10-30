"""SSH transport through Radar's existing authenticated HTTPS proxy."""
import base64
import os
from pathlib import Path
import re
import select
import socket
import sys
from urllib.parse import unquote, urlsplit

if sys.argv[1:] != ['ssh.github.com', '443']:
    raise SystemExit('Unexpected GitHub SSH destination')
network = Path(os.environ['RADAR_NETWORK_ENV']).read_text()
match = re.search(r'^\s*(?:export\s+)?https_proxy=[\"\']?([^\s\"\']+)', network, re.M)
if not match:
    raise SystemExit('Existing HTTPS proxy is not configured')
proxy = urlsplit(match[1])
assert proxy.scheme == 'http' and proxy.hostname
with socket.create_connection((proxy.hostname, proxy.port or 80), timeout=20) as sock:
    headers = ['CONNECT ssh.github.com:443 HTTP/1.1', 'Host: ssh.github.com:443']
    if proxy.username:
        auth = unquote(proxy.username) + ':' + unquote(proxy.password or '')
        headers.append('Proxy-Authorization: Basic ' + base64.b64encode(auth.encode()).decode())
    sock.sendall(('\r\n'.join(headers) + '\r\n\r\n').encode())
    response = b''
    while not response.endswith(b'\r\n\r\n') and len(response) < 16384:
        chunk = sock.recv(1)
        if not chunk:
            raise SystemExit('GitHub proxy disconnected')
        response += chunk
    if not response.startswith(b'HTTP/1.1 200') and not response.startswith(b'HTTP/1.0 200'):
        raise SystemExit('GitHub proxy rejected CONNECT')
    sock.settimeout(None)
    while True:
        ready, _, _ = select.select([sock, sys.stdin.buffer], [], [], 120)
        if not ready:
            continue
        for source in ready:
            data = sock.recv(65536) if source is sock else os.read(0, 65536)
            if not data:
                raise SystemExit(0)
            if source is sock:
                os.write(1, data)
            else:
                sock.sendall(data)
