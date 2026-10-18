"""Półprzezroczysta nakładka na grę: N oddziałów z największymi obrażeniami / zabójstwami + okno ustawień.

Nakładka zawsze pokazuje najnowszy stan nagrania (koniec pliku), niezależnie od suwaka w głównym oknie.
Gdy jest zablokowana, kliknięcia przechodzą przez nią do gry i nie zabiera ona fokusu (gra bez fokusu potrafi stanąć).
Działa nad grą w trybie okna bez ramki (W40k.ini: screenwindowed = 2); nad pełnym ekranem wyłącznym nie będzie widoczna.
"""
import ctypes
import json
import os
import tkinter as tk
from dataclasses import asdict, dataclass, fields
from tkinter import ttk

import iconcache
import paths
from i18n import t
from recmodel import Recording

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
    enabled: bool = True          # domyślnie włączona (v1.2); wyłączenie zapisuje się w settings.json
    count: int = 3
    sort_by: str = 'dealt'
    mode: str = MODE_ALL          # MODE_ALL, MODE_EACH albo nazwa gracza
    window_s: int = 0             # 0 = cały mecz
    show_dealt: bool = True
    show_kills: bool = True
    show_lost: bool = False
    show_share: bool = False
    show_header: bool = True
    show_selected: bool = True    # sekcja z oddziałem zaznaczonym w grze
    opacity: float = 0.75
    font_size: int = 11
    locked: bool = False
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


class Overlay(tk.Toplevel):
    BG = '#11151a'

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
        self.geometry(f'+{settings.x}+{settings.y}')
        self.after(50, self.apply_window_style)

    # -- przeciąganie (tylko gdy odblokowana)
    def bind_all_drag(self, w):
        w.bind('<ButtonPress-1>', self._start_drag)
        w.bind('<B1-Motion>', self._on_drag)
        w.bind('<ButtonRelease-1>', self._end_drag)

    def _start_drag(self, e):
        if not self.s.locked:
            self._drag = (e.x_root - self.winfo_x(), e.y_root - self.winfo_y())

    def _on_drag(self, e):
        if self._drag:
            self.geometry(f'+{e.x_root - self._drag[0]}+{e.y_root - self._drag[1]}')

    def _end_drag(self, _):
        if self._drag:
            self._drag = None
            self.s.x, self.s.y = self.winfo_x(), self.winfo_y()
            self.s.save()

    def apply_window_style(self):
        self.update_idletasks()
        if not set_click_through(self, self.s.locked):
            self.after(100, self.apply_window_style)  # okno jeszcze nie zmapowane – ponów
            return
        # przezroczystość po zmianie stylu – Tk ustawia wtedy atrybuty warstwy na właściwym oknie
        self.attributes('-alpha', 1.0)
        self.attributes('-alpha', max(0.2, min(1.0, self.s.opacity)))
        self.configure(cursor='' if self.s.locked else 'fleur')

    # -- treść
    def render(self, rec: Recording):
        """Buduje listę komórek (tekst, kolor, ikona...) i nanosi tylko zmiany: etykiety są tworzone raz i potem
        aktualizowane; gdy nic się nie zmieniło (np. pauza), okno nie jest w ogóle przerysowywane."""
        cells = self._layout(rec)
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
                     else tk.Label(self.body, bg=self.BG))
                self.bind_all_drag(w)
            if prev == c:
                continue  # komórka bez zmian
            if c['kind'] == 'label':
                img = c['image'] or ''
                w.configure(text=c['text'], fg=c['fg'], font=c['font'], anchor=c['anchor'], image=img,
                            compound='left' if img else 'none', padx=0 if img else 1)
                w.image = c['image']
                w.grid(row=c['row'], column=c['col'], columnspan=c['span'], padx=c['padx'], pady=c['pady'],
                       sticky='we' if c['anchor'] == 'w' else 'e')
            else:
                w.grid(row=c['row'], column=c['col'], columnspan=c['span'], sticky='we', pady=(6, 4))
            self._cells[key] = (w, c)
        for key in [k for k in self._cells if k not in used]:  # komórki z poprzedniego układu, których już nie ma
            self._cells.pop(key)[0].destroy()

    def _layout(self, rec: Recording):
        s = self.s
        font = ('Segoe UI', s.font_size)
        bold = ('Segoe UI', s.font_size, 'bold')
        small = ('Segoe UI', max(7, s.font_size - 2))
        icon_px = s.font_size * 2  # ikona mniej więcej na wysokość wiersza
        cells = []

        def label(text, row, col, fg='#e6e9ec', f=font, anchor='w', padx=(0, 10), image=None, columnspan=1, pady=0):
            cells.append({'kind': 'label', 'row': row, 'col': col, 'text': text, 'fg': fg, 'font': f, 'anchor': anchor,
                          'padx': padx, 'pady': pady, 'image': image, 'span': columnspan})

        if rec is None or (not rec.events and not rec.selection):
            label(t('ov_wait'), 0, 0, fg='#9aa3ab', f=small)
            if not s.locked:
                label(t('ov_drag'), 1, 0, fg='#6b747c', f=small)
            return cells

        tick = rec.max_tick
        from_tick = tick - s.window_s * rec.tps if s.window_s else None
        st = rec.stats(tick, from_tick)
        pcolor = {p: OVERLAY_COLORS[i % len(OVERLAY_COLORS)] for i, p in enumerate(sorted(rec.players))}
        cols = [(k, h) for k, h, on in (('dealt', t('ov_col_dealt'), s.show_dealt), ('share', '%', s.show_share),
                                         ('kills', t('ov_col_kills'), s.show_kills),
                                         ('lost', t('ov_col_lost'), s.show_lost)) if on]
        row = 0
        if s.show_header:
            win = window_label(s.window_s) if s.window_s in WINDOW_VALUES else ''
            by = t('ov_by_kills') if s.sort_by == 'kills' else t('ov_by_dmg')
            label(f"{fmt_time(tick, rec.tps)}  ·  {win}  ·  {by}",
                  row, 0, fg='#9aa3ab', f=small, columnspan=1 + len(cols))
            row += 1

        def top_units(pid):
            ks = [k for k in st.ranking(pid) if st.S[k]['dealt'] > 0 or st.S[k]['kills'] > 0]
            ks.sort(key=lambda k: (-st.S[k][s.sort_by], -st.S[k]['dealt']))
            return ks[:max(1, min(5, s.count))]

        if s.mode == MODE_EACH:
            groups = [(pid, top_units(pid)) for pid in sorted(rec.players)]
        else:
            pid = next((p for p, n in rec.players.items() if n == s.mode), None)
            groups = [(pid, top_units(pid))]

        for gi, (pid, units) in enumerate(groups):
            if s.mode == MODE_EACH:
                label(rec.players.get(pid, '?'), row, 0, fg=pcolor.get(pid, '#ccc'), f=bold, columnspan=1 + len(cols),
                      pady=(6 if gi else 0, 0))
                row += 1
            for i, (cid, head) in enumerate(cols):  # nagłówki kolumn
                label(head, row, 1 + i, fg='#6b747c', f=small, anchor='e', padx=(6, 0))
            row += 1
            total = st.total_dealt(pid if s.mode != MODE_ALL else None) or 1
            if not units:
                label('–', row, 0, fg='#6b747c')
                row += 1
            for n, k in enumerate(units, 1):
                c = st.S[k]
                upid = rec.units.get(k, {}).get('pid')
                label(f' {n}. {rec.unit_label(k)}', row, 0, fg=pcolor.get(upid, '#e6e9ec'),
                      image=iconcache.photo(st.unit_icon(k, icon_px)))
                vals = {'dealt': f"{c['dealt']:.0f}", 'share': f"{100 * c['dealt'] / total:.0f}%",
                        'kills': str(c['kills']), 'lost': str(c['lost'])}
                for i, (cid, _) in enumerate(cols):
                    label(vals[cid], row, 1 + i, f=bold if cid == s.sort_by else font, anchor='e', padx=(6, 0))
                row += 1

        # oddział zaznaczony w grze (rekord 'sel' rejestratora) – zawsze cały mecz, niezależnie od zakresu czasu
        if s.show_selected:
            sel = [k for k in rec.selection if k in rec.units]
            if sel:
                k = sel[0]
                full = rec.stats(tick) if s.window_s else st
                c = full.S[k]
                upid = rec.units.get(k, {}).get('pid')
                span = 1 + max(1, len(cols))
                cells.append({'kind': 'sep', 'row': row, 'col': 0, 'span': span})
                row += 1
                more = f'  (+{len(sel) - 1})' if len(sel) > 1 else ''
                label(f' ▶ {rec.unit_label(k)}{more}', row, 0, fg=pcolor.get(upid, '#e6e9ec'), f=bold, columnspan=span,
                      image=iconcache.photo(full.unit_icon(k, icon_px)))
                row += 1
                label(t('ov_sel_line', d=f"{c['dealt']:.0f}", k=c['kills'], l=c['lost']), row, 0, columnspan=span)
                row += 1
        return cells


class OverlaySettingsWindow(tk.Toplevel):
    """Okno ustawień nakładki; każda zmiana od razu odświeża nakładkę i zapisuje settings.json.
    Listy pokazują etykiety w języku interfejsu, a w ustawieniach zapisywane są kody (sort_by, mode, window_s)."""

    def __init__(self, master, settings: OverlaySettings, players, on_change):
        super().__init__(master)
        self.title(t('set_title'))
        self.resizable(False, False)
        self.s, self.on_change = settings, on_change
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

        def label_of(mapping, value, default):
            return next((k for k, v in mapping.items() if v == value), default)

        self.v['enabled'] = tk.BooleanVar(value=settings.enabled)
        ttk.Checkbutton(f, text=t('set_show'), variable=self.v['enabled'], command=self._apply).grid(
            row=r, column=0, columnspan=2, sticky='w', pady=(0, 6))
        r += 1
        self.v['count'] = tk.IntVar(value=settings.count)
        row(t('set_count'), ttk.Spinbox(f, from_=2, to=5, width=5, textvariable=self.v['count'], command=self._apply,
                                        state='readonly'))
        self.v['sort_by'] = tk.StringVar(value=label_of(self.sorts, settings.sort_by, t('sort_dealt')))
        row(t('set_sort'), self._combo(f, self.v['sort_by'], list(self.sorts)))
        self.v['mode'] = tk.StringVar(value=label_of(self.modes, settings.mode, settings.mode))
        self.mode_box = self._combo(f, self.v['mode'], list(self.modes) + list(players))
        row(t('set_players'), self.mode_box)
        self.v['window_s'] = tk.StringVar(value=label_of(self.windows, settings.window_s, list(self.windows)[0]))
        row(t('set_range'), self._combo(f, self.v['window_s'], list(self.windows)))

        ttk.Label(f, text=t('set_columns')).grid(row=r, column=0, sticky='nw', pady=3)
        cf = ttk.Frame(f)
        cf.grid(row=r, column=1, sticky='w')
        r += 1
        for i, (key, text) in enumerate([('show_dealt', t('chk_dealt')), ('show_kills', t('chk_kills')),
                                         ('show_lost', t('chk_lost')), ('show_share', t('chk_share')),
                                         ('show_header', t('chk_header')), ('show_selected', t('chk_selected'))]):
            self.v[key] = tk.BooleanVar(value=getattr(settings, key))
            ttk.Checkbutton(cf, text=text, variable=self.v[key], command=self._apply).grid(row=i // 2, column=i % 2,
                                                                                           sticky='w', padx=(0, 10))
        self.v['opacity'] = tk.DoubleVar(value=settings.opacity)
        row(t('set_opacity'), ttk.Scale(f, from_=0.3, to=1.0, variable=self.v['opacity'], command=lambda _: self._apply()))
        self.v['font_size'] = tk.IntVar(value=settings.font_size)
        row(t('set_font'), ttk.Spinbox(f, from_=8, to=20, width=5, textvariable=self.v['font_size'],
                                       command=self._apply, state='readonly'))
        self.v['locked'] = tk.BooleanVar(value=settings.locked)
        ttk.Checkbutton(f, text=t('set_lock'), variable=self.v['locked'],
                        command=self._apply).grid(row=r, column=0, columnspan=2, sticky='w', pady=(8, 0))
        r += 1
        ttk.Label(f, text=t('set_drag_hint'), foreground='#666').grid(row=r, column=0, columnspan=2, sticky='w')

    def _combo(self, parent, var, values):
        c = ttk.Combobox(parent, textvariable=var, values=values, state='readonly', width=26)
        c.bind('<<ComboboxSelected>>', lambda e: self._apply())
        return c

    def set_players(self, players):
        self.mode_box.configure(values=list(self.modes) + list(players))

    def _apply(self):
        s, v = self.s, self.v
        s.enabled = v['enabled'].get()
        s.count = int(v['count'].get())
        s.sort_by = self.sorts.get(v['sort_by'].get(), 'dealt')
        s.mode = self.modes.get(v['mode'].get(), v['mode'].get())  # kod trybu albo nazwa gracza
        s.window_s = self.windows.get(v['window_s'].get(), 0)
        for key in ('show_dealt', 'show_kills', 'show_lost', 'show_share', 'show_header', 'show_selected', 'locked'):
            setattr(s, key, v[key].get())
        s.opacity = round(float(v['opacity'].get()), 2)
        s.font_size = int(v['font_size'].get())
        s.save()
        self.on_change()
