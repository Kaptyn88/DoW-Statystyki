# Statystyki powtórek Dawn of War: Definitive Edition – instrukcja

Narzędzie liczy, ile obrażeń zadał i ile modeli zabił każdy oddział w **powtórce** (jak statystyki w powtórkach
StarCrafta II), z broniami, zdolnościami (np. moce duszy Mrocznych Eldarów jako osobny wiersz) i nakładką na grę.

## Uruchamianie

1. Zamknij Dawn of War, jeśli działa. Steam musi być włączony.
2. Kliknij dwa razy **`start.bat`** w tym folderze.
   - Za pierwszym razem może potrwać dłużej (budowa DLL i katalogu nazw z danych gry, ok. 1 min).
3. Otworzy się okno **podglądu** i gra. Jeśli gra stoi na czarnym ekranie, kliknij jej okno.
4. W grze: **Powtórki → wybierz powtórkę → Odtwórz**. Statystyki zaczną się zbierać od pierwszej sekundy.
5. Puść powtórkę na przyspieszeniu albo oglądaj normalnie – podgląd i nakładka odświeżają się co sekundę.

Powtórki gra trzyma w `%APPDATA%\Relic Entertainment\Dawn of War\PLAYBACK` (tam wrzucaj pobrane pliki `.rec`;
nie nazywaj ich `temp.rec`, bo ten plik gra nadpisuje po każdym meczu).

## Podgląd

- Tabela oddziałów: zadane obrażenia, udział, zabite modele, otrzymane, stracone, friendly fire.
  Klik w nagłówek sortuje, lista „Gracz” filtruje.
- Klik w oddział: miejsce w rankingu (ogółem i u gracza), obrażenia na minutę, wykres w czasie, broń i zdolności,
  komu zadał i od kogo dostał.
- Suwak **Czas** cofa statystyki do wybranego momentu; **Na żywo** wraca do bieżącego.
  „● nagrywanie” = powtórka leci; „brak nowych danych” = pauza albo koniec.
- **Otwórz…** – starsze nagrania z folderu `recordings`.

## Nakładka

Przycisk **Nakładka…** w podglądzie: włączenie, liczba oddziałów (2–5), sortowanie (obrażenia / zabójstwa),
gracze (wszyscy razem / każdy osobno / wybrany), zakres czasu (cały mecz / ostatnie 60 s / 3 min), kolumny,
przezroczystość, wielkość tekstu. Odblokowaną nakładkę przeciągasz myszą; po ustawieniu zaznacz
**Zablokuj nakładkę** – wtedy kliknięcia przechodzą przez nią do gry. Ustawienia zapisują się same.
Nakładka działa w trybie okna bez ramki (domyślny w DE); nad pełnym ekranem wyłącznym nie będzie widoczna.

## Zasady bezpieczeństwa

- Rejestrator działa **tylko w grze uruchomionej przez `start.bat`** i **tylko przy odtwarzaniu powtórek**.
  Gdy zaczniesz mecz na żywo, sam się wyłącza (wykrywa nagrywanie `temp.rec`) i włącza ponownie dopiero przy
  otwarciu powtórki. Do gier sieciowych uruchamiaj grę normalnie przez Steam.
- Pliki gry nie są modyfikowane.

## Co liczy się jak

- Obrażenia = faktyczny spadek zdrowia celu (nadwyżka przy zabiciu i trafienia w nietykalne cele się nie liczą).
- Zdolności i granaty – po nazwie z danych gry, przypisane do jednostki, która ich użyła.
- Moce globalne gracza (moce duszy Mrocznych Eldarów) – osobny wiersz „Moce duszy”.
- Obrażenia w czasie mocy (np. Rozdarcie duszy) – przypisane w przybliżeniu (ofiara trafiona tą mocą do 15 s wcześniej).
- „wybuch przy zniszczeniu” (np. generatory), „efekt budynku / mina”, „atak specjalny: <broń>”.
- Nie liczą się: stawianie budynków (start z 20% zdrowia) i samoistna utrata zdrowia jednostek tymczasowych.

## Gdy coś nie działa

- Dziennik rejestratora: `probe\logs\rec_*.log` (ostatni plik). Nagrania: `recordings\*.jsonl`.
- Po aktualizacji gry: jeśli w dzienniku jest `ERR ... nie znaleziono`, adresy w nowej wersji się zmieniły.
- Szczegóły techniczne i historia ustaleń: `NOTES.md`.
