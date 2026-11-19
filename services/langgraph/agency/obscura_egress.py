"""Restricted HTML broker: HTTPS 443, public IPs, pinned connection per hop.

No environment proxy, cookies, authorization headers, JS, or recursive fetching.
The isolated browser receives bytes, never an outbound socket.
"""
import http.client
import os
import hashlib
from datetime import datetime, timezone
import ipaddress
import socket
import ssl
from urllib.parse import urlsplit, urljoin, urlunsplit
from urllib.robotparser import RobotFileParser

MAX_BYTES = 262144


def resolve(url: str) -> tuple[str, str, str]:
    if len(url) > 2048 or any(ord(c) <= 32 or ord(c) == 127 for c in url):
        raise ValueError('URL_REJECTED')
    p = urlsplit(url)
    if p.scheme != 'https' or not p.hostname or p.username is not None or p.password is not None or p.port not in {None, 443}:
        raise ValueError('URL_REJECTED')
    host = p.hostname.encode('idna').decode('ascii')
    addresses = {item[4][0] for item in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)}
    def denied(value):
        ip = ipaddress.ip_address(value)
        transition = ('64:ff9b::/96', '64:ff9b:1::/48', '2002::/16', '2001::/32')
        return not ip.is_global or ip.is_multicast or '%' in value or (ip.version == 6 and any(ip in ipaddress.ip_network(net) for net in transition))
    if not addresses or any(denied(ip) for ip in addresses):
        raise ValueError('EGRESS_DENIED')
    return host, sorted(addresses, key=lambda value:(ipaddress.ip_address(value).version,value))[0], p.path + ('?' + p.query if p.query else '') or '/'


def fetch_html(url: str, *, metadata: bool = False, respect_robots: bool = False, _robots: bool = False, _budget=None):
    budget = [8] if _budget is None else _budget
    policies = {}
    for _ in range(4):
        host, address, path = resolve(url)
        if respect_robots:
            origin = urlsplit(url)
            robots_url = urlunsplit((origin.scheme, origin.netloc, '/robots.txt', '', ''))
            if robots_url not in policies:
                policy = fetch_html(robots_url, metadata=True, _robots=True, _budget=budget)
                parser = RobotFileParser()
                parser.parse(policy['html'].splitlines())
                policies[robots_url] = parser
            if not policies[robots_url].can_fetch('AMC-Research', url):
                raise ValueError('ROBOTS_DENIED')
        if budget[0] <= 0: raise ValueError('REQUEST_LIMIT')
        budget[0] -= 1
        context = ssl.create_default_context()
        context.minimum_version = ssl.TLSVersion.TLSv1_2  # explicit floor, as in security/mtls.py
        connection = http.client.HTTPSConnection(host, timeout=5, context=context)
        # connect directly to the validated numeric address; DNS is never consulted
        # again for this hop. TLS still authenticates the original host.
        proxy = os.environ.get('AMC_OBSCURA_HTTPS_PROXY')
        if proxy:
            peer = urlsplit(proxy)
            if peer.scheme != 'http' or not peer.hostname or peer.username is not None or peer.password is not None or peer.path not in {'', '/'} or peer.query or peer.fragment:
                raise ValueError('PROXY_REJECTED')
            tunnel = http.client.HTTPConnection(peer.hostname, peer.port or 80, timeout=5)
            tunnel.set_tunnel(address, 443)
            tunnel.connect()
            raw = tunnel.sock
            tunnel.sock = None
        else:
            raw = socket.create_connection((address, 443), timeout=5)
        try:
            connection.sock = context.wrap_socket(raw, server_hostname=host)
            connection.request('GET', path, headers={'Accept': 'text/html', 'User-Agent': 'AMC-Research/1'})
            response = connection.getresponse()
            if response.status in {301, 302, 303, 307, 308}:
                target = response.getheader('Location')
                if not target:
                    raise ValueError('INVALID_REDIRECT')
                url = urljoin(url, target)
                continue
            if _robots and response.status == 404:
                return {'html':'', 'http_requests':8-budget[0]}
            if _robots and response.status in {401,403}: raise ValueError('ROBOTS_DENIED')
            allowed_types = {'text/plain'} if _robots else {'text/html'}
            if response.status != 200 or response.getheader('Content-Type', '').split(';')[0].strip().lower() not in allowed_types:
                raise ValueError('RESPONSE_REJECTED')
            data = response.read(MAX_BYTES + 1)
            if len(data) > MAX_BYTES:
                raise ValueError('OUTPUT_LIMIT')
            html = data.decode('utf-8', errors='strict')
            if metadata:
                return {'html':html, 'final_url':url, 'retrieved_at':datetime.now(timezone.utc).isoformat(),
                        'source_sha256':hashlib.sha256(data).hexdigest(), 'http_requests':8-budget[0], 'robots_checked':respect_robots}
            return html
        finally:
            connection.close()
            raw.close()
    raise ValueError('REDIRECT_LIMIT')


def retrieve(url: str, *, timeout: float = 25) -> dict:
    """Killable subprocess bounds DNS, TLS, redirects and slow/trickling bodies.

    No implicit environment proxies/credentials are inherited. Only an explicit
    server-configured proxy and certificate trust path are permitted.
    """
    import json
    import signal
    import subprocess
    import sys
    import tempfile
    from pathlib import Path
    if not 0 < timeout <= 25:
        raise ValueError('INVALID_DEADLINE')
    env = {'PATH':'/usr/bin:/bin','LANG':'C.UTF-8'}
    for key in ('AMC_OBSCURA_HTTPS_PROXY', 'SSL_CERT_FILE'):
        if os.environ.get(key): env[key] = os.environ[key]
    with tempfile.TemporaryDirectory(prefix='amc-obscura-broker-') as tmp:
        out = Path(tmp)/'out'
        with out.open('wb') as stream:
            process = subprocess.Popen(['prlimit','--as=268435456','--cpu=10','--fsize=2097152','--nofile=64','--core=0',
                sys.executable, '-I', str(Path(__file__).resolve())], stdin=subprocess.PIPE, stdout=stream,
                stderr=subprocess.DEVNULL, env=env, start_new_session=True)
            try:
                process.communicate(url.encode(), timeout=timeout)
            except subprocess.TimeoutExpired:
                raise RuntimeError('BROKER_DEADLINE') from None
            finally:
                try: os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError: pass
                process.wait()
        if process.returncode: raise RuntimeError('BROKER_FETCH_FAILED')
        result = json.loads(out.read_bytes())
        if result.get('error'): raise ValueError(result['error'])
        return result


if __name__ == '__main__':
    import json
    import sys
    try:
        result = fetch_html(sys.stdin.buffer.read(2049).decode(), metadata=True, respect_robots=True)
    except ValueError as error:
        code = str(error)
        result = {'error':code if code in {'ROBOTS_DENIED','REQUEST_LIMIT','URL_REJECTED','EGRESS_DENIED','PROXY_REJECTED','INVALID_REDIRECT','REDIRECT_LIMIT','RESPONSE_REJECTED','OUTPUT_LIMIT'} else 'RESPONSE_REJECTED'}
    except Exception:
        result = {'error':'BROKER_FETCH_FAILED'}
    sys.stdout.write(json.dumps(result))
