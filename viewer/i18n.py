"""Teksty interfejsu w trzech językach (pl / en / ru) i wybór języka.

Język: settings.json ("lang"), a domyślnie język interfejsu Windows (polski -> pl, rosyjski -> ru, inny -> en).
Nazwy jednostek, broni i zdolności pochodzą z plików gry (catalog.json) – tu są tylko teksty programu.
"""
import ctypes
import json
import os

import paths

LANGS = {'pl': 'Polski', 'en': 'English', 'ru': 'Русский'}

TEXTS = {
    # --- podgląd
    'title': ('DoW – statystyki oddziałów', 'DoW – squad statistics', 'DoW – статистика отрядов'),
    'open': ('Otwórz…', 'Open…', 'Открыть…'),
    'overlay_btn': ('Nakładka…', 'Overlay…', 'Оверлей…'),
    'follow_newest': ('Śledź najnowsze nagranie', 'Follow newest recording', 'Следить за новой записью'),
    'follow_sel': ('Pokaż oddział zaznaczony w grze', 'Show squad selected in game', 'Показывать выбранный в игре отряд'),
    'topmost': ('Zawsze na wierzchu', 'Always on top', 'Поверх всех окон'),
    'player': ('Gracz:', 'Player:', 'Игрок:'),
    'all_players': ('Wszyscy', 'All', 'Все'),
    'language': ('Język:', 'Language:', 'Язык:'),
    'time': ('Czas:', 'Time:', 'Время:'),
    'live': ('Na żywo', 'Live', 'Вживую'),
    'col_unit': ('Oddział', 'Squad', 'Отряд'),
    'col_player': ('Gracz', 'Player', 'Игрок'),
    'col_dealt': ('Zadane', 'Dealt', 'Нанесено'),
    'col_share': ('Udział', 'Share', 'Доля'),
    'col_kills': ('Zabite', 'Kills', 'Убито'),
    'col_taken': ('Otrzymane', 'Taken', 'Получено'),
    'col_lost': ('Stracone', 'Lost', 'Потери'),
    'pick_squad': ('Wybierz oddział z listy', 'Select a squad from the list', 'Выберите отряд из списка'),
    'card_dealt': ('Zadane obrażenia', 'Damage dealt', 'Нанесённый урон'),
    'card_kills': ('Zabite modele', 'Models killed', 'Убито моделей'),
    'card_rank': ('Miejsce', 'Rank', 'Место'),
    'card_taken': ('Otrzymane', 'Damage taken', 'Полученный урон'),
    'card_lost': ('Stracone modele', 'Models lost', 'Потеряно моделей'),
    'card_dpm': ('Obrażenia / min', 'Damage / min', 'Урон / мин'),
    'timeline': ('Obrażenia w czasie (co 30 s)', 'Damage over time (per 30 s)', 'Урон во времени (за 30 с)'),
    'no_recordings': ('brak nagrań – uruchom grę przez Start.bat i odtwórz powtórkę',
                      'no recordings – start the game with Start.bat and play a replay',
                      'нет записей – запустите игру через Start.bat и откройте реплей'),
    'catalog_building': ('Buduję katalog nazw z plików gry (pierwsze uruchomienie, ok. 20–60 s)…',
                         'Building the name catalog from game files (first run, about 20–60 s)…',
                         'Создаю каталог названий из файлов игры (первый запуск, около 20–60 с)…'),
    'catalog_error': ('Nie udało się zbudować katalogu nazw: {err}', 'Could not build the name catalog: {err}',
                      'Не удалось создать каталог названий: {err}'),
    'catalog_ready': ('Katalog nazw gotowy.', 'Name catalog ready.', 'Каталог названий готов.'),
    'filetype': ('Nagrania dowrec', 'dowrec recordings', 'Записи dowrec'),
    'status_line': ('{replay}  ·  {n} zdarzeń  ·  {players}', '{replay}  ·  {n} events  ·  {players}',
                    '{replay}  ·  событий: {n}  ·  {players}'),
    'recording': ('● nagrywanie', '● recording', '● запись'),
    'no_data': ('brak nowych danych (pauza / koniec)', 'no new data (paused / ended)', 'нет новых данных (пауза / конец)'),
    'detail_sub': ('{player}  ·  {bp}  ·  modeli w nagraniu: {n}', '{player}  ·  {bp}  ·  models in recording: {n}',
                   '{player}  ·  {bp}  ·  моделей в записи: {n}'),
    'rank_val': ('{r}/{n}  (u gracza {ro}/{no})', '{r}/{n}  (player {ro}/{no})', '{r}/{n}  (у игрока {ro}/{no})'),
    'h_weapons': ('Broń', 'Weapons', 'Оружие'),
    'h_victims': ('Najwięcej obrażeń zadał oddziałom', 'Dealt most damage to', 'Больше всего урона нанёс'),
    'h_attackers': ('Najwięcej obrażeń otrzymał od', 'Took most damage from', 'Больше всего урона получил от'),
    'ff_line': ('Friendly fire (własne oddziały): {v}', 'Friendly fire (own squads): {v}', 'Огонь по своим: {v}'),
    'nominal': ('Nominalne obrażenia: {v} (różnica = nadwyżka przy zabiciu,\nnietykalność lub minimalne zdrowie celu)',
                'Nominal damage: {v} (difference = overkill,\ninvulnerability or minimum health of the target)',
                'Номинальный урон: {v} (разница = избыточный урон,\nнеуязвимость или минимальное здоровье цели)'),
    # --- źródła obrażeń i wiersze specjalne (recmodel)
    'powers_soul': ('Moce duszy', 'Soul powers', 'Силы душ'),
    'powers_player': ('Moce gracza', 'Player powers', 'Силы игрока'),
    'src_special_w': ('atak specjalny: {w}', 'special attack: {w}', 'спецатака: {w}'),
    'src_special': ('atak specjalny (wręcz)', 'special attack (melee)', 'спецатака (ближний бой)'),
    'src_unnamed': ('zdolność / atak specjalny (bez nazwy)', 'ability / special attack (unnamed)',
                    'способность / спецатака (без названия)'),
    'src_dot': ('{a} (obrażenia w czasie)', '{a} (damage over time)', '{a} (урон со временем)'),
    'src_explosion': ('wybuch przy zniszczeniu', 'death explosion', 'взрыв при уничтожении'),
    'src_structure': ('efekt budynku / mina', 'building effect / mine', 'эффект здания / мина'),
    'src_weapon_special': ('{w} (atak specjalny)', '{w} (special attack)', '{w} (спецатака)'),
    'src_ability': ('zdolność: {a}', 'ability: {a}', 'способность: {a}'),
    'src_no_weapon': ('bez broni (zdolność / atak specjalny)', 'no weapon (ability / special attack)',
                      'без оружия (способность / спецатака)'),
    'melee_suffix': (' (wręcz)', ' (melee)', ' (ближний бой)'),
    'weapon_n': ('broń {n}', 'weapon {n}', 'оружие {n}'),
    # --- nakładka
    'ov_wait': ('DoW: brak danych – czekam na powtórkę', 'DoW: no data – waiting for a replay',
                'DoW: нет данных – ожидание реплея'),
    'ov_drag': ('(przeciągnij, aby ustawić; zablokuj w ustawieniach)', '(drag to position; lock it in settings)',
                '(перетащите на место; закрепите в настройках)'),
    'ov_col_dealt': ('Obraż.', 'Dmg', 'Урон'),
    'ov_col_kills': ('Zab.', 'Kills', 'Убито'),
    'ov_col_lost': ('Strac.', 'Lost', 'Потери'),
    'ov_by_kills': ('wg zabójstw', 'by kills', 'по убийствам'),
    'ov_by_dmg': ('wg obrażeń', 'by damage', 'по урону'),
    'win_0': ('cały mecz', 'whole match', 'весь матч'),
    'win_60': ('ostatnie 60 s', 'last 60 s', 'последние 60 с'),
    'win_180': ('ostatnie 3 min', 'last 3 min', 'последние 3 мин'),
    'ov_sel_line': ('obrażenia {d}  ·  zabite {k}  ·  stracone {l}', 'damage {d}  ·  kills {k}  ·  lost {l}',
                    'урон {d}  ·  убито {k}  ·  потери {l}'),
    'ov_sel_none': ('Zaznacz oddział w grze', 'Select a squad in the game', 'Выберите отряд в игре'),
    'ov_value_line': ('zniszczył {k}  ·  stracił {l}', 'destroyed {k}  ·  lost {l}', 'уничтожил {k}  ·  потерял {l}'),
    'res_fmt': ('{r} R / {p} E', '{r} R / {p} P', '{r} Р / {p} Э'),
    'tab_army': ('Armia', 'Army', 'Армия'),
    'tab_losses': ('Straty', 'Losses', 'Потери'),
    'tab_eco': ('Ekonomia', 'Economy', 'Экономика'),
    # frakcje (folder rasy w danych gry)
    'race_space_marines': ('Kosmiczni Marines', 'Space Marines', 'Космодесант'),
    'race_chaos': ('Chaos', 'Chaos', 'Хаос'),
    'race_orks': ('Orkowie', 'Orks', 'Орки'),
    'race_eldar': ('Eldarzy', 'Eldar', 'Эльдары'),
    'race_guard': ('Gwardia Imperialna', 'Imperial Guard', 'Имперская гвардия'),
    'race_necrons': ('Nekroni', 'Necrons', 'Некроны'),
    'race_tau': ('Tau', 'Tau', 'Тау'),
    'race_dark_eldar': ('Mroczni Eldarzy', 'Dark Eldar', 'Тёмные эльдары'),
    'race_sisters': ('Siostry Bitwy', 'Sisters of Battle', 'Сёстры битвы'),
    'tab_research': ('Ulepszenia', 'Upgrades', 'Улучшения'),
    'res_none': ('Brak danych o ulepszeniach (nagranie sprzed v1.4 albo inny mod niż DXP3)',
                 'No upgrade data (recording older than v1.4 or a mod other than DXP3)',
                 'Нет данных об улучшениях (запись до v1.4 или мод, отличный от DXP3)'),
    'res_spent': ('wydano: {v}', 'spent: {v}', 'потрачено: {v}'),
    'tab_build': ('Budowa', 'Build order', 'Порядок стройки'),
    'tab_battles': ('Bitwy', 'Battles', 'Битвы'),
    'build_none': ('Brak danych o budowie (nagranie sprzed v2.0)', 'No build data (recording older than v2.0)',
                   'Нет данных о стройке (запись до v2.0)'),
    'set_build_rows': ('Wiersze kolejności budowy', 'Build order rows', 'Строк порядка стройки'),
    'bat_army_now': ('Aktualna wartość armii', 'Current army value', 'Текущая стоимость армии'),
    'bat_team_total': ('razem drużyna', 'team total', 'всего команда'),
    'eco_chart_army': ('Przewaga wartości armii (R + E): {a} ▲ / {b} ▼', 'Army value advantage (R + P): {a} ▲ / {b} ▼',
                       'Преимущество стоимости армии (Р + Э): {a} ▲ / {b} ▼'),
    'bat_col_time': ('Czas', 'Time', 'Время'),
    'bat_col_dmg': ('Obraż. {n}', 'Dmg {n}', 'Урон {n}'),
    'bat_col_lost': ('Straty {n}', 'Lost {n}', 'Потери {n}'),
    'eco_none': ('Brak danych ekonomii (nagranie sprzed v1.4 albo inny mod niż DXP3)',
                 'No economy data (recording older than v1.4 or a mod other than DXP3)',
                 'Нет данных экономики (запись до v1.4 или мод, отличный от DXP3)'),
    'eco_col_bank': ('Stan', 'Bank', 'Запас'),
    'eco_col_income': ('Dochód / 10 s', 'Income / 10 s', 'Доход / 10 с'),
    'res_r': ('R', 'R', 'Р'),
    'res_e': ('E', 'P', 'Э'),
    'eco_col_total': ('Zebrane łącznie', 'Collected total', 'Собрано всего'),
    'eco_chart_req': ('Przewaga dochodu – rekwizycja (/10 s): {a} ▲ / {b} ▼',
                      'Income advantage – requisition (/10 s): {a} ▲ / {b} ▼',
                      'Преимущество в доходе – реквизиция (/10 с): {a} ▲ / {b} ▼'),
    'eco_chart_pow': ('Przewaga dochodu – energia (/10 s): {a} ▲ / {b} ▼',
                      'Income advantage – power (/10 s): {a} ▲ / {b} ▼',
                      'Преимущество в доходе – энергия (/10 с): {a} ▲ / {b} ▼'),
    'ov_col_lost_res': ('Stracone', 'Lost', 'Потеряно'),
    'ov_col_killed_res': ('Zniszczone', 'Destroyed', 'Уничтожено'),
    'ov_col_kd': ('Zab. / strac.', 'Kills / lost', 'Убито / потери'),
    'ov_losses_note': ('R – rekwizycja, E – energia', 'R – requisition, P – power', 'Р – реквизиция, Э – энергия'),
    # --- ustawienia nakładki
    'set_sec_unit': ('Nakładka oddziału (zaznaczony w grze)', 'Squad overlay (selected in game)',
                     'Оверлей отряда (выбранного в игре)'),
    'set_sec_summary': ('Nakładka podsumowania', 'Summary overlay', 'Оверлей сводки'),
    'set_show_summary': ('Pokaż podsumowanie', 'Show summary', 'Показывать сводку'),
    'set_tabs': ('Zakładki', 'Tabs', 'Вкладки'),
    'set_sec_common': ('Obie nakładki', 'Both overlays', 'Оба оверлея'),
    'set_sec_keys': ('Skróty klawiszowe (działają w grze)', 'Hotkeys (work in game)', 'Горячие клавиши (работают в игре)'),
    'key_none': ('brak', 'none', 'нет'),
    'key_unit': ('Pokaż/ukryj nakładkę oddziału', 'Show/hide squad overlay', 'Показать/скрыть оверлей отряда'),
    'key_summary': ('Pokaż/ukryj podsumowanie', 'Show/hide summary', 'Показать/скрыть сводку'),
    'key_tab': ('Następna zakładka podsumowania', 'Next summary tab', 'Следующая вкладка сводки'),
    'key_tab_prev': ('Poprzednia zakładka podsumowania', 'Previous summary tab', 'Предыдущая вкладка сводки'),
    'key_tabs_more': ('Skróty do poszczególnych zakładek (opcjonalne)', 'Hotkeys for individual tabs (optional)',
                      'Клавиши для отдельных вкладок (необязательно)'),
    'key_tab_to': ('Zakładka {tab}', 'Tab {tab}', 'Вкладка {tab}'),
    'key_busy': ('Zajęte przez inny program: {keys} – wybierz inny klawisz.',
                 'Taken by another program: {keys} – choose another key.',
                 'Занято другой программой: {keys} – выберите другую клавишу.'),
    'set_title': ('Nakładka – ustawienia', 'Overlay – settings', 'Оверлей – настройки'),
    'set_show': ('Pokaż nakładkę', 'Show overlay', 'Показывать оверлей'),
    'set_count': ('Oddziałów na gracza', 'Squads per player', 'Отрядов на игрока'),
    'set_sort': ('Sortuj wg', 'Sort by', 'Сортировать по'),
    'sort_dealt': ('zadanych obrażeń', 'damage dealt', 'нанесённому урону'),
    'sort_kills': ('zabitych modeli', 'models killed', 'убитым моделям'),
    'set_players': ('Gracze', 'Players', 'Игроки'),
    'mode_all': ('Wszyscy razem', 'All together', 'Все вместе'),
    'mode_each': ('Każdy gracz osobno', 'Each player separately', 'Каждый игрок отдельно'),
    'set_range': ('Zakres czasu', 'Time range', 'Период'),
    'set_columns': ('Kolumny', 'Columns', 'Столбцы'),
    'chk_dealt': ('zadane obrażenia', 'damage dealt', 'нанесённый урон'),
    'chk_kills': ('zabite modele', 'models killed', 'убитые модели'),
    'chk_lost': ('stracone modele', 'models lost', 'потерянные модели'),
    'chk_share': ('udział %', 'share %', 'доля %'),
    'chk_header': ('nagłówek z czasem', 'header with time', 'заголовок со временем'),
    'chk_selected': ('zaznaczony oddział', 'selected squad', 'выбранный отряд'),
    'set_opacity': ('Przezroczystość', 'Opacity', 'Прозрачность'),
    'set_font': ('Wielkość tekstu', 'Text size', 'Размер текста'),
    'set_lock': ('Zablokuj nakładkę (kliknięcia przechodzą do gry)', 'Lock overlay (clicks pass through to the game)',
                 'Закрепить оверлей (клики проходят в игру)'),
    'set_drag_hint': ('Odblokowaną nakładkę przesuwasz myszą.', 'Drag the unlocked overlay with the mouse.',
                      'Незакреплённый оверлей можно перетаскивать мышью.'),
}
_INDEX = {'pl': 0, 'en': 1, 'ru': 2}
_lang = 'pl'


def system_lang():
    """Język interfejsu Windows -> pl / ru / en."""
    try:
        primary = ctypes.windll.kernel32.GetUserDefaultUILanguage() & 0x3FF
        return {0x15: 'pl', 0x19: 'ru'}.get(primary, 'en')
    except (AttributeError, OSError):
        return 'en'


def _read_settings():
    try:
        with open(paths.SETTINGS_PATH, encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def load():
    """Ustawia język z settings.json albo z systemu; zwraca kod języka."""
    global _lang
    code = _read_settings().get('lang')
    _lang = code if code in LANGS else system_lang()
    return _lang


def save(code):
    """Zapisuje język w settings.json, zachowując pozostałe ustawienia (np. nakładki)."""
    global _lang
    _lang = code if code in LANGS else 'en'
    data = _read_settings()
    data['lang'] = _lang
    try:
        os.makedirs(os.path.dirname(paths.SETTINGS_PATH), exist_ok=True)
        with open(paths.SETTINGS_PATH, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except OSError:
        pass


def lang():
    return _lang


def t(key, **kw):
    text = TEXTS[key][_INDEX[_lang]] or TEXTS[key][1]
    return text.format(**kw) if kw else text
