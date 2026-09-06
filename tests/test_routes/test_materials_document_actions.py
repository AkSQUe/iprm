"""Що сторінка матеріалів ІПРМ має право робити з документом MM Medic.

Заявка переїхала на новий канал: ІПРМ подає ДОКУМЕНТ, комірник погоджує й
видає, і саме видача вішає на рядки партії, з яких береться собівартість
заходу. Легасі-дії сторінки (списання, коригування) написані під старий
канал -- утримання без рядків. Застосовані до документа, вони закривають
його не створивши жодної партії: `issue()` після цього неможливий, а
собівартість недосяжна назавжди.

Тому сторінка їх не пропонує, а маршрути відмовляють. MM Medic відмовляє й
на своєму боці (`actuals_unsupported_for_document`) -- тут перевіряється
наш бік.
"""
from tests.support.rbac import grant_role
from uuid import uuid4

import pytest

from app.admin import routes_materials as routes
from app.extensions import db
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.material_reservation import (
    MaterialReservation, MaterialReservationItem, MaterialReservationStatus,
)
from app.models.user import User
from app.services import material_reservation_service as mrs_module

_SLUG_PREFIX = 'md-'
_EMAIL_PREFIX = 'md-admin-'

FAKE_CATALOG = [
    {'sku': 'NDL-21', 'name': 'Голка 21G', 'available': 100, 'price': 12.5,
     'category': 'Голки', 'is_consumable': True},
]


@pytest.fixture(autouse=True)
def _no_leftovers(app):
    """Прибрати за собою те, що ПЕРЕЖИЛО відкат фікстури.

    Частина тестів тут проходить маршрутом, який комітить (правка заявки),
    а коміт виносить із транзакції ВСЕ, що на той момент було в сесії, --
    у тому числі адміна, курс і захід. Рядки лишаються в тестовій базі до
    кінця сесії й додаються до кожного списку, який хтось десь читає:
    `/api/v1/participants` віддає першу сторінку на 200 користувачів у
    порядку `updated_at`, і зайві облікові записи мовчки виштовхують з неї
    того, кого шукає чужий тест. Саме так це й проявилось -- три падіння в
    ІНШОМУ файлі, зелені при запуску поодинці.
    """
    yield

    from app.models.course_instance import CourseInstance

    # Видаляємо ОРМ-ом, а не bulk-delete: у SQLite (тестова БД) каскади FK
    # вимкнені, а первинні ключі ПЕРЕВИКОРИСТОВУЮТЬСЯ після видалення. Осиротілі
    # рядки позицій діставались наступному резервуванню, яке отримало той самий
    # id, і воно падало на UNIQUE (reservation_id, sku).
    try:
        courses = Course.query.filter(Course.slug.like(f'{_SLUG_PREFIX}%')).all()
        for course in courses:
            for instance in CourseInstance.query.filter_by(
                    course_id=course.id).all():
                for reservation in MaterialReservation.query.filter_by(
                        instance_id=instance.id).all():
                    db.session.delete(reservation)
                db.session.delete(instance)
            db.session.delete(course)
        for user in User.query.filter(User.email.like(f'{_EMAIL_PREFIX}%')).all():
            db.session.delete(user)
        db.session.commit()
    except Exception:
        db.session.rollback()


@pytest.fixture(autouse=True)
def fake_catalog(monkeypatch):
    monkeypatch.setattr(routes.mrs, 'get_catalog',
                        lambda **kw: (FAKE_CATALOG, None, False))


@pytest.fixture
def admin(app):
    user = User.create_with_password(
        f'md-admin-{uuid4().hex[:6]}@test.com', 'password123',
        first_name='А', last_name='Адмін', email_confirmed=True,
    )
    grant_role(user, 'super_admin')
    db.session.flush()
    return user


def _login(client, user):
    with client.session_transaction() as session:
        session['_user_id'] = str(user.id)


def _instance():
    suffix = uuid4().hex[:8]
    course = Course(title='Плазмотерапія', slug=f'md-{suffix}')
    db.session.add(course)
    db.session.flush()
    instance = CourseInstance(course_id=course.id, location='Київ')
    db.session.add(instance)
    db.session.flush()
    return instance


def _reservation(instance, status, *, requested=None, reserved=0):
    reservation = MaterialReservation(
        instance_id=instance.id,
        external_ref=f'iprm-instance-{instance.id}',
        status=status,
    )
    db.session.add(reservation)
    db.session.flush()
    reservation.items.append(MaterialReservationItem(
        sku='NDL-21', name='Голка 21G',
        quantity_requested=requested, quantity_reserved=reserved))
    db.session.flush()
    return reservation


class TestIsMmDocument:
    def test_a_legacy_hold_is_not_a_document(self, app):
        instance = _instance()
        reservation = _reservation(instance, MaterialReservationStatus.RESERVED,
                                   requested=None, reserved=5)

        assert reservation.is_mm_document is False

    def test_requested_quantity_marks_a_document(self, app):
        instance = _instance()
        reservation = _reservation(instance, MaterialReservationStatus.RESERVED,
                                   requested=7, reserved=7)

        assert reservation.is_mm_document is True

    def test_submitted_is_a_document_even_without_rows(self, app):
        """Штовх статусу летить без ретраїв: рядки можуть відстати, а
        SUBMITTED легасі-канал не виробляє взагалі."""
        instance = _instance()
        reservation = MaterialReservation(
            instance_id=instance.id,
            external_ref=f'iprm-instance-{instance.id}',
            status=MaterialReservationStatus.SUBMITTED)
        db.session.add(reservation)
        db.session.flush()

        assert reservation.is_mm_document is True


class TestWriteOffIsRefusedForADocument:
    def test_actuals_route_refuses_and_calls_nobody(self, app, client, admin,
                                                    monkeypatch):
        instance = _instance()
        _reservation(instance, MaterialReservationStatus.RESERVED,
                     requested=7, reserved=7)
        _login(client, admin)

        def _explode(*a, **kw):
            raise AssertionError('легасі-списання пішло в MM Medic')

        monkeypatch.setattr(routes.mrs, 'submit_actuals', _explode)

        response = client.post(
            f'/admin/instances/{instance.id}/materials/actuals',
            data={'sku': 'NDL-21', 'actual': '7'}, follow_redirects=True)

        assert response.status_code == 200
        assert 'керує документ MM Medic' in response.get_data(as_text=True)

    def test_adjust_route_refuses(self, app, client, admin, monkeypatch):
        instance = _instance()
        _reservation(instance, MaterialReservationStatus.CONSUMED,
                     requested=7, reserved=7)
        _login(client, admin)

        def _explode(*a, **kw):
            raise AssertionError('легасі-коригування пішло в MM Medic')

        monkeypatch.setattr(routes.mrs, 'adjust_actuals', _explode)

        response = client.post(
            f'/admin/instances/{instance.id}/materials/adjust',
            data={'sku': 'NDL-21', 'actual': '5'}, follow_redirects=True)

        assert 'керує документ MM Medic' in response.get_data(as_text=True)

    def test_a_legacy_reservation_still_writes_off(self, app, client, admin,
                                                   monkeypatch):
        """Старий канал не має постраждати: у проді він живий."""
        instance = _instance()
        _reservation(instance, MaterialReservationStatus.RESERVED,
                     requested=None, reserved=5)
        _login(client, admin)
        called = {}

        def _fake(instance_arg, actuals, **kw):
            called['actuals'] = actuals
            return True, type('R', (), {'ok': True, 'data': {}, 'error': None})()

        monkeypatch.setattr(routes.mrs, 'submit_actuals', _fake)

        client.post(f'/admin/instances/{instance.id}/materials/actuals',
                    data={'sku': 'NDL-21', 'actual': '4'}, follow_redirects=True)

        assert called['actuals'] == [{'sku': 'NDL-21', 'actual_qty': 4}]

    def test_the_page_offers_no_write_off_button(self, app, client, admin):
        instance = _instance()
        _reservation(instance, MaterialReservationStatus.RESERVED,
                     requested=7, reserved=7)
        _login(client, admin)

        html = client.get(
            f'/admin/instances/{instance.id}/materials').get_data(as_text=True)

        assert 'Провести списання' not in html
        assert 'Списання виконує комірник' in html


class _Result:
    """Мінімальний двійник `MMResult`: сервіс дивиться на ok/data/error."""

    ok = True
    error = None
    shortfalls = ()

    def __init__(self, data=None):
        self.data = data or {}


class TestSubmittedRequestIsCorrectedNotResubmitted:
    """Гвард дивився лише на RESERVED, тож подана заявка падала в режим
    подання. Натискання кликало `submit_request` ще раз, MM Medic повертав
    той самий документ БЕЗ ЗМІН (ідемпотентність), а людині писало «Подано
    на погодження N позицій»: не змінилось нічого, а сказано, що змінилось.
    """

    def test_the_page_offers_saving_the_request(self, app, client, admin):
        instance = _instance()
        _reservation(instance, MaterialReservationStatus.SUBMITTED,
                     requested=4, reserved=0)
        _login(client, admin)

        html = client.get(
            f'/admin/instances/{instance.id}/materials').get_data(as_text=True)

        assert 'Зберегти заявку' in html
        assert 'Подати на погодження' not in html
        assert f'/admin/instances/{instance.id}/materials/update' in html

    def test_the_form_carries_what_was_asked_for(self, app, client, admin):
        instance = _instance()
        _reservation(instance, MaterialReservationStatus.SUBMITTED,
                     requested=4, reserved=0)
        _login(client, admin)

        html = client.get(
            f'/admin/instances/{instance.id}/materials').get_data(as_text=True)

        assert 'value="4"' in html, 'у полі не запитана кількість'

    def test_update_route_rewrites_the_list_through_the_items_endpoint(
            self, app, client, admin, monkeypatch):
        instance = _instance()
        reservation = _reservation(instance, MaterialReservationStatus.SUBMITTED,
                                   requested=4, reserved=0)
        _login(client, admin)
        seen = {}

        class _Client:
            def update_request_items(self, ref, items, request_id=None):
                seen['ref'] = ref
                seen['items'] = items
                return _Result({'reservation': {
                    'status': 'submitted',
                    'items': [{'sku': 'NDL-21', 'name': 'Голка 21G',
                               'quantity': 9, 'quantity_requested': 9,
                               'quantity_approved': None}],
                }})

        monkeypatch.setattr(mrs_module, 'get_client', lambda: _Client())

        response = client.post(
            f'/admin/instances/{instance.id}/materials/update',
            data={'sku': 'NDL-21', 'quantity': '9'}, follow_redirects=True)

        assert response.status_code == 200
        assert seen['ref'] == f'iprm-instance-{instance.id}'
        assert seen['items'] == [{'sku': 'NDL-21', 'quantity': 9}]
        fresh = db.session.get(MaterialReservation, reservation.id)
        assert fresh.status == MaterialReservationStatus.SUBMITTED
        assert fresh.items[0].quantity_requested == 9

    def test_a_line_dropped_from_the_request_disappears_locally(
            self, app, client, admin, monkeypatch):
        """Залишений рядок показував би в пікінг-листі позицію, від якої
        людина щойно відмовилась."""
        instance = _instance()
        reservation = _reservation(instance, MaterialReservationStatus.SUBMITTED,
                                   requested=4, reserved=0)
        reservation.items.append(MaterialReservationItem(
            sku='GLV-M', name='Рукавички M', quantity_requested=2,
            quantity_reserved=0))
        db.session.flush()
        _login(client, admin)

        class _Client:
            def update_request_items(self, ref, items, request_id=None):
                return _Result({'reservation': {
                    'status': 'submitted',
                    'items': [{'sku': 'NDL-21', 'quantity_requested': 4}],
                }})

        monkeypatch.setattr(mrs_module, 'get_client', lambda: _Client())

        client.post(f'/admin/instances/{instance.id}/materials/update',
                    data={'sku': 'NDL-21', 'quantity': '4'},
                    follow_redirects=True)

        fresh = db.session.get(MaterialReservation, reservation.id)
        assert {item.sku for item in fresh.items} == {'NDL-21'}

    def test_resubmitting_a_submitted_request_is_refused(
            self, app, client, admin, monkeypatch):
        instance = _instance()
        _reservation(instance, MaterialReservationStatus.SUBMITTED,
                     requested=4, reserved=0)
        _login(client, admin)

        def _explode(*a, **kw):
            raise AssertionError('повторне подання пішло в MM Medic')

        monkeypatch.setattr(routes.mrs, 'submit_request', _explode)

        response = client.post(
            f'/admin/instances/{instance.id}/materials/reserve',
            data={'sku': 'NDL-21', 'quantity': '4'}, follow_redirects=True)

        assert 'Заявку вже подано' in response.get_data(as_text=True)


class TestIssuedRequestIsNotRolledBack:
    """У стані ISSUED -- нормальному на весь час заходу -- кнопка подання теж
    була жива, і натискання відкочувало дзеркало в SUBMITTED, стираючи
    `consumed_at` і `actuals_reminder_sent_at`. Звірка це не лікує: вона
    дивиться лише на заходи, чия дата вже минула."""

    def test_the_page_is_read_only(self, app, client, admin):
        instance = _instance()
        _reservation(instance, MaterialReservationStatus.ISSUED,
                     requested=4, reserved=4)
        _login(client, admin)

        html = client.get(
            f'/admin/instances/{instance.id}/materials').get_data(as_text=True)

        assert 'Подати на погодження' not in html
        assert 'Провести списання' not in html
        assert 'name="quantity"' not in html
        assert 'Списання виконує комірник' in html

    def test_submitting_again_is_refused_and_the_mirror_stands(
            self, app, client, admin, monkeypatch):
        instance = _instance()
        reservation = _reservation(instance, MaterialReservationStatus.ISSUED,
                                   requested=4, reserved=4)
        _login(client, admin)

        def _explode(*a, **kw):
            raise AssertionError('подання пішло в MM Medic на відвантаженому')

        monkeypatch.setattr(routes.mrs, 'submit_request', _explode)

        response = client.post(
            f'/admin/instances/{instance.id}/materials/reserve',
            data={'sku': 'NDL-21', 'quantity': '4'}, follow_redirects=True)

        assert 'вже відвантажено' in response.get_data(as_text=True)
        fresh = db.session.get(MaterialReservation, reservation.id)
        assert fresh.status == MaterialReservationStatus.ISSUED
