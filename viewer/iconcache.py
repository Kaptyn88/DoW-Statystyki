"""Pamięć podręczna obrazków ikon dla Tk (PhotoImage musi żyć, dopóki widget go wyświetla)."""
import tkinter as tk

_cache = {}


def photo(path):
    """PhotoImage dla pliku PNG albo None (brak ikony / błąd odczytu)."""
    if not path:
        return None
    img = _cache.get(path)
    if img is None:
        try:
            img = _cache[path] = tk.PhotoImage(file=path)
        except tk.TclError:
            return None
    return img


def clear():
    """Po utworzeniu nowego okna głównego (zmiana języka) stare obrazki należą do zamkniętego interpretera Tk."""
    _cache.clear()
