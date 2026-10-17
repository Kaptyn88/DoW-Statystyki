# Odtwarza logikę sondy: TakeDamage (sygnatura) -> SetHealth -> Death, dla wszystkich *Mod.dll
import pefile,sys,os,re,struct
g=sys.argv[1]
SIG_TD=rb'\x40\x53\x48\x83\xEC\x30\x0F\x29\x74\x24\x20\x0F\x28\xF1\x48\x8B\xD9\x45\x84\xC0\x74.\xE8'
SIG_W =rb'\x48\x8B\x0D....\xC7\x44\x24\x40\x58\x54\x4C\x48'
def call_after(d,start,pat,limit):
    i=d.find(pat,start,start+limit)
    if i<0: return None
    j=i+len(pat)-1  # pozycja E8
    return j+5+struct.unpack_from('<i',d,j+1)[0]
for dll in ['W40kMod.dll','WXPMod.dll','DXP2Mod.dll','DXP3Mod.dll']:
    pe=pefile.PE(os.path.join(g,dll),fast_load=True); d=bytes(pe.get_memory_mapped_image())
    td=[m.start() for m in re.finditer(SIG_TD,d,re.S)]
    w=[m.start() for m in re.finditer(SIG_W,d,re.S)]
    sh=call_after(d,td[0],b'\xF3\x0F\x5C\xC8\x48\x8B\xCB\xE8',0x100) if len(td)==1 else None
    de=call_after(d,sh,b'\x33\xD2\x48\x8B\xCB\xE8',0x140) if sh else None
    wg=(w[0]+7+struct.unpack_from('<i',d,w[0]+3)[0]) if len(w)==1 else None
    print('%-12s TakeDamage=%s SetHealth=%s Death=%s World=%s'%(dll,[hex(x) for x in td],hex(sh) if sh else None,hex(de) if de else None,hex(wg) if wg else None))
