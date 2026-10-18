"""Podgląd statystyk oddziałów z nagrań dowrec (Dawn of War: DE) – jak statystyki w powtórkach SC2.

Użycie:  python dow_viewer.py [plik.jsonl]
Bez argumentu otwiera najnowsze nagranie z folderu recordings i przełącza się na nowsze, gdy się pojawią.
Plik czytany jest na bieżąco (rejestrator zrzuca go co sekundę), więc podgląd może działać obok odtwarzanej powtórki.
Interfejs: polski / angielski / rosyjski (i18n.py), wybór w oknie; po zmianie okno uruchamia się ponownie.
"""
import glob
import os
import sys
import threading
import time
import tkinter as tk
from tkinter import filedialog, ttk

import i18n
import paths
import recmodel
from i18n import t
from overlay import Overlay, OverlaySettings, OverlaySettingsWindow
from recmodel import Recording

REC_DIR = paths.REC_DIR
PLAYER_COLORS = ['#2f6fdf', '#d9452b', '#2e9e4f', '#b8860b', '#8e44ad', '#16a085', '#c0392b', '#7f8c8d']
COLUMNS = [  # (id, klucz tekstu nagłówka, szerokość, wyrównanie)
    ('rank', None, 32, 'e'), ('unit', 'col_unit', 180, 'w'), ('player', 'col_player', 120, 'w'),
    ('dealt', 'col_dealt', 64, 'e'), ('share', 'col_share', 56, 'e'), ('kills', 'col_kills', 52, 'e'),
    ('taken', 'col_taken', 74, 'e'), ('lost', 'col_lost', 64, 'e'), ('ff', None, 48, 'e'),
]


def fmt_time(ticks, tps):
    s = int(ticks / tps)
    return f'{s // 60}:{s % 60:02d}'


def newest_recording():
    files = glob.glob(os.path.join(REC_DIR, '*.jsonl'))
    return max(files, key=os.path.getmtime) if files else None


class Viewer(tk.Tk):
    def __init__(self, path, follow_newest=None):
        super().__init__()
        self.title(t('title'))
        self.geometry('1260x700')
        self.minsize(1140, 520)
        ttk.Style(self).theme_use('clam')
        self.restart = None       # (plik, śledź najnowsze) przy zmianie języka – main() tworzy okno od nowa
        self.rec = None
        self.follow_newest = tk.BooleanVar(value=path is None if follow_newest is None else follow_newest)
        self.live = tk.BooleanVar(value=True)
        self.follow_selection = tk.BooleanVar(value=True)
        self._sel_seq = 0
        self.topmost = tk.BooleanVar(value=False)
        self.player_filter = tk.StringVar(value=t('all_players'))
        self.lang_var = tk.StringVar(value=i18n.LANGS[i18n.lang()])
        self.time_var = tk.DoubleVar(value=0)
        self.sort_col, self.sort_desc = 'dealt', True
        self.selected = None      # klucz zaznaczonego oddziału
        self._row_keys = {}       # iid wiersza -> klucz oddziału
        self.ov_settings = OverlaySettings.load()
        self.overlay = None
        self.ov_window = None
        self._build_ui()
        self.open(path or newest_recording())
        self._catalog_job = None
        if not os.path.exists(paths.CATALOG_PATH) or recmodel.CATALOG.outdated():
            self._build_catalog()
        self.after(1000, self._tick)
        if self.ov_settings.enabled:
            self.after(200, self._overlay_changed)

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        top = ttk.Frame(self, padding=(8, 6))
        top.pack(fill='x')
        ttk.Button(top, text=t('open'), command=self._choose_file).pack(side='left')
        ttk.Button(top, text=t('overlay_btn'), command=self._open_overlay_settings).pack(side='left', padx=(6, 0))
        ttk.Checkbutton(top, text=t('follow_newest'), variable=self.follow_newest).pack(side='left', padx=8)
        ttk.Checkbutton(top, text=t('follow_sel'), variable=self.follow_selection).pack(side='left')
        self.file_label = ttk.Label(top, text='', foreground='#555')
        self.file_label.pack(side='left', padx=4)
        ttk.Checkbutton(top, text=t('topmost'), variable=self.topmost,
                        command=lambda: self.attributes('-topmost', self.topmost.get())).pack(side='right')
        lang_box = ttk.Combobox(top, textvariable=self.lang_var, values=list(i18n.LANGS.values()),
                                state='readonly', width=9)
        lang_box.pack(side='right', padx=(0, 12))
        lang_box.bind('<<ComboboxSelected>>', lambda e: self._change_language())
        ttk.Label(top, text=t('language')).pack(side='right', padx=(12, 2))
        self.player_box = ttk.Combobox(top, textvariable=self.player_filter, state='readonly', width=22)
        self.player_box.pack(side='right', padx=(0, 12))
        ttk.Label(top, text=t('player')).pack(side='right', padx=(12, 2))
        self.player_box.bind('<<ComboboxSelected>>', lambda e: self.refresh())

        tbar = ttk.Frame(self, padding=(8, 0))
        tbar.pack(fill='x')
        ttk.Label(tbar, text=t('time')).pack(side='left')
        self.scale = ttk.Scale(tbar, from_=0, to=1, variable=self.time_var, command=self._on_scale)
        self.scale.pack(side='left', fill='x', expand=True, padx=6)
        self.time_label = ttk.Label(tbar, text='0:00 / 0:00', width=14)
        self.time_label.pack(side='left')
        ttk.Checkbutton(tbar, text=t('live'), variable=self.live, command=self.refresh).pack(side='left', padx=6)
        self.rec_status = tk.Label(tbar, text='', width=32, anchor='w')
        self.rec_status.pack(side='left')

        body = ttk.Frame(self)
        body.pack(fill='both', expand=True, padx=8, pady=8)
        body.columnconfigure(0, weight=3, minsize=700)  # tabela mieści wszystkie kolumny
        body.columnconfigure(1, weight=2, minsize=420)
        body.rowconfigure(0, weight=1)

        left = ttk.Frame(body)
        self.tree = ttk.Treeview(left, columns=[c[0] for c in COLUMNS], show='headings', selectmode='browse')
        for cid, key, width, anchor in COLUMNS:
            head = t(key) if key else ('#' if cid == 'rank' else 'FF')
            self.tree.heading(cid, text=head, command=lambda c=cid: self._sort_by(c))
            self.tree.column(cid, width=width, anchor=anchor, stretch=cid == 'unit')
        sb = ttk.Scrollbar(left, orient='vertical', command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side='left', fill='both', expand=True)
        sb.pack(side='left', fill='y')
        self.tree.bind('<<TreeviewSelect>>', self._on_select)
        left.grid(row=0, column=0, sticky='nsew')

        right = ttk.Frame(body, padding=(10, 0))
        self.d_title = ttk.Label(right, text=t('pick_squad'), font=('Segoe UI', 13, 'bold'))
        self.d_title.pack(anchor='w')
        self.d_sub = ttk.Label(right, text='', foreground='#555')
        self.d_sub.pack(anchor='w', pady=(0, 6))
        self.d_cards = ttk.Frame(right)
        self.d_cards.pack(fill='x')
        self.cards = {}
        for i, key in enumerate(('dealt', 'kills', 'rank', 'taken', 'lost', 'dpm')):
            f = ttk.Frame(self.d_cards, padding=(0, 2, 16, 6))
            f.grid(row=i // 3, column=i % 3, sticky='w')
            ttk.Label(f, text=t('card_' + key), foreground='#666').pack(anchor='w')
            v = ttk.Label(f, text='–', font=('Segoe UI', 15, 'bold'))
            v.pack(anchor='w')
            self.cards[key] = v
        ttk.Label(right, text=t('timeline'), foreground='#666').pack(anchor='w', pady=(6, 0))
        self.canvas = tk.Canvas(right, height=90, background='white', highlightthickness=1, highlightbackground='#ddd')
        self.canvas.pack(fill='x', pady=(2, 8))
        self.canvas.bind('<Configure>', lambda e: self._draw_timeline())
        self.d_text = tk.Text(right, height=18, wrap='none', relief='flat', background=self.cget('background'),
                              font=('Consolas', 9))
        self.d_text.pack(fill='both', expand=True)
        self.d_text.tag_configure('h', font=('Segoe UI', 10, 'bold'))
        right.grid(row=0, column=1, sticky='nsew')

        self.status = ttk.Label(self, text='', foreground='#555', padding=(8, 0, 8, 4))
        self.status.pack(fill='x')

    def _change_language(self):
        code = next((c for c, n in i18n.LANGS.items() if n == self.lang_var.get()), 'en')
        if code == i18n.lang():
            return
        i18n.save(code)
        # stan potrzebny nowemu oknu – odczytany przed destroy(), potem zmienne Tk już nie działają
        self.restart = (self.rec.path if self.rec else None, self.follow_newest.get())
        self.destroy()

    # ------------------------------------------------------------------ dane
    def open(self, path):
        if not path:
            self.file_label.configure(text=t('no_recordings'))
            return
        self.rec = Recording(path)
        self.selected = None
        self._sel_seq = 0
        self.file_label.configure(text=os.path.basename(path))
        self.player_box.configure(values=[t('all_players')] + list(self.rec.players.values()))
        self.player_filter.set(t('all_players'))
        if self.ov_window and self.ov_window.winfo_exists():
            self.ov_window.set_players(list(self.rec.players.values()))
        self.refresh()

    # ------------------------------------------------------------------ katalog nazw (pierwsze uruchomienie)
    def _build_catalog(self):
        """Buduje catalog.json z plików gry w tle (ok. 20 s); do tego czasu widać nazwy techniczne."""
        job = {'done': False, 'error': None}

        def work():
            try:
                import build_catalog
                build_catalog.build(out=paths.CATALOG_PATH)
            except Exception as e:  # brak gry, uszkodzone archiwum – podgląd działa dalej bez nazw z gry
                job['error'] = str(e)
            job['done'] = True

        self._catalog_job = job
        threading.Thread(target=work, daemon=True).start()
        self.after(500, self._catalog_wait)

    def _catalog_wait(self):
        job = self._catalog_job
        if not job['done']:
            self.status.configure(text=t('catalog_building'))
            self.after(500, self._catalog_wait)
            return
        if job['error']:
            self.status.configure(text=t('catalog_error', err=job['error']))
        else:
            recmodel.CATALOG.reload()
            self.status.configure(text=t('catalog_ready'))
            self.refresh()

    def _choose_file(self):
        p = filedialog.askopenfilename(initialdir=REC_DIR, filetypes=[(t('filetype'), '*.jsonl')])
        if p:
            self.follow_newest.set(False)
            self.open(p)

    def _apply_game_selection(self):
        """Gdy w grze zmieniło się zaznaczenie – wybierz ten oddział w podglądzie (pierwszy znany z zaznaczonych)."""
        rec = self.rec
        if not self.follow_selection.get() or rec.selection_seq == self._sel_seq:
            return
        self._sel_seq = rec.selection_seq
        known = [k for k in rec.selection if k in rec.units]
        if known:
            self.selected = known[0]

    def _tick(self):
        try:
            if self.follow_newest.get():
                n = newest_recording()
                if n and (not self.rec or os.path.normcase(n) != os.path.normcase(self.rec.path)):
                    self.open(n)
            if self.rec and self.rec.poll():
                self._apply_game_selection()
                self.player_box.configure(values=[t('all_players')] + list(self.rec.players.values()))
                self.refresh()
            elif self.rec:
                self._update_rec_status()
            if self.overlay:
                self.overlay.render(self.rec)
        finally:
            self.after(1000, self._tick)

    # ------------------------------------------------------------------ nakładka
    def _open_overlay_settings(self):
        if self.ov_window and self.ov_window.winfo_exists():
            self.ov_window.lift()
            return
        players = list(self.rec.players.values()) if self.rec else []
        self.ov_window = OverlaySettingsWindow(self, self.ov_settings, players, self._overlay_changed)

    def _overlay_changed(self):
        if self.ov_settings.enabled and not self.overlay:
            self.overlay = Overlay(self, self.ov_settings)
        elif not self.ov_settings.enabled and self.overlay:
            self.overlay.destroy()
            self.overlay = None
        if self.overlay:
            self.overlay.apply_window_style()
            self.overlay.render(self.rec)

    def _pid_filter(self):
        name = self.player_filter.get()
        for pid, n in (self.rec.players.items() if self.rec else []):
            if n == name:
                return pid
        return None

    def _current_tick(self):
        if not self.rec:
            return 0
        return self.rec.max_tick if self.live.get() else int(self.time_var.get())

    def _on_scale(self, _):
        if self.live.get():
            self.live.set(False)
        self.refresh()

    def _sort_by(self, col):
        if col in ('rank', 'share'):
            col = 'dealt'
        self.sort_desc = not self.sort_desc if col == self.sort_col else col not in ('unit', 'player')
        self.sort_col = col
        self.refresh()

    def _on_select(self, _):
        sel = self.tree.selection()
        if sel:
            self.selected = self._row_keys.get(sel[0])
            self._show_detail()

    # ------------------------------------------------------------------ odświeżanie
    def refresh(self):
        if not self.rec:
            return
        rec = self.rec
        self.scale.configure(to=max(1, rec.max_tick))
        tick = self._current_tick()
        if self.live.get():
            self.time_var.set(tick)
        self.time_label.configure(text=f'{fmt_time(tick, rec.tps)} / {fmt_time(rec.max_tick, rec.tps)}')
        self._update_rec_status()
        self.stats = st = rec.stats(tick)
        pid = self._pid_filter()
        total = st.total_dealt(pid) or 1
        ranking = st.ranking(pid)
        pcolor = {p: PLAYER_COLORS[i % len(PLAYER_COLORS)] for i, p in enumerate(sorted(rec.players))}

        def val(k, col):
            c = st.S[k]
            return {'unit': rec.unit_label(k).lower(), 'player': rec.players.get(rec.units.get(k, {}).get('pid'), '?').lower(),
                    'dealt': c['dealt'], 'kills': c['kills'], 'taken': c['taken'], 'lost': c['lost'], 'ff': c['ff']}[col]

        rows = sorted(ranking, key=lambda k: val(k, self.sort_col), reverse=self.sort_desc)
        self.tree.delete(*self.tree.get_children())
        self._row_keys.clear()
        for p, color in pcolor.items():
            self.tree.tag_configure(f'p{p}', foreground=color)
        for k in rows:
            c = st.S[k]
            p = rec.units.get(k, {}).get('pid')
            iid = self.tree.insert('', 'end', tags=(f'p{p}',), values=(
                ranking.index(k) + 1, rec.unit_label(k), rec.players.get(p, '?'), f"{c['dealt']:.0f}",
                f"{100 * c['dealt'] / total:.1f}%", c['kills'], f"{c['taken']:.0f}", c['lost'],
                f"{c['ff']:.0f}" if c['ff'] else ''))
            self._row_keys[iid] = k
            if k == self.selected:
                self.tree.selection_set(iid)
                self.tree.see(iid)
        self.status.configure(text=t('status_line', replay=rec.meta.get('replay', '?'), n=len(rec.events),
                                     players=', '.join(rec.players.values())))
        self._show_detail()

    def _update_rec_status(self):
        """Nagranie trwa, jeśli plik był modyfikowany w ostatnich sekundach (rejestrator dopisuje zegar co ~1 s)."""
        try:
            recording = time.time() - os.path.getmtime(self.rec.path) < 5
        except OSError:
            recording = False
        if recording:
            self.rec_status.configure(text=t('recording'), fg='#1e8e3e')
        else:
            # rejestrator nie odróżnia pauzy od końca powtórki – oba wyglądają jak brak nowych ticków
            self.rec_status.configure(text=t('no_data'), fg='#888')

    def _show_detail(self):
        rec, k = self.rec, self.selected
        if not rec or k is None:
            return
        st = self.stats
        c = st.S[k]
        u = rec.units.get(k, {})
        pid = u.get('pid')
        self.d_title.configure(text=rec.unit_label(k))
        r_all, n_all = st.rank_of(k)
        r_own, n_own = st.rank_of(k, pid)
        self.d_sub.configure(text=t('detail_sub', player=rec.players.get(pid, '?'), bp=u.get('bp', '?'),
                                    n=len(u.get('ents', ()))))
        tl = st.timeline.get(k, {})
        if tl:
            first = min(tl) * 30
            active_min = max(0.5, (self._current_tick() / rec.tps - first) / 60)
            dpm = c['dealt'] / active_min
        else:
            dpm = 0
        self.cards['dealt'].configure(text=f"{c['dealt']:.0f}")
        self.cards['kills'].configure(text=str(c['kills']))
        self.cards['rank'].configure(text=t('rank_val', r=r_all, n=n_all, ro=r_own, no=n_own) if r_all else '–')
        self.cards['taken'].configure(text=f"{c['taken']:.0f}")
        self.cards['lost'].configure(text=str(c['lost']))
        self.cards['dpm'].configure(text=f'{dpm:.0f}')

        tx = self.d_text
        tx.configure(state='normal')
        tx.delete('1.0', 'end')
        tx.insert('end', t('h_weapons') + '\n', 'h')
        for w, hp in st.weap[k].most_common(8):
            tx.insert('end', f'  {st.weapon_name(w)[:44]:<44} {hp:>8.0f}\n')
        tx.insert('end', '\n' + t('h_victims') + '\n', 'h')
        for vk, hp in st.victims[k].most_common(6):
            tx.insert('end', f'  {rec.unit_label(vk)[:44]:<44} {hp:>8.0f}\n')
        tx.insert('end', '\n' + t('h_attackers') + '\n', 'h')
        for ak, hp in st.attackers[k].most_common(6):
            tx.insert('end', f'  {rec.unit_label(ak)[:44]:<44} {hp:>8.0f}\n')
        if c['ff']:
            tx.insert('end', '\n' + t('ff_line', v=f"{c['ff']:.0f}") + '\n')
        nominal = c['nominal']
        if nominal > c['dealt'] * 1.05:
            tx.insert('end', '\n' + t('nominal', v=f'{nominal:.0f}') + '\n')
        tx.configure(state='disabled')
        self._draw_timeline()

    def _draw_timeline(self):
        cv = self.canvas
        cv.delete('all')
        rec, k = self.rec, self.selected
        if not rec or k is None or not hasattr(self, 'stats'):
            return
        w, h = cv.winfo_width(), cv.winfo_height()
        nb = max(1, rec.max_tick // (30 * rec.tps) + 1)
        tl = self.stats.timeline.get(k, {})
        peak = max(tl.values(), default=0) or 1
        bw = w / nb
        color = PLAYER_COLORS[sorted(rec.players).index(rec.units[k]['pid']) % len(PLAYER_COLORS)] \
            if k in rec.units and rec.units[k]['pid'] in rec.players else '#555'
        for b, hp in tl.items():
            bh = (h - 14) * hp / peak
            cv.create_rectangle(b * bw + 1, h - 12 - bh, (b + 1) * bw - 1, h - 12, fill=color, outline='')
        x = w * self._current_tick() / max(1, rec.max_tick)
        cv.create_line(x, 0, x, h - 12, fill='#999', dash=(2, 2))
        for m in range(0, int(rec.max_tick / rec.tps / 60) + 1, 2):
            xm = w * m * 60 * rec.tps / max(1, rec.max_tick)
            cv.create_text(xm + 2, h - 6, text=f'{m}:00', anchor='w', fill='#888', font=('Segoe UI', 7))


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else None
    i18n.load()
    follow = None
    while True:
        v = Viewer(path, follow)
        v.mainloop()
        if not v.restart:
            break
        # po zmianie języka: nowe okno, ten sam plik; teksty z katalogu i nakładki w nowym języku
        path, follow = v.restart


if __name__ == '__main__':
    main()
