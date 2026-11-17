"""INTERNET-003: controlled Nginx HTTP path as a real, active observer-host.

The Nginx origin and caching proxy are unmodified installed services.  The
experiment owns both listeners, an ephemeral directory and a loopback-only
network.  No passive cable is claimed to execute the HTTP operations.
"""
from __future__ import annotations

import argparse
import gzip
import zlib
import hashlib
import http.client
import json
import os
from pathlib import Path
import shutil
import socket
import statistics
import subprocess
import tempfile
import time
from typing import Mapping

SCHEMA = 'mailcpu.internet-path-http.v1'
MAX_WIRE = 1_000_000

class InternetPathRefused(ValueError):
    pass


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False, ensure_ascii=False).encode()


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def port() -> int:
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def make_data(*, mutation: bool = False) -> bytes:
    # Text compresses well, but looks irregular across blocks; no remote payload.
    blocks = [(f'GROUND-{i%37:02d}/' + 'observable-operator-' * (3 + i%3)) for i in range(800)]
    data = ''.join(blocks).encode()
    if mutation:
        data += b'-modified-by-the-origin-with-different-source-identity-' * 23
    return data


def render_conf(root: Path, origin: int, proxy: int) -> tuple[Path, Path]:
    """Build two stand-alone Nginx configurations; both use real TCP sockets."""
    logs = root / 'logs'
    logs.mkdir()
    (root / 'cache').mkdir()
    root.chmod(0o755)  # Allow the nginx worker to traverse the ephemeral fixture.
    if hasattr(os, 'geteuid') and os.geteuid() == 0:
        import pwd
        worker = pwd.getpwnam('www-data')
        os.chown(root / 'cache', worker.pw_uid, worker.pw_gid)
    (root / 'static').mkdir(exist_ok=True)
    for name in ('origin','proxy'):
        (logs / (name+'.log')).write_bytes(b'')
    origin_conf = root/'origin.conf'
    proxy_conf = root/'proxy.conf'
    shared = f"""worker_processes 1;
error_log {root}/logs/error.log warn;
events {{ worker_connections 128; }}
"""
    origin_conf.write_text(shared+f"""pid {root}/origin.pid;
http {{
  access_log {root}/logs/origin.log 'main';
  server {{
    listen 127.0.0.1:{origin};
    server_name localhost;
    location = /payload.bin {{
       alias {root}/static/payload.bin;
       default_type application/octet-stream;
       add_header Cache-Control 'public, max-age=120' always;
    }}
  }}
}}
""".replace("access_log "+str(root)+"/logs/origin.log 'main';",f"access_log {root}/logs/origin.log;"))
    proxy_conf.write_text(shared+f"""pid {root}/proxy.pid;
http {{
  proxy_cache_path {root}/cache levels=1:2 keys_zone=ecpu_path:10m inactive=10m max_size=50m use_temp_path=off;
  access_log {root}/logs/proxy.log;
  server {{
    listen 127.0.0.1:{proxy};
    server_name localhost;
    location = /payload.bin {{
      proxy_pass http://127.0.0.1:{origin};
      proxy_set_header Host localhost;
      proxy_set_header Accept-Encoding '';
      proxy_cache ecpu_path;
      proxy_cache_key $request_uri;
      proxy_cache_valid 200 120s;
      proxy_cache_revalidate on;
      proxy_force_ranges on;
      proxy_cache_bypass $http_x_ecpu_bypass;
      proxy_no_cache $http_x_ecpu_bypass;
      gzip on;
      gzip_min_length 256;
      gzip_types application/octet-stream;
      gzip_vary on;
      add_header X-ECpu-Cache $upstream_cache_status always;
    }}
  }}
}}
""")
    return origin_conf, proxy_conf


class NginxPath:
    def __init__(self, root: Path):
        self.root = root
        self.origin = port()
        self.proxy = port()
        while self.proxy == self.origin:
            self.proxy = port()
        self.processes = []

    def __enter__(self):
        (self.root/'static').mkdir(parents=True, exist_ok=True)
        (self.root/'static'/'payload.bin').write_bytes(make_data())
        confs = render_conf(self.root, self.origin, self.proxy)
        for conf, bind_port in zip(confs, (self.origin, self.proxy)):
            process = subprocess.Popen(['nginx', '-c', str(conf), '-p', str(self.root), '-g', 'daemon off;'],
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self.processes.append(process)
            for _ in range(150):
                try:
                    with socket.create_connection(('127.0.0.1', bind_port), timeout=.15):
                        break
                except OSError:
                    if process.poll() is not None:
                        raise InternetPathRefused('nginx exited during controlled startup: '+(self.root/'logs/error.log').read_text()[-1000:])
                    time.sleep(.015)
            else:
                raise InternetPathRefused('nginx did not bind controlled listener')
        return self

    def stop_origin(self) -> None:
        p = self.processes[0]
        if p.poll() is None:
            p.terminate()
            p.wait(timeout=5)

    def __exit__(self, *exc):
        for p in reversed(self.processes):
            p.terminate()
        for p in reversed(self.processes):
            try:p.wait(timeout=5)
            except subprocess.TimeoutExpired:p.kill();p.wait(timeout=5)
        return False

    def request(self, *, via_proxy: bool, headers: Mapping[str, str] | None = None) -> dict:
        host_port = self.proxy if via_proxy else self.origin
        connection = http.client.HTTPConnection('127.0.0.1', host_port, timeout=8)
        started = time.perf_counter_ns()
        try:
            connection.request('GET', '/payload.bin', headers=dict(headers or {}))
            response = connection.getresponse()
            body = response.read(MAX_WIRE+1)
            if len(body) > MAX_WIRE:
                raise InternetPathRefused('unbounded HTTP response')
            observed_headers = {k.lower():v for k,v in response.getheaders()}
            status = response.status
        finally:
            connection.close()
        return {'status':status,'headers':observed_headers,'body':body,
                'elapsed_ns':max(1, time.perf_counter_ns()-started),
                'route':'proxy' if via_proxy else 'direct-origin'}

    def origin_requests(self) -> int:
        return len((self.root/'logs'/'origin.log').read_text().splitlines())


def verify_response(observed: dict, *, current_source: bytes,
                    mode: str, supplied_etag: str | None = None,
                    offset: int = 0, length: int | None = None,
                    baseline_reference: dict | None = None) -> dict:
    """Independent receiver check of one *particular* response snapshot.

    The expected source is supplied by the receiver. We do NOT trust a hash
    or source/body equivalence claimed only inside the response headers.
    """
    if type(current_source) is not bytes or not 0<len(current_source)<=MAX_WIRE:
        raise InternetPathRefused('receiver requires exact source bytes')
    if type(observed) is not dict or type(observed.get('status')) is not int or type(observed.get('body')) is not bytes:
        raise InternetPathRefused('malformed observed HTTP response')
    status, body = observed['status'],observed['body']
    headers = observed.get('headers')
    if type(headers) is not dict:
        raise InternetPathRefused('missing checked response headers')
    etag = headers.get('etag')
    if type(etag) is not str or not (etag.startswith('"') or (mode == 'complete' and etag.startswith('W/"'))) or not etag.endswith('"'):
        raise InternetPathRefused('missing strong representation ETag')
    if mode == 'complete':
        if status != 200:
            raise InternetPathRefused('expected complete 200 response')
        encoding=headers.get('content-encoding')
        if encoding not in (None,'gzip'):
            raise InternetPathRefused('unrecognized content encoding')
        if encoding == 'gzip':
            try:
                decoder=zlib.decompressobj(16+zlib.MAX_WBITS)
                actual=decoder.decompress(body,len(current_source)+1)
            except zlib.error as exc:
                raise InternetPathRefused('malformed gzip representation') from exc
            if not decoder.eof or decoder.unused_data or decoder.unconsumed_tail:
                raise InternetPathRefused('gzip exceeds original representation bounds')
        else:actual=body
        if actual != current_source:
            raise InternetPathRefused('complete response differs from independent source pin')
    elif mode == 'range':
        if type(offset) is not int or offset < 0 or type(length) is not int or length < 1 or offset+length>len(current_source):
            raise InternetPathRefused('range request outside source')
        if status != 206 or headers.get('content-range')!= f'bytes {offset}-{offset+length-1}/{len(current_source)}':
            raise InternetPathRefused('wrong status or range metadata')
        if body != current_source[offset:offset+length]:
            raise InternetPathRefused('range result differs from source pin')
    elif mode == 'conditional':
        if (status != 304 or body or supplied_etag != etag
            or type(baseline_reference) is not dict
            or baseline_reference.get('mode') != 'complete'
            or baseline_reference.get('status') != 200
            or baseline_reference.get('source_sha256') != digest(current_source)
            or baseline_reference.get('etag') != etag):
            raise InternetPathRefused('conditional source relationship lacks a receiver-pinned complete representation')
    else:
        raise InternetPathRefused('unsupported HTTP intention')
    return {'status':status,'source_sha256':digest(current_source),'etag':etag,
            'mode':mode,'payload_bytes':len(body),'response_body_sha256':digest(body),
            'route':observed.get('route'),
            'elapsed_ns':observed.get('elapsed_ns')}


def experiment() -> dict:
    if not shutil.which('nginx'):
        raise InternetPathRefused('installed Nginx binary required')
    with tempfile.TemporaryDirectory(prefix='internet003-') as tmp:
        with NginxPath(Path(tmp)) as p:
            original=make_data()
            baseline=p.request(via_proxy=False)
            base_verify=verify_response(baseline,current_source=original,mode='complete')
            cold=p.request(via_proxy=True)
            cold_verify=verify_response(cold,current_source=original,mode='complete')
            count_cold=p.origin_requests()
            warm=p.request(via_proxy=True)
            warm_verify=verify_response(warm,current_source=original,mode='complete')
            count_warm=p.origin_requests()
            compressed=p.request(via_proxy=True,headers={'Accept-Encoding':'gzip'})
            compressed_verify=verify_response(compressed,current_source=original,mode='complete')
            offset,size=127,4096
            sliced=p.request(via_proxy=True,headers={'Range':f'bytes={offset}-{offset+size-1}'})
            sliced_verify=verify_response(sliced,current_source=original,mode='range',offset=offset,length=size)
            conditional=p.request(via_proxy=True,headers={'If-None-Match':warm_verify['etag']})
            condition_verify=verify_response(conditional,current_source=original,mode='conditional',supplied_etag=warm_verify['etag'],baseline_reference=warm_verify)
            wrong_cond=p.request(via_proxy=True,headers={'If-None-Match':'"wrong-entity-tag"'})
            wrong_verify=verify_response(wrong_cond,current_source=original,mode='complete')
            # The origin changes after the intermediary cached an earlier representation.
            # Revalidate only after an explicitly cache-bypassing request; do not infer TTL
            # countdown semantics or content freshness from a hash alone.
            updated=make_data(mutation=True)
            (p.root/'static'/'payload.bin').write_bytes(updated)
            bypass=p.request(via_proxy=False)
            bypass_verify=verify_response(bypass,current_source=updated,mode='complete')
            stale=p.request(via_proxy=True)
            stale_old=verify_response(stale,current_source=original,mode='complete')
            refused_new=False
            try:verify_response(stale,current_source=updated,mode='complete')
            except InternetPathRefused:refused_new=True
            if not refused_new:
                raise InternetPathRefused('stale proxy response accepted against changed source')
            forced=p.request(via_proxy=True,headers={'X-ECpu-Bypass':'1'})
            forced_verify=verify_response(forced,current_source=updated,mode='complete')
            # True path-state failure control: the origin stops serving entirely.
            # The already cached representation remains accessible at the proxy,
            # and unsupported attempts to claim current-source freshness refuse.
            p.stop_origin()
            offline_origin_refused = False
            try:p.request(via_proxy=False)
            except (ConnectionError,OSError):offline_origin_refused=True
            if not offline_origin_refused:
                raise InternetPathRefused('direct origin unexpectedly stayed reachable')
            post_failure = []
            for i in range(80):
                mode = i % 4
                if mode == 0:
                    result=p.request(via_proxy=True)
                    verified=verify_response(result,current_source=original,mode='complete')
                elif mode == 1:
                    result=p.request(via_proxy=True,headers={'Range':'bytes=10-522'})
                    verified=verify_response(result,current_source=original,mode='range',offset=10,length=513)
                elif mode == 2:
                    result=p.request(via_proxy=True,headers={'If-None-Match':warm_verify['etag']})
                    verified=verify_response(result,current_source=original,mode='conditional',
                        supplied_etag=warm_verify['etag'],baseline_reference=warm_verify)
                else:
                    result=p.request(via_proxy=True,headers={'Accept-Encoding':'gzip'})
                    verified=verify_response(result,current_source=original,mode='complete')
                    if result['headers'].get('content-encoding') != 'gzip':
                        raise InternetPathRefused('gzip transformation absent during offline warm reuse')
                post_failure.append(verified)
            offline_bypass=p.request(via_proxy=True,headers={'X-ECpu-Bypass':'1'})
            if offline_bypass['status'] != 502:
                raise InternetPathRefused('proxy did not expose origin failure when asked to bypass cache')
            if count_warm!=count_cold:
                raise InternetPathRefused('warm intermediary unexpectedly asked origin again')
            # Real role evidence: source gets contacted on miss; it is NOT contacted on HIT.
            if warm['headers'].get('x-ecpu-cache') != 'HIT':
                raise InternetPathRefused('warm path did not demonstrate cached representation')
            if cold['headers'].get('x-ecpu-cache') != 'MISS':
                raise InternetPathRefused('cold path did not demonstrate origin fetch')
            if compressed['headers'].get('content-encoding') != 'gzip' or len(compressed['body'])>=len(original):
                raise InternetPathRefused('proxy did not demonstrate compressed representation')
            return {'schema':SCHEMA,'mechanism':'controlled-nginx-origin-and-proxy-on-real-TCP',
                    'source_sha256':digest(original),'changed_source_sha256':digest(updated),
                    'source_bytes':len(original),'compressed_bytes':len(compressed['body']),
                    'compressed_payload_fraction':round(len(compressed['body'])/len(original),5),
                    'origin_request_count_after_cold':count_cold,
                    'origin_request_count_after_warm':count_warm,
                    'origin_get_avoided_on_warm':count_cold==count_warm,
                    'cache_miss':cold['headers'].get('x-ecpu-cache'),
                    'cache_hit':warm['headers'].get('x-ecpu-cache'),
                    'origin_offline_after_stop':offline_origin_refused,
                    'origin_offline_proxy_bypass_status':offline_bypass['status'],
                    'offline_qualified_queries':len(post_failure),
                    'offline_statuses':{str(k):sum(x['status']==k for x in post_failure) for k in (200,206,304)},
                    'offline_proxy_median_elapsed_ns':int(statistics.median(x['elapsed_ns'] for x in post_failure)),
                    'offline_source_sha256':post_failure[0]['source_sha256'],
                    'offline_qualified_receipts':post_failure,
                    'origin_access_log_sha256':digest((p.root/'logs'/'origin.log').read_bytes()),
                    'proxy_access_log_sha256':digest((p.root/'logs'/'proxy.log').read_bytes()),
                    'stale_after_origin_changed':stale['body']==original,
                    'changed_source_refused_against_stale_cache':refused_new,
                    'source_equal_after_forced_bypass':forced['body']==updated,
                    'queries':[base_verify,cold_verify,warm_verify,compressed_verify,sliced_verify,condition_verify,wrong_verify,bypass_verify,stale_old,forced_verify],
                    'clock_scope':'one-client-process-monotonic_ns',
                    'physical_scope':'same-machine-two-nginx-processes-not-WAN-or-passive-fiber',
                    'observer_host_roles':['origin-file-serving','proxy-cache-retention','proxy-http-conditional-selection','proxy-gzip-encoding'],
                    'nonclaims':['no-remote-internet-measurement','no-independent-physical-failure-domains',
                                 'no-endpoint-cpu-independence','no-arbitrary-in-network-program']}


def main() -> None:
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path)
    args=p.parse_args()
    report=experiment()
    encoded=json.dumps(report,indent=2,sort_keys=True)+'\n'
    if args.output:
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(encoded)
    else:
        print(encoded)

if __name__=='__main__': main()
