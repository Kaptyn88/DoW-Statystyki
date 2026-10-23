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
import ctypes.wintypes as wt
import json
import os
import tkinter as tk
from dataclasses import asdict, dataclass, field, fields
from tkinter import ttk
from tkinter import font as tkfont

import iconcache
import paths
from hotkeys import KEYS, Hotkeys
from i18n import t
from recmodel import CATALOG, Recording, is_model

SETTINGS_PATH = paths.SETTINGS_PATH
# jaśniejsze odcienie kolorów graczy – czytelne na ciemnym tle nakładki
OVERLAY_COLORS = ['#7fb0ff', '#ff8a6b', '#6fd68f', '#f2c14e', '#c38df0', '#4fd1c5', '#ff6b81', '#c0c6cc']
THEME = {
    'bg': '#14171b', 'surface': '#1b2026', 'border': '#343c45',
    'text': '#edf0f3', 'muted': '#a3adb8', 'quiet': '#89949f',
    'accent': '#8bb9d6', 'bar': '#59809a', 'track': '#282f37',
    'hover': '#29343f', 'selected': '#30485a', 'success': '#83c79a', 'error': '#efaa90',
}
# tryb graczy zapisywany kodem ('all' / 'each') albo nazwą gracza; dawne polskie etykiety mapujemy przy wczytaniu
MODE_ALL, MODE_EACH = 'all', 'each'
LEGACY_MODES = {'Wszyscy razem': MODE_ALL, 'Każdy gracz osobno': MODE_EACH}
WINDOW_VALUES = (0, 60, 180)        # sekundy; 0 = cały mecz
SORT_VALUES = ('dealt', 'kills')


def style_caption(win):
    """Ciemny systemowy pasek tytułu; starsze wersje Windows pomijają nieobsługiwane atrybuty."""
    if os.name != 'nt' or not win.winfo_exists():
        return
    try:
        win.update_idletasks()
        hwnd = ctypes.windll.user32.GetAncestor(win.winfo_id(), 2)
        setter = ctypes.windll.dwmapi.DwmSetWindowAttribute
        for attr, value in ((20, 1), (35, int(THEME['bg'][5:7] + THEME['bg'][3:5] + THEME['bg'][1:3], 16))):
            data = ctypes.c_uint(value)
            setter(wt.HWND(hwnd), attr, ctypes.byref(data), ctypes.sizeof(data))
    except (AttributeError, OSError):
        pass


def configure_app_style(master):
    """Wspólny motyw podglądu i ustawień; nie zmienia danych ani ustawień nakładek."""
    style = ttk.Style(master)
    style.theme_use('clam')
    bg, surface, text = THEME['bg'], THEME['surface'], THEME['text']
    style.configure('.', background=bg, foreground=text, font=('Segoe UI', 9),
                    bordercolor=THEME['border'], lightcolor=bg, darkcolor=bg,
                    troughcolor=THEME['track'], focuscolor=THEME['accent'])
    style.configure('TFrame', background=bg)
    style.configure('Surface.TFrame', background=surface)
    style.configure('TLabel', background=bg, foreground=text)
    style.configure('Muted.TLabel', foreground=THEME['muted'])
    style.configure('Surface.TLabel', background=surface)
    style.configure('TButton', background=surface, foreground=text, padding=(12, 7),
                    borderwidth=1, relief='flat', focusthickness=1, focuscolor=THEME['accent'])
    style.map('TButton', background=[('active', THEME['hover']), ('pressed', THEME['selected'])],
              foreground=[('disabled', THEME['quiet'])], bordercolor=[('focus', THEME['accent'])])
    style.configure('Accent.TButton', background=THEME['accent'], foreground=bg, font=('Segoe UI', 9, 'bold'))
    style.map('Accent.TButton', background=[('pressed', '#6f9bb8'), ('active', '#abd0e7')],
              foreground=[('disabled', THEME['quiet']), ('!disabled', bg)])
    style.configure('TCheckbutton', background=bg, foreground=text, padding=(0, 4),
                    indicatorbackground=surface, indicatorforeground=THEME['accent'])
    style.map('TCheckbutton', background=[('active', bg)],
              indicatorbackground=[('selected', THEME['selected']), ('active', THEME['hover'])],
              foreground=[('disabled', THEME['quiet'])])
    for widget in ('TCombobox', 'TSpinbox'):
        style.configure(widget, fieldbackground=surface, background=surface, foreground=text,
                        arrowcolor=THEME['muted'], padding=(7, 4), borderwidth=1)
        style.map(widget, fieldbackground=[('readonly', surface), ('disabled', bg)],
                  foreground=[('readonly', text), ('disabled', THEME['quiet'])],
                  selectbackground=[('readonly', surface)], selectforeground=[('readonly', text)],
                  bordercolor=[('focus', THEME['accent']), ('active', THEME['accent'])])
    style.configure('Treeview', background=surface, fieldbackground=surface, foreground=text,
                    rowheight=32, borderwidth=0, font=('Segoe UI', 10))
    style.configure('Treeview.Heading', background=THEME['track'], foreground=THEME['muted'],
                    padding=(4, 10), relief='flat', font=('Segoe UI', 9, 'bold'))
    style.map('Treeview', background=[('selected', THEME['selected'])],
              foreground=[('selected', '#ffffff')])
    style.map('Treeview.Heading', background=[('active', THEME['hover'])],
              foreground=[('active', text)])
    style.configure('TScrollbar', background=THEME['border'], troughcolor=surface,
                    borderwidth=0, arrowsize=12, arrowcolor=THEME['muted'])
    style.map('TScrollbar', background=[('active', THEME['bar']), ('pressed', THEME['accent'])])
    style.configure('TScale', background=bg, troughcolor=THEME['track'], sliderlength=18, borderwidth=0)
    style.configure('TSeparator', background=THEME['border'])
    master.configure(background=bg)
    master.option_add('*TCombobox*Listbox.background', surface)
    master.option_add('*TCombobox*Listbox.foreground', text)
    master.option_add('*TCombobox*Listbox.selectBackground', THEME['selected'])
    master.option_add('*TCombobox*Listbox.selectForeground', '#ffffff')
    master.after(30, lambda: style_caption(master))
    return style


def window_label(sec):
    return t(f'win_{sec}')


@dataclass
class OverlaySettings:
    enabled: bool = True          # nakładka oddziału; domyślnie włączona (v1.2); wyłączenie zapisuje się w settings.json
    sum_enabled: bool = True      # nakładka podsumowania (v1.4)
    sum_tab: str = 'army'
    sum_tabs_off: list = field(default_factory=list)
    build_rows: int = 8           # widoczne wiersze kolejności budowy na gracza (reszta pod przewijaniem)  # wyłączone zakładki podsumowania (kody, np. 'eco')
    sum_x: int = 40
    sum_y: int = 420
    key_unit: str = 'F6'          # skróty: pokaż/ukryj nakładkę oddziału, podsumowanie, następna zakładka ('' = brak)
    key_summary: str = 'F7'
    key_tab: str = 'F8'
    key_tab_prev: str = 'Shift+F8'  # poprzednia zakładka
    key_tabs: dict = field(default_factory=dict)  # opcjonalnie: zakładka -> klawisz (domyślnie brak)
    count: int = 3
    sort_by: str = 'dealt'
    mode: str = MODE_ALL          # MODE_ALL, MODE_EACH albo nazwa gracza
    window_s: int = 0             # 0 = cały mecz
    show_dealt: bool = True
    show_kills: bool = True
    show_lost: bool = False
    show_share: bool = False
    show_header: bool = True      # (do v1.4 podtytuł zakresu/sortowania – usunięty; pole dla zgodności)
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
    _no_activate_on_click(win, hwnd)
    return True


# Kliknięcie odblokowanej nakładki (przeciąganie, zakładki, kółko) nie może aktywować jej okna: gra traci wtedy fokus
# i na chwilę staje. Tk na WM_MOUSEACTIVATE odpowiada MA_ACTIVATE mimo WS_EX_NOACTIVATE (sprawdzone 2026-10-19:
# SendMessage(WM_MOUSEACTIVATE) -> 1), więc podmieniamy procedurę okna głównego nakładki: MA_NOACTIVATE, reszta do Tk.
WM_MOUSEACTIVATE, MA_NOACTIVATE, GWLP_WNDPROC = 0x21, 3, -4


def _no_activate_on_click(win, hwnd):
    """Procedura zapamiętana na oknie Tk (musi żyć tak długo jak okno; numer hwnd zamkniętego okna Windows może
    nadać nowemu, więc nie trzymamy globalnej listy)."""
    if getattr(win, '_noact', (None,))[0] == hwnd:
        return
    user32 = ctypes.windll.user32
    lresult = ctypes.c_ssize_t
    proc_t = ctypes.WINFUNCTYPE(lresult, wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM)
    user32.SetWindowLongPtrW.argtypes = [wt.HWND, ctypes.c_int, ctypes.c_void_p]
    user32.SetWindowLongPtrW.restype = ctypes.c_void_p
    user32.CallWindowProcW.argtypes = [ctypes.c_void_p, wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
    user32.CallWindowProcW.restype = lresult

    old = [None]

    def proc(h, msg, wp, lp):
        if msg == WM_MOUSEACTIVATE:
            return MA_NOACTIVATE
        return user32.CallWindowProcW(old[0], h, msg, wp, lp)

    cb = proc_t(proc)
    win._noact = (hwnd, cb)
    old[0] = user32.SetWindowLongPtrW(hwnd, GWLP_WNDPROC, ctypes.cast(cb, ctypes.c_void_p))


class OverlayWindow(tk.Toplevel):
    """Wspólna część nakładek: okno bez ramki na wierzchu, przeciąganie, klikanie przez nakładkę, przezroczystość
    i rysowanie listy komórek (etykiety tworzone raz, potem zmieniane tylko te, które się zmieniły)."""
    BG = THEME['bg']
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
        self.configure(background=self.BG, highlightthickness=1, highlightbackground=THEME['border'])
        self.body = tk.Frame(self, background=self.BG, padx=14, pady=10)
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
        # Najpierw przezroczystość, POTEM nasze style: przy alfa = 1.0 Tk wyłącza WS_EX_LAYERED i nadpisuje rozszerzone
        # style okna, kasując WS_EX_NOACTIVATE/TRANSPARENT – od v2.0 podsumowanie (domyślnie nieprzezroczyste) nie
        # przepuszczało kliknięć i kliknięcie zabierało grze aktywność, więc gra stawała (2026-10-23: ex = 0x8).
        # Alfa najwyżej 0.99 (niewidoczna różnica), żeby Tk zostawał przy oknie warstwowym.
        self.attributes('-alpha', max(0.2, min(0.99, getattr(self.s, self.OPACITY))))
        if not set_click_through(self, self.locked):
            self.after(100, self.apply_window_style)  # okno jeszcze nie zmapowane – ponów
            return
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
                w = (tk.Frame(self.body, height=1, bg=THEME['border']) if c['kind'] == 'sep'
                     else tk.Canvas(self.body, bg=self.BG, highlightthickness=0) if c['kind'] in ('chart', 'vbar', 'bar')
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
            elif c['kind'] == 'bar':
                w.configure(width=180, height=6)
                w.spec = c
                w.bind('<Configure>', lambda e, cv=w: draw_rank_bar(cv))
                w.grid(row=c['row'], column=c['col'], columnspan=c['span'], sticky='we',
                       padx=(0, 12), pady=(3, 9))
                draw_rank_bar(w)
            elif c['kind'] == 'vbar':
                w.configure(width=4, height=1)  # wysokość z wierszy (sticky ns), nie z płótna
                w.spec = c
                w.bind('<Configure>', lambda e, cv=w: draw_vbar(cv))
                w.grid(row=c['row'], column=c['col'], rowspan=c['rows'], sticky='ns', padx=(4, 0), pady=2)
                draw_vbar(w)
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
        self.number = ('Consolas', s.font_size)
        self.number_bold = ('Consolas', s.font_size, 'bold')
        self.headline = ('Consolas', s.font_size + 9, 'bold')
        self.icon_px = s.font_size * 2  # ikona mniej więcej na wysokość wiersza

    def label(self, text, row, col, fg=THEME['text'], f=None, anchor='w', padx=(0, 10), image=None, columnspan=1, pady=0,
              compound='left'):
        self.append({'kind': 'label', 'row': row, 'col': col, 'text': text, 'fg': fg,
                     'font': f or (self.number if anchor == 'e' else self.font),
                     'anchor': anchor, 'padx': padx, 'pady': pady, 'image': image, 'span': columnspan,
                     'compound': compound})

    def res(self, row, col, req, pw, f=None, padx=(14, 0)):
        """Rekwizycja i energia w dwóch kolumnach (col, col + 1), w kolorach RES_COLORS, wyrównane do prawej."""
        self.label(fmt_num(req), row, col, fg=RES_COLORS[0], f=f, anchor='e', padx=padx)
        self.label(fmt_num(pw), row, col + 1, fg=RES_COLORS[1], f=f, anchor='e', padx=(8, 0))

    def res_heads(self, row, col, title):
        """Nagłówek grupy (nad dwiema kolumnami) + R / E w kolorach pod spodem (w wierszu row + 1)."""
        self.label(title, row, col, fg=THEME['quiet'], f=self.small, anchor='e', padx=(14, 0), columnspan=2)
        self.label(t('res_r'), row + 1, col, fg=RES_COLORS[0], f=self.small, anchor='e', padx=(14, 0))
        self.label(t('res_e'), row + 1, col + 1, fg=RES_COLORS[1], f=self.small, anchor='e', padx=(8, 0))

    def sep(self, row, span):
        self.append({'kind': 'sep', 'row': row, 'col': 0, 'span': span})

    def bar(self, row, col, ratio, leader=False, color=None):
        self.append({'kind': 'bar', 'row': row, 'col': col, 'span': 1,
                     'ratio': max(0, min(1, ratio)), 'leader': leader, 'color': color or THEME['bar']})

    def vbar(self, row, col, rows, first, shown, total):
        """Wąski pasek przewijania obok listy: widoczne pozycje first..first+shown z total."""
        self.append({'kind': 'vbar', 'row': row, 'col': col, 'span': 1, 'rows': rows, 'first': first,
                     'shown': shown, 'total': total})

    def chart(self, row, span, points, colors, width, height, end_label):
        self.append({'kind': 'chart', 'row': row, 'col': 0, 'span': span, 'points': tuple(points),
                     'colors': tuple(colors), 'w': width, 'h': height, 'end': end_label})


def _dim(color, bg=THEME['bg'], k=0.35):
    """Kolor wypełnienia: color zmieszany z tłem (k = udział koloru)."""
    a = [int(color[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(bg[i:i + 2], 16) for i in (1, 3, 5)]
    return '#' + ''.join(f'{round(x * k + y * (1 - k)):02x}' for x, y in zip(a, b))


def draw_rank_bar(cv):
    """Zaokrąglony pasek rankingu; szerokość podąża za kolumną nazw."""
    cv.delete('all')
    width, height = max(6, cv.winfo_width()), 6
    radius = height / 2
    cv.create_line(radius, radius, width - radius, radius, width=height,
                   fill=THEME['track'], capstyle=tk.ROUND)
    ratio = cv.spec['ratio']
    if ratio > 0:
        filled = width * ratio
        color = _dim(cv.spec['color'], k=0.95 if cv.spec['leader'] else 0.75)
        if filled < height:
            cv.create_oval(0, 0, filled, height, fill=color, outline='')
        else:
            cv.create_line(radius, radius, filled - radius, radius, width=height,
                           fill=color, capstyle=tk.ROUND)


def draw_vbar(cv):
    c = cv.spec
    cv.delete('all')
    h = max(1, cv.winfo_height())
    cv.create_rectangle(0, 0, 4, h, fill='#1f262d', outline='')
    total = max(1, c['total'])
    y0, y1 = h * c['first'] / total, h * (c['first'] + c['shown']) / total
    cv.create_rectangle(0, y0, 4, max(y0 + 6, y1), fill='#6b7580', outline='')


def draw_chart(cv, c):
    """Wykres przewagi jak "Income advantage" w SC2: nad zerem przewaga drużyny 1 (jej kolor), pod zerem drużyny 2."""
    cv.delete('all')
    w, h, pts = c['w'], c['h'], c['points']
    cv.configure(width=w, height=h)
    left, right, top, bottom = 44, w - 6, 6, h - 16
    font = ('Segoe UI', 8)
    if len(pts) < 2:
        cv.create_text(w // 2, h // 2, text='–', fill=THEME['quiet'], font=font)
        return
    t0, t1 = pts[0][0], pts[-1][0]
    span = max(1, t1 - t0)
    ymax = max(abs(v) for _, v in pts)
    nice = next((n for n in (10, 20, 25, 50, 100, 150, 250, 500, 750, 1000, 1500, 2500, 5000, 10000) if n >= ymax),
                ymax or 1)
    mid = (top + bottom) / 2

    def xy(tick, v):
        return left + (tick - t0) / span * (right - left), mid - v / nice * (bottom - top) / 2

    pos, neg = c['colors']
    cv.create_rectangle(left, top, right, mid, fill=_dim(pos, k=0.08), outline='')
    cv.create_rectangle(left, mid, right, bottom, fill=_dim(neg, k=0.08), outline='')
    for v, col in ((nice, pos), (0, THEME['muted']), (-nice, neg)):
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
    cv.create_text(left, h - 2, text='0:00', anchor='sw', fill=THEME['quiet'], font=font)
    cv.create_text(right, h - 2, text=c['end'], anchor='se', fill=THEME['quiet'], font=font)


def pname(rec, pid):
    """Nick gracza z frakcją, np. 'Frintt (Nekroni)'; frakcja z jednostek gracza (Recording.player_race)."""
    name = rec.players.get(pid, '?')
    race = rec.player_race(pid)
    return f'{name} ({t("race_" + race)})' if race else name


RES_COLORS = ('#e8b45a', '#6cb8e6')  # rekwizycja (bursztyn), energia (niebieski) – kolumny R/E


def fmt_num(v):
    """Liczba całkowita z odstępem tysięcy (wąska spacja niełamiąca), np. 12 345."""
    return f'{v:,.0f}'.replace(',', '\u202f')


def fmt_res(req, pw):
    """Rekwizycja i energia, np. '450 R / 50 E' (skróty w języku interfejsu)."""
    return t('res_fmt', r=f'{req:.0f}', p=f'{pw:.0f}')


class UnitOverlay(OverlayWindow):
    """Nakładka 1: oddział zaznaczony w grze (rekord 'sel' rejestratora) – statystyki z całego meczu."""

    def _layout(self, rec, c):
        if rec is None or (not rec.events and not rec.selection):
            c.label(t('ov_wait'), 0, 0, fg=THEME['muted'], f=c.small)
            if not self.locked:
                c.label(t('ov_drag'), 1, 0, fg=THEME['quiet'], f=c.small)
            return c
        sel = [k for k in rec.selection if k in rec.units]
        if not sel:
            c.label(t('ov_sel_none'), 0, 0, fg=THEME['quiet'], f=c.small)
            if not self.locked:
                c.label(t('ov_drag'), 1, 0, fg=THEME['quiet'], f=c.small)
            return c
        st = rec.stats(rec.max_tick)
        k = sel[0]
        s = st.S[k]
        more = f'  (+{len(sel) - 1})' if len(sel) > 1 else ''
        upid = rec.units.get(k, {}).get('pid')
        portrait_px = max(48, min(64, c.icon_px * 2))
        c.label(f'  {rec.unit_label(k)}{more}', 0, 0, f=c.bold, columnspan=3,
                image=iconcache.photo(st.unit_icon(k, 32), size=portrait_px), pady=(0, 6))
        c.label(pname(rec, upid), 1, 0, fg=self.colors(rec).get(upid, THEME['muted']),
                f=c.small, columnspan=3)
        c.sep(2, 3)
        for col, (value, label) in enumerate(((s['dealt'], 'card_dealt'),
                                             (s['kills'], 'card_kills'), (s['lost'], 'card_lost'))):
            c.label(fmt_num(value), 3, col, f=c.headline if col == 0 else c.number_bold,
                    fg=THEME['text'] if col == 0 else THEME['muted'], padx=(0, 22))
            c.label(t(label), 4, col, f=c.small, fg=THEME['muted'], padx=(0, 22))
        if s['killed_req'] or s['killed_pow'] or s['lost_req'] or s['lost_pow']:
            c.sep(5, 3)
            c.label(t('ov_value_line', k=fmt_res(s['killed_req'], s['killed_pow']),
                      l=fmt_res(s['lost_req'], s['lost_pow'])), 6, 0, fg=THEME['muted'], f=c.small,
                    columnspan=3)
        return c


SUMMARY_TABS = ('army', 'losses', 'eco', 'research', 'build', 'battles')


def visible_tabs(s):
    """Włączone zakładki podsumowania w stałej kolejności (co najmniej jedna)."""
    return [x for x in SUMMARY_TABS if x not in s.sum_tabs_off] or [SUMMARY_TABS[0]]


def current_tab(s):
    tabs = visible_tabs(s)
    return s.sum_tab if s.sum_tab in tabs else tabs[0]
LOST_PER_ROW = 12  # ikon w wierszu zakładki Straty


class OverlayTab(tk.Canvas):
    """Płaska zakładka z podkreśleniem aktywnej pozycji i delikatnym stanem hover."""

    def __init__(self, master, text):
        super().__init__(master, bg=master.cget('background'), highlightthickness=0, bd=0, takefocus=0)
        self.text, self.selected, self.hover = text, False, False
        self.tab_font = ('Segoe UI', 11)
        self.bind('<Enter>', lambda _: self._hover(True))
        self.bind('<Leave>', lambda _: self._hover(False))

    def _hover(self, hover):
        self.hover = hover
        self._paint()

    def set_style(self, selected, size):
        self.selected = selected
        self.tab_font = ('Segoe UI', size, 'bold' if selected else 'normal')
        # Pomiar pogrubionego tekstu także dla nieaktywnych: przy zmianie zakładki pasek nie przesuwa się.
        measure = tkfont.Font(self, family='Segoe UI', size=size, weight='bold')
        self.configure(width=measure.measure(self.text) + 32, height=measure.metrics('linespace') + 18)
        self._paint()

    def _paint(self):
        self.delete('all')
        w, h = int(self.cget('width')), int(self.cget('height'))
        if self.selected or self.hover:
            self.create_rectangle(0, 0, w, h, outline='',
                                  fill='#1c2a35' if self.selected else '#19222b')
        if self.selected:
            self.create_rectangle(10, h - 2, w - 10, h, fill=THEME['accent'], outline='')
        self.create_text(w / 2, (h - 2) / 2, text=self.text, font=self.tab_font,
                         fill=THEME['text'] if self.selected or self.hover else THEME['muted'])


class SummaryOverlay(OverlayWindow):
    """Nakładka 2: podsumowanie meczu w zakładkach (przełączane skrótem klawiszowym)."""
    POS = ('sum_x', 'sum_y')
    OPACITY, LOCK = 'sum_opacity', 'sum_locked'
    TAB_BG = '#10151b'

    def __init__(self, master, settings: OverlaySettings):
        super().__init__(master, settings)
        # pasek zakładek nad siatką treści (osobna ramka – szerokości "przycisków" nie zależą od kolumn tabel)
        self.bar = tk.Frame(self, background=self.TAB_BG, padx=10, pady=8)
        self.bar.pack(fill='x', before=self.body)
        self.bind_all_drag(self.bar)
        self._tabs = {}
        for name in SUMMARY_TABS:
            w = OverlayTab(self.bar, text=t('tab_' + name))
            w.set_style(name == current_tab(settings), settings.font_size)
            w.pack(side='left', padx=(0, 5))
            self.bind_all_drag(w)  # najpierw przeciąganie, potem kliknięcie zakładki (add='+', bez nadpisania)
            w.bind('<ButtonRelease-1>', lambda e, n=name: self._click_tab(n), add='+')
            self._tabs[name] = w
        self._clock = tk.Label(self.bar, text='', bg=self.TAB_BG, fg=THEME['accent'], padx=14)
        self._clock.pack(side='right', padx=(12, 0))
        self.bind_all_drag(self._clock)
        self._bar_state = None
        self._grid_state = None
        self._balanced_columns = []
        self.on_tab = None  # ustawia menedżer: zmiana zakładki kliknięciem (okno odblokowane)

    def _click_tab(self, name):
        if not self.locked and self.on_tab and not self._dragged:
            self.on_tab(name)

    def _start_drag(self, e):
        self._dragged = False
        super()._start_drag(e)

    def _on_drag(self, e):
        self._dragged = True
        super()._on_drag(e)

    _dragged = False
    build_scroll = 0

    def bind_all_drag(self, w):
        super().bind_all_drag(w)
        w.bind('<MouseWheel>', self._wheel)

    def _wheel(self, e):
        if current_tab(self.s) != 'build' or self.locked:
            return
        self.build_scroll = max(0, self.build_scroll + (1 if e.delta > 0 else -1))
        self._last_cells = None
        self.render(self._rec)

    _rec = None

    def render(self, rec):
        self._rec = rec
        tab = current_tab(self.s)
        width = 1 + sum((self.s.show_dealt, self.s.show_share, self.s.show_kills, self.s.show_lost))
        teams = len(rec.teams()) if rec is not None and rec.events else 0
        grid_state = (tab, width, teams)
        if grid_state != self._grid_state:
            for col in self._balanced_columns:
                self.body.columnconfigure(col, uniform='')
            self._balanced_columns = []
            if tab == 'army':
                for side in range(teams):
                    for offset in range(width):
                        col = side * (width + 1) + offset
                        self.body.columnconfigure(col, uniform=f'army_{offset}')
                        self._balanced_columns.append(col)
            self._grid_state = grid_state
        super().render(rec)
        shown = tuple(visible_tabs(self.s))
        clock = fmt_time(rec.max_tick, rec.tps) if rec is not None and rec.events else ''
        state = (tab, shown, clock, self.s.font_size)
        if state == self._bar_state:
            return
        if not self._bar_state or self._bar_state[1] != shown:  # zmiana listy zakładek: ułóż od nowa
            for w in self._tabs.values():
                w.pack_forget()
            for name in shown:
                self._tabs[name].pack(side='left', padx=(0, 5))
        self._bar_state = state
        for name, w in self._tabs.items():
            w.set_style(name == tab, self.s.font_size)
        self._clock.configure(text=clock, font=('Consolas', self.s.font_size))

    def _layout(self, rec, c):
        s = self.s
        tab = current_tab(s)
        if rec is None or not rec.events:
            c.label(t('ov_wait'), 0, 0, fg=THEME['muted'], f=c.small)
            if not self.locked:
                c.label(t('ov_drag'), 1, 0, fg=THEME['quiet'], f=c.small)
            return c
        tick = rec.max_tick
        if tab == 'losses':
            self._losses(rec, c, tick)
        elif tab == 'eco':
            self._eco(rec, c, tick)
        elif tab == 'research':
            self._research(rec, c)
        elif tab == 'build':
            self._build(rec, c)
        elif tab == 'battles':
            self._battles(rec, c)
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
        cols = [(k, h) for k, h, on in (('dealt', t('ov_col_dealt'), s.show_dealt),
                                         ('share', t('ov_player_share'), s.show_share),
                                         ('kills', t('ov_col_kills'), s.show_kills),
                                         ('lost', t('ov_col_lost'), s.show_lost)) if on]
        width = 1 + len(cols)          # kolumny siatki jednej drużyny
        top = 5
        span = max(1, len(rec.teams()) * (width + 1) - 1)
        c.sep(3, span)

        def top_units(pid):
            ks = [k for k in st.ranking(pid) if st.S[k]['dealt'] > 0 or st.S[k]['kills'] > 0]
            ks.sort(key=lambda k: (-st.S[k][s.sort_by], -st.S[k]['dealt']))
            return ks[:max(1, min(5, s.count))]

        for side, team in enumerate(rec.teams()):
            col0 = side * (width + 1)  # między drużynami pusta kolumna odstępu
            if side:
                c.label('', top, width, padx=(14, 14))
            team_damage = sum(st.total_dealt(pid) for pid in team)
            c.label(t('ov_team_damage', n=side + 1), 1, col0, fg=THEME['muted'], f=c.small,
                    columnspan=width)
            c.label(fmt_num(team_damage), 2, col0, f=c.headline, columnspan=width, pady=(0, 8))
            row = top
            for pid in team:
                c.label(pname(rec, pid), row, col0, fg=pcolor.get(pid, '#ccc'), f=c.bold,
                        columnspan=width, pady=(6 if row > top else 0, 0))
                row += 1
                player_damage = st.total_dealt(pid)
                c.label(t('ov_player_damage', damage=fmt_num(player_damage)), row, col0,
                        fg=THEME['muted'], f=c.small, pady=(1, 5))
                for i, (cid, head) in enumerate(cols):
                    c.label(head, row, col0 + 1 + i, fg=THEME['quiet'], f=c.small, anchor='e', padx=(6, 0),
                            pady=(1, 5))
                row += 1
                units = top_units(pid)
                if not units:
                    c.label('–', row, col0, fg=THEME['quiet'])
                    row += 1
                for rank, k in enumerate(units, 1):
                    v = st.S[k]
                    c.label(f' {rank:02d}  {rec.unit_label(k)}', row, col0, fg=THEME['text'],
                            image=iconcache.photo(st.unit_icon(k, c.icon_px)))
                    vals = {'dealt': fmt_num(v['dealt']),
                            'share': f"{100 * v['dealt'] / (player_damage or 1):.0f}%",
                            'kills': str(v['kills']), 'lost': str(v['lost'])}
                    for i, (cid, _) in enumerate(cols):
                        c.label(vals[cid], row, col0 + 1 + i,
                                f=c.number_bold if cid == s.sort_by else c.number, anchor='e',
                                fg=THEME['text'] if cid == s.sort_by else THEME['muted'], padx=(12, 0))
                    # Pasek i kolumna procentowa zawsze pokazują udział w obrażeniach gracza,
                    # niezależnie od sortowania i liczby widocznych oddziałów.
                    c.bar(row + 1, col0, v['dealt'] / (player_damage or 1), leader=rank == 1,
                          color=pcolor.get(pid, THEME['bar']))
                    row += 2

    def _losses(self, rec, c, tick):
        """Jak "Units Lost" w SC2: dla każdej drużyny ikony straconych modeli/budynków z liczbą sztuk (cały mecz),
        nad ikonami stracona rekwizycja i energia, wyliczane jak dotychczas."""
        st = rec.stats(tick)
        pcolor = self.colors(rec)
        tile = c.icon_px + 10  # ikony większe niż w liście oddziałów
        row = 1
        for side, team in enumerate(rec.teams()):
            if side:
                c.sep(row, LOST_PER_ROW)
                row += 1
            c.label(t('ov_team', n=side + 1), row, 0, fg=THEME['quiet'], f=c.small,
                    columnspan=LOST_PER_ROW, pady=(0, 4))
            row += 1
            for pid in team:
                c.label(pname(rec, pid), row, 0, fg=pcolor.get(pid, THEME['text']), f=c.bold,
                        columnspan=LOST_PER_ROW, pady=(0, 2))
                row += 1
            tot = collections.Counter()
            for p in team:
                tot.update(st.player_totals(p))
            for col, key, label, color, suffix in (
                    (0, 'lost_req', 'ov_requisition', RES_COLORS[0], 'res_r'),
                    (LOST_PER_ROW // 2, 'lost_pow', 'ov_power', RES_COLORS[1], 'res_e')):
                c.label(f"{fmt_num(tot[key])} {t(suffix)}", row, col, fg=color, f=c.headline,
                        columnspan=LOST_PER_ROW // 2, pady=(6, 0))
                c.label(t(label), row + 1, col, fg=THEME['muted'], f=c.small,
                        columnspan=LOST_PER_ROW // 2, pady=(0, 10))
            row += 2
            lost = collections.Counter(
                bp for eid, bp in ((e, rec.ent_bp.get(e)) for e in rec.death_tick)
                if rec.ent_pid.get(eid) in team and is_model(bp) and eid not in rec.not_lost)
            if not lost:
                c.label('–', row, 0, fg=THEME['quiet'])
                row += 1
            for i, (bp, n) in enumerate(sorted(lost.items(), key=lambda x: (-x[1], x[0]))):
                img = iconcache.photo(CATALOG.icon_file(CATALOG.squad_icon(bp), tile))
                text = str(n) if img else (CATALOG.squad(bp) or bp)[:8] + chr(10) + str(n)
                c.label(text, row + i // LOST_PER_ROW, i % LOST_PER_ROW, f=c.number if img else c.small,
                        anchor='center', padx=(0, 8), pady=(2, 8), image=img, compound='top')
            row += (len(lost) + LOST_PER_ROW - 1) // LOST_PER_ROW

    def _eco(self, rec, c, tick):
        """Ekonomia: stan konta, dochód na 10 s i zebrane łącznie każdego gracza (drużynami; R i E w osobnych
        kolumnach) + wykresy przewagi dochodu drużyny 1 nad 2, osobno rekwizycja i energia. Dane: rekord 'eco'."""
        if not rec.eco:
            c.label(t('eco_none'), 1, 0, fg=THEME['quiet'], f=c.small, columnspan=6)
            return
        pcolor = self.colors(rec)
        per = rec.INCOME_S * rec.tps
        teams = rec.teams()
        row = 1
        for i, head in enumerate((t('eco_col_bank'), t('eco_col_income'), t('eco_col_total'))):
            c.res_heads(row, 1 + 2 * i, head)
        row += 2
        for side, team in enumerate(teams):
            if side:
                c.sep(row, 7)
                row += 1
            for pid in team:
                e = rec.eco_at(pid)
                c.label(pname(rec, pid), row, 0, fg=pcolor.get(pid, THEME['text']), f=c.bold)
                if e:
                    _, req, pw, ir, ip, cr, cp = e
                    for i, (a, b) in enumerate(((req, pw), (ir * per, ip * per), (cr, cp))):
                        c.res(row, 1 + 2 * i, a, b)
                row += 1
        colors = [pcolor.get(team[0], THEME['text']) if team else THEME['text'] for team in teams]
        width, height = self.s.font_size * 46, self.s.font_size * 11
        names = [' · '.join(rec.players.get(p, '?') for p in team) for team in teams]
        charts = [('eco_chart_req', rec.income_advantage(teams, 3)), ('eco_chart_pow', rec.income_advantage(teams, 4))]
        for (key, points), fg in zip(charts, RES_COLORS):  # nagłówek w kolorze zasobu (jak kolumny R/E)
            c.label(t(key, a=names[0], b=names[1]), row, 0, fg=fg, f=c.small, columnspan=7, pady=(8, 0))
            row += 1
            c.chart(row, 7, points, colors, width, height, fmt_time(tick, rec.tps))
            row += 1

    def _research(self, rec, c):
        """Ukończone ulepszenia (rekord 'res'): drużyna po lewej i po prawej, każdy gracz z listą czas + ikona + nazwa
        i sumą wydaną na ulepszenia (ceny z danych gry)."""
        if not rec.research and not rec.eco:
            c.label(t('res_none'), 1, 0, fg=THEME['quiet'], f=c.small, columnspan=6)
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
                c.label(pname(rec, pid), row, col0, fg=pcolor.get(pid, '#ccc'), f=c.bold, columnspan=2,
                        pady=(6 if row > 1 else 0, 0))
                row += 1
                if not done:
                    c.label('–', row, col0 + 1, fg=THEME['quiet'])
                    row += 1
                for tick, name in done:
                    c.label(fmt_time(tick, rec.tps), row, col0, fg=THEME['muted'], f=c.small, anchor='e', padx=(0, 6))
                    eco = CATALOG.is_eco_research(name)  # ekonomiczne (więcej R/E globalnie) – wyróżnione
                    c.label(f' {CATALOG.research(name) or name}', row, col0 + 1, fg='#7fd88f' if eco else THEME['text'],
                            image=iconcache.photo(CATALOG.icon_file(CATALOG.research_icon(name), c.icon_px)))
                    row += 1
                if done:
                    c.label(t('res_spent', v=fmt_res(req, pw)), row, col0 + 1, fg=THEME['quiet'], f=c.small)
                    row += 1

    def _build(self, rec, c):
        """Kolejność budowy (rekord 'army'): drużyny w dwóch kolumnach, gracz i typy jednostek/budynków w chwili
        pierwszego pojawienia się (bez tego, co gracz miał od startu)."""
        if not rec.army:
            c.label(t('build_none'), 1, 0, fg=THEME['quiet'], f=c.small, columnspan=6)
            return
        pcolor = self.colors(rec)
        rows = max(3, self.s.build_rows)
        orders = {pid: [(tk_, bp) for tk_, bp in rec.build_order(pid) if is_model(bp) and CATALOG.is_unit(bp)]
                  for pid in rec.players}
        # przewijanie: build_scroll = ile pozycji wstecz od najnowszych (0 = śledź najnowsze), wspólne dla graczy
        longest = max((len(o) for o in orders.values()), default=0)
        self.build_scroll = max(0, min(self.build_scroll, longest - rows))
        for side, team in enumerate(rec.teams()):
            col0 = side * 4  # kolumny: czas, nazwa, pasek przewijania, odstęp
            if side:
                c.label('', 1, 3, padx=(14, 14))
            row = 1
            for pid in team:
                c.label(pname(rec, pid), row, col0, fg=pcolor.get(pid, '#ccc'), f=c.bold, columnspan=2,
                        pady=(6 if row > 1 else 0, 0))
                row += 1
                order = orders.get(pid, [])
                if not order:
                    c.label('–', row, col0 + 1, fg=THEME['quiet'])
                    row += 1
                    continue
                end = max(min(rows, len(order)), len(order) - self.build_scroll)
                first = max(0, end - rows)
                if len(order) > rows:
                    c.vbar(row, col0 + 2, end - first, first, end - first, len(order))
                for tick, bp in order[first:end]:
                    struct_ = CATALOG.is_structure(bp)
                    c.label(fmt_time(tick, rec.tps), row, col0, fg=THEME['muted'], f=c.small, anchor='e', padx=(0, 6))
                    c.label(f' {CATALOG.squad(bp) or bp}', row, col0 + 1, fg='#c9b27c' if struct_ else THEME['text'],
                            image=iconcache.photo(CATALOG.icon_file(CATALOG.squad_icon(bp), c.icon_px)))
                    row += 1

    def _battles(self, rec, c):
        """Aktualna wartość armii (stan na teraz: żywe jednostki, faktycznie wydane – zakup, uzupełnienia, broń)
        każdego gracza i drużyny + wykres przewagi wartości armii, pod spodem największe bitwy (obrażenia i straty)."""
        pcolor = self.colors(rec)
        teams = rec.teams()
        colors = [pcolor.get(team[0], THEME['text']) if team else THEME['text'] for team in teams]
        names = [(rec.players.get(team[0], '?') + (f' +{len(team) - 1}' if len(team) > 1 else '')) if team else '?'
                 for team in teams]
        row = 1
        if rec.army:
            c.label(t('bat_army_now'), row, 0, fg='#c0c6cc', f=c.small, columnspan=2)
            c.label(t('res_r'), row, 2, fg=RES_COLORS[0], f=c.small, anchor='e', padx=(14, 0))
            c.label(t('res_e'), row, 3, fg=RES_COLORS[1], f=c.small, anchor='e', padx=(8, 0))
            row += 1
            for side, team in enumerate(teams):
                total = [0.0, 0.0]
                for pid in team:
                    v = rec.army_value(pid)[0]
                    total = [total[0] + v[0], total[1] + v[1]]
                    c.label(pname(rec, pid), row, 0, fg=pcolor.get(pid, THEME['text']), columnspan=2)
                    c.res(row, 2, *v)
                    row += 1
                if len(team) > 1:
                    c.label(t('bat_team_total'), row, 0, fg=THEME['muted'], f=c.small, columnspan=2)
                    c.res(row, 2, *total, f=c.bold)
                    row += 1
            full = [' · '.join(rec.players.get(p, '?') for p in team) for team in teams]
            c.label(t('eco_chart_army', a=full[0], b=full[1]), row, 0, fg='#c0c6cc', f=c.small, columnspan=7,
                    pady=(8, 0))
            row += 1
            c.chart(row, 7, rec.army_advantage(teams), colors, self.s.font_size * 46, self.s.font_size * 11,
                    fmt_time(rec.max_tick, rec.tps))
            row += 1
        fights = rec.battles()
        if not fights:
            c.label('–', row, 0, fg=THEME['quiet'])
            return
        c.label(t('bat_col_time'), row, 0, fg=THEME['quiet'], f=c.small, pady=(8, 0))
        for i in (0, 1):
            c.label(t('bat_col_dmg', n=names[i]), row, 1 + i, fg=THEME['quiet'], f=c.small, anchor='e', padx=(14, 0),
                    pady=(8, 0))
            c.res_heads(row, 3 + 2 * i, t('bat_col_lost', n=names[i]))
        row += 2
        for start, end, d, l in fights:
            win = 0 if sum(l[0]) < sum(l[1]) else 1  # drużyna z mniejszymi stratami – pogrubiona
            c.label(f'{fmt_time(start, rec.tps)}–{fmt_time(end, rec.tps)}', row, 0, fg='#c0c6cc')
            for i in (0, 1):
                c.label(fmt_num(d[i]), row, 1 + i, fg=colors[i], anchor='e', padx=(14, 0))
                c.res(row, 3 + 2 * i, *l[i], f=c.bold if i == win else None)
            row += 1


class Overlays:
    """Obie nakładki + skróty klawiszowe; podgląd woła render() i poll_hotkeys() w swojej pętli."""

    def __init__(self, master, settings: OverlaySettings):
        self.master, self.s = master, settings
        self.unit = self.summary = None
        self._rec = None
        self.hotkeys = Hotkeys()
        self.apply_hotkeys()

    def apply_hotkeys(self):
        keys = {'unit': self.s.key_unit, 'summary': self.s.key_summary, 'tab': self.s.key_tab,
                'tab_prev': self.s.key_tab_prev}
        keys.update({'tab:' + name: key for name, key in self.s.key_tabs.items() if key})
        self.hotkeys.set(keys)
        return self.hotkeys.failed

    def changed(self, rec):
        """Po zmianie ustawień: tworzy/zamyka okna, odświeża styl i treść."""
        self._rec = rec
        for attr, cls, on in (('unit', UnitOverlay, self.s.enabled), ('summary', SummaryOverlay, self.s.sum_enabled)):
            w = getattr(self, attr)
            if on and not w:
                setattr(self, attr, cls(self.master, self.s))
                if attr == 'summary':
                    self.summary.on_tab = self._set_tab
            elif not on and w:
                w.destroy()
                setattr(self, attr, None)
        for w in (self.unit, self.summary):
            if w:
                w.apply_window_style()
                w._last_cells = None
                w.render(rec)

    def _set_tab(self, name):
        self.s.sum_tab = name
        self.s.save()
        self.summary._last_cells = None
        self.summary.render(self._rec)

    def render(self, rec):
        self._rec = rec
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
            elif a in ('tab', 'tab_prev'):
                if not self.s.sum_enabled:
                    self.s.sum_enabled = True
                else:
                    tabs = visible_tabs(self.s)
                    i = tabs.index(current_tab(self.s))
                    self.s.sum_tab = tabs[(i + (1 if a == 'tab' else -1)) % len(tabs)]
            elif a.startswith('tab:'):  # skrót do konkretnej zakładki – pokazuje podsumowanie na tej zakładce
                self.s.sum_enabled = True
                if a[4:] in visible_tabs(self.s):
                    self.s.sum_tab = a[4:]
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
        self.configure(background=THEME['bg'])
        self.after(30, lambda: style_caption(self))
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
        self.v['build_rows'] = tk.IntVar(value=settings.build_rows)
        row(t('set_build_rows'), ttk.Spinbox(f, from_=3, to=30, width=5, textvariable=self.v['build_rows'],
                                             command=self._apply, state='readonly'))
        ttk.Label(f, text=t('set_tabs')).grid(row=r, column=0, sticky='nw', pady=3)
        tf = ttk.Frame(f)
        tf.grid(row=r, column=1, sticky='w')
        r += 1
        self.tab_vars = {}
        for i, name in enumerate(SUMMARY_TABS):
            var = self.tab_vars[name] = tk.BooleanVar(value=name not in settings.sum_tabs_off)
            ttk.Checkbutton(tf, text=t('tab_' + name), variable=var, command=self._apply).grid(
                row=i // 2, column=i % 2, sticky='w', padx=(0, 10))
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
                                         ('show_lost', t('chk_lost')), ('show_share', t('chk_share'))]):
            self.v[key] = tk.BooleanVar(value=getattr(settings, key))
            ttk.Checkbutton(cf, text=text, variable=self.v[key], command=self._apply).grid(row=i // 2, column=i % 2,
                                                                                           sticky='w', padx=(0, 10))
        section(t('set_sec_common'))
        self.v['font_size'] = tk.IntVar(value=settings.font_size)
        row(t('set_font'), ttk.Spinbox(f, from_=8, to=20, width=5, textvariable=self.v['font_size'],
                                       command=self._apply, state='readonly'))
        ttk.Label(f, text=t('set_drag_hint'), foreground=THEME['muted']).grid(row=r, column=0, columnspan=2, sticky='w')
        r += 1

        section(t('set_sec_keys'))
        none = t('key_none')
        for key, text in (('key_unit', t('key_unit')), ('key_summary', t('key_summary')), ('key_tab', t('key_tab')),
                          ('key_tab_prev', t('key_tab_prev'))):
            self.v[key] = tk.StringVar(value=getattr(settings, key) or none)
            row(text, self._combo(f, self.v[key], [none] + KEYS, width=10, command=self._apply_keys))
        # opcjonalne skróty do konkretnych zakładek (domyślnie brak) – zwinięte, żeby nie wydłużać okna
        self.tab_keys = {name: tk.StringVar(value=settings.key_tabs.get(name) or none) for name in SUMMARY_TABS}
        more = ttk.Frame(f)
        self.more_var = tk.BooleanVar(value=any(settings.key_tabs.values()))

        def toggle_more():
            if self.more_var.get():
                more.grid(row=more_row, column=0, columnspan=2, sticky='we')
            else:
                more.grid_remove()
        ttk.Checkbutton(f, text=t('key_tabs_more'), variable=self.more_var, command=toggle_more).grid(
            row=r, column=0, columnspan=2, sticky='w', pady=(4, 0))
        r += 1
        more_row = r
        r += 1
        for i, name in enumerate(SUMMARY_TABS):
            ttk.Label(more, text=t('key_tab_to', tab=t('tab_' + name))).grid(row=i, column=0, sticky='w', padx=(16, 10))
            self._combo(more, self.tab_keys[name], [none] + KEYS, width=10, command=self._apply_keys).grid(
                row=i, column=1, sticky='w', pady=1)
        toggle_more()
        self.key_status = ttk.Label(f, text='', foreground=THEME['error'])
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
        for key in ('key_unit', 'key_summary', 'key_tab', 'key_tab_prev'):
            val = self.v[key].get()
            setattr(self.s, key, val if val in KEYS else '')
        self.s.key_tabs = {name: var.get() for name, var in self.tab_keys.items() if var.get() in KEYS}
        self.s.save()
        self._show_key_status(self.apply_hotkeys())

    def _apply(self):
        s, v = self.s, self.v
        s.enabled = v['enabled'].get()
        s.sum_enabled = v['sum_enabled'].get()
        s.count = int(v['count'].get())
        s.sort_by = self.sorts.get(v['sort_by'].get(), 'dealt')
        s.window_s = self.windows.get(v['window_s'].get(), 0)
        for key in ('show_dealt', 'show_kills', 'show_lost', 'show_share', 'locked', 'sum_locked'):
            setattr(s, key, v[key].get())
        s.opacity = round(float(v['opacity'].get()), 2)
        s.sum_opacity = round(float(v['sum_opacity'].get()), 2)
        s.font_size = int(v['font_size'].get())
        s.build_rows = int(v['build_rows'].get())
        off = [name for name, var in self.tab_vars.items() if not var.get()]
        if len(off) == len(SUMMARY_TABS):  # co najmniej jedna zakładka zostaje włączona
            self.tab_vars[SUMMARY_TABS[0]].set(True)
            off.remove(SUMMARY_TABS[0])
        s.sum_tabs_off = off
        s.save()
        self.on_change()
