"""INTERNET-002: characterize an existing HTTPS resource's validator relation.

A read-only three-probe HTTP protocol experiment on a pinned GitHub commit:
200 to discover an entity tag; If-None-Match with that tag; If-None-Match with
an intentionally nonmatching tag. Responses, cache headers and requester-side
elapsed times are retained without attributing processing to fiber or routers.

This is separate from the Git ancestry/merge-base service computation. A 304
is an observation about the responding HTTP server or intermediary, NOT proof
of which device retained the resource nor of a stable physical-path transfer.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
import re
import time
from typing import Any, Callable, Mapping
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

HEX40 = re.compile(r'[0-9a-f]{40}\Z')
REPO = re.compile(r'[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}\Z')
MAX_RESPONSE = 200_000


class HTTPGroundRefused(ValueError):
    """The observed conditional HTTP relation did not meet the test contract."""


def request_commit(repo: str, commit_sha: str, if_none_match: str | None = None) -> dict:
    if not REPO.fullmatch(repo) or not HEX40.fullmatch(commit_sha):
        raise HTTPGroundRefused('unadmitted resource identity')
    if if_none_match is not None and (len(if_none_match) > 256 or '\n' in if_none_match or '\r' in if_none_match):
        raise HTTPGroundRefused('untrusted HTTP validator')
    headers = {'Accept': 'application/vnd.github+json',
               'User-Agent': 'E-CPU-INTERNET-002-conditional-observer'}
    token = os.environ.get('GITHUB_TOKEN', '')
    if token:
        headers['Authorization'] = 'Bearer '+token
    if if_none_match is not None:
        headers['If-None-Match'] = if_none_match
    req = Request(f'https://api.github.com/repos/{repo}/git/commits/{commit_sha}',headers=headers)
    began=time.perf_counter_ns()
    try:
        response = urlopen(req,timeout=15)
    except HTTPError as error:
        if error.code == 304:
            response = error
        else:
            raise HTTPGroundRefused('HTTP service unavailable or rejected probe') from error
    except URLError as exc:
        raise HTTPGroundRefused('HTTPS service unavailable') from exc
    try:
        with response:
            status=response.status if hasattr(response,'status') else response.code
            body=response.read(MAX_RESPONSE+1)
            if len(body)>MAX_RESPONSE:
                raise HTTPGroundRefused('HTTP response exceeds protocol budget')
            attrs={name:response.headers.get(name) for name in
                   ('ETag','Cache-Control','Age','Via','X-GitHub-Request-Id')}
    finally:
        elapsed=max(1,time.perf_counter_ns()-began)
    return {'status':status,'etag':attrs['ETag'],'cache_control':attrs['Cache-Control'],
            'age':attrs['Age'],'via':attrs['Via'],
            'github_request_id':attrs['X-GitHub-Request-Id'],
            'entity_bytes_received':len(body),'entity_sha256':sha256(body).hexdigest(),
            'requester_elapsed_ns':elapsed,
            'body':body}


def observe_conditional_protocol(read: Callable[[str, str, str | None], Mapping],
                                 *, repo: str, commit_sha: str) -> dict:
    if type(repo) is not str or not REPO.fullmatch(repo) or type(commit_sha) is not str or not HEX40.fullmatch(commit_sha):
        raise HTTPGroundRefused('invalid receiver-owned target')
    first=read(repo,commit_sha,None)
    if type(first) is not dict or first.get('status')!=200 or type(first.get('body')) is not bytes:
        raise HTTPGroundRefused('initial response was not a 200 representation')
    if len(first['body'])>MAX_RESPONSE:
        raise HTTPGroundRefused('oversized initial HTTP body')
    try:
        source=json.loads(first['body'])
    except (UnicodeDecodeError,json.JSONDecodeError) as exc:
        raise HTTPGroundRefused('initial content is not Git metadata') from exc
    if type(source) is not dict or source.get('sha')!=commit_sha:
        raise HTTPGroundRefused('HTTPS resource is not externally pinned commit')
    etag=first.get('etag')
    if type(etag) is not str or not etag or len(etag)>256:
        raise HTTPGroundRefused('HTTP service did not return a usable validator')
    second=read(repo,commit_sha,etag)
    mismatch='"e-cpu-internet-002-intentional-miss"'
    if etag==mismatch:
        raise HTTPGroundRefused('test mismatch accidentally equals service validator')
    third=read(repo,commit_sha,mismatch)
    for r in (first,second,third):
        if type(r) is not dict or type(r.get('status')) is not int or type(r.get('body')) is not bytes or type(r.get('requester_elapsed_ns')) is not int or r['requester_elapsed_ns']<1:
            raise HTTPGroundRefused('missing bounded client measurement')
        if r['entity_sha256']!=sha256(r['body']).hexdigest() or r['entity_bytes_received']!=len(r['body']):
            raise HTTPGroundRefused('HTTP payload observation integrity mismatch')
    accepted = (second['status']==304 and second['body']==b'' and third['status']==200 and
                third['body']==first['body'])
    return {
        'schema':'mailcpu.internet-native-http-condition-observation.v1',
        'repo':repo,'commit':commit_sha,'etag':etag,
        'observations':[{
            'request_kind':kind,
            **{k:v for k,v in r.items() if k!='body'},
        } for kind,r in [('normal-get',first),('match-if-none-match',second),
                         ('mismatch-if-none-match',third)]],
        'verdict':('held-out-conditional-304-and-200-observed' if accepted else
                   'conditional-behavior-not-established-on-this-path'),
        'provenance':'client-side-monotonic-duration-and-HTTPS-response-metadata',
        'physical_attribution':'responding HTTP service or intermediary unknown; not a fiber measurement',
    }


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo',required=True)
    parser.add_argument('--commit',required=True)
    args=parser.parse_args()
    result=observe_conditional_protocol(request_commit,repo=args.repo,commit_sha=args.commit)
    print(json.dumps(result,sort_keys=True,indent=2))


if __name__=='__main__':
    main()
