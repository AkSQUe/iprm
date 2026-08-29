"""Спільний інструментарій списків адмінки: фільтри, пошук, xlsx-експорт.

Кожна сторінка-список повторювала те саме: прочитати request.args, звірити
значення з переліком дозволених, зібрати ILIKE-пошук по кількох колонках,
віддати файл із таймстемпом у назві. Тут це один раз -- сторінка описує лише
власний набір полів.

Візуальний бік того самого набору полів рендерить макрос
`admin/partials/_filter_bar.html`: панель фільтрів і кнопка експорту мають
виглядати однаково на всіх списках, а посилання на експорт -- нести рівно ті
самі параметри, що й сторінка.
"""
from datetime import datetime, timedelta, timezone

from flask import current_app, flash, redirect, request, send_file, url_for
from sqlalchemy import or_

XLSX_MIMETYPE = (
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
)

# Київський час у назві файлу й у полі "Сформовано": менеджер звіряє файл із
# тим, що бачив на екрані. Фіксований UTC+3 -- як у xlsx_io / participant_service.
KYIV = timezone(timedelta(hours=3))


def now_kyiv():
    return datetime.now(KYIV)


def text_arg(name, default=''):
    """Текстовий параметр query-string, обрізаний по краях."""
    return (request.args.get(name) or default).strip()


def int_arg(name, positive=True):
    """Цілочисельний параметр або None (нечислове значення -> None).

    positive=True (типово) відкидає 0 і від'ємні: усі id у проєкті додатні,
    а ?course_id=0 інакше давав розсинхрон -- панель рахувала фільтр активним
    (чіпс + лічильник), тоді як запит його ігнорував через falsy-перевірку.
    """
    value = request.args.get(name, type=int)
    if value is None or (positive and value <= 0):
        return None
    return value


def choice_arg(name, allowed, default=''):
    """Параметр, звірений із переліком дозволених значень.

    Невідоме значення мовчки падає в default: список не має віддавати 500
    чи порожній екран через ?status=<сміття> зі старого посилання.
    """
    value = request.args.get(name, default)
    return value if value in allowed else default


# Типовий розмір сторінки довгих реєстрів.
LIST_PER_PAGE = 50

# Що можна обрати вручну. Дефолту в списку немає навмисно: порожнє значення
# і Є дефолт, інакше він дублювався б у плейсхолдері селекта.
PER_PAGE_CHOICES = ('25', '100', '200')
PER_PAGE_OPTIONS = [(n, f'{n} рядків') for n in PER_PAGE_CHOICES]


def per_page_arg(default=LIST_PER_PAGE):
    """Кількість рядків на сторінці зі списку дозволених (інакше -- дефолт).

    Свавільне ?per_page=100000 інакше клало б сторінку на прод-обсязі.
    """
    raw = choice_arg('per_page', PER_PAGE_CHOICES)
    return int(raw) if raw else default


def sort_arg(allowed, default=''):
    """Ключ сортування зі списку дозволених ('' -- типовий порядок сторінки).

    Сортування СЕРВЕРНЕ і навмисно живе поруч із фільтрами: клієнтський
    `admin-table-sort.js` переставляє лише рядки поточної сторінки, тож на
    пагінованому реєстрі «згори найдовше очікування» він обіцяє те, чого не
    робить. Ключ -- назва порядку, а не колонка з `ORDER BY`: сторінка сама
    вирішує, що саме означає її «найдовше», і жодне значення з URL не
    потрапляє в запит.
    """
    return choice_arg('sort', allowed, default)


# Пошуковий рядок довший за це -- завідомо не запит людини, а сміття з
# автопідстановки чи чужого скрипта; ILIKE по кількох колонках від нього лише
# страждає.
MAX_SEARCH_LENGTH = 100

# Стеля синхронного експорту. Понад неї файл будувався б хвилини й тримав би
# у пам'яті весь зріз, поки nginx ріже запит на 60с; тож відмовляємо явно
# (fail closed), а не віддаємо мовчки обрізаний файл.
MAX_EXPORT_ROWS = 20_000


def date_arg(name):
    """Дата з <input type="date"> як рядок YYYY-MM-DD ('' -- не задано).

    Тримаємо саме рядком: це і значення поля у формі, і параметр URL, і
    підпис чіпса. У запит вона йде через `apply_date_range`.
    """
    value = text_arg(name)
    try:
        datetime.strptime(value, '%Y-%m-%d')
    except ValueError:
        return ''
    return value


def apply_date_range(query, column, date_from='', date_to=''):
    """Звузити запит по датах включно, рахуючи КИЇВСЬКУ добу.

    Колонки зберігаються в UTC, тож «по 10.08» без переводу відрізало б
    записи з 21:00 до 24:00 київського вечора -- вони лежать уже наступною
    добою UTC.

    Перевернутий діапазон міняємо місцями: намір очевидний, а порожній
    список без пояснення виглядав би як «даних немає».
    """
    if date_from and date_to and date_from > date_to:
        date_from, date_to = date_to, date_from
    if date_from:
        start = datetime.strptime(date_from, '%Y-%m-%d').replace(tzinfo=KYIV)
        query = query.filter(column >= start)
    if date_to:
        end = (datetime.strptime(date_to, '%Y-%m-%d').replace(tzinfo=KYIV)
               + timedelta(days=1))
        query = query.filter(column < end)
    return query


def date_range_label(filters, empty='Уся'):
    """Людиночитний підпис діапазону для аркуша «Фільтри» у файлі."""
    start, end = filters.get('date_from'), filters.get('date_to')
    if not start and not end:
        return empty
    return f"{start or '...'} – {end or '...'}"


def _escape_like(term):
    """Екранувати LIKE-метасимволи: пошук '50%' має шукати '50%', а не все."""
    return (
        term.replace('\\', '\\\\')
        .replace('%', '\\%')
        .replace('_', '\\_')
    )


def search_clause(term, columns):
    """OR-ILIKE по кількох колонках; None, якщо шукати нічого."""
    term = (term or '').strip()[:MAX_SEARCH_LENGTH]
    if not term or not columns:
        return None
    pattern = f'%{_escape_like(term)}%'
    return or_(*[col.ilike(pattern, escape='\\') for col in columns])


def apply_search(query, term, columns):
    """Накласти пошук на запит (no-op для порожнього запиту)."""
    clause = search_clause(term, columns)
    return query.filter(clause) if clause is not None else query


def export_summary(pairs, rows_count):
    """Пари (назва, значення) для аркуша «Фільтри» + службові рядки.

    Без цього аркуша два вивантаження з однаковими колонками й різним
    вмістом неможливо відрізнити: файл має сам пояснювати свій зріз.
    """
    return list(pairs) + [
        ('Рядків у файлі', rows_count),
        ('Сформовано', now_kyiv().strftime('%d.%m.%Y %H:%M')),
    ]


def filter_args(filters):
    """Непорожні фільтри для URL: пілюлі, пагінація й експорт мають вести на
    той самий зріз, тож набір параметрів у них один."""
    return {key: value for key, value in filters.items() if value}


def back_args(active_filters, page, extra=None):
    """Параметри для action-URL рядкової форми (retry/delete/unlock тощо),
    що веде користувача назад на той самий зріз списку.

    active_filters -- вже звужені фільтри (`filter_args(...)`); extra --
    додаткові вже звірені параметри поза `filters` (status, instance_id).
    page додається лише коли він не 1 -- інакше кожна дія в реєстрі тягнула б
    за собою порожній ?...&page=1.
    """
    args = dict(active_filters)
    if extra:
        args.update({key: value for key, value in extra.items() if value not in (None, '')})
    if page != 1:
        args['page'] = page
    return args


def back_redirect(endpoint, filters, extra=None):
    """Безпечний POST -> GET редірект назад до списку зі збереженим зрізом.

    НЕ використовує request.referrer (керований клієнтом -> open redirect):
    будує URL через url_for з параметрів, звіданих і звірених тим самим
    способом, що й роут списку -- `filters` тут читається через ті самі
    text_arg / choice_arg / int_arg / date_arg, `extra` -- уже звірені
    значення поза `filters` (status, instance_id). Джерело значень --
    query-string самого запиту дії: рядкові форми несуть зріз в action-URL
    через `back_args()`, викликаний при рендері списку.
    """
    page = request.args.get('page', 1, type=int)
    args = back_args(filter_args(filters), page, extra)
    return redirect(url_for(endpoint, **args))


def export_query(query, back_endpoint, **back_args):
    """Матеріалізувати зріз під експорт, звіривши стелю ДО вибірки.

    Повертає пару (rows, refusal): рівно одне з двох не None. Сенс саме в
    порядку дій -- `xlsx_export` міряє вже готовий список, тож зріз на сто
    тисяч рядків спершу піднімався б у пам'ять цілком (з усіма приєднаними
    об'єктами) і лише потім отримував відмову. `COUNT(*)` коштує один запит
    і не тримає нічого.

        rows, refusal = _listing.export_query(q, 'admin.users')
        if refusal:
            return refusal
    """
    total = query.order_by(None).count()
    if total > MAX_EXPORT_ROWS:
        flash(
            f'У зрізі {total} рядків – це більше за ліміт {MAX_EXPORT_ROWS}. '
            'Звузьте фільтр (наприклад, діапазоном дат) і повторіть експорт.',
            'error',
        )
        return None, redirect(url_for(back_endpoint, **back_args))
    return query.all(), None


def xlsx_download(buf, basename):
    """Віддати BytesIO як xlsx-attachment із таймстемпом у назві."""
    return send_file(
        buf,
        mimetype=XLSX_MIMETYPE,
        as_attachment=True,
        download_name=f'{basename}-{now_kyiv().strftime("%Y%m%d-%H%M")}.xlsx',
        max_age=0,
    )


def xlsx_export(rows, basename, builder, back_endpoint, **back_args):
    """Побудувати й віддати xlsx зі стелею рядків і обробкою помилок.

    rows          -- уже вибраний зріз (список), його довжина і є стелею;
    builder       -- callable() -> io.BytesIO, будує файл;
    back_endpoint -- куди повернути, якщо віддати файл не вдалось.

    Понад MAX_EXPORT_ROWS відмовляємо явно: мовчки обрізаний файл гірший за
    відмову -- менеджер вважав би його повним і звіряв би по ньому гроші.
    Виняток під час побудови теж не має віддавати 500: користувач має
    прочитати, що сталось, і лишитись на своєму зрізі.
    """
    if len(rows) > MAX_EXPORT_ROWS:
        flash(
            f'У зрізі {len(rows)} рядків – це більше за ліміт '
            f'{MAX_EXPORT_ROWS}. Звузьте фільтр (наприклад, діапазоном дат) '
            'і повторіть експорт.',
            'error',
        )
        return redirect(url_for(back_endpoint, **back_args))
    try:
        buf = builder()
    except Exception:
        current_app.logger.exception('xlsx export failed: %s', basename)
        flash('Не вдалося сформувати файл. Спробуйте ще раз або звузьте фільтр.',
              'error')
        return redirect(url_for(back_endpoint, **back_args))
    return xlsx_download(buf, basename)
