"""Сторінка заявки на матеріали в кабінеті тренера."""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from app.extensions import db
from app.models.auth_identity import AuthIdentity
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.material_kit import MaterialKit, MaterialKitItem
from app.models.material_reservation import MaterialReservationStatus as S
from app.models.medical_profile import MedicalProfile
from app.models.trainer import Trainer
from app.models.user import User
from app.services import trainer_links
from tests.support.rbac import switch_user

# Усі акаунти цього файлу -- з цим префіксом. Тестова БД спільна на всю
# сесію pytest, і залишений тут користувач витісняє чужий тест зі сторінки
# /api/v1/participants (максимум 200 рядків) -- симптом виникає за
# кілометр звідси і не вказує на причину (feedback_test_user_cap).
EMAIL_PREFIX = 'tcm-'


@pytest.fixture(autouse=True)
def _clean_users():
    """Прибрати користувачів цього файлу до і після кожного тесту."""
    def _wipe():
        stale = [row.id for row in User.query.filter(
            User.email.like(f'{EMAIL_PREFIX}%@test.com')).all()]
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


def _login(client, user):
    """Залогінити тестовий клієнт як `user`. Тонка обгортка над
    `switch_user`: у файлі кожен тест працює лише одним користувачем, але
    сам хелпер -- те, що проєкт вимагає для зміни користувача в тестах."""
    return switch_user(client, user)


def _csrf(client, url):
    """CSRF-токен для форми на `url`.

    `TestingConfig.WTF_CSRF_ENABLED = False` (config.py) -- форма
    валідується без перевірки токена, тож реальний токен тут не потрібен.
    Поле лишається в POST-даних тестів заради читабельності запиту.
    """
    return 'csrf-disabled-in-tests'


@pytest.fixture
def trainer_user():
    """Тренер, залогінений користувач з активною карткою."""
    user = User.create_with_password(
        f'{EMAIL_PREFIX}{uuid4().hex[:8]}@test.com', 'password123',
        first_name='Тест', last_name='Тренер', email_confirmed=True,
    )
    db.session.flush()
    trainer = Trainer(full_name='Тренер Матеріалів',
                      slug=f'{EMAIL_PREFIX}{uuid4().hex[:10]}',
                      is_active=True, user_id=user.id)
    db.session.add(trainer)
    db.session.commit()
    return user


@pytest.fixture
def instance(trainer_user):
    """Захід, де `trainer_user` -- тренер курсу (через course_trainers)."""
    course = Course(title=f'Курс {uuid4().hex[:4]}',
                    slug=f'{EMAIL_PREFIX}{uuid4().hex[:10]}')
    db.session.add(course)
    db.session.flush()
    trainer_links.set_trainers(course, [trainer_user.active_trainer.id])
    inst = CourseInstance(
        course_id=course.id, status='published', event_format='offline',
        start_date=datetime.now(timezone.utc) + timedelta(days=7),
        max_participants=20,
    )
    db.session.add(inst)
    db.session.commit()
    return inst


@pytest.fixture
def foreign_instance():
    """Захід стороннього курсу -- без жодного тренера, отже, не тренера
    з `trainer_user`."""
    course = Course(title=f'Курс {uuid4().hex[:4]}',
                    slug=f'{EMAIL_PREFIX}{uuid4().hex[:10]}')
    db.session.add(course)
    db.session.flush()
    inst = CourseInstance(
        course_id=course.id, status='published', event_format='offline',
        start_date=datetime.now(timezone.utc) + timedelta(days=7),
        max_participants=20,
    )
    db.session.add(inst)
    db.session.commit()
    return inst


@pytest.fixture
def kit(instance):
    """Стандартний комплект курсу: одна позиція, NEEDLE-30G."""
    material_kit = MaterialKit(name='Стандартний набір',
                               course_id=instance.course_id, is_active=True)
    db.session.add(material_kit)
    db.session.flush()
    db.session.add(MaterialKitItem(kit_id=material_kit.id, sku='NEEDLE-30G',
                                   name_snapshot='Голки 30G', quantity=10))
    db.session.commit()
    return material_kit


def test_foreign_instance_is_not_found(client, trainer_user, foreign_instance):
    """404, а не 403: стороннього не стосується навіть факт існування заявки."""
    _login(client, trainer_user)
    response = client.get(f'/trainer/materials/{foreign_instance.id}')
    assert response.status_code == 404


def test_own_instance_opens_prefilled_with_the_course_kit(client, trainer_user,
                                                          instance, kit):
    _login(client, trainer_user)
    response = client.get(f'/trainer/materials/{instance.id}')
    assert response.status_code == 200
    assert b'NEEDLE-30G' in response.data


def test_submit_creates_a_pending_review_request(client, trainer_user, instance):
    """Подання рухає заявку в pending_review. Лист -- окрема турбота
    наступної задачі (там існує й `EmailService.send_material_request_submitted`,
    якого зараз ще немає): тут перевіряється лише зміна статусу."""
    from app.services import material_request_service as mrq

    _login(client, trainer_user)

    response = client.post(f'/trainer/materials/{instance.id}', data={
        'csrf_token': _csrf(client, f'/trainer/materials/{instance.id}'),
        'sku': ['NEEDLE-30G', 'TUBE-VAC'],
        'quantity': ['12', '24'],
        'action': 'submit',
    }, follow_redirects=True)

    assert response.status_code == 200
    reservation = mrq.mrs.get_reservation(instance.id)
    assert reservation.status == S.PENDING_REVIEW


def test_save_draft_keeps_the_request_a_draft(client, trainer_user, instance):
    from app.services import material_request_service as mrq

    _login(client, trainer_user)

    client.post(f'/trainer/materials/{instance.id}', data={
        'csrf_token': _csrf(client, f'/trainer/materials/{instance.id}'),
        'sku': ['NEEDLE-30G'], 'quantity': ['5'], 'action': 'draft',
    })

    assert mrq.mrs.get_reservation(instance.id).status == S.DRAFT


def test_pending_request_is_read_only(client, trainer_user, instance):
    """Тренер відправив і відкрив стару вкладку -- POST не має перетерти
    те, що відповідальний уже дивиться."""
    from app.services import material_request_service as mrq

    _login(client, trainer_user)
    res = mrq.get_or_create_draft(instance, trainer_user)
    mrq.save_items(res, [{'sku': 'NEEDLE-30G', 'name': None,
                          'image_url': None, 'quantity': 3}])
    mrq.submit(res, trainer_user)

    response = client.post(f'/trainer/materials/{instance.id}', data={
        'csrf_token': _csrf(client, f'/trainer/materials/{instance.id}'),
        'sku': ['NEEDLE-30G'], 'quantity': ['999'], 'action': 'submit',
    }, follow_redirects=True)

    assert response.status_code == 200
    db.session.refresh(res)
    assert res.items[0].quantity_requested == 3


def test_catalog_projection_hides_stock_and_prices(app, monkeypatch):
    """Складські числа не ховаються стилями -- вони не надсилаються взагалі."""
    from app.services import material_request_service as mrq

    monkeypatch.setattr(mrq.mrs, 'get_catalog', lambda **kw: ([
        {'sku': 'NEEDLE-30G', 'name': 'Голки 30G', 'image_url': 'http://x/i.png',
         'quantity_available': 140, 'price_uah': '12.50', 'min_stock': 20},
    ], None, False))

    items, unavailable = mrq.catalog_for_trainer()

    assert unavailable is False
    assert items == [{'sku': 'NEEDLE-30G', 'name': 'Голки 30G',
                      'image_url': 'http://x/i.png'}]
    serialized = repr(items)
    for leaked in ('140', '12.50', 'min_stock', 'quantity_available'):
        assert leaked not in serialized


def test_form_still_works_when_the_partner_is_silent(app, instance, monkeypatch,
                                                     kit):
    """Комплект курсу лежить локально -- головний сценарій не залежить від
    чужого сервера."""
    from app.services import material_request_service as mrq

    monkeypatch.setattr(mrq.mrs, 'get_catalog',
                        lambda **kw: ([], 'partner down', False))

    items, unavailable = mrq.catalog_for_trainer()
    assert unavailable is True
    assert items == []

    rows = mrq.prefill_rows(instance)
    assert [r['sku'] for r in rows] == ['NEEDLE-30G']


def _request_in(instance, trainer_user, status, comment=None):
    """Заявка з одним рядком у заданому стані -- для перевірки текстів."""
    from app.services import material_request_service as mrq

    res = mrq.get_or_create_draft(instance, trainer_user)
    mrq.save_items(res, [{'sku': 'NEEDLE-30G', 'name': None,
                          'image_url': None, 'quantity': 3}])
    res.status = status
    res.review_comment = comment
    db.session.commit()
    return res


@pytest.mark.parametrize('status, expected, forbidden', [
    (S.RETURNED, 'Заявку повернуто на доопрацювання', 'Заявку відхилено'),
    (S.REJECTED, 'Заявку відхилено', 'якщо її повернуть'),
    (S.PENDING_REVIEW, 'надіслано на перевірку', 'Заявку відхилено'),
    (S.SUBMITTED, 'Заявку погоджено й передано на склад', 'надіслано на перевірку'),
    (S.RESERVED, 'Заявку погоджено й передано на склад', 'надіслано на перевірку'),
    (S.CANCELLED, 'Цю заявку вже не можна редагувати', 'надіслано на перевірку'),
])
def test_request_page_says_what_actually_happened(client, trainer_user, instance,
                                                   status, expected, forbidden):
    """Доти відхилену заявку підписували «Заявку повернуто» з обіцянкою
    «редагувати можна буде, якщо повернуть», а погоджену -- «надіслано на
    перевірку». Тренер читав неправду про власну заявку."""
    _request_in(instance, trainer_user, status, comment='Захід без матеріалів')
    _login(client, trainer_user)

    body = client.get(f'/trainer/materials/{instance.id}').get_data(as_text=True)

    assert expected in body
    assert forbidden not in body
    if status == S.REJECTED:
        assert 'Причина: Захід без матеріалів' in body


def test_list_badge_speaks_the_trainer_language(client, trainer_user, instance):
    """Бейдж стану в кабінеті перекладний. Модельний `status_label` --
    українська мова адмінки («На погодженні»), якої тренеру не видно."""
    _request_in(instance, trainer_user, S.SUBMITTED)
    _login(client, trainer_user)

    from flask_babel import refresh

    uk = client.get('/trainer/materials').get_data(as_text=True)
    # flask_babel кешує локаль на `g`, а app-контекст у тестах один на весь
    # тест: без refresh() другий запит отримав би локаль першого.
    refresh()
    ru = client.get('/ru/trainer/materials').get_data(as_text=True)

    assert 'Передано на склад' in uk
    assert 'На погодженні' not in uk
    assert 'Передано на склад' in ru
    assert 'Материалы к мероприятию' in ru
