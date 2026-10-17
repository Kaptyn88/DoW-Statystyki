import pefile,glob,os,sys
g=sys.argv[1]
files=[f for f in glob.glob(g+'/*.dll')+glob.glob(g+'/*.exe') if os.path.getsize(f)>100000]
needle=[b'Squad_GetHealth',b'Entity_GetHealth',b'Scar_DoString',b'Rule_AddInterval',b'SGroup_ForEach']
for f in sorted(files):
    d=open(f,'rb').read()
    hits={n.decode():d.count(n) for n in needle if n in d}
    if hits: print(os.path.basename(f),os.path.getsize(f),hits)
for f in ['SimEngine.dll','W40kMod.dll','W40k.exe']:
    pe=pefile.PE(g+'/'+f,fast_load=True)
    print('==',f,hex(pe.OPTIONAL_HEADER.ImageBase),'machine',hex(pe.FILE_HEADER.Machine),'ts',pe.FILE_HEADER.TimeDateStamp)
    for s in pe.sections: print('  ',s.Name.rstrip(b'\0').decode(),hex(s.VirtualAddress),hex(s.Misc_VirtualSize),hex(s.SizeOfRawData))
    pe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY_EXPORT])
    if hasattr(pe,'DIRECTORY_ENTRY_EXPORT'):
        ex=pe.DIRECTORY_ENTRY_EXPORT.symbols
        print('   exports',len(ex),[e.name.decode() for e in ex if e.name][:15])
