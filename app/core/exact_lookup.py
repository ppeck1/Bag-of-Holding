"""Request-local bounded exact matching; no schema, writes or authority inference."""
from __future__ import annotations
from contextlib import contextmanager
import sqlite3
import time
import json

MAX_MATCHES=512
MAX_CALLBACKS=20_000
MAX_VM_STEPS=2_000_000
MAX_SECONDS=1.5
MAX_FIELD_BYTES=65_536
MAX_EXAMINED_BYTES=64*1024*1024
MAX_MATERIALIZED_BYTES=8*1024*1024
MAX_MATERIALIZED_ROWS=8192
PROGRESS_INTERVAL=1000


class LookupCutoff(Exception):
    """Only this expected cutoff is suppressed by the governed request guard."""


class Budget:
    def __init__(self,matcher):
        self.matcher=matcher
        self.started=time.perf_counter()
        self.callbacks=0
        self.examined_bytes=0
        self.materialized_bytes=0
        self.materialized_rows=0
        self.vm_steps=0
        self.failure=None
        self.large_field=False
        self.chunks=None
        self.cards=None
        self.match_limit=MAX_MATCHES

    def stop(self,reason):
        self.failure=reason
        raise LookupCutoff(reason)

    def check(self):
        if self.failure:
            raise LookupCutoff(self.failure)
        if time.perf_counter()-self.started>=MAX_SECONDS:
            self.stop('time_budget')
        if self.vm_steps>=MAX_VM_STEPS:
            self.stop('vm_budget')

    def progress(self):
        self.vm_steps+=PROGRESS_INTERVAL
        try:
            self.check()
        except LookupCutoff:
            return 1
        return 0

    def examine(self):
        self.check()
        if self.callbacks>=MAX_CALLBACKS:
            self.stop('examined_field_budget')
        self.callbacks+=1

    def match(self,*fields):
        self.examine()
        values=tuple(str(value or '') for value in fields)
        size=sum(len(value.encode('utf-8')) for value in values)
        if size>MAX_FIELD_BYTES:
            self.large_field=True
            return 0
        if self.examined_bytes+size>MAX_EXAMINED_BYTES:
            self.stop('examined_byte_budget')
        self.examined_bytes+=size
        return int(self.matcher(*values))

    def oversized(self):
        self.examine()
        self.large_field=True
        return 0

    def match_card(self,topic,plane,card_type,payload_json):
        self.check()
        payload=json.loads(payload_json or '{}')
        if not isinstance(payload,dict):
            return self.oversized()
        # Match the established Python str(value or '') coercion, including
        # JSON booleans; SQLite json_extract otherwise converts true to 1.
        return self.match(topic,plane,card_type,*(str(payload.get(key) or '')
                          for key in ('title','summary','text')))

    def materialize(self,row):
        self.check()
        size=sum(len(value.encode('utf-8')) if isinstance(value,str) else len(value)
                 if isinstance(value,bytes) else 8 for value in row.values())
        if self.materialized_rows>=MAX_MATERIALIZED_ROWS or self.materialized_bytes+size>MAX_MATERIALIZED_BYTES:
            self.stop('materialization_budget')
        self.materialized_rows+=1
        self.materialized_bytes+=size

    def register(self,connection):
        connection.create_function('boh_exact_match',-1,self.match)
        connection.create_function('boh_exact_oversized',0,self.oversized)
        connection.create_function('boh_exact_card',4,self.match_card)

    def predicate(self,*fields,guard='1=1',function='boh_exact_match'):
        # CASE prevents passing a huge SQLite text value to a Python callback.
        size='+'.join(f"length(CAST(COALESCE({field},'') AS BLOB))" for field in fields)
        return (f' AND CASE WHEN ({guard}) THEN CASE WHEN ({size})>{MAX_FIELD_BYTES} '
                f"THEN boh_exact_oversized() ELSE {function}({','.join(fields)}) END ELSE 0 END")

    def public(self):
        exhausted=self.chunks is True and self.cards is True
        state=('complete' if exhausted and not self.failure and not self.large_field else
               'unknown' if self.failure and self.chunks is None and self.cards is None else 'partial')
        domain=lambda value:('unknown' if value is None else 'partial'
                             if self.failure or self.large_field or not value else 'complete')
        return {'state':state,'population':'indexed_evidence_in_requested_scope',
                'domains':{'chunks':domain(self.chunks),'cards':domain(self.cards)},
                'reason':'work_budget' if self.failure else 'field_budget' if self.large_field else
                         'scope_exhausted' if exhausted else 'matching_evidence_budget',
                'continuation_available':False,'output_completeness_implied':False}


@contextmanager
def guard(budget):
    try:
        yield
        if budget is not None:
            budget.check()
    except LookupCutoff:
        if budget is None:
            raise


def read(connection,query,params,budget,*,one=False):
    budget.check()
    connection.set_progress_handler(budget.progress,PROGRESS_INTERVAL)
    try:
        cursor=connection.execute(query,params)
        rows=[]
        for row in cursor:
            value=dict(row)
            budget.materialize(value)
            rows.append(value)
            if one:
                break
        return (rows[0] if rows else None) if one else rows
    except sqlite3.OperationalError:
        # SQLite translates a callback cutoff into OperationalError. Other SQL
        # errors keep their original exception and are never fail-soft here.
        if budget.failure:
            raise LookupCutoff(budget.failure) from None
        raise
    finally:
        connection.set_progress_handler(None,0)


def candidates(snapshot,fts_sql,fts_params,scan_sql,scan_params,budget):
    rows=snapshot.fetchall('SELECT * FROM ('+fts_sql+') UNION ALL SELECT * FROM ('+scan_sql+')',
                           tuple(fts_params)+tuple(scan_params))
    original,scanned=[],[]
    for row in rows:
        (scanned if row.pop('_exact_scan',0) else original).append(row)
    budget.chunks=len(scanned)<=budget.match_limit
    for row in original:
        row['retrieval_source']='fts'
    for row in scanned:
        row['retrieval_source']='exact_lookup'
    return original,scanned[:budget.match_limit]


def card_filters(filters):
    """Push down the existing card filter values without changing their meaning."""
    values={'doc_id':'card.doc_id','status':"json_extract(card.payload_json,'$.status')",
            'authority_state':"COALESCE(NULLIF(json_extract(card.payload_json,'$.authority_state'),''),json_extract(card.authority_json,'$.state'))",
            'canonical_layer':"json_extract(card.payload_json,'$.canonical_layer')",
            'project':"json_extract(card.payload_json,'$.project')",'chunk_type':"'plane_card'"}
    clauses=[]
    params=[]
    for key,value in filters.items():
        if key=='library_id':
            continue
        clauses.append(' AND '+values[key]+' = ?')
        params.append(value)
    return ''.join(clauses),params
