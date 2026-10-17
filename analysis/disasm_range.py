import pefile,sys,os,capstone,struct,bisect
g=sys.argv[1]; dll=sys.argv[2]; start=int(sys.argv[3],16); length=int(sys.argv[4],16)
pe=pefile.PE(os.path.join(g,dll))
data=pe.get_memory_mapped_image()
imp={}
if hasattr(pe,'DIRECTORY_ENTRY_IMPORT'):
    for d in pe.DIRECTORY_ENTRY_IMPORT:
        for i in d.imports:
            if i.name: imp[i.address-pe.OPTIONAL_HEADER.ImageBase]=(d.dll.decode(),i.name.decode())
md=capstone.Cs(capstone.CS_ARCH_X86,capstone.CS_MODE_64); md.detail=False
code=data[start:start+length]
for ins in md.disasm(code,start):
    note=''
    if 'rip' in ins.op_str:
        # compute target
        import re
        m=re.search(r'rip ([+-]) (0x[0-9a-f]+)',ins.op_str)
        if m:
            off=int(m.group(2),16)*(1 if m.group(1)=='+' else -1)
            tgt=ins.address+ins.size+off
            if tgt in imp: note=' ; IMP '+imp[tgt][1]
            else:
                # string?
                s=data[tgt:tgt+60]
                z=s.split(b'\0')[0]
                if len(z)>=4 and all(32<=c<127 for c in z): note=' ; "%s"'%z.decode()
                else: note=' ; ->0x%x'%tgt
    print('%x: %-8s %s%s'%(ins.address,ins.mnemonic,ins.op_str,note))
