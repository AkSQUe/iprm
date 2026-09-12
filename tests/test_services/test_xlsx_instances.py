"""XLSX розкладу: експорт, розбір, застосування.

Цей імпортер пише в course_instances (дати, ціни, статуси проведень) і не
мав жодного тесту. Саме такий пробіл минулого разу дозволив зламаному
імпорту курсів прожити місяці непоміченим.
"""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from openpyxl import Workbook, load_workbook

from app.extensions import db
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.trainer import Trainer
from app.services import xlsx_io

KYIV = xlsx_io.KYIV


def _course(**kw):
    kw.setdefault('title', f'Курс {uuid4().hex[:4]}')
    c = Course(slug=f'i-{uuid4().hex[:6]}', event_type='course',
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


def _write(tmp_path, rows, drop_columns=()):
    wb = Workbook()
    ws = wb.active
    ws.title = 'Розклад'
    cols = [c for c in xlsx_io.INSTANCE_COLS if c not in drop_columns]
    ws.append([xlsx_io.INSTANCE_LABELS[c] for c in cols])
    for row in rows:
        ws.append([row.get(c, '') for c in cols])
    path = tmp_path / f'sch-{uuid4().hex[:6]}.xlsx'
    wb.save(path)
    return path


def _row(course, **overrides):
    row = {
        'course_slug': course.slug,
        'start_date': (datetime.now(timezone.utc) + timedelta(days=30))
        .astimezone(KYIV).replace(tzinfo=None).isoformat(),
        'event_format': 'Офлайн',
        'status': 'Опубліковано',
        'location': 'Харків',
    }
    row.update(overrides)
    return row


# --- узгодженість формату ---------------------------------------------------

def test_export_header_matches_column_list(client):
    _instance(_course())
    ws = load_workbook(xlsx_io.export_instances_xlsx())['Розклад']
    header = [c.value for c in ws[1]]
    assert header == [xlsx_io.INSTANCE_LABELS[c] for c in xlsx_io.INSTANCE_COLS]


def test_export_values_align_with_columns(client):
    course = _course()
    # Дзеркалимо міграційний бекфіл (cpd_points_online = cpd_points_offline =
    # cpd_points): експорт читає лише нові розщеплені колонки, легасі
    # cpd_points для нього більше не джерело значення.
    _instance(course, location='Полтава', price=5000,
              cpd_points_online=12, cpd_points_offline=12)
    ws = load_workbook(xlsx_io.export_instances_xlsx())['Розклад']
    header = [c.value for c in ws[1]]
    rows = [dict(zip(header, r)) for r in ws.iter_rows(min_row=2, values_only=True)]
    row = next(r for r in rows if r[xlsx_io.INSTANCE_LABELS['course_slug']] == course.slug)
    assert row[xlsx_io.INSTANCE_LABELS['location']] == 'Полтава'
    assert row[xlsx_io.INSTANCE_LABELS['cpd_points_online']] == 12
    assert row[xlsx_io.INSTANCE_LABELS['cpd_points_offline']] == 12


# --- створення й оновлення --------------------------------------------------

def test_import_creates_instance(client, tmp_path):
    course = _course()
    path = _write(tmp_path, [_row(course, location='Львів')])

    plan = xlsx_io.parse_instances_xlsx(path)
    assert plan.is_valid, plan.errors
    assert plan.counts['create'] == 1
    assert xlsx_io.apply_instances_plan(plan)['ok']

    inst = CourseInstance.query.filter_by(course_id=course.id).one()
    assert inst.location == 'Львів'
    assert inst.status == 'published'
    assert inst.event_format == 'offline'


def test_existing_instance_row_does_not_error(client, tmp_path):
    """Той самий клас, що зламав імпорт курсів: _diff_* по неіснуючому полю."""
    course = _course()
    inst = _instance(course, location='Харків')
    path = _write(tmp_path, [_row(course, id=inst.id, location='Одеса')])

    plan = xlsx_io.parse_instances_xlsx(path)
    assert plan.is_valid, plan.errors
    assert not any(ch.action == 'error' for ch in plan.changes)
    assert xlsx_io.apply_instances_plan(plan)['ok']
    assert db.session.get(CourseInstance, inst.id).location == 'Одеса'


def test_unchanged_row_reported_as_unchanged(client, tmp_path):
    """Регресія: naive/aware дати робили кожне проведення "оновити" на SQLite."""
    course = _course()
    start = datetime.now(timezone.utc) + timedelta(days=30)
    inst = _instance(course, start_date=start, location='Харків')

    path = _write(tmp_path, [_row(
        course, id=inst.id, location='Харків',
        start_date=start.astimezone(KYIV).replace(tzinfo=None).isoformat(),
    )])
    change = next(ch for ch in xlsx_io.parse_instances_xlsx(path).changes
                  if ch.course_slug == course.slug)
    assert change.action == 'unchanged', change.fields_changed


def test_diff_reports_changed_date(client, tmp_path):
    course = _course()
    inst = _instance(course)
    later = (inst.start_date + timedelta(days=7)).astimezone(KYIV).replace(tzinfo=None)
    path = _write(tmp_path, [_row(course, id=inst.id, start_date=later.isoformat())])

    change = next(ch for ch in xlsx_io.parse_instances_xlsx(path).changes
                  if ch.course_slug == course.slug)
    assert change.action == 'update'
    assert 'start_date' in change.fields_changed


# --- валідація --------------------------------------------------------------

def test_unknown_course_slug_is_error(client, tmp_path):
    path = _write(tmp_path, [_row(_course(), course_slug='no-such-course')])
    plan = xlsx_io.parse_instances_xlsx(path)
    assert not plan.is_valid
    assert any('не існує' in e for e in plan.errors)


def test_end_before_start_is_error(client, tmp_path):
    course = _course()
    start = datetime.now(timezone.utc) + timedelta(days=30)
    path = _write(tmp_path, [_row(
        course,
        start_date=start.astimezone(KYIV).replace(tzinfo=None).isoformat(),
        end_date=(start - timedelta(days=1)).astimezone(KYIV)
        .replace(tzinfo=None).isoformat(),
    )])
    plan = xlsx_io.parse_instances_xlsx(path)
    assert not plan.is_valid
    assert any('пізніше' in e for e in plan.errors)


def test_unknown_status_is_error(client, tmp_path):
    path = _write(tmp_path, [_row(_course(), status='Невідомо')])
    plan = xlsx_io.parse_instances_xlsx(path)
    assert not plan.is_valid


def test_nonexistent_id_is_error(client, tmp_path):
    path = _write(tmp_path, [_row(_course(), id=999999)])
    plan = xlsx_io.parse_instances_xlsx(path)
    assert not plan.is_valid
    assert any('не існує' in e for e in plan.errors)


def test_missing_column_is_error(client, tmp_path):
    path = _write(tmp_path, [_row(_course())], drop_columns=('status',))
    plan = xlsx_io.parse_instances_xlsx(path)
    assert not plan.is_valid
    assert any('Статус' in e for e in plan.errors)


def test_missing_sheet_is_error(client, tmp_path):
    wb = Workbook()
    wb.active.title = 'Не той лист'
    path = tmp_path / 'wrong.xlsx'
    wb.save(path)
    plan = xlsx_io.parse_instances_xlsx(path)
    assert not plan.is_valid
    assert any('Розклад' in e for e in plan.errors)


def test_invalid_plan_is_not_applied(client, tmp_path):
    course = _course()
    path = _write(tmp_path, [_row(course, status='Невідомо')])
    plan = xlsx_io.parse_instances_xlsx(path)
    assert xlsx_io.apply_instances_plan(plan)['ok'] is False
    assert CourseInstance.query.filter_by(course_id=course.id).count() == 0


def test_trainer_resolved_by_name_and_slug(client, tmp_path):
    """Колонка trainer_slugs приймає і ПІБ, і slug для одного тренера --
    список з єдиним елементом."""
    course = _course()
    trainer = Trainer(slug=f'tr-{uuid4().hex[:6]}', full_name='Тренер Розкладу')
    db.session.add(trainer)
    db.session.commit()

    for value in (trainer.full_name, trainer.slug):
        path = _write(tmp_path, [_row(course, trainer_slugs=value)])
        plan = xlsx_io.parse_instances_xlsx(path)
        assert plan.is_valid, plan.errors
        assert plan.instances[0]['parsed']['trainer_ids'] == [trainer.id]


# --- тема проведення --------------------------------------------------------

def test_export_carries_the_topic(client):
    course = _course()
    _instance(course, topic='PRP у практиці ортопеда')
    ws = load_workbook(xlsx_io.export_instances_xlsx())['Розклад']
    header = [c.value for c in ws[1]]
    rows = [dict(zip(header, r)) for r in ws.iter_rows(min_row=2, values_only=True)]
    row = next(r for r in rows if r[xlsx_io.INSTANCE_LABELS['course_slug']] == course.slug)
    assert row[xlsx_io.INSTANCE_LABELS['topic']] == 'PRP у практиці ортопеда'


def test_import_sets_the_topic(client, tmp_path):
    course = _course()
    inst = _instance(course)
    path = _write(tmp_path, [_row(course, id=inst.id, topic='PRP у практиці ортопеда')])
    plan = xlsx_io.parse_instances_xlsx(path)
    assert plan.is_valid, plan.errors
    xlsx_io.apply_instances_plan(plan)
    assert db.session.get(CourseInstance, inst.id).topic == 'PRP у практиці ортопеда'


def test_empty_cell_clears_the_topic(client, tmp_path):
    """Порожня комірка -- це «зняти тему», і захід вертається до назви курсу.
    У БД має лягти NULL, а не порожній рядок."""
    course = _course()
    inst = _instance(course, topic='Стара тема')
    path = _write(tmp_path, [_row(course, id=inst.id, topic='')])
    plan = xlsx_io.parse_instances_xlsx(path)
    xlsx_io.apply_instances_plan(plan)
    saved = db.session.get(CourseInstance, inst.id)
    assert saved.topic is None
    assert saved.effective_title == course.title


def test_old_file_without_the_column_keeps_the_topic(client, tmp_path):
    """Файл, вивантажений до появи колонки, не має стирати теми: менеджери
    тримають такі файли на руках (та сама причина, що й у OPTIONAL_COURSE_COLS).
    """
    course = _course()
    inst = _instance(course, topic='PRP у практиці ортопеда')
    path = _write(tmp_path, [_row(course, id=inst.id)], drop_columns=('topic',))
    plan = xlsx_io.parse_instances_xlsx(path)
    assert plan.is_valid, plan.errors
    xlsx_io.apply_instances_plan(plan)
    assert db.session.get(CourseInstance, inst.id).topic == 'PRP у практиці ортопеда'


def test_changed_topic_shows_up_in_the_plan(client, tmp_path):
    course = _course()
    inst = _instance(course, topic='Стара тема')
    path = _write(tmp_path, [_row(course, id=inst.id, topic='Нова тема')])
    plan = xlsx_io.parse_instances_xlsx(path)
    change = plan.changes[0]
    assert change.action == 'update'
    assert 'topic' in change.fields_changed


# --- вид заходу БПР для конкретної дати -------------------------------------

def _exported_row(course):
    ws = load_workbook(xlsx_io.export_instances_xlsx())['Розклад']
    header = [c.value for c in ws[1]]
    rows = [dict(zip(header, r)) for r in ws.iter_rows(min_row=2, values_only=True)]
    return next(r for r in rows
                if r[xlsx_io.INSTANCE_LABELS['course_slug']] == course.slug)


def test_export_carries_the_event_type_override(client):
    course = _course()
    _instance(course, event_type='training')
    row = _exported_row(course)
    assert row[xlsx_io.INSTANCE_LABELS['event_type']] == 'Тренінг'


def test_export_leaves_the_cell_empty_when_type_is_inherited(client):
    """Порожньо -- «як у курсу», а не назва курсового виду.

    Друкувати успадкований вид означало б, що перше ж вивантаження й
    завантаження назад запише курсовий тип у КОЖНУ дату твердою копією --
    і наступна зміна виду курсу вже нікуди не дійде.
    """
    course = _course()          # event_type='course'
    _instance(course)
    row = _exported_row(course)
    # openpyxl віддає порожню клітинку як None, а не ''.
    assert not row[xlsx_io.INSTANCE_LABELS['event_type']]


def test_import_sets_the_event_type_override(client, tmp_path):
    course = _course()
    inst = _instance(course)
    path = _write(tmp_path, [_row(course, id=inst.id, event_type='Тренінг')])
    plan = xlsx_io.parse_instances_xlsx(path)
    assert plan.is_valid, plan.errors
    xlsx_io.apply_instances_plan(plan)
    assert db.session.get(CourseInstance, inst.id).event_type == 'training'


def test_import_accepts_the_internal_code_too(client, tmp_path):
    course = _course()
    inst = _instance(course)
    path = _write(tmp_path, [_row(course, id=inst.id, event_type='training')])
    plan = xlsx_io.parse_instances_xlsx(path)
    assert plan.is_valid, plan.errors
    xlsx_io.apply_instances_plan(plan)
    assert db.session.get(CourseInstance, inst.id).event_type == 'training'


def test_empty_cell_clears_the_override(client, tmp_path):
    """Порожня комірка -- «зняти перевизначення», у БД NULL, не ''."""
    course = _course()
    inst = _instance(course, event_type='training')
    path = _write(tmp_path, [_row(course, id=inst.id, event_type='')])
    plan = xlsx_io.parse_instances_xlsx(path)
    xlsx_io.apply_instances_plan(plan)
    saved = db.session.get(CourseInstance, inst.id)
    assert saved.event_type is None
    assert saved.effective_event_type == course.event_type


def test_old_file_without_the_column_keeps_the_override(client, tmp_path):
    course = _course()
    inst = _instance(course, event_type='training')
    path = _write(tmp_path, [_row(course, id=inst.id)],
                  drop_columns=('event_type',))
    plan = xlsx_io.parse_instances_xlsx(path)
    assert plan.is_valid, plan.errors
    xlsx_io.apply_instances_plan(plan)
    assert db.session.get(CourseInstance, inst.id).event_type == 'training'


def test_changed_event_type_shows_up_in_the_plan(client, tmp_path):
    course = _course()
    inst = _instance(course, event_type='training')
    path = _write(tmp_path, [_row(course, id=inst.id,
                                  event_type='Фахова (тематична) школа')])
    plan = xlsx_io.parse_instances_xlsx(path)
    change = plan.changes[0]
    assert change.action == 'update'
    assert 'event_type' in change.fields_changed


def test_unknown_event_type_is_error(client, tmp_path):
    course = _course()
    path = _write(tmp_path, [_row(course, event_type='Файна вечірка')])
    plan = xlsx_io.parse_instances_xlsx(path)
    assert not plan.is_valid
    assert any('event_type' in e for e in plan.errors)


def test_round_trip_keeps_inheritance_intact(client, tmp_path):
    """Вивантажити й одразу завантажити назад не мусить чіпати вид заходу.

    Про start_date тут не йдеться свідомо: на SQLite колонка
    DateTime(timezone=True) читається naive, тож _to_kyiv_naive в експорті --
    no-op, а імпорт трактує naive як Київ і дає зсув на 3 години. На
    PostgreSQL (прод) колонка aware і зсуву немає, тож перевіряти тут увесь
    рядок означало б закріпити артефакт тестової БД.
    """
    course = _course()
    inst = _instance(course)
    exported = tmp_path / 'sch-roundtrip.xlsx'
    exported.write_bytes(xlsx_io.export_instances_xlsx().getvalue())

    plan = xlsx_io.parse_instances_xlsx(exported)
    assert plan.is_valid, plan.errors
    change = next(c for c in plan.changes if c.line_no and c.action != 'error')
    assert 'event_type' not in (change.fields_changed or [])

    xlsx_io.apply_instances_plan(plan)
    assert db.session.get(CourseInstance, inst.id).event_type is None


def test_optional_columns_are_real_columns_of_the_sheet(client):
    """Перелік опційних тепер виводиться з таблиці розбирачів, тож розійтись
    з нею не може. Лишається помилка друку в самій назві -- її й ловимо."""
    assert set(xlsx_io.OPTIONAL_INSTANCE_COLS) <= set(xlsx_io.INSTANCE_COLS)


def test_import_sets_the_event_type_on_a_brand_new_instance(client, tmp_path):
    """Створення (порожній id), а не правка: інша гілка apply_instances_plan."""
    course = _course()
    path = _write(tmp_path, [_row(course, event_type='Тренінг')])
    plan = xlsx_io.parse_instances_xlsx(path)
    assert plan.is_valid, plan.errors
    assert xlsx_io.apply_instances_plan(plan)['created'] == 1

    created = (CourseInstance.query
               .filter_by(course_id=course.id)
               .order_by(CourseInstance.id.desc()).first())
    assert created.event_type == 'training'


def test_schedule_type_dropdown_allows_a_blank_cell(client):
    """Порожня клітинка тут має власне значення «як у курсу».

    Заборона порожнього (як у решти випадайок розкладу) змусила б проставити
    вид у кожну дату руками -- саме те, від чого колонка й рятує.
    """
    _instance(_course())
    ws = load_workbook(xlsx_io.export_instances_xlsx())['Розклад']
    from openpyxl.utils import get_column_letter
    letter = get_column_letter(xlsx_io.INSTANCE_COLS.index('event_type') + 1)

    by_column = {dv: str(dv.sqref) for dv in ws.data_validations.dataValidation}
    ours = [dv for dv, ref in by_column.items() if ref.startswith(f'{letter}2')]
    assert ours, f'на колонці {letter} немає data-validation'
    assert ours[0].allow_blank is True

    fmt_letter = get_column_letter(
        xlsx_io.INSTANCE_COLS.index('event_format') + 1)
    others = [dv for dv, ref in by_column.items()
              if ref.startswith(f'{fmt_letter}2')]
    assert others and others[0].allow_blank is False, (
        'решта випадайок розкладу порожнього приймати не мусить')


def test_export_writes_the_canonical_ukrainian_name_in_any_locale(client):
    """Файл -- контракт, а не переклад.

    Експорт бере base_name, а не label: адмін, що працює в російській чи
    англійській локалі, інакше вивантажив би назви, яких імпорт не приймає.
    """
    from flask_babel import force_locale

    from app.models.event_type import EventType
    from app.services import event_types

    # Без ЖИВОГО перекладу рядка довідника перевірка порожня: label()
    # тоді й сам відкочується на українську назву, і зламаний експорт
    # (label замість base_name) пройшов би непоміченим.
    row_en = EventType.query.filter_by(code='training').one()
    saved = row_en.translations
    row_en.translations = dict(saved or {}, en={'name': 'Training'})
    db.session.commit()
    event_types.reset_cache()
    try:
        course = _course()
        _instance(course, event_type='training')
        with force_locale('en'):
            assert event_types.label('training') == 'Training', (
                'переклад не живий -- перевірка була б порожньою')
            row = _exported_row(course)
        assert row[xlsx_io.INSTANCE_LABELS['event_type']] == 'Тренінг'
    finally:
        row_en.translations = saved
        db.session.commit()
        event_types.reset_cache()
