"""Składa paczkę dla innych graczy: dist/DoW-Statystyki-<wersja>.zip (bez kompilatora i Pythona u odbiorcy).

Użycie (z katalogu projektu):  .venv\\Scripts\\python package\\make_package.py [wersja]
Wymaga: MSVC Build Tools (probe\\build.bat) i PyInstaller w .venv.

Zawartość:
  Start.bat, INSTRUKCJA.txt / INSTRUCTIONS_EN.txt / INSTRUKCIYA_RU.txt, Podglad.exe (podgląd + nakładka + budowa katalogu nazw),
  bin\\dowrec.dll, bin\\dowprobe_launcher.exe, LICENCJE\\MinHook.txt
Nie zawiera danych gry: katalog nazw buduje się z plików gry odbiorcy przy pierwszym uruchomieniu.
"""
import os
import shutil
import subprocess
import sys
import zipfile

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
PKG = os.path.join(ROOT, 'package')
DIST = os.path.join(ROOT, 'dist')
WORK = os.path.join(ROOT, 'build', 'pyinstaller')
NAME = 'DoW-Statystyki'


def run(cmd, **kw):
    print('>', ' '.join(cmd) if isinstance(cmd, list) else cmd)
    subprocess.run(cmd, check=True, cwd=ROOT, **kw)


ARGS = [a for a in sys.argv[1:] if not a.startswith('--')]
NO_BUILD = '--no-build' in sys.argv  # bez kompilacji MSVC (użyj probe/bin; np. gdy gra trzyma dowrec.dll)


def version():
    if ARGS:
        return ARGS[0]
    try:
        return subprocess.run(['git', 'describe', '--tags', '--always', '--dirty'], cwd=ROOT, capture_output=True,
                              text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return 'dev'


def main():
    ver = version()
    # 1. DLL rejestratora i launcher (MSVC, statyczny runtime /MT – odbiorca nie potrzebuje redystrybucji VC++)
    if not NO_BUILD:
        run(['cmd', '/c', os.path.join('probe', 'build.bat')])
    # 2. Podglad.exe: jeden plik, bez konsoli; moduły katalogu (build_catalog, sga, rgd) wbudowane
    pyinstaller = os.path.join(ROOT, '.venv', 'Scripts', 'pyinstaller.exe')
    run([pyinstaller, '--noconfirm', '--clean', '--onefile', '--windowed', '--name', 'Podglad',
         '--paths', 'viewer', '--paths', 'catalog',
         '--hidden-import', 'build_catalog', '--hidden-import', 'sga', '--hidden-import', 'rgd', '--hidden-import', 'icons',
         '--distpath', os.path.join(WORK, 'dist'), '--workpath', os.path.join(WORK, 'work'),
         '--specpath', WORK, os.path.join('viewer', 'dow_viewer.py')])
    # 3. złożenie folderu paczki
    out = os.path.join(DIST, NAME)
    shutil.rmtree(out, ignore_errors=True)
    os.makedirs(os.path.join(out, 'bin'))
    os.makedirs(os.path.join(out, 'LICENCJE'))
    shutil.copy2(os.path.join(WORK, 'dist', 'Podglad.exe'), out)
    for f in ('dowrec.dll', 'dowprobe_launcher.exe'):
        shutil.copy2(os.path.join(ROOT, 'probe', 'bin', f), os.path.join(out, 'bin'))
    for doc in ('INSTRUKCJA.txt', 'INSTRUCTIONS_EN.txt', 'INSTRUKCIYA_RU.txt'):  # PL / EN / RU
        shutil.copy2(os.path.join(PKG, doc), out)
    with open(os.path.join(PKG, 'Start.bat'), 'rb') as src:  # CRLF wymagane przez cmd
        data = src.read().replace(b'\r\n', b'\n').replace(b'\n', b'\r\n')
    with open(os.path.join(out, 'Start.bat'), 'wb') as dst:
        dst.write(data)
    shutil.copy2(os.path.join(ROOT, 'third_party', 'minhook', 'LICENSE.txt'), os.path.join(out, 'LICENCJE', 'MinHook.txt'))
    with open(os.path.join(out, 'WERSJA.txt'), 'w', encoding='utf-8') as f:
        f.write(f'{NAME} {ver}\n')
    # 4. zip
    zpath = os.path.join(DIST, f'{NAME}-{ver}.zip')
    with zipfile.ZipFile(zpath, 'w', zipfile.ZIP_DEFLATED) as z:
        for base, _, files in os.walk(out):
            for fn in files:
                full = os.path.join(base, fn)
                z.write(full, os.path.relpath(full, DIST))
    print('gotowe:', zpath, f'({os.path.getsize(zpath) / 1e6:.1f} MB)')


if __name__ == '__main__':
    main()
