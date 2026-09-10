"""XLSX-імпорт: межі значень, нескінченності, тезки й зниклі сутності.

Спільна нитка всіх цих випадків одна. Розбір файлу вміє акуратно звітувати
про помилку КОНКРЕТНОГО рядка, і саме цього менеджер очікує. Але кілька
перевірок жили лише в CHECK-обмеженнях БД, тож рядок із max_participants=0
проходив розбір, доходив до commit() і валив УВЕСЬ імпорт -- разом із
сотнею сусідніх, ні в чому не винних рядків. Тести нижче фіксують, що
кожне таке порушення лишається помилкою свого рядка.
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from openpyxl import Workbook

from app.extensions import db
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.trainer import Trainer
from app.services import xlsx_io


# --- фікстури -----------------------------------------------------------

def _trainer(**kw):
    kw.setdefault('full_name', f'Тренер {uuid4().hex[:6]}')
    t = Trainer(slug=f'tr-{uuid4().hex[:8]}', **kw)
    db.session.add(t)
    db.session.commit()
    return t


def _course(**kw):
    kw.setdefault('title', f'Курс {uuid4().hex[:4]}')
    c = Course(slug=f'x-{uuid4().hex[:6]}', event_type='course',
               is_active=True, base_price=0, **kw)
    db.session.add(c)
    db.session.commit()
    return c


def _instance(course, **kw):
    kw.setdefault('start_date', datetime.now(timezone.utc) + timedelta(days=30))
    kw.setdefault('status', 'published')
    kw.setdefault('event_format', 'offline')
    inst = CourseInstance(course_id=course.id, **kw)
    db.session.add(inst)
    db.session.commit()
    return inst


def _write_courses_file(tmp_path, rows):
    wb = Workbook()
    ws = wb.active
    ws.title = 'Курси'
    cols = xlsx_io.COURSE_COLS
    ws.append([xlsx_io.COURSE_LABELS[c] for c in cols])
    for row in rows:
        ws.append([row.get(c, '') for c in cols])
    path = tmp_path / f'courses-{uuid4().hex[:6]}.xlsx'
    wb.save(path)
    return path


def _write_instances_file(tmp_path, rows):
    wb = Workbook()
    ws = wb.active
    ws.title = 'Розклад'
    cols = xlsx_io.INSTANCE_COLS
    ws.append([xlsx_io.INSTANCE_LABELS[c] for c in cols])
    for row in rows:
        ws.append([row.get(c, '') for c in cols])
    path = tmp_path / f'inst-{uuid4().hex[:6]}.xlsx'
    wb.save(path)
    return path


def _course_row(course, **overrides):
    row = {
        'id': course.id, 'slug': course.slug, 'title': course.title,
        'event_type': 'Курс', 'base_price': 0,
        'is_active': True, 'is_featured': False,
    }
    row.update(overrides)
    return row


def _instance_row(course, inst, **overrides):
    row = {
        'id': inst.id, 'course_slug': course.slug,
        'start_date': xlsx_io._to_kyiv_naive(
            datetime.now(timezone.utc) + timedelta(days=30)),
        'event_format': 'Офлайн', 'status': 'Опубліковано',
    }
    row.update(overrides)
    return row


# --- перетворювачі значень ------------------------------------------------

def test_decimal_rejects_infinity():
    """Decimal('Infinity') -- валідне значення Decimal, і саме тому небезпечне:
    порівняння `Infinity < 0` повертає False, тобто перевірку меж воно
    ПРОХОДИТЬ і падає аж на commit, забираючи з собою весь імпорт."""
    for raw in ('Infinity', '-Infinity', 'inf'):
        with pytest.raises(ValueError, match='не число'):
            xlsx_io._decimal(raw)


def test_huge_but_finite_number_is_caught_by_the_column_limit():
    """`Decimal('1e400')` СКІНЧЕННЕ, тож is_finite() його пропускає -- і саме
    тому потрібна верхня межа: Numeric(10,2) відхилив би його на commit."""
    assert xlsx_io._decimal('1e400').is_finite()
    with pytest.raises(ValueError, match='більше за дозволене'):
        xlsx_io._check_min_values({'base_price': xlsx_io._decimal('1e400')})


def test_decimal_rejects_nan():
    with pytest.raises(ValueError, match='не число'):
        xlsx_io._decimal('NaN')


def test_decimal_still_accepts_normal_values():
    assert xlsx_io._decimal('1 250,50') == Decimal('1250.50')
    assert xlsx_io._decimal('') is None
    assert xlsx_io._decimal(None) is None


def test_int_reports_overflow_as_row_error():
    """int(float('1e400')) кидає OverflowError, якого не було в except-кортежі,
    тож нагору йшов англомовний внутрішній текст замість нашого рядка."""
    with pytest.raises(ValueError, match='не ціле число'):
        xlsx_io._int('1e400')


# --- межі значень ---------------------------------------------------------

def test_check_min_values_mirrors_every_model_constraint():
    """Перелік меж має покривати всі CHECK-обмеження обох моделей -- інакше
    вони знову розійдуться, і розходження побачить лише прод."""
    for field, bad in (
        ('base_price', Decimal('-1')),
        ('price', Decimal('-1')),
        ('cpd_points_online', Decimal('-0.5')),
        ('cpd_points_offline', Decimal('-0.5')),
        ('max_participants', 0),
    ):
        with pytest.raises(ValueError):
            xlsx_io._check_min_values({field: bad})


def test_check_min_values_skips_empty():
    xlsx_io._check_min_values({'max_participants': None, 'price': None})


def test_course_zero_seats_is_a_row_error_not_an_import_abort(app, tmp_path):
    """Ключовий випадок. Раніше такий рядок проходив розбір і валив commit --
    разом з усіма сусідніми рядками файлу."""
    good = _course()
    bad = _course()
    path = _write_courses_file(tmp_path, [
        _course_row(good),
        _course_row(bad, max_participants=0),
    ])
    plan = xlsx_io.parse_courses_xlsx(path)

    assert not plan.is_valid
    assert any('місць' in e and 'менше за дозволене' in e
               for e in plan.errors), plan.errors
    # Помилка адресна: винен рядок 3, а не файл цілком.
    assert any('Рядок 3' in e for e in plan.errors), plan.errors


def test_course_negative_points_is_a_row_error(app, tmp_path):
    course = _course()
    path = _write_courses_file(tmp_path, [
        _course_row(course, cpd_points_online=-2),
    ])
    plan = xlsx_io.parse_courses_xlsx(path)
    assert not plan.is_valid
    assert any('бали БПР' in e and 'менше за дозволене' in e
               for e in plan.errors), plan.errors


def test_instance_negative_price_is_a_row_error(app, tmp_path):
    """Аркуш Розклад не перевіряв ЖОДНОЇ зі своїх чотирьох меж."""
    course = _course()
    inst = _instance(course)
    path = _write_instances_file(tmp_path, [
        _instance_row(course, inst, price=-5),
    ])
    plan = xlsx_io.parse_instances_xlsx(path)
    assert not plan.is_valid
    assert any('ціна' in e for e in plan.errors), plan.errors


def test_instance_zero_seats_is_a_row_error(app, tmp_path):
    course = _course()
    inst = _instance(course)
    path = _write_instances_file(tmp_path, [
        _instance_row(course, inst, max_participants=0),
    ])
    plan = xlsx_io.parse_instances_xlsx(path)
    assert not plan.is_valid
    assert any('місць' in e and 'менше за дозволене' in e
               for e in plan.errors), plan.errors


# --- тезки серед тренерів -------------------------------------------------

def test_same_full_name_demands_slug_instead_of_guessing():
    """ПІБ не унікальне в БД. Словник «ПІБ -> id» мовчки лишав останнього
    тезку, тож клітинка прив'язувала довільного з двох, і побачити це можна
    було лише на сайті."""
    a = _trainer(full_name='Іваненко І. І.')
    b = _trainer(full_name='Іваненко І. І.')
    by_slug, by_name, ambiguous = xlsx_io.build_trainer_lookup([a, b])

    assert 'Іваненко І. І.' in ambiguous
    assert 'Іваненко І. І.' not in by_name  # жодного мовчазного вибору

    with pytest.raises(ValueError, match='однакове ПІБ'):
        xlsx_io._resolve_trainer_ids('Іваненко І. І.', by_slug, by_name, ambiguous)

    # slug унікальний -- ним однозначно вказати можна.
    assert xlsx_io._resolve_trainer_ids(b.slug, by_slug, by_name, ambiguous) == [b.id]


def test_duplicate_in_one_cell_is_deduped_like_set_trainers():
    """`set_trainers` дедуплікує на записі. Без дзеркальної поведінки тут
    клітинка з повтореним іменем НАЗАВЖДИ показувала б «змінено» у прев'ю:
    розібраний список ніколи не збігся б із дедуплікованим збереженим."""
    a = _trainer()
    b = _trainer()
    by_slug, by_name, ambiguous = xlsx_io.build_trainer_lookup([a, b])

    ids = xlsx_io._resolve_trainer_ids(
        f'{a.slug}; {b.slug}; {a.slug}', by_slug, by_name, ambiguous,
    )
    assert ids == [a.id, b.id]  # порядок першого входження збережено


# --- зникла сутність між прев'ю і застосуванням ---------------------------

def test_course_deleted_between_preview_and_apply_is_skipped(app, tmp_path):
    """План будується на знімку БД і чекає підтвердження людини. Якщо курс за
    цей час видалили, db.session.get поверне None -- і без перевірки наступний
    рядок звалював AttributeError, відкочуючи ВЕСЬ імпорт."""
    survivor = _course()
    doomed = _course()
    path = _write_courses_file(tmp_path, [
        _course_row(survivor, title='Вижив'),
        _course_row(doomed, title='Зник'),
    ])
    plan = xlsx_io.parse_courses_xlsx(path)
    assert plan.is_valid, plan.errors

    doomed_slug = doomed.slug
    db.session.delete(doomed)
    db.session.commit()

    result = xlsx_io.apply_courses_plan(plan)

    assert result['ok'] is True, result
    assert result['vanished'] == [doomed_slug]
    assert db.session.get(Course, survivor.id).title == 'Вижив'


def test_apply_failure_does_not_leak_database_internals(app, tmp_path, monkeypatch):
    """У reason не має бути фрагментів SQL і назв колонок: це відповідь на
    завантажений користувачем файл."""
    course = _course()
    path = _write_courses_file(tmp_path, [_course_row(course)])
    plan = xlsx_io.parse_courses_xlsx(path)
    assert plan.is_valid, plan.errors

    def boom(*_a, **_kw):
        raise RuntimeError('relation "courses" column "secret_column" blew up')

    monkeypatch.setattr(xlsx_io.db.session, 'commit', boom)
    result = xlsx_io.apply_courses_plan(plan)

    assert result['ok'] is False
    assert 'secret_column' not in result['reason']
    assert 'Дані не змінено' in result['reason']
