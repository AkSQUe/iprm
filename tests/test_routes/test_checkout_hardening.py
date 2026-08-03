"""Гострі кути гостьового чекауту: чужий акаунт, гонки, подвійний сабміт.

Гостьова покупка відкрила для анонімів шлях, який раніше був за логіном.
Кожен інваріант, який доти тримався тим, що "користувач уже наш і він
один", тепер треба тримати явно.
"""
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import pytest

from app.extensions import db
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.medical_profile import MedicalProfile
from app.models.registration import EventRegistration
from app.models.user import User
from app.services import participant_service


JS_DIR = Path(__file__).resolve().parents[2] / 'app' / 'static' / 'js'


@pytest.fixture(autouse=True)
def _no_rate_limit(app):
    from app.extensions import limiter
    limiter.enabled = False
    yield
    limiter.enabled = True


@pytest.fixture(autouse=True)
def _no_recaptcha(monkeypatch):
    monkeypatch.setattr('app.registration.routes.verify_recaptcha',
                        lambda action=None: True)


@pytest.fixture
def open_instance(app):
    """Проведення, на яке реально відкрита реєстрація."""
    with app.app_context():
        course = Course(title=f'Курс {uuid4().hex[:4]}',
                        slug=f'h-{uuid4().hex[:6]}',
                        is_active=True, event_type='course')
        db.session.add(course)
        db.session.flush()
        inst = CourseInstance(
            course_id=course.id, status='published', event_format='online',
            price=1000,
            start_date=datetime.now(timezone.utc) + timedelta(days=30),
        )
        db.session.add(inst)
        db.session.commit()
        return inst.id


# --------------------------------------------------------------------------
# CRITICAL-1: подвійний сабміт
# --------------------------------------------------------------------------

def test_single_submit_guard_covers_external_buttons():
    """Кнопку липкої панелі винесено за </form> і прив'язано атрибутом
    form="reg-form". form.querySelectorAll бачить лише НАЩАДКІВ, тож без
    окремого пошуку по [form=id] головна кнопка оплати не блокувалась би."""
    js = (JS_DIR / 'form-single-submit.js').read_text(encoding='utf-8')
    assert "'[form=\"'" in js or "'button[form=\"'" in js, (
        'guard не шукає кнопки, прив\'язані атрибутом form="<id>"'
    )
    assert 'form.id' in js


def test_single_submit_guard_prevents_repeat_submit():
    """Раніше повторний сабміт просто виходив з обробника -- і запит усе
    одно летів на сервер. Має бути preventDefault."""
    js = (JS_DIR / 'form-single-submit.js').read_text(encoding='utf-8')
    block = re.search(
        r"dataset\.submitting\s*===\s*'true'\s*\)\s*\{(.*?)\}", js, re.DOTALL,
    )
    assert block, 'немає перевірки повторного сабміту'
    assert 'preventDefault' in block.group(1)


def test_sticky_pay_button_is_bound_to_registration_form():
    """Зв'язок розмітки з guard-ом: якщо id форми або атрибут form зміняться,
    захист тихо перестане покривати кнопку."""
    tpl = (Path(__file__).resolve().parents[2] / 'app' / 'templates'
           / 'registration' / 'register.html').read_text(encoding='utf-8')
    form_id = re.search(r'<form[^>]*\bid="([^"]+)"', tpl)
    assert form_id, 'у формі реєстрації немає id'
    assert f'form="{form_id.group(1)}"' in tpl, (
        'жодна зовнішня кнопка не прив\'язана до форми -- тест застарів '
        'або липку панель прибрали'
    )


# --------------------------------------------------------------------------
# CRITICAL-2: чужий акаунт не перезаписується
# --------------------------------------------------------------------------

def test_guest_checkout_does_not_overwrite_existing_owner_profile(
    client, app, open_instance,
):
    """Хтось вказує на чекауті ЧУЖУ адресу і своє ім'я. Реєстрацію ми до
    акаунта прив'язуємо (оплату не блокуємо), але ПІБ і телефон власника
    підмінити не можна -- інакше чекаут стає інструментом псування чужих
    даних."""
    with app.app_context():
        owner = User(email='owner-hardening@example.com', email_confirmed=True)
        owner.last_name = 'Власник'
        owner.first_name = 'Оригінал'
        db.session.add(owner)
        db.session.flush()
        profile = MedicalProfile(user_id=owner.id,
                                 source=MedicalProfile.SOURCE_SELF)
        profile.phone = '+380501112233'
        db.session.add(profile)
        db.session.commit()
        owner_id = owner.id
        instance_id = open_instance

    resp = client.post(
        f'/registration/instance/{instance_id}/register',
        data={
            'last_name': 'Чужий',
            'first_name': 'Зайда',
            'email': 'owner-hardening@example.com',
            'phone': '+380671234567',
            'consent_data': 'y',
        },
        follow_redirects=False,
    )
    assert resp.status_code in (302, 200)

    with app.app_context():
        owner = db.session.get(User, owner_id)
        assert owner.last_name == 'Власник'
        assert owner.first_name == 'Оригінал'
        assert owner.medical_profile.phone == '+380501112233'


def test_guest_checkout_fills_empty_fields_of_existing_account(
    client, app, open_instance,
):
    """Зворотний бік: якщо акаунт порожній (створений імпортом чи попередньою
    гостьовою покупкою без ПІБ), дані з замовлення мають його заповнити --
    інакше правка перетворилась би на "мовчазно ігноруємо ввід"."""
    with app.app_context():
        shell = User(email='shell-hardening@example.com', email_confirmed=False)
        db.session.add(shell)
        db.session.commit()
        shell_id = shell.id
        instance_id = open_instance

    client.post(
        f'/registration/instance/{instance_id}/register',
        data={
            'last_name': 'Заповнено',
            'first_name': 'Зданих',
            'email': 'shell-hardening@example.com',
            'phone': '+380671234500',
            'consent_data': 'y',
        },
        follow_redirects=False,
    )

    with app.app_context():
        shell = db.session.get(User, shell_id)
        assert shell.last_name == 'Заповнено'
        assert shell.first_name == 'Зданих'
        assert shell.medical_profile is not None
        assert shell.medical_profile.phone == '+380671234500'


def test_registration_keeps_buyer_data_even_when_profile_untouched(
    client, app, open_instance,
):
    """Дані покупця не губляться: телефон із замовлення лежить у самій
    реєстрації, навіть коли профіль власника ми не чіпали."""
    with app.app_context():
        owner = User(email='keeps-hardening@example.com', email_confirmed=True)
        owner.last_name = 'Власник'
        owner.first_name = 'Оригінал'
        db.session.add(owner)
        db.session.flush()
        profile = MedicalProfile(user_id=owner.id,
                                 source=MedicalProfile.SOURCE_SELF)
        profile.phone = '+380501112299'
        db.session.add(profile)
        db.session.commit()
        owner_id = owner.id
        instance_id = open_instance

    client.post(
        f'/registration/instance/{instance_id}/register',
        data={
            'last_name': 'Чужий', 'first_name': 'Зайда',
            'email': 'keeps-hardening@example.com',
            'phone': '+380679998877', 'consent_data': 'y',
        },
        follow_redirects=False,
    )

    with app.app_context():
        reg = EventRegistration.query.filter_by(
            user_id=owner_id, instance_id=instance_id).first()
        assert reg is not None
        assert reg.phone == '+380679998877'


# --------------------------------------------------------------------------
# IMPORTANT-4: гонка на створенні користувача
# --------------------------------------------------------------------------

def test_resolve_user_does_not_swallow_race(app):
    """Свідоме рішення: сервіс конфлікт НЕ ловить. Портативно це вимагало б
    SAVEPOINT (pysqlite його не тримає) або rollback (знищив би пакет
    xlsx-імпорту -- контракт модуля забороняє). Ловить caller із власною
    транзакцією. Тест фіксує саме цей контракт, щоб його не "полагодили"
    назад у сервіс."""
    src = (Path(__file__).resolve().parents[2] / 'app' / 'services'
           / 'participant_service.py').read_text(encoding='utf-8')
    assert 'begin_nested' not in src, (
        'SAVEPOINT у participant_service ламає pysqlite -- див. коментар у resolve_user'
    )
    assert 'db.session.rollback()' not in src, (
        'rollback у сервісі знищує пакет xlsx-імпорту'
    )


def test_resolve_user_normal_path_unchanged(app):
    """Звичайний шлях: створення й повторне знаходження за email."""
    with app.app_context():
        user, is_new = participant_service.resolve_user(
            'fresh-hardening@example.com', '+380670000002')
        assert is_new is True
        assert user.id is not None
        db.session.commit()

        again, is_new_again = participant_service.resolve_user(
            'fresh-hardening@example.com', '+380670000002')
        assert is_new_again is False
        assert again.id == user.id


def test_user_email_race_gives_retry_not_error(client, app, open_instance,
                                               monkeypatch):
    """Два гості з тим самим email одночасно: другий INSERT падає на
    users.email. Користувач має отримати пропозицію повторити, а не
    "Помилка при реєстрації"."""
    from sqlalchemy.exc import IntegrityError
    from app.services import participant_service as ps

    with app.app_context():
        instance_id = open_instance

    email = 'user-race-hardening@example.com'
    state = {'raised': False}

    def racing_resolve(e, phone):
        if not state['raised']:
            state['raised'] = True
            # Переможець уже в БД -- саме те, що побачить наш except.
            winner = User(email=(e or '').strip().lower(), email_confirmed=False)
            db.session.add(winner)
            db.session.commit()
            raise IntegrityError('users.email', None, Exception())
        return ps.resolve_user(e, phone)

    monkeypatch.setattr('app.services.participant_service.resolve_user',
                        racing_resolve)

    resp = client.post(
        f'/registration/instance/{instance_id}/register',
        data={
            'last_name': 'Гонка', 'first_name': 'Юзер', 'email': email,
            'phone': '+380670000004', 'consent_data': 'y',
        },
        follow_redirects=True,
    )
    body = resp.get_data(as_text=True)
    assert 'Помилка при реєстрації' not in body


# --------------------------------------------------------------------------
# IMPORTANT-3: гонка на створенні реєстрації
# --------------------------------------------------------------------------

def test_duplicate_registration_constraint_exists(app):
    """Захист від дублю тримає БД, а не тільки find_existing. Якщо
    констрейнт приберуть, гонка почне створювати дублі мовчки."""
    from app.models.registration import EventRegistration as R
    names = {c.name for c in R.__table__.constraints if c.name}
    assert 'uq_user_instance_registration' in names


def test_registration_race_redirects_instead_of_generic_error(
    client, app, open_instance, monkeypatch,
):
    """Гонка на uq_user_instance_registration: реєстрація ІСНУЄ, тож
    "Помилка при реєстрації" тут -- брехня, яка відлякує від оплати."""
    from sqlalchemy.exc import IntegrityError
    from app.services import registration_service

    with app.app_context():
        instance_id = open_instance

    state = {'raised': False}
    real_create = registration_service.create_or_reactivate

    def racing_create(user_id, instance, form_data, existing, **kwargs):
        reg = real_create(user_id, instance, form_data, existing, **kwargs)
        if not state['raised']:
            state['raised'] = True
            # Симулюємо переможця іншої транзакції: реєстрація в БД уже є,
            # наш INSERT падає.
            db.session.flush()
            db.session.commit()
            state['reg_id'] = reg.id
            raise IntegrityError('uq_user_instance_registration', None, Exception())
        return reg

    monkeypatch.setattr(registration_service, 'create_or_reactivate', racing_create)

    resp = client.post(
        f'/registration/instance/{instance_id}/register',
        data={
            'last_name': 'Гонка', 'first_name': 'Тест',
            'email': 'reg-race-hardening@example.com',
            'phone': '+380670000003', 'consent_data': 'y',
        },
        follow_redirects=True,
    )
    body = resp.get_data(as_text=True)
    assert 'Помилка при реєстрації' not in body
