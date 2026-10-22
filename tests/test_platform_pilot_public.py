# Public subset: private-corpus/operator harness checks are retained privately.
"""Transport credentials, private checkpoint integrity and owned path guards."""


import json


import os


from pathlib import Path


import subprocess


import sys


import threading


from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


import pytest


from tools.platform.consumer import Client, ConsumerError


@pytest.mark.parametrize('url', [
    'http://example.com:8000', 'https://127.0.0.1:8000', 'http://127.0.0.1',
    'http://' + 'user' + ':' + 'password' + '@127.0.0.1:8000', 'http://127.0.0.1:8000/api',
    'http://127.0.0.1:8000?x=1', 'http://127.0.0.1:8000#x'])
def test_client_requires_loopback_origin(url):
    with pytest.raises(ValueError):
        Client(url, 'retrieval-only')


@pytest.mark.parametrize('token', ['', 'a\nb', 'a b', '\x7f', 'é'])
def test_client_rejects_unsafe_token(token):
    with pytest.raises(ValueError):
        Client('http://127.0.0.1:8000', token)


@pytest.fixture
def endpoint():
    requests = []
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass
        def do_POST(self):
            payload = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            requests.append((dict(self.headers), payload))
            if payload['query'] in ('redirect','denied'):
                self.send_response(302 if payload['query'] == 'redirect' else 403)
                self.send_header('Location', '/leak')
                self.end_headers()
                self.wfile.write(b'private-response-body')
                return
            self.send_response(200)
            self.end_headers()
            packs = ([{'doc_id':'unicode-doc' if payload['query'] == 'unicode' else 'included-doc',
                       'citation':{'source_hash':'indexed-hash'}, 'do_not_treat_as_canonical':True}]
                     if payload['query'] in ('withdocument','unicode') else [])
            self.wfile.write(json.dumps({'context_packs':packs, 'warnings':['policy'],
                'retrieval':{'exact_lookup':{'state':'partial'}}, 'excluded_summary':['untrusted']}).encode())
        def do_GET(self):
            requests.append((dict(self.headers), self.path))
            self.send_response(200)
            self.end_headers()
            self.wfile.write(('café — 🧭' if 'unicode-doc' in self.path else 'citation body').encode('utf-8'))
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f'http://127.0.0.1:{server.server_port}', requests
    server.shutdown()
    server.server_close()
    thread.join(timeout=2)


def test_preserves_metadata_and_sends_only_retrieval_token(endpoint):
    url, requests = endpoint
    result = Client(url, 'retrieval-only').retrieve('question', 'lib-example')
    assert result['retrieval']['exact_lookup']['state'] == 'partial'
    assert result['warnings'] == ['policy'] and result['excluded_summary'] == ['untrusted']
    headers, payload = requests[0]
    assert headers['X-Boh-Retrieval-Token'] == 'retrieval-only'
    assert not any('operator' in key.lower() for key in headers)
    assert payload['library_id'] == 'lib-example' and payload['mode'] == 'exploration'


def test_redirect_cannot_forward_credentials(endpoint):
    url, requests = endpoint
    with pytest.raises(ConsumerError, match='HTTP 302'):
        Client(url, 'retrieval-only').retrieve('redirect', 'lib-example')
    assert len(requests) == 1


def test_lookup_opens_only_included_citations_and_labels_reader_hash_unknown(endpoint):
    url, requests = endpoint
    result = Client(url, 'retrieval-only').lookup('withdocument', 'lib-example')
    assert result['retrieval_result']['warnings'] == ['policy']
    assert result['documents'][0]['body'] == 'citation body'
    assert result['documents'][0]['reader_matches_indexed_source_hash'] == 'unknown'
    assert requests[1][1] == '/api/docs/included-doc/content'
    assert len(requests) == 2


def test_lookup_withheld_evidence_never_opens_reader(endpoint):
    url, requests = endpoint
    result = Client(url, 'retrieval-only').lookup('question', 'lib-example', mode='strict_answer')
    assert result['documents'] == []
    assert len(requests) == 1


def test_standalone_cli_unicode_round_trip_without_python_environment(endpoint, tmp_path):
    from tools.platform import consumer
    url, _ = endpoint
    env = {k:v for k,v in os.environ.items() if k.upper() in ('SYSTEMROOT','WINDIR','PATH','TEMP','TMP')}
    env['BOH_CONSUMER_TOKEN'] = 'retrieval-only'
    result = subprocess.run([sys.executable,'-I','-B',str(Path(consumer.__file__).resolve()),
        '--base-url',url,'--library-id','lib-example','--query','unicode'],
        cwd=tmp_path, env=env, capture_output=True, timeout=20)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)['documents'][0]['body'] == 'café — 🧭'


def test_error_hides_body_and_token(endpoint):
    url, _ = endpoint
    with pytest.raises(ConsumerError) as error:
        Client(url, 'retrieval-only').retrieve('denied', 'lib-example')
    assert str(error.value) == 'BOH HTTP 403'


def test_reader_encodes_identity_and_rejects_traversal(endpoint):
    url, requests = endpoint
    client = Client(url, 'retrieval-only')
    assert client.read('doc#one') == 'citation body'
    assert requests[0][1] == '/api/docs/doc%23one/content'
    for identity in ['../x', '..', 'a\\b', '']:
        with pytest.raises(ValueError):
            client.read(identity)
