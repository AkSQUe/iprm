"""Агрегати режиму «За заходами»: число заголовка = те, що розгорнеться."""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from app.extensions import db
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.registration import EventRegistration
from app.models.user import User
from app.services import registration_groups


def _uid():
    return uuid4().hex[:8]


@pytest.fixture
def two_dates(app):
    """Курс із двома датами: на ближчій -- дві реєстрації, на дальшій -- одна.

    Тільки flush: автоматична фікстура db_session відкочує транзакцію, а
    закомічений користувач переживав би тест і ламав чужі посторінкові тести.
    """
    course = Course(title=f'Курс {_uid()}', slug=f'grp-{_uid()}', is_active=True)
    db.session.add(course)
    db.session.flush()

    now = datetime.now(timezone.utc)
    instances = []
    for offset in (10, 20):
        inst = CourseInstance(
            course_id=course.id, status='published', event_format='offline',
            start_date=now + timedelta(days=offset),
        )
        db.session.add(inst)
        db.session.flush()
        instances.append(inst)

    def _reg(inst, status, payment_status, amount):
        user = User.create_with_password(
            f'grp-{_uid()}@test.com', 'password123',
            first_name='Г', last_name='Т',
        )
        db.session.flush()
        reg = EventRegistration(
            user_id=user.id, instance_id=inst.id, phone='+380670000000',
            specialty='T', workplace='Клініка', status=status,
            payment_status=payment_status, payment_amount=amount,
        )
        db.session.add(reg)
        db.session.flush()
        return reg

    _reg(instances[0], 'confirmed', 'paid', 3500)
    _reg(instances[0], 'pending', 'unpaid', 2975)
    _reg(instances[1], 'confirmed', 'paid', 4500)
    return course, instances


def _matched(status=None):
    query = db.session.query(EventRegistration.id)
    if status:
        query = query.filter(EventRegistration.status == status)
    return query


def _group_of(groups, course):
    return next(g for g in groups if g.course.id == course.id)


def test_group_sums_its_dates(two_dates):
    course, _ = two_dates
    groups, pagination = registration_groups.grouped_page(
        _matched(), page=1, per_page=25)

    group = _group_of(groups, course)
    assert group.total == 3
    assert group.confirmed == 2
    assert group.pending == 1
    assert group.amount == 3500 + 2975 + 4500
    assert group.paid == 3500 + 4500
    assert group.due == 2975
    assert pagination.total >= 1


def test_dates_carry_their_own_numbers(two_dates):
    course, instances = two_dates
    groups, _ = registration_groups.grouped_page(_matched(), page=1, per_page=25)

    by_id = {row.instance.id: row for row in _group_of(groups, course).instances}
    assert by_id[instances[0].id].total == 2
    assert by_id[instances[1].id].total == 1
    assert by_id[instances[0].id].due == 2975
    assert by_id[instances[1].id].due == 0


def test_filter_shrinks_the_numbers(two_dates):
    """Заголовок не сміє обіцяти більше, ніж розгорнеться."""
    course, instances = two_dates
    groups, _ = registration_groups.grouped_page(
        _matched(status='pending'), page=1, per_page=25)

    group = _group_of(groups, course)
    assert group.total == 1
    assert [row.instance.id for row in group.instances] == [instances[0].id]


def test_course_without_matches_disappears(two_dates):
    """Курс, у якого після фільтра нуль реєстрацій, у видачу не потрапляє."""
    course, _ = two_dates
    groups, _ = registration_groups.grouped_page(
        _matched(status='cancelled'), page=1, per_page=25)

    assert all(g.course.id != course.id for g in groups)


def test_cancelled_unpaid_does_not_inflate_debt(two_dates):
    """Скасована неоплачена реєстрація -- не борг: нікому його не пред'явиш."""
    course, instances = two_dates
    user = User.create_with_password(
        f'grp-{_uid()}@test.com', 'password123', first_name='С', last_name='К')
    db.session.flush()
    db.session.add(EventRegistration(
        user_id=user.id, instance_id=instances[0].id, phone='+380670000000',
        specialty='T', workplace='Клініка', status='cancelled',
        payment_status='unpaid', payment_amount=5000,
    ))
    db.session.flush()

    groups, _ = registration_groups.grouped_page(_matched(), page=1, per_page=25)

    group = _group_of(groups, course)
    date_row = next(r for r in group.instances if r.instance.id == instances[0].id)
    # Борг на дату -- незмінний (2975, як і до скасованої реєстрації), а сума
    # виросла на всю скасовану реєстрацію: гроші, які по ній НЕ надійшли,
    # ніхто не винен.
    assert date_row.due == 2975
    assert date_row.amount == 3500 + 2975 + 5000
    # І на рівні курсу борг так само не зрушив.
    assert group.due == 2975


def test_oldest_first_flips_the_order(two_dates):
    course, instances = two_dates
    groups, _ = registration_groups.grouped_page(
        _matched(), page=1, per_page=25, oldest_first=True)

    assert [row.instance.id for row in _group_of(groups, course).instances] == [
        instances[0].id, instances[1].id]


def test_undated_event_stays_last_in_both_directions(two_dates):
    """Захід без дати -- скраю, а не зверху типового перегляду."""
    course, instances = two_dates
    tbd = CourseInstance(
        course_id=course.id, status='published', event_format='offline',
        start_date=None,
    )
    db.session.add(tbd)
    db.session.flush()
    user = User.create_with_password(
        f'grp-{_uid()}@test.com', 'password123', first_name='Т', last_name='Б')
    db.session.flush()
    db.session.add(EventRegistration(
        user_id=user.id, instance_id=tbd.id, phone='+380670000000',
        specialty='T', workplace='Клініка', status='confirmed',
        payment_status='paid', payment_amount=1000,
    ))
    db.session.flush()

    for oldest_first in (False, True):
        groups, _ = registration_groups.grouped_page(
            _matched(), page=1, per_page=25, oldest_first=oldest_first)
        order = [row.instance.id for row in _group_of(groups, course).instances]
        assert order[-1] == tbd.id, (
            f'oldest_first={oldest_first}: TBD опинився не в кінці ({order})')


def _course_with_one_registration(start_date):
    """Окремий курс з однією датою й однією реєстрацією -- для порядку курсів."""
    course = Course(title=f'Курс {_uid()}', slug=f'grp-{_uid()}', is_active=True)
    db.session.add(course)
    db.session.flush()
    inst = CourseInstance(
        course_id=course.id, status='published', event_format='offline',
        start_date=start_date,
    )
    db.session.add(inst)
    db.session.flush()
    user = User.create_with_password(
        f'grp-{_uid()}@test.com', 'password123', first_name='П', last_name='К')
    db.session.flush()
    db.session.add(EventRegistration(
        user_id=user.id, instance_id=inst.id, phone='+380670000000',
        specialty='T', workplace='Клініка', status='confirmed',
        payment_status='paid', payment_amount=1000,
    ))
    db.session.flush()
    return course


def test_courses_order_by_date_and_undated_course_goes_last(app):
    """Порядок КУРСІВ на сторінці: за датою в обидва боки, а курс, у якого
    жодна дата не призначена, -- в кінці за будь-якого напрямку.

    Без явного NULLS LAST PostgreSQL при спаданні ставить такий курс ПЕРШИМ,
    а SQLite -- останнім; тест фіксує спільну для обох поведінку.
    """
    now = datetime.now(timezone.utc)
    near = _course_with_one_registration(now + timedelta(days=10))
    far = _course_with_one_registration(now + timedelta(days=20))
    undated = _course_with_one_registration(None)
    ours = {near.id, far.id, undated.id}

    def _order(oldest_first):
        groups, _ = registration_groups.grouped_page(
            _matched(), page=1, per_page=200, oldest_first=oldest_first)
        return [g.course.id for g in groups if g.course.id in ours]

    assert _order(oldest_first=False) == [far.id, near.id, undated.id]
    assert _order(oldest_first=True) == [near.id, far.id, undated.id]
