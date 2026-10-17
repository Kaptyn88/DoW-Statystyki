# Analiza linii APP (sonda v2): atakujący/ofiara/broń dla wywołań ApplyDamage, które zadały obrażenia
import sys,re,collections
L=sys.argv[1]
rx=re.compile(r'victim=(\S+) attacker=(\S+) res=(\S+) hpLoss=(\S+) sets=(\d+) deaths=(\d+) f5=(\S+) b6=(\d+) r8=(\S+)\((.*?)\) r9=(\S+)\((.*?)\) w=(\S*) wid=(\S+) stk=(\S+)')
tot=collections.Counter(); weap=collections.Counter(); r8c=collections.Counter(); r9c=collections.Counter()
pairs=collections.Counter(); kills=collections.Counter(); dmg=collections.defaultdict(float); stk=collections.Counter()
zero=collections.Counter(); mism=0; ex=[]
for line in open(L,encoding='utf-8',errors='replace'):
    if not line.startswith('APP'): continue
    m=rx.search(line)
    if not m: tot['unparsed']+=1; continue
    v,a,res,hp,sets,de,f5,b6,r8,c8,r9,c9,w,wid,s=m.groups()
    res=float(res); hp=float(hp); de=int(de)
    if res<=0 and hp<=0 and de==0:
        tot['zero']+=1; zero[(v.split(':')[1],a.split(':')[1] if a!='0' else '0',w)]+=1; continue
    tot['effective']+=1
    if a=='0': tot['attacker NULL']+=1
    elif a.split(':')[3]==v.split(':')[3]: tot['same owner']+=1
    else: tot['enemy']+=1
    if abs(res-hp)>0.01: mism+=1; 
    if abs(res-hp)>0.01 and len(ex)<5: ex.append(line[:300])
    ab=a.split(':')[1] if a!='0' else 'NULL'
    weap[(ab,w,wid)]+=1; r8c[c8]+=1; r9c[c9]+=1; stk[','.join(s.split(',')[:2])]+=1
    dmg[ab]+=hp; kills[ab]+=de
print('tot',dict(tot)); print('res != hpLoss:',mism)
for e in ex: print('  ',e)
print('r8 klasy',r8c.most_common(5)); print('r9 klasy',r9c.most_common(5)); print('stosy',stk.most_common(5))
print('--- top (atakujący, broń, wid)'); 
for k,n in weap.most_common(25): print('%5d'%n,*k)
print('--- obrażenia/zabójstwa wg typu atakującego')
for k,v in sorted(dmg.items(),key=lambda x:-x[1])[:20]: print('%-34s dmg=%9.1f kills=%d'%(k,v,kills[k]))
print('--- zerowe (top)'); 
for k,n in zero.most_common(6): print('%6d'%n,*k)
