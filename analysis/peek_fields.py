# Dla obiektu pod adresem: każde pole-wskaźnik -> czy w pobliżu celu (±0x600) jest ścieżka data:attrib (właściciel?)
import ctypes, sys, struct
pid=int(sys.argv[1]); objs=[int(a,16) for a in sys.argv[2].split(',')]; size=int(sys.argv[3],16)
k=ctypes.windll.kernel32; h=k.OpenProcess(0x10|0x400,False,pid)
def read(a,n):
    buf=ctypes.create_string_buffer(n); got=ctypes.c_size_t()
    return buf.raw[:got.value] if k.ReadProcessMemory(h,ctypes.c_void_p(a),buf,n,ctypes.byref(got)) else None
def cstr(a):
    b=read(a,140)
    if not b: return None
    s=b.split(b'\0')[0]
    return s.decode() if len(s)>=4 and all(32<=c<127 for c in s) else None
def paths_near(a):
    res=[]
    d=read(a-0x600,0x900)
    if not d: return res
    for off in range(0,len(d)-7,8):
        q=struct.unpack_from('<Q',d,off)[0]
        if 0x10000<q<0x7FFFFFFFFFFF:
            s=cstr(q)
            if s and s.startswith('data:attrib'): res.append('%+x:%s'%(off-0x600,s))
    return res
for o in objs:
    print('=====',hex(o)); d=read(o,size)
    for off in range(0,len(d)-7,8):
        q=struct.unpack_from('<Q',d,off)[0]
        if not (0x10000<q<0x7FFFFFFFFFFF): continue
        s=cstr(q); p=paths_near(q)
        if s or p: print('  +%x -> %x %s %s'%(off,q,repr(s) if s else '',p[:3]))
