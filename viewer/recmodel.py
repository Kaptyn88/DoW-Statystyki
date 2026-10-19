"""Model danych nagrań dowrec (.jsonl): wczytywanie przyrostowe i statystyki oddziałów do zadanego czasu.

Format rekordów opisuje nagłówek probe/src/recorder.cpp. Oddział = squad id (>0); encje bez oddziału
(budynki, wieżyczki) traktowane są jako osobne "oddziały" z kluczem ('ent', id).
"""
import bisect
import collections
import json
import os
import time

TPS_DEFAULT = 8
from i18n import lang, t
from paths import CATALOG_PATH

CATALOG_VERSION = 5  # 2: nazwy pl/en/ru; 3: ikony; 4: ceny modeli; 5: badania; starszy katalog podgląd buduje od nowa
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
        self._exists = {}
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
        exists = self._exists.get(path)
        if exists is None:  # sprawdzenie dysku raz na plik (wołane dla każdego wiersza co odświeżenie)
            exists = self._exists[path] = os.path.exists(path)
        return path if exists else None

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

    def unit_cost(self, bp):
        """Cena modelu/budynku (rekwizycja, energia) z danych gry; bez ulepszeń broni oddziału. Nieznany -> (0, 0)."""
        v = self.c.get('units', {}).get((bp or '').lower())
        c = v.get('cost') if v else None
        return (c[0], c[1]) if c else (0.0, 0.0)

    def research(self, name):
        """Nazwa badania (ulepszenia) w języku interfejsu."""
        return self._name('research', name)

    def research_icon(self, name):
        v = self.c.get('research', {}).get((name or '').lower())
        return v.get('icon') if v and v.get('icon') in self.c.get('icons', {}) else None

    def research_cost(self, name):
        v = self.c.get('research', {}).get((name or '').lower())
        c = v.get('cost') if v else None
        return (c[0], c[1]) if c else (0.0, 0.0)

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


def is_model(bp):
    """Czy encja to prawdziwy model/budynek. Ciała z Jamy Tortur Mrocznych Eldarów (dark_eldar_torture_pit_corpse,
    oddział dark_eldar_squad_slave_murdered) gra też uśmierca – nie liczymy ich jako zabitych ani straconych modeli."""
    return not (bp or '').endswith('_corpse')


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
        self._last_growth = time.monotonic()  # kiedy plik ostatnio urósł (statystyki na żywo)
        self._live = _Acc(self)                # statystyki całego meczu liczone przyrostowo
        self._labels, self._label_state = {}, None
        self.research = {}         # pid -> lista (tick, nazwa badania) w kolejności ukończenia (rekord 'res')
        self.eco = {}              # pid -> lista (tick, rekwizycja, energia, dochód R/tick, dochód E/tick, zebrane R, zebrane E)
        self.pair_dmg = collections.Counter()  # (gracz atakujący, gracz ofiara) -> obrażenia (do ustalenia drużyn)
        self._teams, self._teams_n = None, -1
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
        self._last_growth = time.monotonic()
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
        elif t == 'eco':
            self._add_eco(r)
        elif t == 'res':
            self.research.setdefault(r['pid'], []).append((r['tick'], r['name']))
            self.max_tick = max(self.max_tick, r['tick'])
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
            if t == 'dmg' and not r['ff']:
                pa, pv = self.ent_pid.get(r['a']), self.ent_pid.get(r['v'])
                if pa is not None and pv is not None and pa != pv:
                    self.pair_dmg[(pa, pv)] += r['hp']
            if t != 'clock':
                self.events.append((tick, t, r))
                self.ticks.append(tick)

    def _add_eco(self, r):
        """Rekord ekonomii (co ~1 s): zebrane łącznie = suma dochodu w czasie (gra nie trzyma takiego licznika;
        dochód na tick między próbkami przyjmujemy jak w poprzedniej próbce)."""
        s = self.eco.setdefault(r['pid'], [])
        tick = r['tick']
        if s and tick < s[-1][0]:
            return  # cofnięcie czasu w tej samej sesji – ignorujemy
        cr, cp = (s[-1][5] + s[-1][3] * (tick - s[-1][0]), s[-1][6] + s[-1][4] * (tick - s[-1][0])) if s else (0.0, 0.0)
        s.append((tick, r['req'], r['pow'], r['ir'], r['ip'], cr, cp))
        self.max_tick = max(self.max_tick, tick)

    def eco_at(self, pid, tick=None):
        """Ostatnia próbka ekonomii gracza do ticku (None = najnowsza) albo None."""
        s = self.eco.get(pid)
        if not s:
            return None
        if tick is None:
            return s[-1]
        i = bisect.bisect_right(s, (tick, float('inf'))) - 1
        return s[i] if i >= 0 else None

    def income_advantage(self, teams, which, points=120):
        """Przewaga dochodu drużyny 0 nad 1 na minutę w czasie: [(tick, wartość)]; which = 3 (rekwizycja) / 4 (energia)."""
        ticks = sorted({e[0] for s in self.eco.values() for e in s})
        if not ticks:
            return []
        step = max(1, len(ticks) // points)
        out = []
        per_min = 60 * self.tps
        for tick in ticks[::step] + ([ticks[-1]] if (len(ticks) - 1) % step else []):
            side = [sum((self.eco_at(p, tick) or (0,) * 7)[which] for p in team) for team in teams]
            out.append((tick, round((side[0] - side[1]) * per_min, 1)))
        return out

    def teams(self):
        """Dwie drużyny (listy pid). Rejestrator nie zna drużyn, więc wybieramy podział graczy, przy którym między
        stronami poleciało najwięcej obrażeń (przypadkowe trafienia sojuszników są małe). Remis / brak walk: kolejność
        graczy – pierwsza połowa vs druga (tak było w powtórce 3v3 #47672736: 1000–1002 vs 1003–1005)."""
        if self._teams_n == len(self.events) and self._teams:
            return self._teams
        pids = sorted(self.players)
        half = set(pids[:len(pids) // 2])
        best, best_score = None, None
        for mask in range(1 << max(0, len(pids) - 1)):  # pierwszy gracz zawsze po lewej
            left = {pids[0]} | {p for i, p in enumerate(pids[1:]) if mask >> i & 1} if pids else set()
            if len(left) == len(pids) and len(pids) > 1:
                continue
            cross = sum(v for (a, b), v in self.pair_dmg.items() if (a in left) != (b in left))
            agree = sum((p in left) == (p in half) for p in pids)
            score = (round(cross), agree)
            if best_score is None or score > best_score:
                best, best_score = left, score
        best = best or set()
        self._teams = [[p for p in pids if p in best], [p for p in pids if p not in best]]
        self._teams_n = len(self.events)
        return self._teams

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
        """Nazwa oddziału z numerem kolejnym wśród oddziałów tego samego typu u gracza (np. 'Ork shoota boy #2').
        Zapamiętywana – numeracja zmienia się tylko, gdy przybywa oddziałów (albo po przeładowaniu katalogu)."""
        state = (len(self.units), id(CATALOG.c))
        if self._label_state != state:
            self._label_state, self._labels = state, {}
        label = self._labels.get(k)
        if label is None:
            label = self._labels[k] = self._unit_label(k)
        return label

    def _unit_label(self, k):
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
        """Statystyki oddziałów dla zdarzeń z from_tick < tick <= upto_tick (None = bez ograniczenia).

        Cały mecz do bieżącej chwili (podgląd "Na żywo", nakładka) liczony jest PRZYROSTOWO – doliczane są tylko nowe
        zdarzenia, więc koszt nie rośnie z długością meczu. Inne zakresy (suwak, ostatnie 60 s) liczone są od zera."""
        if from_tick is None and (upto_tick is None or upto_tick >= self.max_tick):
            self._advance_live()
            acc = self._live
            return Stats(self, acc.S, acc.weap, acc.victims, acc.attackers, acc.timeline, upto_tick)
        end = len(self.events) if upto_tick is None else bisect.bisect_right(self.ticks, upto_tick)
        start = 0 if from_tick is None else bisect.bisect_right(self.ticks, from_tick)
        acc = _Acc(self)
        acc.feed(self.events[start:end])
        return Stats(self, acc.S, acc.weap, acc.victims, acc.attackers, acc.timeline, upto_tick)

    def _advance_live(self):
        """Dolicza do statystyk "na żywo" zdarzenia z ticków starszych niż najnowszy. Zdarzenia z najnowszego ticku
        czekają, bo rejestrator zapisuje np. trafienia wybuchu generatora PRZED rekordem jego zniszczenia (ten sam tick)
        – liczone za wcześnie dostałyby zły podpis. Gdy plik nie rośnie od 1,5 s (pauza/koniec), liczy wszystko."""
        stale = time.monotonic() - self._last_growth > 1.5
        limit = len(self.events) if stale else bisect.bisect_left(self.ticks, self.max_tick)
        if limit > self._live.n:
            self._live.feed(self.events[self._live.n:limit])


class _Acc:
    """Akumulator statystyk: zasilany zdarzeniami w kolejności pliku (całość albo przyrostowo)."""

    DOT_WINDOW_S, DOT_MAX = 15, 25.0

    def __init__(self, rec):
        self.rec = rec
        self.n = 0                                                    # ile zdarzeń przetworzono (tryb przyrostowy)
        self.S = collections.defaultdict(collections.Counter)
        self.weap = collections.defaultdict(collections.Counter)      # oddział -> broń -> zadane
        self.victims = collections.defaultdict(collections.Counter)   # oddział -> oddział-ofiara -> zadane
        self.attackers = collections.defaultdict(collections.Counter) # oddział -> oddział-atakujący -> otrzymane
        self.timeline = collections.defaultdict(collections.Counter)  # oddział -> przedział 30 s -> zadane
        # Obrażenia w czasie (faza _dot) gra nakłada jako modyfikator zdrowia – spadki HP idą poza ApplyDamage, bez
        # sprawcy (rekord 'hp'). HEURYSTYKA (powtórka DE 2026-10-17): małe spadki HP ofiary do DOT_WINDOW po trafieniu
        # zdolnością z fazą _dot przypisujemy tej zdolności i jej sprawcy.
        self.last_dot_hit = {}                                        # ofiara -> (tick, oddział sprawcy, zdolność)
        self.charged = set()                                          # encje, których cenę już doliczono do strat

    def _charge(self, eid, vk, ak=None):
        """Zgon modelu: jego cena (rekwizycja/energia) do strat właściciela i do zniszczonej wartości zabójcy.
        Raz na encję – Nekroni wstają po śmierci i mogą zginąć ponownie."""
        if eid in self.charged:
            return
        self.charged.add(eid)
        req, pw = CATALOG.unit_cost(self.rec.ent_bp.get(eid))
        S = self.S
        S[vk]['lost_req'] += req
        S[vk]['lost_pow'] += pw
        if ak is not None:
            S[ak]['killed_req'] += req
            S[ak]['killed_pow'] += pw

    def feed(self, events):
        rec = self.rec
        S, weap, victims, attackers, timeline = self.S, self.weap, self.victims, self.attackers, self.timeline
        last_dot_hit = self.last_dot_hit
        bucket = 30 * rec.tps
        dot_window = self.DOT_WINDOW_S * rec.tps
        for tick, t, r in events:
            if t == 'dmg':
                ak, vk = r.get('_ak') or rec._key(r['a'], r['as']), rec._key(r['v'], r['vs'])
                hp = r['hp']
                if r['ff']:
                    S[ak]['ff'] += hp
                else:
                    S[ak]['dealt'] += hp
                    S[ak]['nominal'] += r['nom']
                    k_models = r['k'] if is_model(rec.ent_bp.get(r['v'])) else 0
                    S[ak]['kills'] += k_models
                    S[ak]['hits'] += 1
                    # bez WeaponInfo: rozróżniamy po nazwie zdolności albo ścieżce kodu (src)
                    wkey = r['w'] if r['w'] >= 0 else rec._source_key(r)
                    if r.get('_ak') and wkey[0] == 'special':  # w wierszu mocy gracza nie ma broni wręcz
                        wkey = ('unnamed', '')
                    weap[ak][wkey] += hp
                    if isinstance(wkey, tuple) and wkey[0] == 'ab' and CATALOG.has_dot(wkey[1]):
                        last_dot_hit[r['v']] = (tick, ak, wkey[1])
                    victims[ak][vk] += hp
                    attackers[vk][ak] += hp
                    timeline[ak][tick // bucket] += hp
                S[vk]['taken'] += hp
                S[vk]['lost'] += r['k'] if is_model(rec.ent_bp.get(r['v'])) else 0
                if r['k']:
                    self._charge(r['v'], vk, None if r['ff'] else ak)
            elif t == 'die':
                vk = rec._key(r['v'], r['vs'])
                model = is_model(rec.ent_bp.get(r['v']))
                S[vk]['lost'] += model
                dot = last_dot_hit.get(r['v'])
                if dot and tick - dot[0] <= dot_window:
                    S[dot[1]]['kills'] += model                   # zgon w trakcie obrażeń w czasie
                self._charge(r['v'], vk, dot[1] if dot and tick - dot[0] <= dot_window else None)
            elif t == 'hp':
                vk = rec._key(r['v'], r['vs'])
                dot = last_dot_hit.get(r['v'])
                if dot and tick - dot[0] <= dot_window and r['hp'] <= self.DOT_MAX:
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
        self.n += len(events)


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

    def player_totals(self, pid):
        """Sumy gracza: zadane, zabite modele, straty i zniszczona wartość (rekwizycja/energia)."""
        out = collections.Counter()
        for k, c in self.S.items():
            if self.rec.units.get(k, {}).get('pid') == pid:
                for f in ('dealt', 'kills', 'lost', 'lost_req', 'lost_pow', 'killed_req', 'killed_pow'):
                    out[f] += c[f]
        return out

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
