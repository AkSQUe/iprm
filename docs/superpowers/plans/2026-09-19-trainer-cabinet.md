# Кабінет тренера -- план реалізації

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Тренер входить своїм акаунтом і бачить кабінет `/trainer/` з найближчими заходами (числа реєстрацій) та дочірніми сторінками «Анкета», «Договір», «Часті питання»; куратор бачить анкету й пропозиції курсу в адмінці та керує договором і FAQ.

**Architecture:** «Роль тренера» -- прив'язка `Trainer.user_id` до `User`, а не RBAC-роль (RBAC-роль відкриває адмінку). Дані анкети -- дві нові таблиці (`trainer_profiles` 1:1, `trainer_course_proposals` N:1), чутливі реквізити шифруються Fernet. Логіка -- у сервісі `app/services/trainer_cabinet.py`; публічні сторінки -- новий `LocalizedBlueprint` `trainer_cabinet` з префіксом `/trainer`; адмінка -- нові маршрути у `app/admin/routes_trainer_cabinet.py`.

**Tech Stack:** Flask, Flask-Login, Flask-WTF (+ `flask_wtf.file`), SQLAlchemy, Alembic (Flask-Migrate), Flask-Babel, bleach (`sanitize_rich_text`), `cryptography.Fernet`, pytest (SQLite in-memory).

**Spec:** `docs/superpowers/specs/2026-09-19-trainer-cabinet-design.md`

## Global Constraints

- Робота в гілці `main`, без нових гілок і ворктрі. Коміт -- щойно задача зелена; `git add` лише ЯВНО перелічених файлів задачі (`git add -A` / `git add .` заборонені). Повідомлення комітів українською; наприкінці рядок `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`. Пуш -- ніколи.
- Жодних емодзі в коді. Жодних inline-стилів і inline-скриптів у шаблонах сайту (листи `templates/emails/*` -- виняток, там inline-стилі є нормою).
- Дизайн-система: компоненти (кнопки `apple-btn`, поля `form-group`/`form-input`/`form-error`, секції `form-section`, бейджі `badge badge--*`, порожній стан `iprm-empty-state`, картки `account-card`) -- перевикористовуються; `page-*.css` -- лише layout і рівно один шаблон-споживач. Новий компонент -- у компонентний CSS і в каталог `/admin/design-system`.
- Публічний інтерфейс -- `_()` / `_l` (msgid українською). Адмінка -- українська без обгортки (як решта адмінки).
- Id alembic-ревізії <= 32 символів. Поточна голова: `posthog_secondary_20260913`.
- Тести: `python -m pytest tests/<шлях> -q`; наприкінці -- повний прогін `python -m pytest tests/ -q`. Тести, що створюють користувачів, прибирають їх (`tests.support.users.wipe_users`). Перемикати користувача в тесті лише через `tests.support.rbac.switch_user`.
- Email-тригер для листа куратору -- наявний `'course_request'` (CHECK `ck_email_logs_trigger` нових значень не має).

## Уточнення до специфікації (ухвалені під час планування)

1. **PDF договору -- не `MediaFile`.** `/media/...` віддається публічно (nginx alias), а договір має бачити лише тренер. PDF зберігається в БД: `site_settings.trainer_contract_pdf` (`LargeBinary`, `deferred` -- не вантажиться разом із синглтоном на кожному запиті) + `trainer_contract_filename` + `trainer_contract_uploaded_at`. Бонус: потрапляє в бекап БД.
2. **FAQ за замовчуванням -- у коді, не в міграції.** Колонка `trainer_faq_html` порожня; порожнє значення означає «текст за замовчуванням» з `app/data/trainer_faq.py`. Редактор в адмінці префілиться цим текстом. Міграція не дублює довгий HTML.
3. **Анкета в адмінці -- окрема сторінка** `/admin/trainers/<id>/questionnaire` під `trainers.view` (редагування картки вимагає `trainers.manage`, тож маскування на ній не мало б сенсу). Зашифровані поля відкриті лише з `trainers.manage`.
4. **Налаштування «Для тренерів» -- окрема сторінка** `/admin/settings/trainers` під `settings.manage` (загальна форма налаштувань працює через `populate_obj` і не приймає файли).
5. Фото з анкети -- `MediaFile` з `entity_type='trainer_profile'`, `usage_type='photo'` (це фото для сайту, публічна адреса йому не шкодить).

---

## File Structure

| Файл | Відповідальність |
| --- | --- |
| `app/crypto.py` (new) | Один на весь проєкт Fernet-ключ з `SECRET_KEY`; `encrypt_str` / `decrypt_str`; дескриптор `encrypted_field`. |
| `app/models/site_settings.py`, `app/models/email_settings.py` (mod) | Беруть `get_fernet` з `app/crypto.py` замість власних копій; `site_settings` -- нові колонки для тренерів. |
| `app/models/trainer.py` (mod) | `user_id`, зв'язки `user`, `profile`, `proposals`. |
| `app/models/user.py` (mod) | Властивість `active_trainer`. |
| `app/models/trainer_profile.py` (new) | Модель анкети (профіль), шифровані поля, `is_complete`, `mask`. |
| `app/models/trainer_course_proposal.py` (new) | Модель пропозиції курсу, статуси. |
| `app/models/media_file.py` (mod) | `ENTITY_LABELS['trainer_profile']`. |
| `app/models/__init__.py` (mod) | Імпорт нових моделей. |
| `migrations/versions/trainer_cabinet_20260919.py` (new) | DDL. |
| `app/data/trainer_faq.py` (new) | `DEFAULT_TRAINER_FAQ_HTML`. |
| `app/services/trainer_cabinet.py` (new) | Відбір заходів, лічильники, курси, переходи статусів пропозиції, FAQ/email, збереження профілю. |
| `app/trainer_cabinet/__init__.py`, `decorators.py`, `forms.py`, `routes.py` (new) | Публічний блюпринт `/trainer`. |
| `app/templates/trainer_cabinet/*.html` (new) | `index`, `profile`, `proposal_edit`, `proposal_view`, `contract`, `faq`, `_nav.html`. |
| `app/static/css/page-trainer-home.css`, `page-trainer-proposal.css` (new) | Layout двох сторінок. |
| `app/static/js/trainer-theses.js` (new) | Динамічний список тез. |
| `app/templates/partials/header.html` (mod) | Пункт «Кабінет тренера». |
| `app/admin/forms.py` (mod) | `TrainerForm.account_email`, `ProposalReturnForm`, `TrainerSettingsForm`. |
| `app/admin/routes_trainers.py` (mod) | Прив'язка акаунта, індикатори в списку. |
| `app/admin/routes_trainer_cabinet.py` (new) | Анкета в адмінці, дії над пропозиціями, налаштування «Для тренерів». |
| `app/admin/__init__.py` (mod) | Імпорт нового модуля маршрутів. |
| `app/templates/admin/trainer_questionnaire.html`, `admin/settings_trainers.html` (new) | Сторінки адмінки. |
| `app/services/email_service.py` (mod), `app/templates/emails/trainer_proposal_submitted.html` (new) | Лист куратору. |
| `tests/test_trainer_cabinet/*` (new) | Тести. |

---

### Task 1: Спільне шифрування

**Files:**
- Create: `app/crypto.py`
- Modify: `app/models/site_settings.py:1-34` (прибрати власний `_get_fernet`)
- Modify: `app/models/email_settings.py:1-19` (те саме)
- Test: `tests/test_trainer_cabinet/__init__.py`, `tests/test_trainer_cabinet/test_crypto.py`

**Interfaces:**
- Produces: `app.crypto.get_fernet() -> Fernet`, `encrypt_str(value: str) -> str` (порожнє -> `''`), `decrypt_str(token: str, label: str = 'value') -> str` (порожнє або битий токен -> `''`), `encrypted_field(column_attr: str) -> property`.

- [ ] **Step 1: Write the failing test**

`tests/test_trainer_cabinet/__init__.py` -- порожній файл.

`tests/test_trainer_cabinet/test_crypto.py`:

```python
"""Спільний Fernet-хелпер: той самий ключ, що й у SiteSettings/EmailSettings."""
from app.crypto import decrypt_str, encrypt_str, encrypted_field, get_fernet


class _Holder:
    _secret = ''
    secret = encrypted_field('_secret')


def test_roundtrip():
    token = encrypt_str('UA123')
    assert token and token != 'UA123'
    assert decrypt_str(token) == 'UA123'


def test_empty_is_empty():
    assert encrypt_str('') == ''
    assert encrypt_str(None) == ''
    assert decrypt_str('') == ''


def test_broken_token_gives_empty():
    assert decrypt_str('not-a-token') == ''


def test_descriptor_strips_and_encrypts():
    h = _Holder()
    h.secret = '  1234567890  '
    assert h._secret != '1234567890'
    assert h.secret == '1234567890'
    h.secret = ''
    assert h._secret == ''


def test_same_key_as_site_settings():
    from app.models.site_settings import SiteSettings
    s = SiteSettings.get()
    s.partner_api_key = 'k-1'
    assert get_fernet().decrypt(s._partner_api_key_encrypted.encode()).decode() == 'k-1'
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_trainer_cabinet/test_crypto.py -q`
Expected: FAIL -- `ModuleNotFoundError: No module named 'app.crypto'`.

- [ ] **Step 3: Write `app/crypto.py`**

```python
"""Симетричне шифрування секретів у БД (Fernet, ключ з SECRET_KEY).

Одне місце на весь проєкт: доти ключ виводився двома однаковими копіями
(`site_settings._get_fernet`, `email_settings._get_fernet`), і третя копія
для анкети тренера дублювала б їх утретє. Зміна SECRET_KEY робить усі
збережені шифротексти нечитабельними -- decrypt_str тоді повертає '' і пише
warning, а не валить сторінку.
"""
import base64
import hashlib
import logging

from cryptography.fernet import Fernet, InvalidToken
from flask import current_app

logger = logging.getLogger(__name__)


def get_fernet():
    secret = current_app.config['SECRET_KEY']
    key = hashlib.sha256(secret.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(key))


def encrypt_str(value):
    """Шифротекст рядка; порожнє значення -> ''."""
    if not value:
        return ''
    return get_fernet().encrypt(value.encode()).decode()


def decrypt_str(token, label='value'):
    """Відкритий текст; порожній або битий токен -> ''."""
    if not token:
        return ''
    try:
        return get_fernet().decrypt(token.encode()).decode()
    except InvalidToken:
        logger.warning('Failed to decrypt %s', label)
        return ''


def encrypted_field(column_attr):
    """Властивість, що шифрує при записі в `column_attr` і розшифровує при читанні.

    Значення обрізається від пробілів; порожнє зберігається як '' (без
    шифротексту), щоб «не заповнено» відрізнялось без decrypt.
    """
    def fget(self):
        return decrypt_str(getattr(self, column_attr), column_attr)

    def fset(self, value):
        value = (value or '').strip()
        setattr(self, column_attr, encrypt_str(value))

    return property(fget, fset)
```

- [ ] **Step 4: Прибрати копії `_get_fernet`**

У `app/models/site_settings.py` видалити функцію `_get_fernet` (рядки 30-34) і додати імпорт:

```python
from app.crypto import get_fernet as _get_fernet
```

Прибрати імпорти, що стали невикористаними (`base64`, `hashlib`, `Fernet`); `InvalidToken` лишити, якщо він ще вживається в `except` цього файлу (перевірити `grep -n InvalidToken app/models/site_settings.py`).

У `app/models/email_settings.py` так само: видалити `_get_fernet` (рядки 14-18), додати `from app.crypto import get_fernet as _get_fernet`, прибрати невикористані імпорти.

- [ ] **Step 5: Run tests**

Run: `python -m pytest tests/test_trainer_cabinet/test_crypto.py tests/test_routes/test_admin_settings.py -q`
Expected: PASS.

Run: `python -m pyflakes app/crypto.py app/models/site_settings.py app/models/email_settings.py` (або `python -m flake8 --select=F` цих файлів)
Expected: без `imported but unused`.

- [ ] **Step 6: Commit**

```bash
git add app/crypto.py app/models/site_settings.py app/models/email_settings.py tests/test_trainer_cabinet/__init__.py tests/test_trainer_cabinet/test_crypto.py
git commit -m "refactor(crypto): спільний Fernet-хелпер замість двох копій"
```

---

### Task 2: Моделі та міграція

**Files:**
- Create: `app/models/trainer_profile.py`, `app/models/trainer_course_proposal.py`, `migrations/versions/trainer_cabinet_20260919.py`
- Modify: `app/models/trainer.py` (колонка + зв'язки), `app/models/user.py` (властивість `active_trainer` поруч з `is_staff`, ~рядок 270), `app/models/site_settings.py` (колонки), `app/models/media_file.py` (`ENTITY_LABELS`), `app/models/__init__.py`
- Test: `tests/test_trainer_cabinet/_factories.py`, `tests/test_trainer_cabinet/test_models.py`

**Interfaces:**
- Consumes: `app.crypto.encrypted_field`.
- Produces:
  - `Trainer.user_id`, `Trainer.user`, `User.trainer_card` (backref, uselist=False), `Trainer.profile` (`TrainerProfile | None`), `Trainer.proposals` (dynamic query).
  - `User.active_trainer -> Trainer | None` (картка є і `is_active`).
  - `TrainerProfile` поля: `full_name, birth_date, education, position_titles, workplace, phone, email, social_links, photo_media_id, photo_url, fop_recipient, fop_iban*, fop_rnokpp*, fop_payment_purpose, card_number*, tax_id*, registration_address, edrpou` (`*` -- властивості над `_fop_iban`, `_fop_rnokpp`, `_card_number`, `_tax_id`); `is_complete -> bool`; `photo_src -> str | None`; `TrainerProfile.mask(value) -> str`; `SENSITIVE_FIELDS = ('fop_iban', 'fop_rnokpp', 'card_number', 'tax_id')`.
  - `TrainerCourseProposal` поля: `trainer_id, title, theses (list[str]), language, relevance, target_specialties, resources, future_topics, quiz_url, status, curator_comment, submitted_at`; константи `DRAFT, SUBMITTED, ACCEPTED`; `STATUSES`, `STATUS_BADGES`; властивості `is_editable`, `status_label`, `status_badge`.
  - `SiteSettings.trainer_faq_html: str`, `trainer_contract_email: str`, `trainer_contract_pdf: bytes | None` (deferred), `trainer_contract_filename: str`, `trainer_contract_uploaded_at`, властивість `has_trainer_contract -> bool`.
  - Тестові фабрики `make_user`, `make_trainer`, `make_course`, `make_instance`, `make_registration`, `login`.

- [ ] **Step 1: Фабрики для тестів**

`tests/test_trainer_cabinet/_factories.py`:

```python
"""Фабрики тестових даних кабінету тренера.

Усі акаунти -- з префіксом 'tc-', їх прибирає autouse-фікстура в conftest.
"""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from app.extensions import db
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.registration import EventRegistration
from app.models.trainer import Trainer
from app.models.user import User
from tests.support.rbac import switch_user


def make_user(prefix='tc-'):
    user = User.create_with_password(
        f'{prefix}{uuid4().hex[:8]}@test.com', 'password123',
        first_name='Тест', last_name='Тренер', email_confirmed=True,
    )
    db.session.commit()
    return user


def make_trainer(user=None, is_active=True, name='Тренер Т.'):
    trainer = Trainer(
        full_name=name, slug=f'tc-{uuid4().hex[:10]}', is_active=is_active,
        user_id=user.id if user else None,
    )
    db.session.add(trainer)
    db.session.commit()
    return trainer


def make_course(title=None):
    course = Course(title=title or f'Курс {uuid4().hex[:4]}', slug=f'tc-{uuid4().hex[:10]}')
    db.session.add(course)
    db.session.commit()
    return course


def make_instance(course, *, days=7, status='published', event_format='offline',
                  max_participants=20):
    inst = CourseInstance(
        course_id=course.id, status=status, event_format=event_format,
        start_date=datetime.now(timezone.utc) + timedelta(days=days),
        max_participants=max_participants,
    )
    db.session.add(inst)
    db.session.commit()
    return inst


def make_registration(instance, *, status='confirmed', payment_status='unpaid',
                      participation_format=None):
    user = make_user()
    reg = EventRegistration(
        user_id=user.id, instance_id=instance.id, phone='+380671234567',
        specialty='Лікар', workplace='Клініка', status=status,
        payment_status=payment_status, participation_format=participation_format,
    )
    db.session.add(reg)
    db.session.commit()
    return reg


def login(client, user):
    return switch_user(client, user)
```

`tests/test_trainer_cabinet/conftest.py`:

```python
import pytest

from tests.support.users import wipe_users


@pytest.fixture(autouse=True)
def _wipe_tc_users():
    yield
    from app.extensions import db
    from app.models.registration import EventRegistration
    from app.models.user import User
    ids = [u.id for u in User.query.filter(User.email.like('tc-%@test.com')).all()]
    if ids:
        EventRegistration.query.filter(EventRegistration.user_id.in_(ids)).delete(
            synchronize_session=False)
        db.session.commit()
    wipe_users('tc-')
```

- [ ] **Step 2: Write the failing test**

`tests/test_trainer_cabinet/test_models.py`:

```python
import pytest
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models.site_settings import SiteSettings
from app.models.trainer_course_proposal import TrainerCourseProposal
from app.models.trainer_profile import TrainerProfile
from tests.test_trainer_cabinet._factories import make_trainer, make_user


def test_active_trainer_requires_link_and_active():
    user = make_user()
    assert user.active_trainer is None
    trainer = make_trainer(user)
    db.session.expire(user)
    assert user.active_trainer.id == trainer.id
    trainer.is_active = False
    db.session.commit()
    db.session.expire(user)
    assert user.active_trainer is None


def test_user_linked_to_one_trainer_only():
    user = make_user()
    make_trainer(user)
    with pytest.raises(IntegrityError):
        make_trainer(user)
    db.session.rollback()


def test_profile_encrypts_sensitive_fields():
    trainer = make_trainer(make_user())
    profile = TrainerProfile(trainer_id=trainer.id)
    profile.fop_iban = 'UA213052990000026003006239637'
    profile.tax_id = '1234567890'
    db.session.add(profile)
    db.session.commit()
    raw = db.session.execute(db.text(
        'SELECT fop_iban, tax_id FROM trainer_profiles WHERE id = :id'),
        {'id': profile.id}).one()
    assert 'UA2130' not in raw[0]
    assert raw[1] != '1234567890'
    db.session.expire(profile)
    assert profile.fop_iban == 'UA213052990000026003006239637'
    assert trainer.profile.id == profile.id


def test_profile_is_complete():
    profile = TrainerProfile(
        full_name='Іваненко Іван', phone='+380671234567', email='i@test.com',
        registration_address='Київ',
    )
    assert not profile.is_complete
    profile.fop_iban = 'UA1'
    profile.fop_rnokpp = '1'
    profile.tax_id = '1'
    assert profile.is_complete


def test_mask():
    assert TrainerProfile.mask('') == ''
    assert TrainerProfile.mask('1234567890') == '•••• 7890'


def test_proposal_defaults_and_status_check():
    trainer = make_trainer(make_user())
    p = TrainerCourseProposal(trainer_id=trainer.id, title='КОС крові', theses=['A'])
    db.session.add(p)
    db.session.commit()
    assert p.status == TrainerCourseProposal.DRAFT
    assert p.is_editable
    assert trainer.proposals.count() == 1
    p.status = 'bogus'
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()


def test_site_settings_trainer_fields():
    s = SiteSettings.get()
    assert s.trainer_contract_email == ''
    assert not s.has_trainer_contract
    s.trainer_contract_pdf = b'%PDF-1.4 test'
    s.trainer_contract_filename = 'Договір.pdf'
    db.session.commit()
    assert s.has_trainer_contract
```

- [ ] **Step 3: Run test to verify it fails**

Run: `python -m pytest tests/test_trainer_cabinet/test_models.py -q`
Expected: FAIL -- `ModuleNotFoundError: No module named 'app.models.trainer_course_proposal'`.

- [ ] **Step 4: `app/models/trainer_profile.py`**

```python
"""Анкета тренера: персональні дані, реквізити ФОП, дані для договору.

Службові дані для куратора. У публічну картку Trainer НЕ синхронізуються:
її редагує контент-редактор (див. специфікацію кабінету тренера).
IBAN, РНОКПП, номер картки й ідентифікаційний код лежать Fernet-шифротекстом.
"""
from app.crypto import encrypted_field
from app.extensions import db
from app.models.mixins import BigIntPK, TimestampMixin


def _secret_column(name):
    return db.Column(name, db.String(500), nullable=False, default='', server_default='')


class TrainerProfile(TimestampMixin, db.Model):
    __tablename__ = 'trainer_profiles'

    SENSITIVE_FIELDS = ('fop_iban', 'fop_rnokpp', 'card_number', 'tax_id')
    REQUIRED_FOR_COMPLETE = (
        'full_name', 'phone', 'email', 'fop_iban', 'fop_rnokpp', 'tax_id',
        'registration_address',
    )

    id = db.Column(BigIntPK, primary_key=True)
    trainer_id = db.Column(
        db.BigInteger, db.ForeignKey('trainers.id', ondelete='CASCADE'),
        nullable=False, unique=True,
    )

    # Контактна інформація
    full_name = db.Column(db.String(200))
    birth_date = db.Column(db.Date)
    education = db.Column(db.Text)
    position_titles = db.Column(db.Text)
    workplace = db.Column(db.Text)
    phone = db.Column(db.String(30))
    email = db.Column(db.String(255))
    social_links = db.Column(db.Text)

    # Фото: файлом у медіа-реєстр АБО посиланням на файлообмінник.
    photo_media_id = db.Column(
        db.BigInteger, db.ForeignKey('media_files.id', ondelete='SET NULL'),
        nullable=True,
    )
    photo_url = db.Column(db.String(500))

    # Реквізити ФОП (гонорар -- лише на рахунок ФОП)
    fop_recipient = db.Column(db.String(300))
    _fop_iban = _secret_column('fop_iban')
    _fop_rnokpp = _secret_column('fop_rnokpp')
    fop_payment_purpose = db.Column(db.Text)
    _card_number = _secret_column('card_number')

    # Дані для договору
    _tax_id = _secret_column('tax_id')
    registration_address = db.Column(db.Text)
    edrpou = db.Column(db.String(20))

    fop_iban = encrypted_field('_fop_iban')
    fop_rnokpp = encrypted_field('_fop_rnokpp')
    card_number = encrypted_field('_card_number')
    tax_id = encrypted_field('_tax_id')

    trainer = db.relationship('Trainer', back_populates='profile')
    photo_media = db.relationship('MediaFile', foreign_keys=[photo_media_id])

    @property
    def is_complete(self):
        return all((getattr(self, name) or '').strip() for name in self.REQUIRED_FOR_COMPLETE)

    @property
    def photo_src(self):
        if self.photo_media:
            return self.photo_media.variant_url('card')
        return self.photo_url or None

    @staticmethod
    def mask(value):
        """'•••• 7890' для непорожнього значення; '' для порожнього."""
        value = (value or '').strip()
        return f'•••• {value[-4:]}' if value else ''
```

- [ ] **Step 5: `app/models/trainer_course_proposal.py`**

```python
"""Пропозиція курсу/доповіді від тренера (частина «Інформація курсу» анкети).

Переходи статусів -- лише через app.services.trainer_cabinet:
draft -> submitted (тренер), submitted -> accepted | draft (куратор).
Тренер редагує й видаляє тільки чернетку.
"""
from app.extensions import db
from app.models.mixins import BigIntPK, TimestampMixin


class TrainerCourseProposal(TimestampMixin, db.Model):
    __tablename__ = 'trainer_course_proposals'

    DRAFT = 'draft'
    SUBMITTED = 'submitted'
    ACCEPTED = 'accepted'
    STATUSES = [
        (DRAFT, 'Чернетка'),
        (SUBMITTED, 'Надіслано куратору'),
        (ACCEPTED, 'Прийнято'),
    ]
    STATUS_BADGES = {DRAFT: 'draft', SUBMITTED: 'pending', ACCEPTED: 'active'}
    TITLE_MAX = 50
    THESES_MAX = 10

    id = db.Column(BigIntPK, primary_key=True)
    trainer_id = db.Column(
        db.BigInteger, db.ForeignKey('trainers.id', ondelete='CASCADE'),
        nullable=False, index=True,
    )
    title = db.Column(db.String(TITLE_MAX), nullable=False)
    theses = db.Column(db.JSON, nullable=False, default=list)
    language = db.Column(db.String(50))
    relevance = db.Column(db.Text)
    target_specialties = db.Column(db.Text)
    resources = db.Column(db.Text)
    future_topics = db.Column(db.Text)
    quiz_url = db.Column(db.String(500))
    status = db.Column(
        db.String(20), nullable=False, default=DRAFT, server_default=DRAFT, index=True,
    )
    curator_comment = db.Column(db.Text)
    submitted_at = db.Column(db.DateTime(timezone=True))

    __table_args__ = (
        db.CheckConstraint(
            "status IN ('draft', 'submitted', 'accepted')",
            name='ck_trainer_course_proposals_status',
        ),
    )

    trainer = db.relationship('Trainer', back_populates='proposals')

    @property
    def is_editable(self):
        return self.status == self.DRAFT

    @property
    def status_label(self):
        return dict(self.STATUSES).get(self.status, self.status)

    @property
    def status_badge(self):
        return self.STATUS_BADGES.get(self.status, 'draft')
```

- [ ] **Step 6: Зв'язки в `Trainer` і `User`**

У `app/models/trainer.py` після `is_active` додати:

```python
    # Акаунт на сайті, з яким тренер входить у кабінет /trainer. Прив'язує
    # адмін у формі тренера. Unique: один акаунт -- одна картка. Це і є
    # «роль тренера»: RBAC-роль тут не годиться, бо будь-яка роль робить
    # User.is_staff істиною і відкриває адмінку.
    user_id = db.Column(
        db.BigInteger, db.ForeignKey('users.id', ondelete='SET NULL'),
        nullable=True, unique=True,
    )
```

Після `photo_media = ...` додати:

```python
    user = db.relationship(
        'User', foreign_keys=[user_id],
        backref=db.backref('trainer_card', uselist=False),
    )
    profile = db.relationship(
        'TrainerProfile', back_populates='trainer', uselist=False,
        cascade='all, delete-orphan',
    )
    proposals = db.relationship(
        'TrainerCourseProposal', back_populates='trainer', lazy='dynamic',
        cascade='all, delete-orphan',
        order_by='TrainerCourseProposal.created_at.desc()',
    )
```

У `app/models/user.py` після властивості `is_staff`:

```python
    @property
    def active_trainer(self):
        """Прив'язана активна картка тренера або None -- доступ до /trainer."""
        card = self.trainer_card
        return card if card is not None and card.is_active else None
```

- [ ] **Step 7: `SiteSettings`, `MediaFile`, реєстр моделей**

У `app/models/site_settings.py` у класі `SiteSettings` (після блоку способів оплати) додати:

```python
    # Кабінет тренера. Порожній trainer_faq_html означає «текст за
    # замовчуванням» (app/data/trainer_faq.py) -- так міграція не дублює
    # довгий HTML. PDF договору -- у БД, а не в медіа-реєстрі: /media/
    # віддається публічно, а договір бачать лише тренери. deferred -- щоб
    # синглтон, який читається на кожному запиті, не тягнув байти файлу.
    trainer_faq_html = db.Column(db.Text, nullable=False, default='', server_default='')
    trainer_contract_email = db.Column(
        db.String(255), nullable=False, default='', server_default='',
    )
    trainer_contract_pdf = db.deferred(db.Column(db.LargeBinary))
    trainer_contract_filename = db.Column(
        db.String(255), nullable=False, default='', server_default='',
    )
    trainer_contract_uploaded_at = db.Column(db.DateTime(timezone=True))
```

і метод поруч з іншими властивостями:

```python
    @property
    def has_trainer_contract(self):
        """Чи завантажено PDF договору (без читання самих байтів)."""
        return bool(self.trainer_contract_filename)
```

У `app/models/media_file.py` у `ENTITY_LABELS` додати `'trainer_profile': 'Анкета тренера',`.

У `app/models/__init__.py` після `from app.models.trainer import Trainer`:

```python
from app.models.trainer_profile import TrainerProfile
from app.models.trainer_course_proposal import TrainerCourseProposal
```

- [ ] **Step 8: Run model tests**

Run: `python -m pytest tests/test_trainer_cabinet/test_models.py -q`
Expected: PASS (SQLite-схема будується `create_all`).

- [ ] **Step 9: Міграція `migrations/versions/trainer_cabinet_20260919.py`**

```python
"""Кабінет тренера: прив'язка до акаунта, анкета, пропозиції курсу, договір і FAQ.

Revision ID: trainer_cabinet_20260919
Revises: posthog_secondary_20260913

Бекфілу немає: наявні тренери лишаються без акаунта (user_id NULL), поки
адмін не прив'яже їх у формі тренера. trainer_faq_html порожній означає
«текст за замовчуванням з коду».
"""
import sqlalchemy as sa
from alembic import op

revision = 'trainer_cabinet_20260919'
down_revision = 'posthog_secondary_20260913'
branch_labels = None
depends_on = None


def _secret(name):
    return sa.Column(name, sa.String(length=500), nullable=False, server_default='')


def upgrade():
    with op.batch_alter_table('trainers', schema=None) as batch_op:
        batch_op.add_column(sa.Column('user_id', sa.BigInteger(), nullable=True))
        batch_op.create_unique_constraint('uq_trainers_user_id', ['user_id'])
        batch_op.create_foreign_key(
            'fk_trainers_user_id_users', 'users', ['user_id'], ['id'],
            ondelete='SET NULL')

    op.create_table(
        'trainer_profiles',
        sa.Column('id', sa.BigInteger(), primary_key=True),
        sa.Column('trainer_id', sa.BigInteger(),
                  sa.ForeignKey('trainers.id', ondelete='CASCADE'),
                  nullable=False, unique=True),
        sa.Column('full_name', sa.String(length=200)),
        sa.Column('birth_date', sa.Date()),
        sa.Column('education', sa.Text()),
        sa.Column('position_titles', sa.Text()),
        sa.Column('workplace', sa.Text()),
        sa.Column('phone', sa.String(length=30)),
        sa.Column('email', sa.String(length=255)),
        sa.Column('social_links', sa.Text()),
        sa.Column('photo_media_id', sa.BigInteger(),
                  sa.ForeignKey('media_files.id', ondelete='SET NULL')),
        sa.Column('photo_url', sa.String(length=500)),
        sa.Column('fop_recipient', sa.String(length=300)),
        _secret('fop_iban'),
        _secret('fop_rnokpp'),
        sa.Column('fop_payment_purpose', sa.Text()),
        _secret('card_number'),
        _secret('tax_id'),
        sa.Column('registration_address', sa.Text()),
        sa.Column('edrpou', sa.String(length=20)),
        sa.Column('created_at', sa.DateTime(timezone=True)),
        sa.Column('updated_at', sa.DateTime(timezone=True)),
    )

    op.create_table(
        'trainer_course_proposals',
        sa.Column('id', sa.BigInteger(), primary_key=True),
        sa.Column('trainer_id', sa.BigInteger(),
                  sa.ForeignKey('trainers.id', ondelete='CASCADE'), nullable=False),
        sa.Column('title', sa.String(length=50), nullable=False),
        sa.Column('theses', sa.JSON(), nullable=False),
        sa.Column('language', sa.String(length=50)),
        sa.Column('relevance', sa.Text()),
        sa.Column('target_specialties', sa.Text()),
        sa.Column('resources', sa.Text()),
        sa.Column('future_topics', sa.Text()),
        sa.Column('quiz_url', sa.String(length=500)),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='draft'),
        sa.Column('curator_comment', sa.Text()),
        sa.Column('submitted_at', sa.DateTime(timezone=True)),
        sa.Column('created_at', sa.DateTime(timezone=True)),
        sa.Column('updated_at', sa.DateTime(timezone=True)),
        sa.CheckConstraint("status IN ('draft', 'submitted', 'accepted')",
                           name='ck_trainer_course_proposals_status'),
    )
    op.create_index('ix_trainer_course_proposals_trainer_id',
                    'trainer_course_proposals', ['trainer_id'])
    op.create_index('ix_trainer_course_proposals_status',
                    'trainer_course_proposals', ['status'])

    with op.batch_alter_table('site_settings', schema=None) as batch_op:
        batch_op.add_column(sa.Column('trainer_faq_html', sa.Text(),
                                      nullable=False, server_default=''))
        batch_op.add_column(sa.Column('trainer_contract_email', sa.String(length=255),
                                      nullable=False, server_default=''))
        batch_op.add_column(sa.Column('trainer_contract_pdf', sa.LargeBinary()))
        batch_op.add_column(sa.Column('trainer_contract_filename', sa.String(length=255),
                                      nullable=False, server_default=''))
        batch_op.add_column(sa.Column('trainer_contract_uploaded_at',
                                      sa.DateTime(timezone=True)))


def downgrade():
    with op.batch_alter_table('site_settings', schema=None) as batch_op:
        batch_op.drop_column('trainer_contract_uploaded_at')
        batch_op.drop_column('trainer_contract_filename')
        batch_op.drop_column('trainer_contract_pdf')
        batch_op.drop_column('trainer_contract_email')
        batch_op.drop_column('trainer_faq_html')

    op.drop_index('ix_trainer_course_proposals_status',
                  table_name='trainer_course_proposals')
    op.drop_index('ix_trainer_course_proposals_trainer_id',
                  table_name='trainer_course_proposals')
    op.drop_table('trainer_course_proposals')
    op.drop_table('trainer_profiles')

    with op.batch_alter_table('trainers', schema=None) as batch_op:
        batch_op.drop_constraint('fk_trainers_user_id_users', type_='foreignkey')
        batch_op.drop_constraint('uq_trainers_user_id', type_='unique')
        batch_op.drop_column('user_id')
```

- [ ] **Step 10: Прогнати міграцію на dev-БД туди-назад**

Run (по черзі, дивитись ПОВНИЙ вивід, без `grep`):
```bash
flask db upgrade
flask db downgrade posthog_secondary_20260913
flask db upgrade
flask db heads
```
Expected: помилок немає; `flask db heads` -> одна голова `trainer_cabinet_20260919 (head)`.

Run: `python -m pytest tests/test_db/test_migration_revision_ids.py -q`
Expected: PASS.

- [ ] **Step 11: Run model tests + db tests**

Run: `python -m pytest tests/test_trainer_cabinet tests/test_db tests/test_models -q`
Expected: PASS.

- [ ] **Step 12: Commit**

```bash
git add app/models/trainer_profile.py app/models/trainer_course_proposal.py app/models/trainer.py app/models/user.py app/models/site_settings.py app/models/media_file.py app/models/__init__.py migrations/versions/trainer_cabinet_20260919.py tests/test_trainer_cabinet/_factories.py tests/test_trainer_cabinet/conftest.py tests/test_trainer_cabinet/test_models.py
git commit -m "feat(trainer): модель анкети й пропозицій курсу, прив'язка тренера до акаунта"
```

---

### Task 3: Сервіс кабінету

**Files:**
- Create: `app/services/trainer_cabinet.py`, `app/data/trainer_faq.py`
- Test: `tests/test_trainer_cabinet/test_service.py`

**Interfaces:**
- Consumes: моделі Task 2; `course_instance_trainers`, `course_trainers` з `app.models.trainer_links`; `app.services.trainer_links.set_trainers(entity, trainer_ids)`; `app.utils.sanitize_rich_text`.
- Produces:
  - `upcoming_instances(trainer, now=None) -> list[CourseInstance]`
  - `registration_counts(instance_ids) -> dict[int, dict]` з ключами `total, paid, online, offline`
  - `trainer_courses(trainer) -> list[Course]`
  - `class ProposalTransitionError(ValueError)`
  - `submit_proposal(p)`, `accept_proposal(p)`, `return_proposal(p, comment)` -- змінюють об'єкт, НЕ комітять
  - `contract_email(settings) -> str`, `faq_html(settings) -> Markup`, `faq_source(settings) -> str`
  - `get_or_create_profile(trainer) -> TrainerProfile` (flush, без commit)
  - `DEFAULT_TRAINER_FAQ_HTML` у `app/data/trainer_faq.py`

- [ ] **Step 1: Write the failing test**

`tests/test_trainer_cabinet/test_service.py`:

```python
import pytest

from app.extensions import db
from app.models.site_settings import SiteSettings
from app.models.trainer_course_proposal import TrainerCourseProposal
from app.services import trainer_cabinet as svc
from app.services.trainer_links import set_trainers
from tests.test_trainer_cabinet._factories import (
    make_course, make_instance, make_registration, make_trainer, make_user,
)


@pytest.fixture
def trainer():
    return make_trainer(make_user())


def _ids(rows):
    return [r.id for r in rows]


def test_instance_level_assignment(trainer):
    inst = make_instance(make_course())
    set_trainers(inst, [trainer.id])
    db.session.commit()
    assert _ids(svc.upcoming_instances(trainer)) == [inst.id]


def test_course_level_assignment_inherited(trainer):
    course = make_course()
    set_trainers(course, [trainer.id])
    db.session.commit()
    inst = make_instance(course)
    assert _ids(svc.upcoming_instances(trainer)) == [inst.id]


def test_instance_with_own_trainers_overrides_course(trainer):
    other = make_trainer(name='Інший')
    course = make_course()
    set_trainers(course, [trainer.id])
    inst = make_instance(course)
    set_trainers(inst, [other.id])
    db.session.commit()
    assert svc.upcoming_instances(trainer) == []
    assert _ids(svc.upcoming_instances(other)) == [inst.id]


def test_past_and_draft_excluded(trainer):
    course = make_course()
    set_trainers(course, [trainer.id])
    db.session.commit()
    make_instance(course, days=-3)
    make_instance(course, status='draft')
    future = make_instance(course, days=10)
    soon = make_instance(course, days=2)
    assert _ids(svc.upcoming_instances(trainer)) == [soon.id, future.id]


def test_registration_counts():
    inst = make_instance(make_course(), event_format='hybrid')
    make_registration(inst, payment_status='paid', participation_format='online')
    make_registration(inst, participation_format='offline')
    make_registration(inst)  # hybrid без формату -> очно
    make_registration(inst, status='cancelled', payment_status='paid')
    counts = svc.registration_counts([inst.id])
    assert counts[inst.id] == {'total': 3, 'paid': 1, 'online': 1, 'offline': 2}
    assert svc.registration_counts([]) == {}


def test_trainer_courses(trainer):
    course = make_course()
    set_trainers(course, [trainer.id])
    db.session.commit()
    assert _ids(svc.trainer_courses(trainer)) == [course.id]


def test_proposal_transitions(trainer):
    p = TrainerCourseProposal(trainer_id=trainer.id, title='Т', theses=['a'])
    db.session.add(p)
    db.session.commit()
    with pytest.raises(svc.ProposalTransitionError):
        svc.accept_proposal(p)
    svc.submit_proposal(p)
    assert p.status == 'submitted' and p.submitted_at is not None
    with pytest.raises(svc.ProposalTransitionError):
        svc.submit_proposal(p)
    svc.return_proposal(p, 'Уточніть тези')
    assert p.status == 'draft' and p.curator_comment == 'Уточніть тези'
    svc.submit_proposal(p)
    svc.accept_proposal(p)
    assert p.status == 'accepted'


def test_faq_uses_default_and_email_fallback():
    s = SiteSettings.get()
    s.trainer_faq_html = ''
    s.trainer_contract_email = ''
    s.email = 'office@test.com'
    html = str(svc.faq_html(s))
    assert 'Вітаємо із приєднанням' in html
    assert 'office@test.com' in html
    s.trainer_contract_email = 'curator@test.com'
    assert 'curator@test.com' in str(svc.faq_html(s))


def test_faq_is_sanitized():
    s = SiteSettings.get()
    s.trainer_faq_html = '<p>ok {email}</p><script>alert(1)</script>'
    html = str(svc.faq_html(s))
    assert '<script>' not in html
    assert '<p>ok ' in html


def test_get_or_create_profile(trainer):
    p1 = svc.get_or_create_profile(trainer)
    p2 = svc.get_or_create_profile(trainer)
    assert p1 is p2 and p1.trainer_id == trainer.id
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_trainer_cabinet/test_service.py -q`
Expected: FAIL -- `ImportError: cannot import name 'trainer_cabinet'`.

- [ ] **Step 3: `app/data/trainer_faq.py`**

Текст -- дослівно погоджений у специфікації, розмічений дозволеними тегами `sanitize_rich_text` (`p`, `h3`, `ul`, `li`, `strong`). `{email}` підставляє сервіс.

```python
"""Текст «Частих питань» кабінету тренера за замовчуванням.

Показується, поки в адмінці (Налаштування -> Для тренерів) не збережено
власний текст. {email} -- адреса для надсилання договору.
"""

DEFAULT_TRAINER_FAQ_HTML = """\
<p><strong>Вітаємо із приєднанням до когорти викладачів Інституту плазмотерапії та регенеративної медицини!</strong></p>
<p>Дякуємо, що ділитеся своїми унікальними знаннями та досвідом з колегами. Ваш виступ на заході допоможе лікарям удосконалювати свої навички та набути нових професійних компетенцій для покращення здоровʼя та якості життя.</p>
<p>Наша організація працює в правовому полі України для поширення знань та компетенцій. Нам важливо дотримуватись усіх правил інтелектуальної власності та авторського права. Для цього ми просимо Вас підписати документи про передачу права на використання вашої інтелектуальної власності на наших ресурсах.</p>
<h3>Договір</h3>
<p>Для оформлення документів завантажте примірник договору, заповніть Договір, Додаток №1 та Декларацію. В Додатку №1 вкажіть тему першого заходу, який ви будете проводити. У назву файлу договору додайте своє прізвище та надішліть на адресу {email}. Також додайте координати, куди відправити роздруковані та підписані керівництвом ІПРМ примірники договорів (бажано Нова Пошта).</p>
<h3>Анкета та тестування</h3>
<p>Заповніть також анкету викладача та, якщо Ваш захід крім очного передбачає також онлайн-дистанційне (асинхронне) навчання, підготуйте тестування для перевірки знань слухачів. Згідно з Постановою Кабінету Міністрів України № 725 «Про систему безперервного професійного розвитку працівників сфери охорони здоров’я» онлайн-навчання повинно включати систему перевірки знань слухачів у день проведення заходу. Тестування можете підготувати у вигляді Google-форми та додати посилання на неї в анкету.</p>
<h3>Презентація</h3>
<p>За тиждень до анонсованої дати заходу надішліть вашу презентацію куратору для перевірки на відповідність вимогам БПР та допомоги в підготовці тестування знань слухачів. На будь-якому етапі підготовки до заходу звертайтесь до куратора курсу з будь-якими питаннями, з радістю допоможемо!</p>
<h3>Типовий розклад заходу для викладача</h3>
<ul>
<li><strong>9:30</strong> -- прибуття на місце проведення заходу для ознайомлення з приміщенням та підготовленими матеріалами.</li>
<li><strong>10:00-12:00</strong> -- теоретична частина, зазвичай лекція з презентацією, але Ви можете пропонувати свій формат. За домовленістю теоретична частина може одночасно транслюватись онлайн-слухачам. Порада: розбивайте теоретичну частину на блоки та робіть між ними коротенькі перерви.</li>
<li><strong>12:00-12:30</strong> -- кава-пауза.</li>
<li><strong>12:30</strong> -- практична частина. Тривалість практичної частини та можливі перерви визначаєте самі відповідно до запланованих задач та кількості слухачів.</li>
</ul>
<p>Після закінчення практичної частини заплануйте 20-30 хвилин на відповіді на питання слухачів.</p>
<h3>Гонорар</h3>
<p>Переказ гонорару здійснюється на реквізити, вказані Вами в договорі, протягом 5 робочих днів після заходу.</p>
"""
```

Перевірити, що `h3`, `ul`, `li`, `strong`, `p` є в `RICH_TEXT_ALLOWED_TAGS` (`app/utils.py`, ~рядок 165): `python -c "from app.utils import RICH_TEXT_ALLOWED_TAGS as t; print({'p','h3','ul','li','strong'} <= set(t))"` -> `True`. Якщо `h3` немає -- замінити на `h2` (або той заголовок, що є в списку) у тексті вище.

- [ ] **Step 4: `app/services/trainer_cabinet.py`**

```python
"""Кабінет тренера: заходи тренера, лічильники реєстрацій, анкета, FAQ.

Тренер бачить лише ЧИСЛА реєстрацій, без персональних даних учасників.
Переходи статусів пропозиції курсу -- тільки тут; функції змінюють об'єкт
і не комітять (commit і лист робить маршрут).
"""
from datetime import datetime, timezone

from markupsafe import escape
from sqlalchemy import and_, case, exists, func, or_
from sqlalchemy.orm import joinedload

from app.data.trainer_faq import DEFAULT_TRAINER_FAQ_HTML
from app.extensions import db
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.instance_tariff import InstanceTariff
from app.models.registration import EventRegistration
from app.models.trainer_course_proposal import TrainerCourseProposal
from app.models.trainer_links import course_instance_trainers, course_trainers
from app.models.trainer_profile import TrainerProfile
from app.utils import sanitize_rich_text


class ProposalTransitionError(ValueError):
    """Недопустимий перехід статусу пропозиції курсу."""


def upcoming_instances(trainer, now=None):
    """Майбутні published/active дати, де тренер серед effective_trainers.

    Повторює CourseInstance.effective_trainers у SQL: тренер призначений на
    саму дату, АБО на курс -- і тоді лише якщо в дати немає власних тренерів
    (власний список повністю перекриває курсовий).
    """
    now = now or datetime.now(timezone.utc)
    cit = course_instance_trainers
    on_instance = exists().where(
        cit.c.instance_id == CourseInstance.id, cit.c.trainer_id == trainer.id)
    has_own = exists().where(cit.c.instance_id == CourseInstance.id)
    on_course = exists().where(
        course_trainers.c.course_id == CourseInstance.course_id,
        course_trainers.c.trainer_id == trainer.id)
    return (
        CourseInstance.query
        .options(joinedload(CourseInstance.course), joinedload(CourseInstance.city))
        .filter(
            CourseInstance.status.in_(('published', 'active')),
            or_(CourseInstance.start_date.is_(None), CourseInstance.start_date >= now),
            or_(on_instance, and_(~has_own, on_course)),
        )
        .order_by(CourseInstance.start_date.is_(None), CourseInstance.start_date)
        .all()
    )


def registration_counts(instance_ids):
    """{instance_id: {total, paid, online, offline}} одним запитом.

    Скасовані не рахуються. Формат участі -- той самий ланцюжок, що в
    EventRegistration.effective_participation_format: власне поле -> тариф
    -> формат заходу (гібрид без уточнення -> очно).
    """
    if not instance_ids:
        return {}
    reg = EventRegistration
    is_online = case(
        (reg.participation_format == 'online', 1),
        (reg.participation_format == 'offline', 0),
        (InstanceTariff.event_format == 'online', 1),
        (InstanceTariff.event_format == 'offline', 0),
        (CourseInstance.event_format == 'online', 1),
        else_=0,
    )
    rows = (
        db.session.query(
            reg.instance_id,
            func.count(reg.id),
            func.sum(case((reg.payment_status == 'paid', 1), else_=0)),
            func.sum(is_online),
        )
        .join(CourseInstance, CourseInstance.id == reg.instance_id)
        .outerjoin(InstanceTariff, InstanceTariff.id == reg.tariff_id)
        .filter(reg.instance_id.in_(instance_ids), reg.status != 'cancelled')
        .group_by(reg.instance_id)
        .all()
    )
    result = {}
    for instance_id, total, paid, online in rows:
        online = int(online or 0)
        result[instance_id] = {
            'total': int(total), 'paid': int(paid or 0),
            'online': online, 'offline': int(total) - online,
        }
    return result


def trainer_courses(trainer):
    """Активні курси, де тренер призначений на рівні курсу."""
    return (
        Course.query
        .join(course_trainers, course_trainers.c.course_id == Course.id)
        .filter(course_trainers.c.trainer_id == trainer.id, Course.is_active.is_(True))
        .order_by(Course.title)
        .all()
    )


def submit_proposal(proposal):
    if proposal.status != TrainerCourseProposal.DRAFT:
        raise ProposalTransitionError('Надіслати можна лише чернетку')
    proposal.status = TrainerCourseProposal.SUBMITTED
    proposal.submitted_at = datetime.now(timezone.utc)


def accept_proposal(proposal):
    if proposal.status != TrainerCourseProposal.SUBMITTED:
        raise ProposalTransitionError('Прийняти можна лише надіслану пропозицію')
    proposal.status = TrainerCourseProposal.ACCEPTED


def return_proposal(proposal, comment):
    if proposal.status != TrainerCourseProposal.SUBMITTED:
        raise ProposalTransitionError('Повернути можна лише надіслану пропозицію')
    proposal.status = TrainerCourseProposal.DRAFT
    proposal.curator_comment = (comment or '').strip() or None


def contract_email(settings):
    """Куди тренер надсилає договір: окремий email або загальний email сайту."""
    return (settings.trainer_contract_email or '').strip() or (settings.email or '')


def faq_source(settings):
    """Сирий HTML FAQ: збережений в адмінці або текст за замовчуванням."""
    return (settings.trainer_faq_html or '').strip() or DEFAULT_TRAINER_FAQ_HTML


def faq_html(settings):
    """Безпечний HTML FAQ з підставленим email для договорів."""
    html = faq_source(settings).replace('{email}', str(escape(contract_email(settings))))
    return sanitize_rich_text(html)


def get_or_create_profile(trainer):
    if trainer.profile is None:
        trainer.profile = TrainerProfile(trainer_id=trainer.id)
        db.session.flush()
    return trainer.profile
```

Перевірити, що `Course` має `is_active` (`grep -n "is_active" app/models/course.py`); тест `test_trainer_courses` створює курс через `Course(...)` без `is_active` -- якщо дефолт колонки `True`, тест зелений, інакше додати `is_active=True` у `make_course`.

- [ ] **Step 5: Run tests**

Run: `python -m pytest tests/test_trainer_cabinet/test_service.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add app/services/trainer_cabinet.py app/data/trainer_faq.py tests/test_trainer_cabinet/test_service.py
git commit -m "feat(trainer): сервіс кабінету -- заходи тренера, лічильники, статуси пропозицій, FAQ"
```

---

### Task 4: Блюпринт, доступ, головна кабінету, навігація

**Files:**
- Create: `app/trainer_cabinet/__init__.py`, `app/trainer_cabinet/decorators.py`, `app/trainer_cabinet/routes.py`, `app/templates/trainer_cabinet/index.html`, `app/templates/trainer_cabinet/_nav.html`, `app/static/css/page-trainer-home.css`
- Modify: `app/__init__.py` (реєстрація після `trainers_bp`, ~рядок 188), `app/templates/partials/header.html` (два місця: мобільне меню ~рядок 60 і `iprm-header__actions` ~рядок 82)
- Test: `tests/test_trainer_cabinet/test_routes_index.py`

**Interfaces:**
- Consumes: `svc.upcoming_instances`, `svc.registration_counts`, `svc.trainer_courses`, `User.active_trainer`.
- Produces: blueprint `trainer_cabinet` (endpoint-и `trainer_cabinet.index`, далі в Task 5-6: `profile`, `proposal_new`, `proposal_edit`, `proposal_submit`, `proposal_delete`, `contract`, `contract_download`, `faq`); декоратор `trainer_required` (кладе `g.trainer`); partial `trainer_cabinet/_nav.html` з параметром `active`.

- [ ] **Step 1: Write the failing test**

`tests/test_trainer_cabinet/test_routes_index.py`:

```python
from app.extensions import db
from app.services.trainer_links import set_trainers
from tests.support.rbac import make_super_admin
from tests.test_trainer_cabinet._factories import (
    login, make_course, make_instance, make_registration, make_trainer, make_user,
)


def test_anonymous_redirected_to_login(client):
    resp = client.get('/trainer/')
    assert resp.status_code == 302
    assert '/auth/login' in resp.headers['Location']


def test_user_without_card_gets_404(client):
    login(client, make_user())
    assert client.get('/trainer/').status_code == 404


def test_staff_without_card_gets_404(client):
    admin = make_super_admin(email='tc-admin@test.com')
    db.session.commit()
    login(client, admin)
    assert client.get('/trainer/').status_code == 404


def test_inactive_card_gets_404(client):
    user = make_user()
    make_trainer(user, is_active=False)
    login(client, user)
    assert client.get('/trainer/').status_code == 404


def test_dashboard_shows_event_and_counts(client):
    user = make_user()
    trainer = make_trainer(user)
    course = make_course('Кислотно-основний стан')
    set_trainers(course, [trainer.id])
    db.session.commit()
    inst = make_instance(course, max_participants=15)
    make_registration(inst, payment_status='paid')
    make_registration(inst)
    login(client, user)
    resp = client.get('/trainer/')
    html = resp.get_data(as_text=True)
    assert resp.status_code == 200
    assert 'Кислотно-основний стан' in html
    assert 'data-count="total">2<' in html
    assert 'data-count="paid">1<' in html
    assert 'data-count="capacity">15<' in html
    assert '/trainer/profile' in html and '/trainer/contract' in html and '/trainer/faq' in html
    assert resp.headers.get('X-Robots-Tag') == 'noindex, nofollow'


def test_dashboard_empty_state(client):
    user = make_user()
    make_trainer(user)
    login(client, user)
    html = client.get('/trainer/').get_data(as_text=True)
    assert 'iprm-empty-state' in html


def test_faq_page(client):
    user = make_user()
    make_trainer(user)
    login(client, user)
    resp = client.get('/trainer/faq')
    assert resp.status_code == 200
    assert 'Типовий розклад заходу' in resp.get_data(as_text=True)


def test_header_link_only_for_trainer(client):
    user = make_user()
    login(client, user)
    assert '/trainer/' not in client.get('/auth/account').get_data(as_text=True)
    make_trainer(user)
    db.session.expire(user)
    assert '/trainer/' in client.get('/auth/account').get_data(as_text=True)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_trainer_cabinet/test_routes_index.py -q`
Expected: FAIL -- `/trainer/` віддає 404 усім (маршруту немає), перший тест падає на `302`.

- [ ] **Step 3: Блюпринт і декоратор**

`app/trainer_cabinet/__init__.py`:

```python
from app.i18n import LocalizedBlueprint

trainer_cabinet_bp = LocalizedBlueprint('trainer_cabinet', __name__, url_prefix='/trainer')


@trainer_cabinet_bp.after_request
def add_noindex_header(response):
    response.headers['X-Robots-Tag'] = 'noindex, nofollow'
    return response


from app.trainer_cabinet import routes  # noqa: F401,E402
```

`app/trainer_cabinet/decorators.py`:

```python
from functools import wraps

from flask import abort, g
from flask_login import current_user, login_required


def trainer_required(view):
    """Анонім -> вхід; користувач без активної картки тренера -> 404.

    404, а не 403: сторонньому не треба знати, що кабінет існує. Картка
    кладеться в g.trainer.
    """
    @wraps(view)
    def wrapped(*args, **kwargs):
        trainer = current_user.active_trainer
        if trainer is None:
            abort(404)
        g.trainer = trainer
        return view(*args, **kwargs)
    return login_required(wrapped)
```

У `app/__init__.py` після реєстрації `trainers_bp`:

```python
    from app.trainer_cabinet import trainer_cabinet_bp
    app.register_blueprint(trainer_cabinet_bp)
```

- [ ] **Step 4: Маршрут головної**

`app/trainer_cabinet/routes.py`:

```python
import logging

from flask import g, render_template

from app.services import trainer_cabinet as svc
from app.trainer_cabinet import trainer_cabinet_bp
from app.trainer_cabinet.decorators import trainer_required

logger = logging.getLogger(__name__)


@trainer_cabinet_bp.route('/')
@trainer_required
def index():
    trainer = g.trainer
    upcoming = svc.upcoming_instances(trainer)
    return render_template(
        'trainer_cabinet/index.html',
        trainer=trainer,
        upcoming=upcoming,
        counts=svc.registration_counts([i.id for i in upcoming]),
        courses=svc.trainer_courses(trainer),
        profile_complete=bool(trainer.profile and trainer.profile.is_complete),
    )
```

- [ ] **Step 5: Шаблони**

`app/templates/trainer_cabinet/_nav.html` -- три кнопки-посилання (компонент `account-card` з `account.css`):

```html
{# Навігація кабінету тренера. active: 'profile' | 'contract' | 'faq' | None #}
<nav class="account-grid trainer-nav" aria-label="{{ _('Розділи кабінету тренера') }}">
  <a href="{{ url_for('trainer_cabinet.profile') }}" class="account-card account-card--link{% if active == 'profile' %} is-active{% endif %}">
    <h3 class="iprm-block-title">{{ _('Анкета тренера') }}
      {% if not profile_complete %}<span class="badge badge--pending">{{ _('Не заповнено') }}</span>{% endif %}
    </h3>
    <p class="account-card__text">{{ _('Контакти, реквізити ФОП, дані для договору та інформація про ваші курси') }}</p>
  </a>
  <a href="{{ url_for('trainer_cabinet.contract') }}" class="account-card account-card--link{% if active == 'contract' %} is-active{% endif %}">
    <h3 class="iprm-block-title">{{ _('Договір') }}</h3>
    <p class="account-card__text">{{ _('Примірник договору та порядок його оформлення') }}</p>
  </a>
  <a href="{{ url_for('trainer_cabinet.faq') }}" class="account-card account-card--link{% if active == 'faq' %} is-active{% endif %}">
    <h3 class="iprm-block-title">{{ _('Часті питання') }}</h3>
    <p class="account-card__text">{{ _('Підготовка до заходу, розклад дня, гонорар') }}</p>
  </a>
</nav>
```

`app/templates/trainer_cabinet/index.html`:

```html
{% extends "base.html" %}

{% block title %}{{ _('Кабінет тренера | ІПРМ') }}{% endblock %}
{% block extra_meta %}<meta name="robots" content="noindex, nofollow">{% endblock %}

{% block extra_css %}
<link rel="stylesheet" href="{{ url_for('static', filename='css/account.css') }}?v={{ assets_version }}">
<link rel="stylesheet" href="{{ url_for('static', filename='css/page-trainer-home.css') }}?v={{ assets_version }}">
{% endblock %}

{% block content %}
<div class="apple-page">
  <section class="iprm-section">
    <div class="iprm-section__inner">
      <h1 class="iprm-section__title">{{ _('Кабінет тренера') }}</h1>
      <p class="account-card__text">{{ trainer.full_name }}</p>
      {% set active = None %}
      {% include 'trainer_cabinet/_nav.html' %}
    </div>
  </section>

  <section class="iprm-section apple-section-gray">
    <div class="iprm-section__inner">
      <h2 class="iprm-section__title">{{ _('Найближчі заходи') }}</h2>
      {% if upcoming %}
      <ul class="trainer-events">
        {% for inst in upcoming %}
        {% set c = counts.get(inst.id, {'total': 0, 'paid': 0, 'online': 0, 'offline': 0}) %}
        <li class="account-card trainer-events__item">
          <div class="trainer-events__main">
            <p class="account-card__text">
              {% if inst.start_date %}{{ inst.start_date | kyiv_dt('%d.%m.%Y %H:%M') }}{% else %}{{ _('Дата уточнюється') }}{% endif %}
              &middot;
              {% if inst.event_format == 'online' %}{{ _('Онлайн') }}{% else %}{{ inst.city.name if inst.city else (inst.location or '') }}{% endif %}
            </p>
            <h3 class="iprm-block-title">
              <a href="{{ url_for('courses.course_by_slug', slug=inst.course.slug) }}" class="account-course__link">{{ inst.topic or inst.course.title }}</a>
            </h3>
          </div>
          <dl class="trainer-events__counts">
            <div><dt>{{ _('Зареєстровано') }}</dt><dd data-count="total">{{ c.total }}</dd></div>
            <div><dt>{{ _('Оплачено') }}</dt><dd data-count="paid">{{ c.paid }}</dd></div>
            <div><dt>{{ _('Очно') }}</dt><dd data-count="offline">{{ c.offline }}</dd></div>
            <div><dt>{{ _('Онлайн') }}</dt><dd data-count="online">{{ c.online }}</dd></div>
            <div><dt>{{ _('Місць') }}</dt><dd data-count="capacity">{{ inst.effective_max_participants or '—' }}</dd></div>
          </dl>
        </li>
        {% endfor %}
      </ul>
      {% else %}
      <div class="iprm-empty-state">
        <p>{{ _('Найближчих заходів з вашою участю поки немає.') }}</p>
      </div>
      {% endif %}
    </div>
  </section>

  {% if courses %}
  <section class="iprm-section">
    <div class="iprm-section__inner">
      <h2 class="iprm-section__title">{{ _('Мої курси') }}</h2>
      <ul class="trainer-courses">
        {% for course in courses %}
        <li><a href="{{ url_for('courses.course_by_slug', slug=course.slug) }}" class="account-course__link">{{ course.title }}</a></li>
        {% endfor %}
      </ul>
    </div>
  </section>
  {% endif %}
</div>
{% endblock %}
```

Перевірити назви, які шаблон припускає: фільтр `kyiv_dt` зареєстрований у Jinja (`grep -n "kyiv_dt" app/__init__.py`), поле `City.name` (`grep -n "name" app/models/city.py | head -3`), `CourseInstance.location` і `topic` (є за звітом дослідження). Якщо фільтр зветься інакше -- взяти той, що вживається в `auth/account.html` для дат.

`app/static/css/page-trainer-home.css` -- тільки layout:

```css
/* Кабінет тренера (/trainer/): сітка заходів і лічильників. Декор -- з
   account.css і common.css; тут лише розташування. */
.trainer-nav {
  margin-top: var(--space-6, 24px);
}

.trainer-events,
.trainer-courses {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  gap: var(--space-4, 16px);
}

.trainer-events__item {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: var(--space-4, 16px);
  align-items: center;
}

.trainer-events__counts {
  display: grid;
  grid-template-columns: repeat(5, minmax(64px, auto));
  gap: var(--space-3, 12px);
  margin: 0;
  text-align: center;
}

.trainer-events__counts dd {
  margin: 0;
}

@media (max-width: 720px) {
  .trainer-events__item {
    grid-template-columns: 1fr;
  }

  .trainer-events__counts {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
}
```

Перед записом звірити назви токенів відступів з `common.css` (`grep -n "\-\-space-" app/static/css/common.css | head`) і використати справжні імена токенів замість fallback-значень. Якщо для підпису/числа лічильника потрібен декор (розмір шрифту `dd`, колір `dt`) -- перевірити, чи є готовий компонент (`apple-stat` у каталозі `/admin/design-system`); якщо так -- використати його класи в розмітці замість `dl`, якщо ні -- додати компонент у `account.css` і показати в каталозі.

- [ ] **Step 6: Пункт у шапці**

У `app/templates/partials/header.html` у мобільному меню одразу після посилання «Особистий кабінет»:

```html
          {% if current_user.active_trainer %}
          <a href="{{ url_for('trainer_cabinet.index') }}" class="iprm-nav__mobile-link">{{ _('Кабінет тренера') }}</a>
          {% endif %}
```

У `iprm-header__actions` одразу після `<a ... class="iprm-header__user-link">`:

```html
        {% if current_user.active_trainer %}
          <a href="{{ url_for('trainer_cabinet.index') }}" class="iprm-header__admin-link">{{ _('Кабінет тренера') }}</a>
        {% endif %}
```

- [ ] **Step 7: Endpoint-и дочірніх сторінок**

`_nav.html` будує `url_for` на `profile`, `contract`, `faq`, тож вони мають існувати вже зараз. Додати в `routes.py` три робочі маршрути; FAQ тут повний, а `profile` і `contract` Task 5 і 6 розширять:

```python
@trainer_cabinet_bp.route('/profile', methods=['GET', 'POST'])
@trainer_required
def profile():
    return render_template('trainer_cabinet/profile.html', trainer=g.trainer)


@trainer_cabinet_bp.route('/contract')
@trainer_required
def contract():
    return render_template('trainer_cabinet/contract.html', trainer=g.trainer)


@trainer_cabinet_bp.route('/faq')
@trainer_required
def faq():
    from app.models.site_settings import SiteSettings
    return render_template(
        'trainer_cabinet/faq.html', trainer=g.trainer,
        faq_html=svc.faq_html(SiteSettings.get()),
    )
```

і три шаблони з однаковим каркасом (кожен -- повний файл):

`app/templates/trainer_cabinet/faq.html`:

```html
{% extends "base.html" %}

{% block title %}{{ _('Часті питання | Кабінет тренера | ІПРМ') }}{% endblock %}
{% block extra_meta %}<meta name="robots" content="noindex, nofollow">{% endblock %}

{% block extra_css %}
<link rel="stylesheet" href="{{ url_for('static', filename='css/account.css') }}?v={{ assets_version }}">
<link rel="stylesheet" href="{{ url_for('static', filename='css/legal.css') }}?v={{ assets_version }}">
{% endblock %}

{% block content %}
<div class="apple-page">
  <section class="iprm-section">
    <div class="iprm-section__inner">
      <p><a href="{{ url_for('trainer_cabinet.index') }}" class="account-course__link">{{ _('Кабінет тренера') }}</a></p>
      <h1 class="iprm-section__title">{{ _('Часті питання') }}</h1>
      <div class="legal-content">{{ faq_html }}</div>
    </div>
  </section>
</div>
{% endblock %}
```

(Клас прозового блоку взяти з `legal.css` -- `grep -n "^\.legal" app/static/css/legal.css | head`; якщо контейнер прози там зветься інакше, вжити його назву.)

`app/templates/trainer_cabinet/contract.html` і `profile.html` на цьому кроці -- той самий каркас (без `legal.css` і без `faq_html`) із заголовками `{{ _('Договір') }}` / `{{ _('Анкета тренера') }}` і посиланням назад; тіло наповнюють Task 5 (profile) і Task 6 (contract).

- [ ] **Step 8: Run tests**

Run: `python -m pytest tests/test_trainer_cabinet -q`
Expected: PASS.

- [ ] **Step 9: Дизайн-система**

Run:
```bash
python 1-instruments/design-system/layer_check.py
python 1-instruments/design-system/shadowed_rules.py
python -m pytest tests/test_design_system -q
```
Expected: нових порушень немає (`page-trainer-home.css` має рівно одного споживача; `account.css` і `legal.css` -- компонентні). Якщо `layer_check` скаржиться на `account.css`/`legal.css` (змінилась кількість споживачів) -- виконати його рекомендацію (перейменування/переміщення) в межах цієї задачі.

- [ ] **Step 10: Commit**

```bash
git add app/trainer_cabinet/__init__.py app/trainer_cabinet/decorators.py app/trainer_cabinet/routes.py app/__init__.py app/templates/partials/header.html app/templates/trainer_cabinet/index.html app/templates/trainer_cabinet/_nav.html app/templates/trainer_cabinet/profile.html app/templates/trainer_cabinet/contract.html app/templates/trainer_cabinet/faq.html app/static/css/page-trainer-home.css tests/test_trainer_cabinet/test_routes_index.py
git commit -m "feat(trainer): кабінет тренера -- найближчі заходи, лічильники реєстрацій, FAQ"
```

---

### Task 5: Анкета -- профіль і пропозиції курсу

**Files:**
- Create: `app/trainer_cabinet/forms.py`, `app/templates/trainer_cabinet/proposal_edit.html`, `app/templates/trainer_cabinet/proposal_view.html`, `app/static/css/page-trainer-proposal.css`, `app/static/js/trainer-theses.js`
- Modify: `app/trainer_cabinet/routes.py` (розширити `profile`, додати маршрути пропозицій), `app/templates/trainer_cabinet/profile.html` (форма + список пропозицій)
- Test: `tests/test_trainer_cabinet/test_routes_profile.py`, `tests/test_trainer_cabinet/test_routes_proposals.py`

**Interfaces:**
- Consumes: `svc.get_or_create_profile`, `svc.submit_proposal`, `svc.ProposalTransitionError`, `media_service.create_from_upload(file, *, entity_type, entity_id, usage_type, uploader_id) -> (MediaFile|None, error|None)`.
- Produces: `TrainerProfileForm`, `ProposalForm` (поле `theses` -- textarea, одна теза на рядок); endpoint-и `proposal_new`, `proposal_edit(proposal_id)`, `proposal_submit(proposal_id)`, `proposal_delete(proposal_id)`; хук `_after_submit(proposal)` у `routes.py` (Task 8 додає туди лист).

- [ ] **Step 1: Write the failing tests**

`tests/test_trainer_cabinet/test_routes_profile.py`:

```python
from app.extensions import db
from app.models.trainer_profile import TrainerProfile
from tests.test_trainer_cabinet._factories import login, make_trainer, make_user


def _data(**over):
    data = {
        'full_name': 'Іваненко Іван Іванович', 'birth_date': '1985-03-02',
        'education': 'НМУ ім. Богомольця', 'position_titles': 'Лікар-лаборант, к.мед.н.',
        'workplace': 'Клініка, Київ', 'phone': '+380671234567', 'email': 'ivan@test.com',
        'social_links': 'https://facebook.com/ivan', 'photo_url': '',
        'fop_recipient': 'ФОП Іваненко І.І.', 'fop_iban': 'UA213052990000026003006239637',
        'fop_rnokpp': '1234567890', 'fop_payment_purpose': 'Послуги за КВЕД 85.59',
        'card_number': '4149 6090 1234 5678', 'tax_id': '1234567890',
        'registration_address': 'м. Київ, вул. Хрещатик, 1', 'edrpou': '',
    }
    data.update(over)
    return data


def test_profile_save_and_prefill(client):
    user = make_user()
    trainer = make_trainer(user)
    login(client, user)
    resp = client.post('/trainer/profile', data=_data(), follow_redirects=True)
    assert resp.status_code == 200
    profile = TrainerProfile.query.filter_by(trainer_id=trainer.id).one()
    assert profile.fop_iban == 'UA213052990000026003006239637'
    assert profile.is_complete
    html = client.get('/trainer/profile').get_data(as_text=True)
    assert 'UA213052990000026003006239637' in html
    assert 'Іваненко Іван Іванович' in html


def test_profile_invalid_email_rerenders(client):
    user = make_user()
    make_trainer(user)
    login(client, user)
    resp = client.post('/trainer/profile', data=_data(email='not-an-email'))
    assert resp.status_code == 200
    assert 'form-error' in resp.get_data(as_text=True)
    assert TrainerProfile.query.count() == 0 or not TrainerProfile.query.first().email


def test_clearing_secret_keeps_nothing(client):
    user = make_user()
    trainer = make_trainer(user)
    login(client, user)
    client.post('/trainer/profile', data=_data())
    client.post('/trainer/profile', data=_data(card_number=''))
    db.session.expire_all()
    assert TrainerProfile.query.filter_by(trainer_id=trainer.id).one().card_number == ''
```

`tests/test_trainer_cabinet/test_routes_proposals.py`:

```python
from app.extensions import db
from app.models.trainer_course_proposal import TrainerCourseProposal
from tests.test_trainer_cabinet._factories import login, make_trainer, make_user

DATA = {
    'title': 'КОС крові: діагностика',
    'theses': 'Методи визначення КОС\nФізіологічні межі рН\nБуферні системи',
    'language': 'Українська',
    'relevance': 'Лікарю важливо це знати, тому що...',
    'target_specialties': 'Анестезіологи, хірурги',
    'resources': '', 'future_topics': '', 'quiz_url': '',
}


def _setup(client):
    user = make_user()
    trainer = make_trainer(user)
    login(client, user)
    return trainer


def test_create_draft(client):
    trainer = _setup(client)
    resp = client.post('/trainer/proposals/new', data=DATA)
    assert resp.status_code == 302
    p = TrainerCourseProposal.query.filter_by(trainer_id=trainer.id).one()
    assert p.status == 'draft'
    assert p.theses == ['Методи визначення КОС', 'Фізіологічні межі рН', 'Буферні системи']


def test_title_limit_and_theses_limit(client):
    _setup(client)
    resp = client.post('/trainer/proposals/new', data={**DATA, 'title': 'x' * 51})
    assert resp.status_code == 200 and 'form-error' in resp.get_data(as_text=True)
    resp = client.post('/trainer/proposals/new',
                       data={**DATA, 'theses': '\n'.join(str(i) for i in range(11))})
    assert resp.status_code == 200 and 'form-error' in resp.get_data(as_text=True)
    resp = client.post('/trainer/proposals/new', data={**DATA, 'theses': '  \n '})
    assert resp.status_code == 200 and 'form-error' in resp.get_data(as_text=True)


def test_submit_locks_editing(client):
    trainer = _setup(client)
    client.post('/trainer/proposals/new', data=DATA)
    p = TrainerCourseProposal.query.filter_by(trainer_id=trainer.id).one()
    assert client.post(f'/trainer/proposals/{p.id}/submit').status_code == 302
    db.session.expire_all()
    assert p.status == 'submitted'
    resp = client.post(f'/trainer/proposals/{p.id}', data={**DATA, 'title': 'Інше'})
    assert resp.status_code == 409
    assert client.post(f'/trainer/proposals/{p.id}/delete').status_code == 409
    view = client.get(f'/trainer/proposals/{p.id}').get_data(as_text=True)
    assert 'КОС крові: діагностика' in view and 'name="title"' not in view


def test_delete_draft(client):
    trainer = _setup(client)
    client.post('/trainer/proposals/new', data=DATA)
    p = TrainerCourseProposal.query.filter_by(trainer_id=trainer.id).one()
    assert client.post(f'/trainer/proposals/{p.id}/delete').status_code == 302
    assert TrainerCourseProposal.query.filter_by(trainer_id=trainer.id).count() == 0


def test_foreign_proposal_is_404(client):
    owner = make_trainer(make_user(), name='Власник')
    p = TrainerCourseProposal(trainer_id=owner.id, title='Чуже', theses=['a'])
    db.session.add(p)
    db.session.commit()
    _setup(client)
    assert client.get(f'/trainer/proposals/{p.id}').status_code == 404
    assert client.post(f'/trainer/proposals/{p.id}/submit').status_code == 404
    assert client.post(f'/trainer/proposals/{p.id}/delete').status_code == 404


def test_profile_page_lists_proposals(client):
    _setup(client)
    client.post('/trainer/proposals/new', data=DATA)
    html = client.get('/trainer/profile').get_data(as_text=True)
    assert 'КОС крові: діагностика' in html
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_trainer_cabinet/test_routes_profile.py tests/test_trainer_cabinet/test_routes_proposals.py -q`
Expected: FAIL (профіль нічого не зберігає; маршрутів пропозицій немає -> 404/405).

- [ ] **Step 3: `app/trainer_cabinet/forms.py`**

```python
from flask_babel import lazy_gettext as _l
from flask_wtf import FlaskForm
from flask_wtf.file import FileAllowed, FileField
from wtforms import DateField, StringField, TextAreaField
from wtforms.validators import DataRequired, Email, Length, Optional, URL, ValidationError

from app.models.trainer_course_proposal import TrainerCourseProposal


class TrainerProfileForm(FlaskForm):
    # Контактна інформація
    full_name = StringField(_l('ПІБ'), validators=[Optional(), Length(max=200)])
    birth_date = DateField(_l('Дата народження'), validators=[Optional()])
    education = TextAreaField(_l('Освіта (рівень освіти та навчальні заклади)'), validators=[Optional()])
    position_titles = TextAreaField(_l('Посада та регалії'), validators=[Optional()])
    workplace = TextAreaField(_l('Місце роботи, місто'), validators=[Optional()])
    phone = StringField(_l('Телефон'), validators=[Optional(), Length(max=30)])
    email = StringField(_l('Ел. пошта'), validators=[
        Optional(), Email(message=_l('Невалідний email')), Length(max=255)])
    social_links = TextAreaField(_l('Посилання на соцмережі'), validators=[Optional()])
    photo = FileField(_l('Фотографія для сайту'), validators=[
        Optional(), FileAllowed(['jpg', 'jpeg', 'png', 'webp', 'heic'],
                                _l('Дозволені формати: JPG, PNG, WebP, HEIC'))])
    photo_url = StringField(_l('Або посилання на фото (файлообмінник)'), validators=[
        Optional(), URL(message=_l('Невалідне посилання')), Length(max=500)])

    # Реквізити ФОП
    fop_recipient = StringField(_l('Отримувач'), validators=[Optional(), Length(max=300)])
    fop_iban = StringField('IBAN', validators=[Optional(), Length(max=34)])
    fop_rnokpp = StringField(_l('РНОКПП'), validators=[Optional(), Length(max=12)])
    fop_payment_purpose = TextAreaField(_l('Призначення платежу згідно ваших КВЕД'), validators=[Optional()])
    card_number = StringField(_l('Номер картки'), validators=[Optional(), Length(max=23)])

    # Дані для договору
    tax_id = StringField(_l('Ідентифікаційний код'), validators=[Optional(), Length(max=12)])
    registration_address = TextAreaField(_l('Адреса реєстрації (проживання)'), validators=[Optional()])
    edrpou = StringField(_l('ЄДРПОУ'), validators=[Optional(), Length(max=20)])

    # Поля, що копіюються в модель як є (фото обробляє маршрут окремо).
    MODEL_FIELDS = (
        'full_name', 'birth_date', 'education', 'position_titles', 'workplace',
        'phone', 'email', 'social_links', 'photo_url', 'fop_recipient', 'fop_iban',
        'fop_rnokpp', 'fop_payment_purpose', 'card_number', 'tax_id',
        'registration_address', 'edrpou',
    )


class ProposalForm(FlaskForm):
    title = StringField(_l('Назва курсу/доповіді'), validators=[
        DataRequired(message=_l("Назва обов'язкова")),
        Length(max=TrainerCourseProposal.TITLE_MAX,
               message=_l('Не більше 50 символів'))])
    theses = TextAreaField(_l('Програма виступу (5-10 головних тез)'))
    language = StringField(_l('Мова доповіді'), validators=[Optional(), Length(max=50)])
    relevance = TextAreaField(_l('Актуальність вебінару/лекції/курсу'), validators=[Optional()])
    target_specialties = TextAreaField(_l('Яким спеціальностям буде корисним'), validators=[Optional()])
    resources = TextAreaField(_l('Цікаві статті/ресурси по вашій темі'), validators=[Optional()])
    future_topics = TextAreaField(_l('Які теми в майбутньому ви могли б запропонувати'), validators=[Optional()])
    quiz_url = StringField(_l('Посилання на тестування (Google-форма)'), validators=[
        Optional(), URL(message=_l('Невалідне посилання')), Length(max=500)])

    def theses_list(self):
        return [line.strip() for line in (self.theses.data or '').splitlines() if line.strip()]

    def validate_theses(self, field):
        items = self.theses_list()
        if not items:
            raise ValidationError(_l('Додайте хоча б одну тезу'))
        if len(items) > TrainerCourseProposal.THESES_MAX:
            raise ValidationError(_l('Не більше 10 тез'))
```

- [ ] **Step 4: Маршрути профілю й пропозицій**

У `app/trainer_cabinet/routes.py` замінити мінімальний `profile` і додати:

```python
from flask import abort, flash, g, redirect, render_template, request, url_for
from flask_babel import gettext as _
from flask_login import current_user

from app.extensions import db
from app.models.trainer_course_proposal import TrainerCourseProposal
from app.trainer_cabinet.forms import ProposalForm, TrainerProfileForm

PROPOSAL_FIELDS = (
    'title', 'language', 'relevance', 'target_specialties', 'resources',
    'future_topics', 'quiz_url',
)


def _save_photo(form, profile):
    """Завантажене фото -> MediaFile анкети. Повертає текст помилки або None."""
    file = form.photo.data
    if not file or not getattr(file, 'filename', ''):
        return None
    from app.services import media_service
    media, error = media_service.create_from_upload(
        file, entity_type='trainer_profile', entity_id=profile.id,
        usage_type='photo', uploader_id=current_user.id,
    )
    if error:
        return error
    profile.photo_media_id = media.id
    return None


@trainer_cabinet_bp.route('/profile', methods=['GET', 'POST'])
@trainer_required
def profile():
    trainer = g.trainer
    record = trainer.profile
    form = TrainerProfileForm()
    if request.method == 'GET' and record is not None:
        for name in TrainerProfileForm.MODEL_FIELDS:
            getattr(form, name).data = getattr(record, name)

    if form.validate_on_submit():
        record = svc.get_or_create_profile(trainer)
        for name in TrainerProfileForm.MODEL_FIELDS:
            value = getattr(form, name).data
            setattr(record, name, value.strip() if isinstance(value, str) else value)
        photo_error = _save_photo(form, record)
        if photo_error:
            db.session.rollback()
            form.photo.errors.append(photo_error)
        else:
            try:
                db.session.commit()
                flash(_('Анкету збережено'), 'success')
                return redirect(url_for('trainer_cabinet.profile'))
            except Exception:
                logger.exception('Failed to save trainer profile %s', trainer.id)
                db.session.rollback()
                flash(_('Помилка при збереженні'), 'error')

    return render_template(
        'trainer_cabinet/profile.html', trainer=trainer, form=form,
        record=trainer.profile, proposals=trainer.proposals.all(),
    )


def _own_proposal(proposal_id):
    proposal = TrainerCourseProposal.query.filter_by(
        id=proposal_id, trainer_id=g.trainer.id).first()
    if proposal is None:
        abort(404)
    return proposal


def _apply_proposal(form, proposal):
    for name in PROPOSAL_FIELDS:
        value = getattr(form, name).data
        setattr(proposal, name, (value or '').strip() or None)
    proposal.title = form.title.data.strip()
    proposal.theses = form.theses_list()


@trainer_cabinet_bp.route('/proposals/new', methods=['GET', 'POST'])
@trainer_required
def proposal_new():
    form = ProposalForm()
    if form.validate_on_submit():
        proposal = TrainerCourseProposal(trainer_id=g.trainer.id)
        _apply_proposal(form, proposal)
        db.session.add(proposal)
        db.session.commit()
        flash(_('Чернетку збережено'), 'success')
        return redirect(url_for('trainer_cabinet.proposal_edit', proposal_id=proposal.id))
    return render_template('trainer_cabinet/proposal_edit.html', form=form, proposal=None)


@trainer_cabinet_bp.route('/proposals/<int:proposal_id>', methods=['GET', 'POST'])
@trainer_required
def proposal_edit(proposal_id):
    proposal = _own_proposal(proposal_id)
    if not proposal.is_editable:
        if request.method == 'POST':
            abort(409)
        return render_template('trainer_cabinet/proposal_view.html', proposal=proposal)
    form = ProposalForm(obj=proposal) if request.method == 'GET' else ProposalForm()
    if request.method == 'GET':
        form.theses.data = '\n'.join(proposal.theses or [])
    if form.validate_on_submit():
        _apply_proposal(form, proposal)
        db.session.commit()
        flash(_('Чернетку збережено'), 'success')
        return redirect(url_for('trainer_cabinet.proposal_edit', proposal_id=proposal.id))
    return render_template('trainer_cabinet/proposal_edit.html', form=form, proposal=proposal)


def _after_submit(proposal):
    """Побічні дії після надсилання пропозиції (лист куратору -- Task 8)."""


@trainer_cabinet_bp.route('/proposals/<int:proposal_id>/submit', methods=['POST'])
@trainer_required
def proposal_submit(proposal_id):
    proposal = _own_proposal(proposal_id)
    try:
        svc.submit_proposal(proposal)
    except svc.ProposalTransitionError:
        abort(409)
    db.session.commit()
    _after_submit(proposal)
    flash(_('Пропозицію надіслано куратору'), 'success')
    return redirect(url_for('trainer_cabinet.profile'))


@trainer_cabinet_bp.route('/proposals/<int:proposal_id>/delete', methods=['POST'])
@trainer_required
def proposal_delete(proposal_id):
    proposal = _own_proposal(proposal_id)
    if not proposal.is_editable:
        abort(409)
    db.session.delete(proposal)
    db.session.commit()
    flash(_('Чернетку видалено'), 'success')
    return redirect(url_for('trainer_cabinet.profile'))
```

Примітка: `_after_submit` -- порожнє тіло з docstring є валідною функцією, а не заглушкою: у Task 8 в нього додається виклик листа.

- [ ] **Step 5: Шаблон профілю**

`app/templates/trainer_cabinet/profile.html` (повністю замінити каркас Task 4). Зразок розмітки полів -- `auth/certificate_data.html`: `form-section`, `form-section__title`, `form-section__grid`, `form-group`, `form-input`, `form-error`. Макрос для поля оголосити на початку файлу:

```html
{% extends "base.html" %}

{% macro field(f, wide=False) %}
<div class="form-group{% if wide %} form-group--wide{% endif %}">
  <label for="{{ f.id }}">{{ f.label.text }}</label>
  {{ f(class="form-input" + (" is-invalid" if f.errors else ""), id=f.id) }}
  {% for error in f.errors %}<div class="form-error">{{ error }}</div>{% endfor %}
</div>
{% endmacro %}

{% block title %}{{ _('Анкета тренера | ІПРМ') }}{% endblock %}
{% block extra_meta %}<meta name="robots" content="noindex, nofollow">{% endblock %}

{% block extra_css %}
<link rel="stylesheet" href="{{ url_for('static', filename='css/auth.css') }}?v={{ assets_version }}">
<link rel="stylesheet" href="{{ url_for('static', filename='css/registration.css') }}?v={{ assets_version }}">
<link rel="stylesheet" href="{{ url_for('static', filename='css/account.css') }}?v={{ assets_version }}">
{% endblock %}

{% block content %}
<div class="apple-page reg-layout">
  <p><a href="{{ url_for('trainer_cabinet.index') }}" class="account-course__link">{{ _('Кабінет тренера') }}</a></p>
  <h1 class="reg-confirmation__title">{{ _('Анкета тренера') }}</h1>

  <form method="POST" action="{{ url_for('trainer_cabinet.profile') }}" enctype="multipart/form-data" data-validate data-single-submit>
    {{ form.hidden_tag() }}

    <div class="form-section reg-form-section">
      <h3 class="form-section__title reg-form-section__title">{{ _('Контактна інформація') }}</h3>
      <div class="form-section__grid">
        {{ field(form.full_name) }}
        {{ field(form.birth_date) }}
        {{ field(form.phone) }}
        {{ field(form.email) }}
        {{ field(form.education, wide=True) }}
        {{ field(form.position_titles, wide=True) }}
        {{ field(form.workplace, wide=True) }}
        {{ field(form.social_links, wide=True) }}
      </div>
    </div>

    <div class="form-section reg-form-section">
      <h3 class="form-section__title reg-form-section__title">{{ _('Фотографія для сайту') }}</h3>
      {% if record and record.photo_src %}
      <p class="account-card__text"><a href="{{ record.photo_src }}" class="account-course__link" target="_blank" rel="noopener">{{ _('Поточне фото') }}</a></p>
      {% endif %}
      <div class="form-section__grid">
        {{ field(form.photo) }}
        {{ field(form.photo_url) }}
      </div>
    </div>

    <div class="form-section reg-form-section">
      <h3 class="form-section__title reg-form-section__title">{{ _('Реквізити ФОП') }}</h3>
      <p class="account-card__text">{{ _("У зв'язку з обмеженнями банківської системи гонорар перераховується лише на рахунок ФОП.") }}</p>
      <div class="form-section__grid">
        {{ field(form.fop_recipient) }}
        {{ field(form.fop_iban) }}
        {{ field(form.fop_rnokpp) }}
        {{ field(form.card_number) }}
        {{ field(form.fop_payment_purpose, wide=True) }}
      </div>
    </div>

    <div class="form-section reg-form-section">
      <h3 class="form-section__title reg-form-section__title">{{ _('Дані для підписання договору') }}</h3>
      <div class="form-section__grid">
        {{ field(form.tax_id) }}
        {{ field(form.edrpou) }}
        {{ field(form.registration_address, wide=True) }}
      </div>
    </div>

    <button type="submit" class="apple-btn apple-btn--primary">{{ _('Зберегти анкету') }}</button>
  </form>

  <section class="form-section reg-form-section">
    <h3 class="form-section__title reg-form-section__title">{{ _('Інформація курсу') }}</h3>
    {% if proposals %}
    <ul class="account-grid">
      {% for p in proposals %}
      <li class="account-card">
        <a href="{{ url_for('trainer_cabinet.proposal_edit', proposal_id=p.id) }}" class="account-course__link">{{ p.title }}</a>
        <span class="badge badge--{{ p.status_badge }}">{% if p.status == 'draft' %}{{ _('Чернетка') }}{% elif p.status == 'submitted' %}{{ _('Надіслано куратору') }}{% else %}{{ _('Прийнято') }}{% endif %}</span>
      </li>
      {% endfor %}
    </ul>
    {% else %}
    <div class="iprm-empty-state"><p>{{ _('Ви ще не додали жодного курсу чи доповіді.') }}</p></div>
    {% endif %}
    <a href="{{ url_for('trainer_cabinet.proposal_new') }}" class="apple-btn apple-btn--secondary">{{ _('Додати курс / доповідь') }}</a>
  </section>
</div>
{% endblock %}
```

Перевірити, що модифікатор `form-group--wide` існує (`grep -rn "form-group--wide" app/static/css | head -2`); якщо ні -- не вигадувати, а прибрати параметр `wide` з макросу (поля займуть одну клітинку сітки).

- [ ] **Step 6: Шаблони пропозиції, JS тез, layout**

`app/templates/trainer_cabinet/proposal_edit.html`:

```html
{% extends "base.html" %}

{% macro field(f, hint=None) %}
<div class="form-group">
  <label for="{{ f.id }}">{{ f.label.text }}</label>
  {% if hint %}<p class="form-hint">{{ hint }}</p>{% endif %}
  {{ f(class="form-input" + (" is-invalid" if f.errors else ""), id=f.id, **kwargs) }}
  {% for error in f.errors %}<div class="form-error">{{ error }}</div>{% endfor %}
</div>
{% endmacro %}

{% block title %}{{ _('Інформація курсу | Кабінет тренера | ІПРМ') }}{% endblock %}
{% block extra_meta %}<meta name="robots" content="noindex, nofollow">{% endblock %}

{% block extra_css %}
<link rel="stylesheet" href="{{ url_for('static', filename='css/auth.css') }}?v={{ assets_version }}">
<link rel="stylesheet" href="{{ url_for('static', filename='css/registration.css') }}?v={{ assets_version }}">
<link rel="stylesheet" href="{{ url_for('static', filename='css/account.css') }}?v={{ assets_version }}">
<link rel="stylesheet" href="{{ url_for('static', filename='css/page-trainer-proposal.css') }}?v={{ assets_version }}">
{% endblock %}

{% block content %}
<div class="apple-page reg-layout">
  <p><a href="{{ url_for('trainer_cabinet.profile') }}" class="account-course__link">{{ _('Анкета тренера') }}</a></p>
  <h1 class="reg-confirmation__title">{{ _('Інформація курсу') }}</h1>

  {% if proposal and proposal.curator_comment %}
  <aside class="reg-moh-notice" role="note">
    <div class="reg-moh-notice__icon" aria-hidden="true">i</div>
    <p><strong>{{ _('Коментар куратора:') }}</strong> {{ proposal.curator_comment }}</p>
  </aside>
  {% endif %}

  <form method="POST" data-validate data-single-submit
        action="{{ url_for('trainer_cabinet.proposal_edit', proposal_id=proposal.id) if proposal else url_for('trainer_cabinet.proposal_new') }}">
    {{ form.hidden_tag() }}
    <div class="form-section reg-form-section">
      {{ field(form.title, _('Лаконічно та чітко сформульована; до 50 символів'), maxlength=50) }}
      {{ field(form.theses, _('Одна теза на рядок, 5-10 головних тез доповіді'), rows=8, **{'data-theses': ''}) }}
      {{ field(form.language) }}
      {{ field(form.relevance, _('Лікарю важливо це знати, тому що...; до чого може призвести незнання цієї інформації; у яких випадках/станах знадобляться ці знання; з якими хворобами, симптомами, ситуаціями лікар знатиме, як діяти'), rows=8) }}
      {{ field(form.target_specialties) }}
      {{ field(form.resources) }}
      {{ field(form.future_topics) }}
      {{ field(form.quiz_url, _("Обов'язково для онлайн-навчання: перевірка знань слухачів у день заходу (Постанова КМУ № 725)")) }}
    </div>
    <div class="trainer-proposal__actions">
      <button type="submit" class="apple-btn apple-btn--secondary">{{ _('Зберегти чернетку') }}</button>
    </div>
  </form>

  {% if proposal %}
  <div class="trainer-proposal__actions">
    <form method="POST" action="{{ url_for('trainer_cabinet.proposal_submit', proposal_id=proposal.id) }}" data-single-submit>
      <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
      <button type="submit" class="apple-btn apple-btn--primary">{{ _('Надіслати куратору') }}</button>
    </form>
    <form method="POST" action="{{ url_for('trainer_cabinet.proposal_delete', proposal_id=proposal.id) }}" data-single-submit>
      <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
      <button type="submit" class="apple-btn apple-btn--secondary">{{ _('Видалити чернетку') }}</button>
    </form>
  </div>
  {% endif %}
</div>
<script src="{{ url_for('static', filename='js/trainer-theses.js') }}?v={{ assets_version }}" defer></script>
{% endblock %}
```

Перевірити клас підказки під полем (`grep -rn "\.form-hint" app/static/css | head -2`); якщо в дизайн-системі він зветься інакше (напр. `form-help`), вжити справжню назву. Перевірити, як інші шаблони підключають JS (блок `extra_js` у `base.html` -- `grep -n "block extra_js\|block scripts" app/templates/base.html`) і перенести `<script>` у той блок.

`app/templates/trainer_cabinet/proposal_view.html`:

```html
{% extends "base.html" %}

{% block title %}{{ proposal.title }} | {{ _('Кабінет тренера | ІПРМ') }}{% endblock %}
{% block extra_meta %}<meta name="robots" content="noindex, nofollow">{% endblock %}

{% block extra_css %}
<link rel="stylesheet" href="{{ url_for('static', filename='css/account.css') }}?v={{ assets_version }}">
{% endblock %}

{% block content %}
<div class="apple-page">
  <section class="iprm-section">
    <div class="iprm-section__inner">
      <p><a href="{{ url_for('trainer_cabinet.profile') }}" class="account-course__link">{{ _('Анкета тренера') }}</a></p>
      <h1 class="iprm-section__title">{{ proposal.title }}</h1>
      <p><span class="badge badge--{{ proposal.status_badge }}">{% if proposal.status == 'submitted' %}{{ _('Надіслано куратору') }}{% else %}{{ _('Прийнято') }}{% endif %}</span></p>
      <p class="account-card__text">{{ _('Пропозиція на розгляді куратора. Щоб внести зміни, зверніться до куратора курсу.') }}</p>

      <h3 class="iprm-block-title">{{ _('Програма виступу') }}</h3>
      <ol>{% for t in proposal.theses %}<li>{{ t }}</li>{% endfor %}</ol>
      {% for label, value in [
          (_('Мова доповіді'), proposal.language),
          (_('Актуальність'), proposal.relevance),
          (_('Яким спеціальностям буде корисним'), proposal.target_specialties),
          (_('Цікаві статті/ресурси'), proposal.resources),
          (_('Теми на майбутнє'), proposal.future_topics),
          (_('Тестування'), proposal.quiz_url),
      ] if value %}
      <h3 class="iprm-block-title">{{ label }}</h3>
      <p class="account-card__text">{{ value }}</p>
      {% endfor %}
    </div>
  </section>
</div>
{% endblock %}
```

`app/static/js/trainer-theses.js`:

```javascript
/* Динамічний список тез пропозиції курсу (кабінет тренера).
   Прогресивне покращення: без JS працює textarea "одна теза на рядок".
   З JS textarea ховається, замість неї -- по полю на тезу з кнопками
   "+ теза" / видалити; перед сабмітом значення збираються назад у textarea. */
(function () {
  'use strict';

  var MAX = 10;

  function init(textarea) {
    var list = document.createElement('ol');
    list.className = 'trainer-theses';
    var add = document.createElement('button');
    add.type = 'button';
    add.className = 'apple-btn apple-btn--secondary apple-btn--sm';
    add.textContent = textarea.getAttribute('data-add-label') || '+';

    function sync() {
      var values = [];
      list.querySelectorAll('input').forEach(function (input) {
        if (input.value.trim()) { values.push(input.value.trim()); }
      });
      textarea.value = values.join('\n');
      add.disabled = list.children.length >= MAX;
    }

    function row(value) {
      var li = document.createElement('li');
      li.className = 'trainer-theses__row';
      var input = document.createElement('input');
      input.type = 'text';
      input.className = 'form-input';
      input.value = value || '';
      input.addEventListener('input', sync);
      var remove = document.createElement('button');
      remove.type = 'button';
      remove.className = 'apple-btn apple-btn--secondary apple-btn--sm';
      remove.textContent = textarea.getAttribute('data-remove-label') || '-';
      remove.addEventListener('click', function () {
        li.remove();
        if (!list.children.length) { list.appendChild(row('')); }
        sync();
      });
      li.appendChild(input);
      li.appendChild(remove);
      return li;
    }

    var initial = textarea.value.split('\n').filter(function (v) { return v.trim(); });
    (initial.length ? initial : ['']).forEach(function (v) { list.appendChild(row(v)); });

    add.addEventListener('click', function () {
      if (list.children.length < MAX) {
        var li = row('');
        list.appendChild(li);
        li.querySelector('input').focus();
        sync();
      }
    });

    textarea.hidden = true;
    textarea.insertAdjacentElement('afterend', add);
    textarea.insertAdjacentElement('afterend', list);
    if (textarea.form) { textarea.form.addEventListener('submit', sync); }
    sync();
  }

  document.querySelectorAll('textarea[data-theses]').forEach(init);
})();
```

У шаблоні підписи кнопок передаються атрибутами (i18n): у виклику `field(form.theses, ...)` додати до `**{'data-theses': ''}` ще `'data-add-label': _('+ теза'), 'data-remove-label': _('Видалити')`.

`app/static/css/page-trainer-proposal.css`:

```css
/* Пропозиція курсу (кабінет тренера): розкладка списку тез і кнопок дій. */
.trainer-theses {
  display: grid;
  gap: var(--space-2, 8px);
  margin: 0 0 var(--space-3, 12px);
  padding-left: var(--space-5, 20px);
}

.trainer-theses__row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: var(--space-2, 8px);
  align-items: center;
}

.trainer-proposal__actions {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-3, 12px);
  margin-top: var(--space-4, 16px);
}
```

(Як у Task 4 -- замінити fallback-и справжніми токенами з `common.css`.)

- [ ] **Step 7: Run tests**

Run: `python -m pytest tests/test_trainer_cabinet -q`
Expected: PASS.

- [ ] **Step 8: Дизайн-система і візуальна перевірка**

Run: `python 1-instruments/design-system/layer_check.py && python 1-instruments/design-system/shadowed_rules.py && python -m pytest tests/test_design_system -q`
Expected: без нових порушень.

Візуально (див. пам'ять `reference_visual_check`: playwright у venv, системний Chrome): відкрити `/trainer/profile` і `/trainer/proposals/new` під акаунтом тренера на ширині 1280 і 390 px, переконатися, що список тез додається/видаляється, а збережені тези повертаються рядками.

- [ ] **Step 9: Commit**

```bash
git add app/trainer_cabinet/forms.py app/trainer_cabinet/routes.py app/templates/trainer_cabinet/profile.html app/templates/trainer_cabinet/proposal_edit.html app/templates/trainer_cabinet/proposal_view.html app/static/css/page-trainer-proposal.css app/static/js/trainer-theses.js tests/test_trainer_cabinet/test_routes_profile.py tests/test_trainer_cabinet/test_routes_proposals.py
git commit -m "feat(trainer): анкета тренера -- профіль і пропозиції курсу"
```

---

### Task 6: Сторінка договору

**Files:**
- Modify: `app/trainer_cabinet/routes.py` (`contract` + `contract_download`), `app/templates/trainer_cabinet/contract.html`
- Test: `tests/test_trainer_cabinet/test_routes_contract.py`

**Interfaces:**
- Consumes: `SiteSettings.has_trainer_contract`, `trainer_contract_pdf`, `trainer_contract_filename`, `svc.contract_email`.
- Produces: endpoint `trainer_cabinet.contract_download`.

- [ ] **Step 1: Write the failing test**

`tests/test_trainer_cabinet/test_routes_contract.py`:

```python
from app.extensions import db
from app.models.site_settings import SiteSettings
from tests.test_trainer_cabinet._factories import login, make_trainer, make_user


def _trainer_login(client):
    user = make_user()
    make_trainer(user)
    login(client, user)


def _set_pdf(data, name='Договір ІПРМ.pdf'):
    s = SiteSettings.get()
    s.trainer_contract_pdf = data
    s.trainer_contract_filename = name if data else ''
    db.session.commit()


def test_contract_without_file(client):
    _set_pdf(None)
    _trainer_login(client)
    html = client.get('/trainer/contract').get_data(as_text=True)
    assert 'буде додано найближчим часом' in html
    assert client.get('/trainer/contract/download').status_code == 404


def test_contract_download(client):
    _set_pdf(b'%PDF-1.4 contract')
    _trainer_login(client)
    html = client.get('/trainer/contract').get_data(as_text=True)
    assert '/trainer/contract/download' in html
    resp = client.get('/trainer/contract/download')
    assert resp.status_code == 200
    assert resp.mimetype == 'application/pdf'
    assert resp.data == b'%PDF-1.4 contract'
    assert 'attachment' in resp.headers['Content-Disposition']


def test_download_requires_trainer(client):
    _set_pdf(b'%PDF-1.4 contract')
    login(client, make_user())
    assert client.get('/trainer/contract/download').status_code == 404


def test_contract_shows_email(client):
    s = SiteSettings.get()
    s.trainer_contract_email = 'curator@test.com'
    db.session.commit()
    _trainer_login(client)
    assert 'curator@test.com' in client.get('/trainer/contract').get_data(as_text=True)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_trainer_cabinet/test_routes_contract.py -q`
Expected: FAIL (текст відсутній; `/trainer/contract/download` -> 404 навіть з файлом).

- [ ] **Step 3: Маршрути**

У `app/trainer_cabinet/routes.py` замінити `contract` і додати `contract_download` (імпорти `io`, `send_file`, `SiteSettings` -- на початку файлу):

```python
@trainer_cabinet_bp.route('/contract')
@trainer_required
def contract():
    settings = SiteSettings.get()
    return render_template(
        'trainer_cabinet/contract.html', trainer=g.trainer,
        has_contract=settings.has_trainer_contract,
        contract_email=svc.contract_email(settings),
    )


@trainer_cabinet_bp.route('/contract/download')
@trainer_required
def contract_download():
    settings = SiteSettings.get()
    data = settings.trainer_contract_pdf if settings.has_trainer_contract else None
    if not data:
        abort(404)
    return send_file(
        io.BytesIO(data), mimetype='application/pdf', as_attachment=True,
        download_name=settings.trainer_contract_filename or 'contract.pdf',
    )
```

- [ ] **Step 4: Шаблон**

`app/templates/trainer_cabinet/contract.html`:

```html
{% extends "base.html" %}

{% block title %}{{ _('Договір | Кабінет тренера | ІПРМ') }}{% endblock %}
{% block extra_meta %}<meta name="robots" content="noindex, nofollow">{% endblock %}

{% block extra_css %}
<link rel="stylesheet" href="{{ url_for('static', filename='css/account.css') }}?v={{ assets_version }}">
{% endblock %}

{% block content %}
<div class="apple-page">
  <section class="iprm-section">
    <div class="iprm-section__inner">
      <p><a href="{{ url_for('trainer_cabinet.index') }}" class="account-course__link">{{ _('Кабінет тренера') }}</a></p>
      <h1 class="iprm-section__title">{{ _('Договір') }}</h1>
      <ol class="account-card__text">
        <li>{{ _('Завантажте примірник договору.') }}</li>
        <li>{{ _('Заповніть Договір, Додаток №1 та Декларацію. У Додатку №1 вкажіть тему першого заходу, який ви будете проводити.') }}</li>
        <li>{% trans email=contract_email %}Додайте своє прізвище в назву файлу та надішліть договір на {{ email }}.{% endtrans %}</li>
        <li>{{ _('Вкажіть у листі, куди надіслати підписані керівництвом ІПРМ примірники (бажано Нова Пошта).') }}</li>
      </ol>
      {% if has_contract %}
      <a href="{{ url_for('trainer_cabinet.contract_download') }}" class="apple-btn apple-btn--primary">{{ _('Завантажити договір (PDF)') }}</a>
      {% else %}
      <div class="iprm-empty-state"><p>{{ _('Договір буде додано найближчим часом.') }}</p></div>
      {% endif %}
    </div>
  </section>
</div>
{% endblock %}
```

Тест шукає `'буде додано найближчим часом'` -- рядок саме такий.

- [ ] **Step 5: Run tests**

Run: `python -m pytest tests/test_trainer_cabinet -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add app/trainer_cabinet/routes.py app/templates/trainer_cabinet/contract.html tests/test_trainer_cabinet/test_routes_contract.py
git commit -m "feat(trainer): сторінка договору із завантаженням PDF лише для тренерів"
```

---

### Task 7: Адмінка -- прив'язка акаунта, анкета, пропозиції, індикатори

**Files:**
- Create: `app/admin/routes_trainer_cabinet.py`, `app/templates/admin/trainer_questionnaire.html`
- Modify: `app/admin/forms.py` (`TrainerForm.account_email`, новий `ProposalReturnForm`), `app/admin/routes_trainers.py` (`trainer_create`, `trainer_edit`, `trainers_list`), `app/admin/__init__.py` (імпорт модуля маршрутів поряд з іншими `routes_*`), `app/templates/admin/trainer_edit.html` (поле акаунта + посилання на анкету), `app/templates/admin/trainers.html` (індикатори)
- Test: `tests/test_trainer_cabinet/test_admin.py`

**Interfaces:**
- Consumes: `svc.accept_proposal`, `svc.return_proposal`, `svc.ProposalTransitionError`, `TrainerProfile.mask`, `TrainerProfile.SENSITIVE_FIELDS`, `app.rbac.access.has_permission(user, name)`.
- Produces: endpoint-и `admin.trainer_questionnaire(trainer_id)`, `admin.trainer_proposal_accept(proposal_id)`, `admin.trainer_proposal_return(proposal_id)`; хелпер `_apply_account_link(trainer, email) -> str | None` у `routes_trainers.py`.

- [ ] **Step 1: Write the failing test**

`tests/test_trainer_cabinet/test_admin.py`:

```python
from app.extensions import db
from app.models.trainer import Trainer
from app.models.trainer_course_proposal import TrainerCourseProposal
from app.models.trainer_profile import TrainerProfile
from tests.support.rbac import make_super_admin, make_user_with_role
from tests.test_trainer_cabinet._factories import login, make_trainer, make_user


def _admin(client):
    admin = make_super_admin(email='tc-admin@test.com')
    db.session.commit()
    login(client, admin)
    return admin


def _form(trainer, **over):
    data = {'full_name': trainer.full_name, 'slug': trainer.slug, 'is_active': 'y',
            'account_email': ''}
    data.update(over)
    return data


def test_link_account_by_email(client):
    _admin(client)
    trainer = make_trainer()
    user = make_user()
    client.post(f'/admin/trainers/{trainer.id}/edit', data=_form(trainer, account_email=user.email))
    db.session.expire_all()
    assert db.session.get(Trainer, trainer.id).user_id == user.id


def test_link_unknown_email_rejected(client):
    _admin(client)
    trainer = make_trainer()
    resp = client.post(f'/admin/trainers/{trainer.id}/edit',
                       data=_form(trainer, account_email='tc-nobody@test.com'))
    assert 'не знайдено' in resp.get_data(as_text=True)
    db.session.expire_all()
    assert db.session.get(Trainer, trainer.id).user_id is None


def test_link_taken_account_rejected(client):
    _admin(client)
    user = make_user()
    make_trainer(user, name='Перший')
    second = make_trainer(name='Другий')
    resp = client.post(f'/admin/trainers/{second.id}/edit',
                       data=_form(second, account_email=user.email))
    assert 'вже прив' in resp.get_data(as_text=True)


def test_unlink_with_empty_email(client):
    _admin(client)
    trainer = make_trainer(make_user())
    client.post(f'/admin/trainers/{trainer.id}/edit', data=_form(trainer))
    db.session.expire_all()
    assert db.session.get(Trainer, trainer.id).user_id is None


def _profile(trainer):
    p = TrainerProfile(trainer_id=trainer.id, full_name='Іваненко')
    p.fop_iban = 'UA213052990000026003006239637'
    db.session.add(p)
    db.session.commit()
    return p


def test_questionnaire_reveals_for_manage(client):
    _admin(client)
    trainer = make_trainer(make_user())
    _profile(trainer)
    html = client.get(f'/admin/trainers/{trainer.id}/questionnaire').get_data(as_text=True)
    assert 'UA213052990000026003006239637' in html


def test_questionnaire_masks_for_view_only(client):
    viewer = make_user_with_role('viewer', email='tc-viewer@test.com')
    db.session.commit()
    login(client, viewer)
    trainer = make_trainer(make_user())
    _profile(trainer)
    resp = client.get(f'/admin/trainers/{trainer.id}/questionnaire')
    html = resp.get_data(as_text=True)
    assert resp.status_code == 200
    assert 'UA213052990000026003006239637' not in html
    assert '•••• 9637' in html


def _submitted(trainer):
    p = TrainerCourseProposal(trainer_id=trainer.id, title='КОС', theses=['a'],
                              status='submitted')
    db.session.add(p)
    db.session.commit()
    return p


def test_accept_and_return(client):
    _admin(client)
    trainer = make_trainer(make_user())
    p = _submitted(trainer)
    client.post(f'/admin/trainers/proposals/{p.id}/return', data={'comment': 'Уточніть'})
    db.session.expire_all()
    assert p.status == 'draft' and p.curator_comment == 'Уточніть'
    p.status = 'submitted'
    db.session.commit()
    client.post(f'/admin/trainers/proposals/{p.id}/accept')
    db.session.expire_all()
    assert p.status == 'accepted'
    resp = client.post(f'/admin/trainers/proposals/{p.id}/accept', follow_redirects=True)
    assert 'Неможливо' in resp.get_data(as_text=True)


def test_list_indicators(client):
    _admin(client)
    trainer = make_trainer(make_user(), name='Індикаторний')
    _submitted(trainer)
    html = client.get('/admin/trainers').get_data(as_text=True)
    assert 'data-trainer-linked="' + str(trainer.id) + '"' in html
    assert 'data-trainer-new-proposals="' + str(trainer.id) + '">1<' in html
```

(Перевірити, що системна роль `viewer` має `trainers.view` і не має `trainers.manage`: `grep -n "viewer" -A 6 app/rbac/registry.py`. Якщо ні -- у тесті створити роль через `Role`/`Permission` як у `tests/test_rbac`.)

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_trainer_cabinet/test_admin.py -q`
Expected: FAIL.

- [ ] **Step 3: Форми**

У `app/admin/forms.py` у `TrainerForm` після `email`:

```python
    account_email = StringField(
        'Акаунт на сайті (email)',
        validators=[Optional(), Email(message='Невалідний email'), Length(max=255)],
        description='Email зареєстрованого користувача. Після прив\'язки тренер '
                    'бачить «Кабінет тренера». Порожнє поле -- відв\'язати.',
    )
```

Новий клас наприкінці файлу:

```python
class ProposalReturnForm(FlaskForm):
    comment = TextAreaField('Коментар для тренера', validators=[Optional(), Length(max=2000)])
```

- [ ] **Step 4: Прив'язка в `routes_trainers.py`**

Додати імпорт `from app.models.user import User` і хелпер:

```python
def _apply_account_link(trainer, email):
    """Прив'язати/відв'язати акаунт. Повертає текст помилки або None."""
    email = (email or '').strip().lower()
    if not email:
        trainer.user_id = None
        return None
    user = User.query.filter(db.func.lower(User.email) == email).first()
    if user is None:
        return 'Користувача з таким email не знайдено'
    taken = Trainer.query.filter(Trainer.user_id == user.id, Trainer.id != trainer.id).first()
    if taken is not None:
        return f'Цей акаунт вже прив\'язано до тренера «{taken.full_name}»'
    trainer.user_id = user.id
    return None
```

У `trainer_create` і `trainer_edit` перед `db.session.add/commit` (після `_apply_profile_fields`):

```python
        link_error = _apply_account_link(trainer, form.account_email.data)
        if link_error:
            form.account_email.errors.append(link_error)
            db.session.rollback()
            return render_template('admin/trainer_edit.html', form=form, trainer=...)
```

(у `trainer_create` -- `trainer=None`; у `trainer_edit` -- той самий набір аргументів, що вже передається при помилці slug: `trainer=trainer, referral_link=referral_link, referral_balance=referral_balance, referral_dashboard_url=referral_dashboard_url`. Для `trainer_create` виклик робити ДО `db.session.add(trainer)`, щоб rollback не був потрібен -- тоді `db.session.rollback()` прибрати.)

У `trainer_edit` у гілці `if request.method == 'GET':` додати `form.account_email.data = trainer.user.email if trainer.user else ''`.

У `trainers_list` порахувати індикатори агрегатами:

```python
    trainers = query.order_by(Trainer.full_name).all()
    ids = [t.id for t in trainers]
    new_proposals = dict(
        db.session.query(TrainerCourseProposal.trainer_id, db.func.count(TrainerCourseProposal.id))
        .filter(TrainerCourseProposal.trainer_id.in_(ids),
                TrainerCourseProposal.status == TrainerCourseProposal.SUBMITTED)
        .group_by(TrainerCourseProposal.trainer_id).all()
    ) if ids else {}
    complete = {
        p.trainer_id for p in TrainerProfile.query.filter(TrainerProfile.trainer_id.in_(ids)).all()
        if p.is_complete
    } if ids else set()
```

і передати `trainers=trainers, new_proposals=new_proposals, complete_profiles=complete` у `render_template` (імпорти моделей -- на початку файлу).

- [ ] **Step 5: `app/admin/routes_trainer_cabinet.py`**

```python
"""Адмінка кабінету тренера: анкета, пропозиції курсу, налаштування «Для тренерів»."""
import logging

from flask import abort, flash, redirect, render_template, url_for
from flask_login import current_user

from app.admin import admin_bp
from app.admin.forms import ProposalReturnForm
from app.extensions import db
from app.models.trainer import Trainer
from app.models.trainer_course_proposal import TrainerCourseProposal
from app.models.trainer_profile import TrainerProfile
from app.rbac import permission_required
from app.rbac.access import has_permission
from app.services import trainer_cabinet as svc

audit_logger = logging.getLogger('audit')


@admin_bp.route('/trainers/<int:trainer_id>/questionnaire')
@permission_required('trainers.view')
def trainer_questionnaire(trainer_id):
    trainer = db.session.get(Trainer, trainer_id) or abort(404)
    profile = trainer.profile
    reveal = has_permission(current_user, 'trainers.manage')
    secrets = {}
    if profile is not None:
        for name in TrainerProfile.SENSITIVE_FIELDS:
            value = getattr(profile, name)
            secrets[name] = value if reveal else TrainerProfile.mask(value)
    return render_template(
        'admin/trainer_questionnaire.html', trainer=trainer, profile=profile,
        secrets=secrets, can_manage=reveal, proposals=trainer.proposals.all(),
        return_form=ProposalReturnForm(),
    )


def _proposal_or_404(proposal_id):
    return db.session.get(TrainerCourseProposal, proposal_id) or abort(404)


@admin_bp.route('/trainers/proposals/<int:proposal_id>/accept', methods=['POST'])
@permission_required('trainers.manage')
def trainer_proposal_accept(proposal_id):
    proposal = _proposal_or_404(proposal_id)
    try:
        svc.accept_proposal(proposal)
        db.session.commit()
        audit_logger.info('Admin %s accepted trainer proposal %s', current_user.email, proposal.id)
        flash('Пропозицію прийнято', 'success')
    except svc.ProposalTransitionError:
        flash('Неможливо прийняти: пропозиція не на розгляді', 'error')
    return redirect(url_for('admin.trainer_questionnaire', trainer_id=proposal.trainer_id))


@admin_bp.route('/trainers/proposals/<int:proposal_id>/return', methods=['POST'])
@permission_required('trainers.manage')
def trainer_proposal_return(proposal_id):
    proposal = _proposal_or_404(proposal_id)
    form = ProposalReturnForm()
    if not form.validate_on_submit():
        flash('Коментар задовгий', 'error')
    else:
        try:
            svc.return_proposal(proposal, form.comment.data)
            db.session.commit()
            audit_logger.info('Admin %s returned trainer proposal %s', current_user.email, proposal.id)
            flash('Пропозицію повернуто на доопрацювання', 'success')
        except svc.ProposalTransitionError:
            flash('Неможливо повернути: пропозиція не на розгляді', 'error')
    return redirect(url_for('admin.trainer_questionnaire', trainer_id=proposal.trainer_id))
```

У `app/admin/__init__.py` додати `routes_trainer_cabinet` до переліку імпортованих модулів маршрутів (той самий стиль, що для `routes_trainers`).

- [ ] **Step 6: Шаблони адмінки**

`app/templates/admin/trainer_questionnaire.html` -- наслідує той самий базовий шаблон і структуру заголовка, що `admin/trainer_edit.html` (відкрити його й скопіювати `extends`, блоки заголовка/хлібних крихт). Тіло:

```html
{% set p = profile %}
<section class="admin-card">
  <h2>Анкета: {{ trainer.full_name }}</h2>
  {% if not p %}
    <div class="iprm-empty-state"><p>Тренер ще не заповнював анкету.</p></div>
  {% else %}
  <dl class="admin-dl">
    {% for label, value in [
        ('ПІБ', p.full_name), ('Дата народження', p.birth_date.strftime('%d.%m.%Y') if p.birth_date else ''),
        ('Освіта', p.education), ('Посада та регалії', p.position_titles),
        ('Місце роботи', p.workplace), ('Телефон', p.phone), ('Ел. пошта', p.email),
        ('Соцмережі', p.social_links), ('Отримувач (ФОП)', p.fop_recipient),
        ('IBAN', secrets.fop_iban), ('РНОКПП', secrets.fop_rnokpp),
        ('Призначення платежу', p.fop_payment_purpose), ('Номер картки', secrets.card_number),
        ('Ідентифікаційний код', secrets.tax_id), ('Адреса реєстрації', p.registration_address),
        ('ЄДРПОУ', p.edrpou),
    ] %}
    <dt>{{ label }}</dt><dd>{{ value or '—' }}</dd>
    {% endfor %}
    <dt>Фото</dt>
    <dd>{% if p.photo_src %}<a href="{{ p.photo_src }}" target="_blank" rel="noopener">Відкрити</a>{% else %}—{% endif %}</dd>
  </dl>
  {% if not can_manage %}<p class="admin-hint">Реквізити приховано: потрібне право «Тренери: керування».</p>{% endif %}
  {% endif %}
</section>

<section class="admin-card">
  <h2>Інформація курсу</h2>
  {% for pr in proposals %}
  <article class="admin-card" id="proposal-{{ pr.id }}">
    <h3>{{ pr.title }} <span class="badge badge--{{ pr.status_badge }}">{{ pr.status_label }}</span></h3>
    <ol>{% for t in pr.theses %}<li>{{ t }}</li>{% endfor %}</ol>
    <dl class="admin-dl">
      <dt>Мова</dt><dd>{{ pr.language or '—' }}</dd>
      <dt>Актуальність</dt><dd>{{ pr.relevance or '—' }}</dd>
      <dt>Спеціальності</dt><dd>{{ pr.target_specialties or '—' }}</dd>
      <dt>Статті/ресурси</dt><dd>{{ pr.resources or '—' }}</dd>
      <dt>Теми на майбутнє</dt><dd>{{ pr.future_topics or '—' }}</dd>
      <dt>Тестування</dt><dd>{% if pr.quiz_url %}<a href="{{ pr.quiz_url }}" target="_blank" rel="noopener">{{ pr.quiz_url }}</a>{% else %}—{% endif %}</dd>
      {% if pr.curator_comment %}<dt>Коментар куратора</dt><dd>{{ pr.curator_comment }}</dd>{% endif %}
    </dl>
    {% if can_manage and pr.status == 'submitted' %}
    <form method="POST" action="{{ url_for('admin.trainer_proposal_accept', proposal_id=pr.id) }}">
      <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
      <button type="submit" class="apple-btn apple-btn--primary apple-btn--sm">Прийнято</button>
    </form>
    <form method="POST" action="{{ url_for('admin.trainer_proposal_return', proposal_id=pr.id) }}">
      {{ return_form.hidden_tag() }}
      {{ return_form.comment(class="form-input", rows=3, placeholder="Що доопрацювати") }}
      <button type="submit" class="apple-btn apple-btn--secondary apple-btn--sm">Повернути на доопрацювання</button>
    </form>
    {% endif %}
  </article>
  {% else %}
  <div class="iprm-empty-state"><p>Пропозицій курсу немає.</p></div>
  {% endfor %}
</section>
```

Класи `admin-card`, `admin-dl`, `admin-hint` -- лише якщо вони існують у дизайн-системі адмінки (`grep -n "^\.admin-card\|^\.admin-dl\|^\.admin-hint" app/static/css/admin.css`); інакше взяти ті, що вживає `trainer_edit.html` для секцій і підказок. Розкладку форм кнопок (в ряд) -- через наявний утилітарний клас адмінки, не inline.

`app/templates/admin/trainer_edit.html`: поле `form.account_email` поруч із `form.email` (той самий макрос/розмітка, що в сусідніх полях), а для наявного тренера (`{% if trainer %}`) -- посилання «Анкета тренера» на `url_for('admin.trainer_questionnaire', trainer_id=trainer.id)`.

`app/templates/admin/trainers.html`: у рядку тренера додати три індикатори (у колонку імені або окрему колонку -- як влаштована таблиця):

```html
{% if t.user_id %}<span class="badge badge--active" data-trainer-linked="{{ t.id }}">Акаунт</span>{% endif %}
{% if t.id in complete_profiles %}<span class="badge badge--info">Анкета</span>{% endif %}
{% if new_proposals.get(t.id) %}<a href="{{ url_for('admin.trainer_questionnaire', trainer_id=t.id) }}" class="badge badge--pending" data-trainer-new-proposals="{{ t.id }}">{{ new_proposals[t.id] }}</a>{% endif %}
```

(Змінна циклу в шаблоні може зватись не `t` -- взяти ту, що є.)

- [ ] **Step 7: Run tests**

Run: `python -m pytest tests/test_trainer_cabinet tests/test_routes/test_admin_instance_trainers.py tests/test_routes/test_admin_course_trainers.py tests/test_rbac -q`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add app/admin/forms.py app/admin/routes_trainers.py app/admin/routes_trainer_cabinet.py app/admin/__init__.py app/templates/admin/trainer_edit.html app/templates/admin/trainers.html app/templates/admin/trainer_questionnaire.html tests/test_trainer_cabinet/test_admin.py
git commit -m "feat(admin): прив'язка тренера до акаунта, анкета й пропозиції курсу в адмінці"
```

---

### Task 8: Налаштування «Для тренерів» і лист куратору

**Files:**
- Create: `app/templates/admin/settings_trainers.html`, `app/templates/emails/trainer_proposal_submitted.html`
- Modify: `app/admin/forms.py` (`TrainerSettingsForm`), `app/admin/routes_trainer_cabinet.py` (маршрут налаштувань), `app/templates/admin/settings.html` (посилання на нову сторінку), `app/services/email_service.py` (`send_trainer_proposal_notification`), `app/trainer_cabinet/routes.py` (`_after_submit`)
- Test: `tests/test_trainer_cabinet/test_admin_settings.py`, `tests/test_trainer_cabinet/test_notification.py`

**Interfaces:**
- Consumes: `svc.faq_source`, `svc.contract_email`, `EmailService.send_email(to, subject, template_name, context=None, trigger=None, ...)`.
- Produces: endpoint `admin.settings_trainers`; `EmailService.send_trainer_proposal_notification(proposal) -> EmailLog | None`.

- [ ] **Step 1: Write the failing tests**

`tests/test_trainer_cabinet/test_admin_settings.py`:

```python
import io

from app.extensions import db
from app.models.site_settings import SiteSettings
from tests.support.rbac import make_super_admin
from tests.test_trainer_cabinet._factories import login


def _admin(client):
    admin = make_super_admin(email='tc-sadmin@test.com')
    db.session.commit()
    login(client, admin)


def test_form_prefilled_with_default_faq(client):
    _admin(client)
    SiteSettings.get().trainer_faq_html = ''
    db.session.commit()
    html = client.get('/admin/settings/trainers').get_data(as_text=True)
    assert 'Вітаємо із приєднанням' in html


def test_save_faq_email_and_pdf(client):
    _admin(client)
    resp = client.post('/admin/settings/trainers', data={
        'faq_html': '<p>Новий текст {email}</p>',
        'contract_email': 'curator@test.com',
        'contract_pdf': (io.BytesIO(b'%PDF-1.4 new'), 'dogovir.pdf'),
    }, content_type='multipart/form-data')
    assert resp.status_code == 302
    s = SiteSettings.get()
    db.session.refresh(s)
    assert s.trainer_faq_html == '<p>Новий текст {email}</p>'
    assert s.trainer_contract_email == 'curator@test.com'
    assert s.trainer_contract_pdf == b'%PDF-1.4 new'
    assert s.trainer_contract_filename == 'dogovir.pdf'


def test_reject_non_pdf(client):
    _admin(client)
    resp = client.post('/admin/settings/trainers', data={
        'faq_html': '', 'contract_email': '',
        'contract_pdf': (io.BytesIO(b'MZ not a pdf'), 'evil.pdf'),
    }, content_type='multipart/form-data')
    assert resp.status_code == 200
    assert 'PDF' in resp.get_data(as_text=True)


def test_remove_contract(client):
    _admin(client)
    s = SiteSettings.get()
    s.trainer_contract_pdf = b'%PDF-1.4 x'
    s.trainer_contract_filename = 'x.pdf'
    db.session.commit()
    client.post('/admin/settings/trainers', data={
        'faq_html': '', 'contract_email': '', 'remove_contract': 'y'})
    db.session.refresh(s)
    assert not s.has_trainer_contract and s.trainer_contract_pdf is None


def test_requires_settings_permission(client):
    from tests.support.rbac import make_user_with_role
    viewer = make_user_with_role('viewer', email='tc-sviewer@test.com')
    db.session.commit()
    login(client, viewer)
    assert client.get('/admin/settings/trainers').status_code == 403
```

`tests/test_trainer_cabinet/test_notification.py`:

```python
from unittest import mock

from app.extensions import db
from app.models.site_settings import SiteSettings
from app.models.trainer_course_proposal import TrainerCourseProposal
from app.services.email_service import EmailService
from tests.test_trainer_cabinet._factories import login, make_trainer, make_user


def _draft(trainer):
    p = TrainerCourseProposal(trainer_id=trainer.id, title='КОС', theses=['a'])
    db.session.add(p)
    db.session.commit()
    return p


def test_submit_sends_to_contract_email(client):
    s = SiteSettings.get()
    s.trainer_contract_email = 'curator@test.com'
    db.session.commit()
    user = make_user()
    trainer = make_trainer(user, name='Петренко П.')
    p = _draft(trainer)
    login(client, user)
    with mock.patch.object(EmailService, 'send_email') as send:
        client.post(f'/trainer/proposals/{p.id}/submit')
    send.assert_called_once()
    args, kwargs = send.call_args
    to = kwargs.get('to', args[0] if args else None)
    assert to == 'curator@test.com'
    assert kwargs['template_name'] == 'trainer_proposal_submitted'
    assert kwargs['trigger'] == 'course_request'
    assert 'КОС' in kwargs['subject']


def test_fallback_to_site_email(client):
    s = SiteSettings.get()
    s.trainer_contract_email = ''
    s.email = 'office@test.com'
    db.session.commit()
    user = make_user()
    p = _draft(make_trainer(user))
    login(client, user)
    with mock.patch.object(EmailService, 'send_email') as send:
        client.post(f'/trainer/proposals/{p.id}/submit')
    args, kwargs = send.call_args
    assert kwargs.get('to', args[0] if args else None) == 'office@test.com'


def test_template_renders(app):
    user = make_user()
    trainer = make_trainer(user, name='Петренко П.')
    p = _draft(trainer)
    from flask import render_template
    html = render_template('emails/trainer_proposal_submitted.html', proposal=p,
                           trainer=trainer, admin_url='https://x/admin',
                           site_settings=SiteSettings.get())
    assert 'Петренко П.' in html and 'КОС' in html
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_trainer_cabinet/test_admin_settings.py tests/test_trainer_cabinet/test_notification.py -q`
Expected: FAIL.

- [ ] **Step 3: Форма налаштувань**

У `app/admin/forms.py` (імпорт `from flask_wtf.file import FileField, FileAllowed` на початку файлу):

```python
class TrainerSettingsForm(FlaskForm):
    faq_html = TextAreaField(
        'Текст «Частих питань»',
        validators=[Optional()],
        description='HTML: p, h3, ul/ol, li, strong, em, a. {email} -- адреса для договорів. '
                    'Порожнє поле -- текст за замовчуванням.',
    )
    contract_email = StringField(
        'Email для надсилання договорів',
        validators=[Optional(), Email(message='Невалідний email'), Length(max=255)],
        description='Порожнє -- загальний email сайту.',
    )
    contract_pdf = FileField(
        'PDF договору', validators=[Optional(), FileAllowed(['pdf'], 'Лише PDF')],
    )
    remove_contract = BooleanField('Прибрати завантажений договір')
```

- [ ] **Step 4: Маршрут налаштувань**

У `app/admin/routes_trainer_cabinet.py` (імпорти `from datetime import datetime, timezone`, `from flask import request`, `from app.admin.forms import TrainerSettingsForm`, `from app.models.site_settings import SiteSettings`):

```python
CONTRACT_MAX_BYTES = 10 * 1024 * 1024


def _read_contract(file):
    """Байти PDF або (None, помилка). Перевіряємо сигнатуру, а не лише розширення."""
    data = file.read()
    if not data.startswith(b'%PDF-'):
        return None, 'Файл не є PDF'
    if len(data) > CONTRACT_MAX_BYTES:
        return None, 'PDF більший за 10 МБ'
    return data, None


@admin_bp.route('/settings/trainers', methods=['GET', 'POST'])
@permission_required('settings.manage')
def settings_trainers():
    site = SiteSettings.get()
    form = TrainerSettingsForm()
    if request.method == 'GET':
        form.faq_html.data = svc.faq_source(site)
        form.contract_email.data = site.trainer_contract_email

    if form.validate_on_submit():
        upload = form.contract_pdf.data
        if upload and getattr(upload, 'filename', ''):
            data, error = _read_contract(upload)
            if error:
                form.contract_pdf.errors.append(error)
                return render_template('admin/settings_trainers.html', form=form, site=site)
            site.trainer_contract_pdf = data
            site.trainer_contract_filename = upload.filename
            site.trainer_contract_uploaded_at = datetime.now(timezone.utc)
        elif form.remove_contract.data:
            site.trainer_contract_pdf = None
            site.trainer_contract_filename = ''
            site.trainer_contract_uploaded_at = None

        site.trainer_faq_html = (form.faq_html.data or '').strip()
        site.trainer_contract_email = (form.contract_email.data or '').strip().lower()
        db.session.commit()
        audit_logger.info('Admin %s updated trainer settings', current_user.email)
        flash('Налаштування для тренерів збережено', 'success')
        return redirect(url_for('admin.settings_trainers'))

    return render_template('admin/settings_trainers.html', form=form, site=site)
```

Тонкість: якщо збережений текст FAQ дослівно дорівнює тексту за замовчуванням, зберігати `''`, щоб майбутні правки дефолту в коді доходили до сайту:

```python
        from app.data.trainer_faq import DEFAULT_TRAINER_FAQ_HTML
        faq = (form.faq_html.data or '').strip()
        site.trainer_faq_html = '' if faq == DEFAULT_TRAINER_FAQ_HTML.strip() else faq
```

(замінює рядок `site.trainer_faq_html = ...` вище).

`app/templates/admin/settings_trainers.html` -- той самий базовий шаблон і розмітка полів, що `admin/settings.html` (скопіювати `extends` і макрос поля). Форма `enctype="multipart/form-data"`: `faq_html` (textarea `rows=24`), `contract_email`, блок договору: якщо `site.has_trainer_contract` -- «Поточний файл: {{ site.trainer_contract_filename }}, завантажено {{ site.trainer_contract_uploaded_at | kyiv_dt }}» + чекбокс `remove_contract`; поле `contract_pdf`; кнопка «Зберегти». Помилки -- `form-error`.

У `app/templates/admin/settings.html` у верхній частині сторінки додати посилання «Для тренерів: договір і часті питання» на `url_for('admin.settings_trainers')`.

- [ ] **Step 5: Лист куратору**

У `app/services/email_service.py` після `send_b2b_request_notification`:

```python
    @staticmethod
    def send_trainer_proposal_notification(proposal):
        """Тренер надіслав пропозицію курсу -- лист на email для договорів.

        Тригер 'course_request': семантично це теж заявка на навчання, а
        нового значення CHECK ck_email_logs_trigger не має.
        """
        from app.models.site_settings import SiteSettings
        from app.services import trainer_cabinet
        settings = SiteSettings.get()
        to = trainer_cabinet.contract_email(settings)
        if not to:
            return None
        base = (settings.website_url or '').rstrip('/')
        path = f'/admin/trainers/{proposal.trainer_id}/questionnaire#proposal-{proposal.id}'
        return EmailService.send_email(
            to=to,
            subject=f'Пропозиція курсу від тренера: {proposal.title}',
            template_name='trainer_proposal_submitted',
            context={
                'proposal': proposal,
                'trainer': proposal.trainer,
                'admin_url': f'{base}{path}' if base else path,
            },
            trigger='course_request',
            lang='uk',
        )
```

`app/templates/emails/trainer_proposal_submitted.html` (за зразком `b2b_request_notification.html`):

```html
{% extends "emails/base.html" %}
{% from "emails/_macros.html" import button_primary, detail_row, spacer %}

{% block title %}Пропозиція курсу від тренера{% endblock %}

{% block preview_text %}{{ trainer.full_name }} -- {{ proposal.title }}{% endblock %}

{% block content %}
    <h1 class="mobile-h1" style="margin: 0 0 8px 0; font-size: 28px; font-weight: 700; color: #17131D; line-height: 1.25;">
        Нова пропозиція курсу
    </h1>

    <p class="mobile-text" style="margin: 0 0 24px 0; font-size: 15px; color: #625A6D; line-height: 1.5;">
        Тренер заповнив інформацію курсу в анкеті й надіслав її на розгляд.
    </p>

    <table role="presentation" style="width: 100%; margin-bottom: 24px; background-color: #F7F4FB; border: 1px solid #E9E4EF; border-radius: 8px;" cellpadding="0" cellspacing="0" border="0">
        <tr>
            <td style="padding: 20px 24px;">
                <p style="margin: 0 0 16px 0; font-size: 18px; font-weight: 600; color: #17131D; line-height: 1.3;">
                    {{ proposal.title }}
                </p>
                {{ detail_row("Тренер", trainer.full_name) }}
                {{ detail_row("Мова", proposal.language or "—") }}
                {{ detail_row("Тез", proposal.theses | length) }}
            </td>
        </tr>
    </table>

    {{ button_primary("Відкрити анкету в адмінці", admin_url) }}

    {{ spacer(16) }}
{% endblock %}
```

- [ ] **Step 6: Виклик після надсилання**

У `app/trainer_cabinet/routes.py` тіло `_after_submit`:

```python
def _after_submit(proposal):
    """Лист куратору. Збій пошти не скасовує надсилання -- пропозиція вже збережена."""
    from app.services.email_service import EmailService
    try:
        EmailService.send_trainer_proposal_notification(proposal)
    except Exception:
        logger.exception('Failed to notify curator about proposal %s', proposal.id)
```

- [ ] **Step 7: Run tests**

Run: `python -m pytest tests/test_trainer_cabinet -q`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add app/admin/forms.py app/admin/routes_trainer_cabinet.py app/templates/admin/settings_trainers.html app/templates/admin/settings.html app/services/email_service.py app/templates/emails/trainer_proposal_submitted.html app/trainer_cabinet/routes.py tests/test_trainer_cabinet/test_admin_settings.py tests/test_trainer_cabinet/test_notification.py
git commit -m "feat(trainer): налаштування договору й FAQ в адмінці, лист куратору про пропозицію"
```

---

### Task 9: Переклади, документація, повний прогін

**Files:**
- Modify: `app/translations/ru/LC_MESSAGES/messages.po`, `app/translations/en/LC_MESSAGES/messages.po`, `README.md` (розділ-навігатор функцій), перелік маршрутів (файл, куди останній коміт `fdad207d` додав режим «За заходами» -- `git show --stat fdad207d`), `docs/superpowers/specs/2026-09-19-trainer-cabinet-design.md` (статус + уточнення з цього плану)

- [ ] **Step 1: Витягти й влити рядки**

```bash
pybabel extract -F babel.cfg -k _l -o app/translations/messages.pot --project=IPRM --no-location app
pybabel update -i app/translations/messages.pot -d app/translations -w 79
```

- [ ] **Step 2: Перекласти нові msgid**

Заповнити `msgstr` для всіх нових рядків кабінету тренера в `ru` і `en` (`grep -n 'msgstr ""' -B2` біля нових `msgid`: «Кабінет тренера», «Анкета тренера», «Договір», «Часті питання», підписи полів форм, повідомлення flash, «Договір буде додано найближчим часом.» тощо). Прибрати мітки `#, fuzzy` у вичитаних записах.

- [ ] **Step 3: Компіляція**

Run: `pybabel compile -d app/translations`
Expected: без помилок. `.mo` не комітяться.

- [ ] **Step 4: Документація**

- `README.md`: у навігатор функцій -- пункт «Кабінет тренера» (що це, де вмикається: прив'язка акаунта в картці тренера; `/trainer`; налаштування `/admin/settings/trainers`; анкета `/admin/trainers/<id>/questionnaire`).
- Перелік маршрутів: `/trainer/`, `/trainer/profile`, `/trainer/proposals/new`, `/trainer/proposals/<id>`, `.../submit`, `.../delete`, `/trainer/contract`, `/trainer/contract/download`, `/trainer/faq`; адмінські `/admin/trainers/<id>/questionnaire`, `/admin/trainers/proposals/<id>/accept|return`, `/admin/settings/trainers`.
- Специфікація: статус «реалізовано (не запушено)»; розділ «Уточнення під час планування» з п'ятьма пунктами з цього плану.

- [ ] **Step 5: Повний прогін і інструменти**

```bash
python -m pytest tests/ -q
python 1-instruments/design-system/layer_check.py
python 1-instruments/design-system/shadowed_rules.py
node 1-instruments/design-system/atom-audit.cjs
```
Expected: усі тести зелені (зокрема `tests/test_routes/test_api_v1_clients.py` -- перевірка, що тести прибрали користувачів), нових порушень дизайн-системи немає, пороги `1-instruments/hygiene-ci/thresholds.json` не перевищено.

- [ ] **Step 6: Commit**

```bash
git add app/translations/ru/LC_MESSAGES/messages.po app/translations/en/LC_MESSAGES/messages.po README.md docs/superpowers/specs/2026-09-19-trainer-cabinet-design.md <файл переліку маршрутів>
git commit -m "docs(trainer): кабінет тренера -- переклади, README, перелік маршрутів"
```

---

## Після реалізації (для користувача, не для виконавця)

- Деплой: міграція `trainer_cabinet_20260919` (після `posthog_secondary_20260913`).
- В адмінці: вказати email для договорів і завантажити PDF договору (`/admin/settings/trainers`); прив'язати акаунти тренерів у їхніх картках.
