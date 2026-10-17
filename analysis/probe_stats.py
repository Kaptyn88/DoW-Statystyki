# Statystyki logu sondy: unikalne ślady stosu per rodzaj zdarzenia i offsety stosu z innymi encjami
import sys,re,collections
L=sys.argv[1]
stk=collections.defaultdict(collections.Counter); sent=collections.defaultdict(collections.Counter)
amt=collections.defaultdict(float); ents={}
for line in open(L,encoding='utf-8',errors='replace'):
    k=line.split(' ',1)[0]
    if k=='E':
        m=re.search(r'id=(\d+).* bp=(\S*)',line); ents[m.group(1)]=m.group(2); continue
    if k not in ('SET','DMG','DIE'): continue
    s=re.search(r' stk=(\S*)',line).group(1).split(',')
    stk[k][','.join(s[:6])]+=1
    se=re.search(r' sent=(\S*)',line).group(1)
    sent[k]['any' if se else 'none']+=1
    for x in filter(None,se.split(',')):
        off,_=x.split(':'); sent[k+'_off'][off]+=1
for k in ('DMG','SET','DIE'):
    print('=====',k,'stacks (pierwsze 6 ramek)')
    for s,n in stk[k].most_common(15): print('%6d  %s'%(n,s))
    print('  sent:',dict(sent[k]),' top offsets:',sent[k+'_off'].most_common(8))
