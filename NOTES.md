# DoW:DE replay overlay – notatki z analizy (2026-10-17)

> Uruchamianie: start.bat (instrukcja: INSTRUKCJA.md). Repozytorium git (gałąź main) od 2026-10-17;
> pomijane: .venv, probe/bin|obj|logs, recordings, catalog/catalog.json, viewer/settings.json.
> MinHook v1.3.4 dołączony w third_party/minhook (bez własnego .git).
> GitHub (publiczne): https://github.com/Kaptyn88/DoW-Statystyki – wydanie v1.0 z paczką 2026-10-18.
> Nowe wydanie: commit -> git tag -a vX.Y -> .venv\Scripts\python package\make_package.py vX.Y ->
> git push --tags -> na GitHubie "Create a new release" z tagiem i zipem z dist\ (brak gh CLI na tym PC).
> Paczka: Podglad.exe (PyInstaller --onefile, katalog nazw budowany z gry odbiorcy przy 1. uruchomieniu),
> bin\dowrec.dll + dowprobe_launcher.exe (gra z bibliotek Steam: libraryfolders.vdf, app 3556750), Start.bat.

## Cel
Nakładka/podgląd do powtórek Dawn of War: Definitive Edition (jak statystyki w SC2): dla wybranego oddziału
pokazać zadane obrażenia, zabite modele i porównanie z resztą. Gra: Steam, wersja 2.10.3.1.
Gra: C:\Program Files (x86)\Steam\steamapps\common\Dawn of War Definitive Edition
Przykładowa powtórka: Downloads\...W-NEC-L-ORK.rec (Necron vs Ork, mapa 2P_TITAN_FALL)

## Wnioski
- .rec (Relic Chunky) zawiera TYLKO ustawienia meczu i komendy graczy. Brak zdarzeń walki. Gra liczy bitwę od nowa
  (lockstep), więc dane o obrażeniach trzeba wyprodukować uruchamiając silnik w trakcie odtwarzania.
- SCAR (Tools\ScarDoc): brak zdarzeń zabójstw/obrażeń z informacją o atakującym; są tylko odczyty stanu
  (Squad_GetHealth, Squad_Count, Stats_PlayerUnitsKilled...).
- autoexec.lua -> localexec.lua NIE jest wykonywany (test z markerem ps_log.txt, także z -dev w opcjach Steam).
  Plik localexec.lua w folderze gry to nieudany eksperyment – można usunąć.
- Wybrana droga: hook w silniku (DLL) obserwujący zmiany zdrowia + osobna aplikacja-podgląd (patrz architektura).

## Fakty o plikach gry (build z ts SimEngine 1789202316, ImageBase 0x180000000, x64)
- Logika walki: W40kMod.dll (eksportuje tylko GetDllInterface/GetDllVersion/MemManagerOverloads). RTTI daje nazwy klas:
  HealthExt, WeaponInfo, Weapon, ShootingWeapon, MeleeWeapon, ProjectileWeapon, StateProjectile, CombatExt,
  SyncKillExtInfo, SyncDeathExtInfo, SquadStateCombat, SquadReinforceExt itd.
- SimEngine.dll eksportuje 2400 symboli C++ (lista: analysis/simengine_exports.txt): Entity::GetID/GetOwner/GetSquad/
  GetBlueprintName, Squad::GetOwner/GetBlueprintName/GetID, World::GetPlayerAt/GetSquads, Player::GetSquads...
- Lua/SCAR rejestracje w W40kMod.dll: funkcja 0xbd830 rejestruje Entity_GetHealth (wrapper 0xbe920),
  Entity_SetHealth (wrapper 0xbf090), Entity_IsUnderAttack*, itd. (wszystkie adresy to RVA)
- Układ obiektu zdrowia (HealthExt): [+0x10]=flaga aktywności (w obiekcie ext), [+0x28]=zdrowie jako ułamek 0..1,
  [+0x2c]=zdrowie maksymalne (GetHealth = ułamek * max, funkcja 0x93310), [+0xe0], [+0xe4], [+0x3c] liczniki/flagi.
- Jedyne miejsce zapisu zdrowia: HealthExt::SetHealth(core) @ RVA 0x943c0 (this=rcx, nowa wartość bezwzględna=xmm1).
  Wołają je m.in. 0x92f00 (TakeDamage? args: rcx=this, xmm1=kwota, r8b=flaga), 0x93230 (podobna; bez bezpośrednich
  wywołań E8 – wołana pośrednio), 0x93040/0x93bb5 (regeneracja/degeneracja), 0x93d90 (losowa zmiana), 0xadd30, 0xd0860.
- 0x93e20 = ścieżka śmierci (wołana gdy zdrowie <= 0, ma losowanie 'XTLH').
- Wywołania 0x92f00: z 0x9940a (func 0x992a0) i 0xdfa70 (func 0xdf939).
- Vtable HealthExt: RVA 0x260be8 (sloty: 92e60 93f00 ... 93c30 93ab0 ... 934d0 94110 938b0).
- Funkcje obrażeń nie dostają wskaźnika atakującego -> atakującego trzeba znaleźć wyżej w łańcuchu (kod broni/pocisku:
  m.in. xref ciągu 'armour_damage' @ func 0x16ee40, 'max_damage' @ 0x81cb0, 'NrAttackers' @ 0x98490,
  'WasAttackedSince' @ 0x40160, 'SyncKillEntity' @ 0x15b730, 'InCombatTicks' @ 0x89530).

## Sesja 2026-10-17 (2) – sonda: ustalenia
- !!! Gra przy powtórce NEC vs ORK ładuje **DXP3Mod.dll** (Soulstorm), NIE W40kMod.dll. Każdy mod ma własną DLL
  (W40kMod/WXPMod/DXP2Mod/DXP3Mod) z tym samym kodem, ale innym rozkładem. DLL moda ładuje się dopiero po ekranie
  startowym (SimEngine.dll od razu przy starcie procesu).
- Rozwiązywanie adresów łańcuchem (analysis/resolve_chain.py, ta sama logika w sondzie):
  TakeDamage = sygnatura `40 53 48 83 EC 30 0F 29 74 24 20 0F 28 F1 48 8B D9 45 84 C0 74 ?? E8` (unikalna w 4 DLL)
  SetHealth = cel `call` po `F3 0F 5C C8 48 8B CB E8` w TakeDamage; Death = cel `call` po `33 D2 48 8B CB E8` w SetHealth.
  World* (global) = `48 8B 0D ?? ?? ?? ?? C7 44 24 40 58 54 4C 48` (mov rcx,[rip+X]; stała 'XTLH').
  | DLL | TakeDamage | SetHealth | Death | &World* |
  | W40kMod | 92f00 | 943c0 | 93e20 | 3247b0 |
  | WXPMod  | 93b90 | 95050 | 94ab0 | 339290 |
  | DXP2Mod | c1c60 | c3610 | c2d40 | 40a420 |
  | DXP3Mod | cfca0 | d19e0 | d1170 | 477e20 |
- Czas gry: World::GetGameTicks = [World+0x14] (int), GetGameTime = ticks * stała / [World+0x10] (eksporty SimEngine).
- Entity (SimEngine, trywialne akcesory): [+4]=ID, [+8]->...->nazwa bp, [+0x10]=Player*, [+0x20]=Squad*.
- HIPOTEZA (do potwierdzenia logiem): Entity* = [[HealthExt+8]+0x10] (ścieżka śmierci czyta [r14+0x10] = Player).
- W40kMod: 0x93230 nie ma ŻADNYCH odwołań (martwy kod). 0x930c0/0x93880 = leczenie (AddHealth, tail-jmp do SetHealth).
  0x992a0 zadaje WŁASNEJ encji max_hp/(n+1) – to nie ścieżka broni.
- W DXP3 HealthExt ma dodatkowo [+0x30] = minimalne zdrowie (clamp) i [+0x20]->[+0x28] flaga.
- Gra ma steam_appid.txt i brak anty-cheatu (EAC/BattlEye) => W40k.exe można startować bezpośrednio (Steam musi działać).
- Usunięto z folderu gry localexec.lua (kopia: backup/localexec.lua.bak).

## Sonda (probe/) – zbudowana
- probe/build.bat (MSVC Build Tools 2026, vcvars64) -> probe/bin/dowprobe.dll + dowprobe_launcher.exe; MinHook v1.3.4 w third_party/.
- Launcher: odmawia, gdy W40k.exe działa; ustawia DOWPROBE_LAUNCHER=1 i DOWPROBE_LOG; startuje grę, po SimEngine.dll
  wstrzykuje DLL (CreateRemoteThread+LoadLibraryW). Pliki gry nietknięte. Log: probe/logs/probe_*.log.
- Bezpiecznik w DLL: hook NtCreateFile; hooki gry włączane po otwarciu *.rec do odczytu, zdejmowane po otwarciu *.rec
  do zapisu (gra na żywo nagrywa temp.rec). NIEPOTWIERDZONE: czy odtwarzanie powtórki nie zapisuje temp.rec.
- Log: linie E (opis encji), SET/DMG/DIE (z tick, stosem M+rva i "sent" = ID innych znanych encji znalezionych na stosie),
  FILE/GUARD/HOOKS/STAT.

## Wyniki sondy (log probe/logs/probe_20261017_160306.log, cała powtórka NEC vs ORK, 785 s / 6287 ticków)
- 5404 DMG, 4966 SET (spadki), 121 DIE, 95k zdarzeń leczenia/regeneracji, 130 encji. Statystyki: analysis/probe_stats.py.
- POTWIERDZONE: Entity* = [[HealthExt+8]+0x10] (130/130 encji z poprawnymi bp, ownerem i squadem).
- POTWIERDZONE: czas gry = World::GetGameTicks/GetGameTime przez global World; 8 ticków = 1 s.
- POTWIERDZONE: odtwarzanie powtórki czyta #...rec, a ~170 ms później TWORZY temp.rec (zapis). Bezpiecznik uznaje
  zapis do 30 s po odczycie za część odtwarzania; zapis bez wcześniejszego odczytu (gra na żywo) wyłącza sondę.
- POTWIERDZONE: zbyt wczesne wstrzyknięcie (przy SimEngine.dll) zawiesza start gry (czarny ekran, brak DLL moda).
  Launcher wstrzykuje dopiero po załadowaniu DLL moda.
- Ścieżki (DXP3Mod): wszystkie obrażenia od broni: TakeDamage <- M+15ffcd/15ffbd (func 0x15fbc0) <- 0x1604a0 / 0x160400
  <- 0xafd50 / 0xa6f60 <- 0xaf610 <- 0xb0c90 ... Budowa budynków: SET z M+eef78 (zdrowie startuje od 20%).
  DIE spoza walki: M+d19b3 <- 0x15f1c7/0x15f162 (do zbadania: despawn/poświęcenie?).
- Skan stosu: encja na stałym offsecie stosu w ~78% to wróg ofiary (np. ork_slugga_boy -> necron_listening_post)
  => atakujący przechodzi przez ten łańcuch. ~22% "same-owner" – niewyjaśnione (prawdopodobnie stare sloty stosu
  lub friendly fire); docelowy hook czyta argumenty wprost, więc heurystyka nie będzie potrzebna.

## DOCELOWY HOOK: ApplyDamage (DXP3Mod 0x15fbc0) – z analizy statycznej, zgodny z logiem
  ApplyDamage(rcx=ofiara Entity*, rdx=ATAKUJĄCY Entity* (może być NULL), r8=?, r9=WeaponInfo?*,
              [rsp+0x28 przy wejściu]=float, [rsp+0x30]=byte) -> xmm0 = zadane obrażenia
  - ofiara: [[rcx+0x28]+0x28] = HealthExt, na którym woła TakeDamage(kwota=xmm7, r8b=1 wróg / 0 gdy [rdx+0x10]==[rcx+0x10]).
  - atakujący: [rdx+0x10] porównywany z ownerem ofiary (friendly fire), [[rdx+0x28]+0x28] = HealthExt atakującego
    (0xd0850 / 0xcfe70 / TakeDamage na atakującym = efekty typu life-steal / odbicie, mod. 0x8c/0x91/0x92).
  - r9: [r9+0x120] std::string (prawdopodobnie nazwa broni – NIEPOTWIERDZONE), [r9+0x10] int, [r9+0x5e] bajt.
  - 0x1605a0 liczy obrażenia (pancerz?) zanim zostaną pomnożone przez modyfikator.
  - wysyła zdarzenie {owner ofiary, typ 0xE, atakujący, ofiara, kwota} przez 0xf7be0/0xf7bf0 (alternatywny punkt hooka).
  - 0xd1610(HealthExt ofiary, atakujący) – prawdopodobnie "ostatni atakujący".
  Znajdowanie: wywołanie TakeDamage wzorcem `41 B0 01 0F 28 CF 48 8B CF E8 <rel32=TakeDamage>`, a potem początek
  funkcji przez RtlLookupFunctionEntry (analysis/find_applydamage.py). Działa w DXP3Mod i DXP2Mod; w W40kMod/WXPMod
  kod jest inny (tam kandydat: func 0xdf939 wołająca TakeDamage z 0xdfa70 – do zbadania, jeśli będą potrzebne).
  Rejestrator: przy wejściu do ApplyDamage zapamiętać (atakujący, ofiara, broń) w zmiennej wątku; SET/DIE wywołane
  wewnątrz przypisać atakującemu; po wyjściu zapisać xmm0. Zabite modele = DIE wewnątrz ApplyDamage.

## Sonda v2 – hook ApplyDamage (log probe/logs/probe_20261017_161115.log; analiza: analysis/app_stats.py)
- ApplyDamage znajdowany automatycznie (wzorzec wywołania TakeDamage + RtlLookupFunctionEntry) -> DXP3 M+15fbc0. OK.
- Determinizm: liczby SET/DMG/DIE identyczne jak w przebiegu v1 (4966/5404/121) => hooki nie zmieniają symulacji.
- POTWIERDZONE: rdx = atakujący Entity*. 5404 skutecznych wywołań = dokładnie 5404 TakeDamage; atakujący nigdy NULL;
  5364 wróg ofiary, 40 ten sam właściciel = friendly fire odłamkami ork_wartrak (pociski 588/644).
- POTWIERDZONE: rcx = ofiara; wszystkie DMG i 4927/4966 SET oraz 114/121 DIE dzieją się wewnątrz ApplyDamage.
  7 DIE poza nim (M+d19b3 <- 0x15f1c7/0x15f162) i 39 SET – ścieżki spoza walki (budowa itp.).
- POTWIERDZONE: r9 = WeaponInfo (RTTI) w 5283 wywołaniach; [r9+0x10] = stabilne ID broni (np. ork_shoota_boy 646,
  necron_basic_warrior 545, necron_wraith 549). r9 = NULL w 121 (ścieżka M+160432 – bez broni).
  [r9+0x120] NIE jest nazwą broni (zwykle pusty, czasem nazwa pocisku: Ork_Battlecannon_Shell, ork_dual_rokkit).
  r8: obiekt bez RTTI (do ustalenia).
- Zwrot xmm0 = nominalne obrażenia. Różni się od faktycznej straty HP przy (a) zgonie – nadwyżka (114×),
  (b) trafieniach w necron_wraith (299×) i necron_lord (178×) bez spadku HP (nietykalność/min. zdrowie [+0x30]).
  => w statystykach liczyć obrażenia = faktyczny spadek HP (SET wewnątrz ApplyDamage), res zapisywać jako nominalne.
- ~29 tys. wywołań z res=0 i bez zmian HP (np. ork_shoota_boy na samym sobie, ork_hq co 8 ticków) – szum, odfiltrować.
- W TEJ POWTÓRCE wg atakującego (faktyczne HP / zabite modele): necron_basic_warrior 16372/36, ork_shoota_boy 13452/14,
  ork_wartrak 9754/3, necron_lord 8216/14, ork_mek_boy 6163/7, necron_wraith 3594/16 ...
## Sonda v2.1 – nazwa broni (log probe/logs/probe_20261017_162835.log, linie WI/R8)
- POTWIERDZONE: nazwa blueprintu broni = *(const char**)(*(uintptr_t*)(WeaponInfo + 8)), np.
  646 ork_shoota_shoota, 545 necron_warrior_gauss_flayer_ranged, 658 ork_slugga_slugga, 596 ork_choppa_boyz_slugga,
  629 ork_power_claw_mekboy, 526 necron_lord_staff_of_light_melee, 528 necron_lord_staff_of_light_ranged,
  614 ork_knife_shoota, 656 ork_slugga_bigmek, 604 ork_grot_blasta, 607 ork_grot_knife.
- WeaponInfo+0xe0 = std::string 'Melee' dla broni wręcz (puste dla dystansowych); +0x200 czasem nazwa ulepszenia
  (np. 'ork_power_klaw'). Napisy od ~+0x380 w zrzucie należą już do SĄSIEDNIEGO obiektu w pamięci – ignorować.
- POTWIERDZONE: r8 = r9 + 0x288 (podobiekt WeaponInfo) gdy jest broń.
- Gdy r9 = NULL: r8 to inny obiekt. Przy zerowych "obrażeniach" bywa to zdolność (+0x1e0 = nazwa, np. ork_waagh_charge,
  ork_pop_growth_increase_at_10; +0x3f8 'ability/...'). Przy SKUTECZNYCH obrażeniach bez broni (ork_mek_boy 50 dmg,
  necron_flayed_one, necron_tomb_spyder, necron_lord) r8 wskazuje na obiekt z nazwami hardpointów/animacji
  (Weapon_Range_Upgrade_Hull, abilities\ork_waagh_charge.lua...) – typ NIEUSTALONY. Atakujący jest w tych przypadkach
  poprawny; źródło opisywać jako "zdolność/atak specjalny" do czasu ustalenia typu.

## Rejestrator dowrec.dll (probe/src/recorder.cpp) – ZBUDOWANY i przetestowany 2026-10-17
- Uruchamianie: probe\bin\dowprobe_launcher.exe --rec  -> sesje w recordings\<powtórka>_<data>.jsonl,
  dziennik w probe\logs\rec_*.log. Podsumowanie: python analysis\rec_summary.py <plik.jsonl> [--do SEKUNDY].
- Format JSONL opisany w nagłówku recorder.cpp (meta/player/ent/wpn/dmg/die). Nowa sesja przy każdym ponownym
  odtworzeniu (cofnięcie ticka) albo innej powtórce. Plik zrzucany co 1 s (podgląd może czytać na bieżąco).
- Test (recordings/_47673293-W-NEC-L-ORK_20261017_164127.jsonl): 5404 dmg i 7 die – identycznie z sondą;
  114 zabitych modeli w dmg + 7 = 121 zgonów. Gracze: 1001 (Necron), 1000 (Ork) – nicki rozpoznane poprawnie. 28 broni.
- BŁĄD w tym nagraniu (naprawiony): oddział/bp encji czytane PO ApplyDamage, a zabity model jest wtedy wypięty
  z oddziału (vs=0) -> straty trafiały do "encji bez oddziału". Teraz odczyt PRZED oryginałem. rec_summary.py dla
  starych nagrań bierze ostatni znany niezerowy oddział encji.
- Test poprawki (recordings/_47673293-W-NEC-L-ORK_20261017_164704.jsonl): dmg 5404, die 7, ent 199 (było 309),
  zabite z vs=0 tylko 6 – same budynki bez oddziału (listening_post, gork_totem). 7 "die" poza ApplyDamage to też
  budynki (ork_hq, boy_hut, mek_shop, generator, waagh_banner, gork_totem, necron_turret) – prawdopodobnie koniec gry
  / inna ścieżka niszczenia (NIEPOTWIERDZONE która).
- Bezpiecznik włącza się już w menu (lista powtórek czyta pliki .rec) – to nieszkodliwe; gra na żywo zapisuje temp.rec
  > 30 s później i wyłącza rejestrator.
- POTWIERDZONE: gra uruchomiona z terminala w tle potrafi stać na czarnym ekranie (170 MB, ~0 CPU, brak DLL moda)
  do czasu wyciągnięcia okna na wierzch – to była przyczyna "zawieszeń" (nie wstrzykiwanie). Launcher teraz co 2 s
  wyciąga okno gry na wierzch, dopóki mod się nie załaduje.
- Obrażenia "bez WeaponInfo" to ~12% (9986 HP) – źródło (zdolności/ataki specjalne) nadal nieustalone.

## Podgląd statystyk (viewer/) – ZBUDOWANY 2026-10-17
- Uruchamianie: viewer\podglad.bat [plik.jsonl] (pythonw z .venv; tkinter, bez dodatkowych pakietów).
  Bez argumentu: najnowsze nagranie z recordings\ i automatyczne przełączanie na nowsze ("Śledź najnowsze nagranie").
- viewer/recmodel.py – model (wczytywanie przyrostowe .jsonl, statystyki do zadanego ticka, ranking, nazwy oddziałów
  "Ork shoota boy #2" = kolejność squad id u gracza). viewer/dow_viewer.py – okno.
- Funkcje: tabela oddziałów (zadane, udział %, zabite, otrzymane, stracone, FF; sortowanie po nagłówkach; kolor gracza;
  filtr gracza), suwak czasu + "Na żywo", panel oddziału: miejsce ogółem i u gracza, obrażenia/min, oś czasu co 30 s
  ze znacznikiem bieżącego czasu, broń, komu zadał / od kogo otrzymał. "Zawsze na wierzchu" do pracy obok gry
  (gra ma screenwindowed=2). Zrzuty nakładki: viewer/screenshot_overlay*.png.
- Sprawdzone na nagraniu 164704: sumy zgodne z rec_summary.py (114 zabitych / 121 strat), widok "do 5:00" działa.
- Rejestrator dopisuje rekord {"t":"clock","tick"} co ~1 s, gdy symulacja biegnie (tick rośnie), i OTWIERA SESJĘ już
  od startu powtórki (wcześniej dopiero przy pierwszym trafieniu – przez pierwsze ~1,5 min podgląd pokazywał stare,
  zakończone nagranie i "Na żywo" skakało na jego koniec; zgłoszone przez użytkownika).
- POTWIERDZONE na żywo 2026-10-17 (recordings/_47673293-W-NEC-L-ORK_20261017_165855.jsonl): sesja od ticka 2,
  podgląd sam przełącza się na nowy plik, "Na żywo" nadąża za powtórką (8:50 w podglądzie = tick 4240 w pliku),
  status "● nagrywanie" / "brak nowych danych (pauza / koniec)" (pauzy nie da się odróżnić od końca). Pauza w środku
  nie dzieli sesji.
- Ograniczenia: oddział wybiera się w podglądzie (wybór z gry wymagałby hooka selekcji); czas pojawienia się oddziału
  przybliżony (ostatni tick przed rekordem 'ent'); ~12% obrażeń "bez broni" (zdolności) bez nazwy źródła.

## Nakładka + zdolności (w toku, 2026-10-17)
- POTWIERDZONE: bezpiecznik wyłączył rejestrator, gdy użytkownik zaczął grę na żywo w instancji uruchomionej
  launcherem ("GUARD zapis .rec (gra na zywo?) - rejestrator WYLACZONY", sesja zamknięta).
- viewer/overlay.py: nakładka (Toplevel bez ramki, topmost, alpha; zablokowana = WS_EX_TRANSPARENT|NOACTIVATE, czyli
  kliknięcia przechodzą do gry i nie zabiera fokusu) + okno ustawień (przycisk "Nakładka…" w podglądzie):
  liczba oddziałów 2–5, sortowanie (obrażenia/zabójstwa), gracze (wszyscy / każdy osobno / wybrany), zakres czasu
  (cały mecz / 60 s / 3 min), kolumny, przezroczystość, wielkość tekstu, blokada; zapis w viewer/settings.json.
  Nakładka zawsze pokazuje najnowszy stan nagrania. NIEPRZETESTOWANA na ekranie (użytkownik akurat grał).
- recmodel.stats(upto, from_tick) – statystyki w przedziale czasu.
- Rejestrator (skompilowany kontrolnie, NIEZBUDOWANY – DLL zablokowana przez grę): rekord "hp" dla spadków HP poza
  ApplyDamage (src = ścieżka kodu M+rva>...), a "dmg" bez broni dostaje src i ab (nazwa zdolności z r8+0x1e0, gdy
  r8+0x3f8 zaczyna się od "ability/" – hipoteza). Cel: rozpoznać granaty i moce prorokini (Eldar) na powtórce.
- ZROBIONE: dowrec.dll przebudowany; nakładka przetestowana nad grą na żywo (viewer/screenshot_overlay.png).
  Błąd "pusta nakładka": styl WS_EX_LAYERED trafiał do wewnętrznego okna Tk (przed zmapowaniem okna GetAncestor
  zwraca samo okno z treścią) -> treść się nie rysowała. Teraz styl dopiero, gdy istnieje okno najwyższego poziomu.
- POTWIERDZONE (powtórka Eldar vs Gwardia, recordings/2P_VELVET_DURESS...171936.jsonl, 12 min, 9715 dmg):
  * granaty plazmowe Eldarów = zdolność "eldar_plasma_grenades" przez ApplyDamage, atakujący = eldar_guardian
    (28 trafień, 1932 HP); granatnik Gwardii = zwykła broń guard_grenade_launcher_guardsmen.
  * Eldritch Storm prorokini = zdolność "eldar_psychic_storm" przez ApplyDamage (188 trafień, 2348 HP, 2 użycia
    po 9 s) – hipoteza z nazwą zdolności z r8+0x1e0 / "ability/" w r8+0x3f8 POTWIERDZONA.
  * WSZYSTKIE obrażenia bojowe idą przez ApplyDamage (atakujący zawsze znany). Spadki HP poza nim (rekord "hp")
    to wyłącznie stawianie budynków (start z 20% HP, ścieżka M+eef78>M+222586>M+2224fa) – podgląd ich nie liczy.
  * Bez nazwy (r8 nie jest obiektem zdolności): prorokini ~1084 HP, kapitan Gwardii ~307, Necron lord ~2538.
    Ścieżka "a72a1": ~68 dmg/tick wyłącznie w dowódców (komisarz, kapitan, enginseer), serie 1–4 s – PRAWDOPODOBNIE
    Mind War (niepotwierdzone). Ścieżka "affe4": krótkie salwy ~13 dmg w kilka modeli – ta sama ścieżka co granaty,
    więc ścieżka kodu nie odróżnia mocy od ataków specjalnych. Podgląd łączy je w "zdolność / atak specjalny (bez nazwy)".
## Ogólne nazywanie źródeł obrażeń (2026-10-17) – dla WSZYSTKICH jednostek, bez ręcznej listy
- Kod: obrażenia obszarowe idą przez 0xaf610 ("Areaeffect") -> 0xafcc0/0xafd50 -> 0x1604a0 (z bronią) albo 0x160400
  (bez broni) -> ApplyDamage. r8 = rsi+8, gdzie rsi = opis obszaru rażenia (AreaEffectInfo; +0x78/+0x80 tablica spadku
  z odległością). Kolejka opóźnionych efektów: pętla 0xb1b60 (wpis r14: [r14]=AreaEffectInfo, +8 cel, +0x70 pozycja,
  +0xa0 atakujący, +0xd0 broń).
- AreaEffectInfo jest POLEM obiektu-źródła. Obiekty z danych gry trzymają ścieżkę pliku "data:attrib\<folder>\<x>.rgd".
  Rejestrator szuka najbliższej takiej ścieżki wstecz od r8 (do 0x800) -> dmg.ab (nazwa) / dmg.abf (folder) / dmg.abo.
  POTWIERDZONE (powtórka Eldar, rec log "SRC"): eldar_psychic_storm, eldar_plasma_grenades, eldar_mind_war – ścieżka
  zawsze 0xb8 przed r8. Mind War (wcześniej "bez nazwy", wniosek z zachowania) teraz nazwany wprost.
  Dla broni ścieżka WeaponInfo leży ~0x310–0x330 przed r8 (porównanie w logu).
- Bez pliku danych (abo=-1): AreaEffectInfo tworzony w locie, pamięć bez odwołań do właściciela (odczyt pamięci gry:
  analysis/peek_mem.py, peek_fields.py). Salwy zbiegają się z walką bronią wręcz tej jednostki (kapitan Gwardii:
  13/14 serii przy power_gauntlet) -> ATAK SPECJALNY WRĘCZ (wniosek, nie odczyt). Rejestrator dopisuje "sw" =
  ostatnia broń wręcz atakującego; podgląd: "atak specjalny: <broń>". Zbudowane, NIEPRZETESTOWANE w grze.
- Podgląd: "zdolność: <nazwa>", "<nazwa> (atak specjalny)" dla folderu weapon, "atak specjalny: <broń>".
- UWAGA (poprawka nazw): eldar_psychic_storm = "Burza psioniczna" (Psychic Storm), NIE Eldritch Storm.
  Eldritch Storm = eldar_eldritchstorm ("Tajemna Burza").

## Katalog z danych gry (catalog/) – ZBUDOWANY 2026-10-17
- python catalog\build_catalog.py  (~20 s) -> catalog\catalog.json. Wymaga tylko Pythona, bez dodatkowych pakietów (sga.py, rgd.py).
- sga.py: SGA v2 w wariancie DE: nazwa archiwum 64 wchar, nagłówek spisu od 0xB4 (offsety względem 0xB4),
  folder 12 B, plik 20 B (nazwa, flagi, offset, spakowany, rozmiar), dane od u32@0xB0, zlib gdy rozmiary różne.
- rgd.py: Relic Chunky DATA/AEGD; tabela = u32 n, n×(hasz, typ, offset), dane; typy 0 float, 1 int, 2 bool, 3 str,
  4 wstr, 100/101 tabela. Klucze = Bob Jenkins lookup2 (initval 0) – POTWIERDZONE (screen_name_id, max_damage...).
- Warstwy jak DoWDE.module: DoWDE > DXP3 > DXP2 > WXP > W40k (4710 plików attrib).
- Nazwy: Engine\Locale\Polish\Engine.ucs (UTF-16, "id<TAB>tekst"; DE trzyma tu teksty wszystkich dodatków) + English.
  Polskich lokalizacji nie ma w archiwach modów (tylko EN/FR/DE/RU) – jest tylko w Engine.
- Zawartość: 507 zdolności (215 z obrażeniami), 974 bronie, 604 jednostki, 452 oddziały, 10 ras (+npc).
  Nazwy PL: oddziały 445/452, jednostki 594/604, zdolności 391/507, bronie 400/974 (wiele broni nie ma nazwy w UI).
  Jednostka -> zdolności/bronie i oddział -> jednostki/zdolności z odwołań "abilities\x.lua"/"weapon\y.lua"/"ebps\..".
  Zdolności potomne (fazy jednej mocy) -> rodzic przez child_ability_name albo PRZYPUSZCZENIE z nazwy
  (parent_guess; np. chaos_doombolt3 -> chaos_doombolt "Pocisk zagłady"). Z 215 zdolności z obrażeniami 20 bez
  jednostki (kampania/twierdze/globalne, np. chaos_warp_storm_damage_*).
- Obrażenia w katalogu = min/max z armour_damage w tablicach weapon_damage (bez tabel egzekucji ~100000).
- Podgląd (recmodel.Catalog) używa nazw PL dla oddziałów, broni, zdolności i ataków specjalnych; bez katalogu
  zostają nazwy techniczne. Fazy jednej mocy sumują się pod zdolnością-rodzicem (CATALOG.root).

## Moce globalne gracza (np. moce duszy Mrocznych Eldarów) – 2026-10-17
- W danych gry to zdolności głównego budynku: dark_eldar_hq (Forteca Kabału) ma corrosive_cloud (Korozja),
  piercing_vision, rekindle_rage, rend_soul (Rozdarcie duszy 100 + faza _dot 6), screams_of_the_damned,
  soulstorm (Burza Spaczni; obrażenia w fazie _aura 11). Katalog: abilities[x].global = właściciel to *_hq
  (z fazami potomnymi). Inne rasy: brak mocy globalnych z obrażeniami w grze sieciowej (eldar "Kamień Duszy" = kampania).
  Zdolności zwykłych budynków (np. necron_listening_post "Wyjący terror") zostają przy budynku.
- Podgląd/nakładka: obrażenia z mocy globalnej -> osobny wiersz ('powers', gracz) "Moce duszy" (DE) / "Moce gracza";
  zapas: trafienie bez broni ze źródłem HQ też trafia do tego wiersza. Sprawdzone na sztucznym nagraniu.
- Powtórka 3v3 #47672736-W-NEC-DE-TAU-L-SOB-CSM-SM (11 min, 6 graczy, recordings/..._175820.jsonl, 11085 dmg):
  gracz DE NIE użył żadnej mocy duszy -> reguła wciąż niesprawdzona na żywo.
  Tau rozpoznane po nazwie: tau_photon_grenade (Granaty Fotonowe 2092), tau_devour (480), tau_target_acquired (400).
- Obszar rażenia bez pliku danych (abo=-1) to nie tylko ataki specjalne: generatory Necronów/Marines – wybuch
  dokładnie w ticku zniszczenia (44/44 trafień, dt=0); chaos_mine_field – miny. Podgląd rozróżnia: atakujący zginął
  ±2 ticki -> "wybuch przy zniszczeniu"; atakujący to budynek/pole minowe (katalog: category structures) ->
  "efekt budynku / mina"; sw>=0 -> "atak specjalny: <broń>"; reszta -> "bez nazwy" (np. dowódca Tau, misjonarz).
- Rekordy "hp" ścieżką M+d0a20>M+d0e71 (930 szt., 1564 HP) = samoistna utrata zdrowia: chaos_slave 2,2/tick
  (jednostki tymczasowe), skull_probe 100–125 naraz (wygasanie), budynki Necron/Tau 0,2/tick. Nie liczone jako obrażenia.
- POTWIERDZONE (mecz użytkownika DE vs AI Eldar, 2P_BATTLE_MARSHES.2026-10-17.18-25-37, 21 min,
  recordings/..._182815.jsonl, 14311 dmg):
  * Burza Spaczni: atakujący = osobna ENCJA POMOCNICZA "dark_eldar_soulstorm" (tworzona na czas burzy), źródło
    dark_eldar_soulstorm_aura -> 1651 trafień, 7376 HP (bez FF). Największe źródło mocy.
  * Rozdarcie duszy: atakujący = dark_eldar_hq (Forteca), dark_eldar_rend_soul -> 441 HP.
  * Faza _dot (Rozdarcie duszy) NIE idzie przez ApplyDamage: modyfikator zdrowia -> rekordy "hp" (1,1/tick) bez sprawcy.
    Podgląd: HEURYSTYKA – małe spadki HP (<=25) ofiary do 15 s po trafieniu zdolnością, która ma fazę "<x>_dot"
    w katalogu, liczą się tej zdolności i jej sprawcy ("(obrażenia w czasie)", tu 159 HP); zgon w tym oknie = zabójstwo.
  * "Moce duszy" w podglądzie/nakładce: 7976 HP, 13 zabitych, 2. miejsce w meczu (viewer/screenshot_overlay_de.png).
    Encje pomocnicze mocy (bez własnych statystyk) są ukrywane w tabeli (Recording.power_helpers).
  * Pozostałe rekordy "hp": stawianie budynków AI (800–3200 naraz), samoistna utrata zdrowia od 0 s meczu (0,12/0,25
    na tick) – nieprzypisywane.
- (historyczne) NIEPOTWIERDZONE w grze: kogo ApplyDamage podaje jako atakującego przy mocach duszy (HQ? encja pomocnicza?) –
  reguła po nazwie zdolności działa niezależnie od tego, o ile rejestrator odczyta ścieżkę abilities\..; potrzebna
  powtórka z Mrocznymi Eldarami.

## Zaznaczenie oddziału w grze -> podgląd/nakładka (2026-10-17) – DZIAŁA (potwierdzone przez użytkownika)
- W40k.exe: SCAR Misc_GetSelectedSquads -> obsługa E+d4f480: app=E+bd7820(), ui=E+bd6c80(app), sel=E+cc2ac0(ui),
  grp = sel->vtbl[1](sel) = EntityHolderGroup zaznaczonych encji (SimEngine begin/end), encja+0x20 = oddział.
  Rejestrator znajduje to sam: napis -> lea r8 w rejestracji -> lea rax/mov [rsi+20] -> 3 wywołania + ogon
  "mov rcx,rax; mov rdx,[rax]; call [rdx+8]" (analysis/resolve_selection.py odtwarza to na pliku).
- Odczyt z wątku roboczego co 0,2 s (w __try), rekord {"t":"sel","tick","sq":[...],"e":[...]} przy zmianie,
  wraz z rekordami 'ent' zaznaczonych encji (oddział mógł jeszcze nie walczyć).
- Podgląd: "Pokaż oddział zaznaczony w grze" (domyślnie wł.) przełącza wybór przy każdej zmianie zaznaczenia.
- Nakładka: sekcja "▶ <oddział>" + "obrażenia · zabite · stracone" (cały mecz); przełącznik "zaznaczony oddział".
  "Miejsce w rankingu" usunięte na prośbę użytkownika (było niejasne).

## Języki PL / EN / RU (v1.1, 2026-10-18)
- viewer/i18n.py: teksty interfejsu (podgląd, nakładka, ustawienia, podpisy źródeł obrażeń) w 3 językach;
  język w settings.json ("lang"), domyślnie język Windows (GetUserDefaultUILanguage: 0x15 pl, 0x19 ru, inny en).
  Zmiana w podglądzie -> zapis i ponowne otwarcie okna (main() w pętli).
- Nazwy z gry: catalog.json ma pl/en/ru z Engine\Locale\{Polish,English,Russian}\Engine.ucs (RU: 445/452 oddziałów);
  katalog "version": 2 – podgląd sam przebudowuje starszy katalog (bez ru) przy starcie.
- Nakładka: tryb graczy zapisywany kodem ('all'/'each' albo nick); stare polskie wartości mapowane przy wczytaniu.
  OverlaySettings.save zachowuje inne klucze settings.json (lang).
- Launcher: komunikaty pl/en/ru (język: <folder launchera>\..\settings.json albo Windows), UTF-16 w konsoli /
  UTF-8 przy przekierowaniu; --check (gra znaleziona i nie działa) dla Start.bat, który nie ma już własnych tekstów.
- Paczka: INSTRUKCJA.txt, INSTRUCTIONS_EN.txt, INSTRUKCIYA_RU.txt; make_package.py --no-build (bez MSVC).

## Ikony jednostek (v1.2, 2026-10-18)
- Źródło: klasyczne TGA 64x64 w archiwach: art\ui\ingame\<rasa>_icons\<nazwa>.tga (typ 2, 32 bit; wszystkie rasy).
  Remaster ma .rtx (DoWDE.sga, *SharedTextures-Definitive) i .dds (art\ui\swf\icons) – nieużywane.
- Nazwa ikony: ui_info/icon_name w RGD (najpłytsze), np. 'eldar_icons/farseer_icon'. Oddziały 424/452 mają plik;
  bez własnej ikony (np. guard_squad_command) -> ikona pierwszej jednostki oddziału. Moce gracza -> ikona ich
  najmocniejszej zdolności.
- catalog/icons.py: TGA -> PNG (czysty Python, zlib), średnia z bloków do 20/26/32 px, zapis w catalog/icons
  (428 ikon, ~30 s budowy razem z katalogiem). Katalog "version": 3 – podgląd znajomego przebuduje go sam.
- Podgląd: kolumna ikon (Treeview #0, wiersz 24 px) i ikona 32 px przy nazwie w szczegółach; nakładka: ikona
  ~2x wielkości tekstu przy nazwie oddziału i w sekcji zaznaczonego oddziału (viewer/iconcache.py).

## Szybsza reakcja na zaznaczenie, nakładka domyślnie włączona (v1.2, 2026-10-18)
- Rejestrator: odczyt zaznaczenia co 0,1 s (było 0,2 s); zegar/zrzut buforów nadal co 1 s (iter % 10).
- Podgląd: pętla co 0,1 s (było 1 s – to było główne źródło opóźnienia). Zmiana zaznaczenia -> tylko podświetlenie
  wiersza, szczegóły z ostatnich statystyk i nakładka (bez przeliczania); pełne przeliczenie najwyżej raz na sekundę.
  Pomiar (dopisanie rekordu sel -> zmiana w podglądzie): 16–74 ms (było do ~1000 ms).
- OverlaySettings.enabled domyślnie True (nowi użytkownicy widzą nakładkę od razu).
- Wydanie v1.2 obejmuje ikony + szybsze zaznaczenie + nakładkę domyślnie włączoną (tag v1.3 usunięty na prośbę
  użytkownika, v1.2 przeniesiony na ten commit przed publikacją wydania).

## Optymalizacja wydajności (v1.3, 2026-10-18)
- recmodel: statystyki "na żywo" liczone przyrostowo (_Acc dokarmiany nowymi zdarzeniami; ostatni tick wstrzymany
  do następnego, bo np. wybuch generatora zapisuje rekordy nie po kolei; po 1,5 s bez przyrostu – dociągnięcie całości).
  Wynik identyczny z pełnym przeliczeniem na 3 nagraniach. Pamięć podręczna etykiet jednostek i istnienia ikon.
- Podgląd: tabela aktualizowana w miejscu (bez kasowania wierszy); nakładka tworzy etykiety raz i zmienia tylko
  komórki, które się zmieniły (bez zmian – brak przerysowania).
- Pomiar offline (symulacja powtórki x8): ~250 ms/s -> mediana 17,5 ms na cykl (p95 63 ms).
- Rejestrator: linia "PERF hooki: X ms/s (N wywolan/s, max Y us) | zaznaczenie: Z ms/s" co 10 s w logu rec_*.log.
  Pomiar na żywo (3v3, do 325 trafień/s): hooki <= 0,24 ms/s (~0,02% czasu gry), max pojedyncze wywołanie 0,12 ms;
  zaznaczenie co 0,1 s ~0,08 ms/s. Podgląd: 5–7% jednego rdzenia w trakcie walki (osobny proces).
  Użytkownik w AMD Adrenalin nie widzi różnicy FPS z nakładką i bez – zostawiono odświeżanie 0,1 s.

## v1.4 (w toku, 2026-10-19): dwie nakładki, skróty, straty zasobów
Pomysły użytkownika: skrót do nakładki, wskaźnik ekonomii (zebrane zasoby ŁĄCZNIE; dochód/min gra już pokazuje),
wynalezione ulepszenia, wykres przewagi ekonomicznej, stracona rekwizycja/energia. Układ: nakładka oddziału +
nakładka podsumowania z zakładkami.
- ZROBIONE – ceny: ebps/<model>.rgd -> cost_ext/time_cost/cost/{requisition,power} (np. marine taktyczny 50/0,
  sierżant 75/25, Predator 165/300, HQ SM 450/0, generator SM 135/0). Oddział: koszt modelu = jego ebps (lider ma
  własny ebps; squad_reinforce_ext/cost = cena dokupienia modelu, zgodna z ebps). Katalog "version": 4, units[*].cost.
  529/604 encji ma niezerową cenę. NIEPOTWIERDZONE: necron_basic_warrior ma cenę 0/0 w danych – sprawdzić w grze.
  Bez ulepszeń broni oddziału (osobne koszty upgrade) i bez częściowej ceny budynku w budowie; startowe HQ liczone
  pełną ceną.
- ZROBIONE – straty/zniszczona wartość (recmodel._Acc._charge): przy zgonie (dmg.k / die) cena modelu do
  S[ofiara]['lost_req'/'lost_pow'] i S[zabójca]['killed_req'/'killed_pow'] (bez friendly fire; zgon w DoT ->
  sprawca DoT). Raz na encję – Nekroni wstają i giną ponownie (1 encja z 2 zgonami w NEC-ORK).
  Stats.player_totals(pid).
- ZROBIONE – ciała z Jamy Tortur DE (dark_eldar_torture_pit_corpse, oddział dark_eldar_squad_slave_murdered) nie są
  liczone jako zabite/stracone modele (recmodel.is_model); wcześniej Raguel "stracił" 145 modeli, faktycznie 7.
- ZROBIONE – overlay.py: OverlayWindow (wspólne), UnitOverlay (tylko zaznaczony oddział + wartość zniszczona/stracona),
  SummaryOverlay (zakładki 'army' = dawny ranking, 'losses' = zasoby graczy), Overlays (menedżer + skróty).
  Ustawienia: sum_enabled, sum_tab, sum_x/sum_y, key_unit/key_summary/key_tab (domyślnie F6/F7/F8).
- ZROBIONE – hotkeys.py: RegisterHotKey(NULL, MOD_NOREPEAT) w osobnym wątku z GetMessage (Tk nie przekazuje WM_HOTKEY),
  akcje w kolejce, podgląd odbiera je w _tick (co 0,1 s). Zajęty klawisz -> komunikat w oknie ustawień. Przy zmianie
  języka (restart okna) skróty zwalniane przed destroy(). NIEPOTWIERDZONE: czy F6–F8 nie kolidują z klawiszami gry.
- Test: zrzut okna poza ekranem (PrintWindow) pokazuje nieodrysowane resztki – to artefakt testu; na ekranie czysto,
  a lista widżetów po przełączeniu zakładki poprawna (scratchpad/check_slaves.py, winshot.py).
- ZROBIONE – drużyny (Recording.teams): rejestrator ich nie zna; podział graczy z największymi obrażeniami między
  stronami (pair_dmg bez ff), remis -> kolejność pid (1. połowa vs 2.). Sprawdzone: 3v3 #47672736 = SOB/CSM/SM vs
  NEC/DE/TAU (zgodne z nazwą powtórki), 1v1 poprawne. NIEPOTWIERDZONE dla FFA / 2v2 z AI.
- ZROBIONE – zakładka Armia: dwie kolumny (drużyna lewa/prawa), gracz + jego najlepsze oddziały (obrażenia, zabite).
  Zakładka Straty na wzór "Units Lost" z SC2: ikony straconych modeli/budynków z liczbą + suma R/E na drużynę.
- Prośba użytkownika: wykres "Income advantage" jak w SC2, osobno rekwizycja i energia -> wymaga sondy ekonomii.
- ZROBIONE – okno podsumowania: osobna przezroczystość/blokada (sum_opacity domyślnie 1.0, sum_locked), stały rozmiar
  (sum_w/sum_h rośnie do największej zawartości, nie maleje; podwójne kliknięcie odblokowanego okna = dopasuj od nowa).
- SONDA EKONOMII (zbudowana 2026-10-19, NIE uruchomiona):
  - SimEngine nie eksportuje zasobów gracza (Player@@: tylko GetID/GetName/timery itp.) – obiekt gracza to podklasa
    z modu. Launcher `--eco` (= --rec + DOWREC_ECO) -> rejestrator co 5 s zapisuje probe/logs/eco_<data>.bin:
    0x2000 B obiektu gracza + po 256 B z każdego wskaźnika w pierwszych 0x800 B. Gracze z World::GetPlayerFromID
    (1000..1007), więc od początku meczu. W logu rec_*.log: "ECO gracz <pid> obiekt ... klasa <RTTI>".
  - Analiza: `python analysis/eco_scan.py` (najnowszy eco_*.bin) – rosnące floaty = kandydaci na "zebrane łącznie",
    zmienne 0..50000 = "stan konta"; `--at 1000:<tick>=<wartość z ekranu>` zawęża (odczytać z gry stan rekwizycji
    przy pauzie i podać tick z podglądu).
  - Uruchomienie testu: `probe\bin\dowprobe_launcher.exe --eco` (z głównego folderu), podgląd osobno (viewer\podglad.bat).
  - TROP NA PÓŹNIEJ (lepszy niż zgadywanie z pamięci): SimEngine eksportuje
    `?GetCurrentPlayerStats@World@@QEAAXPEAUPlayerStats@@@Z` (World::GetCurrentPlayerStats(PlayerStats*) – zapewne
    dane ekranu statystyk końcowych) oraz `?QueryRelationship@World@@QEBA_NPEBVPlayer@@0W4PlayerRelationship@1@@Z`
    (sojusznik/wróg – pewniejsze drużyny niż heurystyka z obrażeń). Rozmiar struktury PlayerStats nieznany – NIE
    wołać na ślepo; najpierw disasm (analysis/disasm_range.py SimEngine.dll <rva>), ile bajtów zapisuje.
- WYNIK SONDY (2026-10-19, powtórka 2P_BATTLE_MARSHES 19-19-35, Raguel 1000 vs Komputer 1 1001):
  obiekt gracza = klasa `.?AVSigmaPlayer@@` (DXP3Mod, vtable DXP3+0x389e68), z World::GetPlayerFromID. Pola float:
  - +0x3f8 = rekwizycja (stan konta), +0x3fc = energia (stan konta) – POTWIERDZONE z ekranem gry:
    1:35 Komputer energia 155 (pamięć 155.00), 2:36 Raguel 49 rek / 176 en (pamięć 49.55 / 176.38).
  - +0x410 = dochód rekwizycji NA TICK (0.25 -> 0.85; x 480 = na minutę), +0x414 = dochód energii na tick (0.125)
    – POTWIERDZONE rachunkiem: tick 1009->1049 rekwizycja +28.0 = 40 x 0.70; tick 467->507 energia +5.0 = 40 x 0.125.
  - +0x400: 15 -> 3 -> 22 (NIEZNANE; może dusze/populacja – nie używać), +0x418 chwilowe.
  - Licznika "zebrane łącznie" w obiekcie nie ma -> zebrane = suma dochodu w czasie (zapis dochodu co 1 s).
  - Pomiar 54 s nie pasował (tick 432 wypada między próbkami, gdy energia skoczyła 80 -> 138.5) – zegar gry vs
    ticki przesunięte o kilka sekund.
  - Offsety dotyczą DXP3Mod.dll w wersji 2.10.3.1 – po aktualizacji gry sprawdzić ponownie (eco_scan.py --at).
- ZROBIONE (kod, 2026-10-19): rekord {"t":"eco",tick,pid,req,pow,ir,ip} co ~1 s (EcoRecord; tylko gdy RTTI obiektu
  gracza zawiera "SigmaPlayer", wartości 0..1e7). recmodel: Recording.eco (zebrane = suma ir/ip x Δtick),
  eco_at(), income_advantage(teams, 3|4) w /min. Zakładka "Ekonomia" (SUMMARY_TABS): stan / dochód na min /
  zebrane łącznie + 2 wykresy przewagi (Canvas, draw_chart, kolory drużyn). Sprawdzone offline na nagraniu testowym
  z rekordami eco wyliczonymi ze zrzutów sondy (scratchpad make_eco_rec.py); DLL skompilowany próbnie –
  NIE sprawdzony w grze (gra trzymała probe/bin/dowrec.dll – przebudować build.bat po jej zamknięciu).
  Zebrane łącznie nie obejmuje zasobów startowych.
- DRUŻYNY Z GRY (2026-10-19, kod gotowy, NIEPRZETESTOWANY w grze): World::QueryRelationship (SimEngine 0x9c780) =
  jmp [[World+8]]->vtable+0x40; w silniku WorldImp::IsPlayerRelationship (0xa72e0) to `return rel == 0` (wszyscy
  "0" – zapewne wrogowie), właściwą relację nadpisuje mod. Rejestrator: rekord {"t":"rel",a,b,q:[r0..r3]} raz na
  sesję (i przy nowym graczu) dla każdej pary + para (pierwszy gracz, on sam). Podgląd (Recording.teams_from_game):
  ta sama drużyna, gdy q pary == q gracza z samym sobą; dokładnie 2 drużyny -> używane, inaczej heurystyka z obrażeń.
  POTWIERDZONE 2026-10-19 na powtórce 3v3 #47672736: PlayerRelationship 0 = WRÓG, 1 = SOJUSZNIK (gracz z samym
  sobą: [0,1,0,0]; SOB/CSM/SM między sobą [0,1,0,0], z NEC/DE/TAU [1,0,0,0]); 2 i 3 zawsze 0. Drużyny z gry =
  SOB/CSM/SM vs NEC/DE/TAU, zgodnie z nazwą powtórki.
- Wygląd podsumowania: pasek zakładek nad treścią (osobna ramka, aktywna zakładka podświetlona, czas po prawej,
  klik w zakładkę gdy okno odblokowane); usunięty podtytuł "cały mecz · wg obrażeń" (pole show_header zostaje).
- v2.0 (w toku, 2026-10-19):
  - Ustawienia: wyłączanie zakładek podsumowania (sum_tabs_off; co najmniej jedna zostaje; F8 tylko po włączonych).
  - Rejestrator: rekord {"t":"army",tick,pid,n:{bp:liczba}} co ~1 s przy zmianie – Player::GetEntities ->
    EntityGroup, iteracja EntityHolderGroup::begin/end pod przesunięciem 0/8/0x10 (wybór: pierwsza encja należy do
    gracza; log "ARMY przesuniecie ..."). POTWIERDZONE 2026-10-19 (3v3 #47672736): przesunięcie 0x0, składy
    sensowne (chaos_cultist 10, tau_fire_warrior 3 ...). W składzie są też nie-jednostki (strategic_point_flag,
    blood_splat, relic_struct) – spoza attrib/ebps/races, filtrowane CATALOG.is_unit w Budowie; cena 0, więc
    wartości armii nie psują. Wartość armii także pod nazwą gracza w zakładce Armia.
  - Podgląd: Recording.army / first_seen / army_value / army_advantage / build_order; zakładki Budowa (pierwsze
    pojawienie się typów jednostek/budynków, bez startowych) i Bitwy (Recording.battles: odcinki 10 s z
    obrażeniami >= 25% szczytu, łączone z przerwą <= 1 odcinka; obrażenia i stracone R/E drużyn); Ekonomia:
    kolumna Armia + wykres przewagi wartości armii. Bitwy sprawdzone na 3v3 (3 starcia: 4:40, 5:30, 7:40–10:50).
- Budowa: build_rows (domyślnie 8) widocznych pozycji na gracza, domyślnie najnowsze; wąski pasek przewijania
  (komórka 'vbar', Canvas height=1 – inaczej domyślna wysokość płótna rozpycha wiersze); kółko myszy przewija
  wszystkich graczy naraz (build_scroll = pozycje wstecz od najnowszych) – tylko gdy okno odblokowane
  (zablokowane przepuszcza mysz do gry).
- is_model: poza ciałami (_corpse) także encje spoza jednostek ras (attrib/ebps/races), np. dark_eldar_soulstorm,
  dark_eldar_torture_amp_entity, tau_snare_trap – wcześniej w Stratach jako "dark_eld"/"tau_snar" bez ikony.
- Przerwana budowa (gra zwraca całość zasobów) i usunięcie budynków pokonanego gracza: rekord 'die' budynku bez
  trafienia od wroga w ostatnich 10 s (Recording.NOT_LOST_S) -> Recording.not_lost, bez straty/zabicia/bitwy.
  W nagraniach: generator Chaosu (tick 68), generator Tau (1585), Nekronów (2389) – nigdy trafione; HQ i koszary
  Tau na końcu meczu (ostatnie trafienie 60–95 s wcześniej). Zniszczone budynki giną od dmg.k albo 'die' 0–9 ticków
  po trafieniu. Ryzyko: budynek dobity samymi obrażeniami spoza ApplyDamage (np. moc DoT) >10 s po ostatnim
  zwykłym trafieniu zostałby uznany za "bez walki".
  UWAGA użytkownika: budowę często anuluje się właśnie POD OSTRZAŁEM – reguła 10 s tego nie łapie. Dlatego rekord
  'die' z hkDeath ma teraz "hp" (ReadHealth przed oryginałem) i "fl" (flaga Death). Podgląd: budynek z hp > 0 =
  anulowany/usunięty (nie strata), hp = 0 = zniszczony; bez pola hp (stare nagrania) – reguła 10 s.
  TEST (DE vs TAU #38380165, generator Tau anulowany tick 1585): hp = 0.0 (gra zeruje HP przed Death), fl =
  880008881921 (młodszy bajt 1, reszta śmieci z rejestru) – HP NIE rozróżnia. OSTATECZNA REGUŁA: budynek z rekordem
  'die' (by = 0, czyli Death poza ApplyDamage) = anulowany/usunięty, nie strata – niezależnie od wcześniejszych
  trafień; budynki zniszczone w walce giną od dmg.k (w nagraniach zawsze). Przykłady 3v3: generator Nekronów
  trafiony 233 pkt w 2666–2682, 'die' 2691 (anulowanie pod ostrzałem); wieżyczka Nekronów 52 trafienia, 'die' 3 ticki
  po ostatnim. Ryzyko: budynek dobity obrażeniami spoza ApplyDamage (moc DoT) – nie zaobserwowane.
- Rekord res POTWIERDZONY w grze po poprawce (tau_anti_grav_research, tick 422, powtórka DE vs TAU 2026-10-19).
- FAKTYCZNIE WYDANE (wybór użytkownika, 2026-10-19): cena modelu (ebps) != koszt uzupełnienia (sbps
  squad_reinforce_ext/cost/cost): wojownik Nekronów 0 / 35 E, gwardzista 32 / 20 R, szturmowy SM 52,5 / 55 R.
  Rejestrator: rekord {"t":"seen",tick,e,bp,sq,sqbp,pid} przy pierwszym pojawieniu się encji w oddziale (z pętli
  "army"). Podgląd (Recording._add_seen/unit_value): model obecny <= INITIAL_S = 2 s od pojawienia się oddziału =
  zakup (cena ebps), później = uzupełnienie (koszt uzupełnienia) albo lider (squad_leader_ext/*/leader/type – cena
  ebps). Broń z ceną (weapon cost/cost, 203 rodzaje) doliczana do modelu, który jej użył (dmg.w) – broń kupiona,
  a nieużyta, niewidoczna. Wartość armii: liczba modeli z 'army' x średnia wydana wartość żywych modeli typu.
  Katalog v6: squads[*].reinforce/leaders, weapons[*].cost. DO SPRAWDZENIA: czy któraś broń startowa ma cenę
  (np. space_marine_missile_krak_tempest) – liczyłaby się podwójnie.
  POTWIERDZONE w grze (NEC vs ORK #47673293, 2026-10-19, 475 rekordów seen): wojownicy Nekronów 5 x 0 (zakup) +
  3 x 35 E (uzupełnienia); strzelcy Orków 35 R / 75 R + 10 E (uzupełnienie/broń); suma strat Frintta 542 E zgodna
  z zakładką. Aktualna wartość armii przeniesiona (prośba użytkownika) z Armii i Ekonomii do zakładki Bitwy: gracze,
  suma drużyny, wykres przewagi wartości armii, pod spodem bitwy.
- Frakcja gracza (Recording.player_race): rasa większości jego encji wg katalogu (units[*].race), bez 'npc';
  w zakładkach "Nick (Frakcja)" (overlay.pname), nazwy race_* PL/EN/RU. Sprawdzone na 3v3, NEC-ORK, DE-TAU.
- IKONY (2026-10-19): (1) część ebps podaje ikonę bez folderu (necron_wraith: 'necron_wraith_icon', oddział:
  'necron_icons/necron_wraith_icon') – szukanie pliku po nazwie w dowolnym folderze ikon; (2) jednostka bez ikony
  -> ikona oddziału, w którym występuje (Catalog._unit_squad); (3) brakujące .tga (Berserkerowie Khorne'a, drużyny
  broni ciężkiej, Hell Talon, Marauder...) są tylko jako .rtx w <warstwa>Data-SharedTextures-Definitive.sga:
  Relic Chunky FOLDTXTR, DATAATTR = (format 11, szer., wys., mipmapy), DATADATA = mipmapy DXT5 od największej bez
  nagłówków (128x128/8 mipmap = 21872 B) – icons.read_rtx (dekoder DXT5 w czystym Pythonie, mipmapa <= 64 px).
  Wynik: ikony 656/682; jednostki bez ikony tylko kampanijne/testowe (npc_*, thunderhawk, test_building).
  Katalog v7. Badania ekonomiczne (zielone) potwierdzone w grze przez użytkownika (Ork vs Nekron).
- Języki: ikony te same pliki dla PL/EN/RU (sprawdzone zrzutami EN i RU oraz zmianą języka w działającym podglądzie
  pl -> ru: ikony i teksty poprawne); w katalogu każda pozycja z nazwą PL ma też EN i RU (jednostki 359, oddziały
  207, badania 378, bronie 352, zdolności 334). Przy zmianie języka anulowany zaplanowany _tick starego okna
  (wcześniej Tcl: invalid command name ..._tick).
- WYDANIE v2.0 (2026-10-19): commit 631f383, tag v2.0 wypchnięty, paczka dist/DoW-Statystyki-v2.0.zip (13 MB);
  sprawdzone: launcher --check, Podglad.exe z paczki sam buduje katalog v7 (656 ikon, w tym .rtx).
  Uruchamianie przez Steam (podpięcie do gry uruchomionej przez Steam) przesunięte do v2.1.
- Skróty: Shift+F8 = poprzednia zakładka (domyślnie), opcjonalne skróty do każdej zakładki (key_tabs, domyślnie
  brak, sekcja zwinięta w ustawieniach); hotkeys.py obsługuje Shift+/Ctrl+ (MOD_SHIFT/MOD_CONTROL).
- NIEROZWIĄZANE (na v2.1): kliknięcie w ODBLOKOWANĄ nakładkę PODSUMOWANIA na chwilę zatrzymuje grę (nakładka
  oddziału – nie). Poprawka WM_MOUSEACTIVATE -> MA_NOACTIVATE (podmiana procedury okna, overlay._no_activate_on_click)
  potwierdzona komunikatem (SendMessage zwraca 3), ale w grze nie pomogła. Do zbadania: co robi klik w podsumowaniu
  (pasek zakładek -> _set_tab: s.save() zapis pliku + pełne przerysowanie; kółko; przeciąganie geometry()), czy gra
  staje przez utratę fokusu (sprawdzić GetForegroundWindow przed/po kliknięciu) czy przez coś innego; zablokowana
  nakładka (WS_EX_TRANSPARENT) problemu nie ma. Uruchamianie przez Steam – też v2.1.
- NIEPRZETESTOWANE przed v2.0 (użytkownik zdecydował wydać): pełny przebieg z paczki przez Start.bat oraz
  wyłączanie się rejestratora w potyczce na żywo po zmianach v2.0 (kod: nowe rekordy tylko gdy g_armed).
- WYCOFANE na prośbę użytkownika: stały rozmiar okna podsumowania (sum_w/sum_h) – okno znów dopasowuje się do treści.
- ULEPSZENIA (badania) – ustalenia 2026-10-19:
  - SimEngine nie ma nic o badaniach; wszystko w DXP3Mod (napisy: "Research not found while loading Research Array
    in SigmaPlayer", Player_GetResearchState, Stats_PlayerTechResearched, CompletedResearchCount, UICueResearchCompleted).
  - Loader tablicy badań DXP3 0x19b320 (Chunky "ASER", nazwy -> ResearchInfo* przez 0x183860) wołany z
    SigmaPlayer::Load (0x199d1c, 0x199d2e) dla pól +0x2a8 i +0x2c0 (std::vector<ResearchInfo*>); +0x290 innym
    loaderem 0x19aca0.
  - W zrzutach sondy (Battle Marshes): +0x2a8 Raguel 0 -> 3 (ticki 762, 3163, 3413), Komputer 0 -> 1 (2118);
    +0x290 Raguel 0 -> 5, Komputer 0 -> 4; +0x2c0 puste.
  - POTWIERDZONE (sonda RES 2026-10-19 + notatki użytkownika z ekranu): +0x2a8 = UKOŃCZONE badania, element =
    wskaźnik do wpisu tabeli badań, nazwa pliku = *(char**)element. ork_research_grot_infiltrate tick 750 (gra 1:33),
    ork_research_eavy_armor_boyz 3137 (6:32), ork_research_burna 3377 (7:01–7:02). +0x290 = typy postawionych
    budynków (ork_boy_hut, ork_generator, ...), nie badania.
  - Rejestrator: rekord {"t":"res",tick,pid,name} co ~1 s przy wydłużeniu +0x2a8 (ResearchRecords).
    BŁĄD (zgłoszony przez użytkownika: bionika SM 7:35 w 3v3 nie pokazała się): pierwsza wersja czytała *element jako
    tekst, a nazwa jest o wskaźnik głębiej (**element; zapas: tekst w obiekcie – krótki std::string) – żaden rekord
    res nie powstał w żadnym nagraniu; zakładkę testowałem na nagraniu z rekordami dopisanymi z logu sondy, więc
    tego nie wyłapałem. Poprawione + reset listy przy nowej sesji. DO SPRAWDZENIA w grze.
  - "Ulepszenia globalne" wg użytkownika = badania w budynkach + badania ekonomiczne (więcej R/E globalnie):
    *_requisition_research_N / *_power_research_N / *_upgrade_requisition_N / *_upgrade_power_N (34 w danych:
    4 na rasę, Nekroni 2) – Catalog.is_eco_research, w zakładce na zielono. Dobudówki budynków (+0x308 "AddOn
    Array" w SigmaPlayer, loader 0x19a6a0; 64 add-ony w attrib/addons: posterunki, HQ, wieżyczki) – użytkownik NIE
    chce ich w statystykach, kod wycofany (generatory nie mają add-onów w danych).
  - Katalog v5: research[name] = nazwa pl/en/ru (ui_info/screen_name_id), ikona, rasa, koszt time_cost/cost
    (417 badań, 277 z ikoną). Zakładka "Ulepszenia": drużyny w dwóch kolumnach, czas + ikona + nazwa, "wydano R/E".
- (stare) DO ZROBIENIA: sonda ekonomii (zebrane zasoby gracza – licznik z ekranu statystyk końcowych?), sonda ulepszeń
  (moment ukończenia badania), zakładki Ekonomia / Ulepszenia, wykres przewagi.

## Docelowy projekt rejestratora (zrealizowany powyżej, notatka historyczna)
- Hooki: ApplyDamage (wejście/wyjście), SetHealth (faktyczna strata HP), Death (zgon) + bezpiecznik .rec + World (czas).
- Zdarzenie na każde skuteczne ApplyDamage: tick, atakujący (id, bp, squadId, owner), ofiara (to samo), broń
  (WeaponInfo id + nazwa, melee), nominalne obrażenia (xmm0), faktyczna strata HP, zabity model (DIE wewnątrz), friendly fire.
- Pomijać wywołania z res=0 i bez zmian HP. Osobno logować DIE/SET poza ApplyDamage (budowa, inne ścieżki).

## (stare) NASTĘPNY KROK: sonda
Mała biblioteka (DLL) hookująca 0x943c0 i 0x92f00 (MinHook lub podobne), logująca do pliku przy każdym wywołaniu:
czas gry, this, nowa wartość, kwota, oraz ślad stosu (kilka adresów powrotu jako RVA względem W40kMod.dll).
Odtworzyć powtórkę, z śladów ustalić, gdzie w łańcuchu jest dostępny atakujący (Entity/Weapon), potem docelowy hook.
Adresy znajdować docelowo skanowaniem sygnatur, bo aktualizacje gry je zmieniają.
Sondy używać tylko do powtórek offline (nie w grach online).

## Architektura docelowa
1. Rejestrator (DLL w grze): zapisuje strumień zdarzeń (czas, atakujący, ofiara, kwota, zabite modele) podczas przewijania powtórki.
2. Podgląd (osobna aplikacja): czyta czas powtórki i pokazuje statystyki wybranego oddziału (obrażenia, zabójstwa, ranking).
3. Opcjonalnie parser .rec: oś czasu komend, build order, APM.

## Skrypty (analysis/)
Uruchamiać z katalogu innego niż folder gry i z nazwą folderu gry jako argumentem; wymagają: pip install pefile capstone.
- pe_overview.py, strs.py (stringi/RTTI), exports.py, xref.py <dll> <string...>, disasm_range.py <dll> <rva_hex> <len_hex>,
  callers.py <rva...>, vtable.py <Klasa>.
UWAGA: nie nazywać skryptów dis.py ani inspect.py itp. (zasłaniają moduły standardowe).
