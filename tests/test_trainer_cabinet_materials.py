"""Сторінка заявки на матеріали в кабінеті тренера."""
import json
import re
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


def _flashes(resp):
    """Тексти flash-повідомлень зі сторінки. Flash рендериться JSON-блоком
    для тосту, а |tojson екранує кирилицю у \\uXXXX -- шукати підрядок у
    сирому HTML не можна (той самий хелпер, що в test_mm_medic_materials)."""
    match = re.search(
        r'<script type="application/json" id="iprm-flash-data">(.*?)</script>',
        resp.get_data(as_text=True), re.S,
    )
    if not match:
        return []
    return [item['message'] for item in json.loads(match.group(1))]


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


def test_submit_creates_a_pending_review_request(client, trainer_user, instance,
                                                 kit):
    """Подання рухає заявку в pending_review. Артикул -- з комплекту курсу:
    невідомий сервер у заявку більше не приймає (див. тести resolve_rows)."""
    from app.services import material_request_service as mrq

    _login(client, trainer_user)

    response = client.post(f'/trainer/materials/{instance.id}', data={
        'csrf_token': _csrf(client, f'/trainer/materials/{instance.id}'),
        'sku': ['NEEDLE-30G'],
        'quantity': ['12'],
        'action': 'submit',
    }, follow_redirects=True)

    assert response.status_code == 200
    reservation = mrq.mrs.get_reservation(instance.id)
    assert reservation.status == S.PENDING_REVIEW


def test_save_draft_keeps_the_request_a_draft(client, trainer_user, instance, kit):
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
        # Справжній каталог MM Medic віддає фото під `image` (не `image_url`).
        {'sku': 'NEEDLE-30G', 'name': 'Голки 30G', 'image': 'http://x/i.png',
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


# --- Межа довіри: назву, фото й артикул знає сервер, а не форма -------------

def _catalog(monkeypatch, *products):
    """Підмінити каталог MM Medic справжньою формою відповіді (ключ `image`)."""
    from app.services import material_reservation_service as mrs
    monkeypatch.setattr(mrs, 'get_catalog', lambda **kw: (list(products), None, False))


def test_forged_name_and_image_do_not_reach_the_reviewers(client, trainer_user,
                                                          instance, monkeypatch):
    """Доти назву й фото сервер брав із прихованих полів форми, і тренер міг
    підписати артикул голок як «шприци»: відповідальний погодив би шприци,
    склад відвантажив би голки. Тепер ідентичність позиції -- з каталогу."""
    from app.services import material_request_service as mrq

    _catalog(monkeypatch, {'sku': 'NEEDLE-30G', 'name': 'Голки 30G',
                           'image': 'https://mm-medic.example/needle.jpg'})
    _login(client, trainer_user)

    client.post(f'/trainer/materials/{instance.id}', data={
        'csrf_token': _csrf(client, f'/trainer/materials/{instance.id}'),
        'sku': ['NEEDLE-30G'], 'quantity': ['3'],
        'name': ['Шприци 5 мл'], 'image_url': ['https://evil.example/pixel.gif'],
        'action': 'draft',
    })

    item = mrq.mrs.get_reservation(instance.id).items[0]
    assert item.name == 'Голки 30G'
    assert item.image_url == 'https://mm-medic.example/needle.jpg'


def test_unknown_sku_is_not_saved_and_the_trainer_is_told(client, trainer_user,
                                                          instance, kit, monkeypatch):
    """Артикул, якого немає ні в каталозі, ні в комплекті, ні в заявці, --
    вигаданий. Доти він лягав у заявку й валив погодження на MM Medic."""
    from app.services import material_request_service as mrq

    _catalog(monkeypatch)  # каталог порожній: відомий лише комплект
    _login(client, trainer_user)

    response = client.post(f'/trainer/materials/{instance.id}', data={
        'csrf_token': _csrf(client, f'/trainer/materials/{instance.id}'),
        # Звичайної довжини: наддовгий артикул мовчки відсіює ще парсер
        # (test_parse_form_rows_boundaries), тут перевіряється шлях resolve_rows.
        'sku': ['NEEDLE-30G', 'FORGED-1'],
        'quantity': ['3', '5'], 'action': 'draft',
    }, follow_redirects=True)

    skus = [i.sku for i in mrq.mrs.get_reservation(instance.id).items]
    assert skus == ['NEEDLE-30G']
    assert any('не збережено' in m for m in _flashes(response)), _flashes(response)


def test_quantity_over_the_limit_is_refused_not_a_500(client, trainer_user,
                                                      instance, kit):
    """11-значне число переповнювало int4 на Postgres: DataError і 500.
    SQLite цього не бачить, тому межа перевіряється явно."""
    from app.services import material_request_service as mrq

    _login(client, trainer_user)

    response = client.post(f'/trainer/materials/{instance.id}', data={
        'csrf_token': _csrf(client, f'/trainer/materials/{instance.id}'),
        'sku': ['NEEDLE-30G'], 'quantity': ['99999999999'], 'action': 'draft',
    }, follow_redirects=True)

    assert response.status_code == 200
    assert any('не може перевищувати' in m for m in _flashes(response)), _flashes(response)
    assert mrq.mrs.get_reservation(instance.id) is None


@pytest.mark.parametrize('skus, quantities, expected', [
    (['A'], ['3'], [{'sku': 'A', 'quantity': 3}]),
    (['A', 'B'], ['', '0'], []),                 # прибрані рядки
    (['A'], ['abc'], []),                        # нечислове -- прибраний
    (['A'], ['1e400'], []),                      # inf -> OverflowError, не 500
    (['  A  '], ['2,0'], [{'sku': 'A', 'quantity': 2}]),
    (['X' * 101], ['1'], []),                    # довший за колонку sku
])
def test_parse_form_rows_boundaries(app, skus, quantities, expected):
    from app.services import material_request_service as mrq
    assert mrq.parse_form_rows(skus, quantities) == expected


def test_parse_form_rows_refuses_too_many_rows(app):
    from app.services import material_request_service as mrq
    skus = [f'S{i}' for i in range(mrq.MAX_ROWS + 1)]
    with pytest.raises(mrq.RequestTransitionError):
        mrq.parse_form_rows(skus, ['1'] * len(skus))


# --- Префіл: один комплект, а не сума всіх ---------------------------------

def _kit(course_id, name, sku, quantity, is_default=False):
    kit = MaterialKit(name=name, course_id=course_id, is_active=True,
                      is_default=is_default)
    db.session.add(kit)
    db.session.flush()
    db.session.add(MaterialKitItem(kit_id=kit.id, sku=sku,
                                   name_snapshot=name, quantity=quantity))
    db.session.commit()
    return kit


def test_prefill_takes_the_default_kit_not_the_sum(app, instance):
    """Комплекти -- альтернативи («пропонується першим при застосуванні»).
    Доти «Базовий» + «Розширений» складались, і тренер бачив подвоєне."""
    from app.services import material_request_service as mrq

    _kit(instance.course_id, 'Базовий', 'NEEDLE-30G', 10, is_default=True)
    _kit(instance.course_id, 'Розширений', 'NEEDLE-30G', 25)

    rows = mrq.prefill_rows(instance)

    assert [(r['sku'], r['quantity']) for r in rows] == [('NEEDLE-30G', 10)]


def test_prefill_does_not_guess_between_several_unmarked_kits(app, instance):
    from app.services import material_request_service as mrq

    _kit(instance.course_id, 'Перший', 'A-1', 5)
    _kit(instance.course_id, 'Другий', 'B-2', 5)

    assert mrq.prefill_rows(instance) == []


def test_prefill_prefers_the_course_kit_over_a_universal_one(app, instance):
    from app.services import material_request_service as mrq

    _kit(None, 'Універсальний', 'UNI-1', 3, is_default=True)
    _kit(instance.course_id, 'Курсовий', 'OWN-1', 7)

    assert [r['sku'] for r in mrq.prefill_rows(instance)] == ['OWN-1']


# --- Заявку приймає лише живий захід ---------------------------------------

@pytest.mark.parametrize('status, days, expected', [
    ('published', 7, True),
    ('active', 0, True),
    ('published', -3, False),   # минув
    ('cancelled', 7, False),
    ('draft', 7, False),
])
def test_accepts_requests(app, instance, status, days, expected):
    from app.services import material_request_service as mrq

    instance.status = status
    instance.start_date = datetime.now(timezone.utc) + timedelta(days=days)
    instance.end_date = None
    db.session.commit()

    assert mrq.accepts_requests(instance) is expected


def test_request_for_a_past_event_is_refused(client, trainer_user, instance, kit):
    """Сторінка відкривається за прямим URL -- доти й заявку на минулий захід
    приймала, і відповідальному лишалось хіба відхилити її."""
    from app.services import material_request_service as mrq

    instance.start_date = datetime.now(timezone.utc) - timedelta(days=3)
    db.session.commit()
    _login(client, trainer_user)

    response = client.post(f'/trainer/materials/{instance.id}', data={
        'csrf_token': _csrf(client, f'/trainer/materials/{instance.id}'),
        'sku': ['NEEDLE-30G'], 'quantity': ['3'], 'action': 'submit',
    }, follow_redirects=True)

    assert mrq.mrs.get_reservation(instance.id) is None
    assert any('уже не приймаємо' in m for m in _flashes(response)), _flashes(response)


# --- Невалідний POST і сторінка без MM Medic --------------------------------

def test_rejected_form_keeps_the_trainer_rows_and_says_why(client, trainer_user,
                                                          instance, kit):
    """Доти невалідна форма мовчки показувала ЗБЕРЕЖЕНІ рядки: правки
    тренера зникали без жодного слова."""
    from app.services import material_request_service as mrq

    _login(client, trainer_user)

    response = client.post(f'/trainer/materials/{instance.id}', data={
        'csrf_token': _csrf(client, f'/trainer/materials/{instance.id}'),
        'sku': ['NEEDLE-30G'], 'quantity': ['777'],
        'comment': 'x' * 2001, 'action': 'draft',
    })

    assert response.status_code == 200
    assert any('задовгий' in m for m in _flashes(response)), _flashes(response)
    assert 'value="777"' in response.get_data(as_text=True)
    assert mrq.mrs.get_reservation(instance.id) is None


def test_request_page_does_not_call_the_partner_on_render(client, trainer_user,
                                                         instance, kit, monkeypatch):
    """Шаблону каталог не потрібен, а живий виклик MM Medic (з ретраями) на
    холодному кеші вішав сторінку. Про недоступність скаже пошук."""
    from app.services import material_reservation_service as mrs

    def _boom(**kwargs):
        raise AssertionError('сторінка не мала питати каталог')

    monkeypatch.setattr(mrs, 'get_catalog', _boom)
    _login(client, trainer_user)

    response = client.get(f'/trainer/materials/{instance.id}')

    assert response.status_code == 200
    assert b'data-catalog-status' in response.data
