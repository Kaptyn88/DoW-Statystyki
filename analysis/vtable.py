import pefile,sys,os,struct,re
g=sys.argv[1]; cls=sys.argv[2]
pe=pefile.PE(os.path.join(g,'W40kMod.dll'),fast_load=True)
d=pe.get_memory_mapped_image(); base=pe.OPTIONAL_HEADER.ImageBase
name=('.?AV'+cls+'@@').encode()
i=d.find(name); td=i-16
print('typedesc rva',hex(td))
cols=[]
for m in re.finditer(struct.pack('<I',td),d):
    p=m.start()
    if p>=12 and struct.unpack_from('<I',d,p-12)[0]==1 and p%4==0: cols.append(p-12)
print('COLs',[hex(c) for c in cols])
for c in cols:
    ptr=struct.pack('<Q',base+c)
    for m in re.finditer(re.escape(ptr),d):
        vt=m.start()+8
        print('vtable at rva',hex(vt))
        slots=[]
        for k in range(0,80):
            v=struct.unpack_from('<Q',d,vt+8*k)[0]
            if not (base<=v<base+len(d)): break
            slots.append(v-base)
        print('  slots:',' '.join('%d:%x'%(k,s) for k,s in enumerate(slots)))
