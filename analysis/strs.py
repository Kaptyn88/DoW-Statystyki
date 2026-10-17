import re,sys,os
g=sys.argv[1]
pat=re.compile(rb'[ -~]{4,160}')
kw=re.compile(r'(damage|Damage|DAMAGE|Weapon|weapon|Health|health|Killed|killed|Casualt|Death|Combat|Attack|Projectile|Kill)')
for f in ['W40kMod.dll','SimEngine.dll']:
    d=open(os.path.join(g,f),'rb').read()
    out=set()
    for m in pat.finditer(d):
        s=m.group().decode()
        if kw.search(s): out.add(s)
    print('=====',f,len(out))
    rtti=[s for s in out if s.startswith('.?AV') or s.startswith('.?AU')]
    print('--RTTI',len(rtti))
    for s in sorted(rtti)[:120]: print(s)
    print('--other')
    for s in sorted(out-set(rtti))[:200]: print(s)
