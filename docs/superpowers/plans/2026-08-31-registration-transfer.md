# Перенесення реєстрації на інший захід — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Дати адміністратору перенести зареєстрованого учасника на інше проведення — тихо або з листом, у якому учасник обирає між згодою й поверненням коштів, — з узгодженням різниці тарифів.

**Architecture:** Окрема таблиця `registration_transfers` (один рядок на перенесення) плюс чистий сервіс `app/services/transfer_service.py`, у якому живуть усі запобіжники й уся арифметика. Переїзд негайний; згода учасника лише підтверджує його. Гроші не рухаються ні з модалки, ні з публічної сторінки — лише через наявну чергу `RefundRequest` і `payment_ops`.

**Tech Stack:** Flask 3, SQLAlchemy ORM, Alembic (batch_alter_table), Jinja2, Flask-WTF (CSRF), pytest, власна CSS-дизайн-система (без Tailwind), vanilla JS без збірок.

**Spec:** `docs/superpowers/specs/2026-08-31-registration-transfer-design.md`

## Global Constraints

Скопійовано зі специфікації та `CLAUDE.md`. Кожне завдання неявно містить ці вимоги.

- **Жодних емодзі в коді.** Жодного inline-CSS і inline-JS у шаблонах (No Inline Policy, External Assets Pattern).
- **Не комітити й не пушити без прямої вказівки** — крок «Commit» у завданнях є винятком, він частина плану.
- **Tailwind не використовувати.** Тільки токени `common.css` + компонентні CSS.
- **Дизайн-система — джерело істини.** Новий компонент оголошується в компонентному CSS (не в `page-*.css`) і ПОКАЗУЄТЬСЯ в каталозі `/admin/design-system`. Клас, оголошений у двох файлах, — порушення.
- **`TRANSFER_MIN_HOURS = 48`** — поріг «2 дні», календарні години, одна константа на весь код.
- **`initiator='organizer'` забороняє `tariff_decision='surcharge'`** (§3.2 Політики). Правило стоїть у CHECK-обмеженні БД, не лише у формі.
- **Котирування повернення:** `organizer` → 100% сплаченого (§3.2); `participant` → `refund_policy.quote_registration(reg)` (§4.1).
- **`payment_amount` при перенесенні не змінюється.** Її рухає лише `payment_ops` — при поверненні або при зарахуванні доплати.
- **Промокод при перенесенні лишається застосованим**; `promo_code_id` і `discount_amount` не чіпаються.
- **Уся арифметика грошей — на сервері.** JS показує те, що прийшло, і нічого не рахує.
- **Тести прибирають за собою.** Сервіси комітять, тестова БД одна на сесію; користувачів і каталог чистити через `tests/refund_fixtures.purge`, інакше валиться `test_api_v1_clients` і `test_xlsx_participants`.
- **Alembic head на момент написання плану — `9fad58660b0d`.** Перед створенням міграції завжди звіряти реальний head: `python -m flask db heads`. Двох голів не створювати.

## File Structure

| Файл | Відповідальність |
|---|---|
| `app/models/registration_transfer.py` | Створити. Модель `RegistrationTransfer`: колонки, CHECK, індекси, ярлики й бейджі |
| `app/services/transfer_service.py` | Створити. Запобіжники, підбір цільових заходів, виконання переносу, відповіді учасника, міст до заявок |
| `app/admin/routes_registrations.py` | Змінити. Два роути: JSON-опції модалки й виконання переносу |
| `app/templates/admin/partials/_registration_actions.html` | Змінити. Пункт «Перенести» — спільний для обох сторінок реєстрацій |
| `app/templates/admin/partials/_transfer_modal.html` | Створити. Розмітка модалки |
| `app/static/css/modal.css` | Створити. Компонент дизайн-системи |
| `app/static/js/modal.js` | Створити. Відкриття/закриття, фокус, Esc |
| `app/static/js/admin-transfer.js` | Створити. Заповнення модалки з `options`, вимикання «доплати» |
| `app/templates/design_system/_tab_molecules.html` | Змінити. Показ компонента `modal` у каталозі |
| `app/services/email_service.py` | Змінити. `send_transfer_offer` |
| `app/models/email_log.py` | Змінити. Тригер `transfer` у `TRIGGERS` і в CHECK |
| `app/templates/emails/transfer_offer.html` | Створити. Лист із вибором |
| `app/registration/routes.py` | Змінити. Чотири публічні роути по токену |
| `app/templates/registration/transfer_consent.html` | Створити. Сторінка згоди |
| `app/services/payment_ops.py` | Змінити. Префікс `SUR-` і зарахування доплати |
| `migrations/versions/registration_transfer_20260831.py` | Створити. Таблиця |
| `migrations/versions/email_trigger_transfer_20260831.py` | Створити. CHECK тригерів |
| `tests/refund_fixtures.py` | Змінити. Чистити `registration_transfers` |
| `tests/test_models/test_registration_transfer.py` | Створити |
| `tests/test_services/test_transfer_service.py` | Створити |
| `tests/test_routes/test_transfer_public.py` | Створити |
| `tests/test_routes/test_admin_transfer.py` | Створити |
| `docs/registration-transfer.md` | Створити. Опис фічі |
| `README.md` | Змінити. Рядок у таблиці документації |

---

### Task 1: Модель `RegistrationTransfer` і міграція

**Files:**
- Create: `app/models/registration_transfer.py`
- Create: `migrations/versions/registration_transfer_20260831.py`
- Modify: `app/models/__init__.py`
- Modify: `tests/refund_fixtures.py`
- Test: `tests/test_models/test_registration_transfer.py`

**Interfaces:**
- Consumes: нічого (перше завдання).
- Produces: клас `RegistrationTransfer` з константами станів `STATE_APPLIED='applied'`, `STATE_AWAITING='awaiting_consent'`, `STATE_ACCEPTED='accepted'`, `STATE_REFUND_REQUESTED='refund_requested'`; методи `issue_consent_token(ttl_days=30) -> str`, властивості `consent_token_active -> bool`, `surcharge_due -> bool`, `state_label`, `state_badge`, `initiator_label`, `tariff_decision_label`.

- [ ] **Step 1: Написати тести моделі**

Створити `tests/test_models/test_registration_transfer.py`. Тести перевіряють САМЕ обмеження БД — те, чого не видно з Python-коду.

```python
"""Обмеження таблиці registration_transfers.

Перевіряємо рівень БД, а не Python: правило "організатор не може вимагати
доплату" родом з опублікованої Політики (§3.2), і форма -- не те місце, де
його можна обійти наступною правкою шаблону.
"""
import pytest
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.registration import EventRegistration
from app.models.registration_transfer import RegistrationTransfer
from app.models.user import User
from tests.refund_fixtures import purge

PREFIX = 'rtm-'


@pytest.fixture
def reg(app):
    user = User(email=f'{PREFIX}one@example.com', first_name='Тест',
                last_name='Переносний', is_active=True)
    user.set_password('x' * 12)
    course = Course(title='Курс переносу', slug=f'{PREFIX}course')
    db.session.add_all([user, course])
    db.session.flush()
    src = CourseInstance(course_id=course.id, status='published')
    dst = CourseInstance(course_id=course.id, status='published')
    db.session.add_all([src, dst])
    db.session.flush()
    item = EventRegistration(
        user_id=user.id, instance_id=src.id, phone='+380000000000',
        specialty='Лікар', workplace='Клініка', status='confirmed',
        payment_status='paid', payment_amount=1000,
    )
    db.session.add(item)
    db.session.commit()
    yield item, src, dst
    purge(PREFIX, slug_prefix=PREFIX)


def _transfer(item, src, dst, **kwargs):
    data = dict(
        registration_id=item.id, from_instance_id=src.id, to_instance_id=dst.id,
        initiator='participant', tariff_decision='keep',
        state=RegistrationTransfer.STATE_APPLIED,
    )
    data.update(kwargs)
    return RegistrationTransfer(**data)


def test_organizer_cannot_demand_surcharge(reg):
    """CHECK §3.2: перенесення з нашої ініціативи -- без додаткової оплати."""
    item, src, dst = reg
    db.session.add(_transfer(item, src, dst,
                             initiator='organizer', tariff_decision='surcharge'))
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()


def test_participant_may_be_asked_to_surcharge(reg):
    item, src, dst = reg
    db.session.add(_transfer(item, src, dst,
                             initiator='participant', tariff_decision='surcharge'))
    db.session.commit()
    assert RegistrationTransfer.query.count() == 1


def test_only_one_open_transfer_per_registration(reg):
    """Партіальний унікальний індекс: два відкритих переноси на одну
    реєстрацію означали б, що згода закриває випадковий із них."""
    item, src, dst = reg
    db.session.add(_transfer(item, src, dst,
                             state=RegistrationTransfer.STATE_AWAITING))
    db.session.commit()
    db.session.add(_transfer(item, src, dst,
                             state=RegistrationTransfer.STATE_AWAITING))
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()


def test_closed_transfers_do_not_collide(reg):
    """Індекс частковий: закриті переноси не заважають наступному."""
    item, src, dst = reg
    db.session.add(_transfer(item, src, dst,
                             state=RegistrationTransfer.STATE_ACCEPTED))
    db.session.add(_transfer(item, src, dst,
                             state=RegistrationTransfer.STATE_ACCEPTED))
    db.session.commit()
    assert RegistrationTransfer.query.count() == 2


def test_surcharge_due_only_until_paid(reg):
    item, src, dst = reg
    row = _transfer(item, src, dst, tariff_decision='surcharge', difference=500)
    db.session.add(row)
    db.session.commit()
    assert row.surcharge_due is True
    row.surcharge_paid_at = db.func.now()
    db.session.commit()
    assert row.surcharge_due is False


def test_consent_token_expires(reg):
    item, src, dst = reg
    row = _transfer(item, src, dst)
    token = row.issue_consent_token(ttl_days=30)
    assert len(token) > 20
    assert row.consent_token_active is True
    row.consent_token_expires_at = None
    assert row.consent_token_active is False
```

- [ ] **Step 2: Запустити тести — вони мають упасти**

Run: `python -m pytest tests/test_models/test_registration_transfer.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.models.registration_transfer'`

- [ ] **Step 3: Написати модель**

Створити `app/models/registration_transfer.py`:

```python
"""RegistrationTransfer -- перенесення реєстрації на інше проведення.

Окрема таблиця, а не колонки на EventRegistration: людину можна переносити
повторно, і другий перенос не має затирати перший. Реєстрація вже несе
понад тридцять колонок -- дописувати туди ще вісім означало б, що кожен
лістинг тягне поля, потрібні одному екрану.

Суми тут -- ЗНІМКИ на момент переносу, як `quoted_*` у RefundRequest: тариф
можна відредагувати заднім числом, і жива формула дала б іншу відповідь,
ніж та, яку учасник побачив у листі.

Гроші звідси не рухаються. Рішення про повернення лишається за чергою
заявок і сторінкою /admin/refunds/..., доплата -- за LiqPay-callback у
payment_ops. Одне місце, де система віддає гроші, легше стерегти, ніж три.
"""
import secrets
from datetime import timedelta, timezone

from app.extensions import db
from app.models.mixins import TimestampMixin, BigIntPK, utcnow

CONSENT_TOKEN_TTL_DAYS = 30

STATE_APPLIED = 'applied'
STATE_AWAITING = 'awaiting_consent'
STATE_ACCEPTED = 'accepted'
STATE_REFUND_REQUESTED = 'refund_requested'

INITIATOR_ORGANIZER = 'organizer'
INITIATOR_PARTICIPANT = 'participant'

DECISION_KEEP = 'keep'
DECISION_REFUND_DIFF = 'refund_diff'
DECISION_SURCHARGE = 'surcharge'


class RegistrationTransfer(TimestampMixin, db.Model):
    __tablename__ = 'registration_transfers'

    STATE_APPLIED = STATE_APPLIED
    STATE_AWAITING = STATE_AWAITING
    STATE_ACCEPTED = STATE_ACCEPTED
    STATE_REFUND_REQUESTED = STATE_REFUND_REQUESTED

    id = db.Column(BigIntPK, primary_key=True)
    registration_id = db.Column(
        db.BigInteger,
        db.ForeignKey('event_registrations.id', ondelete='CASCADE'),
        nullable=False, index=True,
    )
    # SET NULL, а не CASCADE: історія перенесення має пережити видалення
    # заходу, інакше зникає саме той запис, заради якого таблиця й заведена.
    from_instance_id = db.Column(
        db.BigInteger,
        db.ForeignKey('course_instances.id', ondelete='SET NULL'),
        nullable=True,
    )
    to_instance_id = db.Column(
        db.BigInteger,
        db.ForeignKey('course_instances.id', ondelete='SET NULL'),
        nullable=True,
    )

    initiator = db.Column(db.String(20), nullable=False)
    announced = db.Column(
        db.Boolean, nullable=False, default=False, server_default=db.false(),
    )

    # Порожні поля НЕ рендеряться в листі -- ані заголовка, ані порожнього
    # блоку. Тому NULL тут значуще, і порожній рядок нормалізуємо в None.
    reason = db.Column(db.String(500))
    note = db.Column(db.Text)

    tariff_decision = db.Column(db.String(20), nullable=False)
    to_tariff_id = db.Column(
        db.BigInteger,
        db.ForeignKey('instance_tariffs.id', ondelete='SET NULL'),
        nullable=True,
    )

    old_amount = db.Column(db.Numeric(10, 2))
    new_amount = db.Column(db.Numeric(10, 2))
    difference = db.Column(db.Numeric(10, 2))

    state = db.Column(db.String(20), nullable=False, index=True)

    consent_token = db.Column(db.String(64), unique=True, index=True)
    consent_token_expires_at = db.Column(db.DateTime(timezone=True))
    responded_at = db.Column(db.DateTime(timezone=True))

    refund_request_id = db.Column(
        db.BigInteger,
        db.ForeignKey('refund_requests.id', ondelete='SET NULL'),
        nullable=True,
    )

    surcharge_paid_at = db.Column(db.DateTime(timezone=True))
    surcharge_payment_id = db.Column(db.String(255))

    created_by_id = db.Column(
        db.BigInteger, db.ForeignKey('users.id', ondelete='SET NULL'),
        nullable=True,
    )

    registration = db.relationship('EventRegistration')
    from_instance = db.relationship(
        'CourseInstance', foreign_keys=[from_instance_id])
    to_instance = db.relationship(
        'CourseInstance', foreign_keys=[to_instance_id])
    to_tariff = db.relationship('InstanceTariff', foreign_keys=[to_tariff_id])
    refund_request = db.relationship('RefundRequest')
    created_by = db.relationship('User', foreign_keys=[created_by_id])

    __table_args__ = (
        db.CheckConstraint(
            "state IN ('applied', 'awaiting_consent', 'accepted', "
            "'refund_requested')",
            name='ck_registration_transfers_state',
        ),
        db.CheckConstraint(
            "initiator IN ('organizer', 'participant')",
            name='ck_registration_transfers_initiator',
        ),
        db.CheckConstraint(
            "tariff_decision IN ('keep', 'refund_diff', 'surcharge')",
            name='ck_registration_transfers_decision',
        ),
        # §3.2 Політики: перенесення з ініціативи Організатора -- без
        # додаткової оплати. Правило стоїть у БД, бо родом з оферти.
        db.CheckConstraint(
            "NOT (initiator = 'organizer' AND tariff_decision = 'surcharge')",
            name='ck_registration_transfers_organizer_no_surcharge',
        ),
        # Одне відкрите перенесення на реєстрацію. Без цього повторний клік
        # адміна лишав би дві пропозиції, і згода закривала б випадкову.
        db.Index(
            'uq_registration_transfers_open',
            'registration_id', unique=True,
            postgresql_where=db.text("state = 'awaiting_consent'"),
            sqlite_where=db.text("state = 'awaiting_consent'"),
        ),
        db.Index('ix_registration_transfers_registration', 'registration_id'),
    )

    STATES = [
        (STATE_APPLIED, 'Виконано'),
        (STATE_AWAITING, 'Очікує відповіді'),
        (STATE_ACCEPTED, 'Погоджено учасником'),
        (STATE_REFUND_REQUESTED, 'Учасник просить повернення'),
    ]

    STATE_BADGES = {
        STATE_APPLIED: 'active',
        STATE_AWAITING: 'pending',
        STATE_ACCEPTED: 'active',
        STATE_REFUND_REQUESTED: 'cancelled',
    }

    INITIATORS = [
        (INITIATOR_ORGANIZER, 'З ініціативи Організатора'),
        (INITIATOR_PARTICIPANT, 'На прохання учасника'),
    ]

    DECISIONS = [
        (DECISION_KEEP, 'Лишити суму як є'),
        (DECISION_REFUND_DIFF, 'Повернути різницю'),
        (DECISION_SURCHARGE, 'Запросити доплату різниці'),
    ]

    @property
    def state_label(self):
        return dict(self.STATES).get(self.state, self.state)

    @property
    def state_badge(self):
        return self.STATE_BADGES.get(self.state, 'draft')

    @property
    def initiator_label(self):
        return dict(self.INITIATORS).get(self.initiator, self.initiator)

    @property
    def tariff_decision_label(self):
        return dict(self.DECISIONS).get(
            self.tariff_decision, self.tariff_decision)

    @property
    def surcharge_due(self):
        """Доплату запросили, але вона ще не надійшла."""
        return (self.tariff_decision == DECISION_SURCHARGE
                and self.surcharge_paid_at is None)

    @property
    def is_open(self):
        return self.state == STATE_AWAITING

    def issue_consent_token(self, ttl_days=CONSENT_TOKEN_TTL_DAYS):
        """Згенерувати токен публічного посилання. Не комітить."""
        self.consent_token = secrets.token_urlsafe(32)
        self.consent_token_expires_at = utcnow() + timedelta(days=ttl_days)
        return self.consent_token

    @property
    def consent_token_active(self):
        if not self.consent_token or self.consent_token_expires_at is None:
            return False
        exp = self.consent_token_expires_at
        if exp.tzinfo is None:  # SQLite повертає naive
            exp = exp.replace(tzinfo=timezone.utc)
        return utcnow() <= exp

    def __repr__(self):
        return (f'<RegistrationTransfer {self.id} REG-{self.registration_id} '
                f'{self.state}>')
```

- [ ] **Step 4: Зареєструвати модель в `app/models/__init__.py`**

Відкрити `app/models/__init__.py`, знайти рядок імпорту `registration` і додати поруч, зберігши наявний стиль файлу (алфавітний порядок імпортів і склад `__all__`, якщо він є):

```python
from app.models.registration_transfer import RegistrationTransfer  # noqa: F401
```

- [ ] **Step 5: Перевірити реальний head Alembic**

Run: `python -m flask db heads`
Expected: рівно ОДИН рядок. Записати це значення — воно піде в `down_revision`. На момент написання плану це `9fad58660b0d`; якщо вивід інший — брати вивід, а не плановане значення. Якщо голів дві — зупинитись і повідомити координатора: двох голів не створювати.

- [ ] **Step 6: Написати міграцію**

Створити `migrations/versions/registration_transfer_20260831.py`. Підставити у `down_revision` значення з кроку 5.

```python
"""registration_transfers -- перенесення реєстрації на інше проведення.

Revision ID: registration_transfer_20260831
Revises: 9fad58660b0d
"""
import sqlalchemy as sa
from alembic import op

revision = 'registration_transfer_20260831'
down_revision = '9fad58660b0d'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'registration_transfers',
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column('registration_id', sa.BigInteger(), nullable=False),
        sa.Column('from_instance_id', sa.BigInteger(), nullable=True),
        sa.Column('to_instance_id', sa.BigInteger(), nullable=True),
        sa.Column('initiator', sa.String(length=20), nullable=False),
        sa.Column('announced', sa.Boolean(), nullable=False,
                  server_default=sa.false()),
        sa.Column('reason', sa.String(length=500), nullable=True),
        sa.Column('note', sa.Text(), nullable=True),
        sa.Column('tariff_decision', sa.String(length=20), nullable=False),
        sa.Column('to_tariff_id', sa.BigInteger(), nullable=True),
        sa.Column('old_amount', sa.Numeric(10, 2), nullable=True),
        sa.Column('new_amount', sa.Numeric(10, 2), nullable=True),
        sa.Column('difference', sa.Numeric(10, 2), nullable=True),
        sa.Column('state', sa.String(length=20), nullable=False),
        sa.Column('consent_token', sa.String(length=64), nullable=True),
        sa.Column('consent_token_expires_at', sa.DateTime(timezone=True),
                  nullable=True),
        sa.Column('responded_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('refund_request_id', sa.BigInteger(), nullable=True),
        sa.Column('surcharge_paid_at', sa.DateTime(timezone=True),
                  nullable=True),
        sa.Column('surcharge_payment_id', sa.String(length=255), nullable=True),
        sa.Column('created_by_id', sa.BigInteger(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['registration_id'], ['event_registrations.id'],
                                ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['from_instance_id'], ['course_instances.id'],
                                ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['to_instance_id'], ['course_instances.id'],
                                ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['to_tariff_id'], ['instance_tariffs.id'],
                                ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['refund_request_id'], ['refund_requests.id'],
                                ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['created_by_id'], ['users.id'],
                                ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.CheckConstraint(
            "state IN ('applied', 'awaiting_consent', 'accepted', "
            "'refund_requested')",
            name='ck_registration_transfers_state'),
        sa.CheckConstraint(
            "initiator IN ('organizer', 'participant')",
            name='ck_registration_transfers_initiator'),
        sa.CheckConstraint(
            "tariff_decision IN ('keep', 'refund_diff', 'surcharge')",
            name='ck_registration_transfers_decision'),
        sa.CheckConstraint(
            "NOT (initiator = 'organizer' AND tariff_decision = 'surcharge')",
            name='ck_registration_transfers_organizer_no_surcharge'),
    )
    op.create_index('ix_registration_transfers_registration',
                    'registration_transfers', ['registration_id'])
    op.create_index('ix_registration_transfers_state',
                    'registration_transfers', ['state'])
    op.create_index('ix_registration_transfers_consent_token',
                    'registration_transfers', ['consent_token'], unique=True)
    op.create_index(
        'uq_registration_transfers_open', 'registration_transfers',
        ['registration_id'], unique=True,
        postgresql_where=sa.text("state = 'awaiting_consent'"),
        sqlite_where=sa.text("state = 'awaiting_consent'"),
    )


def downgrade():
    op.drop_index('uq_registration_transfers_open',
                  table_name='registration_transfers')
    op.drop_index('ix_registration_transfers_consent_token',
                  table_name='registration_transfers')
    op.drop_index('ix_registration_transfers_state',
                  table_name='registration_transfers')
    op.drop_index('ix_registration_transfers_registration',
                  table_name='registration_transfers')
    op.drop_table('registration_transfers')
```

- [ ] **Step 7: Додати прибирання в `tests/refund_fixtures.py`**

У функції `purge`, у блоці `if regs:` — ПЕРЕД видаленням `EventRegistration` (інакше FK CASCADE спрацює по-різному в SQLite і Postgres, і тест побачить різну поведінку на dev і в CI):

```python
            RegistrationTransfer.query.filter(
                RegistrationTransfer.registration_id.in_(regs)).delete(
                    synchronize_session=False)
```

І імпорт угорі файла, в алфавітному порядку серед решти:

```python
from app.models.registration_transfer import RegistrationTransfer
```

- [ ] **Step 8: Прогнати міграцію й тести**

Run:
```bash
python -m flask db upgrade
python -m pytest tests/test_models/test_registration_transfer.py -v
```
Expected: міграція проходить; усі 6 тестів PASS.

- [ ] **Step 9: Переконатись, що голова одна й нічого не зламано**

Run:
```bash
python -m flask db heads
python -m pytest tests/test_models tests/test_db -q
```
Expected: рівно один head; тести PASS.

- [ ] **Step 10: Commit**

```bash
git add app/models/registration_transfer.py app/models/__init__.py \
        migrations/versions/registration_transfer_20260831.py \
        tests/refund_fixtures.py tests/test_models/test_registration_transfer.py
git commit -m "feat(перенесення): модель RegistrationTransfer і міграція"
```

---

### Task 2: Запобіжники й підбір цільових заходів

**Files:**
- Create: `app/services/transfer_service.py`
- Test: `tests/test_services/test_transfer_service.py`

**Interfaces:**
- Consumes: `RegistrationTransfer` з Task 1 (константи `STATE_AWAITING`).
- Produces:
  - `TRANSFER_MIN_HOURS = 48`
  - `check(registration, target_instance=None) -> list[str]` — список причин; порожній = можна
  - `eligible_instances(registration) -> list[CourseInstance]`
  - `hours_until(start_date) -> float | None`

- [ ] **Step 1: Написати тести запобіжників**

Створити `tests/test_services/test_transfer_service.py`:

```python
"""Запобіжники перенесення.

Кожен -- окремим тестом: список причин показується адміну як є, і "чому
кнопка неактивна" має бути видно з падіння одного тесту, а не з'ясовуватись
перебором.
"""
from datetime import timedelta

import pytest

from app.extensions import db
from app.models.certificate import Certificate
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.mixins import utcnow
from app.models.registration import EventRegistration
from app.models.registration_transfer import RegistrationTransfer
from app.models.user import User
from app.services import transfer_service
from tests.refund_fixtures import purge

PREFIX = 'rts-'


@pytest.fixture
def world(app):
    """Реєстрація на заході через 10 днів + вільний цільовий через 20."""
    user = User(email=f'{PREFIX}one@example.com', first_name='Тест',
                last_name='Переносний', is_active=True)
    user.set_password('x' * 12)
    course = Course(title='Курс переносу', slug=f'{PREFIX}course')
    db.session.add_all([user, course])
    db.session.flush()
    now = utcnow()
    src = CourseInstance(course_id=course.id, status='published',
                         start_date=now + timedelta(days=10), price=1000)
    dst = CourseInstance(course_id=course.id, status='published',
                         start_date=now + timedelta(days=20), price=1500)
    db.session.add_all([src, dst])
    db.session.flush()
    reg = EventRegistration(
        user_id=user.id, instance_id=src.id, phone='+380000000000',
        specialty='Лікар', workplace='Клініка', status='confirmed',
        payment_status='paid', payment_amount=1000,
    )
    db.session.add(reg)
    db.session.commit()
    yield reg, src, dst, user, course
    purge(PREFIX, slug_prefix=PREFIX)


def test_clean_case_has_no_blockers(world):
    reg, src, dst, _, _ = world
    assert transfer_service.check(reg, dst) == []


def test_guard_1_source_event_too_close(world):
    reg, src, dst, _, _ = world
    src.start_date = utcnow() + timedelta(hours=47)
    db.session.commit()
    problems = transfer_service.check(reg, dst)
    assert any('поточного заходу' in p for p in problems)


def test_guard_2_target_event_too_close(world):
    reg, src, dst, _, _ = world
    dst.start_date = utcnow() + timedelta(hours=47)
    db.session.commit()
    problems = transfer_service.check(reg, dst)
    assert any('обраного заходу' in p for p in problems)


def test_guard_3_same_instance(world):
    reg, src, dst, _, _ = world
    problems = transfer_service.check(reg, src)
    assert any('той самий захід' in p for p in problems)


def test_guard_4_target_not_published(world):
    reg, src, dst, _, _ = world
    dst.status = 'draft'
    db.session.commit()
    problems = transfer_service.check(reg, dst)
    assert any('недоступний' in p for p in problems)


def test_guard_5_already_registered_on_target(world):
    """Без цього перенесення падає на uq_user_instance_registration --
    у момент коміту, вже після надсилання листа."""
    reg, src, dst, user, _ = world
    db.session.add(EventRegistration(
        user_id=user.id, instance_id=dst.id, phone='+380000000000',
        specialty='Лікар', workplace='Клініка',
    ))
    db.session.commit()
    problems = transfer_service.check(reg, dst)
    assert any('уже зареєстрований' in p for p in problems)


def test_guard_6_cancelled_registration(world):
    reg, src, dst, _, _ = world
    reg.status = 'cancelled'
    db.session.commit()
    assert any('скасовано' in p.lower() for p in transfer_service.check(reg, dst))


def test_guard_7_certificate_issued(world):
    """Certificate має чотири NOT NULL-поля понад FK -- number,
    recipient_name, event_title, pdf_path; без них падає сам INSERT."""
    reg, src, dst, user, _ = world
    db.session.add(Certificate(
        registration_id=reg.id, user_id=user.id, number=f'{PREFIX}0001',
        recipient_name='Тест Переносний', event_title='Курс переносу',
        pdf_path='certificates/rts-0001.pdf',
    ))
    db.session.commit()
    assert any('сертифікат' in p for p in transfer_service.check(reg, dst))


def test_guard_8_quiz_passed(world):
    reg, src, dst, _, _ = world
    reg.quiz_passed_at = utcnow()
    db.session.commit()
    assert any('тест' in p for p in transfer_service.check(reg, dst))


def test_guard_9_open_transfer_exists(world):
    reg, src, dst, _, _ = world
    db.session.add(RegistrationTransfer(
        registration_id=reg.id, from_instance_id=src.id, to_instance_id=dst.id,
        initiator='participant', tariff_decision='keep',
        state=RegistrationTransfer.STATE_AWAITING,
    ))
    db.session.commit()
    assert any('очікує відповіді' in p for p in transfer_service.check(reg, dst))


def test_check_without_target_runs_only_registration_guards(world):
    """Без цілі перевіряємо лише стан самої реєстрації -- саме так модалка
    вирішує, чи пропонувати заходи взагалі."""
    reg, src, dst, _, _ = world
    assert transfer_service.check(reg) == []
    reg.status = 'cancelled'
    db.session.commit()
    assert transfer_service.check(reg) != []


def test_eligible_instances_excludes_blocked(world):
    reg, src, dst, _, _ = world
    ids = [i.id for i in transfer_service.eligible_instances(reg)]
    assert dst.id in ids
    assert src.id not in ids


def test_eligible_instances_excludes_too_close(world):
    reg, src, dst, _, _ = world
    dst.start_date = utcnow() + timedelta(hours=12)
    db.session.commit()
    assert transfer_service.eligible_instances(reg) == []
```

- [ ] **Step 2: Запустити — має впасти**

Run: `python -m pytest tests/test_services/test_transfer_service.py -v`
Expected: FAIL — `ImportError: cannot import name 'transfer_service'`

- [ ] **Step 3: Написати запобіжники**

Створити `app/services/transfer_service.py`:

```python
"""Перенесення реєстрації на інше проведення.

Уся логіка тут; роути лишаються тонкими. Гроші звідси не рухаються --
повернення йде через чергу заявок, доплата через LiqPay-callback.

Правова рамка -- опублікована Політика (app/templates/main/refund.html):
§3.2 дає учаснику, ЯКОГО ПЕРЕНЕСЛИ МИ, право на участь без додаткової
оплати або на 100% повернення; §4.1 з його сіткою 100/50/25/0 діє лише
коли від участі відмовляється сам учасник. Тому `initiator` -- не довідкове
поле, а розгалуження всієї фічі.
"""
import logging

from app.models.course_instance import CourseInstance
from app.models.registration import EventRegistration
from app.models.registration_transfer import RegistrationTransfer
from app.models.mixins import utcnow
from app.utils import ensure_utc

logger = logging.getLogger(__name__)

# "Не пізніше ніж за 2 дні" -- 48 календарних годин. Політика оперує
# робочими днями лише в §3.3, і саме про дедлайн заявки на повернення, а не
# про перенесення. Одна константа: перехід на робочі дні -- одна правка.
TRANSFER_MIN_HOURS = 48


def hours_until(start_date):
    """Скільки годин лишилось до початку заходу. None -- дати немає."""
    if start_date is None:
        return None
    return (ensure_utc(start_date) - utcnow()).total_seconds() / 3600.0


def _registration_problems(reg):
    """Запобіжники, що не залежать від цільового заходу (1, 6, 7, 8, 9)."""
    problems = []

    if reg.status == 'cancelled':
        problems.append('Реєстрацію скасовано')

    hours = hours_until(reg.instance.start_date if reg.instance else None)
    if hours is not None and hours < TRANSFER_MIN_HOURS:
        problems.append(
            'До поточного заходу лишилось менше 2 діб — '
            'перенесення вже неможливе'
        )

    if reg.certificate is not None and not reg.certificate.revoked:
        problems.append('За реєстрацією вже видано сертифікат')

    if reg.quiz_passed_at is not None:
        problems.append('Учасник уже склав тест за цим заходом')

    open_transfer = RegistrationTransfer.query.filter_by(
        registration_id=reg.id, state=RegistrationTransfer.STATE_AWAITING,
    ).first()
    if open_transfer is not None:
        problems.append(
            'Попереднє перенесення ще очікує відповіді учасника'
        )

    return problems


def _target_problems(reg, target):
    """Запобіжники щодо цільового заходу (2, 3, 4, 5)."""
    problems = []

    if target.id == reg.instance_id:
        problems.append('Це той самий захід')

    hours = hours_until(target.start_date)
    if hours is None or hours < TRANSFER_MIN_HOURS:
        problems.append('До обраного заходу лишилось менше 2 діб')

    if target.status not in ('published', 'active'):
        problems.append('Захід недоступний для реєстрації')

    # Без цього перенесення падає на uq_user_instance_registration у момент
    # коміту -- вже після того, як лист пішов учаснику.
    duplicate = EventRegistration.query.filter_by(
        user_id=reg.user_id, instance_id=target.id,
    ).first()
    if duplicate is not None and duplicate.id != reg.id:
        problems.append('Учасник уже зареєстрований на цей захід')

    return problems


def check(registration, target_instance=None):
    """Причини, чому перенести не можна. Порожній список -- можна.

    Формулювання розраховані на показ як є: людина має розуміти, чому
    кнопки немає, а не впиратись у мовчазну відсутність.

    Без `target_instance` виконуються лише перевірки стану самої
    реєстрації -- саме так модалка вирішує, чи пропонувати заходи взагалі.
    """
    problems = _registration_problems(registration)
    if target_instance is not None:
        problems.extend(_target_problems(registration, target_instance))
    return problems


def eligible_instances(registration):
    """Проведення, на які цю реєстрацію можна перенести.

    Порядок -- за датою: адмін шукає найближчу придатну дату, а не курс.
    """
    if _registration_problems(registration):
        return []

    candidates = (
        CourseInstance.query
        .filter(CourseInstance.status.in_(('published', 'active')))
        .filter(CourseInstance.start_date.isnot(None))
        .order_by(CourseInstance.start_date.asc())
        .all()
    )
    return [
        item for item in candidates
        if not _target_problems(registration, item)
    ]
```

- [ ] **Step 4: Прогнати тести**

Run: `python -m pytest tests/test_services/test_transfer_service.py -v`
Expected: усі 13 тестів PASS.

- [ ] **Step 5: Commit**

```bash
git add app/services/transfer_service.py tests/test_services/test_transfer_service.py
git commit -m "feat(перенесення): запобіжники й підбір цільових заходів"
```

---

### Task 3: Виконання перенесення

**Files:**
- Modify: `app/services/transfer_service.py`
- Test: `tests/test_services/test_transfer_service.py`

**Interfaces:**
- Consumes: `check()`, `TRANSFER_MIN_HOURS` з Task 2; `registration_service.assign_place_number(reg)`.
- Produces: `execute(registration, *, target_instance, initiator, tariff=None, tariff_decision='keep', reason=None, note=None, announced=False, admin_user=None) -> RegistrationTransfer` — комітить, кидає `ValueError` зі списком причин у `args[0]`, якщо `check()` не порожній.

- [ ] **Step 1: Дописати тести виконання**

Додати в кінець `tests/test_services/test_transfer_service.py`:

```python
def _execute(reg, dst, **kwargs):
    data = dict(target_instance=dst, initiator='participant',
                tariff_decision='keep')
    data.update(kwargs)
    return transfer_service.execute(reg, **data)


def test_execute_moves_registration(world):
    reg, src, dst, _, _ = world
    transfer = _execute(reg, dst)
    assert reg.instance_id == dst.id
    assert transfer.from_instance_id == src.id
    assert transfer.to_instance_id == dst.id
    assert transfer.state == RegistrationTransfer.STATE_APPLIED


def test_execute_reassigns_place_number(world):
    """place_number унікальний у межах заходу, а assign_place_number
    ідемпотентний -- без знулення реєстрація приїхала б із чужим номером."""
    reg, src, dst, _, _ = world
    reg.place_number = 7
    db.session.commit()
    _execute(reg, dst)
    assert reg.place_number == 1


def test_execute_points_tariff_at_target(world):
    """tariff_id мусить вказувати на тариф ЦІЛЬОВОГО заходу, інакше
    лишається висяча вказівка на чужий тариф."""
    from app.models.instance_tariff import InstanceTariff
    reg, src, dst, _, _ = world
    tariff = InstanceTariff(instance_id=dst.id, name='Практикум', price=1500)
    db.session.add(tariff)
    db.session.commit()
    transfer = _execute(reg, dst, tariff=tariff, tariff_decision='keep')
    assert reg.tariff_id == tariff.id
    assert transfer.to_tariff_id == tariff.id
    assert transfer.new_amount == 1500


def test_execute_does_not_touch_money_or_promo(world):
    """payment_amount рухає лише payment_ops; перенесення не має анулювати
    вже надану знижку."""
    reg, src, dst, _, _ = world
    reg.discount_amount = 200
    db.session.commit()
    _execute(reg, dst)
    assert reg.payment_amount == 1000
    assert reg.discount_amount == 200
    assert reg.payment_status == 'paid'


def test_execute_snapshots_amounts(world):
    from app.models.instance_tariff import InstanceTariff
    reg, src, dst, _, _ = world
    tariff = InstanceTariff(instance_id=dst.id, name='Практикум', price=1500)
    db.session.add(tariff)
    db.session.commit()
    transfer = _execute(reg, dst, tariff=tariff)
    assert transfer.old_amount == 1000
    assert transfer.new_amount == 1500
    assert transfer.difference == 500
    # Знімок не переписується правкою тарифу заднім числом.
    tariff.price = 9999
    db.session.commit()
    assert transfer.new_amount == 1500


def test_execute_falls_back_to_instance_price_without_tariffs(world):
    reg, src, dst, _, _ = world
    transfer = _execute(reg, dst)
    assert transfer.new_amount == 1500
    assert transfer.difference == 500


def test_execute_normalises_empty_reason_and_note(world):
    """Порожні поля мусять бути NULL: лист вирішує за ними, чи рендерити
    блок, і '' дав би порожній заголовок."""
    reg, src, dst, _, _ = world
    transfer = _execute(reg, dst, reason='   ', note='')
    assert transfer.reason is None
    assert transfer.note is None


def test_execute_keeps_reason_and_note(world):
    reg, src, dst, _, _ = world
    transfer = _execute(reg, dst, reason='Тренер захворів', note='Місце те саме')
    assert transfer.reason == 'Тренер захворів'
    assert transfer.note == 'Місце те саме'


def test_execute_rejects_blocked_transfer(world):
    reg, src, dst, _, _ = world
    reg.status = 'cancelled'
    db.session.commit()
    with pytest.raises(ValueError):
        _execute(reg, dst)
    assert reg.instance_id == src.id


def test_execute_rejects_organizer_surcharge(world):
    """§3.2: перенесення з нашої ініціативи -- без додаткової оплати."""
    reg, src, dst, _, _ = world
    with pytest.raises(ValueError):
        _execute(reg, dst, initiator='organizer', tariff_decision='surcharge')
    assert reg.instance_id == src.id


def test_execute_rejects_refund_diff_on_pricier_tariff(world):
    """Інакше "повернути різницю" на дорожчому тарифі тихо не зробило б
    нічого, а адмін був би певен, що заявку заведено."""
    reg, src, dst, _, _ = world  # dst дорожчий: 1500 проти сплачених 1000
    with pytest.raises(ValueError):
        _execute(reg, dst, tariff_decision='refund_diff')
    assert reg.instance_id == src.id


def test_execute_rejects_surcharge_on_cheaper_tariff(world):
    from app.models.instance_tariff import InstanceTariff
    reg, src, dst, _, _ = world
    tariff = InstanceTariff(instance_id=dst.id, name='Онлайн', price=600)
    db.session.add(tariff)
    db.session.commit()
    with pytest.raises(ValueError):
        _execute(reg, dst, tariff=tariff, tariff_decision='surcharge')
    assert reg.instance_id == src.id


def test_execute_announced_issues_token(world, monkeypatch):
    sent = []
    monkeypatch.setattr(
        'app.services.email_service.EmailService.send_transfer_offer',
        staticmethod(lambda transfer: sent.append(transfer)),
    )
    reg, src, dst, _, _ = world
    transfer = _execute(reg, dst, announced=True)
    assert transfer.state == RegistrationTransfer.STATE_AWAITING
    assert transfer.consent_token_active is True
    assert sent == [transfer]


def test_execute_silent_sends_nothing(world, monkeypatch):
    sent = []
    monkeypatch.setattr(
        'app.services.email_service.EmailService.send_transfer_offer',
        staticmethod(lambda transfer: sent.append(transfer)),
    )
    reg, src, dst, _, _ = world
    transfer = _execute(reg, dst, announced=False)
    assert transfer.state == RegistrationTransfer.STATE_APPLIED
    assert transfer.consent_token is None
    assert sent == []
```

- [ ] **Step 2: Запустити — нові тести мають упасти**

Run: `python -m pytest tests/test_services/test_transfer_service.py -v -k execute`
Expected: FAIL — `AttributeError: module 'app.services.transfer_service' has no attribute 'execute'`

- [ ] **Step 3: Написати `execute`**

Дописати в `app/services/transfer_service.py` (імпорти — до наявного блоку імпортів угорі файла):

```python
from decimal import Decimal

from app.extensions import db
from app.models.registration_transfer import (
    DECISION_SURCHARGE, INITIATOR_ORGANIZER,
)
from app.services import registration_service

audit_logger = logging.getLogger('audit')


def _money(value):
    return Decimal(str(value or 0))


def _clean(text, limit):
    """Порожній рядок -> None: лист вирішує за NULL, чи рендерити блок."""
    text = (text or '').strip()
    return text[:limit] if text else None


def execute(registration, *, target_instance, initiator, tariff=None,
            tariff_decision='keep', reason=None, note=None, announced=False,
            admin_user=None):
    """Перенести реєстрацію. Комітить.

    Переїзд негайний і для тихого, і для голосного режиму: людину, яку ми
    перенесли, не можна лишати на заході, якого не буде, поки вона не
    відповість на лист. Згода лише підтверджує вже здійснений переїзд.
    """
    problems = check(registration, target_instance)
    if problems:
        raise ValueError(problems)

    if (initiator == INITIATOR_ORGANIZER
            and tariff_decision == DECISION_SURCHARGE):
        # Дублює CHECK у БД -- свідомо: сервіс має відмовити зрозумілим
        # текстом, а не IntegrityError на коміті.
        raise ValueError([
            'Перенесення з ініціативи Організатора не допускає доплати '
            '(§3.2 Політики)'
        ])

    from_instance_id = registration.instance_id
    old_amount = _money(registration.payment_amount)
    if tariff is not None:
        new_amount = _money(tariff.price)
    else:
        new_amount = _money(target_instance.price)

    difference = new_amount - old_amount
    # Напрямок різниці мусить відповідати рішенню, інакше "повернути
    # різницю" на ДОРОЖЧОМУ тарифі тихо не зробило б нічого, а адмін був би
    # певен, що заявку заведено.
    if tariff_decision == 'refund_diff' and difference >= 0:
        raise ValueError([
            'Повертати нічого: новий тариф не дешевший за сплачену суму'
        ])
    if tariff_decision == DECISION_SURCHARGE and difference <= 0:
        raise ValueError([
            'Доплачувати нічого: новий тариф не дорожчий за сплачену суму'
        ])

    # Знулення обов'язкове: assign_place_number ідемпотентний і на
    # заповненому номері одразу поверне старий -- реєстрація приїхала б на
    # новий захід із чужим номером, порушивши uq_registrations_instance_place.
    registration.place_number = None
    registration.instance_id = target_instance.id
    registration.tariff_id = tariff.id if tariff is not None else None

    if (registration.payment_status == 'paid'
            and registration.status != 'cancelled'):
        try:
            registration_service.assign_place_number(registration)
        except Exception:
            logger.exception(
                'Failed to assign place_number for REG-%s after transfer',
                registration.id,
            )

    transfer = RegistrationTransfer(
        registration_id=registration.id,
        from_instance_id=from_instance_id,
        to_instance_id=target_instance.id,
        initiator=initiator,
        announced=bool(announced),
        reason=_clean(reason, 500),
        note=_clean(note, 5000),
        tariff_decision=tariff_decision,
        to_tariff_id=tariff.id if tariff is not None else None,
        old_amount=old_amount,
        new_amount=new_amount,
        difference=difference,
        state=(RegistrationTransfer.STATE_AWAITING if announced
               else RegistrationTransfer.STATE_APPLIED),
        created_by_id=admin_user.id if admin_user is not None else None,
    )
    if announced:
        transfer.issue_consent_token()
    db.session.add(transfer)
    db.session.commit()

    audit_logger.info(
        'Transfer #%s: REG-%s moved %s -> %s by %s (%s, %s, diff %s)',
        transfer.id, registration.id, from_instance_id, target_instance.id,
        admin_user.email if admin_user is not None else 'system',
        initiator, tariff_decision, transfer.difference,
    )

    if announced:
        # Best-effort: збій пошти не має скасовувати вже здійснений переїзд.
        # Посилання лишається в адмінці, лист можна надіслати повторно.
        from app.services.email_service import EmailService
        try:
            EmailService.send_transfer_offer(transfer)
        except Exception:
            logger.exception(
                'Failed to queue transfer offer for #%s', transfer.id)

    return transfer
```

- [ ] **Step 4: Додати заглушку `send_transfer_offer`**

Повний лист — Task 7. Щоб `execute` не падав уже зараз, додати в `app/services/email_service.py`, у клас `EmailService`, поруч із `send_refund_request_received`:

```python
    @staticmethod
    def send_transfer_offer(transfer):
        """Лист-пропозиція при перенесенні. Реалізація -- окремим кроком."""
        return None
```

- [ ] **Step 5: Прогнати тести**

Run: `python -m pytest tests/test_services/test_transfer_service.py -v`
Expected: усі тести PASS — 13 із Task 2 плюс 14 нових, разом 27.

- [ ] **Step 6: Commit**

```bash
git add app/services/transfer_service.py app/services/email_service.py \
        tests/test_services/test_transfer_service.py
git commit -m "feat(перенесення): виконання переносу зі знімками сум"
```

---

### Task 4: Заявки на повернення й відповіді учасника

**Files:**
- Modify: `app/services/transfer_service.py`
- Test: `tests/test_services/test_transfer_service.py`

**Interfaces:**
- Consumes: `execute()` з Task 3; `refund_policy.quote_registration(reg)`; `RefundRequest` зі `STATUS_NEW`.
- Produces:
  - `accept(transfer) -> (bool, str)` — комітить
  - `request_refund(transfer, reason, payout_details=None) -> (RefundRequest | None, str | None)` — комітить
  - `_open_refund_request(transfer, amount, reason, quoted_code, percent=None) -> RefundRequest`
  - `execute()` при `tariff_decision='refund_diff'` заводить заявку й заповнює `transfer.refund_request_id`

- [ ] **Step 1: Дописати тести**

Додати в кінець `tests/test_services/test_transfer_service.py`:

```python
def test_refund_diff_opens_request_for_absolute_difference(world):
    """Новий тариф дешевший -- заявка на модуль різниці, гроші рухає адмін."""
    from app.models.instance_tariff import InstanceTariff
    from app.models.refund_request import RefundRequest, STATUS_NEW
    reg, src, dst, _, _ = world
    tariff = InstanceTariff(instance_id=dst.id, name='Онлайн', price=600)
    db.session.add(tariff)
    db.session.commit()
    transfer = _execute(reg, dst, tariff=tariff, tariff_decision='refund_diff')
    request = RefundRequest.query.get(transfer.refund_request_id)
    assert request is not None
    assert request.status == STATUS_NEW
    assert request.quoted_amount == 400
    assert reg.payment_amount == 1000  # гроші ще не рухались


def test_accept_confirms_registration(world, monkeypatch):
    monkeypatch.setattr(
        'app.services.email_service.EmailService.send_transfer_offer',
        staticmethod(lambda transfer: None),
    )
    reg, src, dst, _, _ = world
    reg.status = 'pending'
    db.session.commit()
    transfer = _execute(reg, dst, announced=True)
    ok, _msg = transfer_service.accept(transfer)
    assert ok is True
    assert transfer.state == RegistrationTransfer.STATE_ACCEPTED
    assert transfer.responded_at is not None
    assert reg.status == 'confirmed'


def test_accept_is_idempotent(world, monkeypatch):
    monkeypatch.setattr(
        'app.services.email_service.EmailService.send_transfer_offer',
        staticmethod(lambda transfer: None),
    )
    reg, src, dst, _, _ = world
    transfer = _execute(reg, dst, announced=True)
    transfer_service.accept(transfer)
    first_response = transfer.responded_at
    ok, _msg = transfer_service.accept(transfer)
    assert ok is False
    assert transfer.responded_at == first_response


def test_organizer_refund_is_full_amount(world, monkeypatch):
    """§3.2: перенесли ми -- повертаємо 100%, а не сітку §4.1."""
    monkeypatch.setattr(
        'app.services.email_service.EmailService.send_transfer_offer',
        staticmethod(lambda transfer: None),
    )
    reg, src, dst, _, _ = world
    transfer = _execute(reg, dst, initiator='organizer', announced=True)
    request, err = transfer_service.request_refund(transfer, 'Не підходить дата')
    assert err is None
    assert request.quoted_percent == 100
    assert request.quoted_amount == 1000
    assert request.quoted_code == 'transfer_organizer'
    assert transfer.state == RegistrationTransfer.STATE_REFUND_REQUESTED


def test_participant_refund_uses_policy_grid(world, monkeypatch):
    """§4.1: відмова за власною ініціативою -- за сіткою. Захід через 20
    днів, тож сходинка 'early' = 100%; на 5-й день була б 50%."""
    monkeypatch.setattr(
        'app.services.email_service.EmailService.send_transfer_offer',
        staticmethod(lambda transfer: None),
    )
    reg, src, dst, _, _ = world
    dst.start_date = utcnow() + timedelta(days=5)
    db.session.commit()
    transfer = _execute(reg, dst, initiator='participant', announced=True)
    request, err = transfer_service.request_refund(transfer, 'Передумав')
    assert err is None
    assert request.quoted_percent == 50
    assert request.quoted_code == 'standard'


def test_second_refund_updates_open_request(world, monkeypatch):
    """uq_refund_requests_open_registration дозволяє ОДНУ відкриту заявку.
    Сценарій "перенесли з поверненням різниці -> учасник просить усе назад"
    інакше падає IntegrityError рівно в момент кліку учасника."""
    from app.models.instance_tariff import InstanceTariff
    from app.models.refund_request import RefundRequest
    monkeypatch.setattr(
        'app.services.email_service.EmailService.send_transfer_offer',
        staticmethod(lambda transfer: None),
    )
    reg, src, dst, _, _ = world
    tariff = InstanceTariff(instance_id=dst.id, name='Онлайн', price=600)
    db.session.add(tariff)
    db.session.commit()
    transfer = _execute(reg, dst, tariff=tariff, initiator='organizer',
                        tariff_decision='refund_diff', announced=True)
    assert RefundRequest.query.filter_by(registration_id=reg.id).count() == 1

    request, err = transfer_service.request_refund(transfer, 'Хочу все назад')
    assert err is None
    assert RefundRequest.query.filter_by(registration_id=reg.id).count() == 1
    assert request.quoted_amount == 1000
    assert 'Хочу все назад' in request.reason


def test_request_refund_is_idempotent(world, monkeypatch):
    monkeypatch.setattr(
        'app.services.email_service.EmailService.send_transfer_offer',
        staticmethod(lambda transfer: None),
    )
    reg, src, dst, _, _ = world
    transfer = _execute(reg, dst, announced=True)
    transfer_service.request_refund(transfer, 'Причина')
    _second, err = transfer_service.request_refund(transfer, 'Ще раз')
    assert err is not None
```

- [ ] **Step 2: Запустити — має впасти**

Run: `python -m pytest tests/test_services/test_transfer_service.py -v -k "refund or accept"`
Expected: FAIL — `AttributeError: module ... has no attribute 'accept'`

- [ ] **Step 3: Реалізувати міст до заявок**

Дописати в `app/services/transfer_service.py` (імпорти — у блок угорі):

```python
from app.models.refund_request import RefundRequest, STATUS_NEW
from app.services import refund_policy

MAX_REASON = 2000
MAX_PAYOUT = 500


def _open_refund_request(transfer, amount, reason, quoted_code, percent=None):
    """Завести (або оновити) заявку на повернення від імені перенесення.

    Партіальний унікальний індекс uq_refund_requests_open_registration
    дозволяє ОДНУ відкриту заявку на реєстрацію. Тож коли на різницю тарифу
    вже висить заявка, а учасник просить повернути все, ми ОНОВЛЮЄМО її, а
    не створюємо другу: інакше сценарій падає IntegrityError рівно в момент
    кліку учасника.

    Не комітить -- caller відповідає за commit.
    """
    reg = transfer.registration
    existing = RefundRequest.query.filter_by(
        registration_id=reg.id, status=STATUS_NEW,
    ).first()

    reason = (reason or '').strip()[:MAX_REASON]

    if existing is not None:
        existing.reason = reason
        existing.quoted_amount = amount
        existing.quoted_percent = percent
        existing.quoted_code = quoted_code
        return existing

    item = RefundRequest(
        registration_id=reg.id,
        enrollment_id=None,
        user_id=reg.user_id,
        reason=reason,
        quoted_percent=percent,
        quoted_amount=amount,
        quoted_code=quoted_code,
    )
    db.session.add(item)
    db.session.flush()
    return item


def accept(transfer):
    """Учасник погодився на перенесення. Комітить.

    Ідемпотентно за станом: повторний POST із тієї ж сторінки (або
    подвійний клік) не має переписувати дату відповіді.
    """
    if not transfer.is_open:
        return False, 'Ви вже відповіли на цю пропозицію'

    transfer.state = RegistrationTransfer.STATE_ACCEPTED
    transfer.responded_at = utcnow()
    reg = transfer.registration
    if reg is not None and reg.status == 'pending':
        reg.status = 'confirmed'
    db.session.commit()

    audit_logger.info('Transfer #%s accepted by participant', transfer.id)
    return True, 'Дякуємо, участь підтверджено'


def request_refund(transfer, reason, payout_details=None):
    """Учасник обрав повернення коштів замість перенесення. Комітить.

    Сума залежить від того, ЧИЯ була ініціатива:
    * organizer   -- 100% сплаченого (§3.2), бо перенесли ми;
    * participant -- сітка §4.1 через refund_policy.
    """
    if not transfer.is_open:
        return None, 'Ви вже відповіли на цю пропозицію'

    reg = transfer.registration
    if reg is None:
        return None, 'Реєстрацію не знайдено'

    if transfer.initiator == INITIATOR_ORGANIZER:
        percent = 100
        amount = _money(reg.payment_amount)
        code = 'transfer_organizer'
    else:
        quote = refund_policy.quote_registration(reg)
        percent = quote.percent
        amount = quote.amount
        code = quote.code

    item = _open_refund_request(transfer, amount, reason, code, percent)
    if payout_details:
        item.payout_details = payout_details.strip()[:MAX_PAYOUT] or None

    transfer.state = RegistrationTransfer.STATE_REFUND_REQUESTED
    transfer.responded_at = utcnow()
    transfer.refund_request_id = item.id
    db.session.commit()

    audit_logger.info(
        'Transfer #%s: participant requested refund, request #%s (%s%%, %s)',
        transfer.id, item.id, percent, amount,
    )

    from app.services.email_service import EmailService
    try:
        EmailService.send_refund_request_notification(item)
    except Exception:
        logger.exception(
            'Failed to notify admins about refund request #%s', item.id)

    return item, None
```

- [ ] **Step 4: Підключити `refund_diff` до `execute`**

У `execute`, ПІСЛЯ `db.session.add(transfer)` і ПЕРЕД `db.session.commit()`, вставити:

```python
    if tariff_decision == 'refund_diff' and transfer.difference < 0:
        db.session.flush()  # transfer.id потрібен для аудиту заявки
        request = _open_refund_request(
            transfer,
            amount=abs(transfer.difference),
            reason=(f'Різниця тарифів при перенесенні на '
                    f'{target_instance.course.title if target_instance.course else "інший захід"}'),
            quoted_code='transfer_diff',
            percent=None,
        )
        transfer.refund_request_id = request.id
```

- [ ] **Step 5: Прогнати всі тести сервісу**

Run: `python -m pytest tests/test_services/test_transfer_service.py -v`
Expected: усі тести PASS — 27 попередніх плюс 7 нових, разом 34.

- [ ] **Step 6: Прогнати сусідні набори — переконатись, що черга заявок не зламана**

Run: `python -m pytest tests/test_services -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add app/services/transfer_service.py tests/test_services/test_transfer_service.py
git commit -m "feat(перенесення): заявки на повернення й відповіді учасника"
```

---

### Task 5: Компонент `modal` у дизайн-системі

**Files:**
- Create: `app/static/css/modal.css`
- Create: `app/static/js/modal.js`
- Modify: `app/templates/design_system/_tab_molecules.html`
- Modify: `app/templates/admin/design_system.html`

**Interfaces:**
- Consumes: токени `common.css`.
- Produces: класи `.modal`, `.modal__backdrop`, `.modal__dialog`, `.modal__head`, `.modal__title`, `.modal__close`, `.modal__body`, `.modal__foot`; API `window.IprmModal.open(id)` / `.close(id)`; атрибути `data-modal-open="<id>"`, `data-modal-close`.

- [ ] **Step 1: Написати CSS компонента**

Створити `app/static/css/modal.css`. Компонентний файл, не `page-*`: за правилом дизайн-системи клас, оголошений посторінково, невидимий для наступної сторінки. Токени беруться з `common.css`; жодних власних значень кольору.

```css
/* modal.css — модальне вікно з довільним вмістом. Парний до modal.js.

   Чому окремо від .iprm-confirm: той приймає лише текст і дві кнопки, і
   форма всередині нього ламає його ж розмітку. Чому не всередині
   page-*.css: компонент, оголошений посторінково, невидимий для наступної
   сторінки — і наступний розробник напише його заново. */

.modal {
  position: fixed;
  inset: 0;
  z-index: 10002;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
}

/* display:flex вище за UA [hidden]{display:none} за порядком джерел, тож
   ховаємо явно — інакше лишається невидимий перехоплювач кліків. */
.modal[hidden] { display: none; }

.modal__backdrop {
  position: absolute;
  inset: 0;
  background: rgba(20, 16, 40, 0.45);
  backdrop-filter: blur(2px);
  -webkit-backdrop-filter: blur(2px);
}

.modal__dialog {
  position: relative;
  width: min(640px, 100%);
  max-height: calc(100vh - 48px);
  display: flex;
  flex-direction: column;
  background: var(--iprm-surface);
  color: var(--iprm-text);
  border-radius: var(--iprm-radius-lg);
  box-shadow: var(--iprm-shadow-lg);
}

.modal__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 20px 24px 12px;
}

.modal__title {
  margin: 0;
  font-size: 1.125rem;
  font-weight: 600;
}

.modal__close {
  border: 0;
  background: none;
  color: var(--iprm-text-muted);
  font-size: 1.5rem;
  line-height: 1;
  cursor: pointer;
  padding: 4px 8px;
  border-radius: var(--iprm-radius-sm);
}

.modal__close:hover { color: var(--iprm-text); }

.modal__body {
  padding: 0 24px;
  overflow-y: auto;
}

.modal__foot {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  padding: 16px 24px 20px;
}

@media (max-width: 640px) {
  .modal { padding: 12px; }
  .modal__dialog { max-height: calc(100vh - 24px); }
  .modal__foot { flex-direction: column-reverse; }
  .modal__foot > * { width: 100%; }
}
```

**Перед написанням звірити імена токенів** із `app/static/css/common.css`: якщо `--iprm-surface`, `--iprm-text`, `--iprm-text-muted`, `--iprm-radius-lg`, `--iprm-radius-sm`, `--iprm-shadow-lg` називаються інакше — використати наявні імена, а не заводити нові. Захардкоджених кольорів не лишати: пам'ять проєкту фіксує пастку з `--iprm-white` у тёмній темі.

- [ ] **Step 2: Написати JS компонента**

Створити `app/static/js/modal.js`:

```javascript
/* modal.js — відкриття/закриття модалок. Парний до modal.css.

   Розмітка декларативна: кнопка з data-modal-open="<id>" відкриває
   #<id>; будь-який елемент із data-modal-close усередині закриває його.
   Так сторінці не потрібен власний скрипт лише заради показу вікна. */
(function () {
  'use strict';

  var lastTrigger = null;

  function open(id) {
    var el = document.getElementById(id);
    if (!el) { return; }
    el.hidden = false;
    document.body.style.overflow = 'hidden';
    var focusable = el.querySelector(
      'input:not([type=hidden]), select, textarea, button'
    );
    if (focusable) { focusable.focus(); }
  }

  function close(id) {
    var el = document.getElementById(id);
    if (!el) { return; }
    el.hidden = true;
    document.body.style.overflow = '';
    // Фокус назад на кнопку, що відкривала: без цього клавіатурний
    // користувач після Esc опиняється на початку сторінки.
    if (lastTrigger) { lastTrigger.focus(); lastTrigger = null; }
  }

  document.addEventListener('click', function (event) {
    var opener = event.target.closest('[data-modal-open]');
    if (opener) {
      lastTrigger = opener;
      open(opener.getAttribute('data-modal-open'));
      return;
    }
    var closer = event.target.closest('[data-modal-close]');
    if (closer) {
      var host = closer.closest('.modal');
      if (host) { close(host.id); }
    }
  });

  document.addEventListener('keydown', function (event) {
    if (event.key !== 'Escape') { return; }
    var openModal = document.querySelector('.modal:not([hidden])');
    if (openModal) { close(openModal.id); }
  });

  window.IprmModal = { open: open, close: close };
})();
```

- [ ] **Step 3: Показати компонент у каталозі**

У `app/templates/admin/design_system.html`, у блоці `extra_css`, серед спільних компонентів САЙТУ (не адмінки) додати рядок, зберігши наявний коментований порядок підключення:

```html
<link rel="stylesheet" href="{{ url_for('static', filename='css/modal.css') }}?v={{ assets_version }}">
```

У блок `extra_scripts` того ж файла:

```html
<script src="{{ url_for('static', filename='js/modal.js') }}?v={{ assets_version }}" defer></script>
```

У `app/templates/design_system/_tab_molecules.html` додати секцію в кінець, повторивши структуру сусідніх секцій цього файла (спершу прочитати файл і взяти наявну обгортку — заголовок, опис, демо-область):

```html
<h3>Модальне вікно</h3>
<p>Вікно з довільним вмістом — форма, список, підтвердження зі складнішим
   поясненням. Для простого «так/ні» лишається <code>.iprm-confirm</code>.</p>
<button type="button" class="btn-admin btn-admin--secondary" data-modal-open="ds-modal-demo">
  Відкрити модалку
</button>
<div class="modal" id="ds-modal-demo" hidden>
  <div class="modal__backdrop" data-modal-close></div>
  <div class="modal__dialog" role="dialog" aria-modal="true" aria-labelledby="ds-modal-demo-title">
    <div class="modal__head">
      <h3 class="modal__title" id="ds-modal-demo-title">Заголовок вікна</h3>
      <button type="button" class="modal__close" data-modal-close aria-label="Закрити">&times;</button>
    </div>
    <div class="modal__body">
      <p>Тіло вікна прокручується, якщо вміст не вміщається.</p>
    </div>
    <div class="modal__foot">
      <button type="button" class="btn-admin btn-admin--secondary" data-modal-close>Скасувати</button>
      <button type="button" class="btn-admin btn-admin--primary">Підтвердити</button>
    </div>
  </div>
</div>
```

- [ ] **Step 4: Перевірити сторожів дизайн-системи**

Run:
```bash
python -m pytest tests/test_design_system -v
python tools/ds/ds_audit.py
```
Expected: тести PASS; аудит не повідомляє про клас, оголошений у двох файлах.

- [ ] **Step 5: Переконатись, що каталог рендериться**

Run: `python -m pytest tests/test_routes -q -k design`
Expected: PASS. Якщо тесту на каталог немає — відкрити `/admin/design-system` через тестовий клієнт і переконатись, що відповідь 200 і містить `ds-modal-demo`.

- [ ] **Step 6: Commit**

```bash
git add app/static/css/modal.css app/static/js/modal.js \
        app/templates/design_system/_tab_molecules.html \
        app/templates/admin/design_system.html
git commit -m "feat(дизайн-система): компонент модального вікна"
```

---

### Task 6: Роути адмінки й модалка перенесення

**Files:**
- Modify: `app/admin/routes_registrations.py`
- Create: `app/templates/admin/partials/_transfer_modal.html`
- Create: `app/static/js/admin-transfer.js`
- Modify: `app/templates/admin/partials/_registration_actions.html`
- Modify: `app/templates/admin/instance_registrations.html`
- Modify: `app/templates/admin/registrations.html`
- Test: `tests/test_routes/test_admin_transfer.py`

**Interfaces:**
- Consumes: `transfer_service.check/eligible_instances/execute` (Tasks 2–4); компонент `modal` (Task 5).
- Produces: ендпоінти `admin.registration_transfer_options` (`GET /admin/registrations/<int:reg_id>/transfer/options`) і `admin.registration_transfer` (`POST /admin/registrations/<int:reg_id>/transfer`).

- [ ] **Step 1: Написати тести роутів**

Створити `tests/test_routes/test_admin_transfer.py`. Спосіб автентифікації адміна брати з наявних тестів у `tests/test_routes/` — прочитати сусідній файл і повторити його фікстуру логіну, а не вигадувати свою.

```python
"""Роути перенесення в адмінці."""
from datetime import timedelta

import pytest

from app.extensions import db
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.mixins import utcnow
from app.models.registration import EventRegistration
from app.models.user import User
from tests.refund_fixtures import purge

PREFIX = 'rta-'


@pytest.fixture
def world(app):
    admin = User(email=f'{PREFIX}admin@example.com', first_name='Адмін',
                 last_name='Тестовий', is_active=True, is_admin=True)
    admin.set_password('x' * 12)
    user = User(email=f'{PREFIX}one@example.com', first_name='Тест',
                last_name='Переносний', is_active=True)
    user.set_password('x' * 12)
    course = Course(title='Курс переносу', slug=f'{PREFIX}course')
    db.session.add_all([admin, user, course])
    db.session.flush()
    now = utcnow()
    src = CourseInstance(course_id=course.id, status='published',
                         start_date=now + timedelta(days=10), price=1000)
    dst = CourseInstance(course_id=course.id, status='published',
                         start_date=now + timedelta(days=20), price=1500)
    soon = CourseInstance(course_id=course.id, status='published',
                          start_date=now + timedelta(hours=12), price=1500)
    db.session.add_all([src, dst, soon])
    db.session.flush()
    reg = EventRegistration(
        user_id=user.id, instance_id=src.id, phone='+380000000000',
        specialty='Лікар', workplace='Клініка', status='confirmed',
        payment_status='paid', payment_amount=1000,
    )
    db.session.add(reg)
    db.session.commit()
    yield {'admin': admin, 'reg': reg, 'src': src, 'dst': dst, 'soon': soon}
    purge(PREFIX, slug_prefix=PREFIX)


def test_options_requires_admin(client, world):
    resp = client.get(f"/admin/registrations/{world['reg'].id}/transfer/options")
    assert resp.status_code in (302, 401, 403)


def test_options_lists_only_eligible(client, world, login_admin):
    login_admin(world['admin'])
    resp = client.get(f"/admin/registrations/{world['reg'].id}/transfer/options")
    assert resp.status_code == 200
    ids = [row['id'] for row in resp.get_json()['instances']]
    assert world['dst'].id in ids
    assert world['src'].id not in ids
    assert world['soon'].id not in ids  # менше 2 діб


def test_options_reports_blockers(client, world, login_admin):
    login_admin(world['admin'])
    world['reg'].status = 'cancelled'
    db.session.commit()
    resp = client.get(f"/admin/registrations/{world['reg'].id}/transfer/options")
    data = resp.get_json()
    assert data['instances'] == []
    assert data['problems']


def test_transfer_moves_registration(client, world, login_admin):
    login_admin(world['admin'])
    reg = world['reg']
    resp = client.post(f'/admin/registrations/{reg.id}/transfer', data={
        'instance_id': world['dst'].id,
        'initiator': 'participant',
        'tariff_decision': 'keep',
        'reason': 'Прохання учасника',
    }, follow_redirects=True)
    assert resp.status_code == 200
    db.session.refresh(reg)
    assert reg.instance_id == world['dst'].id


def test_transfer_rejects_organizer_surcharge(client, world, login_admin):
    """§3.2 має відбиватись і роутом, а не лише CHECK-ом БД."""
    login_admin(world['admin'])
    reg = world['reg']
    client.post(f'/admin/registrations/{reg.id}/transfer', data={
        'instance_id': world['dst'].id,
        'initiator': 'organizer',
        'tariff_decision': 'surcharge',
    }, follow_redirects=True)
    db.session.refresh(reg)
    assert reg.instance_id == world['src'].id


def test_transfer_rejects_blocked(client, world, login_admin):
    login_admin(world['admin'])
    reg = world['reg']
    client.post(f'/admin/registrations/{reg.id}/transfer', data={
        'instance_id': world['soon'].id,
        'initiator': 'participant',
        'tariff_decision': 'keep',
    }, follow_redirects=True)
    db.session.refresh(reg)
    assert reg.instance_id == world['src'].id
```

Якщо у `tests/test_routes/` немає фікстури `login_admin` — створити її локально у цьому файлі, повторивши спосіб логіну з сусіднього тесту адмінки:

```python
@pytest.fixture
def login_admin(client):
    def _login(admin):
        with client.session_transaction() as sess:
            sess['_user_id'] = str(admin.id)
            sess['_fresh'] = True
    return _login
```

- [ ] **Step 2: Запустити — має впасти**

Run: `python -m pytest tests/test_routes/test_admin_transfer.py -v`
Expected: FAIL — 404 на обох роутах.

- [ ] **Step 3: Додати роути**

Дописати в кінець `app/admin/routes_registrations.py` (імпорти — у блок угорі файла):

```python
@admin_bp.route('/registrations/<int:reg_id>/transfer/options')
@admin_required
def registration_transfer_options(reg_id):
    """Дані для модалки перенесення: придатні заходи, тарифи, різниці.

    Арифметика грошей рахується ТУТ, а не в JS: інакше сума в модалці й
    сума в листі одного дня розійдуться, і дізнаємось ми про це від
    учасника.
    """
    from app.services import transfer_service

    reg = EventRegistration.query.get_or_404(reg_id)
    problems = transfer_service.check(reg)
    paid = Decimal(str(reg.payment_amount or 0))

    instances = []
    for item in transfer_service.eligible_instances(reg):
        tariffs = [
            {
                'id': t.id,
                'name': t.name,
                'price': float(t.price or 0),
                'difference': float(Decimal(str(t.price or 0)) - paid),
            }
            for t in item.tariffs if t.is_active
        ]
        instances.append({
            'id': item.id,
            'title': item.course.title if item.course else 'Захід',
            'start_date': (item.start_date.strftime('%d.%m.%Y')
                           if item.start_date else ''),
            'location': item.location or '',
            'price': float(item.price or 0),
            'difference': float(Decimal(str(item.price or 0)) - paid),
            'tariffs': tariffs,
        })

    return jsonify({
        'paid': float(paid),
        'problems': problems,
        'instances': instances,
    })


@admin_bp.route('/registrations/<int:reg_id>/transfer', methods=['POST'])
@admin_required
def registration_transfer(reg_id):
    """Перенести реєстрацію на інше проведення."""
    from app.models.instance_tariff import InstanceTariff
    from app.services import transfer_service

    reg = EventRegistration.query.get_or_404(reg_id)
    target = CourseInstance.query.get(
        request.form.get('instance_id', type=int) or 0)
    if target is None:
        flash('Оберіть захід, на який переносимо', 'error')
        return _redirect_after_action(reg)

    tariff = None
    tariff_id = request.form.get('tariff_id', type=int)
    if tariff_id:
        tariff = InstanceTariff.query.filter_by(
            id=tariff_id, instance_id=target.id).first()
        if tariff is None:
            flash('Обраний тариф не належить цьому заходу', 'error')
            return _redirect_after_action(reg)

    try:
        transfer = transfer_service.execute(
            reg,
            target_instance=target,
            initiator=request.form.get('initiator', 'participant'),
            tariff=tariff,
            tariff_decision=request.form.get('tariff_decision', 'keep'),
            reason=request.form.get('reason'),
            note=request.form.get('note'),
            announced=bool(request.form.get('announced')),
            admin_user=current_user,
        )
    except ValueError as exc:
        for problem in exc.args[0]:
            flash(problem, 'error')
        return _redirect_after_action(reg)

    if transfer.announced:
        flash('Учасника перенесено, лист із вибором надіслано', 'success')
    else:
        flash('Учасника перенесено', 'success')
    return _redirect_after_action(reg)
```

Переконатись, що на початку файла є `from decimal import Decimal`, `from flask import jsonify, request, flash`, `from flask_login import current_user`, `from app.models.course_instance import CourseInstance` — додати те, чого бракує, у наявні групи імпортів.

- [ ] **Step 4: Прогнати тести роутів**

Run: `python -m pytest tests/test_routes/test_admin_transfer.py -v`
Expected: усі 6 PASS.

- [ ] **Step 5: Створити розмітку модалки**

Створити `app/templates/admin/partials/_transfer_modal.html`:

```html
{# Модалка перенесення. Один екземпляр на сторінку: список заходів і
   тарифів довантажується під конкретну реєстрацію з
   admin.registration_transfer_options, тож копіювати розмітку в кожен
   рядок таблиці немає потреби. #}
<div class="modal" id="transfer-modal" hidden>
  <div class="modal__backdrop" data-modal-close></div>
  <div class="modal__dialog" role="dialog" aria-modal="true" aria-labelledby="transfer-modal-title">
    <div class="modal__head">
      <h3 class="modal__title" id="transfer-modal-title">Перенести учасника</h3>
      <button type="button" class="modal__close" data-modal-close aria-label="Закрити">&times;</button>
    </div>

    <form method="POST" id="transfer-form" data-options-url-template="{{ url_for('admin.registration_transfer_options', reg_id=0) }}">
      <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
      <input type="hidden" name="next" value="{{ back_url }}">

      <div class="modal__body">
        <div class="admin-alert admin-alert--danger" id="transfer-problems" hidden></div>

        <div class="admin-form-group">
          <label class="admin-label" for="transfer-instance">Перенести на захід</label>
          <select class="admin-input" name="instance_id" id="transfer-instance" required></select>
        </div>

        <div class="admin-form-group" id="transfer-tariff-group" hidden>
          <label class="admin-label" for="transfer-tariff">Тариф на новому заході</label>
          <select class="admin-input" name="tariff_id" id="transfer-tariff"></select>
        </div>

        <div class="admin-form-group">
          <label class="admin-label" for="transfer-initiator">Ініціатива</label>
          <select class="admin-input" name="initiator" id="transfer-initiator">
            <option value="organizer">З ініціативи Організатора</option>
            <option value="participant" selected>На прохання учасника</option>
          </select>
          <p class="admin-hint" id="transfer-initiator-hint"></p>
        </div>

        <div class="admin-form-group">
          <label class="admin-label" for="transfer-decision">Різниця тарифів</label>
          <select class="admin-input" name="tariff_decision" id="transfer-decision">
            <option value="keep" selected>Лишити суму як є</option>
            <option value="refund_diff">Повернути різницю</option>
            <option value="surcharge">Запросити доплату різниці</option>
          </select>
          <p class="admin-hint" id="transfer-difference"></p>
        </div>

        <div class="admin-form-group">
          <label class="admin-label" for="transfer-reason">Причина переносу</label>
          <input type="text" class="admin-input" name="reason" id="transfer-reason"
                 maxlength="500" placeholder="Не обов'язково">
          <p class="admin-hint">Якщо порожньо — у листі блок не показується.</p>
        </div>

        <div class="admin-form-group">
          <label class="admin-label" for="transfer-note">Примітка для учасника</label>
          <textarea class="admin-input" name="note" id="transfer-note" rows="3"
                    placeholder="Не обов'язково"></textarea>
        </div>

        <div class="admin-form-group">
          <label class="admin-checkbox">
            <input type="checkbox" name="announced" value="1" id="transfer-announced">
            Сповістити учасника листом із вибором «погодитись / повернути кошти»
          </label>
        </div>
      </div>

      <div class="modal__foot">
        <button type="button" class="btn-admin btn-admin--secondary" data-modal-close>Скасувати</button>
        <button type="submit" class="btn-admin btn-admin--primary" id="transfer-submit">Перенести</button>
      </div>
    </form>
  </div>
</div>
```

Імена класів форми (`admin-form-group`, `admin-label`, `admin-input`, `admin-hint`, `admin-alert`, `admin-checkbox`) **звірити з наявними шаблонами адмінки** — узяти ті, що вже вживаються, а не заводити нові. Якщо якогось немає — використати найближчий наявний.

- [ ] **Step 6: Написати скрипт модалки**

Створити `app/static/js/admin-transfer.js`:

```javascript
/* admin-transfer.js — заповнення модалки перенесення.

   Скрипт нічого не рахує: суми й різниці приходять з
   /admin/registrations/<id>/transfer/options уже порахованими на сервері.
   Інакше сума в модалці й сума в листі одного дня розійдуться. */
(function () {
  'use strict';

  var form = document.getElementById('transfer-form');
  if (!form) { return; }

  var instanceSelect = document.getElementById('transfer-instance');
  var tariffGroup = document.getElementById('transfer-tariff-group');
  var tariffSelect = document.getElementById('transfer-tariff');
  var initiatorSelect = document.getElementById('transfer-initiator');
  var initiatorHint = document.getElementById('transfer-initiator-hint');
  var decisionSelect = document.getElementById('transfer-decision');
  var differenceHint = document.getElementById('transfer-difference');
  var problemsBox = document.getElementById('transfer-problems');
  var submitBtn = document.getElementById('transfer-submit');
  var template = form.getAttribute('data-options-url-template');
  var data = null;

  function optionsUrl(regId) {
    return template.replace(/\/0\//, '/' + regId + '/');
  }

  function currentInstance() {
    if (!data) { return null; }
    var id = parseInt(instanceSelect.value, 10);
    for (var i = 0; i < data.instances.length; i += 1) {
      if (data.instances[i].id === id) { return data.instances[i]; }
    }
    return null;
  }

  function difference() {
    var instance = currentInstance();
    if (!instance) { return null; }
    if (instance.tariffs.length && tariffSelect.value) {
      var id = parseInt(tariffSelect.value, 10);
      for (var i = 0; i < instance.tariffs.length; i += 1) {
        if (instance.tariffs[i].id === id) {
          return instance.tariffs[i].difference;
        }
      }
    }
    return instance.difference;
  }

  function renderTariffs() {
    var instance = currentInstance();
    tariffSelect.innerHTML = '';
    if (!instance || !instance.tariffs.length) {
      tariffGroup.hidden = true;
      return;
    }
    tariffGroup.hidden = false;
    instance.tariffs.forEach(function (tariff) {
      var option = document.createElement('option');
      option.value = tariff.id;
      option.textContent = tariff.name + ' — ' + tariff.price + ' грн';
      tariffSelect.appendChild(option);
    });
  }

  function renderDifference() {
    var diff = difference();
    if (diff === null) { differenceHint.textContent = ''; return; }
    if (diff === 0) {
      differenceHint.textContent = 'Тариф збігається зі сплаченою сумою.';
    } else if (diff > 0) {
      differenceHint.textContent = 'Новий тариф дорожчий на ' + diff + ' грн.';
    } else {
      differenceHint.textContent = 'Новий тариф дешевший на ' + Math.abs(diff) + ' грн.';
    }
  }

  function renderInitiator() {
    /* §3.2 Політики: перенесення з нашої ініціативи -- без доплати.
       Вимикаємо варіант і кажемо чому, а не даємо серверу відбити мовчки. */
    var byOrganizer = initiatorSelect.value === 'organizer';
    var surcharge = decisionSelect.querySelector('option[value="surcharge"]');
    surcharge.disabled = byOrganizer;
    if (byOrganizer) {
      if (decisionSelect.value === 'surcharge') { decisionSelect.value = 'keep'; }
      initiatorHint.textContent =
        'За §3.2 Політики учасник бере участь у нову дату без додаткової '
        + 'оплати, а при відмові отримує 100% повернення.';
    } else {
      initiatorHint.textContent =
        'Повернення рахується за сіткою §4.1 від дати заявки.';
    }
  }

  function renderProblems(problems) {
    if (!problems.length) {
      problemsBox.hidden = true;
      submitBtn.disabled = false;
      return;
    }
    problemsBox.hidden = false;
    problemsBox.innerHTML = '';
    problems.forEach(function (text) {
      var line = document.createElement('div');
      line.textContent = text;
      problemsBox.appendChild(line);
    });
    submitBtn.disabled = true;
  }

  document.addEventListener('click', function (event) {
    var trigger = event.target.closest('[data-transfer-reg]');
    if (!trigger) { return; }
    var regId = trigger.getAttribute('data-transfer-reg');
    form.action = trigger.getAttribute('data-transfer-action');
    instanceSelect.innerHTML = '';
    problemsBox.hidden = true;
    submitBtn.disabled = true;

    fetch(optionsUrl(regId), { credentials: 'same-origin' })
      .then(function (response) { return response.json(); })
      .then(function (payload) {
        data = payload;
        renderProblems(payload.problems);
        payload.instances.forEach(function (instance) {
          var option = document.createElement('option');
          option.value = instance.id;
          option.textContent = instance.title + ' — ' + instance.start_date
            + (instance.location ? ' — ' + instance.location : '');
          instanceSelect.appendChild(option);
        });
        if (!payload.instances.length && !payload.problems.length) {
          renderProblems(['Немає жодного заходу, придатного для перенесення']);
        }
        renderTariffs();
        renderDifference();
        renderInitiator();
      })
      .catch(function () {
        renderProblems(['Не вдалося завантажити список заходів']);
      });
  });

  instanceSelect.addEventListener('change', function () {
    renderTariffs();
    renderDifference();
  });
  tariffSelect.addEventListener('change', renderDifference);
  initiatorSelect.addEventListener('change', renderInitiator);
})();
```

- [ ] **Step 7: Додати пункт меню й підключити модалку**

У `app/templates/admin/partials/_registration_actions.html`, усередині `.admin-actions-menu__items`, після блоку «Скопіювати посилання» (зберігши наявний стиль пунктів):

```html
    {% if reg.status != 'cancelled' %}
    <button type="button" class="admin-actions-menu__item"
            data-modal-open="transfer-modal"
            data-transfer-reg="{{ reg.id }}"
            data-transfer-action="{{ url_for('admin.registration_transfer', reg_id=reg.id) }}">
      {{ icon('swap_horiz') }} Перенести на інший захід
    </button>
    {% endif %}
```

У `app/templates/admin/instance_registrations.html` і `app/templates/admin/registrations.html` — включити модалку (один раз на сторінку, поза таблицею, перед `{% endblock %}` основного блоку):

```html
{% include 'admin/partials/_transfer_modal.html' %}
```

І в `extra_css` кожної з двох сторінок:

```html
<link rel="stylesheet" href="{{ url_for('static', filename='css/modal.css') }}?v={{ assets_version }}">
```

У `extra_scripts` кожної з двох сторінок (після `super()`):

```html
<script src="{{ url_for('static', filename='js/modal.js') }}?v={{ assets_version }}" defer></script>
<script src="{{ url_for('static', filename='js/admin-transfer.js') }}?v={{ assets_version }}" defer></script>
```

Переконатись, що змінна `back_url` доступна в контексті обох шаблонів (вона вже передається в `registration_actions`); якщо в `registrations.html` вона зветься інакше — використати наявне ім'я.

- [ ] **Step 8: Перевірити, що сторінки рендеряться**

Run: `python -m pytest tests/test_routes -q`
Expected: PASS. Якщо тесту на ці дві сторінки немає — відкрити обидві через тестовий клієнт і перевірити код 200 та наявність `transfer-modal` у відповіді.

- [ ] **Step 9: Прогнати сторожів дизайн-системи**

Run: `python -m pytest tests/test_design_system -v && python tools/ds/ds_audit.py`
Expected: PASS; жодного класу, оголошеного двічі.

- [ ] **Step 10: Commit**

```bash
git add app/admin/routes_registrations.py \
        app/templates/admin/partials/_transfer_modal.html \
        app/templates/admin/partials/_registration_actions.html \
        app/templates/admin/instance_registrations.html \
        app/templates/admin/registrations.html \
        app/static/js/admin-transfer.js \
        tests/test_routes/test_admin_transfer.py
git commit -m "feat(перенесення): модалка й роути в адмінці"
```

---

### Task 7: Лист із вибором

**Files:**
- Modify: `app/models/email_log.py`
- Create: `migrations/versions/email_trigger_transfer_20260831.py`
- Modify: `app/services/email_service.py`
- Create: `app/templates/emails/transfer_offer.html`
- Test: `tests/test_services/test_transfer_email.py`

**Interfaces:**
- Consumes: `RegistrationTransfer` (Task 1), `execute()` (Task 3).
- Produces: `EmailService.send_transfer_offer(transfer)` — повертає `EmailLog` або `None`; тригер `'transfer'` у `EmailLog.TRIGGERS`.

- [ ] **Step 1: Написати тести листа**

Створити `tests/test_services/test_transfer_email.py`:

```python
"""Лист-пропозиція при перенесенні.

Головне, що тут перевіряється: порожні причина й примітка не дають ані
заголовка, ані порожнього блоку. Це прямий пункт технічного завдання.
"""
from datetime import timedelta

import pytest

from app.extensions import db
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.email_log import EmailLog
from app.models.mixins import utcnow
from app.models.registration import EventRegistration
from app.models.user import User
from app.services import transfer_service
from app.services.email_service import EmailService
from tests.refund_fixtures import purge

PREFIX = 'rte-'


@pytest.fixture
def world(app):
    user = User(email=f'{PREFIX}one@example.com', first_name='Тест',
                last_name='Переносний', is_active=True)
    user.set_password('x' * 12)
    course = Course(title='Курс переносу', slug=f'{PREFIX}course')
    db.session.add_all([user, course])
    db.session.flush()
    now = utcnow()
    src = CourseInstance(course_id=course.id, status='published',
                         start_date=now + timedelta(days=10), price=1000)
    dst = CourseInstance(course_id=course.id, status='published',
                         start_date=now + timedelta(days=20), price=1000)
    db.session.add_all([src, dst])
    db.session.flush()
    reg = EventRegistration(
        user_id=user.id, instance_id=src.id, phone='+380000000000',
        specialty='Лікар', workplace='Клініка', status='confirmed',
        payment_status='paid', payment_amount=1000,
    )
    db.session.add(reg)
    db.session.commit()
    yield reg, dst
    purge(PREFIX, slug_prefix=PREFIX)


def test_transfer_trigger_is_allowed():
    """Інваріант TRIGGERS <-> ck_email_logs_trigger стереже
    test_trigger_coverage; тут перевіряємо саме новий код."""
    assert EmailLog.is_valid_trigger('transfer')


def test_offer_renders_reason_and_note(world, app):
    reg, dst = world
    transfer = transfer_service.execute(
        reg, target_instance=dst, initiator='organizer',
        tariff_decision='keep', reason='Тренер захворів',
        note='Місце проведення те саме', announced=False,
    )
    html = _render(app, transfer)
    assert 'Тренер захворів' in html
    assert 'Місце проведення те саме' in html


def test_offer_omits_empty_reason_and_note(world, app):
    """Порожні поля не мають лишати ані заголовка, ані порожнього блоку."""
    reg, dst = world
    transfer = transfer_service.execute(
        reg, target_instance=dst, initiator='organizer',
        tariff_decision='keep', announced=False,
    )
    html = _render(app, transfer)
    assert 'Причина перенесення' not in html
    assert 'Примітка' not in html


def test_offer_contains_both_choices(world, app):
    reg, dst = world
    transfer = transfer_service.execute(
        reg, target_instance=dst, initiator='organizer',
        tariff_decision='keep', announced=False,
    )
    transfer.issue_consent_token()
    db.session.commit()
    html = _render(app, transfer)
    assert f'/registration/transfer/{transfer.consent_token}' in html


def _render(app, transfer):
    from flask import render_template
    with app.test_request_context():
        from app.models.site_settings import SiteSettings
        return render_template(
            'emails/transfer_offer.html',
            user=transfer.registration.user,
            transfer=transfer,
            registration=transfer.registration,
            consent_url=f'https://example.com/registration/transfer/{transfer.consent_token}',
            surcharge_url=None,
            site_settings=SiteSettings.get(),
        )
```

- [ ] **Step 2: Запустити — має впасти**

Run: `python -m pytest tests/test_services/test_transfer_email.py -v`
Expected: FAIL — `'transfer'` не в `ALLOWED_TRIGGERS`, шаблона немає.

- [ ] **Step 3: Додати тригер у модель**

У `app/models/email_log.py`, у список `TRIGGERS`, перед `('test', 'Тест')`:

```python
        ('transfer', 'Перенесення заходу'),
```

І в CHECK-обмеження `ck_email_logs_trigger` — додати `'transfer'` до переліку:

```python
        db.CheckConstraint(
            "trigger IN ('registration', 'payment', 'reminder', 'status_change', "
            "'email_confirm', 'course_request', 'certificate', 'blog_comment', "
            "'password_reset', 'backup_failure', 'materials', 'referral', "
            "'meta_lead', 'transfer', 'test')",
            name='ck_email_logs_trigger',
        ),
```

- [ ] **Step 4: Написати міграцію CHECK**

Перевірити head: `python -m flask db heads` (має бути `registration_transfer_20260831` після Task 1). Створити `migrations/versions/email_trigger_transfer_20260831.py`:

```python
"""ck_email_logs_trigger: додати тригер 'transfer'.

CHECK перевипускається цілком -- ALTER для нього немає ні в SQLite, ні в
Postgres у формі "додати значення". batch_alter_table робить це однаково
на обох.

Revision ID: email_trigger_transfer_20260831
Revises: registration_transfer_20260831
"""
from alembic import op

revision = 'email_trigger_transfer_20260831'
down_revision = 'registration_transfer_20260831'
branch_labels = None
depends_on = None

OLD = (
    "trigger IN ('registration', 'payment', 'reminder', 'status_change', "
    "'email_confirm', 'course_request', 'certificate', 'blog_comment', "
    "'password_reset', 'backup_failure', 'materials', 'referral', "
    "'meta_lead', 'test')"
)
NEW = (
    "trigger IN ('registration', 'payment', 'reminder', 'status_change', "
    "'email_confirm', 'course_request', 'certificate', 'blog_comment', "
    "'password_reset', 'backup_failure', 'materials', 'referral', "
    "'meta_lead', 'transfer', 'test')"
)


def upgrade():
    with op.batch_alter_table('email_logs', schema=None) as batch_op:
        batch_op.drop_constraint('ck_email_logs_trigger', type_='check')
        batch_op.create_check_constraint('ck_email_logs_trigger', NEW)


def downgrade():
    with op.batch_alter_table('email_logs', schema=None) as batch_op:
        batch_op.drop_constraint('ck_email_logs_trigger', type_='check')
        batch_op.create_check_constraint('ck_email_logs_trigger', OLD)
```

- [ ] **Step 5: Написати шаблон листа**

Створити `app/templates/emails/transfer_offer.html`. Спершу **прочитати `app/templates/emails/refund_request_received.html`** і повторити його структуру: `{% extends %}`, блоки, макроси з `emails/_macros.html`. Нижче — вміст, який має бути всередині блоку тіла:

```html
{% extends "emails/base.html" %}

{% block content %}
<p>Вітаємо, {{ user.first_name }}!</p>

<p>Вашу реєстрацію перенесено на інше проведення курсу
   <strong>{{ transfer.to_instance.course.title if transfer.to_instance and transfer.to_instance.course else 'курсу' }}</strong>.</p>

<table role="presentation" width="100%" cellpadding="0" cellspacing="0">
  <tr>
    <td><strong>Було:</strong></td>
    <td>{{ transfer.from_instance.start_date.strftime('%d.%m.%Y') if transfer.from_instance and transfer.from_instance.start_date else 'дата не вказана' }}{% if transfer.from_instance and transfer.from_instance.location %}, {{ transfer.from_instance.location }}{% endif %}</td>
  </tr>
  <tr>
    <td><strong>Стало:</strong></td>
    <td>{{ transfer.to_instance.start_date.strftime('%d.%m.%Y') if transfer.to_instance and transfer.to_instance.start_date else 'дата не вказана' }}{% if transfer.to_instance and transfer.to_instance.location %}, {{ transfer.to_instance.location }}{% endif %}</td>
  </tr>
</table>

{# Порожні поля НЕ рендеряться -- ані заголовка, ані порожнього блоку. #}
{% if transfer.reason %}
<p><strong>Причина перенесення:</strong><br>{{ transfer.reason }}</p>
{% endif %}

{% if transfer.note %}
<p><strong>Примітка:</strong><br>{{ transfer.note|replace('\n', '<br>')|safe }}</p>
{% endif %}

{% if transfer.difference and transfer.difference != 0 %}
  {% if transfer.tariff_decision == 'refund_diff' %}
<p>Новий тариф дешевший на {{ transfer.difference|abs }} грн. Ми повернемо
   вам цю різницю — заявку вже передано менеджеру.</p>
  {% elif transfer.tariff_decision == 'surcharge' %}
<p>Новий тариф дорожчий на {{ transfer.difference }} грн.</p>
  {% else %}
<p>Вартість участі для вас лишається без змін.</p>
  {% endif %}
{% endif %}

<p><strong>Оберіть, будь ласка, що робимо далі:</strong></p>

<p>
  <a href="{{ consent_url }}" class="btn">Погоджуюсь на перенесення</a>
</p>
<p>
  <a href="{{ consent_url }}#refund">Прошу повернення коштів</a>
</p>

{% if surcharge_url %}
<p><a href="{{ surcharge_url }}">Доплатити {{ transfer.difference }} грн</a></p>
{% endif %}

<p>Якщо кнопки не працюють, відкрийте посилання:<br>
   <a href="{{ consent_url }}">{{ consent_url }}</a></p>
{% endblock %}
```

Класи й макроси кнопок узяти з `emails/_macros.html` і сусідніх листів — власних inline-стилів не додавати понад ті, що вже вживає `emails/base.html`.

- [ ] **Step 6: Замінити заглушку `send_transfer_offer`**

У `app/services/email_service.py` замінити заглушку з Task 3 на реалізацію:

```python
    @staticmethod
    def send_transfer_offer(transfer):
        """Повідомити учасника про перенесення й дати вибір (§3.2).

        Лист учаснику, тож NotificationRule тут не залучається: список
        отримувачів -- рівно одна людина, чию реєстрацію перенесли.
        """
        reg = transfer.registration
        user = reg.user if reg is not None else None
        if user is None or not user.email:
            return None

        base = EmailService._site_base_url()
        consent_url = (f'{base}/registration/transfer/{transfer.consent_token}'
                       if base and transfer.consent_token else None)
        surcharge_url = None
        if transfer.surcharge_due and consent_url:
            surcharge_url = f'{consent_url}/surcharge'

        return EmailService.send_email(
            to=user.email,
            subject=lambda: _('Ваш захід перенесено: %(title)s',
                              title=reg.target_title or 'курс'),
            template_name='transfer_offer',
            context={
                'user': user,
                'transfer': transfer,
                'registration': reg,
                'consent_url': consent_url,
                'surcharge_url': surcharge_url,
            },
            trigger='transfer',
            registration_id=reg.id,
        )
```

- [ ] **Step 7: Прогнати міграцію й тести**

Run:
```bash
python -m flask db upgrade
python -m pytest tests/test_services/test_transfer_email.py -v
python -m pytest tests -q -k trigger_coverage
```
Expected: усе PASS. `test_trigger_coverage` стереже збіг `TRIGGERS` і CHECK — якщо він падає, розбіжність між моделлю й міграцією.

- [ ] **Step 8: Commit**

```bash
git add app/models/email_log.py app/services/email_service.py \
        app/templates/emails/transfer_offer.html \
        migrations/versions/email_trigger_transfer_20260831.py \
        tests/test_services/test_transfer_email.py
git commit -m "feat(перенесення): лист із вибором для учасника"
```

---

### Task 8: Публічні сторінки згоди

**Files:**
- Modify: `app/registration/routes.py`
- Create: `app/templates/registration/transfer_consent.html`
- Test: `tests/test_routes/test_transfer_public.py`

**Interfaces:**
- Consumes: `transfer_service.accept()`, `transfer_service.request_refund()` (Task 4).
- Produces: ендпоінти `registration.transfer_consent` (`GET /registration/transfer/<token>`), `registration.transfer_accept` (`POST /registration/transfer/<token>/accept`), `registration.transfer_refund` (`POST /registration/transfer/<token>/refund`).

- [ ] **Step 1: Написати тести**

Створити `tests/test_routes/test_transfer_public.py`:

```python
"""Публічні сторінки згоди на перенесення -- без входу, по токену."""
from datetime import timedelta

import pytest

from app.extensions import db
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.mixins import utcnow
from app.models.registration import EventRegistration
from app.models.registration_transfer import RegistrationTransfer
from app.models.user import User
from app.services import transfer_service
from tests.refund_fixtures import purge

PREFIX = 'rtp-'


@pytest.fixture
def offer(app, monkeypatch):
    monkeypatch.setattr(
        'app.services.email_service.EmailService.send_transfer_offer',
        staticmethod(lambda transfer: None),
    )
    user = User(email=f'{PREFIX}one@example.com', first_name='Тест',
                last_name='Переносний', is_active=True)
    user.set_password('x' * 12)
    course = Course(title='Курс переносу', slug=f'{PREFIX}course')
    db.session.add_all([user, course])
    db.session.flush()
    now = utcnow()
    src = CourseInstance(course_id=course.id, status='published',
                         start_date=now + timedelta(days=10), price=1000)
    dst = CourseInstance(course_id=course.id, status='published',
                         start_date=now + timedelta(days=20), price=1000)
    db.session.add_all([src, dst])
    db.session.flush()
    reg = EventRegistration(
        user_id=user.id, instance_id=src.id, phone='+380000000000',
        specialty='Лікар', workplace='Клініка', status='pending',
        payment_status='paid', payment_amount=1000,
    )
    db.session.add(reg)
    db.session.commit()
    transfer = transfer_service.execute(
        reg, target_instance=dst, initiator='organizer',
        tariff_decision='keep', announced=True,
    )
    yield transfer, reg
    purge(PREFIX, slug_prefix=PREFIX)


def test_page_opens_without_login(client, offer):
    transfer, _reg = offer
    resp = client.get(f'/registration/transfer/{transfer.consent_token}')
    assert resp.status_code == 200


def test_unknown_token_is_404(client, offer):
    resp = client.get('/registration/transfer/definitely-not-a-token')
    assert resp.status_code == 404


def test_expired_token_is_rejected(client, offer):
    transfer, _reg = offer
    transfer.consent_token_expires_at = utcnow() - timedelta(days=1)
    db.session.commit()
    resp = client.get(f'/registration/transfer/{transfer.consent_token}')
    assert resp.status_code == 404


def test_accept_confirms(client, offer):
    transfer, reg = offer
    resp = client.post(
        f'/registration/transfer/{transfer.consent_token}/accept',
        follow_redirects=True)
    assert resp.status_code == 200
    db.session.refresh(transfer)
    db.session.refresh(reg)
    assert transfer.state == RegistrationTransfer.STATE_ACCEPTED
    assert reg.status == 'confirmed'


def test_refund_opens_request(client, offer):
    from app.models.refund_request import RefundRequest
    transfer, reg = offer
    resp = client.post(
        f'/registration/transfer/{transfer.consent_token}/refund',
        data={'reason': 'Дата не підходить'}, follow_redirects=True)
    assert resp.status_code == 200
    db.session.refresh(transfer)
    assert transfer.state == RegistrationTransfer.STATE_REFUND_REQUESTED
    request = RefundRequest.query.filter_by(registration_id=reg.id).one()
    assert request.quoted_percent == 100


def test_refund_requires_reason(client, offer):
    from app.models.refund_request import RefundRequest
    transfer, reg = offer
    client.post(f'/registration/transfer/{transfer.consent_token}/refund',
                data={'reason': '   '}, follow_redirects=True)
    db.session.refresh(transfer)
    assert transfer.state == RegistrationTransfer.STATE_AWAITING
    assert RefundRequest.query.filter_by(registration_id=reg.id).count() == 0


def test_second_answer_is_refused(client, offer):
    transfer, _reg = offer
    client.post(f'/registration/transfer/{transfer.consent_token}/accept',
                follow_redirects=True)
    client.post(f'/registration/transfer/{transfer.consent_token}/refund',
                data={'reason': 'Передумав'}, follow_redirects=True)
    db.session.refresh(transfer)
    assert transfer.state == RegistrationTransfer.STATE_ACCEPTED
```

- [ ] **Step 2: Запустити — має впасти**

Run: `python -m pytest tests/test_routes/test_transfer_public.py -v`
Expected: FAIL — 404 на всіх роутах.

- [ ] **Step 3: Додати роути**

Дописати в `app/registration/routes.py`, поруч із наявними `complete_*` роутами (вони — зразок токен-флоу без логіну):

```python
def _transfer_by_token(token):
    """Активне перенесення за токеном або None."""
    from app.models.registration_transfer import RegistrationTransfer
    item = RegistrationTransfer.query.filter_by(consent_token=token).first()
    if item is None or not item.consent_token_active:
        return None
    return item


@registration_bp.route('/transfer/<token>')
def transfer_consent(token):
    """Сторінка вибору: погодитись чи просити повернення.

    Саме сторінка, а не дія по GET: пре-фетчер поштового клієнта не має
    вирішувати за людину. Той самий мотив, що у /registration/complete/.
    """
    transfer = _transfer_by_token(token)
    if transfer is None:
        abort(404)
    return render_template(
        'registration/transfer_consent.html',
        transfer=transfer,
        registration=transfer.registration,
    )


@registration_bp.route('/transfer/<token>/accept', methods=['POST'])
def transfer_accept(token):
    from app.services import transfer_service

    transfer = _transfer_by_token(token)
    if transfer is None:
        abort(404)
    ok, message = transfer_service.accept(transfer)
    flash(message, 'success' if ok else 'info')
    return redirect(url_for('registration.transfer_consent', token=token))


@registration_bp.route('/transfer/<token>/refund', methods=['POST'])
def transfer_refund(token):
    from app.services import transfer_service

    transfer = _transfer_by_token(token)
    if transfer is None:
        abort(404)

    reason = (request.form.get('reason') or '').strip()
    if not reason:
        # §6.2 Політики вимагає письмову причину -- без неї заявки немає.
        flash('Вкажіть, будь ласка, причину відмови', 'error')
        return redirect(url_for('registration.transfer_consent', token=token))

    _item, error = transfer_service.request_refund(
        transfer, reason, request.form.get('payout_details'))
    flash(error or 'Заявку прийнято, менеджер зв\'яжеться з вами',
          'error' if error else 'success')
    return redirect(url_for('registration.transfer_consent', token=token))
```

Переконатись, що у файлі вже імпортовані `abort`, `flash`, `redirect`, `render_template`, `request`, `url_for` — додати те, чого бракує.

- [ ] **Step 4: Написати шаблон сторінки**

Створити `app/templates/registration/transfer_consent.html`. Спершу **прочитати сусідній шаблон токен-флоу** (той, що рендериться з `complete_registration`) і повторити його `extends`, блоки й класи — власних класів не заводити.

```html
{% extends "base.html" %}

{% block title %}Перенесення заходу | ІПРМ{% endblock %}
{% block extra_meta %}<meta name="robots" content="noindex, nofollow">{% endblock %}

{% block content %}
<section class="registration-page">
  <h1>Ваш захід перенесено</h1>

  <dl>
    <dt>Було</dt>
    <dd>{{ transfer.from_instance.start_date.strftime('%d.%m.%Y') if transfer.from_instance and transfer.from_instance.start_date else 'дата не вказана' }}</dd>
    <dt>Стало</dt>
    <dd>{{ transfer.to_instance.start_date.strftime('%d.%m.%Y') if transfer.to_instance and transfer.to_instance.start_date else 'дата не вказана' }}{% if transfer.to_instance and transfer.to_instance.location %}, {{ transfer.to_instance.location }}{% endif %}</dd>
  </dl>

  {% if transfer.reason %}
  <p><strong>Причина перенесення:</strong> {{ transfer.reason }}</p>
  {% endif %}
  {% if transfer.note %}
  <p><strong>Примітка:</strong> {{ transfer.note }}</p>
  {% endif %}

  {% if transfer.state == 'awaiting_consent' %}
    <form method="POST" action="{{ url_for('registration.transfer_accept', token=transfer.consent_token) }}">
      <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
      <button type="submit" class="btn btn--primary">Погоджуюсь на перенесення</button>
    </form>

    <h2 id="refund">Або поверніть кошти</h2>
    {% if transfer.initiator == 'organizer' %}
    <p>Оскільки захід перенесли ми, за §3.2 Політики ви маєте право на
       повернення 100% сплаченої суми.</p>
    {% endif %}
    <form method="POST" action="{{ url_for('registration.transfer_refund', token=transfer.consent_token) }}">
      <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
      <label for="transfer-refund-reason">Причина відмови</label>
      <textarea id="transfer-refund-reason" name="reason" rows="3" required></textarea>
      <label for="transfer-payout">Реквізити для повернення (якщо на інший рахунок)</label>
      <input type="text" id="transfer-payout" name="payout_details" maxlength="500">
      <button type="submit" class="btn btn--secondary">Прошу повернення коштів</button>
    </form>
  {% elif transfer.state == 'accepted' %}
    <p>Дякуємо, вашу участь у новій даті підтверджено.</p>
  {% elif transfer.state == 'refund_requested' %}
    <p>Заявку на повернення прийнято. Менеджер зв'яжеться з вами.</p>
  {% endif %}
</section>
{% endblock %}
```

- [ ] **Step 5: Прогнати тести**

Run: `python -m pytest tests/test_routes/test_transfer_public.py -v`
Expected: усі 7 PASS.

- [ ] **Step 6: Прогнати весь набір роутів**

Run: `python -m pytest tests/test_routes -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add app/registration/routes.py \
        app/templates/registration/transfer_consent.html \
        tests/test_routes/test_transfer_public.py
git commit -m "feat(перенесення): публічні сторінки згоди по токену"
```

---

### Task 9: Доплата різниці

**Files:**
- Modify: `app/services/payment_ops.py`
- Modify: `app/registration/routes.py`
- Modify: `app/templates/admin/partials/_registration_actions.html` (плашка боргу — у шаблон рядка)
- Modify: `app/templates/admin/instance_registrations.html`
- Modify: `app/admin/routes_registrations.py` (фільтр)
- Test: `tests/test_services/test_transfer_surcharge.py`

**Interfaces:**
- Consumes: `RegistrationTransfer.surcharge_due` (Task 1); `parse_order_id` (наявний).
- Produces: `parse_order_id('SUR-<id>') -> ('surcharge', <id>)`; `PaymentOps.apply_surcharge(transfer, payment_id, amount)`; ендпоінт `registration.transfer_surcharge` (`GET /registration/transfer/<token>/surcharge`); фільтр `surcharge=due` у `/admin/registrations`.

- [ ] **Step 1: Написати тести**

Створити `tests/test_services/test_transfer_surcharge.py`:

```python
"""Доплата різниці тарифу при перенесенні."""
from datetime import timedelta

import pytest

from app.extensions import db
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.instance_tariff import InstanceTariff
from app.models.mixins import utcnow
from app.models.registration import EventRegistration
from app.models.user import User
from app.services import transfer_service
from app.services.payment_ops import parse_order_id
from tests.refund_fixtures import purge

PREFIX = 'rtu-'


@pytest.fixture
def transfer(app, monkeypatch):
    monkeypatch.setattr(
        'app.services.email_service.EmailService.send_transfer_offer',
        staticmethod(lambda t: None),
    )
    user = User(email=f'{PREFIX}one@example.com', first_name='Тест',
                last_name='Переносний', is_active=True)
    user.set_password('x' * 12)
    course = Course(title='Курс переносу', slug=f'{PREFIX}course')
    db.session.add_all([user, course])
    db.session.flush()
    now = utcnow()
    src = CourseInstance(course_id=course.id, status='published',
                         start_date=now + timedelta(days=10), price=1000)
    dst = CourseInstance(course_id=course.id, status='published',
                         start_date=now + timedelta(days=20), price=1500)
    db.session.add_all([src, dst])
    db.session.flush()
    tariff = InstanceTariff(instance_id=dst.id, name='Практикум', price=1500)
    reg = EventRegistration(
        user_id=user.id, instance_id=src.id, phone='+380000000000',
        specialty='Лікар', workplace='Клініка', status='confirmed',
        payment_status='paid', payment_amount=1000,
    )
    db.session.add_all([tariff, reg])
    db.session.commit()
    item = transfer_service.execute(
        reg, target_instance=dst, initiator='participant', tariff=tariff,
        tariff_decision='surcharge', announced=True,
    )
    yield item, reg
    purge(PREFIX, slug_prefix=PREFIX)


def test_order_id_prefix_is_recognised():
    assert parse_order_id('SUR-42') == ('surcharge', 42)
    assert parse_order_id('REG-42') == ('registration', 42)


def test_surcharge_is_due_before_payment(transfer):
    item, _reg = transfer
    assert item.difference == 500
    assert item.surcharge_due is True


def test_applying_surcharge_tops_up_payment_amount(transfer):
    """Саме тут сума замовлення доганяє новий тариф."""
    from app.services.payment_ops import PaymentOps
    item, reg = transfer
    PaymentOps.apply_surcharge(item, payment_id='lp-1', amount=500)
    db.session.refresh(reg)
    assert reg.payment_amount == 1500
    assert item.surcharge_paid_at is not None
    assert item.surcharge_payment_id == 'lp-1'
    assert item.surcharge_due is False


def test_applying_surcharge_twice_is_ignored(transfer):
    """Повторний callback LiqPay не має додати різницю вдруге."""
    from app.services.payment_ops import PaymentOps
    item, reg = transfer
    PaymentOps.apply_surcharge(item, payment_id='lp-1', amount=500)
    PaymentOps.apply_surcharge(item, payment_id='lp-1', amount=500)
    db.session.refresh(reg)
    assert reg.payment_amount == 1500


def test_unpaid_surcharge_does_not_block_participation(transfer):
    """Рішення власника: участь чинна, доплата висить як борг."""
    item, reg = transfer
    assert reg.status == 'confirmed'
    assert reg.payment_status == 'paid'
```

- [ ] **Step 2: Запустити — має впасти**

Run: `python -m pytest tests/test_services/test_transfer_surcharge.py -v`
Expected: FAIL — `parse_order_id('SUR-42')` повертає `(None, None)`; `apply_surcharge` немає.

- [ ] **Step 3: Розширити `parse_order_id` і додати зарахування**

У `app/services/payment_ops.py` замінити тіло циклу в `parse_order_id`:

```python
def parse_order_id(order_id):
    """Розібрати order_id у пару (тип, числовий id).

    Типи: 'registration' (REG-<id>), 'enrollment' (ONL-<id>) і
    'surcharge' (SUR-<transfer_id>) -- доплата різниці тарифу при
    перенесенні. Останній вказує на RegistrationTransfer, а не на
    реєстрацію: сума й підстава живуть саме там.
    """
    for prefix, kind in (('REG-', 'registration'), ('ONL-', 'enrollment'),
                         ('SUR-', 'surcharge')):
        if order_id.startswith(prefix):
            try:
                return kind, int(order_id.split('-', 1)[1])
            except (ValueError, IndexError):
                return kind, None
    return None, None
```

Додати в клас `PaymentOps` статичний метод (поруч із рештою методів, що рухають гроші):

```python
    @staticmethod
    def apply_surcharge(transfer, payment_id, amount):
        """Зарахувати доплату різниці тарифу. Комітить.

        Саме тут payment_amount реєстрації доганяє новий тариф: до цієї
        миті вона лишалась такою, якою людина заплатила спочатку.

        Ідемпотентно за surcharge_paid_at: LiqPay повторює callback, і без
        цієї перевірки різниця додалась би двічі.
        """
        if transfer.surcharge_paid_at is not None:
            logger.info('Surcharge for transfer #%s already applied',
                        transfer.id)
            return False

        reg = transfer.registration
        if reg is None:
            return False

        reg.payment_amount = _money(reg.payment_amount) + _money(amount)
        transfer.surcharge_paid_at = utcnow()
        transfer.surcharge_payment_id = payment_id
        db.session.commit()

        audit_logger.info(
            'Surcharge %s applied to REG-%s via transfer #%s (payment %s)',
            amount, reg.id, transfer.id, payment_id,
        )
        return True
```

Переконатись, що у файлі доступні `utcnow`, `db`, `audit_logger` — якщо `audit_logger` не оголошений, додати поруч із `logger`:

```python
audit_logger = logging.getLogger('audit')
```

- [ ] **Step 4: Обробити `SUR-` у callback**

Знайти в `PaymentOps.process_callback` місце, де результат `parse_order_id` розводиться на `registration`/`enrollment`, і додати гілку в тому ж стилі:

```python
        if kind == 'surcharge':
            from app.models.registration_transfer import RegistrationTransfer
            transfer = db.session.get(RegistrationTransfer, entity_id)
            if transfer is None:
                return _fail(f'Перенесення #{entity_id} не знайдено')
            if mapped_status != 'paid':
                return _noop(f'Доплата #{entity_id}: статус {mapped_status}')
            PaymentOps.apply_surcharge(
                transfer,
                payment_id=str(payload.get('payment_id') or ''),
                amount=payload.get('amount') or transfer.difference,
            )
            return _noop(f'Доплату за перенесенням #{entity_id} зараховано')
```

Імена локальних змінних (`kind`, `entity_id`, `mapped_status`, `payload`) взяти з наявного коду методу — вони можуть зватись інакше; підлаштуватись під файл, а не переписувати його.

- [ ] **Step 5: Додати публічний роут доплати**

У `app/registration/routes.py`, поруч із рештою `transfer_*`:

```python
@registration_bp.route('/transfer/<token>/surcharge')
def transfer_surcharge(token):
    """Сторінка оплати різниці тарифу.

    Окремий order_id SUR-<transfer_id>: платіж стосується перенесення, а
    не початкового замовлення, і плутати їх у звітності не можна.
    """
    transfer = _transfer_by_token(token)
    if transfer is None:
        abort(404)
    if not transfer.surcharge_due:
        flash('Доплату вже отримано', 'info')
        return redirect(url_for('registration.transfer_consent', token=token))

    return render_template(
        'registration/transfer_surcharge.html',
        transfer=transfer,
        registration=transfer.registration,
        order_id=f'SUR-{transfer.id}',
        amount=transfer.difference,
    )
```

Роут вище — неповний: віджет LiqPay треба зібрати так само, як це робить `complete_payment` (`app/registration/routes.py:800-830`). Повна версія:

```python
@registration_bp.route('/transfer/<token>/surcharge')
def transfer_surcharge(token):
    """Сторінка оплати різниці тарифу.

    Окремий order_id SUR-<transfer_id>: платіж стосується перенесення, а
    не початкового замовлення, і плутати їх у звітності не можна.
    """
    from app.services.liqpay import get_liqpay_service

    transfer = _transfer_by_token(token)
    if transfer is None:
        abort(404)
    if not transfer.surcharge_due:
        flash('Доплату вже отримано', 'info')
        return redirect(url_for('registration.transfer_consent', token=token))

    reg = transfer.registration
    liqpay_data = liqpay_signature = liqpay_checkout_url = None
    service = get_liqpay_service()
    if service.is_configured:
        result_url = url_for(
            'registration.transfer_consent', token=token, _external=True)
        server_url = url_for('payments.liqpay_callback', _external=True)
        description = (
            f'Доплата різниці тарифу: '
            f'{reg.target_title or "перенесення реєстрації"}'
        )
        liqpay_data, liqpay_signature, liqpay_checkout_url = (
            service.create_payment_form(
                order_id=f'SUR-{transfer.id}',
                amount=float(transfer.difference),
                description=description,
                result_url=result_url,
                server_url=server_url,
            )
        )

    return render_template(
        'registration/transfer_surcharge.html',
        transfer=transfer,
        reg=reg,
        amount=transfer.difference,
        liqpay_data=liqpay_data,
        liqpay_signature=liqpay_signature,
        liqpay_checkout_url=liqpay_checkout_url,
    )
```

Створити `app/templates/registration/transfer_surcharge.html`. Розмітку віджета взяти з **`app/templates/registration/complete_pay.html`** — там уже є форма з `liqpay_data` / `liqpay_signature` / `liqpay_checkout_url` і підключення `js/liqpay-checkout.js`. Скопіювати саме цей блок, прибравши все, що стосується встановлення пароля, рахунка й крос-селу; заголовок замінити на «Доплата різниці тарифу», суму брати з `amount`. Власного інтегрування LiqPay не писати: воно вже є.

- [ ] **Step 6: Показати борг у адмінці**

У `app/templates/admin/instance_registrations.html`, у комірці «Сума» (після блоку знижки), додати:

```html
            {% if reg.surcharge_due_amount %}
              <div class="badge badge--pending">Доплата {{ money(reg.surcharge_due_amount) }} не надійшла</div>
            {% endif %}
```

Щоб `surcharge_due_amount` існувало, додати властивість у `app/models/registration.py`, поруч із рештою властивостей:

```python
    @property
    def surcharge_due_amount(self):
        """Незакрита доплата різниці тарифу, або None.

        Денормалізації тут свідомо немає: перенесення -- рідкісна подія, і
        зайва колонка на кожній реєстрації коштувала б більше, ніж запит на
        тих небагатьох рядках, де плашка справді потрібна.
        """
        from app.models.registration_transfer import RegistrationTransfer
        row = RegistrationTransfer.query.filter_by(
            registration_id=self.id, tariff_decision='surcharge',
            surcharge_paid_at=None,
        ).first()
        return row.difference if row is not None else None
```

- [ ] **Step 7: Додати фільтр у реєстр реєстрацій**

У `app/admin/routes_registrations.py`, у словнику, який повертає `_registration_filters()`, додати рядок поруч із `'no_certificate'` (той самий вигляд — прапорець з одним допустимим значенням):

```python
        'surcharge': _listing.choice_arg('surcharge', ('due',)),
```

У `_apply_registration_filters(query, filters)` — додати гілку:

```python
    if filters.get('surcharge') == 'due':
        from app.models.registration_transfer import RegistrationTransfer
        query = query.filter(EventRegistration.id.in_(
            db.session.query(RegistrationTransfer.registration_id).filter(
                RegistrationTransfer.tariff_decision == 'surcharge',
                RegistrationTransfer.surcharge_paid_at.is_(None),
            )
        ))
```

Контроль у філтр-барі — це `<select>` з одним значенням, як `no_certificate` (у `_registration_select_options()` йому робити нічого: та функція постачає лише довідники курсів, тренерів і заходів). У `app/templates/admin/registrations.html`, у списку полів фільтр-бара, після рядка `no_certificate`:

```python
           {'name': 'surcharge', 'label': 'Доплата',
            'placeholder': 'Будь-яка', 'options': [('due', 'Не надійшла')]},
```

І в `_registration_filters_summary(filters, rows_count)`, поруч із блоком `no_certificate` — щоб вивантаження називало той самий зріз, який менеджер бачив на екрані. Підпис і значення дослівно ті самі, що в опції селекта:

```python
    if filters['surcharge']:
        summary.append(('Доплата', 'Не надійшла'))
```

- [ ] **Step 8: Прогнати тести**

Run:
```bash
python -m pytest tests/test_services/test_transfer_surcharge.py -v
python -m pytest tests/test_services tests/test_routes -q
```
Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add app/services/payment_ops.py app/registration/routes.py \
        app/templates/registration/transfer_surcharge.html \
        app/models/registration.py \
        app/templates/admin/instance_registrations.html \
        app/admin/routes_registrations.py \
        tests/test_services/test_transfer_surcharge.py
git commit -m "feat(перенесення): доплата різниці тарифу через LiqPay"
```

---

### Task 10: Документація

**Files:**
- Create: `docs/registration-transfer.md`
- Modify: `README.md`

**Interfaces:**
- Consumes: усе попереднє.
- Produces: сторінку документації й рядок навігації в `README.md`.

- [ ] **Step 1: Написати документацію**

Створити `docs/registration-transfer.md`. Структура — за зразком сусідніх файлів `docs/` (прочитати `docs/promo-codes.md` і повторити його розкладку розділів). Обов'язково розкрити:

- **Що це і навіщо** — до появи фічі перевести людину можна було лише скасуванням і повторною реєстрацією, з втратою історії оплати й номера місця.
- **Два види перенесення** — таблиця `initiator` × дозволена дія × котирування повернення, з посиланням на §3.2 і §4.1 Політики.
- **Запобіжники** — усі дев'ять, з формулюваннями, які бачить адмін, і поясненням, що `TRANSFER_MIN_HOURS = 48` — календарні години.
- **Тихо чи голосно** — що саме відбувається в кожному режимі й чому переїзд негайний в обох.
- **Гроші** — таблиця з чотирьох випадків із Task 4 і Task 9; окремо наголосити, що з модалки гроші не рухаються.
- **Пастки, які варто знати наступному:**
  - `place_number` треба знулити перед перепризначенням, інакше `assign_place_number` мовчки поверне старий номер;
  - `uq_refund_requests_open_registration` дозволяє одну відкриту заявку — друга заявка ОНОВЛЮЄ першу;
  - `uq_user_instance_registration` — тому запобіжник 5 перевіряє наявну реєстрацію на цілі ДО коміту;
  - `parse_order_id` тепер знає три префікси, і `SUR-` вказує на `RegistrationTransfer`, а не на реєстрацію;
  - `ck_email_logs_trigger` — CHECK, а не Python-перелік: новий тригер завжди потребує міграції.
- **Не зроблено** — MM Medic не отримує події про переїзд; потрібна парна робота в обох репозиторіях.
- **Порядок деплою** — дві міграції: `registration_transfer_20260831`, далі `email_trigger_transfer_20260831`.

- [ ] **Step 2: Додати рядок у README**

У `README.md`, у таблицю «Документація», додати рядок у наявному форматі — після рядка про повернення коштів (сусідня за змістом тема):

```markdown
| [Перенесення реєстрації](docs/registration-transfer.md) | Переведення учасника на інший захід: тихо чи з листом-вибором, запобіжник 48 годин до обох заходів, узгодження тарифів (лишити / повернути різницю / доплатити), відповідність §3.2 Політики |
```

- [ ] **Step 3: Прогнати весь набір тестів**

Run: `python -m pytest tests -q`
Expected: PASS. Особливо звірити `test_api_v1_clients` і `test_xlsx_participants` — вони падають першими, якщо тести залишили по собі користувачів або курси.

- [ ] **Step 4: Перевірити, що голова міграцій одна**

Run: `python -m flask db heads`
Expected: рівно один рядок — `email_trigger_transfer_20260831`.

- [ ] **Step 5: Commit**

```bash
git add docs/registration-transfer.md README.md
git commit -m "docs: перенесення реєстрації на інший захід"
```
