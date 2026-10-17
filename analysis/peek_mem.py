# Odczyt pamięci działającej gry (tylko odczyt): szuka napisów i wskaźników do napisów wokół podanych adresów
import ctypes, ctypes.wintypes as w, sys, re, struct
pid=int(sys.argv[1]); addrs=[int(a,16) for a in sys.argv[2].split(',')]; back=int(sys.argv[3],16); fwd=int(sys.argv[4],16)
k=ctypes.windll.kernel32
h=k.OpenProcess(0x10|0x400,False,pid)
def read(a,n):
    buf=ctypes.create_string_buffer(n); got=ctypes.c_size_t()
    ok=k.ReadProcessMemory(h,ctypes.c_void_p(a),buf,n,ctypes.byref(got))
    return buf.raw[:got.value] if ok else None
def cstr(a):
    b=read(a,120)
    if not b: return None
    s=b.split(b'\0')[0]
    return s.decode() if len(s)>=4 and all(32<=c<127 for c in s) else None
for base in addrs:
    print('=====',hex(base))
    data=read(base-back,back+fwd)
    if data is None:
        # spróbuj mniejszymi kawałkami
        data=b''.join((read(base-back+i,0x100) or b'\0'*0x100) for i in range(0,back+fwd,0x100))
    out=[]
    for off in range(0,len(data)-7,8):
        q=struct.unpack_from('<Q',data,off)[0]
        rel=off-back
        if 0x10000<q<0x7FFFFFFFFFFF:
            s=cstr(q)
            if s: out.append('%s0x%x=*%s'%('-' if rel<0 else '+',abs(rel),s))
        m=re.match(rb'[ -~]{6,}',data[off:off+64])
        if m: out.append('%s0x%x=in"%s"'%('-' if rel<0 else '+',abs(rel),m.group().decode()[:50]))
    seen=set()
    for o in out:
        key=o.split('=',1)[1]
        if key in seen: continue
        seen.add(key); print('  ',o)
