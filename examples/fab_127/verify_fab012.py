"""Independent report, effect-chain and optional native E-CPU law verification."""
from pathlib import Path
import sys

MASK = 2**32-1
A = (5, 7, 0, MASK)
B = (3, 19, 123456789, 100)


def verify(path, native=False):
    """Verify exact counts and each retained sample chain from its initial state."""
    rows = [dict(part.split('=', 1) for part in line.split() if '=' in part)
            for line in Path(path).read_text().splitlines()]
    if len(rows) < 5:
        raise ValueError('incomplete report')
    head, final = rows[0], rows[4]
    n, rounds, pure = (int(head[k]) for k in ('machines', 'rounds', 'pure_instructions'))
    assert 16 <= n <= 2**24 and n & (n-1) == 0
    assert 1 <= rounds <= 8 and 2 <= pure <= 2048 and pure % 2 == 0
    assert int(head['state_bytes']) == n*8
    assert int(head['journal_bytes']) == n*rounds*12
    mode = head['mode']
    assert mode in ('literal', 'leap')
    count = n*rounds
    expected = dict(machines=n, instructions=count*(pure+5),
                    transitions=count*(pure+5 if mode == 'literal' else 6),
                    leaps=count if mode == 'leap' else 0,
                    sends=count, receives=count, stores=count,
                    live_observations=n*3, live_history=n, future_refusals=n, history=n)
    assert all(int(final[k]) == v for k,v in expected.items())
    for i,row in enumerate(rows[1:4]):
        assert int(row['scan']) == i and int(row['observations']) == n
        assert 0 <= int(row['moving']) <= n
        assert 0 <= int(row['min_tick']) <= int(row['max_tick']) <= rounds*(pure+5)
        assert 0 <= int(row['effect_visible']) <= n
        if i: assert int(row['effect_visible']) == n
    assert sum(int(r['moving']) for r in rows[1:4]) == int(final['moving_observations'])
    assert sum(int(r['effect_visible']) for r in rows[1:4]) == int(final['effect_visible'])
    samples = {}
    for row in rows[5:]:
        i,r,other,x,y,z,w = (int(row[k]) for k in ('id','round','peer','anchor','sent','received','stored'))
        assert 0 <= i < n and 0 <= r < rounds and (i,r) not in samples
        assert other == i ^ ((n>>1) | (1 << (r % (n.bit_length()-2))))
        assert all(0 <= v <= MASK for v in (x,y,z,w))
        samples[i,r] = (other,x,y,z,w)
    ids = {i for i,_ in samples}
    assert len(ids) == min(n,64) and len(samples) == len(ids)*rounds and {0,n-1} <= ids
    for i in ids:
        x = (i*2654435761+17)&MASK
        for r in range(rounds):
            other,anchor,sent,received,stored = samples[i,r]
            assert anchor == x
            for _ in range(pure//2): x = (A[i%4]*x+B[i%4])&MASK
            assert x == sent
            if native:
                from mailcpu.law_certifier import lcg_navigate
                assert lcg_navigate(A[i%4],B[i%4],2**32,anchor,pure//2) == sent
            if (other,r) in samples: assert received == samples[other,r][2]
            x ^= received
            x = ((x+37)&MASK) if x&1 else x^0xa5a5a5a5
            assert x == stored
    print(f'{n:,} CPUs, {count:,} effect chains, {len(samples)} independent sample records, {mode}: verified')
    return head,final,samples


def compare(left,right):
    """Require equal logical workload, sampled records and full oracle checksums."""
    a,b,c = left
    d,e,f = right
    assert all(a[k] == d[k] for k in ('machines','rounds','pure_instructions'))
    assert a['mode'] == 'literal' and d['mode'] == 'leap'
    assert all(b[k] == e[k] for k in ('instructions','sends','receives','stores','checksum','history_checksum'))
    assert c == f
    print('literal and leap realizations agree on sampled effect chains and whole-fleet checksums')


if __name__ == '__main__':
    paths = [p for p in sys.argv[1:] if p != '--native-law']
    reports = [verify(path, '--native-law' in sys.argv) for path in paths]
    if len(reports) == 2: compare(*reports)
