"""INTERNET-003 remote HTTPS condition check against a precisely pinned Git blob.

Bounded read-only external probe. ETag/304 is a *service protocol observation*,
not evidence that a particular CDN, router, or physical propagation medium
performed the conditional selection. This script never bypasses permissions.
"""
from __future__ import annotations
import argparse
import base64
import hashlib
import json
from pathlib import Path
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from typing import Callable

BLOB_SHA1='46958c491ec504e2f8562ca37b8b152d441376f0'
SOURCE_SHA256='ece11d917a3c4bf1240e8e02a29b94ff2761fcdf8e37504bc9660d382b0f5c67'
ENDPOINT='https://api.github.com/repos/Kier73/E-CPU/git/blobs/'+BLOB_SHA1
MAX_BYTES=128_000

class HttpsPathRefused(ValueError):pass


def strict_json(blob: bytes) -> dict:
    def pairs(rows):
        result={}
        for k,v in rows:
            if k in result:raise HttpsPathRefused('duplicate remote JSON key')
            result[k]=v
        return result
    try:
        obj=json.loads(blob,object_pairs_hook=pairs)
    except (ValueError,UnicodeDecodeError) as exc:
        raise HttpsPathRefused('unparseable bounded remote JSON') from exc
    if type(obj) is not dict:raise HttpsPathRefused('remote JSON must be an object')
    return obj


def raw_https_request(endpoint: str, *, etag: str | None = None) -> dict:
    if endpoint != ENDPOINT:raise HttpsPathRefused('remote HTTP observation outside pinned owned source')
    headers={'Accept':'application/vnd.github+json',
             'Accept-Encoding':'identity','User-Agent':'E-CPU-Internet003-Ground-Observer'}
    if etag is not None:
        if type(etag) is not str or '\n' in etag or '\r' in etag:
            raise HttpsPathRefused('invalid HTTP validator')
        headers['If-None-Match']=etag
    started=time.monotonic_ns()
    req=Request(endpoint,headers=headers)
    try:
        with urlopen(req,timeout=20) as response:
            status=response.status
            body=response.read(MAX_BYTES+1)
            result_headers={k.lower():v for k,v in response.headers.items()}
    except HTTPError as exc:
        if exc.code != 304: raise
        status=304
        body=exc.read(MAX_BYTES+1)
        result_headers={k.lower():v for k,v in exc.headers.items()}
    elapsed=max(1,time.monotonic_ns()-started)
    if len(body)>MAX_BYTES:raise HttpsPathRefused('remote response exceeds budget')
    return {'status':status,'headers':result_headers,'body':body,'elapsed_ns':elapsed}


def verify_live_https(read: Callable,*, external_blob_sha1: str, external_source_sha256: str,
                      require_304: bool=False) -> dict:
    """Require external source pins; select observed service behavior without inventing it."""
    if external_blob_sha1 != BLOB_SHA1 or external_source_sha256 != SOURCE_SHA256:
        raise HttpsPathRefused('receiver-owned source pins differ from declared source')
    first=read(ENDPOINT,etag=None)
    if type(first) is not dict or first.get('status') != 200:
        raise HttpsPathRefused('remote unconditional source not observed')
    etag=first.get('headers',{}).get('etag')
    if type(etag) is not str or not etag or len(etag)>256:
        raise HttpsPathRefused('origin did not expose a bounded HTTP entity tag')
    body=first.get('body')
    if type(body) is not bytes or len(body)>MAX_BYTES:raise HttpsPathRefused('unbounded source body')
    item=strict_json(body)
    if item.get('sha')!=external_blob_sha1 or item.get('encoding')!='base64' or type(item.get('content')) is not str:
        raise HttpsPathRefused('Git blob identity differs from the external manifest')
    try:decoded=base64.b64decode(item['content'].replace('\n',''),validate=True)
    except ValueError as exc:raise HttpsPathRefused('Git blob is not valid base64') from exc
    actual_git=hashlib.sha1(b'blob '+str(len(decoded)).encode()+b'\0'+decoded).hexdigest()
    if actual_git!=external_blob_sha1 or hashlib.sha256(decoded).hexdigest()!=external_source_sha256:
        raise HttpsPathRefused('remote source violates independently supplied content identity')
    second=read(ENDPOINT,etag=etag)
    if type(second) is not dict or type(second.get('body')) is not bytes:
        raise HttpsPathRefused('remote conditional response malformed')
    cond_status=second.get('status')
    if cond_status==304:
        if second['body']:
            raise HttpsPathRefused('304 unexpectedly included response body')
    elif cond_status==200:
        if second['body']!=body:
            raise HttpsPathRefused('remote conditional response changed the pinned representation')
        if require_304:
            raise HttpsPathRefused('service returned 200, not measured conditional 304')
    else:raise HttpsPathRefused('unexpected conditional HTTP status')
    return {'schema':'mailcpu.internet-003-remote-https.v1','source_sha256':external_source_sha256,
            'blob_sha1':external_blob_sha1,'source_bytes':len(decoded),
            'observed_entity_tag':etag,'conditional_status':cond_status,
            'conditional_response_body_bytes':len(second['body']),
            'conditional_selection_observed':cond_status==304,
            'unconditional_elapsed_ns':first.get('elapsed_ns'),
            'conditional_elapsed_ns':second.get('elapsed_ns'),
            'endpoint_kind':'third-party-Git-service-over-public-HTTPS',
            'nonclaims':['no-proof-of-proxy-versus-origin-attribution',
                          'no-evidence-of-passive-fiber-logic',
                          'no-remote-ECPU-executor-installed']}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--expected-source-sha256',required=True)
    p.add_argument('--expected-blob-sha1',required=True)
    p.add_argument('--require-304',action='store_true')
    p.add_argument('--output',type=Path)
    args=p.parse_args()
    report=verify_live_https(raw_https_request,external_blob_sha1=args.expected_blob_sha1,
              external_source_sha256=args.expected_source_sha256,require_304=args.require_304)
    encoded=json.dumps(report,sort_keys=True,indent=2)+'\n'
    if args.output:
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(encoded)
    else:print(encoded)

if __name__=='__main__':main()
