# Sprawdza unikalność sygnatur bajtowych (z '??' jako wildcard) w sekcji .text pliku DLL
import pefile,sys,os,re
g=sys.argv[1]; dll=sys.argv[2]; sigs=sys.argv[3:]
pe=pefile.PE(os.path.join(g,dll),fast_load=True); d=pe.get_memory_mapped_image()
t=[s for s in pe.sections if s.Name.startswith(b'.text')][0]
tb=d[t.VirtualAddress:t.VirtualAddress+t.Misc_VirtualSize]
for s in sigs:
    rx=b''.join(b'.' if x=='??' else re.escape(bytes([int(x,16)])) for x in s.split())
    hits=[t.VirtualAddress+m.start() for m in re.finditer(rx,tb,re.S)]
    print(len(hits),[hex(h) for h in hits[:5]],'|',s)
