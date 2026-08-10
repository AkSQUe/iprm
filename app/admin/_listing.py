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

from flask import request, send_file
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


def int_arg(name):
    """Цілочисельний параметр або None (нечислове значення -> None)."""
    return request.args.get(name, type=int)


def choice_arg(name, allowed, default=''):
    """Параметр, звірений із переліком дозволених значень.

    Невідоме значення мовчки падає в default: список не має віддавати 500
    чи порожній екран через ?status=<сміття> зі старого посилання.
    """
    value = request.args.get(name, default)
    return value if value in allowed else default


def _escape_like(term):
    """Екранувати LIKE-метасимволи: пошук '50%' має шукати '50%', а не все."""
    return (
        term.replace('\\', '\\\\')
        .replace('%', '\\%')
        .replace('_', '\\_')
    )


def search_clause(term, columns):
    """OR-ILIKE по кількох колонках; None, якщо шукати нічого."""
    term = (term or '').strip()
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


def xlsx_download(buf, basename):
    """Віддати BytesIO як xlsx-attachment із таймстемпом у назві."""
    return send_file(
        buf,
        mimetype=XLSX_MIMETYPE,
        as_attachment=True,
        download_name=f'{basename}-{now_kyiv().strftime("%Y%m%d-%H%M")}.xlsx',
        max_age=0,
    )
