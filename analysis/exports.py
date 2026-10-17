import pefile,sys,re,os
g=sys.argv[1]
for f in ['W40kMod.dll','SimEngine.dll']:
    pe=pefile.PE(os.path.join(g,f),fast_load=True)
    pe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY['IMAGE_DIRECTORY_ENTRY_EXPORT']])
    ex=getattr(pe,'DIRECTORY_ENTRY_EXPORT',None)
    names=[(e.name.decode(),e.address) for e in ex.symbols if e.name] if ex else []
    print('=====',f,'exports',len(names),'imagebase',hex(pe.OPTIONAL_HEADER.ImageBase))
    open('/tmp/an_exports_'+f+'.txt','w').write('\n'.join('%x %s'%(a,n) for n,a in names))
    rx=re.compile(r'(Damage|Health|Kill|Attack|Death|Dead|Weapon|Fire|Shoot|Hit|Combat)',re.I)
    sel=[(n,a) for n,a in names if rx.search(n)]
    print('matching',len(sel))
    for n,a in sel[:150]: print(hex(a),n)
