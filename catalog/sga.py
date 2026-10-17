"""Czytnik archiwów SGA v2 z Dawn of War: Definitive Edition (tylko odczyt).

Układ (ustalony na DXP3Data.sga, 2026-10-17):
  0x00 "_ARCHIVE", u32 wersja=2, 16 B MD5 narzędzia, 64 wchar nazwa archiwum, 16 B MD5 nagłówka,
  0xAC u32 rozmiar nagłówka danych, 0xB0 u32 początek danych plików
  0xB4 nagłówek spisu (offsety względem 0xB4): u32+u16 dyski wirtualne, foldery, pliki, napisy
  dysk wirtualny 138 B: char[64] ścieżka, char[64] nazwa, u16 pierwszy/ostatni folder, pierwszy/ostatni plik, korzeń
  folder 12 B: u32 nazwa (pełna ścieżka), u16 podfoldery od/do, pliki od/do
  plik 20 B: u32 nazwa, u32 flagi (kompresja), u32 offset danych, u32 rozmiar spakowany, u32 rozmiar
"""
import struct
import zlib

TOC = 0xB4


class SgaArchive:
    def __init__(self, path):
        self.path = path
        self.f = open(path, 'rb')
        head = self.f.read(TOC + 24)
        if head[:8] != b'_ARCHIVE' or struct.unpack_from('<I', head, 8)[0] != 2:
            raise ValueError(f'{path}: to nie jest SGA v2')
        hdr_size, self.data_off = struct.unpack_from('<II', head, 0xAC)
        (vd_off, vd_n, fo_off, fo_n, fi_off, fi_n, st_off, st_n) = struct.unpack_from('<IHIHIHIH', head, TOC)
        self.f.seek(TOC)
        toc = self.f.read(hdr_size)
        self._toc = toc
        self._st_off = st_off

        def name(off):
            end = toc.index(b'\0', st_off + off)
            return toc[st_off + off:end].decode('ascii', 'replace')

        self.folders = []
        for i in range(fo_n):
            n, sub0, sub1, f0, f1 = struct.unpack_from('<IHHHH', toc, fo_off + 12 * i)
            self.folders.append((name(n), f0, f1))
        self.files = {}  # pełna ścieżka (małe litery, '\\') -> (flagi, offset, spakowany, rozmiar)
        raw = [struct.unpack_from('<IIIII', toc, fi_off + 20 * i) for i in range(fi_n)]
        for fname, f0, f1 in self.folders:
            for i in range(f0, f1):
                n, flags, off, csize, size = raw[i]
                full = (fname + '\\' + name(n)) if fname else name(n)
                self.files[full.lower()] = (flags, off, csize, size)

    def list(self, prefix=''):
        prefix = prefix.lower()
        return [p for p in self.files if p.startswith(prefix)]

    def read(self, path):
        flags, off, csize, size = self.files[path.lower()]
        self.f.seek(self.data_off + off)
        data = self.f.read(csize)
        if csize != size:
            data = zlib.decompress(data)
        return data

    def close(self):
        self.f.close()


if __name__ == '__main__':
    import sys
    a = SgaArchive(sys.argv[1])
    files = a.list(sys.argv[2] if len(sys.argv) > 2 else '')
    print(len(a.folders), 'folderów,', len(a.files), 'plików,', len(files), 'pasujących')
    for p in files[:15]:
        print(' ', p, a.files[p][3])
    if files:
        d = a.read(files[0])
        print('pierwszy plik:', len(d), 'B', d[:48])
