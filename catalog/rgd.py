"""Czytnik plików RGD (Relic Game Data, Dawn of War) – drzewo atrybutów z haszowanymi kluczami.

Plik: "Relic Chunky\\r\\n\\x1a\\0", u32 wersja, u32 platforma, potem bloki: char[4] typ, char[4] id, u32 wersja,
u32 rozmiar, u32 długość nazwy, nazwa. Blok DATA/AEGD: u32 suma kontrolna, u32 długość danych, potem tabela.
Tabela: u32 liczba dzieci, dzieci po 12 B (u32 hasz klucza, u32 typ, u32 offset), potem dane; offsety liczone od
początku danych tej tabeli. Typy: 0 float, 1 int, 2 bool (1 B), 3 string (ASCII, \\0), 4 wstring (UTF-16, \\0\\0),
100 tabela, 101 tabela-referencja (dziedziczenie w danych źródłowych; tu traktowana jak tabela).
Klucze: hasz Boba Jenkinsa (lookup2, initval 0) z nazwy klucza – nazwy odzyskujemy przez SŁOWNIK znanych kluczy.
"""
import struct

M = 0xFFFFFFFF


def _mix(a, b, c):
    a = (a - b - c) & M; a ^= c >> 13
    b = (b - c - a) & M; b ^= (a << 8) & M
    c = (c - a - b) & M; c ^= b >> 13
    a = (a - b - c) & M; a ^= c >> 12
    b = (b - c - a) & M; b ^= (a << 16) & M
    c = (c - a - b) & M; c ^= b >> 5
    a = (a - b - c) & M; a ^= c >> 3
    b = (b - c - a) & M; b ^= (a << 10) & M
    c = (c - a - b) & M; c ^= b >> 15
    return a, b, c


def jenkins(s, init=0):
    k = s.encode('ascii') if isinstance(s, str) else s
    a = b = 0x9E3779B9
    c = init
    n = len(k)
    i = 0
    while n - i >= 12:
        a = (a + k[i] + (k[i + 1] << 8) + (k[i + 2] << 16) + (k[i + 3] << 24)) & M
        b = (b + k[i + 4] + (k[i + 5] << 8) + (k[i + 6] << 16) + (k[i + 7] << 24)) & M
        c = (c + k[i + 8] + (k[i + 9] << 8) + (k[i + 10] << 16) + (k[i + 11] << 24)) & M
        a, b, c = _mix(a, b, c)
        i += 12
    c = (c + n) & M
    r = k[i:]
    ln = len(r)
    if ln >= 11: c = (c + (r[10] << 24)) & M
    if ln >= 10: c = (c + (r[9] << 16)) & M
    if ln >= 9: c = (c + (r[8] << 8)) & M
    if ln >= 8: b = (b + (r[7] << 24)) & M
    if ln >= 7: b = (b + (r[6] << 16)) & M
    if ln >= 6: b = (b + (r[5] << 8)) & M
    if ln >= 5: b = (b + r[4]) & M
    if ln >= 4: a = (a + (r[3] << 24)) & M
    if ln >= 3: a = (a + (r[2] << 16)) & M
    if ln >= 2: a = (a + (r[1] << 8)) & M
    if ln >= 1: a = (a + r[0]) & M
    a, b, c = _mix(a, b, c)
    return c


class Dictionary:
    """Hasz -> nazwa klucza. Nieznane klucze zostają jako '#%08x'."""

    def __init__(self, names=()):
        self.map = {}
        for n in names:
            self.add(n)

    def add(self, name):
        self.map[jenkins(name)] = name

    def name(self, h):
        return self.map.get(h, '#%08x' % h)


def _parse_table(buf, start, dic):
    n = struct.unpack_from('<I', buf, start)[0]
    data = start + 4 + 12 * n
    out = {}
    for i in range(n):
        h, typ, off = struct.unpack_from('<III', buf, start + 4 + 12 * i)
        p = data + off
        if typ == 0:
            v = struct.unpack_from('<f', buf, p)[0]
        elif typ == 1:
            v = struct.unpack_from('<i', buf, p)[0]
        elif typ == 2:
            v = buf[p] != 0
        elif typ == 3:
            v = buf[p:buf.index(b'\0', p)].decode('latin-1')
        elif typ == 4:
            e = p
            while buf[e:e + 2] != b'\0\0':
                e += 2
            v = buf[p:e].decode('utf-16le')
        elif typ in (100, 101):
            v = _parse_table(buf, p, dic)
        else:
            v = ('?type', typ)
        out[dic.name(h)] = v
    return out


def parse(data, dic=None):
    dic = dic or Dictionary()
    if not data.startswith(b'Relic Chunky\r\n\x1a\0'):
        raise ValueError('to nie jest Relic Chunky')
    p = 16 + 8
    while p < len(data):
        ctype, cid = data[p:p + 4], data[p + 4:p + 8]
        ver, size, nlen = struct.unpack_from('<III', data, p + 8)
        body = p + 20 + nlen
        if ctype == b'DATA' and cid == b'AEGD':
            # u32 suma kontrolna, u32 długość danych, potem tabela korzenia
            return _parse_table(data[body + 8:body + 8 + struct.unpack_from('<I', data, body + 4)[0]], 0, dic)
        p = body + size
    raise ValueError('brak bloku DATA/AEGD')
