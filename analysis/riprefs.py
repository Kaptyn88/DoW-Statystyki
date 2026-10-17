# Szuka odwołań RIP-relative (lea/mov/call/jmp) oraz wskaźników absolutnych do podanych RVA w W40kMod.dll
import pefile,sys,os,struct,bisect
g=sys.argv[1]; targets=set(int(x,16) for x in sys.argv[2:])
pe=pefile.PE(os.path.join(g,'W40kMod.dll'),fast_load=True)
d=pe.get_memory_mapped_image(); base=pe.OPTIONAL_HEADER.ImageBase
t=[s for s in pe.sections if s.Name.startswith(b'.text')][0]
tva,tsz=t.VirtualAddress,t.Misc_VirtualSize
pe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY['IMAGE_DIRECTORY_ENTRY_EXCEPTION']])
funcs=sorted((e.struct.BeginAddress,e.struct.EndAddress) for e in pe.DIRECTORY_ENTRY_EXCEPTION)
starts=[f[0] for f in funcs]
def fo(a):
    i=bisect.bisect_right(starts,a)-1
    return hex(funcs[i][0]) if i>=0 and funcs[i][0]<=a<funcs[i][1] else None
for i in range(tva,tva+tsz-4):
    disp=struct.unpack_from('<i',d,i)[0]
    for ilen_after in (4,):
        tgt=i+4+disp
        if tgt in targets:
            print('rel32 at %x -> %x (op bytes %s) func %s'%(i,tgt,d[i-3:i].hex(),fo(i)))
for s in pe.sections:
    a=s.VirtualAddress;n=s.Misc_VirtualSize
    for off in range(0,n-7,8):
        v=struct.unpack_from('<Q',d,a+off)[0]
        if v-base in targets: print('abs ptr in %s at %x -> %x'%(s.Name.rstrip(b'\0').decode(),a+off,v-base))
