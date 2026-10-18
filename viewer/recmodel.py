"""Model danych nagrań dowrec (.jsonl): wczytywanie przyrostowe i statystyki oddziałów do zadanego czasu.

Format rekordów opisuje nagłówek probe/src/recorder.cpp. Oddział = squad id (>0); encje bez oddziału
(budynki, wieżyczki) traktowane są jako osobne "oddziały" z kluczem ('ent', id).
"""
import bisect
import collections
import json
import os

TPS_DEFAULT = 8
from i18n import lang, t
from paths import CATALOG_PATH

CATALOG_VERSION = 3  # 2: nazwy pl/en/ru; 3: ikony; starszy katalog podgląd buduje od nowa
ICONS_DIR = os.path.join(os.path.dirname(CATALOG_PATH), 'icons')
ICON_SIZES = (20, 26, 32)  # jak catalog/icons.py


class Catalog:
    """Nazwy z danych gry (catalog/build_catalog.py): oddziały, jednostki, bronie, zdolności – w języku interfejsu
    (pl/en/ru), z angielskim i polskim jako zapasem. Bez katalogu metody zwracają None (zostają nazwy techniczne)."""

    def __init__(self, path=CATALOG_PATH):
        self.path = path
        self.reload()

    def reload(self):
        """Wczytuje (ponownie) catalog.json – np. po zbudowaniu go przy pierwszym uruchomieniu paczki."""
        path = self.path
        try:
            with open(path, encoding='utf-8') as f:
                self.c = json.load(f)
        except (OSError, ValueError):
            self.c = {}

    def outdated(self):
        return self.c.get('version', 1) < CATALOG_VERSION

    @staticmethod
    def _pick(v):
        """Nazwa w języku interfejsu; zapas: angielska, potem polska."""
        return (v.get(lang()) or v.get('en') or v.get('pl') or None) if v else None

    def _name(self, kind, key):
        return self._pick(self.c.get(kind, {}).get((key or '').lower()))

    # -- ikony (catalog/icons/<rdzeń>_<rozmiar>.png, zbudowane z plików gry)
    def icon_file(self, icon, size):
        stem = self.c.get('icons', {}).get(icon) if icon else None
        if not stem:
            return None
        size = min(ICON_SIZES, key=lambda s: abs(s - size))
        path = os.path.join(ICONS_DIR, f'{stem}_{size}.png')
        return path if os.path.exists(path) else None

    def squad_icon(self, bp):
        """Ikona oddziału; gdy oddział nie ma własnej (np. Oddział Dowodzenia Gwardii) – ikona jego pierwszej jednostki."""
        have = self.c.get('icons', {})
        for kind in ('squads', 'units'):
            v = self.c.get(kind, {}).get((bp or '').lower())
            if not v:
                continue
            if v.get('icon') in have:
                return v['icon']
            for u in v.get('units', []):
                uv = self.c.get('units', {}).get(u, {})
                if uv.get('icon') in have:
                    return uv['icon']
        return None

    def ability_icon(self, name):
        v = self.c.get('abilities', {}).get((name or '').lower())
        if not v:
            return None
        have = self.c.get('icons', {})
        root = self.c['abilities'].get(v.get('root', ''), {})
        return next((i for i in (v.get('icon'), root.get('icon')) if i in have), None)

    def is_structure(self, bp):
        v = self.c.get('units', {}).get((bp or '').lower())
        return bool(v and v.get('category') == 'structures') or 'mine_field' in (bp or '')

    def squad(self, bp):
        return self._name('squads', bp) or self._name('units', bp)

    def weapon(self, name):
        return self._name('weapons', name)

    def root(self, name):
        """Zdolność-rodzic dla fazy potomnej (np. dark_eldar_rend_soul_dot -> dark_eldar_rend_soul)."""
        v = self.c.get('abilities', {}).get((name or '').lower())
        return v.get('root', name) if v else name

    def has_dot(self, name):
        """Czy zdolność (rodzic) ma fazę obrażeń w czasie '<nazwa>_dot' (np. dark_eldar_rend_soul_dot)."""
        return (name or '').lower() + '_dot' in self.c.get('abilities', {})

    def is_global(self, name):
        """Moc globalna gracza (zdolność budynku HQ, np. moce duszy Mrocznych Eldarów) – patrz build_catalog."""
        v = self.c.get('abilities', {}).get((name or '').lower())
        return bool(v and v.get('global'))

    def ability(self, name):
        v = self.c.get('abilities', {}).get((name or '').lower())
        if not v:
            return None
        root = self.c['abilities'].get(v.get('root', ''), {})
        return self._pick(v) or self._pick(root)


CATALOG = Catalog()


def unit_key(eid, sq):
    return ('sq', sq) if sq else ('ent', eid)


def pretty_bp(bp):
    """necron_basic_warrior_squad -> Necron basic warrior; ork_squad_shoota_boy -> Ork shoota boy"""
    if not bp:
        return '?'
    parts = [p for p in bp.split('_') if p not in ('squad',)]
    s = ' '.join(parts)
    return s[:1].upper() + s[1:]


class Recording:
    """Wczytuje plik .jsonl przyrostowo (poll() dopisuje nowe linie)."""

    def __init__(self, path):
        self.path = path
        self._pos = 0
        self._partial = ''
        self.meta = {}
        self.tps = TPS_DEFAULT
        self.players = {}          # pid -> nazwa
        self.weapons = {}          # wid -> (nazwa, wręcz)
        self.units = {}            # klucz oddziału -> {'bp','pid','ents':set}
        self.last_sq = {}          # id encji -> ostatni niezerowy oddział
        self.ent_bp = {}           # id encji -> bp
        self.ent_pid = {}          # id encji -> gracz
        self.death_tick = {}       # id encji -> tick zgonu (z dmg.k i die)
        self.power_helpers = set() # oddziały-encje pomocnicze mocy gracza (np. encja Burzy Spaczni) – ukrywane
        self.selection = []        # zaznaczenie gracza w grze (rekord 'sel'): klucze oddziałów, ostatni stan
        self.selection_seq = 0     # rośnie przy każdej zmianie zaznaczenia (podgląd wie, kiedy przełączyć)
        self.events = []           # (tick, typ, rekord) w kolejności pliku
        self.ticks = []            # ticki zdarzeń (do bisect)
        self.max_tick = 0
        self.poll()

    # -- wczytywanie
    def poll(self):
        """Dopisuje nowe pełne linie z pliku. Zwraca liczbę nowych rekordów."""
        try:
            size = os.path.getsize(self.path)
        except OSError:
            return 0
        if size < self._pos:  # plik nadpisany – wczytaj od nowa
            self.__init__(self.path)
            return len(self.events)
        if size == self._pos:
            return 0
        with open(self.path, 'rb') as f:
            f.seek(self._pos)
            chunk = f.read()
        self._pos += len(chunk)
        text = self._partial + chunk.decode('utf-8', errors='replace')
        lines = text.split('\n')
        self._partial = lines.pop()  # ostatnia (niepełna) linia czeka na dopisanie
        n = 0
        for line in lines:
            if line.strip():
                try:
                    self._add(json.loads(line))
                    n += 1
                except json.JSONDecodeError:
                    pass
        return n

    def _add(self, r):
        t = r.get('t')
        if t == 'meta':
            self.meta = r
            self.tps = r.get('tps', TPS_DEFAULT)
        elif t == 'player':
            self.players[r['pid']] = r['name'] or f"gracz {r['pid']}"
        elif t == 'wpn':
            self.weapons[r['wid']] = (r['name'], r['melee'])
        elif t == 'ent':
            self.ent_bp[r['id']] = r['bp']
            self.ent_pid[r['id']] = r['pid']
            if r['sq']:
                self.last_sq[r['id']] = r['sq']
            elif r['id'] in self.last_sq:
                return  # wypięty z oddziału (starsze nagrania) – zostaje przy dawnym oddziale
            k = unit_key(r['id'], r['sq'])
            # first: przybliżony czas pojawienia się (ostatni znany tick; rekord 'ent' poprzedza pierwsze zdarzenie oddziału)
            u = self.units.setdefault(k, {'bp': r['sqbp'] or r['bp'], 'pid': r['pid'], 'ents': set(), 'first': self.max_tick})
            u['ents'].add(r['id'])
        elif t == 'sel':
            self.selection = [('sq', q) for q in r.get('sq', [])] + [('ent', e) for e in r.get('e', [])]
            self.selection_seq += 1
        elif t in ('dmg', 'die', 'hp', 'clock'):
            tick = r['tick']
            if (t == 'dmg' and r['k']) or t == 'die':
                self.death_tick.setdefault(r['v'], tick)
            self.max_tick = max(self.max_tick, tick)
            if t == 'dmg' and self._is_player_power(r):
                # moc globalna gracza – osobny "oddział" ('powers', gracz), nie budynek HQ ani żaden oddział
                pid = self.ent_pid.get(r['a'])
                r['_ak'] = ('powers', pid)
                self.power_helpers.add(self._key(r['a'], r['as']))
                self.units.setdefault(r['_ak'], {'bp': 'player_powers', 'pid': pid, 'ents': set(), 'first': tick})
            if t != 'clock':
                self.events.append((tick, t, r))
                self.ticks.append(tick)

    def _is_player_power(self, r):
        """Obrażenia z mocy globalnej: zdolność oznaczona w katalogu jako global albo (zapas) trafienie bez broni,
        którego źródłem jest główny budynek (*_hq) – HQ nie ma własnej broni, więc to moc rzucona przez gracza."""
        if r.get('w', 0) >= 0:
            return False
        ab = self._source_key(r)
        if ab[0] == 'ab' and CATALOG.is_global(ab[1]):
            return True
        bp = self.ent_bp.get(r['a'], '')
        return bp.endswith('_hq') or '_hq_' in bp

    def _key(self, eid, sq):
        return unit_key(eid, sq or self.last_sq.get(eid, 0))

    def _source_key(self, r):
        """Klucz źródła obrażeń bez WeaponInfo: nazwa zdolności albo wspólna pozycja "bez nazwy".
        Ścieżka kodu (src) nie odróżnia mocy od ataków specjalnych – granaty plazmowe (nazwane) i salwy ataków
        specjalnych idą tą samą ścieżką – więc nienazwane źródła łączymy w jedną pozycję."""
        # ab/abf: nazwa pliku i folder danych gry źródła (rejestrator od 2026-10-17); starsze nagrania – tylko ab
        ab, abf = r.get('ab', ''), r.get('abf', '')
        for folder in ('abilities', 'weapon'):  # nagranie testowe 173337: folder sklejony z nazwą ("abilities_x")
            if not abf and ab.startswith(folder + '_'):
                ab, abf = ab[len(folder) + 1:], folder
        if ab:
            # fazy jednej mocy liczymy razem pod zdolnością-rodzicem
            return ('ab', CATALOG.root(ab) if abf.startswith('abilit') else ab, abf)
        if 'sw' in r:
            # obszar rażenia bez pliku danych (nagranie 3v3 2026-10-17): rozróżniamy po atakującym
            a = r['a']
            dt = self.death_tick.get(a)
            if dt is not None and abs(r['tick'] - dt) <= 2:
                return ('explosion', '')                      # np. wybuch generatora przy zniszczeniu
            if CATALOG.is_structure(self.ent_bp.get(a, '')):
                return ('structure', '')                      # np. pole minowe
            if r['sw'] >= 0:
                return ('special', r['sw'])                   # atak specjalny wręcz (heurystyka: ostatnia broń wręcz)
        return ('unnamed', '')

    def unit_label(self, k):
        """Nazwa oddziału z numerem kolejnym wśród oddziałów tego samego typu u gracza (np. 'Ork shoota boy #2')."""
        u = self.units.get(k)
        if not u:
            return f'{k[0]}{k[1]}'
        if k[0] == 'powers':
            dark_eldar = any(b.startswith('dark_eldar') for e, b in self.ent_bp.items() if self.ent_pid.get(e) == k[1])
            return t('powers_soul') if dark_eldar else t('powers_player')
        same = sorted(kk for kk, uu in self.units.items() if uu['bp'] == u['bp'] and uu['pid'] == u['pid'])
        name = CATALOG.squad(u['bp']) or pretty_bp(u['bp'])
        return f'{name} #{same.index(k) + 1}' if len(same) > 1 else name

    # -- statystyki
    def stats(self, upto_tick=None, from_tick=None):
        """Statystyki oddziałów dla zdarzeń z from_tick < tick <= upto_tick (None = bez ograniczenia)."""
        end = len(self.events) if upto_tick is None else bisect.bisect_right(self.ticks, upto_tick)
        start = 0 if from_tick is None else bisect.bisect_right(self.ticks, from_tick)
        S = collections.defaultdict(collections.Counter)
        weap = collections.defaultdict(collections.Counter)      # oddział -> broń -> zadane
        victims = collections.defaultdict(collections.Counter)   # oddział -> oddział-ofiara -> zadane
        attackers = collections.defaultdict(collections.Counter) # oddział -> oddział-atakujący -> otrzymane
        timeline = collections.defaultdict(collections.Counter)  # oddział -> przedział 30 s -> zadane
        bucket = 30 * self.tps
        # Obrażenia w czasie (faza _dot) gra nakłada jako modyfikator zdrowia – spadki HP idą poza ApplyDamage, bez
        # sprawcy (rekord 'hp'). HEURYSTYKA (powtórka DE 2026-10-17): małe spadki HP ofiary do DOT_WINDOW po trafieniu
        # zdolnością z fazą _dot przypisujemy tej zdolności i jej sprawcy.
        dot_window, dot_max = 15 * self.tps, 25.0
        last_dot_hit = {}                                         # ofiara -> (tick, oddział sprawcy, zdolność)
        for tick, t, r in self.events[start:end]:
            if t == 'dmg':
                ak, vk = r.get('_ak') or self._key(r['a'], r['as']), self._key(r['v'], r['vs'])
                hp = r['hp']
                if r['ff']:
                    S[ak]['ff'] += hp
                else:
                    S[ak]['dealt'] += hp
                    S[ak]['nominal'] += r['nom']
                    S[ak]['kills'] += r['k']
                    S[ak]['hits'] += 1
                    # bez WeaponInfo: rozróżniamy po nazwie zdolności albo ścieżce kodu (src)
                    wkey = r['w'] if r['w'] >= 0 else self._source_key(r)
                    if r.get('_ak') and wkey[0] == 'special':  # w wierszu mocy gracza nie ma broni wręcz
                        wkey = ('unnamed', '')
                    weap[ak][wkey] += hp
                    if isinstance(wkey, tuple) and wkey[0] == 'ab' and CATALOG.has_dot(wkey[1]):
                        last_dot_hit[r['v']] = (tick, ak, wkey[1])
                    victims[ak][vk] += hp
                    attackers[vk][ak] += hp
                    timeline[ak][tick // bucket] += hp
                S[vk]['taken'] += hp
                S[vk]['lost'] += r['k']
            elif t == 'die':
                S[self._key(r['v'], r['vs'])]['lost'] += 1
                dot = last_dot_hit.get(r['v'])
                if dot and tick - dot[0] <= dot_window:
                    S[dot[1]]['kills'] += 1                       # zgon w trakcie obrażeń w czasie
            elif t == 'hp':
                vk = self._key(r['v'], r['vs'])
                dot = last_dot_hit.get(r['v'])
                if dot and tick - dot[0] <= dot_window and r['hp'] <= dot_max:
                    ak = dot[1]
                    S[ak]['dealt'] += r['hp']
                    weap[ak][('dot', dot[2])] += r['hp']
                    victims[ak][vk] += r['hp']
                    attackers[vk][ak] += r['hp']
                    timeline[ak][tick // bucket] += r['hp']
                    S[vk]['taken'] += r['hp']
                else:
                    # reszta: stawianie budynków (start z 20% HP), samoistna utrata zdrowia (jednostki tymczasowe,
                    # wygasanie) – nie są to obrażenia zadane przez kogokolwiek
                    S[vk]['hp_other'] += r['hp']
        return Stats(self, S, weap, victims, attackers, timeline, upto_tick)


class Stats:
    def __init__(self, rec, S, weap, victims, attackers, timeline, upto_tick=None):
        self.rec, self.S, self.weap, self.victims, self.attackers, self.timeline = rec, S, weap, victims, attackers, timeline
        self.upto = upto_tick

    def units(self):
        """Oddziały istniejące do bieżącego czasu (także te, które jeszcze nic nie zrobiły)."""
        known = {k for k, u in self.rec.units.items() if self.upto is None or u['first'] <= self.upto}
        units = known | set(self.S)
        # encje pomocnicze mocy gracza bez własnych statystyk nie są oddziałami
        return {k for k in units if k not in self.rec.power_helpers or any(self.S[k].values())}

    def unit_icon(self, k, size):
        """Plik PNG ikony wiersza: oddział/encja -> ikona z katalogu; moce gracza -> ikona ich najmocniejszej zdolności."""
        if k[0] == 'powers':
            for w, _ in self.weap[k].most_common():
                if isinstance(w, tuple) and w[0] == 'ab':
                    icon = CATALOG.ability_icon(w[1])
                    if icon:
                        return CATALOG.icon_file(icon, size)
            return None
        return CATALOG.icon_file(CATALOG.squad_icon(self.rec.units.get(k, {}).get('bp')), size)

    def total_dealt(self, pid=None):
        return sum(c['dealt'] for k, c in self.S.items() if pid is None or self.rec.units.get(k, {}).get('pid') == pid)

    def ranking(self, pid=None):
        """Oddziały posortowane malejąco wg zadanych obrażeń (opcjonalnie tylko gracza pid)."""
        ks = [k for k in self.units() if pid is None or self.rec.units.get(k, {}).get('pid') == pid]
        return sorted(ks, key=lambda k: (-self.S[k]['dealt'], -self.S[k]['kills']))

    def rank_of(self, k, pid=None):
        r = self.ranking(pid)
        return (r.index(k) + 1, len(r)) if k in r else (None, len(r))

    def weapon_name(self, wid):
        if isinstance(wid, tuple):  # ('ab', nazwa zdolności albo ścieżka kodu)
            kind, name = wid[0], wid[1]
            folder = wid[2] if len(wid) > 2 else 'abilities'
            if kind == 'special':
                if name is not None and name >= 0 and name in self.rec.weapons:
                    wn = self.rec.weapons[name][0]
                    return t('src_special_w', w=CATALOG.weapon(wn) or wn)
                return t('src_special')
            if kind == 'unnamed':
                return t('src_unnamed')
            if kind == 'dot':
                return t('src_dot', a=CATALOG.ability(name) or name)
            if kind == 'explosion':
                return t('src_explosion')
            if kind == 'structure':
                return t('src_structure')
            if folder.startswith('weapon'):
                return t('src_weapon_special', w=CATALOG.weapon(name) or name)
            if folder.startswith('abilit') or not folder:
                return t('src_ability', a=CATALOG.ability(name) or name)
            return f'{folder}: {name}'
        if wid == -1:
            return t('src_no_weapon')
        name, melee = self.rec.weapons.get(wid, (t('weapon_n', n=wid), False))
        return (CATALOG.weapon(name) or name) + (t('melee_suffix') if melee else '')
