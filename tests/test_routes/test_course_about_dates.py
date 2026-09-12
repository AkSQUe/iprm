"""Блок «Про курс» із колонкою доступних дат (пункт 14 ТЗ).

Опис курсу пояснює користь, а поруч із ним відвідувач одразу бачить, коли
на цей курс можна прийти. До пункту 14 це були дві окремі секції одна під
одною: описавши курс, сторінка починала розповідь заново заголовком
«Найближчі дати». Тепер це один блок у дві колонки -- опис ліворуч,
картки проведень праворуч -- і читається він як «ось курс, ось дати».

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

EMAIL_PREFIX = 'about-dates-'


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
        Course.query.filter(Course.slug.like('about-dates%')).delete(
            synchronize_session=False)
        db.session.commit()

    _wipe()
    yield
    _wipe()


def _course(suffix, **kwargs):
    fields = dict(
        slug=f'about-dates{suffix}',
        title='Курс із датами',
        is_active=True,
        description='<p>Повний опис курсу.</p>',
        base_price=6000,
    )
    fields.update(kwargs)
    course = Course(**fields)
    db.session.add(course)
    db.session.flush()
    return course


def _instance(course, *, days=None, start_date=None, location='Київ',
              max_participants=10):
    inst = CourseInstance(
        course_id=course.id,
        status='published',
        event_format='offline',
        start_date=start_date or (
            datetime.now(timezone.utc) + timedelta(days=days)),
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


def _about_html(client, course):
    """HTML секції «Про курс» цілком -- обидві колонки."""
    html = client.get(f'/courses/{course.slug}').get_data(as_text=True)
    start = html.find('id="about"')
    assert start != -1, 'секцію «Про курс» не знайдено'
    return html[start:html.find('</section>', start)]


def test_dates_column_stands_beside_the_description(client):
    """Дві колонки -- один блок, а не дві секції одна під одною."""
    course = _course('-two-col')
    _instance(course, days=30)
    db.session.commit()

    about = _about_html(client, course)
    assert 'iprm-about__text' in about, 'колонки опису немає'
    assert 'id="schedule"' in about, 'колонка дат мусить жити в цій же секції'
    assert 'iprm-datecard' in about, 'картки дати немає'
    assert about.find('iprm-about__text') < about.find('id="schedule"'), (
        'на комп-ютері опис ліворуч, дати праворуч -- такий же порядок у HTML'
    )


def test_datecard_shows_date_topic_place_and_a_way_in(client):
    """Компактна картка: коли, про що, де -- і кнопка вибору."""
    course = _course('-card')
    inst = _instance(course, days=30, location='Харків')
    inst.topic = 'Плазмотерапія обличчя'
    db.session.commit()

    about = _about_html(client, course)
    assert inst.start_date.strftime('%d') in about
    assert 'Плазмотерапія обличчя' in about
    assert 'Харків' in about
    assert 'Обрати дату' in about
    assert f'/instance/{inst.id}/register' in about


def test_datecard_prints_the_hour_exactly_as_it_was_entered(client):
    """Час доби -- без переведення зон, як усюди на цій сторінці.

    DateTimeLocalField в адмінці пише наївний datetime -- київський
    настінний час, який на проді лягає в timestamptz як UTC і читається
    назад тими самими цифрами. Фільтр `| kyiv` додав би поверх нього ще
    зсув зони, і захід о 10:00 показувався б о 13:00. Картка hero, листи,
    підтвердження реєстрації та startDate JSON-LD цієї ж сторінки друкують
    те саме значення голим strftime; розсинхронізувати їх було б гірше,
    ніж мати одну спільну умовність.
    """
    course = _course('-time')
    _instance(course, start_date=datetime(2030, 6, 12, 10, 0))
    db.session.commit()

    about = _about_html(client, course)
    assert '10:00' in about
    assert '13:00' not in about


def test_datecard_keeps_bpr_points_and_tariffs(client):
    """Дві речі, заради яких лікар і обирає дату: бали й ціна участі."""
    course = _course('-tariffs')
    inst = _instance(course, days=30)
    inst.cpd_points_offline = Decimal('10')
    db.session.add(InstanceTariff(
        instance_id=inst.id, name='Слухач', price=Decimal('4000'),
    ))
    db.session.commit()

    about = _about_html(client, course)
    assert 'Слухач' in about
    assert 'БПР' in about


def test_course_without_description_still_shows_its_dates(client):
    """Порожній опис -- не привід ховати розклад.

    Умова рендеру секції висіла на course.description; без неї курс із
    датами, але без опису, не показував жодної дати.
    """
    course = _course('-nodesc', description=None)
    _instance(course, days=30)
    db.session.commit()

    about = _about_html(client, course)
    assert 'iprm-datecard' in about


def test_difficulty_level_is_named_once_beside_the_description(client):
    """Рівень -- властивість курсу, а не проведення.

    На кожній картці це був би той самий текст стільки разів, скільки дат.
    """
    course = _course('-level', difficulty_level=2)
    for day in (10, 20):
        _instance(course, days=day)
    db.session.commit()

    about = _about_html(client, course)
    assert about.count('iprm-card-badge--level') == 1
    assert about.find('iprm-card-badge--level') < about.find('iprm-datecard')


def test_datecard_names_the_level_only_when_it_differs_from_the_course(client):
    """Рівень проведення -- привід порівняти дати між собою.

    Дата з власним рівнем називає його біля себе; сусідня, що йде за
    курсом, мовчить -- інакше в колонці стояв би стовпчик однакових
    підписів, серед яких відмінність і губиться.
    """
    course = _course('-inst-level', difficulty_level=2)
    _instance(course, days=10)
    deeper = _instance(course, days=20)
    deeper.difficulty_level = 3
    db.session.commit()

    about = _about_html(client, course)
    dates = about[about.find('id="schedule"'):]

    assert dates.count('iprm-schedule__tag--level') == 1
    assert 'Рівень 3/3' in dates


def test_datecard_stays_silent_when_the_level_repeats_the_course(client):
    """Рівень курсу названо один раз біля опису -- на картках його немає."""
    course = _course('-same-level', difficulty_level=2)
    inst = _instance(course, days=10)
    inst.difficulty_level = 2
    db.session.commit()

    about = _about_html(client, course)
    dates = about[about.find('id="schedule"'):]

    assert 'iprm-schedule__tag--level' not in dates
    assert about.count('iprm-card-badge--level') == 1


def test_fifth_and_further_dates_hide_behind_a_disclosure(client):
    """Колонка не має бути вищою за опис -- решта дат під розкривачем.

    Ховаємо, а не відрізаємо: усі дати лишаються в HTML, тож і пошуковик,
    і читач екрана бачать повний перелік.
    """
    course = _course('-many')
    for day in (10, 20, 30, 40, 50, 60):
        _instance(course, days=day)
    db.session.commit()

    about = _about_html(client, course)
    assert 'iprm-daterail__more' in about
    assert 'Ще 2 дати' in about
    assert about.count('iprm-datecard"') == 6


def test_four_dates_need_no_disclosure(client):
    course = _course('-few')
    for day in (10, 20, 30, 40):
        _instance(course, days=day)
    db.session.commit()

    about = _about_html(client, course)
    assert 'iprm-daterail__more' not in about
    assert about.count('iprm-datecard"') == 4


def test_column_keeps_the_empty_state_when_there_is_nothing_to_choose(client):
    course = _course('-empty')
    db.session.commit()

    about = _about_html(client, course)
    assert 'Наразі немає запланованих проведень' in about
    assert 'Залишити запит на проведення' in about


def test_column_still_mentions_groups_that_are_already_full(client):
    course = _course('-full')
    _instance(course, days=30, location='Київ')
    full = _instance(course, days=40, location='Львів', max_participants=1)
    _fill(full, 'full')
    db.session.commit()

    about = _about_html(client, course)
    assert 'Київ' in about
    assert 'ще 1 групу вже набрано' in about


def test_datecard_names_the_type_only_when_it_differs_from_the_course(client):
    """Перевизначений вид заходу мусить бути видно публічно.

    Доти сторінка казала неправду: hero-чип друкував вид КУРСУ, а картки
    дат виду не називали зовсім -- дата, перевизначена на тренінг під
    курсом-семінаром, публічно виглядала семінаром.
    """
    course = _course('-inst-type', event_type='seminar')
    _instance(course, days=10)
    other = _instance(course, days=20)
    other.event_type = 'training'
    db.session.commit()

    about = _about_html(client, course)
    dates = about[about.find('id="schedule"'):]

    assert dates.count('iprm-schedule__tag--type') == 1
    assert 'Тренінг' in dates


def test_datecard_stays_silent_when_the_type_repeats_the_course(client):
    """Вид курсу вже стоїть hero-чипом -- на картках його немає."""
    course = _course('-same-type', event_type='seminar')
    inst = _instance(course, days=10)
    inst.event_type = 'seminar'
    db.session.commit()

    about = _about_html(client, course)
    dates = about[about.find('id="schedule"'):]

    assert 'iprm-schedule__tag--type' not in dates
