"""Real loopback TLS fixtures; public-address routing replaced only in tests."""
import http.server
import socket
import ssl
import subprocess
import threading
from unittest.mock import patch
import pytest
from services.langgraph.agency import obscura_egress as broker


@pytest.fixture
def tls_site(tmp_path):
    cert, key = tmp_path/'cert.pem', tmp_path/'key.pem'
    subprocess.run(['openssl','req','-x509','-newkey','rsa:2048','-nodes','-keyout',str(key),'-out',str(cert),'-days','1','-subj','/CN=example.test','-addext','subjectAltName=DNS:example.test'],check=True,capture_output=True)
    seen=[]
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            seen.append(self.path)
            if self.path == '/private':
                self.send_response(302); self.send_header('Location','https://127.0.0.1/secret'); self.end_headers(); return
            if self.path == '/loop':
                self.send_response(302); self.send_header('Location','/loop'); self.end_headers(); return
            self.send_response(200); self.send_header('Content-Type','text/html'); self.end_headers()
            self.wfile.write(b'x'*262145 if self.path=='/big' else b'<h1>fixture</h1>')
        def log_message(self,*args): pass
    server=http.server.ThreadingHTTPServer(('127.0.0.1',0),Handler)
    ctx=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);ctx.load_cert_chain(cert,key)
    ctx.minimum_version=ssl.TLSVersion.TLSv1_2
    server.socket=ctx.wrap_socket(server.socket,server_side=True)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    original_dns=socket.getaddrinfo
    connect=socket.create_connection
    client=ssl.create_default_context(cafile=str(cert))
    client.minimum_version=ssl.TLSVersion.TLSv1_2
    def route(address, **kw):
        assert address == ('8.8.8.8',443)
        return connect(('127.0.0.1',server.server_port),**kw)
    def dns(host,*args,**kwargs):
        if host == '127.0.0.1': return original_dns(host,*args,**kwargs)
        return [(2,1,6,'',('8.8.8.8',443))]
    try:
        with patch.object(broker.socket,'getaddrinfo',side_effect=dns), patch.object(broker.socket,'create_connection',side_effect=route), patch.object(broker.ssl,'create_default_context',return_value=client):
            yield seen
    finally:
        server.shutdown();server.server_close();thread.join(timeout=2)


def test_tls_pinned_hostname_and_html(tls_site):
    assert broker.fetch_html('https://example.test/ok') == '<h1>fixture</h1>'
    assert tls_site == ['/ok']


@pytest.mark.parametrize('path,code,count',[('/private','EGRESS_DENIED',1),('/loop','REDIRECT_LIMIT',4),('/big','OUTPUT_LIMIT',1)])
def test_redirect_and_size_refusals(tls_site,path,code,count):
    with pytest.raises(ValueError,match=code): broker.fetch_html('https://example.test'+path)
    assert len(tls_site)==count
