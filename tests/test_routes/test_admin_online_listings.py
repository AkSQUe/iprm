"""Реєстри онлайн-курсів і замовлень в адмінці.

Головне тут -- не рендер, а три речі, які тихо розходились:

* правило готовності до публікації жило двома копіями (властивість моделі і
  SQL-фільтр списку) і встигло розійтись -- зріз «Готові до публікації»
  ховав курси, які та сама сторінка позначала «Готовий»;
* підсумки над таблицею рахувались окремими COUNT-ами, тепер одним запитом;
* період і курс не були фільтрами взагалі, а суми друкувались через
  `| int`, який з'їдав копійки.
"""
from tests.support.rbac import grant_role
from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pytest

from app.extensions import db
from app.models.auth_identity import AuthIdentity
from app.models.medical_profile import MedicalProfile
from app.models.online_course import OnlineCourse
from app.models.online_enrollment import OnlineEnrollment
from app.models.user import User
from app.utils import kyiv_dt, to_kyiv

# Префікси адрес, за якими впізнаємо створених тут користувачів.
EMAIL_PREFIXES = ('ol-', 'ob-')


@pytest.fixture(autouse=True)
def clean(app):
    """Порожні таблиці курсів, замовлень і власних користувачів.

    Користувачів прибираємо теж, і це не косметика: тестова БД спільна на
    всю сесію, а /api/v1/participants віддає сторінку максимум у 200 рядків
    у порядку оновлення. Кожен залишений тут користувач витісняє з тієї
    сторінки чужий тест, і той падає на StopIteration за кілометр звідси.
    """
    def _wipe():
        OnlineEnrollment.query.delete()
        OnlineCourse.query.delete()
        stale = [
            row.id for row in User.query.filter(db.or_(*[
                User.email.like(f'{prefix}%@test.com')
                for prefix in EMAIL_PREFIXES
            ])).all()
        ]
        if stale:
            for model in (AuthIdentity, MedicalProfile):
                model.query.filter(model.user_id.in_(stale)).delete(
                    synchronize_session=False)
            User.query.filter(User.id.in_(stale)).delete(
                synchronize_session=False)
        db.session.commit()

    _wipe()
    yield
    _wipe()


@pytest.fixture
def admin(app):
    user = User.create_with_password(
        f'ol-{uuid4().hex[:8]}@test.com', 'password123',
        first_name='А', last_name='Адмін', email_confirmed=True,
    )
    grant_role(user, 'super_admin')
    db.session.commit()
    return user


@pytest.fixture
def buyer(app):
    user = User.create_with_password(
        f'ob-{uuid4().hex[:8]}@test.com', 'password123',
        first_name='Ольга', last_name='Коваль', email_confirmed=True,
    )
    db.session.commit()
    return user


def _login(client, user):
    with client.session_transaction() as session:
        session.clear()
        session['_user_id'] = str(user.id)


def _course(**kwargs):
    kwargs.setdefault('remote_name', f'Курс {uuid4().hex[:4]}')
    kwargs.setdefault('remote_status', 1)
    item = OnlineCourse(
        sintegrum_id=int(uuid4().int % 10_000_000),
        slug=f'ol-{uuid4().hex[:8]}',
        **kwargs,
    )
    db.session.add(item)
    db.session.commit()
    return item


def _order(buyer, course, **kwargs):
    kwargs.setdefault('payment_amount', course.effective_price or Decimal('0'))
    item = OnlineEnrollment(user_id=buyer.id, online_course_id=course.id,
                            **kwargs)
    db.session.add(item)
    db.session.commit()
    return item


# --------------------- готовність до публікації ---------------------

CASES = [
    # (наша ціна, ціна Sintegrum, зник)
    (None, None, False),
    (None, Decimal('4000'), False),
    (Decimal('5000'), None, False),
    (Decimal('5000'), Decimal('4000'), False),
    (Decimal('0'), Decimal('4000'), False),
    (Decimal('0'), None, False),
    (None, Decimal('0'), False),
    (Decimal('5000'), Decimal('4000'), True),
    (None, None, True),
]


class TestPublishableRule:
    """SQL-предикат мусить давати те саме, що властивість моделі.

    Доки це були дві незалежні копії, вони розійшлись: фільтр вимагав
    `access_url` (модель перестала його вимагати) і дивився на власну ціну
    замість ефективної -- а типовий курс продається за ціною Sintegrum.
    """

    @pytest.mark.parametrize('price,remote_price,vanished', CASES)
    def test_sql_clause_matches_the_property(self, app, price, remote_price,
                                             vanished):
        course = _course(price=price, remote_price=remote_price,
                         is_vanished=vanished)
        matched = OnlineCourse.query.filter(
            OnlineCourse.publishable_clause(),
            OnlineCourse.id == course.id,
        ).count()
        assert bool(matched) == course.can_be_published

    @pytest.mark.parametrize('price,remote_price,vanished', CASES)
    def test_negation_is_the_exact_complement(self, app, price, remote_price,
                                              vanished):
        course = _course(price=price, remote_price=remote_price,
                         is_vanished=vanished)
        matched = OnlineCourse.query.filter(
            db.not_(OnlineCourse.publishable_clause()),
            OnlineCourse.id == course.id,
        ).count()
        assert bool(matched) is not course.can_be_published

    def test_ready_filter_shows_course_priced_by_sintegrum(self, client, admin):
        """Найчастіший випадок: власної ціни немає, продаємо за ціною партнера."""
        course = _course(remote_name='Плазмотерапія',
                         remote_price=Decimal('4000'))
        assert course.can_be_published

        _login(client, admin)
        body = client.get(
            '/admin/online-courses?status=ready').get_data(as_text=True)
        assert 'Плазмотерапія' in body

    def test_incomplete_filter_hides_it(self, client, admin):
        _course(remote_name='Плазмотерапія', remote_price=Decimal('4000'))
        _login(client, admin)
        body = client.get(
            '/admin/online-courses?status=incomplete').get_data(as_text=True)
        assert 'Плазмотерапія' not in body

    def test_course_without_any_price_is_incomplete(self, client, admin):
        """Без ціни взагалі: у SQL це NULL, і саме на ньому падало заперечення."""
        _course(remote_name='Безцінний')
        _login(client, admin)
        body = client.get(
            '/admin/online-courses?status=incomplete').get_data(as_text=True)
        assert 'Безцінний' in body


# --------------------------- підсумки ---------------------------

class TestTotals:
    def test_order_counts_come_out_of_one_query(self, client, admin, buyer):
        course = _course(remote_price=Decimal('1000'))
        _order(buyer, course, payment_status='paid')
        other = _course(remote_price=Decimal('1000'))
        _order(buyer, other, payment_status='unpaid')

        _login(client, admin)
        body = client.get('/admin/online-orders').get_data(as_text=True)
        assert 'Усього 2' in body
        assert 'оплачено 1' in body
        assert 'не оплачено 1' in body
        # Оплачене без provisioned_at -- та сама «зависла» черга.
        assert 'без доступу 1' in body

    def test_catalog_counts(self, client, admin):
        _course(is_published=True, remote_price=Decimal('1000'))
        _course(is_vanished=True)
        _login(client, admin)
        body = client.get('/admin/online-courses').get_data(as_text=True)
        assert 'Усього 2' in body
        assert 'опубліковано 1' in body
        assert 'зникло з Sintegrum 1' in body


# --------------------------- фільтри ---------------------------

class TestOrderFilters:
    def test_period_narrows_the_list(self, client, admin, buyer):
        """Межі включні з обох боків.

        Опівнічну межу тут не перевіряємо: SQLite зберігає datetime без зони,
        тож київська доба з `_listing.apply_date_range` спостерігається лише
        на PostgreSQL. Що перевіряємо -- що фільтр узагалі підключено до
        `created_at` і що він ріже з обох боків.
        """
        course = _course(remote_price=Decimal('1000'))
        order = _order(buyer, course, payment_status='paid',
                       created_at=datetime(2026, 8, 10, 12, 0,
                                           tzinfo=timezone.utc))
        tag = f'ONL-{order.id}'

        _login(client, admin)
        same_day = client.get(
            '/admin/online-orders?date_from=2026-08-10&date_to=2026-08-10',
        ).get_data(as_text=True)
        assert tag in same_day

        before = client.get(
            '/admin/online-orders?date_to=2026-08-09').get_data(as_text=True)
        assert tag not in before

        after = client.get(
            '/admin/online-orders?date_from=2026-08-11').get_data(as_text=True)
        assert tag not in after

    def test_course_filter_narrows_the_list(self, client, admin, buyer):
        wanted = _course(remote_name='Плазмотерапія',
                         remote_price=Decimal('1000'))
        other = _course(remote_name='Ботулінотерапія',
                        remote_price=Decimal('1000'))
        kept = _order(buyer, wanted, payment_status='paid')
        dropped = _order(buyer, other, payment_status='paid')

        _login(client, admin)
        body = client.get(
            f'/admin/online-orders?course={wanted.id}').get_data(as_text=True)
        # Звіряємо саме номери замовлень: назви обох курсів у сторінці є в
        # будь-якому разі -- вони наповнюють селект фільтра.
        assert f'ONL-{kept.id}' in body
        assert f'ONL-{dropped.id}' not in body

    def test_course_select_lists_only_courses_with_orders(self, client, admin,
                                                          buyer):
        sold = _course(remote_name='Плазмотерапія', remote_price=Decimal('1'))
        _course(remote_name='Ніхто не купив', remote_price=Decimal('1'))
        _order(buyer, sold, payment_status='paid')

        _login(client, admin)
        body = client.get('/admin/online-orders').get_data(as_text=True)
        assert 'Ніхто не купив' not in body

    def test_empty_state_offers_a_reset_for_the_access_slice(self, client,
                                                             admin):
        """Порожня черга «оплачено без доступу» -- зріз, а не «немає замовлень»."""
        _login(client, admin)
        body = client.get(
            '/admin/online-orders?access=stuck').get_data(as_text=True)
        assert 'скинути фільтри' in body

    def test_empty_catalog_slice_offers_a_reset(self, client, admin):
        _login(client, admin)
        body = client.get(
            '/admin/online-courses?status=vanished').get_data(as_text=True)
        assert 'скинути фільтри' in body


# --------------------------- подача даних ---------------------------

class TestPresentation:
    def test_amount_keeps_kopiykas(self, client, admin, buyer):
        """`| int` округлював 0.60 до нуля -- саме те, що ховало залишок."""
        course = _course(remote_price=Decimal('4000'))
        _order(buyer, course, payment_status='paid',
               payment_amount=Decimal('0.60'))

        _login(client, admin)
        body = client.get('/admin/online-orders').get_data(as_text=True)
        assert '0.60' in body

    def test_time_is_shown_in_kyiv(self, client, admin, buyer):
        course = _course(remote_price=Decimal('1000'))
        _order(buyer, course, payment_status='unpaid',
               created_at=datetime(2026, 8, 10, 21, 30, tzinfo=timezone.utc))

        _login(client, admin)
        body = client.get('/admin/online-orders').get_data(as_text=True)
        assert '11.08.2026 00:30' in body

    def test_kyiv_filter_leaves_dates_and_blanks_alone(self):
        assert kyiv_dt(None) == ''
        assert to_kyiv(date(2026, 8, 10)) == date(2026, 8, 10)
        naive = datetime(2026, 8, 10, 21, 30)
        assert kyiv_dt(naive) == '11.08.2026 00:30'
