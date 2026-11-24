"""FAB-008: finite observation-formed kernel-native truth tables."""
from contextlib import ExitStack
from hashlib import sha256
import ctypes
import json
import selectors
import socket
import struct
import sys
import time

NET = -0x100000

class Instruction(ctypes.Structure):
    """Linux socket filter instruction."""
    _fields_ = [('code', ctypes.c_ushort), ('jt', ctypes.c_ubyte), ('jf', ctypes.c_ubyte), ('k', ctypes.c_uint32)]

class Program(ctypes.Structure):
    """Linux socket filter program."""
    _fields_ = [('len', ctypes.c_ushort), ('filter', ctypes.POINTER(Instruction))]

def attach(sock, code, option):
    """Install real kernel code; no userspace fallback."""
    instructions = (Instruction * len(code))(*(Instruction(*x) for x in code))
    descriptor = Program(len(code), instructions)
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.setsockopt(sock.fileno(), socket.SOL_SOCKET, option, ctypes.byref(descriptor), ctypes.sizeof(descriptor)):
        raise OSError(ctypes.get_errno(), 'BPF attach failed')

def codes(values, width):
    """Compile a finite table and strict coordinate guard into native cBPF."""
    if type(width) is not int or width not in (1, 2) or type(values) is not tuple or len(values) not in (2, 4, 8, 16) or any(type(v) is not int or not 0 <= v < 1 << width for v in values):
        raise ValueError('invalid truth Ground')
    packed = sum(v << (i * width) for i, v in enumerate(values))
    selector = [(0x30,0,0,NET+19),(0x24,0,0,width),(7,0,0,0),(0,0,0,packed),(0x7c,0,0,0),(0x54,0,0,(1<<width)-1),(0x16,0,0,0)]
    gate = [(0x80,0,0,0),(0x15,1,0,8),(6,0,0,0)]
    for offset, value in [(16,127),(17,18),(18,0)]:
        gate += [(0x30,0,0,NET+offset),(0x15,1,0,value),(6,0,0,0)]
    gate += [(0x30,0,0,NET+19),(0x35,0,1,len(values)),(6,0,0,0),(6,0,0,8)]
    return selector, gate

class KernelTable:
    """Serial, fixed-membership, loopback-only result paths."""
    def __init__(self, values, width):
        self.values, self.width = values, width
        self.code, self.gate = codes(values, width)
        if sys.platform != 'linux':
            raise OSError('Linux required')
        self.stack = ExitStack()
        self.failed = False
        try:
            self.poll = self.stack.enter_context(selectors.DefaultSelector())
            self.port = 0
            sockets = []
            for i in range(1 << width):
                sock = self.stack.enter_context(socket.socket(socket.AF_INET, socket.SOCK_DGRAM))
                sock.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEPORT,1)
                sock.setsockopt(socket.SOL_SOCKET,25,b'lo\0')
                sock.setsockopt(socket.IPPROTO_IP,8,1)
                sock.bind(('0.0.0.0',self.port))
                self.port = sock.getsockname()[1]
                attach(sock,self.gate,26)
                self.poll.register(sock,selectors.EVENT_READ,i)
                sockets.append(sock)
            attach(sockets[0],self.code,51)
            self.sender = self.stack.enter_context(socket.socket(socket.AF_INET,socket.SOCK_DGRAM))
            self.sender.bind(('127.0.0.1',0))
        except BaseException:
            self.stack.close()
            raise
    def __enter__(self):
        return self
    def __exit__(self,*exc):
        self.failed = True
        self.stack.close()
    def observe(self,x):
        """Observe the actual selected path, without evaluating the table."""
        if self.failed or type(x) is not int or not 0 <= x < len(self.values):
            raise ValueError('invalid coordinate or failed incarnation')
        dest = f'127.18.0.{x}'
        try:
            self.sender.sendto(b'',(dest,self.port))
            ready = self.poll.select(.5)
            if len(ready) != 1:
                raise RuntimeError('missing or ambiguous path')
            key,_ = ready[0]
            data,control,flags,peer = key.fileobj.recvmsg(1,socket.CMSG_SPACE(12))
            addresses = [socket.inet_ntoa(c[8:12]) for level,kind,c in control if level == socket.IPPROTO_IP and kind == 8 and len(c) == 12]
            if data or flags & (socket.MSG_TRUNC|socket.MSG_CTRUNC) or peer != self.sender.getsockname() or addresses != [dest]:
                raise RuntimeError('invalid observation identity')
            return key.data
        except BaseException:
            self.failed = True
            self.stack.close()
            raise
    def refuse_controls(self):
        """Check actual kernel refusal without host coordinate guard."""
        for dest,payload in [('127.19.0.0',b''),('127.18.1.0',b''),(f'127.18.0.{len(self.values)}',b''),('127.18.0.0',b'x')]:
            self.sender.sendto(payload,(dest,self.port))
            if self.poll.select(.05):
                self.failed = True
                self.stack.close()
                raise RuntimeError('invalid request delivered')
    def realizer_binding(self,resource_id):
        """Provide a native SAB binding, without granting execution authority."""
        from .substrate_bootstrap import RealizerBinding
        return RealizerBinding(resource_id=resource_id,operation='fabric.truth.observe.v1',handler=self.observe,implementation_digest=sha256(json.dumps([self.code,self.gate]).encode()).hexdigest(),oracle=lambda x,y: type(x) is int and 0 <= x < len(self.values) and type(y) is int and self.values[x] == y)

def form_adder(nand):
    """Derive a full-adder table from 72 actual NAND path observations."""
    def g(a,b):
        return nand.observe(a | (b<<1))
    values = []
    for x in range(8):
        a,b,c = x&1,(x>>1)&1,(x>>2)&1
        t=g(a,b); u=g(a,t); v=g(b,t); s=g(u,v)
        w=g(s,c); y=g(s,w); z=g(c,w)
        values.append(g(y,z) | (g(t,w)<<1))
    if values != [x.bit_count() for x in range(8)]:
        raise RuntimeError('observed Ground contradicts oracle')
    return tuple(values)

def byte_add(table,a,b):
    """Wire eight actual native full-adder calls."""
    carry=result=0
    for i in range(8):
        r=table.observe(((a>>i)&1)|(((b>>i)&1)<<1)|(carry<<2))
        result |= (r&1)<<i
        carry=r>>1
    return result|(carry<<8)

def experiment(full=True):
    """Form a Ground, rebind, and verify the composed larger circuit."""
    with KernelTable((1,1,1,0),1) as nand:
        values=form_adder(nand)
    digest=sha256(); count=0
    with KernelTable(values,2) as first, KernelTable(values,2) as second:
        if first.port == second.port:
            raise RuntimeError('expected distinct bindings')
        for table in (first,second):
            table.refuse_controls()
            for x,v in enumerate(values):
                if table.observe(x) != v:
                    raise RuntimeError('compiled table mismatch')
        start=time.perf_counter()
        domain=range(256) if full else (0,1,7,127,128,255)
        for a in domain:
            for b in domain:
                result=byte_add(second,a,b)
                if result != a+b:
                    raise RuntimeError('addition mismatch')
                digest.update(struct.pack('!BBH',a,b,result)); count+=1
        elapsed=time.perf_counter()-start
    return dict(table=values,ground=sha256(json.dumps(['fab008.truth.v1',2,values]).encode()).hexdigest(),packed=hex(sum(v<<(2*i) for i,v in enumerate(values))),formation_packets=72,rebound_checks=16,refusal_controls=8,byte_additions=count,composition_packets=count*8,seconds=elapsed,digest=digest.hexdigest(),selector_instructions=7)

if __name__=='__main__':
    print(json.dumps(experiment('--quick' not in sys.argv),indent=2))
