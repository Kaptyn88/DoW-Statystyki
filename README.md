# DoW – statystyki powtórek (Dawn of War: Definitive Edition)

Statystyki oddziałów z powtórek **Dawn of War: Definitive Edition**, podobne do tych w powtórkach StarCrafta II.
Dla każdego oddziału liczy zadane obrażenia, zabite modele, otrzymane obrażenia i stracone modele, z podziałem na
bronie, granaty i zdolności (moce duszy Mrocznych Eldarów jako osobny wiersz). Dane pokazuje okno podglądu oraz
półprzezroczysta nakładka na grę. Po kliknięciu oddziału w grze widać jego statystyki.

![Nakładka podczas powtórki](viewer/screenshot_overlay_de.png)

Interfejs: **polski, angielski, rosyjski** · UI: **Polish, English, Russian** · Интерфейс: **польский, английский, русский**

## Pobranie i użycie (dla graczy)

1. Pobierz `DoW-Statystyki-<wersja>.zip` z zakładki **[Releases](../../releases)** i rozpakuj.
2. Uruchom **`Start.bat`**, w grze otwórz **Powtórki → powtórka → Odtwórz**.
3. Szczegóły: `INSTRUKCJA.txt` w paczce.

Wymagania: Windows 10/11 64-bit, DoW: Definitive Edition ze Steam (wersja 2.10.3.1). Nic więcej nie trzeba instalować.

## English

Squad statistics for **Dawn of War: Definitive Edition** replays, similar to StarCraft II replay stats: damage dealt,
models killed, damage taken and models lost for every squad, split by weapons, grenades and abilities (Dark Eldar
soul powers as a separate row). A viewer window and a semi-transparent in-game overlay; selecting a squad in the
game shows its numbers. Download the zip from **[Releases](../../releases)**, extract, run **`Start.bat`**, then
in the game: Replays → choose a replay → Play. Details: `INSTRUCTIONS_EN.txt`. Works only while watching replays;
game files are not modified.

## Русский

Статистика отрядов в реплеях **Dawn of War: Definitive Edition**, как в реплеях StarCraft II: нанесённый урон,
убитые модели, полученный урон и потери каждого отряда с разбивкой по оружию, гранатам и способностям (силы душ
Тёмных эльдар отдельной строкой). Окно просмотра и полупрозрачный оверлей поверх игры; при выборе отряда в игре
показывается его статистика. Скачайте zip из **[Releases](../../releases)**, распакуйте, запустите **`Start.bat`**,
затем в игре: Реплеи → выберите реплей → Воспроизвести. Подробности: `INSTRUKCIYA_RU.txt`. Работает только при
просмотре реплеев; файлы игры не изменяются.

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
