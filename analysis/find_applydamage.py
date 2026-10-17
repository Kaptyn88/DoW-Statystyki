# Szuka ApplyDamage: funkcji, która woła TakeDamage sekwencją "mov r8b,1; movaps xmm1,xmm7; mov rcx,rdi; call TakeDamage"
import pefile,sys,os,re,struct,bisect
g=sys.argv[1]
SIG_TD=rb'\x40\x53\x48\x83\xEC\x30\x0F\x29\x74\x24\x20\x0F\x28\xF1\x48\x8B\xD9\x45\x84\xC0\x74.\xE8'
for dll in ['W40kMod.dll','WXPMod.dll','DXP2Mod.dll','DXP3Mod.dll']:
    pe=pefile.PE(os.path.join(g,dll),fast_load=True); d=bytes(pe.get_memory_mapped_image())
    pe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY['IMAGE_DIRECTORY_ENTRY_EXCEPTION']])
    f=sorted((e.struct.BeginAddress,e.struct.EndAddress) for e in pe.DIRECTORY_ENTRY_EXCEPTION); s=[x[0] for x in f]
    td=re.search(SIG_TD,d,re.S).start()
    hits=[]
    for m in re.finditer(rb'\x41\xB0\x01\x0F\x28\xCF\x48\x8B\xCF\xE8',d):
        e8=m.end()-1
        if e8+5+struct.unpack_from('<i',d,e8+1)[0]==td:
            i=bisect.bisect_right(s,e8)-1; hits.append((hex(e8),hex(f[i][0])))
    print('%-12s TakeDamage=%x  wywolania wzorcem: %s  poczatek funkcji: %s'%(dll,td,hits,d[f[bisect.bisect_right(s,int(hits[0][0],16))-1][0]:][:16].hex(' ') if hits else '-'))
