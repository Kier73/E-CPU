"""INTERNET-003: independent offline consistency check for a measured local report.

The report does NOT authenticate the experimenter, measure physical propagation
or prove that a socket/path existed. It checks that the claimed observations are
internally consistent with independent source bytes and report schema.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
from typing import Mapping

from probe_internet_path_nginx import make_data, digest, InternetPathRefused

MAX_REPORT_BYTES=300_000


def pairs_no_duplicates(pairs):
    value={}
    for key, item in pairs:
        if key in value:raise InternetPathRefused('duplicate report JSON field')
        value[key]=item
    return value


def read_report(path: Path) -> dict:
    if not path.is_file() or path.stat().st_size > MAX_REPORT_BYTES:
        raise InternetPathRefused('missing or oversized report')
    try:result=json.loads(path.read_bytes(),object_pairs_hook=pairs_no_duplicates)
    except (ValueError,UnicodeDecodeError) as exc:
        raise InternetPathRefused('invalid report JSON') from exc
    if type(result) is not dict: raise InternetPathRefused('report must be JSON object')
    return result


def verify_record(report: Mapping, *, receiver_expected_source_sha256: str) -> dict:
    if type(report) is not dict or report.get('schema')!='mailcpu.internet-path-http.v1':
        raise InternetPathRefused('unsupported report schema')
    source=make_data()
    changed=make_data(mutation=True)
    if receiver_expected_source_sha256!=digest(source):
        raise InternetPathRefused('receiver-owned source identity was not known')
    if (report.get('source_sha256')!=receiver_expected_source_sha256 or
        report.get('changed_source_sha256')!=digest(changed) or
        report.get('source_bytes')!=len(source)):
        raise InternetPathRefused('declared source Ground does not match independent bytes')
    if (report.get('physical_scope')!='same-machine-two-nginx-processes-not-WAN-or-passive-fiber' or
        report.get('clock_scope')!='one-client-process-monotonic_ns'):
        raise InternetPathRefused('claim scope changed')
    if any(report.get(k) is not True for k in (
        'origin_get_avoided_on_warm','origin_offline_after_stop',
        'stale_after_origin_changed','changed_source_refused_against_stale_cache',
        'source_equal_after_forced_bypass')):
        raise InternetPathRefused('required path-state or negative control not supported')
    if (report.get('cache_miss')!='MISS' or report.get('cache_hit')!='HIT' or
            report.get('origin_request_count_after_cold')!=report.get('origin_request_count_after_warm') or
            report.get('origin_offline_proxy_bypass_status')!=502):
        raise InternetPathRefused('path-state evidence conflicts')
    qs=report.get('queries')
    if type(qs) is not list or len(qs)!=10:
        raise InternetPathRefused('missing source, bypass, conditional or stale controls')
    expected=[('complete',200,source),('complete',200,source),('complete',200,source),
              ('complete',200,source),('range',206,source),('conditional',304,source),
              ('complete',200,source),('complete',200,changed),('complete',200,source),
              ('complete',200,changed)]
    for i,(q,(mode,status,version)) in enumerate(zip(qs,expected)):
        if (type(q) is not dict or q.get('mode')!=mode or q.get('status')!=status or
                q.get('source_sha256')!=digest(version) or
                type(q.get('elapsed_ns')) is not int or q['elapsed_ns']<=0 or
                type(q.get('payload_bytes')) is not int or q['payload_bytes']<0):
            raise InternetPathRefused(f'invalid origin/proxy evidence at slot {i}')
        if i == 4 and q.get('response_body_sha256')!=digest(source[127:127+4096]):
            raise InternetPathRefused('range response digest disagrees with independent slice')
        if i == 5 and q.get('response_body_sha256')!=digest(b''):
            raise InternetPathRefused('conditional response is not an empty body')
    receipt_list=report.get('offline_qualified_receipts')
    if type(receipt_list) is not list or len(receipt_list)!=80 or report.get('offline_qualified_queries')!=80:
        raise InternetPathRefused('offline proof record does not retain all 80 observations')
    expected_status={'200':40,'206':20,'304':20}
    if report.get('offline_statuses')!=expected_status or report.get('offline_source_sha256')!=digest(source):
        raise InternetPathRefused('offline claims disagree')
    for i,q in enumerate(receipt_list):
        mode=('complete','range','conditional','complete')[i%4]
        status=(200,206,304,200)[i%4]
        if (type(q) is not dict or q.get('route')!='proxy' or q.get('mode')!=mode or
            q.get('status')!=status or q.get('source_sha256')!=digest(source) or
            type(q.get('elapsed_ns')) is not int or q['elapsed_ns']<=0):
            raise InternetPathRefused('replay evidence changed at index '+str(i))
        if mode=='range' and (q.get('payload_bytes')!=513 or
            q.get('response_body_sha256')!=digest(source[10:523])):
            raise InternetPathRefused('offline range proof changed')
        if mode=='conditional' and (q.get('payload_bytes')!=0 or
            q.get('response_body_sha256')!=digest(b'')):
            raise InternetPathRefused('offline 304 proof changed')
        if status==200 and (type(q.get('payload_bytes')) is not int or not 0<q['payload_bytes']<=len(source)):
            raise InternetPathRefused('offline complete/gzip byte extent disagrees')
    raw=json.dumps(report,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()
    return {'schema':'mailcpu.internet-003-offline-record-verdict.v1',
            'record_sha256':hashlib.sha256(raw).hexdigest(),
            'records_checked':len(receipt_list),'source_sha256':receiver_expected_source_sha256,
            'classification':'internal-evidence-consistency-only-not-independent-path-attestation'}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--report',type=Path,required=True)
    p.add_argument('--expected-source-sha256',required=True)
    args=p.parse_args()
    print(json.dumps(verify_record(read_report(args.report),
          receiver_expected_source_sha256=args.expected_source_sha256),sort_keys=True,indent=2))

if __name__=='__main__':main()
