import os
from pathlib import Path
import pytest
from services.langgraph.agency.obscura_worker import extract


def test_invalid_inputs_do_not_launch():
    with pytest.raises(ValueError, match='INPUT_LIMIT'):
        extract('x'*262145, Path('/absent'))
    with pytest.raises(ValueError, match='UNSUPPORTED_FORMAT'):
        extract('', Path('/absent'), format='cookies')


def test_isolated_real_binary():
    binary = os.environ.get('TEST_OBSCURA_BIN')
    if not binary:
        pytest.skip('explicit verified local binary required')
    output = extract('<h1>Fixture</h1><script>document.querySelector("h1").textContent="Computed fixture"</script>', Path(binary))
    assert 'Computed fixture' in output


def test_browser_cannot_reach_host_loopback():
    import http.server
    import threading
    binary = os.environ.get('TEST_OBSCURA_BIN')
    if not binary:
        pytest.skip('explicit verified local binary required')
    requests = []
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            requests.append(self.path)
            self.send_response(200)
            self.end_headers()
        def log_message(self, *args):
            pass
    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        html = f'<p id="result">pending</p><script>fetch("http://127.0.0.1:{server.server_port}/canary").then(()=>document.querySelector("p").textContent="LEAK").catch(()=>document.querySelector("p").textContent="denied")</script>'
        assert 'denied' in extract(html, Path(binary))
        assert requests == []
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_concurrency_refuses_third_and_releases():
    from services.langgraph.agency.obscura_worker import slot
    with slot():
        with slot():
            with pytest.raises(RuntimeError, match='CONCURRENCY_LIMIT'):
                with slot():
                    pass
    with slot():
        pass


def test_cancel_before_launch():
    from threading import Event
    event=Event();event.set()
    with pytest.raises(RuntimeError,match='CANCELLED'):
        extract('<p>fixture</p>',Path('/absent'),cancel=event)


def test_real_cancellation_releases_slot():
    import threading
    import time
    binary=os.environ.get('TEST_OBSCURA_BIN')
    if not binary or not os.environ.get('AMC_OBSCURA_RUNTIME_IMAGE'):
        pytest.skip('explicit bounded local runtime required')
    cancel=threading.Event()
    failures=[]
    def run():
        try: extract('<script>while(true){}</script>',Path(binary),cancel=cancel)
        except RuntimeError as error: failures.append(str(error))
    thread=threading.Thread(target=run);thread.start()
    time.sleep(0.5);cancel.set();thread.join(timeout=12)
    assert not thread.is_alive()
    assert failures==['CANCELLED']
    from services.langgraph.agency.obscura_worker import slot
    with slot():
        with slot(): pass


def test_real_memory_exhaustion_refuses_success():
    binary=os.environ.get('TEST_OBSCURA_BIN')
    if not binary or not os.environ.get('AMC_OBSCURA_RUNTIME_IMAGE'):
        pytest.skip('explicit bounded local runtime required')
    html='<script>let allocations=[];while(true){allocations.push(new Uint8Array(16*1024*1024).fill(1));}</script>'
    with pytest.raises(RuntimeError,match='BLOCKED_WORKER|WORKER_TIMEOUT'):
        extract(html,Path(binary))


def test_large_page_does_not_use_command_line_payload():
    binary=os.environ.get('TEST_OBSCURA_BIN')
    if not binary or not os.environ.get('AMC_OBSCURA_RUNTIME_IMAGE'):
        pytest.skip('explicit bounded local runtime required')
    html='<h1>Large fixture</h1><!--'+('x'*180000)+'-->'
    assert 'Large fixture' in extract(html,Path(binary))


def test_browser_cannot_read_host_file(tmp_path):
    binary=os.environ.get('TEST_OBSCURA_BIN')
    if not binary or not os.environ.get('AMC_OBSCURA_RUNTIME_IMAGE'):
        pytest.skip('explicit bounded local runtime required')
    canary=tmp_path/'fictional-canary.txt'
    canary.write_text('FIXTURE_HOST_CANARY_MUST_STAY_OUTSIDE')
    html=f'<p>pending</p><script>fetch("file://{canary}").then(r=>r.text()).then(t=>document.querySelector("p").textContent=t).catch(()=>document.querySelector("p").textContent="denied")</script>'
    text=extract(html,Path(binary))
    assert 'FIXTURE_HOST_CANARY_MUST_STAY_OUTSIDE' not in text
    assert 'denied' in text
