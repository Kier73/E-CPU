"""FAB-007: arithmetic expressed as kernel-selected communication paths."""
import ctypes
import hashlib
import json
import selectors
import socket
import struct
import time
from contextlib import ExitStack
from loopback_kernel_fabric import Instruction, Program, OPS, oracle, program

SINKS = 511


def route_program():
    """Reuse arithmetic bodies; return a socket index rather than a byte length."""
    original = program()
    code = original[3:]
    return [(op,jt,jf,0 if op==4 and k==8 else k-8 if op==6 and k in (8,9) else k)
            for op,jt,jf,k in code]


def attach(sock, code, option):
    """Attach classic BPF to a local socket or its reuseport group."""
    instructions = (Instruction*len(code))(*(Instruction(*x) for x in code))
    descriptor = Program(len(code),instructions)
    libc = ctypes.CDLL(None,use_errno=True)
    if libc.setsockopt(sock.fileno(),socket.SOL_SOCKET,option,
                       ctypes.byref(descriptor),ctypes.sizeof(descriptor)):
        raise OSError(ctypes.get_errno(),'BPF attach failed')


def gate_program():
    """Reject invalid operators and nonempty datagrams after route selection."""
    code=[(0x80,0,0,0),(0x15,1,0,8),(6,0,0,0),
          (0x30,0,0,-0x100000+16),(0x15,1,0,127),(6,0,0,0),
          (0x30,0,0,-0x100000+17)]
    code += [(0x15,len(OPS)-i,0,op) for i,op in enumerate(OPS)]
    return code+[(6,0,0,0),(6,0,0,8)]


def nand_circuit(observe):
    """Construct a full adder from nine kernel NAND operations per bit."""
    gates=0
    def nand(a,b):
        nonlocal gates
        gates+=1
        return observe(16,a,b)
    def full_adder(a,b,c):
        t=nand(a,b); u=nand(a,t); v=nand(b,t); x=nand(u,v)
        w=nand(x,c); y=nand(x,w); z=nand(c,w)
        return nand(y,z),nand(t,w)
    for a in (0,1):
        for b in (0,1):
            for c in (0,1):
                result,carry=full_adder(255*a,255*b,255*c)
                if (result,carry)!=(255*((a+b+c)%2),255*((a+b+c)//2)):
                    raise AssertionError('full adder truth table')
    cases=[(a,(73*a+91)%256) for a in range(256)]+[(0,0),(255,255),(255,1),(128,128)]
    start=time.perf_counter()
    for a,b in cases:
        carry=0; bits=[]
        for bit in range(8):
            out,carry=full_adder(255*((a>>bit)&1),255*((b>>bit)&1),carry)
            bits.append(out)
        result=sum((out==255)<<bit for bit,out in enumerate(bits)) + (carry==255)*256
        if result!=a+b:raise AssertionError(('ripple adder',a,b,result))
    return {'full_adder_truth_cases':8,'byte_addition_cases':len(cases),
            'kernel_nand_calls':gates,'ripple_addition_seconds':time.perf_counter()-start}


def experiment(full=True):
    """Verify exactly one empty datagram appears on the correct result path."""
    with ExitStack() as stack:
        selector=stack.enter_context(selectors.DefaultSelector())
        sockets=[]
        for result in range(SINKS):
            sock=stack.enter_context(socket.socket(socket.AF_INET,socket.SOCK_DGRAM))
            sock.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEPORT,1)
            sock.setsockopt(socket.SOL_SOCKET,25,b'lo\0')
            sock.setsockopt(socket.IPPROTO_IP,8,1)
            sock.bind(('0.0.0.0',sockets[0].getsockname()[1] if sockets else 0))
            attach(sock,gate_program(),26)
            selector.register(sock,selectors.EVENT_READ,result)
            sockets.append(sock)
        attach(sockets[0],route_program(),51)
        sender=stack.enter_context(socket.socket(socket.AF_INET,socket.SOCK_DGRAM))
        sender.bind(('127.0.0.1',0))
        port=sockets[0].getsockname()[1]
        def observe(op,a,b):
            dest=f'127.{op}.{a}.{b}'
            sender.sendto(b'',(dest,port))
            ready=selector.select(.5)
            if len(ready)!=1:
                raise AssertionError(('unexpected path count',len(ready),dest))
            key,_=ready[0]
            data,control,flags,peer=key.fileobj.recvmsg(1,socket.CMSG_SPACE(12))
            addresses=[socket.inet_ntoa(c[8:12]) for level,kind,c in control
                       if level==socket.IPPROTO_IP and kind==8 and len(c)==12]
            if data or flags & (socket.MSG_TRUNC|socket.MSG_CTRUNC) or peer!=sender.getsockname() or addresses!=[dest]:
                raise AssertionError(('bad observation',dest))
            return key.data
        evidence=hashlib.sha256(); reports=[]; start=time.perf_counter()
        values=range(256) if full else (0,1,7,40,127,128,254,255)
        for op,name in OPS.items():
            begin=time.perf_counter(); count=0
            for a in values:
                for b in values:
                    result=observe(op,a,b)
                    if result!=oracle(op,a,b):
                        raise AssertionError((op,a,b,result))
                    evidence.update(struct.pack('!BBBH',op,a,b,result));count+=1
            reports.append({'operator':name,'count':count,'seconds':time.perf_counter()-begin})
        elapsed=time.perf_counter()-start
        x=observe(12,40,23);y=observe(14,x,2);z=observe(13,y,7)
        if (x,y,z)!=(63,126,121):raise AssertionError('composition')
        for dest,payload in [('127.99.1.2',b''),('127.12.1.2',b'x')]:
            sender.sendto(payload,(dest,port))
            if selector.select(.1):raise AssertionError('invalid request accepted')
        if observe(17,1,2)!=0:raise AssertionError('zero missing')
        return {'scope':'one Linux kernel; loopback-only UDP reuseport group',
                'result_sockets':SINKS,'sending_sockets':1,'payload_bytes':0,
                'selector_instructions':len(route_program()),'gate_instructions':len(gate_program()),
                'operators':reports,'total':sum(r['count'] for r in reports),'seconds':elapsed,
                'observations_sha256':evidence.hexdigest(),'path':[x,y,z],
                'rejected_requests':2,'zero_result_received':True,'nand_circuit':nand_circuit(observe)}


if __name__=='__main__':
    import sys
    print(json.dumps(experiment('--quick' not in sys.argv),indent=2))
