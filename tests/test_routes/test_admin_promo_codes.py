"""Адмін-CRUD промокодів + ручне застосування коду у формі учасника."""
from tests.support.rbac import grant_role
from decimal import Decimal
from uuid import uuid4

import pytest

from app.extensions import db
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.promo_code import PromoCode
from app.models.registration import EventRegistration
from app.models.user import User
from app.services import promo_service


@pytest.fixture
def admin(app):
    u = User.create_with_password(
        f'ap-{uuid4().hex[:6]}@test.com', 'password123',
        first_name='А', last_name='Адмін', email_confirmed=True,
    )
    grant_role(u, 'super_admin')
    db.session.flush()
    return u


def _login(client, user):
    with client.session_transaction() as s:
        s['_user_id'] = str(user.id)


def _promo(code='ADMIN', **kwargs):
    kwargs.setdefault('discount_type', 'percent')
    kwargs.setdefault('discount_value', Decimal('50'))
    code = f'{code}-{uuid4().hex[:6]}'
    promo = PromoCode(code=code, code_norm=promo_service.normalize_code(code),
                      **kwargs)
    db.session.add(promo)
    db.session.flush()
    return promo


def _instance(price=1000):
    # is_active=False -- адмінка на це не дивиться, а закомічені активні
    # курси накопичуються у спільній тестовій БД і засмічують публічні
    # списки/каталог іншим тестам.
    course = Course(title='Курс', slug=f'ap-{uuid4().hex[:6]}', is_active=False)
    db.session.add(course)
    db.session.flush()
    inst = CourseInstance(course_id=course.id, status='published', price=price)
    db.session.add(inst)
    db.session.flush()
    return inst


def test_pages_render(client, admin):
    _login(client, admin)
    promo = _promo()
    assert client.get('/admin/promo-codes').status_code == 200
    assert client.get('/admin/promo-codes/new').status_code == 200
    assert client.get(f'/admin/promo-codes/{promo.id}').status_code == 200
    assert client.get(f'/admin/promo-codes/{promo.id}/edit').status_code == 200


def test_requires_admin(client):
    assert client.get('/admin/promo-codes').status_code in (302, 401, 403)


def test_create(client, admin):
    _login(client, admin)
    code = f'Дмитро-{uuid4().hex[:6]}'
    resp = client.post('/admin/promo-codes/new', data={
        'code': f'  {code}  ',
        'description': 'Персонально',
        'discount_type': 'percent',
        'discount_value': '100',
        'max_uses': '1',
        'per_user_limit': '1',
        'course_id': '',
        'instance_id': '',
        'is_active': 'y',
    }, follow_redirects=True)
    assert resp.status_code == 200

    promo = PromoCode.query.filter_by(
        code_norm=promo_service.normalize_code(code)).one()
    assert promo.code == code          # пробіли обрізано, регістр збережено
    assert promo.max_uses == 1
    assert promo.is_active is True


def test_batch_creates_unique_codes_with_shared_prefix(client, admin):
    """Кейс фарми: 5 місць -- п'ять одноразових кодів, а не один на п'ятьох."""
    _login(client, admin)
    prefix = f'PHARMA{uuid4().hex[:4].upper()}'

    resp = client.post('/admin/promo-codes/new', data={
        'code': prefix,
        'description': 'Фарма X, рекламний внесок',
        'discount_type': 'percent', 'discount_value': '100',
        'max_uses': '1', 'per_user_limit': '1',
        'course_id': '', 'instance_id': '', 'is_active': 'y',
        'batch_count': '5',
    }, follow_redirects=True)
    assert resp.status_code == 200

    codes = PromoCode.query.filter(PromoCode.code.startswith(prefix)).all()
    assert len(codes) == 5
    assert len({c.code for c in codes}) == 5           # усі різні
    assert all(c.max_uses == 1 for c in codes)         # налаштування спільні
    assert all(c.discount_value == Decimal('100') for c in codes)
    assert all(c.description == 'Фарма X, рекламний внесок' for c in codes)
    # Сам префікс окремим кодом не створюється.
    assert PromoCode.query.filter_by(
        code_norm=promo_service.normalize_code(prefix)).first() is None


def test_batch_of_one_behaves_as_plain_create(client, admin):
    _login(client, admin)
    code = f'single-{uuid4().hex[:6]}'
    client.post('/admin/promo-codes/new', data={
        'code': code, 'discount_type': 'percent', 'discount_value': '10',
        'course_id': '', 'instance_id': '', 'is_active': 'y',
        'batch_count': '1',
    }, follow_redirects=True)

    promo = PromoCode.query.filter_by(
        code_norm=promo_service.normalize_code(code)).one()
    assert promo.code == code       # без згенерованого суфікса


def test_generated_codes_avoid_ambiguous_characters(app):
    """Коди диктують телефоном -- 0/O та 1/I/L там не місце."""
    code = promo_service.generate_code('TEST')
    suffix = code.rsplit('-', 1)[1]
    assert len(suffix) == promo_service.GENERATED_SUFFIX_LENGTH
    assert not set(suffix) & set('01OIL')


def test_duplicate_code_rejected(client, admin):
    _login(client, admin)
    existing = _promo('dup')
    db.session.commit()

    resp = client.post('/admin/promo-codes/new', data={
        'code': existing.code.upper(),   # той самий код іншим регістром
        'discount_type': 'percent', 'discount_value': '10',
        'course_id': '', 'instance_id': '', 'is_active': 'y',
    })
    assert resp.status_code == 200
    assert PromoCode.query.filter_by(code_norm=existing.code_norm).count() == 1


def test_percent_over_100_rejected(client, admin):
    _login(client, admin)
    code = f'over-{uuid4().hex[:6]}'
    resp = client.post('/admin/promo-codes/new', data={
        'code': code, 'discount_type': 'percent', 'discount_value': '150',
        'course_id': '', 'instance_id': '', 'is_active': 'y',
    })
    assert resp.status_code == 200
    assert PromoCode.query.filter_by(
        code_norm=promo_service.normalize_code(code)).first() is None


def test_instance_scope_wins_over_course(client, admin):
    """Обидві прив'язки разом -- зайве правило; лишається вужча."""
    _login(client, admin)
    inst = _instance()
    db.session.commit()
    code = f'scope-{uuid4().hex[:6]}'

    client.post('/admin/promo-codes/new', data={
        'code': code, 'discount_type': 'percent', 'discount_value': '10',
        'course_id': str(inst.course_id), 'instance_id': str(inst.id),
        'is_active': 'y',
    }, follow_redirects=True)

    promo = PromoCode.query.filter_by(
        code_norm=promo_service.normalize_code(code)).one()
    assert promo.instance_id == inst.id
    assert promo.course_id is None


def test_toggle_and_recount_and_delete(client, admin):
    _login(client, admin)
    promo = _promo('togg', used_count=5)
    db.session.commit()

    client.post(f'/admin/promo-codes/{promo.id}/toggle')
    assert db.session.get(PromoCode, promo.id).is_active is False

    client.post(f'/admin/promo-codes/{promo.id}/recount')
    assert db.session.get(PromoCode, promo.id).used_count == 0

    client.post(f'/admin/promo-codes/{promo.id}/delete')
    assert db.session.get(PromoCode, promo.id) is None


# --- ручне застосування у формі учасника ------------------------------------

def _participant_payload(**over):
    data = {
        'last_name': 'Іваненко',
        'first_name': 'Олена',
        'phone': '+380501234567',
        'email': f'part-{uuid4().hex[:6]}@test.com',
        'status': 'confirmed',
        'payment_status': 'unpaid',
        'payment_amount': '1000',
        'participant_type': '',
    }
    data.update(over)
    return data


def test_manager_applies_promo_to_new_participant(client, admin):
    _login(client, admin)
    inst = _instance()
    promo = _promo('manager', discount_value=Decimal('100'))
    db.session.commit()

    resp = client.post(
        f'/admin/instances/{inst.id}/participants/new',
        data=_participant_payload(instance_id=str(inst.id),
                                  promo_code=promo.code),
        follow_redirects=True,
    )
    assert resp.status_code == 200

    reg = EventRegistration.query.filter_by(instance_id=inst.id).one()
    assert reg.payment_amount == Decimal('0.00')
    assert reg.discount_amount == Decimal('1000.00')
    assert reg.promo_code_id == promo.id
    assert db.session.get(PromoCode, promo.id).used_count == 1


def test_manager_removes_promo_on_edit(client, admin):
    _login(client, admin)
    inst = _instance()
    promo = _promo('removable', discount_value=Decimal('50'))
    db.session.commit()

    client.post(f'/admin/instances/{inst.id}/participants/new',
                data=_participant_payload(instance_id=str(inst.id),
                                          promo_code=promo.code),
                follow_redirects=True)
    reg = EventRegistration.query.filter_by(instance_id=inst.id).one()
    assert reg.payment_amount == Decimal('500.00')

    client.post(f'/admin/registrations/{reg.id}/edit',
                data=_participant_payload(instance_id=str(inst.id),
                                          email=reg.user.email,
                                          promo_code=''),
                follow_redirects=True)

    reg = db.session.get(EventRegistration, reg.id)
    assert reg.promo_code_id is None
    assert reg.discount_amount is None
    assert reg.payment_amount == Decimal('1000.00')
    assert db.session.get(PromoCode, promo.id).used_count == 0


def test_promo_blocked_on_online_paid_registration(client, admin):
    """Гроші вже пройшли через LiqPay -- знижка змінила б суму повернення."""
    _login(client, admin)
    inst = _instance()
    promo = _promo('too-late', discount_value=Decimal('50'))
    db.session.commit()

    base = _participant_payload(instance_id=str(inst.id),
                                payment_status='paid', promo_code='')
    client.post(f'/admin/instances/{inst.id}/participants/new', data=base,
                follow_redirects=True)
    reg = EventRegistration.query.filter_by(instance_id=inst.id).one()
    reg.payment_id = 'LP-77777'
    db.session.commit()

    resp = client.post(f'/admin/registrations/{reg.id}/edit',
                       data={**base, 'email': reg.user.email,
                             'promo_code': promo.code},
                       follow_redirects=True)
    assert resp.status_code == 200

    reg = db.session.get(EventRegistration, reg.id)
    db.session.refresh(reg)
    assert reg.payment_amount == Decimal('1000.00')
    assert reg.promo_code_id is None
    assert db.session.get(PromoCode, promo.id).used_count == 0


def test_paid_registration_keeps_amount_on_plain_resave(client, admin):
    """Оплачена онлайн реєстрація зі знижкою: збереження форми не має
    піднімати суму до до-знижкової (форма показує саме її)."""
    _login(client, admin)
    inst = _instance()
    promo = _promo('paid-keep', discount_value=Decimal('50'))
    db.session.commit()

    base = _participant_payload(instance_id=str(inst.id))
    client.post(f'/admin/instances/{inst.id}/participants/new',
                data={**base, 'promo_code': promo.code}, follow_redirects=True)
    reg = EventRegistration.query.filter_by(instance_id=inst.id).one()
    reg.payment_status = 'paid'
    reg.payment_id = 'LP-88888'
    db.session.commit()
    assert reg.payment_amount == Decimal('500.00')

    client.post(f'/admin/registrations/{reg.id}/edit',
                data={**base, 'email': reg.user.email,
                      'payment_status': 'paid', 'payment_amount': '1000',
                      'promo_code': promo.code},
                follow_redirects=True)

    reg = db.session.get(EventRegistration, reg.id)
    db.session.refresh(reg)
    assert reg.payment_amount == Decimal('500.00')
    assert reg.discount_amount == Decimal('500.00')


def test_orphaned_discount_snapshot_is_cleared(client, admin):
    """Промокод видалили (FK SET NULL) -- знімок знижки не має роздувати
    суму при кожному збереженні форми."""
    _login(client, admin)
    inst = _instance()
    promo = _promo('deleted-later', discount_value=Decimal('50'))
    db.session.commit()

    base = _participant_payload(instance_id=str(inst.id))
    client.post(f'/admin/instances/{inst.id}/participants/new',
                data={**base, 'promo_code': promo.code}, follow_redirects=True)
    reg = EventRegistration.query.filter_by(instance_id=inst.id).one()

    # Стан після ON DELETE SET NULL на PostgreSQL (SQLite у тестах FK-дії
    # не виконує, тож відтворюємо його руками).
    client.post(f'/admin/promo-codes/{promo.id}/delete', follow_redirects=True)
    reg = db.session.get(EventRegistration, reg.id)
    reg.promo_code_id = None
    db.session.commit()

    client.post(f'/admin/registrations/{reg.id}/edit',
                data={**base, 'email': reg.user.email,
                      'payment_amount': str(int(reg.amount_before_discount)),
                      'promo_code': ''},
                follow_redirects=True)

    reg = db.session.get(EventRegistration, reg.id)
    db.session.refresh(reg)
    assert reg.discount_amount is None
    assert reg.payment_amount == Decimal('1000.00')
    assert reg.amount_before_discount == Decimal('1000.00')


def test_resaving_form_does_not_double_apply(client, admin):
    """Повторне збереження форми не має різати суму вдруге."""
    _login(client, admin)
    inst = _instance()
    promo = _promo('resave', discount_value=Decimal('50'), per_user_limit=1)
    db.session.commit()

    client.post(f'/admin/instances/{inst.id}/participants/new',
                data=_participant_payload(instance_id=str(inst.id),
                                          promo_code=promo.code),
                follow_redirects=True)
    reg = EventRegistration.query.filter_by(instance_id=inst.id).one()

    # Форма редагування показує суму ДО знижки -- саме її і надсилаємо назад.
    client.post(f'/admin/registrations/{reg.id}/edit',
                data=_participant_payload(instance_id=str(inst.id),
                                          email=reg.user.email,
                                          payment_amount='1000',
                                          promo_code=promo.code),
                follow_redirects=True)

    reg = db.session.get(EventRegistration, reg.id)
    assert reg.payment_amount == Decimal('500.00')
    assert db.session.get(PromoCode, promo.id).used_count == 1
