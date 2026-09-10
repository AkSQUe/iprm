"""Блок «Найближчі дати» на сторінці курсу.

Пункт 7 ТЗ: перелік проведень стоїть одразу під повним описом курсу і
показує лише ті дати, на які реально можна зареєструватися. Проведення з
набраною групою -- не варіант вибору для відвідувача, тож у переліку його
немає взагалі, а не з бейджем «Реєстрацію закрито».

Набрану групу будуємо чесно -- max_participants=1 плюс одна оплачена
реєстрація: CHECK-обмеження не дає поставити 0, а capacity_map рахує
зайнятим саме оплачене місце (services.seating.occupied_clause).
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.extensions import db
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.instance_tariff import InstanceTariff
from app.models.registration import EventRegistration
from app.models.user import User

# Префікс адрес, за якими впізнаємо створених тут користувачів.
EMAIL_PREFIX = 'sched-block-'


@pytest.fixture(autouse=True)
def clean(app):
    """Прибрати за собою курси, проведення й користувачів.

    Користувачів -- не з косметики: тестова БД спільна на всю сесію, а
    /api/v1/participants віддає щонайбільше 200 рядків. Кожен залишений
    тут користувач витісняє звідти чужий тест.
    """
    def _wipe():
        stale = [u.id for u in User.query.filter(
            User.email.like(f'{EMAIL_PREFIX}%')).all()]
        if stale:
            EventRegistration.query.filter(
                EventRegistration.user_id.in_(stale)).delete(
                    synchronize_session=False)
            User.query.filter(User.id.in_(stale)).delete(
                synchronize_session=False)
        Course.query.filter(Course.slug.like('schedule-block%')).delete(
            synchronize_session=False)
        db.session.commit()

    _wipe()
    yield
    _wipe()


def _course(suffix):
    course = Course(
        slug=f'schedule-block{suffix}',
        title='Курс із розкладом',
        is_active=True,
        description='<p>Повний опис курсу.</p>',
        base_price=6000,
    )
    db.session.add(course)
    db.session.flush()
    return course


def _instance(course, *, days, location, max_participants=None):
    inst = CourseInstance(
        course_id=course.id,
        status='published',
        event_format='offline',
        start_date=datetime.now(timezone.utc) + timedelta(days=days),
        location=location,
        max_participants=max_participants,
    )
    db.session.add(inst)
    db.session.flush()
    return inst


def _fill(inst, suffix):
    """Зайняти єдине місце проведення оплаченою реєстрацією."""
    user = User(email=f'{EMAIL_PREFIX}{suffix}@test.com')
    db.session.add(user)
    db.session.flush()
    db.session.add(EventRegistration(
        user_id=user.id, instance_id=inst.id,
        phone='+380000000000', specialty='Лікар', workplace='Клініка',
        status='confirmed', payment_status='paid',
    ))


def _schedule_html(client, course):
    """HTML лише секції розкладу -- від її заголовка до кінця секції."""
    html = client.get(f'/courses/{course.slug}').get_data(as_text=True)
    start = html.find('id="schedule-title"')
    assert start != -1, 'секцію «Найближчі дати» не знайдено'
    return html[start:html.find('</section>', start)]


def test_schedule_lists_only_instances_open_for_registration(client):
    course = _course('-open')
    _instance(course, days=30, location='Київ', max_participants=10)
    full = _instance(course, days=40, location='Львів', max_participants=1)
    _fill(full, 'open')
    db.session.commit()

    schedule = _schedule_html(client, course)
    assert 'Київ' in schedule
    assert 'Львів' not in schedule
    assert 'Реєстрацію закрито' not in schedule


def test_schedule_shows_empty_state_when_every_group_is_full(client):
    course = _course('-full')
    full = _instance(course, days=30, location='Київ', max_participants=1)
    _fill(full, 'full')
    db.session.commit()

    schedule = _schedule_html(client, course)
    # Копія тут -- про набрану групу (див. test_empty_state_names_...):
    # «проведень немає» лишається для курсу без запланованих дат узагалі.
    assert 'вже набрано' in schedule
    assert 'Київ' not in schedule


def test_schedule_stands_between_description_and_roi(client):
    course = _course('-order')
    _instance(course, days=30, location='Київ', max_participants=10)
    db.session.commit()

    html = client.get(f'/courses/{course.slug}').get_data(as_text=True)
    about = html.find('id="about"')
    schedule = html.find('id="schedule-title"')
    roi = html.find('id="roi-title"')
    assert -1 < about < schedule < roi, (
        'розклад мусить стояти одразу після повного опису, до калькулятора'
    )


def test_format_block_skips_instance_with_full_group(client):
    """«Оберіть формат участі» -- теж показ проведення.

    Тарифи набраної групи пропонувати нікуди: кнопка реєстрації там усе
    одно не з'явиться, а відвідувач вирішить, що місця є.
    """
    course = _course('-formats')
    full = _instance(course, days=30, location='Київ', max_participants=1)
    _fill(full, 'formats')
    db.session.add(InstanceTariff(
        instance_id=full.id, name='Слухач', price=Decimal('4000'),
    ))
    db.session.commit()

    html = client.get(f'/courses/{course.slug}').get_data(as_text=True)
    assert 'id="formats"' not in html
    assert 'Слухач' not in html


def test_empty_state_names_the_group_that_is_already_full(client):
    """«Проведень немає» -- неправда, коли група просто набрана.

    Відвідувач мусить розуміти різницю між «курс не планують» і «на
    найближчу дату вже не встиг».
    """
    course = _course('-full-note')
    full = _instance(course, days=30, location='Київ', max_participants=1)
    _fill(full, 'full-note')
    db.session.commit()

    schedule = _schedule_html(client, course)
    assert 'вже набрано' in schedule
    assert full.start_date.strftime('%d.%m.%Y') in schedule


def test_empty_state_offers_to_be_notified_about_a_new_date(client):
    course = _course('-notify')
    full = _instance(course, days=30, location='Київ', max_participants=1)
    _fill(full, 'notify')
    db.session.commit()

    schedule = _schedule_html(client, course)
    assert 'Повідомити про нову дату' in schedule
    assert 'href="#request"' in schedule


def test_note_under_the_list_counts_groups_that_are_full(client):
    course = _course('-mixed')
    _instance(course, days=30, location='Київ', max_participants=10)
    full = _instance(course, days=40, location='Львів', max_participants=1)
    _fill(full, 'mixed')
    db.session.commit()

    schedule = _schedule_html(client, course)
    assert 'Київ' in schedule
    assert 'ще 1 групу вже набрано' in schedule


def test_many_dates_are_grouped_by_city(client):
    """Понад п'ять дат плоским списком -- каша, у якій губиться своє місто."""
    course = _course('-grouped')
    for day in (10, 20, 30):
        _instance(course, days=day, location='Київ', max_participants=10)
    for day in (15, 25, 35):
        _instance(course, days=day, location='Львів', max_participants=10)
    db.session.commit()

    schedule = _schedule_html(client, course)
    assert 'iprm-schedule__group-title' in schedule
    # Групи -- за найранішою датою всередині: Київ (10 днів) перед Львовом (15).
    assert schedule.find('Київ') < schedule.find('Львів')


def test_few_dates_stay_a_flat_list(client):
    course = _course('-flat')
    for day in (10, 20, 30):
        _instance(course, days=day, location='Київ', max_participants=10)
    db.session.commit()

    schedule = _schedule_html(client, course)
    assert 'iprm-schedule__group-title' not in schedule
