"""Партнерське API як джерело РОЗКЛАДУ: вікно дат, порядок, пагінація.

До цих параметрів партнер не міг побудувати розклад узагалі:

  * фільтра за діапазоном дат не було -- доводилось тягнути весь каталог і
    різати його в себе, а `per_page` обмежений сотнею;
  * instance-режим жорстко сортував `start_date DESC`, тобто найдальші
    заходи йшли першими -- для «найближчих подій» це точно навпаки;
  * покурсовий режим викликав `paginate()` БЕЗ `order_by`, а вже вибрану
    сторінку сортував у Python. Виходила хронологія всередині сторінки й
    довільний порядок між сторінками: гортання губило одні заходи й
    показувало інші двічі. Саме це найважче помітити -- перша сторінка
    виглядає бездоганно.

Тести навмисно перевіряють ПАРИ сторінок, а не лише першу.
"""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from app.extensions import db
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.site_settings import SiteSettings
from app.models.user import User


API_KEY = 'test-partner-api-key-12345678901234567890'
HEADERS = {'X-API-Key': API_KEY}


def _uid():
    return uuid4().hex[:8]


@pytest.fixture
def partner_settings(app):
    s = SiteSettings.get()
    s.partner_integration_enabled = True
    s.partner_api_key = API_KEY
    db.session.commit()
    yield s
    s.partner_integration_enabled = False
    s.partner_api_key = ''
    db.session.commit()


@pytest.fixture
def author(app):
    u = User(email=f'sched-{_uid()}@test.com', password='pw-' + _uid(),
             first_name='S', last_name='U')
    db.session.add(u)
    db.session.flush()
    return u


def _course_with_instance(author, *, days_from_now, status='published',
                          title=None, price=1000):
    """Курс з одним проведенням у заданій точці часу."""
    course = Course(
        title=title or f'Course {days_from_now:+d}d', slug=f'c-{_uid()}',
        short_description='d', event_type='course', base_price=price,
        is_active=True, created_by=author.id,
    )
    db.session.add(course)
    db.session.flush()
    inst = CourseInstance(
        course_id=course.id, status=status, event_format='offline',
        price=price,
        start_date=datetime.now(timezone.utc) + timedelta(days=days_from_now),
    )
    db.session.add(inst)
    db.session.flush()
    course._test_instance = inst
    return course


def _dates(payload, slugs=None):
    """Дати з відповіді, за потреби звужені до власних курсів тесту.

    Звуження принципове: у спільній тестовій БД лежать курси інших тестів, і
    частина з них без дати. Судити про порядок усієї видачі означало б
    перевіряти чужі дані — саме на цьому тест і падав у повному прогоні,
    хоча поодинці був зелений.
    """
    items = payload['items']
    if slugs is not None:
        items = [i for i in items if i['slug'] in slugs]
    return [item['start_date'] for item in items]


class TestDateWindow:
    def test_date_from_excludes_earlier_events(self, client, partner_settings, author):
        soon = _course_with_instance(author, days_from_now=5)
        later = _course_with_instance(author, days_from_now=40)
        db.session.commit()

        cutoff = (datetime.now(timezone.utc) + timedelta(days=20)).date().isoformat()
        data = client.get(f'/api/v1/events?date_from={cutoff}',
                          headers=HEADERS).get_json()

        slugs = {i['slug'] for i in data['items']}
        assert later.slug in slugs
        assert soon.slug not in slugs

    def test_date_to_covers_the_whole_final_day(self, client, partner_settings, author):
        """Гола дата в `date_to` -- кінець доби.

        Інакше захід, що починається о 10:00 останнього дня діапазону, зникає:
        `2026-09-30` як опівніч відсікає весь свій же день, і партнер бачить
        порожній кінець місяця.
        """
        target = datetime.now(timezone.utc) + timedelta(days=7)
        course = _course_with_instance(author, days_from_now=7)
        db.session.commit()

        data = client.get(f'/api/v1/events?date_to={target.date().isoformat()}',
                          headers=HEADERS).get_json()
        assert course.slug in {i['slug'] for i in data['items']}

    def test_upcoming_drops_past_events(self, client, partner_settings, author):
        past = _course_with_instance(author, days_from_now=-30, status='completed')
        future = _course_with_instance(author, days_from_now=30)
        db.session.commit()

        data = client.get('/api/v1/events?upcoming=1&status=published,completed',
                          headers=HEADERS).get_json()
        slugs = {i['slug'] for i in data['items']}
        assert future.slug in slugs
        assert past.slug not in slugs

    def test_representative_instance_stays_inside_the_window(
            self, client, partner_settings, author):
        """Курс, знайдений за вереснем, не має показувати жовтневу дату."""
        course = _course_with_instance(author, days_from_now=10)
        db.session.add(CourseInstance(
            course_id=course.id, status='published', event_format='offline',
            price=1000,
            start_date=datetime.now(timezone.utc) + timedelta(days=100),
        ))
        db.session.commit()

        window_end = (datetime.now(timezone.utc) + timedelta(days=30)).date().isoformat()
        data = client.get(f'/api/v1/events?date_to={window_end}',
                          headers=HEADERS).get_json()
        card = next(i for i in data['items'] if i['slug'] == course.slug)

        # SQLite віддає дату без зсуву, PostgreSQL -- зі зсувом; звіряємо через
        # той самий нормалізатор, що й застосунок.
        from app.utils import ensure_utc
        shown = ensure_utc(datetime.fromisoformat(card['start_date']))
        assert shown < datetime.now(timezone.utc) + timedelta(days=31)

    def test_bad_date_is_rejected(self, client, partner_settings):
        resp = client.get('/api/v1/events?date_from=вересень', headers=HEADERS)
        assert resp.status_code == 400
        assert 'error' in resp.get_json()

    def test_reversed_window_is_rejected(self, client, partner_settings):
        resp = client.get('/api/v1/events?date_from=2026-10-01&date_to=2026-09-01',
                          headers=HEADERS)
        assert resp.status_code == 400


class TestSort:
    def test_instance_mode_ascending(self, client, partner_settings, author):
        mine = {_course_with_instance(author, days_from_now=d).slug
                for d in (30, 5, 60)}
        db.session.commit()

        data = client.get('/api/v1/events?granularity=instance&sort=start_asc'
                          '&per_page=100', headers=HEADERS).get_json()
        dates = _dates(data, mine)
        assert len(dates) == 3
        assert dates == sorted(dates)

    def test_instance_mode_defaults_to_descending(self, client, partner_settings, author):
        """Типовий порядок не змінюється: на нього спирається історія семінарів
        у виконавчому звіті MM Medic."""
        mine = {_course_with_instance(author, days_from_now=d).slug
                for d in (5, 60)}
        db.session.commit()

        data = client.get('/api/v1/events?granularity=instance&per_page=100',
                          headers=HEADERS).get_json()
        dates = _dates(data, mine)
        assert len(dates) == 2
        assert dates == sorted(dates, reverse=True)

    def test_course_mode_ascending(self, client, partner_settings, author):
        mine = {_course_with_instance(author, days_from_now=d).slug
                for d in (45, 3)}
        db.session.commit()

        data = client.get('/api/v1/events?sort=start_asc&per_page=100',
                          headers=HEADERS).get_json()
        dates = _dates(data, mine)
        assert len(dates) == 2
        assert dates == sorted(dates)

    def test_bad_sort_is_rejected(self, client, partner_settings):
        resp = client.get('/api/v1/events?sort=alphabetical', headers=HEADERS)
        assert resp.status_code == 400


class TestPaginationIsStable:
    """Головне: сторінка 2 має ПРОДОВЖУВАТИ сторінку 1, а не перетинатися."""

    @pytest.mark.parametrize('granularity', ['course', 'instance'])
    def test_pages_do_not_overlap_or_skip(self, client, partner_settings, author,
                                          granularity):
        # Вікно дат ізолює вибірку від курсів інших тестів — інакше сторінки
        # заповнювались би чужими рядками і перевіряти було б нічого.
        offsets = (500, 507, 514, 521, 528, 535)
        for offset in offsets:
            _course_with_instance(author, days_from_now=offset)
        db.session.commit()

        window_from = (datetime.now(timezone.utc) + timedelta(days=490)).date().isoformat()
        base = (f'/api/v1/events?granularity={granularity}&sort=start_asc'
                f'&per_page=2&date_from={window_from}')
        pages = [
            client.get(f'{base}&page={n}', headers=HEADERS).get_json()
            for n in (1, 2, 3)
        ]
        items = [i for page in pages for i in page['items']]

        key = 'instance_id' if granularity == 'instance' else 'slug'
        ids = [i[key] for i in items]
        assert len(ids) == len(set(ids)), 'сторінки перетинаються — рядки дублюються'
        assert len(ids) == len(offsets), 'сторінки пропускають рядки'

        dates = [i['start_date'] for i in items]
        assert dates == sorted(dates), 'хронологія рветься між сторінками'


class TestUndatedInstances:
    """Проведення без дати мусить стояти в кінці НА БУДЬ-ЯКІЙ СУБД.

    Голий ORDER BY тут розходиться між двигунами: SQLite кладе NULL першими
    при ASC, PostgreSQL -- останніми. Тобто на dev розклад починався б із
    заходів «дата уточнюється», а в проді вони були б у хвості — і жодна
    перевірка на SQLite цього б не показала.
    """

    def _undated(self, author):
        course = Course(
            title='TBD', slug=f'tbd-{_uid()}', short_description='d',
            event_type='course', base_price=100, is_active=True,
            created_by=author.id,
        )
        db.session.add(course)
        db.session.flush()
        db.session.add(CourseInstance(
            course_id=course.id, status='published', event_format='online',
            price=100, start_date=None,
        ))
        db.session.flush()
        return course

    @pytest.mark.parametrize('sort', ['start_asc', 'start_desc'])
    def test_undated_goes_last(self, client, partner_settings, author, sort):
        undated = self._undated(author)
        dated = {_course_with_instance(author, days_from_now=d).slug
                 for d in (700, 730)}
        db.session.commit()

        data = client.get(
            f'/api/v1/events?granularity=instance&sort={sort}&per_page=100',
            headers=HEADERS).get_json()

        mine = [i for i in data['items']
                if i['slug'] == undated.slug or i['slug'] in dated]
        assert len(mine) == 3
        assert mine[-1]['slug'] == undated.slug
        assert mine[-1]['start_date'] is None


class TestCancelledIsRequestable:
    def test_cancelled_hidden_by_default(self, client, partner_settings, author):
        cancelled = _course_with_instance(author, days_from_now=15, status='cancelled')
        db.session.commit()

        data = client.get('/api/v1/events', headers=HEADERS).get_json()
        assert cancelled.slug not in {i['slug'] for i in data['items']}

    def test_cancelled_returned_when_asked(self, client, partner_settings, author):
        """Партнер мусить мати змогу показати «Захід скасовано».

        Доки статус не можна було запитати, скасоване проведення просто
        зникало з відповіді — для партнера це не відрізнити від видалення, і
        замість плашки він мовчки прибирав рядок розкладу.
        """
        cancelled = _course_with_instance(author, days_from_now=15, status='cancelled')
        db.session.commit()

        data = client.get('/api/v1/events?status=published,cancelled',
                          headers=HEADERS).get_json()
        card = next((i for i in data['items'] if i['slug'] == cancelled.slug), None)
        assert card is not None
        assert card['status'] == 'cancelled'


class TestCardFields:
    def test_is_registration_open_removes_the_null_guesswork(
            self, client, partner_settings, author):
        course = _course_with_instance(author, days_from_now=15)
        db.session.commit()

        data = client.get('/api/v1/events', headers=HEADERS).get_json()
        card = next(i for i in data['items'] if i['slug'] == course.slug)
        assert card['is_registration_open'] is True

    def test_price_is_from_is_false_for_a_single_price(
            self, client, partner_settings, author):
        course = _course_with_instance(author, days_from_now=15)
        db.session.commit()

        data = client.get('/api/v1/events', headers=HEADERS).get_json()
        card = next(i for i in data['items'] if i['slug'] == course.slug)
        assert card['price_is_from'] is False

    def test_price_is_from_when_tariffs_differ(self, client, partner_settings, author):
        from app.models.instance_tariff import InstanceTariff

        course = _course_with_instance(author, days_from_now=15)
        inst = course._test_instance
        db.session.add(InstanceTariff(
            instance_id=inst.id, name='Базовий', price=1000, is_active=True))
        db.session.add(InstanceTariff(
            instance_id=inst.id, name='Розширений', price=2500, is_active=True))
        db.session.commit()

        data = client.get('/api/v1/events', headers=HEADERS).get_json()
        card = next(i for i in data['items'] if i['slug'] == course.slug)
        assert card['price_is_from'] is True
        assert card['price'] == 1000.0, 'ціна «від» -- мінімальний активний тариф'
