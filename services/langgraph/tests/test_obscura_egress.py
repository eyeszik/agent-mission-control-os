import socket
from unittest.mock import patch
import pytest
from services.langgraph.agency.obscura_egress import resolve


@pytest.mark.parametrize('url', ['http://example.com', 'file:///etc/passwd', 'https://u:p@example.com', 'https://example.com:8443', 'https://example.com/\r\nX:1'])
def test_disallowed_url_never_resolves(url):
    with patch('socket.getaddrinfo', side_effect=AssertionError('DNS must not run')):
        with pytest.raises(ValueError, match='URL_REJECTED'):
            resolve(url)


@pytest.mark.parametrize('ip', ['127.0.0.1','10.0.0.1','169.254.169.254','::1','::ffff:127.0.0.1','192.168.1.1','100.64.0.1'])
def test_private_dns_denied(ip):
    with patch('socket.getaddrinfo', return_value=[(2,1,6,'',(ip,443))]):
        with pytest.raises(ValueError, match='EGRESS_DENIED'):
            resolve('https://example.com')


def test_mixed_dns_denied():
    with patch('socket.getaddrinfo', return_value=[(2,1,6,'',('8.8.8.8',443)),(2,1,6,'',('10.0.0.1',443))]):
        with pytest.raises(ValueError, match='EGRESS_DENIED'):
            resolve('https://example.com')


def test_dns_rebinding_is_rechecked():
    with patch('socket.getaddrinfo', side_effect=[[(2,1,6,'',('8.8.8.8',443))],[(2,1,6,'',('127.0.0.1',443))]]):
        assert resolve('https://example.com/a')[1] == '8.8.8.8'
        with pytest.raises(ValueError, match='EGRESS_DENIED'):
            resolve('https://example.com/b')


def test_supervisor_bounds_blocked_dns_or_slow_transport(monkeypatch):
    import subprocess
    import sys
    import time
    from services.langgraph.agency.obscura_egress import retrieve
    real_popen=subprocess.Popen
    children=[]
    def stalled(*args,**kwargs):
        # Replace only the broker program; exercise the actual supervisor and
        # process-group termination, without relying on flaky external DNS.
        process=real_popen([sys.executable,'-c','import time;time.sleep(10)'],**kwargs)
        children.append(process)
        return process
    monkeypatch.setattr(subprocess,'Popen',stalled)
    before=time.monotonic()
    with pytest.raises(RuntimeError,match='BROKER_DEADLINE'):
        retrieve('https://example.test',timeout=0.1)
    assert time.monotonic()-before < 3
    assert children[0].poll() is not None


def test_supervisor_denies_private_url():
    from services.langgraph.agency.obscura_egress import retrieve
    with pytest.raises(ValueError,match='EGRESS_DENIED'):
        retrieve('https://127.0.0.1')


@pytest.mark.parametrize('ip',['224.0.0.1','ff02::1','64:ff9b::a00:1','64:ff9b:1::1','2002:7f00:1::','2001::1'])
def test_multicast_and_transition_networks_denied(ip):
    with patch('socket.getaddrinfo',return_value=[(2,1,6,'',(ip,443))]):
        with pytest.raises(ValueError,match='EGRESS_DENIED'): resolve('https://example.test')


def test_robots_refusal_stops_page_request(monkeypatch):
    from services.langgraph.agency import obscura_egress as broker
    actual=broker.fetch_html
    calls=[]
    monkeypatch.setattr(broker,'resolve',lambda url:('example.test','8.8.8.8','/private'))
    def robots(url,**options):
        calls.append(url)
        assert options['_robots']
        return {'html':'User-agent: *\nDisallow: /private\n','http_requests':1}
    monkeypatch.setattr(broker,'fetch_html',robots)
    with pytest.raises(ValueError,match='ROBOTS_DENIED'):
        actual('https://example.test/private',respect_robots=True)
    assert calls==['https://example.test/robots.txt']
