"""Stdlib HTTP evidence client; no BOH imports or operator credentials.

Run: python consumer.py --base-url http://127.0.0.1:PORT --library-id ID --query TEXT
Set BOH_CONSUMER_TOKEN in the calling process; it is never printed or persisted.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener


class ConsumerError(RuntimeError):
    pass


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class Client:
    """Loopback-only pilot client; logical library scope is explicit per request."""
    def __init__(self, base_url: str, token: str, timeout: float = 30):
        url = urlsplit(base_url)
        if (url.scheme != 'http' or url.hostname != '127.0.0.1' or not url.port
                or url.username or url.password or url.path not in ('', '/')
                or url.query or url.fragment):
            raise ValueError('a literal loopback HTTP origin with an explicit port is required')
        if not token or any(ord(c) < 33 or ord(c) > 126 for c in token):
            raise ValueError('a nonempty printable retrieval token is required')
        self.base_url = base_url.rstrip('/')
        self._token = token
        self.timeout = timeout
        self._opener = build_opener(ProxyHandler({}), NoRedirect())

    def _request(self, path: str, payload=None, *, text=False):
        body = None if payload is None else json.dumps(payload).encode('utf-8')
        req = Request(self.base_url + path, data=body, headers={
            'X-BOH-Retrieval-Token': self._token, 'Content-Type': 'application/json'})
        try:
            with self._opener.open(req, timeout=self.timeout) as response:
                raw = response.read(4_000_001)
                if len(raw) > 4_000_000:
                    raise ConsumerError('response exceeds pilot size limit')
                value = raw.decode('utf-8')
                return value if text else json.loads(value)
        except HTTPError as exc:
            raise ConsumerError(f'BOH HTTP {exc.code}') from None
        except (URLError, TimeoutError, OSError):
            raise ConsumerError('BOH unavailable or request timed out') from None
        except (UnicodeError, ValueError):
            raise ConsumerError('BOH returned an invalid response') from None

    def libraries(self):
        return self._request('/api/libraries')['libraries']

    def retrieve(self, query: str, library_id: str, *, mode='exploration', limit=5):
        if not query.strip() or not library_id.strip():
            raise ValueError('query and library_id are required')
        if mode not in ('exploration', 'strict_answer', 'audit_provenance'):
            raise ValueError('unsupported retrieval mode')
        result = self._request('/api/retrieve', {
            'query':query, 'library_id':library_id, 'mode':mode, 'limit':limit,
            'max_context_chars':30000, 'include_lineage':True})
        if not isinstance(result, dict) or not isinstance(result.get('context_packs'), list):
            raise ConsumerError('BOH response lacks context_packs')
        # Preserve every warning, gate, exclusion, coverage and authority field.
        return result

    def read(self, doc_id: str):
        if not doc_id or '/' in doc_id or '\\' in doc_id or doc_id in ('.', '..'):
            raise ValueError('invalid document identity')
        return self._request('/api/docs/'+quote(doc_id, safe='')+'/content', text=True)

    def lookup(self, query: str, library_id: str, *, mode='exploration', limit=5):
        """Retrieve, then open only included citations; keep both deliveries distinct."""
        result = self.retrieve(query, library_id, mode=mode, limit=limit)
        documents = []
        seen = set()
        for pack in result['context_packs']:
            doc_id = pack.get('doc_id')
            if not doc_id or doc_id in seen:
                continue
            seen.add(doc_id)
            document = {'doc_id':doc_id, 'citation':pack.get('citation'),
                        'authority_state':pack.get('authority_state'),
                        'do_not_treat_as_canonical':pack.get('do_not_treat_as_canonical'),
                        'source_lifecycle':pack.get('source_lifecycle'),
                        'reader_matches_indexed_source_hash':'unknown',
                        'warnings':['Reader returns the current file body; its indexed source hash is not verified.']}
            try:
                body = self.read(doc_id)
                document.update(body=body, body_sha256=hashlib.sha256(body.encode('utf-8')).hexdigest())
            except ConsumerError as exc:
                document.update(body=None, error=str(exc))
            documents.append(document)
        return {'contract':'boh-http-consumer-v0.1', 'retrieval_result':result, 'documents':documents}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', required=True)
    parser.add_argument('--library-id', required=True)
    parser.add_argument('--query', required=True)
    parser.add_argument('--mode', default='exploration',
                        choices=['exploration','strict_answer','audit_provenance'])
    args = parser.parse_args()
    try:
        result = Client(args.base_url, os.environ.get('BOH_CONSUMER_TOKEN', '')).lookup(
            args.query, args.library_id, mode=args.mode)
    except (ValueError, ConsumerError) as exc:
        parser.exit(2, str(exc)+'\n')
    # ASCII JSON round-trips Unicode even under Windows redirected cp1252 and -I.
    print(json.dumps(result, ensure_ascii=True, indent=2))


if __name__ == '__main__':
    main()
