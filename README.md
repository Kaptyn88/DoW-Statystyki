# DoW – statystyki powtórek (Dawn of War: Definitive Edition)

Statystyki oddziałów z powtórek **Dawn of War: Definitive Edition**, podobne do tych w powtórkach StarCrafta II.
Dla każdego oddziału liczy zadane obrażenia, zabite modele, otrzymane obrażenia i stracone modele, z podziałem na
bronie, granaty i zdolności (moce duszy Mrocznych Eldarów jako osobny wiersz). Dane pokazuje okno podglądu oraz
półprzezroczysta nakładka na grę. Po kliknięciu oddziału w grze widać jego statystyki.

![Nakładka podczas powtórki](viewer/screenshot_overlay_de.png)

*Unofficial replay statistics tool for Dawn of War: Definitive Edition (Steam). Works only while watching replays.*

## Pobranie i użycie (dla graczy)

1. Pobierz `DoW-Statystyki-<wersja>.zip` z zakładki **[Releases](../../releases)** i rozpakuj.
2. Uruchom **`Start.bat`**, w grze otwórz **Powtórki → powtórka → Odtwórz**.
3. Szczegóły: `INSTRUKCJA.txt` w paczce.

Wymagania: Windows 10/11 64-bit, DoW: Definitive Edition ze Steam (wersja 2.10.3.1). Nic więcej nie trzeba instalować.

## Jak to działa

- Plik powtórki `.rec` zawiera tylko komendy graczy, a gra liczy bitwę od nowa przy odtwarzaniu. Dlatego
  rejestrator (`dowrec.dll`) działa **w grze** podczas odtwarzania. Podpina się (MinHook) pod funkcję nakładania
  obrażeń (atakujący, ofiara, broń/zdolność), zmianę zdrowia i śmierć modelu, a adresy znajduje wzorcami bajtów.
  Zdarzenia zapisuje do `recordings/*.jsonl`.
- Launcher uruchamia grę i wstrzykuje rejestrator. **Pliki gry nie są modyfikowane.** Rejestrator działa tylko
  przy odtwarzaniu powtórek i sam wyłącza się w meczu na żywo. Do gier sieciowych uruchamiaj grę normalnie przez Steam.
- Podgląd i nakładka (Python/tkinter) czytają nagranie na bieżąco. Polskie nazwy jednostek i zdolności pochodzą
  z plików gry gracza (archiwa SGA, pliki RGD, `Engine.ucs`), zbieranych przy pierwszym uruchomieniu.

## Dla programistów

| Folder | Zawartość |
|---|---|
| `probe/` | rejestrator `recorder.cpp`, sonda diagnostyczna `probe.cpp`, launcher, `build.bat` (MSVC) |
| `viewer/` | podgląd `dow_viewer.py`, nakładka `overlay.py`, model danych `recmodel.py` |
| `catalog/` | czytniki SGA v2 i RGD, budowa katalogu nazw `build_catalog.py` |
| `package/` | paczka dla graczy: `make_package.py` (PyInstaller), `Start.bat`, `INSTRUKCJA.txt` |
| `analysis/` | skrypty analizy statycznej i diagnostyki |
| `NOTES.md` | wszystkie ustalenia: adresy, formaty, co jest potwierdzone, a co jest hipotezą |

Uruchamianie z kodu: `start.bat` (wymaga Visual Studio Build Tools i Pythona 3).
Budowa paczki: `.venv\Scripts\python package\make_package.py` (wymaga `pip install pyinstaller` w `.venv`).

Narzędzie nieoficjalne, niezwiązane z Relic Entertainment ani SEGA. Używa [MinHook](https://github.com/TsudaKageyu/minhook)
(licencja BSD, `third_party/minhook/LICENSE.txt`).
