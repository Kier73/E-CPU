"""Verify FAB-011 coverage, instruction accounting and independent sample replay."""
import sys
from pathlib import Path


def check(program_path, report_path, native_law=False):
    """Check a complete report; independently replay final sample states."""
    programs = [[]]
    for line in Path(program_path).read_text().splitlines():
        parts = line.split()
        if not parts:
            continue
        if parts == ['END']:
            programs.append([])
        else:
            programs[-1].append((parts[0], int(parts[1])))
    assert not programs.pop()
    rows = [dict(s.split('=', 1) for s in row.split() if '=' in s)
            for row in Path(report_path).read_text().splitlines()]
    count = int(rows[0]['machines'])
    assert int(rows[0]['programs']) == len(programs)
    assert int(rows[0]['state_bytes']) == 8*count
    assert int(rows[0]['observer_bytes']) == 4*count
    scans = [r for r in rows if 'pass' in r]
    assert [(int(r['epoch']), int(r['pass'])) for r in scans] == [(1,0),(1,1),(2,0),(2,1)]
    for r in scans:
        assert int(r['observations']) == count
        assert int(r['advanced']) + int(r['unchanged']) == count
        assert int(r['advanced']) > 0
        if r['pass'] == '1':
            assert int(r['advanced']) == count
    epochs = [r for r in rows if 'executed' in r]
    assert len(epochs) == 2 and int(rows[-1]['machines']) == count
    assert sum(int(r['executed']) for r in epochs) == int(rows[-1]['total_instructions'])
    samples = [r for r in rows if 'id' in r]
    assert len(samples) == min(count, 64) == len({r['id'] for r in samples})
    assert {0,count-1} <= {int(r['id']) for r in samples}
    mask = 2**32-1
    for r in samples:
        i,t,pos,value = (int(r[k]) for k in ('id','tick','pc','register'))
        prog = programs[i % len(programs)]
        x, pc = (i*2654435761+17)&mask,0
        for _ in range(t):
            op,arg = prog[pc]
            if op == 'ADD': x = (x+arg)&mask
            if op == 'MUL': x = (x*arg)&mask
            pc = 0 if op == 'JUMP' else pc+1
        assert (pc,x)==(pos,value)
        if native_law:
            from mailcpu.law_certifier import lcg_navigate
            m,b = 1,0
            for op,arg in prog:
                if op=='ADD': b=(b+arg)&mask
                if op=='MUL': m,b=(m*arg)&mask,(b*arg)&mask
            q,p = divmod(t,len(prog))
            y=lcg_navigate(m,b,2**32,(i*2654435761+17)&mask,q)
            for op,arg in prog[:p]:
                if op=='ADD': y=(y+arg)&mask
                if op=='MUL': y=(y*arg)&mask
            assert (p,y)==(pos,value)
    print(f'{count:,} CPUs; four complete scans; {len(samples)} independent sample replays; instruction accounting exact')


if __name__ == '__main__':
    check(sys.argv[1],sys.argv[2], '--native-law' in sys.argv[3:])
