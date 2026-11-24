"""FAB-006: loopback-address arithmetic in a Linux classic BPF socket filter."""
import ctypes
import hashlib
import json
import socket
import struct
import sys
import time
from contextlib import closing

PAD = bytes(510)
NET = -0x100000  # Linux SKF_NET_OFF, relative to the IPv4 header
OPS = {12: 'add', 13: 'xor', 14: 'mul8', 15: 'min', 16: 'nand8', 17: 'eq'}


class Instruction(ctypes.Structure):
    """Linux sock_filter ABI."""
    _fields_ = [('code', ctypes.c_ushort), ('jt', ctypes.c_ubyte),
                ('jf', ctypes.c_ubyte), ('k', ctypes.c_uint32)]


class Program(ctypes.Structure):
    """Linux sock_fprog ABI."""
    _fields_ = [('len', ctypes.c_ushort), ('filter', ctypes.POINTER(Instruction))]


def program():
    """Return deterministic classic BPF code, with refusal of unknown requests."""
    # LD LEN; require UDP header + fixed payload; LD first IPv4 octet of dst.
    code = [(0x80, 0, 0, 0), (0x15, 1, 0, len(PAD)+8), (6, 0, 0, 0),
            (0x30, 0, 0, NET+16), (0x15, 1, 0, 127), (6, 0, 0, 0),
            (0x30, 0, 0, NET+17)]
    dispatch = len(code)
    code += [(0x15, 0, 0, op) for op in OPS] + [(6, 0, 0, 0)]
    bodies = {
        12: [(0x0c, 0, 0, 0)],  # A += X
        13: [(0xac, 0, 0, 0)],  # A ^= X
        14: [(0x2c, 0, 0, 0), (0x54, 0, 0, 255)],
        15: [(0x2d, 0, 1, 0), (0x87, 0, 0, 0)],  # if A > X: A = X
        16: [(0x5c, 0, 0, 0), (0xa4, 0, 0, 255)],
        17: [(0x1d, 0, 1, 0), (6, 0, 0, 9), (6, 0, 0, 8)],
    }
    for i, (op, body) in enumerate(bodies.items()):
        code[dispatch+i] = (0x15, len(code)-dispatch-i-1, 0, op)
        code += [(0x30, 0, 0, NET+18), (7, 0, 0, 0),
                 (0x30, 0, 0, NET+19)] + body
        if op != 17:
            code += [(4, 0, 0, 8), (0x16, 0, 0, 0)]
    return code


def attach(sock):
    """Install the exact instruction sequence in the kernel, not a Python VM."""
    code = program()
    instructions = (Instruction*len(code))(*(Instruction(*x) for x in code))
    descriptor = Program(len(code), instructions)
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.setsockopt(sock.fileno(), socket.SOL_SOCKET, 26,
                       ctypes.byref(descriptor), ctypes.sizeof(descriptor)):
        raise OSError(ctypes.get_errno(), 'SO_ATTACH_FILTER failed')


def receiver(filtered):
    """Open a local-only ephemeral UDP observer; fail closed on setup errors."""
    if sys.platform != 'linux':
        raise OSError('Linux classic BPF/IP_PKTINFO required')
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.setsockopt(socket.SOL_SOCKET, 25, b'lo\0')  # SO_BINDTODEVICE
        sock.setsockopt(socket.IPPROTO_IP, 8, 1)  # IP_PKTINFO
        sock.bind(('0.0.0.0', 0))
        sock.settimeout(0.5)
        if filtered:
            attach(sock)
        return sock
    except BaseException:
        sock.close()
        raise


def read(sock, source, dest):
    """Observe result length and check kernel-supplied address and peer."""
    data, control, flags, peer = sock.recvmsg(len(PAD)+1, socket.CMSG_SPACE(12))
    destinations = [socket.inet_ntoa(c[8:12]) for level, kind, c in control
                    if level == socket.IPPROTO_IP and kind == 8 and len(c) == 12]
    if flags & (socket.MSG_TRUNC | socket.MSG_CTRUNC) or peer != source or destinations != [dest]:
        raise ValueError('unexpected receive identity or truncation')
    if data != PAD[:len(data)]:
        raise ValueError('unexpected result bytes')
    return len(data)


def observe(sender, target, op, a, b):
    """Address an operation; receiver only decodes the kernel-produced length."""
    if op not in OPS or any(type(x) is not int or not 0 <= x <= 255 for x in (a,b)):
        raise ValueError('invalid coordinate')
    dest = f'127.{op}.{a}.{b}'
    sender.sendto(PAD, (dest, target.getsockname()[1]))
    return read(target, sender.getsockname(), dest)


def oracle(op, a, b):
    """Independent userspace reference, never used to form a transmitted request."""
    return {12: lambda: a+b, 13: lambda: a^b, 14: lambda: a*b%256,
            15: lambda: min(a,b), 16: lambda: 255-(a&b),
            17: lambda: int(a==b)}[op]()


def experiment(full=True):
    """Compare real kernel results, bypass, malformed requests and a composed path."""
    with closing(receiver(True)) as target, closing(receiver(False)) as bypass, \
            socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sender:
        sender.bind(('127.0.0.1',0))
        if observe(sender,bypass,12,40,23) != len(PAD):
            raise AssertionError('bypass altered input')
        reports = []
        evidence = hashlib.sha256()
        start = time.perf_counter()
        values = range(256) if full else (0,1,7,40,127,128,254,255)
        for op,name in OPS.items():
            begin = time.perf_counter()
            n = 0
            for a in values:
                for b in values:
                    result = observe(sender,target,op,a,b)
                    if result != oracle(op,a,b):
                        raise AssertionError((op,a,b,result))
                    evidence.update(struct.pack('!BBBH',op,a,b,result))
                    n += 1
            reports.append({'operator':name,'count':n,'seconds':time.perf_counter()-begin})
        elapsed = time.perf_counter()-start
        x = observe(sender,target,12,40,23)
        y = observe(sender,target,14,x,2)
        z = observe(sender,target,13,y,7)
        if (x,y,z) != (63,126,121):
            raise AssertionError('composition mismatch')
        if observe(sender,target,17,1,2) != 0:
            raise AssertionError('zero observation missing')
        for dest,payload in [('127.99.1.2',PAD),('127.12.1.2',b'')]:
            sender.sendto(payload,(dest,target.getsockname()[1]))
            try:
                target.recv(1024)
            except socket.timeout:
                pass
            else:
                raise AssertionError('invalid request delivered')
        code_digest = hashlib.sha256(json.dumps(program(),separators=(',',':')).encode()).hexdigest()
        return {'scope':'single Linux kernel; controlled loopback', 'program_sha256':code_digest,
                'observations_sha256':evidence.hexdigest(), 'instructions':len(program()),
                'operators':reports,'total':sum(r['count'] for r in reports),
                'seconds':elapsed,'bypass_length':len(PAD),'path':[x,y,z],
                'rejected_requests':2,'zero_result_received':True,
                'constant_payload_bytes':len(PAD)}


if __name__ == '__main__':
    print(json.dumps(experiment('--quick' not in sys.argv), indent=2))
