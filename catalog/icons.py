"""Ikony jednostek z plików gry: TGA (art/ui/ingame/<rasa>_icons/<nazwa>.tga, 64x64) -> małe PNG dla podglądu.

Czysty Python (zlib), bez dodatkowych bibliotek: odczyt TGA (typ 2 bez kompresji / 10 RLE, 24/32 bity),
zmniejszenie średnią z bloków (box filter) i zapis PNG RGBA.
"""
import struct
import zlib

SIZES = (20, 26, 32)  # rozmiary w pikselach; nakładka dobiera najbliższy do wielkości tekstu


def read_tga(data):
    """-> (szerokość, wysokość, piksele RGBA wierszami od góry)."""
    id_len, cmap_type, img_type = data[0], data[1], data[2]
    w, h, bpp, desc = struct.unpack_from('<HHBB', data, 12)
    if cmap_type != 0 or img_type not in (2, 10) or bpp not in (24, 32):
        raise ValueError(f'nieobsługiwany TGA (typ {img_type}, {bpp} bit)')
    px = bpp // 8
    p = 18 + id_len
    n = w * h
    raw = bytearray()
    if img_type == 2:
        raw = data[p:p + n * px]
    else:  # RLE
        while len(raw) < n * px:
            hdr = data[p]; p += 1
            count = (hdr & 0x7F) + 1
            if hdr & 0x80:
                raw += data[p:p + px] * count; p += px
            else:
                raw += data[p:p + count * px]; p += count * px
    rows = []
    for y in range(h):
        row = bytearray()
        for x in range(w):
            i = (y * w + x) * px
            b, g, r = raw[i], raw[i + 1], raw[i + 2]
            a = raw[i + 3] if px == 4 else 255
            row += bytes((r, g, b, a))
        rows.append(row)
    if not desc & 0x20:  # domyślnie TGA zapisuje wiersze od dołu
        rows.reverse()
    return w, h, rows


def _rgb565(c):
    return ((c >> 11) & 31) * 255 // 31, ((c >> 5) & 63) * 255 // 63, (c & 31) * 255 // 31


def read_rtx(data, max_size=64):
    """Tekstura Definitive Edition (.rtx, Relic Chunky FOLDTXTR): DATAATTR = (format, szer., wys., liczba mipmap),
    DATADATA = wszystkie mipmapy DXT5 od największej, bez nagłówków (format 11; np. 128x128 i 8 mipmap = 21872 B).
    Dekodujemy pierwszą mipmapę nie większą niż max_size -> (szer., wys., wiersze RGBA)."""
    i = data.find(b'DATAATTR')
    if i < 0:
        raise ValueError('brak DATAATTR')
    _, _, nl = struct.unpack_from('<III', data, i + 8)
    fmt, w, h, mips = struct.unpack_from('<IIII', data, i + 20 + nl)
    if fmt != 11:
        raise ValueError(f'nieobsługiwany format rtx {fmt}')
    j = data.find(b'DATADATA')
    _, size, nl = struct.unpack_from('<III', data, j + 8)
    p = j + 20 + nl
    for _ in range(mips):  # pomijamy większe mipmapy
        if w <= max_size and h <= max_size:
            break
        p += max(1, (w + 3) // 4) * max(1, (h + 3) // 4) * 16
        w, h = max(1, w // 2), max(1, h // 2)
    bw, bh = max(1, (w + 3) // 4), max(1, (h + 3) // 4)
    px = [[(0, 0, 0, 0)] * (bw * 4) for _ in range(bh * 4)]
    for by in range(bh):
        for bx in range(bw):
            a0, a1 = data[p], data[p + 1]
            abits = int.from_bytes(data[p + 2:p + 8], 'little')
            alpha = [a0, a1] + ([((6 - k) * a0 + (k + 1) * a1) // 7 for k in range(6)] if a0 > a1 else
                                [((4 - k) * a0 + (k + 1) * a1) // 5 for k in range(4)] + [0, 255])
            c0, c1, cbits = struct.unpack_from('<HHI', data, p + 8)
            r0, r1 = _rgb565(c0), _rgb565(c1)
            cols = [r0, r1, tuple((2 * x + y) // 3 for x, y in zip(r0, r1)), tuple((x + 2 * y) // 3 for x, y in zip(r0, r1))]
            for k in range(16):
                r, g, b = cols[(cbits >> (2 * k)) & 3]
                px[by * 4 + k // 4][bx * 4 + k % 4] = (r, g, b, alpha[(abits >> (3 * k)) & 7])
            p += 16
    rows = [bytearray(b for x in range(w) for b in px[y][x]) for y in range(h)]
    return w, h, rows


def resize(w, h, rows, size):
    """Zmniejszenie do size x size średnią z bloków (z uwzględnieniem przezroczystości)."""
    out = []
    for oy in range(size):
        y0, y1 = oy * h // size, max(oy * h // size + 1, (oy + 1) * h // size)
        row = bytearray()
        for ox in range(size):
            x0, x1 = ox * w // size, max(ox * w // size + 1, (ox + 1) * w // size)
            r = g = b = a = cnt = 0
            for y in range(y0, y1):
                src = rows[y]
                for x in range(x0, x1):
                    i = x * 4
                    pa = src[i + 3]
                    r += src[i] * pa; g += src[i + 1] * pa; b += src[i + 2] * pa; a += pa; cnt += 1
            row += bytes((r // a, g // a, b // a, a // cnt)) if a else b'\0\0\0\0'
        out.append(row)
    return out


def write_png(path, rows):
    h, w = len(rows), len(rows[0]) // 4

    def chunk(tag, body):
        return struct.pack('>I', len(body)) + tag + body + struct.pack('>I', zlib.crc32(tag + body) & 0xFFFFFFFF)

    raw = b''.join(b'\0' + bytes(r) for r in rows)
    png = (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 6, 0, 0, 0))
           + chunk(b'IDAT', zlib.compress(raw, 9)) + chunk(b'IEND', b''))
    with open(path, 'wb') as f:
        f.write(png)


def file_stem(icon):
    """'eldar_icons/HG_harlequin_icon' -> 'eldar_icons__hg_harlequin_icon'."""
    return icon.lower().replace('/', '__').replace('\\', '__')
