import pefile,sys,os,struct,re,bisect
g=sys.argv[1]; dll=sys.argv[2]; strings=sys.argv[3:]
pe=pefile.PE(os.path.join(g,dll),fast_load=True)
data=pe.get_memory_mapped_image()
base=pe.OPTIONAL_HEADER.ImageBase
text=[s for s in pe.sections if s.Name.startswith(b'.text')][0]
tva,tsz=text.VirtualAddress,text.Misc_VirtualSize
tb=data[tva:tva+tsz]
# pdata
pe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY['IMAGE_DIRECTORY_ENTRY_EXCEPTION']])
funcs=sorted((e.struct.BeginAddress,e.struct.EndAddress) for e in pe.DIRECTORY_ENTRY_EXCEPTION)
starts=[f[0] for f in funcs]
def func_of(rva):
    i=bisect.bisect_right(starts,rva)-1
    return funcs[i] if i>=0 and funcs[i][0]<=rva<funcs[i][1] else None
# find string rvas
for s in strings:
    needle=s.encode()+b'\0'
    rvas=[m.start() for m in re.finditer(re.escape(needle),data)]
    # exact start of string only (preceded by NUL)
    rvas=[r for r in rvas if r==0 or data[r-1]==0]
    print('##',s,'string rvas',[hex(r) for r in rvas])
    for r in rvas:
        refs=[]
        for m in re.finditer(rb'[\x48\x4c]\x8d[\x05\x0d\x15\x1d\x25\x2d\x35\x3d]',tb,re.S):
            i=m.start()
            disp=struct.unpack_from('<i',tb,i+3)[0]
            tgt=tva+i+7+disp
            if tgt==r: refs.append(tva+i)
        for a in refs:
            f=func_of(a)
            print('   xref at',hex(a),'func',(hex(f[0]),hex(f[1])) if f else None)
