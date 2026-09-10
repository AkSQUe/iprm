"""Міграція bpr_points_split_20260909.

Саму upgrade() тут не проганяємо: у тестовій схемі (create_all з моделей)
нові колонки вже є, тож add_column упав би на дублікаті. Перевіряємо те, що
справді може піти не так, -- перенесення даних.

Живу базу (dev) на момент написання цих тестів проштампувати міграцією
неможливо: вона стоїть на ревізії з паралельного воркітрі, якої немає в цій
історії (див. task-11-report.md). Тому підрядкові перевірки згенерованого
SQL (нижче) лишаються ДЕШЕВИМ додатковим шаром, а основним сторожем стають
тести, які цей SQL СПРАВДІ виконують -- на тимчасових таблицях для
copy/collapse (де реальна таблиця вже втратила legacy-колонку cpd_points) і
на реальних ORM-таблицях для бекфілу формату (там усі потрібні колонки вже є
в моделях).
"""
import importlib.util
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import text

from app.extensions import db
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.instance_tariff import InstanceTariff
from app.models.registration import EventRegistration
from app.models.user import User

MIGRATION_PATH = (
    Path(__file__).resolve().parents[2] / 'migrations' / 'versions'
    / 'bpr_points_split_20260909_add_format_columns.py'
)


@pytest.fixture(scope='module')
def migration():
    spec = importlib.util.spec_from_file_location('m_points_split', MIGRATION_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# --- дешевий додатковий шар: текст запиту -----------------------------------

def test_copies_old_value_into_both_columns(migration):
    for table in ('courses', 'course_instances'):
        sql = migration.copy_points_sql(table)
        assert 'cpd_points_online = cpd_points' in sql
        assert 'cpd_points_offline = cpd_points' in sql
        assert table in sql


def test_backfill_takes_format_from_tariff(migration):
    sql = migration.participation_format_backfill_sql()
    assert 'instance_tariffs' in sql
    assert 'event_format' in sql
    # Тільки задані формати: NULL у тарифі не має ставати рядком.
    assert "IN ('online', 'offline')" in sql


def test_downgrade_keeps_offline_value(migration):
    sql = migration.collapse_points_sql('courses')
    assert 'cpd_points = cpd_points_offline' in sql


# --- основний шар: SQL справді виконується ----------------------------------
#
# `copy_points_sql` / `collapse_points_sql` перевіряються на тимчасовій
# таблиці, а не на `courses`/`course_instances`: у поточній схемі (моделі
# вже без legacy-колонки, Task 10) реальні таблиці не мають колонки
# `cpd_points`, тож запит просто не мав би на чому виконатись.

def _make_points_table():
    """Тимчасова таблиця форми "до міграції": стара колонка + дві нові."""
    db.session.execute(text(
        'CREATE TABLE tmp_points_migration ('
        'id INTEGER PRIMARY KEY, '
        'cpd_points NUMERIC(5, 2), '
        'cpd_points_online NUMERIC(5, 2), '
        'cpd_points_offline NUMERIC(5, 2))'
    ))


def _row(table, row_id):
    return db.session.execute(
        text(f'SELECT cpd_points, cpd_points_online, cpd_points_offline '
             f'FROM {table} WHERE id = :id'),
        {'id': row_id},
    ).mappings().one()


def test_copy_points_sql_fills_both_columns_from_existing_value(migration):
    _make_points_table()
    db.session.execute(text(
        'INSERT INTO tmp_points_migration (id, cpd_points) VALUES (1, 12)'
    ))
    db.session.execute(text(migration.copy_points_sql('tmp_points_migration')))

    row = _row('tmp_points_migration', 1)
    assert float(row['cpd_points_online']) == 12
    assert float(row['cpd_points_offline']) == 12


def test_copy_points_sql_leaves_null_as_null_not_zero(migration):
    """NULL має лишитись NULL: WHERE cpd_points IS NOT NULL боронить від 0."""
    _make_points_table()
    db.session.execute(text(
        'INSERT INTO tmp_points_migration (id, cpd_points) VALUES (2, NULL)'
    ))
    db.session.execute(text(migration.copy_points_sql('tmp_points_migration')))

    row = _row('tmp_points_migration', 2)
    assert row['cpd_points_online'] is None
    assert row['cpd_points_offline'] is None


def test_collapse_points_sql_takes_offline_value(migration):
    """downgrade() зводить пару в одну колонку саме ОФЛАЙНОВИМ значенням."""
    _make_points_table()
    db.session.execute(text(
        'INSERT INTO tmp_points_migration '
        '(id, cpd_points_online, cpd_points_offline) VALUES (3, 4.5, 7.5)'
    ))
    db.session.execute(text(migration.collapse_points_sql('tmp_points_migration')))

    row = _row('tmp_points_migration', 3)
    assert float(row['cpd_points']) == 7.5


# --- основний шар: бекфіл participation_format ------------------------------
#
# Виконується на реальних ORM-таблицях: `event_registrations.tariff_id`,
# `event_registrations.participation_format` та `instance_tariffs.event_format`
# уже є в поточних моделях (Task 3), тож підмінна таблиця тут не потрібна.

def _course_instance():
    course = Course(title=f'К {uuid4().hex[:4]}', slug=f'pts-{uuid4().hex[:6]}',
                     is_active=True, event_type='course')
    db.session.add(course)
    db.session.flush()
    inst = CourseInstance(
        course_id=course.id, status='completed', event_format='hybrid',
        start_date=datetime.now(timezone.utc) - timedelta(days=5),
    )
    db.session.add(inst)
    db.session.flush()
    return inst


def _registration(instance, tariff=None):
    user = User.create_with_password(
        f'pts-{uuid4().hex[:6]}@test.com', 'password123',
        first_name='Т', last_name='С', email_confirmed=True)
    db.session.flush()
    reg = EventRegistration(
        user_id=user.id, instance_id=instance.id, phone='+380501234567',
        specialty='Терапія', workplace='Клініка', payment_status='paid',
        tariff_id=tariff.id if tariff else None,
    )
    db.session.add(reg)
    db.session.flush()
    return reg


def _tariff(instance, event_format):
    tariff = InstanceTariff(
        instance_id=instance.id, name='Тариф', price=1000,
        event_format=event_format,
    )
    db.session.add(tariff)
    db.session.flush()
    return tariff


def _reload_format(migration, reg_id):
    db.session.execute(text(migration.participation_format_backfill_sql()))
    return db.session.execute(
        text('SELECT participation_format FROM event_registrations '
             'WHERE id = :id'),
        {'id': reg_id},
    ).scalar()


def test_backfill_sets_online_from_tariff(migration):
    instance = _course_instance()
    tariff = _tariff(instance, 'online')
    reg = _registration(instance, tariff=tariff)

    assert _reload_format(migration, reg.id) == 'online'


def test_backfill_leaves_null_when_tariff_format_is_null(migration):
    instance = _course_instance()
    tariff = _tariff(instance, None)
    reg = _registration(instance, tariff=tariff)

    assert _reload_format(migration, reg.id) is None


def test_backfill_leaves_null_when_registration_has_no_tariff(migration):
    instance = _course_instance()
    reg = _registration(instance, tariff=None)

    assert _reload_format(migration, reg.id) is None
