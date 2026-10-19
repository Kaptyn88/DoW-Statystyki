"""Półprzezroczyste nakładki na grę + okno ustawień:
1. nakładka oddziału – oddział zaznaczony w grze (obrażenia, zabite/stracone modele, wartość zniszczona/stracona),
2. nakładka podsumowania – zakładki: Armia (N oddziałów z największymi obrażeniami / zabójstwami), Straty (zasoby).
Skróty klawiszowe (hotkeys.py): pokaż/ukryj każdą z nakładek, następna zakładka podsumowania.

Nakładki zawsze pokazują najnowszy stan nagrania (koniec pliku), niezależnie od suwaka w głównym oknie.
Gdy jest zablokowana, kliknięcia przechodzą przez nią do gry i nie zabiera ona fokusu (gra bez fokusu potrafi stanąć).
Działa nad grą w trybie okna bez ramki (W40k.ini: screenwindowed = 2); nad pełnym ekranem wyłącznym nie będzie widoczna.
"""
import collections
import ctypes
import json
import os
import tkinter as tk
from dataclasses import asdict, dataclass, fields
from tkinter import ttk

import iconcache
import paths
from hotkeys import KEYS, Hotkeys
from i18n import t
from recmodel import CATALOG, Recording, is_model

SETTINGS_PATH = paths.SETTINGS_PATH
# jaśniejsze odcienie kolorów graczy – czytelne na ciemnym tle nakładki
OVERLAY_COLORS = ['#7fb0ff', '#ff8a6b', '#6fd68f', '#f2c14e', '#c38df0', '#4fd1c5', '#ff6b81', '#c0c6cc']
# tryb graczy zapisywany kodem ('all' / 'each') albo nazwą gracza; dawne polskie etykiety mapujemy przy wczytaniu
MODE_ALL, MODE_EACH = 'all', 'each'
LEGACY_MODES = {'Wszyscy razem': MODE_ALL, 'Każdy gracz osobno': MODE_EACH}
WINDOW_VALUES = (0, 60, 180)        # sekundy; 0 = cały mecz
SORT_VALUES = ('dealt', 'kills')


def window_label(sec):
    return t(f'win_{sec}')


@dataclass
class OverlaySettings:
    enabled: bool = True          # nakładka oddziału; domyślnie włączona (v1.2); wyłączenie zapisuje się w settings.json
    sum_enabled: bool = True      # nakładka podsumowania (v1.4)
    sum_tab: str = 'army'
    sum_x: int = 40
    sum_y: int = 420
    key_unit: str = 'F6'          # skróty: pokaż/ukryj nakładkę oddziału, podsumowanie, następna zakładka ('' = brak)
    key_summary: str = 'F7'
    key_tab: str = 'F8'
    count: int = 3
    sort_by: str = 'dealt'
    mode: str = MODE_ALL          # MODE_ALL, MODE_EACH albo nazwa gracza
    window_s: int = 0             # 0 = cały mecz
    show_dealt: bool = True
    show_kills: bool = True
    show_lost: bool = False
    show_share: bool = False
    show_header: bool = True
    show_selected: bool = True    # (do v1.3 sekcja zaznaczonego oddziału; teraz osobna nakładka – pole dla zgodności)
    opacity: float = 0.75
    font_size: int = 11
    locked: bool = False
    sum_opacity: float = 1.0      # podsumowanie: osobna przezroczystość (domyślnie pełne, nieprzezroczyste okno)
    sum_locked: bool = False      # i osobna blokada
    x: int = 40
    y: int = 120

    @classmethod
    def load(cls):
        try:
            with open(SETTINGS_PATH, encoding='utf-8') as f:
                data = json.load(f).get('overlay', {})
            known = {f.name for f in fields(cls)}
            s = cls(**{k: v for k, v in data.items() if k in known})
            s.mode = LEGACY_MODES.get(s.mode, s.mode)
            return s
        except (OSError, ValueError, TypeError):
            return cls()

    def save(self):
        """Zapisuje sekcję 'overlay', zachowując resztę settings.json (np. język)."""
        try:
            with open(SETTINGS_PATH, encoding='utf-8') as f:
                data = json.load(f)
        except (OSError, ValueError):
            data = {}
        data['overlay'] = asdict(self)
        try:
            with open(SETTINGS_PATH, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except OSError:
            pass


def fmt_time(ticks, tps):
    s = int(ticks / tps)
    return f'{s // 60}:{s % 60:02d}'


# ---------------------------------------------------------------- styl okna Windows (klikanie przez nakładkę)
GWL_EXSTYLE = -20
WS_EX_LAYERED, WS_EX_TRANSPARENT, WS_EX_TOOLWINDOW, WS_EX_NOACTIVATE = 0x80000, 0x20, 0x80, 0x08000000


def set_click_through(win, enabled):
    """Zwraca False, gdy okno najwyższego poziomu jeszcze nie istnieje (trzeba spróbować później)."""
    if os.name != 'nt':
        return True
    user32 = ctypes.windll.user32
    # Styl musi trafić do okna najwyższego poziomu (GA_ROOT). Nadanie WS_EX_LAYERED wewnętrznemu oknu Tk
    # bez SetLayeredWindowAttributes sprawia, że treść nakładki w ogóle się nie rysuje (pusty prostokąt).
    # Zaraz po utworzeniu nakładki okno główne jeszcze nie istnieje i GetAncestor zwraca samo okno z treścią.
    inner = win.winfo_id()
    hwnd = user32.GetAncestor(inner, 2)
    if not hwnd or hwnd == inner:
        return False
    style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE) | WS_EX_LAYERED | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE
    style = style | WS_EX_TRANSPARENT if enabled else style & ~WS_EX_TRANSPARENT
    user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)
    return True


class OverlayWindow(tk.Toplevel):
    """Wspólna część nakładek: okno bez ramki na wierzchu, przeciąganie, klikanie przez nakładkę, przezroczystość
    i rysowanie listy komórek (etykiety tworzone raz, potem zmieniane tylko te, które się zmieniły)."""
    BG = '#11151a'
    POS = ('x', 'y')  # pola OverlaySettings z położeniem okna, przezroczystością i blokadą
    OPACITY, LOCK = 'opacity', 'locked'

    @property
    def locked(self):
        return getattr(self.s, self.LOCK)

    def __init__(self, master, settings: OverlaySettings):
        super().__init__(master)
        self.s = settings
        self.overrideredirect(True)
        self.attributes('-topmost', True)
        self.configure(background=self.BG)
        self.body = tk.Frame(self, background=self.BG, padx=10, pady=6)
        self.body.pack(fill='both', expand=True)
        self._drag = None
        self._cells = {}          # (rodzaj, wiersz, kolumna) -> (widget, ostatnia specyfikacja)
        self._last_cells = None   # ostatni układ – bez zmian nic nie przerysowujemy
        self.bind_all_drag(self)
        self.geometry(f'+{getattr(settings, self.POS[0])}+{getattr(settings, self.POS[1])}')
        self.after(50, self.apply_window_style)

    # -- przeciąganie (tylko gdy odblokowana)
    def bind_all_drag(self, w):
        w.bind('<ButtonPress-1>', self._start_drag)
        w.bind('<B1-Motion>', self._on_drag)
        w.bind('<ButtonRelease-1>', self._end_drag)

    def _start_drag(self, e):
        if not self.locked:
            self._drag = (e.x_root - self.winfo_x(), e.y_root - self.winfo_y())

    def _on_drag(self, e):
        if self._drag:
            self.geometry(f'+{e.x_root - self._drag[0]}+{e.y_root - self._drag[1]}')

    def _end_drag(self, _):
        if self._drag:
            self._drag = None
            setattr(self.s, self.POS[0], self.winfo_x())
            setattr(self.s, self.POS[1], self.winfo_y())
            self.s.save()

    def apply_window_style(self):
        self.update_idletasks()
        if not set_click_through(self, self.locked):
            self.after(100, self.apply_window_style)  # okno jeszcze nie zmapowane – ponów
            return
        # przezroczystość po zmianie stylu – Tk ustawia wtedy atrybuty warstwy na właściwym oknie
        self.attributes('-alpha', 1.0)
        self.attributes('-alpha', max(0.2, min(1.0, getattr(self.s, self.OPACITY))))
        self.configure(cursor='' if self.locked else 'fleur')

    # -- treść
    def render(self, rec: Recording):
        """Buduje listę komórek (tekst, kolor, ikona...) i nanosi tylko zmiany; gdy nic się nie zmieniło (np. pauza),
        okno nie jest w ogóle przerysowywane."""
        cells = self._layout(rec, Cells(self.s))
        if cells == self._last_cells:
            return
        self._last_cells = cells
        used = set()
        for c in cells:
            key = (c['kind'], c['row'], c['col'])
            used.add(key)
            w, prev = self._cells.get(key, (None, None))
            if w is None:
                w = (tk.Frame(self.body, height=1, bg='#3a434c') if c['kind'] == 'sep'
                     else tk.Canvas(self.body, bg=self.BG, highlightthickness=0) if c['kind'] == 'chart'
                     else tk.Label(self.body, bg=self.BG))
                self.bind_all_drag(w)
            if prev == c:
                continue  # komórka bez zmian
            if c['kind'] == 'label':
                img = c['image'] or ''
                w.configure(text=c['text'], fg=c['fg'], font=c['font'], anchor=c['anchor'], image=img,
                            compound=c['compound'] if img else 'none', padx=0 if img else 1)
                w.image = c['image']
                w.grid(row=c['row'], column=c['col'], columnspan=c['span'], padx=c['padx'], pady=c['pady'],
                       sticky={'w': 'we', 'e': 'e'}.get(c['anchor'], ''))
            elif c['kind'] == 'chart':
                draw_chart(w, c)
                w.grid(row=c['row'], column=c['col'], columnspan=c['span'], sticky='w', pady=(2, 6))
            else:
                w.grid(row=c['row'], column=c['col'], columnspan=c['span'], sticky='we', pady=(6, 4))
            self._cells[key] = (w, c)
        for key in [k for k in self._cells if k not in used]:  # komórki z poprzedniego układu, których już nie ma
            self._cells.pop(key)[0].destroy()

    def _layout(self, rec, cells):
        raise NotImplementedError

    @staticmethod
    def colors(rec):
        return {p: OVERLAY_COLORS[i % len(OVERLAY_COLORS)] for i, p in enumerate(sorted(rec.players))}


class Cells(list):
    """Lista komórek nakładki z czcionkami wg ustawień."""

    def __init__(self, s):
        super().__init__()
        self.font = ('Segoe UI', s.font_size)
        self.bold = ('Segoe UI', s.font_size, 'bold')
        self.small = ('Segoe UI', max(7, s.font_size - 2))
        self.icon_px = s.font_size * 2  # ikona mniej więcej na wysokość wiersza

    def label(self, text, row, col, fg='#e6e9ec', f=None, anchor='w', padx=(0, 10), image=None, columnspan=1, pady=0,
              compound='left'):
        self.append({'kind': 'label', 'row': row, 'col': col, 'text': text, 'fg': fg, 'font': f or self.font,
                     'anchor': anchor, 'padx': padx, 'pady': pady, 'image': image, 'span': columnspan,
                     'compound': compound})

    def sep(self, row, span):
        self.append({'kind': 'sep', 'row': row, 'col': 0, 'span': span})

    def chart(self, row, span, points, colors, width, height, end_label):
        self.append({'kind': 'chart', 'row': row, 'col': 0, 'span': span, 'points': tuple(points),
                     'colors': tuple(colors), 'w': width, 'h': height, 'end': end_label})


def _dim(color, bg='#11151a', k=0.35):
    """Kolor wypełnienia: color zmieszany z tłem (k = udział koloru)."""
    a = [int(color[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(bg[i:i + 2], 16) for i in (1, 3, 5)]
    return '#' + ''.join(f'{round(x * k + y * (1 - k)):02x}' for x, y in zip(a, b))


def draw_chart(cv, c):
    """Wykres przewagi jak "Income advantage" w SC2: nad zerem przewaga drużyny 1 (jej kolor), pod zerem drużyny 2."""
    cv.delete('all')
    w, h, pts = c['w'], c['h'], c['points']
    cv.configure(width=w, height=h)
    left, right, top, bottom = 44, w - 6, 6, h - 16
    font = ('Segoe UI', 8)
    if len(pts) < 2:
        cv.create_text(w // 2, h // 2, text='–', fill='#6b747c', font=font)
        return
    t0, t1 = pts[0][0], pts[-1][0]
    span = max(1, t1 - t0)
    ymax = max(abs(v) for _, v in pts)
    nice = next((n for n in (50, 100, 150, 250, 500, 750, 1000, 1500, 2500, 5000, 10000) if n >= ymax), ymax or 1)
    mid = (top + bottom) / 2

    def xy(tick, v):
        return left + (tick - t0) / span * (right - left), mid - v / nice * (bottom - top) / 2

    pos, neg = c['colors']
    cv.create_rectangle(left, top, right, mid, fill=_dim(pos, k=0.08), outline='')
    cv.create_rectangle(left, mid, right, bottom, fill=_dim(neg, k=0.08), outline='')
    for v, col in ((nice, pos), (0, '#9aa3ab'), (-nice, neg)):
        y = xy(t0, v)[1]
        cv.create_text(left - 4, y, text=f'{abs(v):.0f}', anchor='e', fill=col, font=font)
        cv.create_line(left, y, right, y, fill='#2a3138')
    # odcinki: przy zmianie znaku dzielimy w punkcie przecięcia zera
    for (ta, va), (tb, vb) in zip(pts, pts[1:]):
        segs = [((ta, va), (tb, vb))]
        if va * vb < 0:
            tz = ta + (tb - ta) * va / (va - vb)
            segs = [((ta, va), (tz, 0.0)), ((tz, 0.0), (tb, vb))]
        for (a, av), (b, bv) in segs:
            col = pos if (av + bv) > 0 else neg
            (xa, ya), (xb, yb) = xy(a, av), xy(b, bv)
            cv.create_polygon(xa, mid, xa, ya, xb, yb, xb, mid, fill=_dim(col), outline='')
            cv.create_line(xa, ya, xb, yb, fill=col, width=2)
    cv.create_text(left, h - 2, text='0:00', anchor='sw', fill='#6b747c', font=font)
    cv.create_text(right, h - 2, text=c['end'], anchor='se', fill='#6b747c', font=font)


def fmt_res(req, pw):
    """Rekwizycja i energia, np. '450 R / 50 E' (skróty w języku interfejsu)."""
    return t('res_fmt', r=f'{req:.0f}', p=f'{pw:.0f}')


class UnitOverlay(OverlayWindow):
    """Nakładka 1: oddział zaznaczony w grze (rekord 'sel' rejestratora) – statystyki z całego meczu."""

    def _layout(self, rec, c):
        if rec is None or (not rec.events and not rec.selection):
            c.label(t('ov_wait'), 0, 0, fg='#9aa3ab', f=c.small)
            if not self.locked:
                c.label(t('ov_drag'), 1, 0, fg='#6b747c', f=c.small)
            return c
        sel = [k for k in rec.selection if k in rec.units]
        if not sel:
            c.label(t('ov_sel_none'), 0, 0, fg='#6b747c', f=c.small)
            if not self.locked:
                c.label(t('ov_drag'), 1, 0, fg='#6b747c', f=c.small)
            return c
        st = rec.stats(rec.max_tick)
        k = sel[0]
        s = st.S[k]
        more = f'  (+{len(sel) - 1})' if len(sel) > 1 else ''
        upid = rec.units.get(k, {}).get('pid')
        c.label(f' {rec.unit_label(k)}{more}', 0, 0, fg=self.colors(rec).get(upid, '#e6e9ec'), f=c.bold,
                image=iconcache.photo(st.unit_icon(k, c.icon_px)))
        c.label(t('ov_sel_line', d=f"{s['dealt']:.0f}", k=s['kills'], l=s['lost']), 1, 0)
        if s['killed_req'] or s['killed_pow'] or s['lost_req'] or s['lost_pow']:
            c.label(t('ov_value_line', k=fmt_res(s['killed_req'], s['killed_pow']),
                      l=fmt_res(s['lost_req'], s['lost_pow'])), 2, 0, fg='#9aa3ab', f=c.small)
        return c


SUMMARY_TABS = ('army', 'losses', 'eco', 'research')
LOST_PER_ROW = 12  # ikon w wierszu zakładki Straty


class SummaryOverlay(OverlayWindow):
    """Nakładka 2: podsumowanie meczu w zakładkach (przełączane skrótem klawiszowym)."""
    POS = ('sum_x', 'sum_y')
    OPACITY, LOCK = 'sum_opacity', 'sum_locked'

    def _layout(self, rec, c):
        s = self.s
        tab = s.sum_tab if s.sum_tab in SUMMARY_TABS else SUMMARY_TABS[0]
        if rec is None or not rec.events:
            c.label(t('ov_wait'), 0, 0, fg='#9aa3ab', f=c.small)
            if not self.locked:
                c.label(t('ov_drag'), 1, 0, fg='#6b747c', f=c.small)
            return c
        tick = rec.max_tick
        # pasek zakładek: bieżąca jasna, pozostałe przygaszone; czas meczu na końcu
        names = '   '.join(f'[{t("tab_" + x)}]' if x == tab else t('tab_' + x) for x in SUMMARY_TABS)
        c.label(f'{names}   ·  {fmt_time(tick, rec.tps)}', 0, 0, fg='#c0c6cc', f=c.small, columnspan=11)
        if tab == 'losses':
            self._losses(rec, c, tick)
        elif tab == 'eco':
            self._eco(rec, c, tick)
        elif tab == 'research':
            self._research(rec, c)
        else:
            self._army(rec, c, tick)
        return c

    def _army(self, rec, c, tick):
        """Dwie kolumny – drużyna po lewej, drużyna po prawej (Recording.teams); w każdej gracze i ich najlepsze
        oddziały z ikoną oraz wybranymi wartościami (domyślnie obrażenia i zabite modele)."""
        s = self.s
        from_tick = tick - s.window_s * rec.tps if s.window_s else None
        st = rec.stats(tick, from_tick)
        pcolor = self.colors(rec)
        cols = [(k, h) for k, h, on in (('dealt', t('ov_col_dealt'), s.show_dealt), ('share', '%', s.show_share),
                                         ('kills', t('ov_col_kills'), s.show_kills),
                                         ('lost', t('ov_col_lost'), s.show_lost)) if on]
        width = 1 + len(cols)          # kolumny siatki jednej drużyny
        top = 1
        if s.show_header:
            win = window_label(s.window_s) if s.window_s in WINDOW_VALUES else ''
            by = t('ov_by_kills') if s.sort_by == 'kills' else t('ov_by_dmg')
            c.label(f'{win}  ·  {by}', top, 0, fg='#9aa3ab', f=c.small, columnspan=2 * width + 1)
            top += 1
        total = st.total_dealt() or 1

        def top_units(pid):
            ks = [k for k in st.ranking(pid) if st.S[k]['dealt'] > 0 or st.S[k]['kills'] > 0]
            ks.sort(key=lambda k: (-st.S[k][s.sort_by], -st.S[k]['dealt']))
            return ks[:max(1, min(5, s.count))]

        for side, team in enumerate(rec.teams()):
            col0 = side * (width + 1)  # między drużynami pusta kolumna odstępu
            if side:
                c.label('', top, width, padx=(14, 14))
            row = top
            for pid in team:
                c.label(rec.players.get(pid, '?'), row, col0, fg=pcolor.get(pid, '#ccc'), f=c.bold,
                        pady=(6 if row > top else 0, 0))
                for i, (cid, head) in enumerate(cols):  # nagłówki kolumn w wierszu gracza
                    c.label(head, row, col0 + 1 + i, fg='#6b747c', f=c.small, anchor='e', padx=(6, 0),
                            pady=(6 if row > top else 0, 0))
                row += 1
                units = top_units(pid)
                if not units:
                    c.label('–', row, col0, fg='#6b747c')
                    row += 1
                for k in units:
                    v = st.S[k]
                    c.label(f' {rec.unit_label(k)}', row, col0, fg='#e6e9ec',
                            image=iconcache.photo(st.unit_icon(k, c.icon_px)))
                    vals = {'dealt': f"{v['dealt']:.0f}", 'share': f"{100 * v['dealt'] / total:.0f}%",
                            'kills': str(v['kills']), 'lost': str(v['lost'])}
                    for i, (cid, _) in enumerate(cols):
                        c.label(vals[cid], row, col0 + 1 + i, f=c.bold if cid == s.sort_by else c.font, anchor='e',
                                padx=(6, 0))
                    row += 1

    def _losses(self, rec, c, tick):
        """Jak "Units Lost" w SC2: dla każdej drużyny ikony straconych modeli/budynków z liczbą sztuk (cały mecz),
        pod spodem stracona rekwizycja i energia (ceny z danych gry, bez ulepszeń broni)."""
        st = rec.stats(tick)
        pcolor = self.colors(rec)
        tile = c.icon_px + 10  # ikony większe niż w liście oddziałów
        row = 1
        for side, team in enumerate(rec.teams()):
            if side:
                c.sep(row, LOST_PER_ROW)
                row += 1
            names = '  ·  '.join(rec.players.get(p, '?') for p in team)
            c.label(names, row, 0, fg=pcolor.get(team[0], '#e6e9ec') if team else '#e6e9ec', f=c.bold,
                    columnspan=LOST_PER_ROW)
            row += 1
            lost = collections.Counter(
                bp for eid, bp in ((e, rec.ent_bp.get(e)) for e in rec.death_tick)
                if rec.ent_pid.get(eid) in team and is_model(bp))
            if not lost:
                c.label('–', row, 0, fg='#6b747c')
                row += 1
            for i, (bp, n) in enumerate(sorted(lost.items(), key=lambda x: (-x[1], x[0]))):
                img = iconcache.photo(CATALOG.icon_file(CATALOG.squad_icon(bp), tile))
                text = str(n) if img else (CATALOG.squad(bp) or bp)[:8] + chr(10) + str(n)
                c.label(text, row + i // LOST_PER_ROW, i % LOST_PER_ROW, f=c.small, anchor='center', padx=(0, 4),
                        pady=(0, 2), image=img, compound='top')
            row += (len(lost) + LOST_PER_ROW - 1) // LOST_PER_ROW
            tot = collections.Counter()
            for p in team:
                tot.update(st.player_totals(p))
            c.label(fmt_res(tot['lost_req'], tot['lost_pow']), row, 0, fg='#9aa3ab', columnspan=LOST_PER_ROW,
                    pady=(2, 0))
            row += 1
        c.label(t('ov_losses_note'), row, 0, fg='#6b747c', f=c.small, columnspan=LOST_PER_ROW, pady=(4, 0))

    def _eco(self, rec, c, tick):
        """Ekonomia: stan konta, dochód na minutę i zebrane łącznie każdego gracza (drużynami) + wykresy przewagi
        dochodu drużyny 1 nad 2, osobno rekwizycja i energia. Dane: rekord 'eco' rejestratora (co ~1 s)."""
        if not rec.eco:
            c.label(t('eco_none'), 1, 0, fg='#6b747c', f=c.small, columnspan=6)
            return
        pcolor = self.colors(rec)
        per_min = 60 * rec.tps
        teams = rec.teams()
        row = 1
        for i, head in enumerate((t('eco_col_bank'), t('eco_col_income'), t('eco_col_total'))):
            c.label(head, row, 1 + i, fg='#6b747c', f=c.small, anchor='e', padx=(12, 0))
        row += 1
        for side, team in enumerate(teams):
            if side:
                c.sep(row, 4)
                row += 1
            for pid in team:
                e = rec.eco_at(pid)
                c.label(rec.players.get(pid, '?'), row, 0, fg=pcolor.get(pid, '#e6e9ec'), f=c.bold)
                if e:
                    _, req, pw, ir, ip, cr, cp = e
                    for i, (a, b) in enumerate(((req, pw), (ir * per_min, ip * per_min), (cr, cp))):
                        c.label(fmt_res(a, b), row, 1 + i, anchor='e', padx=(12, 0))
                row += 1
        colors = [pcolor.get(team[0], '#e6e9ec') if team else '#e6e9ec' for team in teams]
        width, height = self.s.font_size * 46, self.s.font_size * 11
        names = [' · '.join(rec.players.get(p, '?') for p in team) for team in teams]
        for which, key in ((3, 'eco_chart_req'), (4, 'eco_chart_pow')):
            c.label(t(key, a=names[0], b=names[1]), row, 0, fg='#c0c6cc', f=c.small, columnspan=4, pady=(8, 0))
            row += 1
            c.chart(row, 4, rec.income_advantage(teams, which), colors, width, height, fmt_time(tick, rec.tps))
            row += 1

    def _research(self, rec, c):
        """Ukończone ulepszenia (rekord 'res'): drużyna po lewej i po prawej, każdy gracz z listą czas + ikona + nazwa
        i sumą wydaną na ulepszenia (ceny z danych gry)."""
        if not rec.research and not rec.eco:
            c.label(t('res_none'), 1, 0, fg='#6b747c', f=c.small, columnspan=6)
            return
        pcolor = self.colors(rec)
        for side, team in enumerate(rec.teams()):
            col0 = side * 3  # kolumny: czas, nazwa, odstęp
            if side:
                c.label('', 1, 2, padx=(14, 14))
            row = 1
            for pid in team:
                done = rec.research.get(pid, [])
                req = sum(CATALOG.research_cost(n)[0] for _, n in done)
                pw = sum(CATALOG.research_cost(n)[1] for _, n in done)
                c.label(rec.players.get(pid, '?'), row, col0, fg=pcolor.get(pid, '#ccc'), f=c.bold, columnspan=2,
                        pady=(6 if row > 1 else 0, 0))
                row += 1
                if not done:
                    c.label('–', row, col0 + 1, fg='#6b747c')
                    row += 1
                for tick, name in done:
                    c.label(fmt_time(tick, rec.tps), row, col0, fg='#9aa3ab', f=c.small, anchor='e', padx=(0, 6))
                    c.label(f' {CATALOG.research(name) or name}', row, col0 + 1,
                            image=iconcache.photo(CATALOG.icon_file(CATALOG.research_icon(name), c.icon_px)))
                    row += 1
                if done:
                    c.label(t('res_spent', v=fmt_res(req, pw)), row, col0 + 1, fg='#6b747c', f=c.small)
                    row += 1


class Overlays:
    """Obie nakładki + skróty klawiszowe; podgląd woła render() i poll_hotkeys() w swojej pętli."""

    def __init__(self, master, settings: OverlaySettings):
        self.master, self.s = master, settings
        self.unit = self.summary = None
        self.hotkeys = Hotkeys()
        self.apply_hotkeys()

    def apply_hotkeys(self):
        self.hotkeys.set({'unit': self.s.key_unit, 'summary': self.s.key_summary, 'tab': self.s.key_tab})
        return self.hotkeys.failed

    def changed(self, rec):
        """Po zmianie ustawień: tworzy/zamyka okna, odświeża styl i treść."""
        for attr, cls, on in (('unit', UnitOverlay, self.s.enabled), ('summary', SummaryOverlay, self.s.sum_enabled)):
            w = getattr(self, attr)
            if on and not w:
                setattr(self, attr, cls(self.master, self.s))
            elif not on and w:
                w.destroy()
                setattr(self, attr, None)
        for w in (self.unit, self.summary):
            if w:
                w.apply_window_style()
                w._last_cells = None
                w.render(rec)

    def render(self, rec):
        for w in (self.unit, self.summary):
            if w:
                w.render(rec)

    def poll_hotkeys(self, rec):
        """Obsługuje wciśnięte skróty. Zwraca True, gdy zmieniły się ustawienia (okno ustawień może je odświeżyć)."""
        acts = self.hotkeys.poll()
        for a in acts:
            if a == 'unit':
                self.s.enabled = not self.s.enabled
            elif a == 'summary':
                self.s.sum_enabled = not self.s.sum_enabled
            elif a == 'tab':
                if not self.s.sum_enabled:
                    self.s.sum_enabled = True
                else:
                    i = SUMMARY_TABS.index(self.s.sum_tab) if self.s.sum_tab in SUMMARY_TABS else 0
                    self.s.sum_tab = SUMMARY_TABS[(i + 1) % len(SUMMARY_TABS)]
        if acts:
            self.s.save()
            self.changed(rec)
        return bool(acts)


class OverlaySettingsWindow(tk.Toplevel):
    """Okno ustawień nakładek; każda zmiana od razu odświeża nakładki i zapisuje settings.json.
    Listy pokazują etykiety w języku interfejsu, a w ustawieniach zapisywane są kody (sort_by, mode, window_s)."""

    def __init__(self, master, settings: OverlaySettings, players, on_change, apply_hotkeys, failed_keys=()):
        super().__init__(master)
        self.title(t('set_title'))
        self.resizable(False, False)
        self.s, self.on_change, self.apply_hotkeys = settings, on_change, apply_hotkeys
        self.sorts = {t('sort_dealt'): 'dealt', t('sort_kills'): 'kills'}
        self.windows = {window_label(sec).capitalize(): sec for sec in WINDOW_VALUES}
        self.modes = {t('mode_all'): MODE_ALL, t('mode_each'): MODE_EACH}
        f = ttk.Frame(self, padding=12)
        f.pack(fill='both', expand=True)
        self.v = {}
        r = 0

        def row(label_text, widget):
            nonlocal r
            ttk.Label(f, text=label_text).grid(row=r, column=0, sticky='w', pady=3, padx=(0, 10))
            widget.grid(row=r, column=1, sticky='we', pady=3)
            r += 1

        def section(text):
            nonlocal r
            ttk.Label(f, text=text, font=('Segoe UI', 9, 'bold')).grid(row=r, column=0, columnspan=2, sticky='w',
                                                                      pady=(10 if r else 0, 2))
            r += 1

        def check(key, text):
            nonlocal r
            self.v[key] = tk.BooleanVar(value=getattr(settings, key))
            ttk.Checkbutton(f, text=text, variable=self.v[key], command=self._apply).grid(
                row=r, column=0, columnspan=2, sticky='w')
            r += 1

        def label_of(mapping, value, default):
            return next((k for k, v in mapping.items() if v == value), default)

        def look(opacity_key, lock_key):
            nonlocal r
            self.v[opacity_key] = tk.DoubleVar(value=getattr(settings, opacity_key))
            row(t('set_opacity'), ttk.Scale(f, from_=0.3, to=1.0, variable=self.v[opacity_key],
                                            command=lambda _: self._apply()))
            check(lock_key, t('set_lock'))

        section(t('set_sec_unit'))
        check('enabled', t('set_show'))
        look('opacity', 'locked')
        section(t('set_sec_summary'))
        check('sum_enabled', t('set_show_summary'))
        look('sum_opacity', 'sum_locked')
        self.v['count'] = tk.IntVar(value=settings.count)
        row(t('set_count'), ttk.Spinbox(f, from_=2, to=5, width=5, textvariable=self.v['count'], command=self._apply,
                                        state='readonly'))
        self.v['sort_by'] = tk.StringVar(value=label_of(self.sorts, settings.sort_by, t('sort_dealt')))
        row(t('set_sort'), self._combo(f, self.v['sort_by'], list(self.sorts)))
        self.v['window_s'] = tk.StringVar(value=label_of(self.windows, settings.window_s, list(self.windows)[0]))
        row(t('set_range'), self._combo(f, self.v['window_s'], list(self.windows)))

        ttk.Label(f, text=t('set_columns')).grid(row=r, column=0, sticky='nw', pady=3)
        cf = ttk.Frame(f)
        cf.grid(row=r, column=1, sticky='w')
        r += 1
        for i, (key, text) in enumerate([('show_dealt', t('chk_dealt')), ('show_kills', t('chk_kills')),
                                         ('show_lost', t('chk_lost')), ('show_share', t('chk_share')),
                                         ('show_header', t('chk_header'))]):
            self.v[key] = tk.BooleanVar(value=getattr(settings, key))
            ttk.Checkbutton(cf, text=text, variable=self.v[key], command=self._apply).grid(row=i // 2, column=i % 2,
                                                                                           sticky='w', padx=(0, 10))
        section(t('set_sec_common'))
        self.v['font_size'] = tk.IntVar(value=settings.font_size)
        row(t('set_font'), ttk.Spinbox(f, from_=8, to=20, width=5, textvariable=self.v['font_size'],
                                       command=self._apply, state='readonly'))
        ttk.Label(f, text=t('set_drag_hint'), foreground='#666').grid(row=r, column=0, columnspan=2, sticky='w')
        r += 1

        section(t('set_sec_keys'))
        none = t('key_none')
        for key, text in (('key_unit', t('key_unit')), ('key_summary', t('key_summary')), ('key_tab', t('key_tab'))):
            self.v[key] = tk.StringVar(value=getattr(settings, key) or none)
            row(text, self._combo(f, self.v[key], [none] + KEYS, width=8, command=self._apply_keys))
        self.key_status = ttk.Label(f, text='', foreground='#a33')
        self.key_status.grid(row=r, column=0, columnspan=2, sticky='w')
        r += 1
        self._show_key_status(failed_keys)

    def _combo(self, parent, var, values, width=26, command=None):
        c = ttk.Combobox(parent, textvariable=var, values=values, state='readonly', width=width)
        c.bind('<<ComboboxSelected>>', lambda e: (command or self._apply)())
        return c

    def set_players(self, players):
        pass  # (do v1.3 lista graczy; teraz drużyny ustalane automatycznie)

    def refresh_from_settings(self):
        """Po zmianie ustawień skrótem klawiszowym – zaznaczenia w oknie zgodne z ustawieniami."""
        for key in ('enabled', 'sum_enabled'):
            self.v[key].set(getattr(self.s, key))

    def _show_key_status(self, failed):
        self.key_status.configure(text=t('key_busy', keys=', '.join(failed)) if failed else '')

    def _apply_keys(self):
        for key in ('key_unit', 'key_summary', 'key_tab'):
            val = self.v[key].get()
            setattr(self.s, key, val if val in KEYS else '')
        self.s.save()
        self._show_key_status(self.apply_hotkeys())

    def _apply(self):
        s, v = self.s, self.v
        s.enabled = v['enabled'].get()
        s.sum_enabled = v['sum_enabled'].get()
        s.count = int(v['count'].get())
        s.sort_by = self.sorts.get(v['sort_by'].get(), 'dealt')
        s.window_s = self.windows.get(v['window_s'].get(), 0)
        for key in ('show_dealt', 'show_kills', 'show_lost', 'show_share', 'show_header', 'locked', 'sum_locked'):
            setattr(s, key, v[key].get())
        s.opacity = round(float(v['opacity'].get()), 2)
        s.sum_opacity = round(float(v['sum_opacity'].get()), 2)
        s.font_size = int(v['font_size'].get())
        s.save()
        self.on_change()
