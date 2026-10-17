# Dla RVA podaje funkcję główną (podąża za łańcuchem UNW_FLAG_CHAININFO w .pdata/.xdata) – DXP3Mod.dll domyślnie
import pefile,sys,os,bisect,struct
g=sys.argv[1]; dll=sys.argv[2]; rvas=[int(x,16) for x in sys.argv[3:]]
pe=pefile.PE(os.path.join(g,dll),fast_load=True); d=pe.get_memory_mapped_image()
pe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY['IMAGE_DIRECTORY_ENTRY_EXCEPTION']])
ents=sorted((e.struct.BeginAddress,e.struct.EndAddress,e.struct.UnwindData) for e in pe.DIRECTORY_ENTRY_EXCEPTION)
starts=[e[0] for e in ents]
for a in rvas:
    i=bisect.bisect_right(starts,a)-1; b,e,u=ents[i]; chain=[(b,e)]
    while d[u]>>3 & 4:  # CHAININFO
        cnt=d[u+2]; off=u+4+((cnt+1)&~1)*2
        b,e,u=struct.unpack_from('<III',d,off); chain.append((b,e))
    print(hex(a),'->',' <- '.join('%x-%x'%c for c in chain))
