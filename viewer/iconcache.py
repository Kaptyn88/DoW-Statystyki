"""Pamięć podręczna obrazków ikon dla Tk (PhotoImage musi żyć, dopóki widget go wyświetla)."""
import tkinter as tk
from math import gcd

_cache = {}


def photo(path, size=None):
    """PhotoImage dla PNG, opcjonalnie przeskalowany i zapamiętany, albo None przy braku ikony."""
    if not path:
        return None
    img = _cache.get(path)
    if img is None:
        try:
            img = _cache[path] = tk.PhotoImage(file=path)
        except tk.TclError:
            return None
    if img is None or size is None or (img.width() == size and img.height() == size):
        return img
    key = (path, size)
    scaled = _cache.get(key)
    if scaled is None:
        gx, gy = gcd(size, img.width()), gcd(size, img.height())
        scaled = img.zoom(size // gx, size // gy).subsample(img.width() // gx, img.height() // gy)
        _cache[key] = scaled
    return scaled


def clear():
    """Po utworzeniu nowego okna głównego (zmiana języka) stare obrazki należą do zamkniętego interpretera Tk."""
    _cache.clear()
