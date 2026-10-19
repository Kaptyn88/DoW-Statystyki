"""Analiza zrzutów sondy ekonomii (launcher --eco -> probe/logs/eco_*.bin).

Szuka w pamięci obiektu gracza (i obiektów, na które wskazuje) liczb float, które:
  - tylko rosną przez mecz        -> kandydaci na "zebrane zasoby łącznie" (rekwizycja / energia),
  - rosną i maleją w zakresie 0..50000 -> kandydaci na "stan konta".
Użycie: python eco_scan.py [plik.bin] [--top N] [--at pid:tick=wartość ...]
  --at 1000:2400=830  pokaż pola gracza 1000, które w ticku najbliższym 2400 mają wartość ~830 (odczyt z ekranu gry).
Format rekordu: patrz probe/src/recorder.cpp (EcoDump).
"""
import argparse
import collections
import glob
import os
import struct


def read_records(path):
    data = open(path, 'rb').read()
    i, out = 0, []
    while i + 24 <= len(data):
        if data[i:i + 4] != b'ECO1':
            raise ValueError(f'zły nagłówek w {i}')
        tick, pid, obj, n = struct.unpack_from('<iIQI', data, i + 4)
        i += 24
        body = data[i:i + n]
        i += n
        (k,) = struct.unpack_from('<I', data, i)
        i += 4
        subs = {}
        for _ in range(k):
            off, ptr = struct.unpack_from('<IQ', data, i)
            subs[off] = data[i + 12:i + 12 + 256]
            i += 12 + 256
        out.append((tick, pid, body, subs))
    return out


def fields(body, subs):
    """(nazwa pola, float) dla każdego 4-bajtowego słowa obiektu i obiektów podrzędnych."""
    for off in range(0, len(body) - 3, 4):
        yield f'+0x{off:x}', struct.unpack_from('<f', body, off)[0]
    for soff, sb in subs.items():
        for off in range(0, len(sb) - 3, 4):
            yield f'[+0x{soff:x}]+0x{off:x}', struct.unpack_from('<f', sb, off)[0]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('path', nargs='?')
    ap.add_argument('--top', type=int, default=25)
    ap.add_argument('--at', nargs='*', default=[])
    a = ap.parse_args()
    here = os.path.dirname(os.path.abspath(__file__))
    path = a.path or max(glob.glob(os.path.join(here, '..', 'probe', 'logs', 'eco_*.bin')), key=os.path.getmtime)
    recs = read_records(path)
    print(path, '- rekordów:', len(recs), '- gracze:', sorted({r[1] for r in recs}))

    series = collections.defaultdict(lambda: collections.defaultdict(list))  # pid -> pole -> [(tick, v)]
    for tick, pid, body, subs in recs:
        for name, v in fields(body, subs):
            series[pid][name].append((tick, v))

    for spec in a.at:  # porównanie z wartością odczytaną z ekranu gry
        who, _, val = spec.partition('=')
        pid, _, tick = who.partition(':')
        pid, tick, val = int(pid), int(tick), float(val)
        print(f'\n== gracz {pid}, tick ~{tick}: pola ~= {val}')
        for name, s in series[pid].items():
            t, v = min(s, key=lambda x: abs(x[0] - tick))
            if abs(v - val) <= max(1.0, abs(val) * 0.01):
                print(f'   {name:22} {v:.2f} (tick {t})')

    for pid in sorted(series):
        grow, acct = [], []
        for name, s in series[pid].items():
            vs = [v for _, v in s]
            if len(vs) < 4 or any(v != v or abs(v) > 1e7 for v in vs):  # NaN / śmieci
                continue
            if vs[-1] - vs[0] < 50 or min(vs) < 0:
                inc = False
            else:
                inc = all(b >= a - 1e-3 for a, b in zip(vs, vs[1:]))
            changes = sum(1 for a, b in zip(vs, vs[1:]) if a != b)
            if inc and changes >= len(vs) // 3:
                grow.append((vs[-1], name, vs))
            elif 0 <= min(vs) and max(vs) <= 50000 and changes >= len(vs) // 3 and \
                    any(b < a for a, b in zip(vs, vs[1:])) and any(b > a for a, b in zip(vs, vs[1:])):
                acct.append((max(vs), name, vs))
        print(f'\n== gracz {pid}: rosnące (kandydaci na "zebrane łącznie"): {len(grow)}')
        for last, name, vs in sorted(grow, reverse=True)[:a.top]:
            step = max(1, len(vs) // 6)
            print(f'   {name:22} ' + ' '.join(f'{v:9.1f}' for v in vs[::step]))
        print(f'== gracz {pid}: zmienne 0..50000 (kandydaci na "stan konta"): {len(acct)}')
        for mx, name, vs in sorted(acct, reverse=True)[:a.top]:
            step = max(1, len(vs) // 6)
            print(f'   {name:22} ' + ' '.join(f'{v:9.1f}' for v in vs[::step]))


if __name__ == '__main__':
    main()
