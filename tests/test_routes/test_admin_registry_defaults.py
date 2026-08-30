"""Сторож: реєстр адмінки з ненейтральним дефолтом фільтра.

Чотири рази поспіль клітинка таблиці посилалась на реєстр, звужений ЩЕ ДО
того, як хтось торкнувся фільтр-бару, і клікнутий рядок опинявся поза
видимою сторінкою:

- ``routes_error_logs.py``    -- журнал показує лише останні 7 днів
  (``_DEFAULT_ERROR_DAYS``);
- ``routes_meta_leads.py``    -- ``_leads_query`` ховає тестові ліди, доки
  не попросили інакше;
- ``routes_registrations.py`` -- ``scope`` за замовчуванням ``'upcoming'``;
- ``routes_blog_comments.py`` -- статус за замовчуванням ``'pending'``.

Кожен із чотирьох ловило ОКРЕМЕ рев'ю -- людина щоразу уважно читала саме
цю сторінку. Дефект має дві різні форми, і поверхневий сторож, що дивиться
лише на одну з них, дає хибну певність:

1. Дефолт ОГОЛОШЕНО прямо у виклику -- ``choice_arg('scope', ..., 'upcoming')``.
   Видно, якщо знати, куди дивитись (``registrations``, ``blog_comments``).
2. Дефолт ЗАШИТО в будівнику запиту -- сам виклик ``choice_arg`` не передає
   ``default`` (він порожній і виглядає нейтрально), а звужує запит уже
   ``_error_log_query`` / ``_leads_query`` за конкретним значенням поля
   (``error_logs``, ``meta_leads``). Це форма, яку рев'ю проґавило тричі:
   дефолт не видно, доки не прочитаєш функцію запиту рядок за рядком.

Тест НЕ переказує логіку роутів -- ЗАПУСКАЄ саму логіку (AST для форми 1,
реальні функції фільтрів/запиту для форми 2). Дублювати умови
``if scope != 'all': ...`` тут означало б повторити саме ту помилку, яку
рев'ю вже пропустило один раз у коді, що дублюється.

Обидві форми зведені в один перелік ``KNOWN_NON_NEUTRAL_DEFAULTS``: кожен
запис -- свідоме рішення "так, ця сторінка звужена за замовчуванням, і ось
чому", а не мовчазний built-in. Новий запис, якого там нема, валить тест.

Три межі того, що Rule 2 (поведінкова перевірка форми 2) реально
покриває -- навмисні, і сказані тут прямо, а не лише в звіті задачі, який
є чернеткою й буде прибраний:

1. Rule 2 зареєстрована точково для трьох реєстрів у ``_BEHAVIORAL_SITES``
   (``error_logs``, ``meta_leads``, ``registrations``), а не для всіх
   ``routes_*.py`` автоматично. Новий реєстр із захованим у будівнику
   запиту дефолтом лишиться непоміченим, доки хтось не додасть його
   рядком у ``_BEHAVIORAL_SITES``.
2. Rule 2 ловить лише те поле, серед ДОЗВОЛЕНИХ значень якого існує явний
   "без обмежень" (``'0'``, ``'with'``) -- перебір усіх значень шукає
   коротший SQL проти цього "без обмежень". Суто бінарний перемикач без
   варіанту "обидва" (дефолт мовчки обирає один бік, і жодне дозволене
   значення тоді не дає ширшого запиту) Rule 2 не побачить.
3. Rule 2 підміняє ЛИШЕ ``_listing.choice_arg``: звуження, виражене через
   ``int_arg``, ``date_arg``, ``ranged_int_arg`` чи ``bounded_token_arg``,
   у перебір ``calls`` не потрапляє й ніколи не пробується. Саме тому
   власний фільтр ``platform`` (``routes_meta_leads.py``) щойно перейшов
   із ``choice_arg`` на ``bounded_token_arg`` (значення поза випадною
   підказкою мусить фільтрувати теж) -- і цим самим вийшов з-під
   поведінкового пробника Rule 2: захований дефолт на ``platform``, якби
   він тепер з'явився, ця перевірка вже не зловить.
"""
import ast
import glob
import importlib
import os
from pathlib import Path

# Абсолютний шлях від __file__, а не відносний 'app/admin': відносний шлях
# залежить від робочої директорії процесу pytest, і зі старим кодом сторож
# при запуску не з кореня репозиторію мовчки сканував ГЛОБ, що не збігався
# з жодним файлом, і зелено проходив -- без жодної перевіреної умови. Той
# самий прийом, що й tests/test_design_system/test_catalog_coverage.py:21
# (там -- ``Path(__file__).resolve().parents[2]``).
ADMIN_DIR = os.path.join(str(Path(__file__).resolve().parents[2]), 'app', 'admin')

# Скільки routes_*.py реально лежить у app/admin на момент написання цього
# порогу -- 47. Поріг далеко нижче цього числа: сторож мусить пережити
# додавання чи видалення кількох файлів, але голосно впасти, якщо скан
# раптом побачив нуль чи жменю файлів -- ознака зламаного ADMIN_DIR, а не
# порожнього каталогу.
_MIN_PLAUSIBLE_ROUTE_FILES = 20


# --- Перелік ВІДОМИХ ненейтральних дефолтів --------------------------------
#
# Ключ -- (ім'я файлу routes_*.py, ім'я параметра фільтра). Значення --
# пояснення ЧОМУ саме такий дефолт існує: воно ж документує, що станеться
# з посиланням, побудованим на значенні з клітинки цього реєстру (клікнутий
# рядок може опинитись поза дефолтним зрізом).
KNOWN_NON_NEUTRAL_DEFAULTS = {
    ('routes_registrations.py', 'scope'):
        "scope='upcoming' -- реєстр за замовчуванням ховає минулі заходи, "
        "щоб не показувати тисячі нерелевантних реєстрацій; посилання на "
        "реєстрацію минулого заходу мусить нести власний scope.",
    ('routes_blog_comments.py', 'status'):
        "status=BlogComment.STATUS_PENDING -- премодерація: нові коментарі "
        "не показані в дефолтному зрізі, доки адмін не схвалив/не позначив "
        "спамом; посилання на конкретний коментар мусить нести його статус.",
    ('routes_error_logs.py', 'days'):
        "'' -> 7 днів (_DEFAULT_ERROR_DAYS) у _error_log_query -- сам "
        "choice_arg('days', ...) дефолту не оголошує, звужує вже функція "
        "запиту; стара помилка поза вікном 7 днів у дефолтному зрізі не "
        "видна.",
    ('routes_meta_leads.py', 'test'):
        "'' -> is_test=False у _leads_query -- сам choice_arg('test', ...) "
        "дефолту не оголошує, ховає тестові ліди вже функція запиту; "
        "посилання на тестовий лід мусить нести test=with.",
}


# --- Rule 1: дефолт, ОГОЛОШЕНИЙ прямо у виклику -----------------------------

# `sort_arg` навмисно НЕ в цьому переліку. Цей сторож -- про рядки, сховані
# з видимого зрізу; `sort_arg(allowed, default='newest')` міняє лише
# ПОРЯДОК рядків реєстру, жоден рядок не зникає. Сканер тим часом читає
# `node.args[0]` як ім'я параметра (в `choice_arg`/`text_arg` це справді
# перший позиційний аргумент), а в `sort_arg(allowed, default='')`
# (`app/admin/_listing.py:154`) першим позиційним стоїть сам `allowed` --
# без імені параметра. Легальний виклик на кшталт
# `sort_arg(_SORT_OPTIONS, 'newest')` сканер тоді читав би як параметр з
# AST-репрезентацією кортежу замість рядкового імені -- запис, який можна
# внести в KNOWN_NON_NEUTRAL_DEFAULTS, лише вставивши туди цей самий
# `ast.dump()`-непотріб. Пробувати виправити індекс замість виключення
# сенсу нема: сортування просто поза тим, що цей сторож перевіряє.
_DECLARING_CALLS = {'choice_arg', 'text_arg'}


# Позиційний індекс аргументу `default` -- ОКРЕМО для кожної сигнатури:
#   choice_arg(name, allowed, default='')            -- індекс 2
#   text_arg(name, default='', max_length=...)        -- індекс 1
# Спільний індекс для choice_arg і text_arg (як було раніше) -- баг, не
# спрощення: `text_arg('foo', 'значення')` (два аргументи) під індексом 2
# не має чого читати -- виклик мовчки пропускався; а
# `text_arg('foo', '', 80)` (max_length третім) під тим самим індексом
# читав 80 як default і хибно палив нейтральний виклик. Обидва рядки
# `app/admin/_listing.py:40` (text_arg) і `:75` (choice_arg) -- джерело
# цих чисел, не здогадка.
_DEFAULT_ARG_INDEX = {
    'choice_arg': 2,
    'text_arg': 1,
}


def _scan_source(file_label, src):
    """AST-прохід по ОДНОМУ джерелу: виклики choice_arg/text_arg,
    де передано ``default``, відмінний від порожнього рядка.

    Винесено з ``_declared_non_neutral_defaults`` окремою функцією, щоб
    тест міг прогнати сканер на сирому фрагменті коду (нижче), а не
    редагувати реальний роут заради перевірки самого парсера.
    """
    found = []
    tree = ast.parse(src, filename=file_label)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (isinstance(func, ast.Attribute) and func.attr in _DECLARING_CALLS):
            continue
        default_node = None
        for kw in node.keywords:
            if kw.arg == 'default':
                default_node = kw.value
                break
        if default_node is None:
            index = _DEFAULT_ARG_INDEX[func.attr]
            if len(node.args) > index:
                default_node = node.args[index]
        if default_node is None:
            continue
        if isinstance(default_node, ast.Constant) and default_node.value == '':
            continue  # '' -- нейтральний дефолт самого хелпера, не звуження
        name_node = node.args[0] if node.args else None
        if isinstance(name_node, ast.Constant):
            param = name_node.value
        elif name_node is not None:
            param = ast.dump(name_node)
        else:
            param = '?'
        found.append((file_label, param, ast.unparse(default_node)))
    return found


def _declared_non_neutral_defaults():
    """AST-скан усіх ``app/admin/routes_*.py`` (див. ``_scan_source``).

    Саме AST, а не "викликати кожну ``*_filters()``": дефолт статусу в
    ``routes_blog_comments.py`` живе в окремій ``_status_arg()``, а не у
    ``_filters()`` -- обхід за іменами функцій-фільтрів її б і не побачив.
    AST бачить виклик БУДЬ-ДЕ у файлі, незалежно від імені функції навколо,
    і не виконує жодного коду (швидко, без БД).
    """
    paths = sorted(glob.glob(os.path.join(ADMIN_DIR, 'routes_*.py')))
    # Нуль чи жменя файлів тут -- НЕ "у app/admin нема роутів": це ознака
    # зламаного ADMIN_DIR (стара відносна форма мовчки давала нуль збігів
    # при запуску pytest не з кореня репозиторію -- сторож зникав, а не
    # падав). Голосний assert замість тихого порожнього результату.
    assert len(paths) >= _MIN_PLAUSIBLE_ROUTE_FILES, (
        f"Скан {ADMIN_DIR!r} на 'routes_*.py' знайшов лише {len(paths)} "
        "файлів -- це ознака зламаного шляху ADMIN_DIR, а не порожнього "
        "app/admin. Сторож, що мовчки скановує нуль файлів, зелено "
        "проходить, не перевіривши нічого."
    )
    found = []
    for path in paths:
        src = open(path, encoding='utf-8').read()
        found.extend(_scan_source(os.path.basename(path), src))
    return found


def test_declared_filter_defaults_are_all_known():
    """Кожен оголошений (непорожній) дефолт фільтра -- в явному переліку.

    Джерело правди -- сам код через AST, не переказ логіки: НОВИЙ виклик
    на кшталт ``choice_arg('щось', ..., default='не-порожньо')`` будь-де в
    ``admin/routes_*.py`` валить цей тест, доки автор не додасть пояснення
    в ``KNOWN_NON_NEUTRAL_DEFAULTS`` -- тобто не подумає, куди веде
    посилання, побудоване на значенні з клітинки цього реєстру.
    """
    missing = []
    for file_name, param, default_src in _declared_non_neutral_defaults():
        if (file_name, param) not in KNOWN_NON_NEUTRAL_DEFAULTS:
            missing.append(f"{file_name}:{param} (default={default_src})")
    assert not missing, (
        "Новий ненейтральний дефолт фільтра без пояснення в "
        "KNOWN_NON_NEUTRAL_DEFAULTS (tests/test_routes/"
        "test_admin_registry_defaults.py): " + ', '.join(missing)
    )


def test_scanner_reads_text_arg_default_at_its_own_index():
    """Сторож самого сканера: ``text_arg`` і ``choice_arg`` тримають
    ``default`` на РІЗНИХ позиційних місцях -- переплутати їх уже було
    реальним багом (рев'ю знайшло: спільний індекс або пропускав
    двоаргументний ``text_arg`` із непорожнім дефолтом, або хибно приймав
    ``max_length`` за дефолт у трьохаргументному виклику). Парсимо сирий
    фрагмент коду, а не редагуємо справжній роут -- перевіряємо сам
    сканер, а не конкретний файл.
    """
    # text_arg(name, default) -- два позиційні, default НЕПОРОЖНІЙ:
    # мусить знайтись (індекс 1, не 2).
    two_positional = (
        "from app.admin import _listing\n"
        "def f():\n"
        "    return _listing.text_arg('foo', 'some-default')\n"
    )
    found = _scan_source('snippet.py', two_positional)
    assert any(param == 'foo' for _file, param, _default in found), (
        "text_arg('foo', 'some-default') -- непорожній дефолт на "
        "індексі 1, сканер мусить його побачити"
    )

    # text_arg(name, '', max_length) -- три позиційні, default ПОРОЖНІЙ,
    # третій аргумент -- max_length, а не default: НЕ мусить спрацювати.
    three_positional_neutral = (
        "from app.admin import _listing\n"
        "def f():\n"
        "    return _listing.text_arg('foo', '', 80)\n"
    )
    found2 = _scan_source('snippet.py', three_positional_neutral)
    assert not any(param == 'foo' for _file, param, _default in found2), (
        "text_arg('foo', '', 80) -- дефолт порожній (індекс 1), 80 -- "
        "це max_length (індекс 2), сканер не повинен сплутати їх"
    )


# --- Rule 2: дефолт, ЗАШИТИЙ у будівнику запиту -----------------------------
#
# ``_error_log_query`` і ``_leads_query`` не передають ``choice_arg``
# власного ``default`` -- він порожній і виглядає нейтрально. Звужує запит
# уже сама функція запиту, звіряючи значення з КОНКРЕТНИМ рядком
# (``'' -> 7 днів``, ``'' -> is_test=False``). Rule 1 тут мовчить: немає
# ЖОДНОГО виклику з непорожнім ``default`` для цих полів.
#
# Перевірка тут ПОВЕДІНКОВА, а не переказ умов: беремо РЕАЛЬНІ дефолтні
# фільтри (як після заходу на сторінку без жодного query-параметра) і ТОЙ
# САМИЙ будівник запиту з routes_*.py. Порівнюємо SQL типового запиту з
# тим самим запитом, де ОДНЕ поле по черзі отримує КОЖНЕ дозволене
# значення (перелік значень -- той самий, що бачить ``<select>``, дістаємо
# його підміною ``choice_arg``, а не окремим повторенням). Якщо бодай одне
# значення дає КОРОТШИЙ SQL (менше умов у WHERE/JOIN -- отже, менше
# обмежень), ніж типовий -- типовий запит обмежує зайве, і поле мусить
# бути в переліку вище.
#
# Тест НЕ знає заздалегідь, яке саме значення означає "без обмежень" (для
# ``days`` це ``'0'``, для ``test`` -- ``'with'``) -- перебір усіх
# дозволених значень знаходить це сам, без дублювання семантики поля.
_BEHAVIORAL_SITES = (
    # (модуль, ф-ція фільтрів, ф-ція запиту, чи потрібна власна base query)
    ('app.admin.routes_error_logs', '_error_log_filters', '_error_log_query', False),
    ('app.admin.routes_meta_leads', '_lead_filters', '_leads_query', False),
    ('app.admin.routes_registrations', '_registration_filters',
     '_apply_registration_filters', True),
)


def _where_part(compiled_sql):
    # ORDER BY навмисно відрізаний: 'sort' міняє лише порядок рядків, а не
    # їхню кількість, і ASC/DESC випадково дають рядок іншої довжини --
    # інакше це було б хибне спрацювання, не пов'язане з прихованим рядків.
    return compiled_sql.split(' ORDER BY')[0]


def _hidden_non_neutral_fields(app, modname, filters_name, query_name, needs_base_query):
    """Поля реєстру з нейтральним НА ВИГЛЯД дефолтом (``''`` у самому
    ``choice_arg``), для яких хоч одне дозволене значення дає МЕНШ
    обмежений запит, ніж дефолтний -- тобто дефолт насправді щось ховає.
    """
    from app.admin import _listing

    mod = importlib.import_module(modname)
    filters_func = getattr(mod, filters_name)
    query_func = getattr(mod, query_name)

    real_choice_arg = _listing.choice_arg
    calls = {}

    def _recording_choice_arg(name, allowed, default=''):
        calls[name] = (list(allowed), default)
        return real_choice_arg(name, allowed, default)

    _listing.choice_arg = _recording_choice_arg
    try:
        with app.test_request_context('/probe'):
            default_filters = filters_func()
    finally:
        _listing.choice_arg = real_choice_arg

    def _run(filters):
        if needs_base_query:
            from app.models.registration import EventRegistration
            return query_func(EventRegistration.query, dict(filters))
        return query_func(dict(filters))

    base_sql = _where_part(str(_run(default_filters)))
    findings = []
    for field, (allowed, declared_default) in calls.items():
        if declared_default != '':
            continue  # непорожній дефолт -- відповідальність Rule 1
        for value in allowed:
            variant = dict(default_filters)
            variant[field] = value
            candidate_sql = _where_part(str(_run(variant)))
            if len(candidate_sql) < len(base_sql):
                findings.append(field)
                break
    return findings


def test_hidden_query_builder_defaults_are_all_known(app):
    """Кожен фактичний (не лише оголошений) ненейтральний дефолт -- у переліку.

    ``error_logs`` і ``meta_leads`` -- саме ті два з чотирьох, де сам
    ``choice_arg`` виглядає нейтральним, а звужує запит уже функція
    запиту. Тест жодного разу не запускає SQL проти БД (даних немає й не
    треба) -- лише компілює запит у текст і порівнює довжини WHERE-частини.
    """
    missing = []
    for modname, filters_name, query_name, needs_base in _BEHAVIORAL_SITES:
        file_name = modname.rsplit('.', 1)[-1] + '.py'
        for field in _hidden_non_neutral_fields(
            app, modname, filters_name, query_name, needs_base,
        ):
            if (file_name, field) not in KNOWN_NON_NEUTRAL_DEFAULTS:
                missing.append(f"{file_name}:{field}")
    assert not missing, (
        "Новий захований ненейтральний дефолт без пояснення в "
        "KNOWN_NON_NEUTRAL_DEFAULTS (tests/test_routes/"
        "test_admin_registry_defaults.py): " + ', '.join(missing)
    )


# --- Зворотний напрямок: перелік -> код -------------------------------------
#
# Обидва тести вище перевіряють лише "код -> перелік": НОВИЙ дефолт без
# запису валить тест. Жоден з них не помічає протилежного: видали
# `elif filters['test'] != 'with': ...` з `_leads_query` чи перейменуй
# `scope` на щось інше -- обидва Rule і далі зелені (дефолта, що звужує,
# просто більше нема, скану нема чого ловити), а запис у
# KNOWN_NON_NEUTRAL_DEFAULTS лишається лежати, описуючи поведінку, якої
# в коді вже нема. Наступний автор посилання прочитає його і довіриться
# брехні саме тоді, коли перелік мав би попередити, що звуження зникло.
#
# Перевірка проста: об'єднуємо все, що РЕАЛЬНО знайшли обидва Rule (Rule 1
# -- AST, Rule 2 -- поведінково, з тим самим app), і вимагаємо, щоб КОЖЕН
# запис переліку в цьому об'єднанні був. Не знайшовся -- отже, дефолт,
# який запис описує, або видалили, або перейменували, і запис протух.
def test_known_non_neutral_defaults_still_apply(app):
    """Кожен запис KNOWN_NON_NEUTRAL_DEFAULTS -- досі реальний дефолт.

    Без цього тесту перелік -- нотатник, якому ніхто не зобов'язаний
    вірити: обидва Rule вище мовчать, коли запис описує дефолт, якого вже
    нема (видалили умову чи перейменували поле), і сам факт присутності
    запису в словнику нічого не гарантує. Тут -- навпаки напрямок: кожен
    запис мусить знайтись або серед оголошених (Rule 1), або серед
    захованих (Rule 2) дефолтів прямо зараз.
    """
    declared = {(file_name, param) for file_name, param, _default
                in _declared_non_neutral_defaults()}
    hidden = set()
    for modname, filters_name, query_name, needs_base in _BEHAVIORAL_SITES:
        file_name = modname.rsplit('.', 1)[-1] + '.py'
        for field in _hidden_non_neutral_fields(
            app, modname, filters_name, query_name, needs_base,
        ):
            hidden.add((file_name, field))
    still_real = declared | hidden

    stale = [
        f"{file_name}:{param}"
        for file_name, param in KNOWN_NON_NEUTRAL_DEFAULTS
        if (file_name, param) not in still_real
    ]
    assert not stale, (
        "Запис KNOWN_NON_NEUTRAL_DEFAULTS без відповідного дефолту в коді "
        "(tests/test_routes/test_admin_registry_defaults.py) -- дефолт, "
        "який запис описував, видалено або перейменовано, а запис "
        "лишився лежати як брехня: " + ', '.join(stale)
    )
