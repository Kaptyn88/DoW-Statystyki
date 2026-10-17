import pefile,sys,os,struct,bisect
g=sys.argv[1]; targets=[int(x,16) for x in sys.argv[2:]]
pe=pefile.PE(os.path.join(g,'W40kMod.dll'),fast_load=True)
data=pe.get_memory_mapped_image(); base=pe.OPTIONAL_HEADER.ImageBase
t=[s for s in pe.sections if s.Name.startswith(b'.text')][0]
tva,tsz=t.VirtualAddress,t.Misc_VirtualSize
pe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY['IMAGE_DIRECTORY_ENTRY_EXCEPTION']])
funcs=sorted((e.struct.BeginAddress,e.struct.EndAddress) for e in pe.DIRECTORY_ENTRY_EXCEPTION)
starts=[f[0] for f in funcs]
def fo(a):
    i=bisect.bisect_right(starts,a)-1
    return funcs[i][0] if i>=0 and funcs[i][0]<=a<funcs[i][1] else None
T=set(targets)
for i in range(tva,tva+tsz-5):
    if data[i] in (0xE8,0xE9):
        tgt=i+5+struct.unpack_from('<i',data,i+1)[0]
        if tgt in T: print('call/jmp %x -> %x  in func %s'%(i,tgt,hex(fo(i)) if fo(i) else None))
# absolute pointers (vtables)
vals={base+x:x for x in targets}
for s in pe.sections:
    if s.Name.startswith(b'.rdata') or s.Name.startswith(b'.data'):
        a=s.VirtualAddress; n=s.Misc_VirtualSize
        for off in range(0,n-7,8):
            v=struct.unpack_from('<Q',data,a+off)[0]
            if v in vals: print('vtable-slot at rva %x holds %x'%(a+off,vals[v]))
