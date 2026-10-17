# Odtwarza ResolveSelection z recorder.cpp na pliku W40k.exe (napis -> rejestracja -> funkcja obsługi -> f1..f3)
import pefile,sys,os,re,struct
pe=pefile.PE(os.path.join(sys.argv[1],'W40k.exe'),fast_load=True); d=bytes(pe.get_memory_mapped_image())
execs=[(s.VirtualAddress,s.Misc_VirtualSize) for s in pe.sections if s.Characteristics & 0x20000000]
str_rva=[m.start() for m in re.finditer(b'Misc_GetSelectedSquads\0',d) if not any(a<=m.start()<a+n for a,n in execs)][0]
reg=None
for a,n in execs:
    for m in re.finditer(rb'\x4C\x8D\x05',d[a:a+n]):
        i=a+m.start()
        if i+7+struct.unpack_from('<i',d,i+3)[0]==str_rva: reg=i; break
h=None
for k in range(0x40):
    p=reg+k
    if d[p:p+3]==b'\x48\x8D\x05' and d[p+7:p+11]==b'\x48\x89\x46\x20': h=p+7+struct.unpack_from('<i',d,p+3)[0]; break
k=0
while not (d[h+k]==0xFF and d[h+k+1]==0x15): k+=1
k+=6; calls=[]
while k<0x60 and len(calls)<3:
    if d[h+k]==0xE8: calls.append(h+k+5+struct.unpack_from('<i',d,h+k+1)[0]); k+=5
    else: k+=1
print('napis',hex(str_rva),'rejestracja',hex(reg),'obsluga',hex(h),'f1..f3',[hex(c) for c in calls],'ogon OK:', d[h+k:h+k+9]==bytes.fromhex('488BC8488B10FF5208'))
