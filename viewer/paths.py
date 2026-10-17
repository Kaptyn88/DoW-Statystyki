"""Ścieżki podglądu: w projekcie (python viewer/dow_viewer.py) i w paczce (Podglad.exe zbudowany PyInstallerem).

Projekt: <projekt>/recordings, <projekt>/catalog/catalog.json, <projekt>/viewer/settings.json
Paczka:  obok Podglad.exe – recordings/, catalog/catalog.json, settings.json
"""
import os
import sys

FROZEN = getattr(sys, 'frozen', False)
ROOT = (os.path.dirname(sys.executable) if FROZEN
        else os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')))
REC_DIR = os.path.join(ROOT, 'recordings')
CATALOG_PATH = os.path.join(ROOT, 'catalog', 'catalog.json')
SETTINGS_PATH = os.path.join(ROOT, 'settings.json') if FROZEN else os.path.join(ROOT, 'viewer', 'settings.json')

# moduły katalogu (catalog/build_catalog.py, sga.py, rgd.py) – w paczce są wbudowane w exe
if not FROZEN:
    sys.path.insert(0, os.path.join(ROOT, 'catalog'))
