"""Міграція course_trainers_20260910: бекфіл, відкат, захисний guard.

upgrade()/downgrade() тут не проганяємо (як і в test_migration_specialties.py
та test_migration_bpr_points_split.py) -- у тестовій схемі (create_all з
моделей, Task 1-12 вже прибрали trainer_id/speaker_info з моделей і додали
course_trainers/course_instance_trainers) `create_table` впав би на дублікаті,
а `drop_column('trainer_id')` -- на колонці, якої вже немає. Перевіряємо те,
що справді може піти не так:

* бекфіл-SQL (_backfill_sql) і SQL відкату (_restore_first_trainer_sql) --
  на тимчасових таблицях форми "до міграції", де trainer_id/speaker_info ще є;
* guard дублікатів (_duplicate_certificate_instances /
  _guard_unique_instance_restorable) -- на РЕАЛЬНІй lecturer_certificates:
  ця таблиця й пара (instance_id, trainer_id) вже такі, як після міграції
  (Task 2), тож підмінна таблиця тут не потрібна.
"""
import importlib.util
import re
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import text

from app.extensions import db
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.lecturer_certificate import LecturerCertificate
from app.models.trainer import Trainer

MIGRATION_PATH = (
    Path(__file__).resolve().parents[2] / 'migrations' / 'versions'
    / 'course_trainers_20260910.py'
)


@pytest.fixture(scope='module')
def migration():
    spec = importlib.util.spec_from_file_location('m_course_trainers', MIGRATION_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _trainer(name='Т'):
    t = Trainer(full_name=name, slug=f't-mct-{uuid4().hex[:10]}')
    db.session.add(t)
    db.session.flush()
    return t


def _course():
    c = Course(title='К', slug=f'mct-{uuid4().hex[:8]}', is_active=True)
    db.session.add(c)
    db.session.flush()
    return c


def _instance(course):
    inst = CourseInstance(course_id=course.id, status='draft')
    db.session.add(inst)
    db.session.flush()
    return inst


# --- упевнюємось, що самі тексти INSERT/UPDATE звертаються до правильних
# таблиць і колонок -- дешевий шар, дублює перевірку нижче на живих даних ---

def test_backfill_sql_targets_link_table_and_source(migration):
    sql = migration._backfill_sql('course_trainers', 'course_id', 'courses')
    assert 'INSERT INTO course_trainers' in sql
    assert 'course_id' in sql
    assert 'FROM courses' in sql
    assert 'trainer_id IS NOT NULL' in sql


def test_restore_sql_orders_by_position_and_takes_first(migration):
    """НЕ `position = 0`: position 0 не гарантований (ON DELETE CASCADE на
    course_trainers.trainer_id прибирає рядок видаленого тренера, не
    перенумеровуючи сусідів) -- SQL мусить брати НАЙМЕНШУ позицію серед
    тих, що лишились, а не буквальний нуль."""
    sql = migration._restore_first_trainer_sql(
        'courses', 'course_trainers', 'course_id',
    )
    assert 'UPDATE courses SET trainer_id' in sql
    assert 'course_trainers.position = 0' not in sql
    assert 'ORDER BY course_trainers.position' in sql
    assert 'LIMIT 1' in sql


# --- основний шар: SQL справді виконується на тимчасових таблицях "до
# міграції" (trainer_id ще колонка, а не рядок звʼязку) -----------------------

def _make_old_schema_tables():
    """Тимчасові таблиці форми "courses/course_instances до Task 13": PK id +
    trainer_id-колонка, плюс порожня таблиця звʼязку тієї самої форми, що й
    course_trainers/course_instance_trainers."""
    db.session.execute(text(
        'CREATE TABLE tmp_old_courses (id INTEGER PRIMARY KEY, trainer_id INTEGER)'
    ))
    db.session.execute(text(
        'CREATE TABLE tmp_course_trainers_link ('
        'course_id INTEGER, trainer_id INTEGER, position INTEGER)'
    ))


def test_upgrade_moves_trainer_id_to_position_zero(db_session, migration):
    """Бекфіл: наявний тренер стає головним (position=0) записом таблиці
    звʼязку, а рядок без тренера (NULL) не породжує запису взагалі."""
    _make_old_schema_tables()
    db.session.execute(text(
        'INSERT INTO tmp_old_courses (id, trainer_id) VALUES (1, 42), (2, NULL)'
    ))

    sql = migration._backfill_sql(
        'tmp_course_trainers_link', 'course_id', 'tmp_old_courses',
    )
    db.session.execute(text(sql))

    rows = db.session.execute(text(
        'SELECT course_id, trainer_id, position FROM tmp_course_trainers_link'
    )).fetchall()
    assert rows == [(1, 42, 0)]


def test_downgrade_restores_the_first_trainer(db_session, migration):
    """Дзеркально до бекфілу: UPDATE бере тренера з найменшою позицією і
    повертає його в колонку; заходу без жодного запису у звʼязку
    trainer_id лишається NULL."""
    _make_old_schema_tables()
    db.session.execute(text(
        'INSERT INTO tmp_old_courses (id, trainer_id) VALUES (10, NULL), (11, NULL)'
    ))
    db.session.execute(text(
        'INSERT INTO tmp_course_trainers_link (course_id, trainer_id, position) '
        'VALUES (10, 100, 0), (10, 200, 1), (10, 300, 2)'
    ))

    sql = migration._restore_first_trainer_sql(
        'tmp_old_courses', 'tmp_course_trainers_link', 'course_id',
    )
    db.session.execute(text(sql))

    row = db.session.execute(text(
        'SELECT trainer_id FROM tmp_old_courses WHERE id = 10'
    )).scalar()
    # Позиції 1 і 2 (тренери 200, 300) -- саме та втрата, що описана
    # коментарем у downgrade(): колонка вміщає рівно одного, і це той,
    # хто лідирує (тут -- буквально position=0).
    assert row == 100

    untouched = db.session.execute(text(
        'SELECT trainer_id FROM tmp_old_courses WHERE id = 11'
    )).scalar()
    assert untouched is None


def test_downgrade_restores_leader_when_position_zero_is_gone(db_session, migration):
    """Регресія на знахідку рев'ю: position 0 -- НЕ гарантія. Видалення
    тренера з довідника каскадно прибирає його рядок звʼязку (ON DELETE
    CASCADE, trainer_links.py), не перенумеровуючи сусідів -- захід
    [A@0, B@1] після видалення A лишає рівно [B@1], без жодного рядка на
    position=0. Фільтр "= 0" знайшов би НІЧОГО й затер би trainer_id на
    NULL, хоча B і далі головний (єдиний) тренер заходу і в базі, і за
    правилом застосунку (trainers[0] за позицією). Фікстура навмисно БЕЗ
    position=0 -- контигуальна з 0 фікстура вище цю діру не ловить."""
    _make_old_schema_tables()
    db.session.execute(text(
        'INSERT INTO tmp_old_courses (id, trainer_id) VALUES (20, NULL)'
    ))
    db.session.execute(text(
        'INSERT INTO tmp_course_trainers_link (course_id, trainer_id, position) '
        'VALUES (20, 200, 1), (20, 300, 2)'
    ))

    sql = migration._restore_first_trainer_sql(
        'tmp_old_courses', 'tmp_course_trainers_link', 'course_id',
    )
    db.session.execute(text(sql))

    row = db.session.execute(text(
        'SELECT trainer_id FROM tmp_old_courses WHERE id = 20'
    )).scalar()
    # Найменша наявна позиція -- 1 (тренер 200), НЕ NULL.
    assert row == 200


# --- guard: downgrade має впасти зрозуміло, з переліком проведень --------

def _certificate(instance, trainer, number):
    cert = LecturerCertificate(
        instance_id=instance.id, trainer_id=trainer.id, number=number,
        recipient_name='Тестовий Тестович', event_title='Захід',
    )
    db.session.add(cert)
    db.session.flush()
    return cert


def test_duplicate_certificate_instances_finds_multi_lecturer_events(db_session, migration):
    course = _course()
    inst_shared = _instance(course)
    inst_solo = _instance(course)
    a, b = _trainer('А'), _trainer('Б')

    _certificate(inst_shared, a, f'mct-{uuid4().hex[:10]}')
    _certificate(inst_shared, b, f'mct-{uuid4().hex[:10]}')
    _certificate(inst_solo, a, f'mct-{uuid4().hex[:10]}')

    duplicates = migration._duplicate_certificate_instances(db.session.get_bind())

    assert inst_shared.id in duplicates
    assert inst_solo.id not in duplicates


def test_downgrade_fails_loudly_on_multiple_lecturer_certificates(db_session, migration):
    """Ревізія має впасти зрозуміло, з переліком проведень, що заважають, а
    не помилкою БД про порушення UNIQUE."""
    course = _course()
    inst = _instance(course)
    inst_solo = _instance(course)
    a, b = _trainer('А'), _trainer('Б')
    _certificate(inst, a, f'mct-{uuid4().hex[:10]}')
    _certificate(inst, b, f'mct-{uuid4().hex[:10]}')
    _certificate(inst_solo, a, f'mct-{uuid4().hex[:10]}')

    with pytest.raises(RuntimeError) as exc_info:
        migration._guard_unique_instance_restorable(db.session.get_bind())

    message = str(exc_info.value)
    # Не просто "якесь виключення": повідомлення називає САМЕ це проведення,
    # а не переказує загальну помилку БД про порушення UNIQUE. \b, а не
    # голий `in`: текст містить revision id 'course_trainers_20260910' --
    # суцільний \w-рядок з цифрами (2026, 0910), тож маленький числовий id
    # (1, 2, 6, 9...) майже завжди трапляється в ньому ПІДРЯДКОМ, і `in`
    # проходить незалежно від того, згаданий цей id насправді, чи ні. \b
    # ловить лише самостійне число (оточене не-\w symbolами), а не цифру
    # всередині сусіднього \w-рядка.
    assert re.search(rf'\b{inst.id}\b', message)
    assert 'UNIQUE' in message
    # І не просто "якийсь текст містить цифри": id проведення БЕЗ дублікатів
    # не має потрапити в повідомлення. Той самий \b з тієї самої причини --
    # інакше `assert str(inst_solo.id) not in message` міг би хибно ЗНАЙТИ
    # inst_solo.id підрядком у 'course_trainers_20260910' і провалити
    # перевірку на цілком справному коді.
    assert not re.search(rf'\b{inst_solo.id}\b', message)


def test_guard_passes_when_every_instance_has_one_certificate(db_session, migration):
    course = _course()
    inst = _instance(course)
    a = _trainer('А')
    _certificate(inst, a, f'mct-{uuid4().hex[:10]}')

    # Не мусить кинути -- жодного проведення з двома сертифікатами немає.
    migration._guard_unique_instance_restorable(db.session.get_bind())
