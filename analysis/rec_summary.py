# Podsumowanie sesji rejestratora (recordings/*.jsonl): statystyki per oddział i per gracz.
# Użycie: python rec_summary.py <plik.jsonl> [--do SEKUNDY] [--top N]
import sys, json, argparse, collections

ap = argparse.ArgumentParser()
ap.add_argument('path')
ap.add_argument('--do', type=float, default=None, help='licz tylko zdarzenia do tej sekundy gry')
ap.add_argument('--top', type=int, default=25)
args = ap.parse_args()

meta = {}; players = {}; ents = {}; weapons = {}
def unit_key(eid, sq):
    # oddział: sq>0; budynki/encje bez oddziału: osobno per encja
    return ('sq', sq) if sq else ('ent', eid)

stats = collections.defaultdict(lambda: collections.Counter())
wstats = collections.defaultdict(lambda: collections.Counter())
label = {}; owner = {}
last_sq = {}  # id encji -> ostatni niezerowy oddział (starsze nagrania zapisywały sq=0 zabitego modelu)
tps = 8
for line in open(args.path, encoding='utf-8'):
    r = json.loads(line)
    t = r['t']
    if t == 'meta': meta = r; tps = r.get('tps', 8)
    elif t == 'player': players[r['pid']] = r['name'] or f"gracz {r['pid']}"
    elif t == 'wpn': weapons[r['wid']] = r['name'] + (' (wręcz)' if r['melee'] else '')
    elif t == 'ent':
        ents[r['id']] = r
        if r['sq']: last_sq[r['id']] = r['sq']
        elif r['id'] in last_sq: continue
        k = unit_key(r['id'], r['sq'])
        label[k] = r['sqbp'] or r['bp']; owner[k] = r['pid']
    elif t in ('dmg', 'die'):
        if args.do is not None and r['tick'] / tps > args.do: continue
        if t == 'dmg':
            ak = unit_key(r['a'], r['as'] or last_sq.get(r['a'], 0)); vk = unit_key(r['v'], r['vs'] or last_sq.get(r['v'], 0))
            if r['ff']:
                stats[ak]['ff'] += r['hp']
            else:
                stats[ak]['zadane'] += r['hp']; stats[ak]['nominalne'] += r['nom']; stats[ak]['zabite'] += r['k']
                wstats[r['w']]['zadane'] += r['hp']; wstats[r['w']]['zabite'] += r['k']
            stats[vk]['otrzymane'] += r['hp']; stats[vk]['stracone'] += r['k']
        else:
            stats[unit_key(r['v'], r['vs'] or last_sq.get(r['v'], 0))]['stracone_inne'] += 1

print(f"Powtórka: {meta.get('replay')}  mod: {meta.get('mod')}")
print('Gracze:', ', '.join(f'{p}={n}' for p, n in players.items()))
print()
rows = sorted(stats.items(), key=lambda kv: -kv[1]['zadane'])
tot = collections.Counter()
for _, c in rows: tot['zadane'] += c['zadane']
print(f"{'#':>3} {'oddział':<38} {'gracz':<14} {'zadane':>9} {'udział':>7} {'zabite':>6} {'otrzym.':>9} {'strac.':>6} {'FF':>6}")
for i, (k, c) in enumerate(rows[:args.top], 1):
    name = f"{label.get(k, '?')} [{k[0]}{k[1]}]"
    pl = players.get(owner.get(k), '?')
    share = 100 * c['zadane'] / tot['zadane'] if tot['zadane'] else 0
    print(f"{i:>3} {name:<38} {pl[:14]:<14} {c['zadane']:>9.0f} {share:>6.1f}% {c['zabite']:>6} {c['otrzymane']:>9.0f} "
          f"{c['stracone'] + c['stracone_inne']:>6} {c['ff']:>6.0f}")
print()
print('Broń (zadane / zabite):')
for w, c in sorted(wstats.items(), key=lambda kv: -kv[1]['zadane'])[:15]:
    print(f"  {weapons.get(w, 'bez WeaponInfo' if w == -1 else w):<45} {c['zadane']:>9.0f} {c['zabite']:>5}")
