"""Buduje katalog broni, zdolności, jednostek i oddziałów wszystkich ras z danych gry (DoW: Definitive Edition).

Użycie: python build_catalog.py [folder_gry] [--out catalog.json]
Wynik: catalog/catalog.json – nazwy polskie i angielskie (Engine.ucs), rasa, obrażenia, kto ma daną broń/zdolność.
Warstwy danych jak w grze (DoWDE.module): DoWDE > DXP3 > DXP2 > WXP > W40k (wyższa nadpisuje plik niższej).
"""
import argparse
import collections
import json
import os
import re
import struct
import sys

import icons
from rgd import Dictionary, parse
from sga import SgaArchive

HERE = os.path.dirname(os.path.abspath(__file__))
BS = chr(92)  # ukośnik wsteczny
ICON_DIR = BS.join(['art', 'ui', 'ingame', ''])  # ikony jednostek: art/ui/ingame/<rasa>_icons/<nazwa>.tga
DEFAULT_GAME = r'C:\Program Files (x86)\Steam\steamapps\common\Dawn of War Definitive Edition'
LAYERS = [('DoWDE', r'DoWDE\DoWDE.sga'), ('DXP3', r'DXP3\DXP3Data.sga'), ('DXP2', r'DXP2\DXP2Data.sga'),
          ('WXP', r'WXP\WXPData.sga'), ('W40k', r'W40k\W40kData.sga')]
KEYS = ['GameData', 'ui_info', 'ui_ext', 'screen_name_id', 'help_text_list', 'icon_name', 'area_effect',
        'area_effect_information', 'weapon_damage', 'armour_damage', 'min_damage', 'max_damage', 'radius',
        'duration_time', 'recharge_time', 'refresh_time', 'child_ability_name', '$REF', 'melee_weapon',
        'cost_ext', 'time_cost', 'cost', 'requisition', 'power', 'squad_reinforce_ext', 'squad_leader_ext', 'leader',
        'type', 'squad_loadout_ext', 'trooper_base', 'unit_min']
# przedrostek nazwy -> nazwa folderu rasy w attrib/ebps/races
RACE_PREFIXES = [('dark_eldar', 'dark_eldar'), ('space_marine', 'space_marines'), ('chaos', 'chaos'),
                 ('eldar', 'eldar'), ('guard', 'guard'), ('ork', 'orks'), ('necron', 'necrons'), ('tau', 'tau'),
                 ('sisters', 'sisters'), ('sm_', 'space_marines'), ('marine', 'space_marines'), ('inquisition', 'sisters')]


def load_ucs(path):
    out = {}
    if not os.path.exists(path):
        return out
    with open(path, encoding='utf-16') as f:
        for line in f:
            k, _, v = line.rstrip('\r\n').partition('\t')
            if k.isdigit():
                out[int(k)] = v
    return out


class Vfs:
    """Wirtualny system plików z warstw archiwów (pierwsza warstwa zawierająca plik wygrywa)."""

    def __init__(self, game):
        self.archives = []
        for name, rel in LAYERS:
            p = os.path.join(game, rel)
            if os.path.exists(p):
                self.archives.append((name, SgaArchive(p)))
        self.index = {}
        for name, a in reversed(self.archives):  # niższe najpierw, wyższe nadpisują
            for path in a.files:
                if path.startswith('attrib\\') or path.startswith(ICON_DIR):  # dane + ikony jednostek
                    self.index[path] = (name, a)

    def list(self, prefix):
        return sorted(p for p in self.index if p.startswith(prefix))

    def read(self, path):
        name, a = self.index[path]
        return name, a.read(path)


def walk(t, path=()):
    """Wszystkie (ścieżka kluczy, wartość) liści drzewa."""
    for k, v in t.items():
        if isinstance(v, dict):
            yield from walk(v, path + (k,))
        else:
            yield path + (k,), v


def text_id(v):
    return int(v[1:]) if isinstance(v, str) and re.fullmatch(r'\$\d+', v) and v != '$0' else None


def race_of(name):
    for prefix, race in RACE_PREFIXES:
        if name.startswith(prefix):
            return race
    return None


def screen_name(t):
    """Najpłycej położone ui_info/screen_name_id (jednostki: ui_ext/ui_info, oddziały: <ext>/ui_info, zdolności: ui_info)."""
    best = None
    for path, v in walk(t):
        if path[-1] == 'screen_name_id' and len(path) >= 2 and path[-2] == 'ui_info':
            tid = text_id(v)
            if tid and (best is None or len(path) < best[0]):
                best = (len(path), tid)
    return best[1] if best else None


def icon_name(t):
    """Najpłycej położone ui_info/icon_name, np. 'eldar_icons/farseer_icon' (pusty napis -> None)."""
    best = None
    for path, v in walk(t):
        if path[-1] == 'icon_name' and len(path) >= 2 and path[-2] == 'ui_info' and isinstance(v, str) and v.strip():
            if best is None or len(path) < best[0]:
                best = (len(path), v.strip().lower())
    return best[1] if best else None


def extract_icons(vfs, cat, out_dir):
    """Ikony oddziałów, jednostek i zdolności: TGA z gry -> out_dir/icons/<nazwa>_<rozmiar>.png.
    Zapisuje cat['icons'] = {nazwa ikony: rdzeń nazwy pliku}; brakujące w archiwach pomija."""
    os.makedirs(os.path.join(out_dir, 'icons'), exist_ok=True)
    wanted = {e['icon'] for kind in ('squads', 'units', 'abilities', 'research') for e in cat[kind].values() if e.get('icon')}
    done = {}
    for icon in sorted(wanted):
        src = ICON_DIR + icon.replace('/', BS) + '.tga'
        if src not in vfs.index:
            continue
        try:
            w, h, rows = icons.read_tga(vfs.read(src)[1])
        except (ValueError, IndexError, struct.error):
            continue
        stem = icons.file_stem(icon)
        for size in icons.SIZES:
            icons.write_png(os.path.join(out_dir, 'icons', f'{stem}_{size}.png'), icons.resize(w, h, rows, size))
        done[icon] = stem
    cat['icons'] = done
    return len(done), len(wanted)


def damage_of(t):
    """(min, max) obrażeń z tabel weapon_damage (bez tabel egzekucji, które mają wartości rzędu 100000)."""
    best = (0.0, 0.0)
    for path, v in walk(t):
        if path[-1] == 'max_damage' and 'armour_damage' in path and isinstance(v, float) and 0 < v < 50000:
            mn = 0.0
            node = t
            for k in path[:-1]:
                node = node[k]
            mn = node.get('min_damage', 0.0)
            if v > best[1]:
                best = (mn, v)
    return best


def cost_of(t):
    """Cena modelu/budynku z cost_ext/time_cost/cost: [rekwizycja, energia] (bez ulepszeń broni oddziału)."""
    ce = t.get('cost_ext')
    c = ce.get('time_cost', {}).get('cost', {}) if isinstance(ce, dict) else {}
    return [round(float(c.get('requisition', 0.0) or 0.0), 1), round(float(c.get('power', 0.0) or 0.0), 1)]


def refs(t, folder):
    """Odwołania do innych plików danych, np. 'abilities\\x.lua' albo 'weapon\\y.lua' -> nazwy bez rozszerzenia."""
    out = set()
    pat = re.compile(r'^' + re.escape(folder) + r'\\(.+)\.(lua|rgd)$', re.I)
    for path, v in walk(t):
        if isinstance(v, str) and path[-1] != '$REF':
            m = pat.match(v)
            if m:
                out.add(m.group(1).lower())
    return out


def find_game():
    """Folder gry: biblioteki Steam (HKCU/Software/Valve/Steam: SteamPath -> steamapps/libraryfolders.vdf,
    aplikacja 3556750), inaczej domyślna ścieżka. Ta sama logika co FindGameDir w launcher.cpp."""
    sub = os.path.join('steamapps', 'common', 'Dawn of War Definitive Edition')
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'Software\Valve\Steam') as k:
            steam = winreg.QueryValueEx(k, 'SteamPath')[0]
        with open(os.path.join(steam, 'steamapps', 'libraryfolders.vdf'), encoding='utf-8', errors='replace') as f:
            text = f.read()
        libs, lib = [], None
        for line in text.splitlines():
            m = re.search(r'"path"\s+"(.*)"', line)
            if m:
                lib = m.group(1).replace(2 * BS, BS)  # w .vdf ukośniki są podwojone
                libs.append(lib)
            elif '"3556750"' in line and lib and os.path.exists(os.path.join(lib, sub, 'W40k.exe')):
                return os.path.join(lib, sub)
        for lib in libs:
            if os.path.exists(os.path.join(lib, sub, 'W40k.exe')):
                return os.path.join(lib, sub)
    except (OSError, ImportError):
        pass
    return DEFAULT_GAME


class Args:
    def __init__(self, game, out):
        self.game, self.out = game, out


def build(game=None, out=None):
    """Buduje katalog (wołane też z podglądu przy pierwszym uruchomieniu paczki). Zwraca ścieżkę wyniku."""
    out = out or os.path.join(HERE, 'catalog.json')
    _build(Args(game or find_game(), out))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('game', nargs='?', default=None)
    ap.add_argument('--out', default=os.path.join(HERE, 'catalog.json'))
    args = ap.parse_args()
    args.game = args.game or find_game()
    _build(args)


def _build(args):
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)

    vfs = Vfs(args.game)
    print('warstwy:', [n for n, _ in vfs.archives], '· plików attrib:', len(vfs.index))
    pl = load_ucs(os.path.join(args.game, r'Engine\Locale\Polish\Engine.ucs'))
    en = load_ucs(os.path.join(args.game, r'Engine\Locale\English\Engine.ucs'))
    ru = load_ucs(os.path.join(args.game, r'Engine\Locale\Russian\Engine.ucs'))
    dic = Dictionary(KEYS)

    def names(tid):
        return ({'pl': pl.get(tid, ''), 'en': en.get(tid, ''), 'ru': ru.get(tid, '')} if tid
                else {'pl': '', 'en': '', 'ru': ''})

    def load(prefix):
        out = {}
        for p in vfs.list(prefix):
            if not p.endswith('.rgd'):
                continue
            try:
                layer, data = vfs.read(p)
                out[p] = (layer, parse(data, dic))
            except Exception as e:  # pojedynczy uszkodzony plik nie zatrzymuje katalogu
                print('  pominięto', p, e, file=sys.stderr)
        return out

    cat = {'version': 6, 'abilities': {}, 'weapons': {}, 'units': {}, 'squads': {}, 'research': {}, 'source': {
        'layers': [n for n, _ in vfs.archives], 'ucs': 'Engine/Locale/{Polish,English,Russian}/Engine.ucs'}}

    for p, (layer, t) in load('attrib\\abilities\\').items():
        name = os.path.splitext(os.path.basename(p))[0]
        mn, mx = damage_of(t)
        ae = t.get('area_effect', {}).get('area_effect_information', {}) if isinstance(t.get('area_effect'), dict) else {}
        child = t.get('child_ability_name') or ''
        cat['abilities'][name] = {**names(screen_name(t)), 'icon': icon_name(t), 'race': race_of(name), 'layer': layer,
                                  'child': child.lower() if isinstance(child, str) else '',
                                  'damage': [round(mn, 1), round(mx, 1)], 'radius': ae.get('radius', 0.0),
                                  'duration': t.get('duration_time', 0.0), 'recharge': t.get('recharge_time', 0.0),
                                  'units': [], 'squads': []}
    for p, (layer, t) in load('attrib\\weapon\\').items():
        name = os.path.splitext(os.path.basename(p))[0]
        mn, mx = damage_of(t)
        wc = t.get('cost', {}).get('cost', {}) if isinstance(t.get('cost'), dict) else {}  # cena ulepszenia broni
        cat['weapons'][name] = {**names(screen_name(t)), 'race': race_of(name), 'layer': layer,
                                'damage': [round(mn, 1), round(mx, 1)], 'units': [],
                                'cost': [round(float(wc.get('requisition', 0.0) or 0.0), 1),
                                         round(float(wc.get('power', 0.0) or 0.0), 1)]}
    # badania (ulepszenia): nazwa, ikona, rasa, koszt (time_cost/cost – inaczej niż jednostki: cost_ext/time_cost/cost)
    for kind, prefix in (('research', 'attrib\\research\\'),):
        for p, (layer, t) in load(prefix).items():
            name = os.path.splitext(os.path.basename(p))[0]
            c = t.get('time_cost', {}).get('cost', {}) if isinstance(t.get('time_cost'), dict) else {}
            cat[kind][name] = {**names(screen_name(t)), 'icon': icon_name(t), 'race': race_of(name),
                               'layer': layer, 'cost': [round(float(c.get('requisition', 0.0) or 0.0), 1),
                                                        round(float(c.get('power', 0.0) or 0.0), 1)]}
    for kind, prefix in (('units', 'attrib\\ebps\\races\\'), ('squads', 'attrib\\sbps\\races\\')):
        for p, (layer, t) in load(prefix).items():
            parts = p.split('\\')
            name = os.path.splitext(parts[-1])[0]
            entry = {**names(screen_name(t)), 'icon': icon_name(t), 'race': parts[3], 'category': parts[4] if len(parts) > 5 else '',
                     'layer': layer, 'abilities': sorted(refs(t, 'abilities'))}
            if kind == 'units':
                entry['weapons'] = sorted(refs(t, 'weapon'))
                entry['cost'] = cost_of(t)
            else:
                entry['units'] = sorted(refs(t, 'ebps\\races\\' + parts[3] + '\\' + entry['category'])
                                        | {r.split('\\')[-1] for r in refs(t, 'ebps')})
                # koszt uzupełnienia jednego modelu (squad_reinforce_ext/cost/cost) i typy liderów (squad_leader_ext/*/
                # leader/type) – do liczenia faktycznie wydanych zasobów (zakup oddziału vs uzupełnienia)
                rf = t.get('squad_reinforce_ext')
                rc = rf.get('cost', {}).get('cost', {}) if isinstance(rf, dict) else {}
                entry['reinforce'] = [round(float(rc.get('requisition', 0.0) or 0.0), 1),
                                      round(float(rc.get('power', 0.0) or 0.0), 1)] if rc else None
                entry['leaders'] = sorted({v.split('\\')[-1][:-4].lower() for path, v in walk(t.get('squad_leader_ext', {}))
                                           if path[-1] == 'type' and isinstance(v, str) and v.endswith('.lua')})
            cat[kind][name] = entry

    # zdolności potomne (kolejne fazy jednej mocy) -> rodzic: z pola child_ability_name, a gdy go brak –
    # PRZYPUSZCZENIE z nazwy (doombolt3 -> doombolt, let_it_burn_child_2 -> let_it_burn, warp_storm_damage_1 -> warp_storm)
    abil = cat['abilities']
    for name, a in abil.items():
        if a['child'] in abil and a['child'] != name:
            abil[a['child']].setdefault('parent', name)
    suffix = re.compile(r'(_child)?_?\d+$|_damage(_\d+)?$|_dot$|_aura$|_fx$')
    for name, a in abil.items():
        if 'parent' in a:
            continue
        base = name
        while True:
            nb = suffix.sub('', base)
            if nb == base:
                break
            base = nb
            if base in abil and base != name:
                a['parent'], a['parent_guess'] = base, True
                break

    # kto ma daną broń/zdolność (+ rasa zdolności/broni z jednostek, gdy nie wynika z nazwy)
    for uname, u in cat['units'].items():
        for a in u['abilities']:
            if a in cat['abilities']:
                cat['abilities'][a]['units'].append(uname)
                cat['abilities'][a]['race'] = cat['abilities'][a]['race'] or u['race']
        for w in u['weapons']:
            if w in cat['weapons']:
                cat['weapons'][w]['units'].append(uname)
                cat['weapons'][w]['race'] = cat['weapons'][w]['race'] or u['race']
    for sname, s in cat['squads'].items():
        for a in s['abilities']:
            if a in cat['abilities']:
                cat['abilities'][a]['squads'].append(sname)
                cat['abilities'][a]['race'] = cat['abilities'][a]['race'] or s['race']

    def root(name, seen=()):
        p = abil[name].get('parent')
        return root(p, seen + (name,)) if p and p not in seen and p in abil else name
    for name, a in abil.items():
        r = root(name)
        if r != name:
            a['root'] = r
            for key in ('pl', 'en', 'ru'):
                if not a[key]:
                    a[key] = abil[r][key]
            a['race'] = a['race'] or abil[r]['race']
            if not a['units'] and not a['squads']:
                a['units'], a['squads'] = list(abil[r]['units']), list(abil[r]['squads'])

    # Moce globalne gracza (np. moce duszy Mrocznych Eldarów): w danych gry to zdolności głównego budynku (*_hq),
    # rzucane z puli gracza, a nie przez oddział. Oznaczamy je (z fazami potomnymi), żeby podgląd liczył je osobno.
    for name, a in abil.items():
        owners = set(a['units']) | set(abil.get(a.get('root', ''), {}).get('units', []))
        a['global'] = any(cat['units'].get(u, {}).get('category') == 'structures' and re.search(r'_hq($|_)', u)
                          for u in owners)

    got, want = extract_icons(vfs, cat, os.path.dirname(os.path.abspath(args.out)))
    print(f'ikony: {got}/{want} (PNG {icons.SIZES} px w folderze icons)')

    with open(args.out, 'w', encoding='utf-8') as f:
        json.dump(cat, f, ensure_ascii=False, indent=1, sort_keys=True)
    dmg_ab = [a for a, v in cat['abilities'].items() if v['damage'][1] > 0]
    races = collections.Counter(v['race'] for v in cat['abilities'].values() if v['damage'][1] > 0)
    print(f"zdolności: {len(cat['abilities'])} (zadające obrażenia: {len(dmg_ab)}), broni: {len(cat['weapons'])}, "
          f"jednostek: {len(cat['units'])}, oddziałów: {len(cat['squads'])}")
    print('zdolności z obrażeniami wg rasy:', dict(races))
    print('zapisano', args.out)


if __name__ == '__main__':
    main()
