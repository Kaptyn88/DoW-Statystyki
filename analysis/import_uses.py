# Pokazuje miejsca wywołań importowanej funkcji (call [rip+imp]) w W40kMod.dll wraz z kilkoma instrukcjami przed nimi
import pefile,sys,os,struct,capstone
g=sys.argv[1]; name=sys.argv[2]; nmax=int(sys.argv[3]) if len(sys.argv)>3 else 15
pe=pefile.PE(os.path.join(g,'W40kMod.dll'))
d=pe.get_memory_mapped_image(); base=pe.OPTIONAL_HEADER.ImageBase
slot=None
for e in pe.DIRECTORY_ENTRY_IMPORT:
    for i in e.imports:
        if i.name and i.name.decode()==name: slot=i.address-base
print('IAT slot',hex(slot))
t=[s for s in pe.sections if s.Name.startswith(b'.text')][0]
md=capstone.Cs(capstone.CS_ARCH_X86,capstone.CS_MODE_64)
n=0
for i in range(t.VirtualAddress,t.VirtualAddress+t.Misc_VirtualSize-6):
    if d[i]==0xFF and d[i+1] in (0x15,0x25) and i+6+struct.unpack_from('<i',d,i+2)[0]==slot:
        n+=1
        if n>nmax: continue
        print('-- use at %x'%i)
        for ins in md.disasm(d[i-40:i+6],i-40):
            if ins.address>=i-24: print('   %x: %s %s'%(ins.address,ins.mnemonic,ins.op_str))
print('total uses',n)
