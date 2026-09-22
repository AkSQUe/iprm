# Заявка тренера на витратні матеріали — план реалізації

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Тренер складає в кабінеті заявку на витратні матеріали до свого заходу; відповідальні перевіряють її в адмінці й погоджують, і лише тоді вона йде на склад наявним `submit_request()`.

**Architecture:** Заявка — це той самий рядок `MaterialReservation`, що дозріває: два нові ЛОКАЛЬНІ статуси (`pending_review`, `returned`) стоять перед наявним `submitted`. Локальний життєвий цикл живе в новому тонкому сервісі `material_request_service.py`, який делегує розмову з MM Medic наявному `material_reservation_service.py` і не дублює її. Сторінка тренера — новий розділ кабінету під наявним `@trainer_required`.

**Tech Stack:** Flask 3.1 (application factory + blueprints), SQLAlchemy ORM, Alembic, Flask-WTF, Flask-Login, Flask-Babel, Jinja2, pytest. Фронтенд — власна дизайн-система (`common.css` + компонентні CSS), vanilla JS, без збірок і без Tailwind.

**Spec:** `docs/superpowers/specs/2026-09-22-trainer-material-request-design.md`

## Global Constraints

Витягнуто зі спеки й `CLAUDE.md`. Ці вимоги неявно входять у КОЖНУ задачу.

- Гілка одна — `main`. Ніяких фіча-гілок, sdd-гілок і ворктрі.
- Коміт — щойно фаза готова, окремим комітом. Файли перелічуються ЯВНО;
  `git add -A` і `git add .` ЗАБОРОНЕНІ (у тому ж дереві може працювати інша
  сесія). Пуш — ніколи без прямого запиту. Повідомлення — українською, без
  згадок про інструмент.
- Фаза з червоними тестами не комітиться.
- Жодних емодзі в коді. Жодного інлайн-коду (ні `<style>`, ні `<script>`,
  ні `onclick`). Жодного Tailwind.
- `page-*.css` — ЛИШЕ layout (сітка, ширини, відступи, порядок). Декор
  (колір, шрифт, межа, тінь) береться з дизайн-системи. Клас, оголошений у
  двох файлах, — порушення; перевірка
  `python 1-instruments/design-system/layer_check.py`.
- `id` alembic-ревізії — НЕ ДОВШЕ 32 символів (колонка `varchar(32)`).
- Кількість alembic-голів питати ЛИШЕ у `flask db heads`, не regex-ом.
  Поточна голова на момент написання плану: `email_trainer_reqs_20260919`.
- Тести, що створюють користувачів, ЗОБОВ'ЯЗАНІ прибирати за собою в
  teardown — інакше валять `test_api_v1_clients`.
- Зміна користувача всередині тесту — лише через `switch_user`; присвоєння
  `g._login_user` переживає запит.
- Усі рядки інтерфейсу — через `_()` / `_l()` (проєкт мультимовний uk/ru/en).
- Нових RBAC-прав не заводимо: `materials.view` і `materials.manage` уже є.

## Що вже є і НЕ переписується

Прочитати перед початком, щоб не написати вдруге:

| Готове | Де |
| --- | --- |
| `submit_request(instance, items)` -> `(ok, result, reservation)` | `app/services/material_reservation_service.py:340` |
| `update_request_items(instance, items)` -> `(ok, result, reservation)` | там само, `:399` |
| `get_reservation(instance_id)` | там само, `:196` |
| `external_ref_for(instance_id)` -> `'iprm-instance-<id>'` | там само, `:38` |
| `get_catalog(consumable=False, search=None, force=False)` -> `(items, error, stale)` | там само, `:110` |
| `kits_for_instance(instance)` -> `list[MaterialKit]` (курсові + універсальні) | там само, `:180` |
| `_event_meta(instance)` -> dict | там само, `:265` |
| `_submitter_id()` -> `current_user.id` або `None` | там само, `:318` |
| Патерн переходів з винятком | `app/services/trainer_cabinet.py:135-171` (`submit_proposal` / `return_proposal`, `ProposalTransitionError`) |
| Патерн best-effort листа з роута | `app/trainer_cabinet/routes.py:293` (`_after_submit`) |
| Патерн адмінського листа за правилами | `app/services/email_service.py:1949` (`send_materials_actuals_reminder`) |
| `EmailService.send_email(..., idempotency_key=...)` | `app/services/email_service.py:306` |
| `notification_recipients.resolve(event_type, instance=None)` | `app/services/notification_recipients.py:95` |
| Декоратор кабінету, кладе картку в `g.trainer` | `app/trainer_cabinet/decorators.py` |
| `upcoming_instances(trainer)` | `app/services/trainer_cabinet.py:43` |
| `CourseInstance.effective_trainers` | `app/models/course_instance.py:435` |

Бік MM Medic НЕ змінюється взагалі.

---

## Task 1: Дані — статуси, походження, колонки, міграція

**Files:**
- Modify: `app/models/material_reservation.py`
- Modify: `app/models/email_log.py:86-113` (`TRIGGERS`)
- Modify: `app/models/notification_rule.py:20-38` (`EVENT_TYPES`)
- Create: `migrations/versions/mat_request_20260922.py`
- Test: `tests/test_mm_medic_materials.py`

**Interfaces:**
- Consumes: нічого (перша задача).
- Produces:
  - `MaterialReservationStatus.PENDING_REVIEW == 'pending_review'`
  - `MaterialReservationStatus.RETURNED == 'returned'`
  - `MaterialReservationStatus.LOCAL_STATES == ('draft', 'pending_review', 'returned')`
  - `MaterialReservationOrigin.TRAINER_CABINET == 'trainer_cabinet'`
  - колонки `MaterialReservation.trainer_submitted_at`, `.reviewed_at`,
    `.reviewed_by_id`, `.review_comment`, relationship `.reviewed_by`
  - тригер листа `'material_request'` у `EmailLog.TRIGGERS`
  - тип події `'material_request'` у `NotificationRule.EVENT_TYPES`

- [ ] **Step 1: Write the failing test**

Додати в кінець `tests/test_mm_medic_materials.py`:

```python
def test_local_states_are_declared_and_badged():
    """Нові локальні стани мають бути в ALL, і кожен -- з бейджем і міткою.

    BADGES/LABELS -- словники з .get(): пропущений ключ не падає, а тихо
    малює сирий рядок статусу в інтерфейсі. Тому звіряємо повний обхід ALL,
    а не наявність двох конкретних ключів.
    """
    from app.models.material_reservation import MaterialReservationStatus as S

    assert S.PENDING_REVIEW == 'pending_review'
    assert S.RETURNED == 'returned'
    assert S.PENDING_REVIEW in S.ALL
    assert S.RETURNED in S.ALL
    assert S.LOCAL_STATES == (S.DRAFT, S.PENDING_REVIEW, S.RETURNED)
    for status in S.ALL:
        assert status in S.BADGES, f'немає бейджа для {status}'
        assert status in S.LABELS, f'немає мітки для {status}'


def test_trainer_cabinet_origin_is_distinct_from_mm_medic_one():
    """Два різні канали тренера не мають виглядати однаково в огляді."""
    from app.models.material_reservation import MaterialReservationOrigin as O

    assert O.TRAINER_CABINET == 'trainer_cabinet'
    assert O.TRAINER_CABINET in O.ALL
    assert O.LABELS[O.TRAINER_CABINET] != O.LABELS[O.TRAINER]


def test_material_request_trigger_and_event_type_registered():
    """Тригер листа й тип події мусять бути в моделях -- інакше CHECK у базі
    відкине INSERT, і лист загубиться тихо."""
    from app.models.email_log import EmailLog
    from app.models.notification_rule import NotificationRule

    assert 'material_request' in dict(EmailLog.TRIGGERS)
    assert 'material_request' in dict(NotificationRule.EVENT_TYPES)


def test_pending_review_is_not_treated_as_mm_document():
    """`is_mm_document` вирішує, які кнопки показати. Заявка тренера заповнює
    quantity_requested ЩЕ ДО відправлення на MM Medic, тож без перевірки
    статусу властивість збрехала б, що документ уже існує."""
    from app.models.material_reservation import (
        MaterialReservation, MaterialReservationItem, MaterialReservationStatus)

    res = MaterialReservation(status=MaterialReservationStatus.PENDING_REVIEW)
    res.items.append(MaterialReservationItem(sku='A', quantity_requested=3))
    assert res.is_mm_document is False

    res.status = MaterialReservationStatus.SUBMITTED
    assert res.is_mm_document is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `venv/Scripts/python -m pytest tests/test_mm_medic_materials.py -k "local_states or trainer_cabinet_origin or material_request_trigger or not_treated_as_mm" -v`

Expected: FAIL — `AttributeError: type object 'MaterialReservationStatus' has no attribute 'PENDING_REVIEW'`.

- [ ] **Step 3: Додати статуси й походження в модель**

У `app/models/material_reservation.py`, клас `MaterialReservationStatus` — додати два значення і розширити три колекції:

```python
    DRAFT = 'draft'          # built locally, not yet sent
    # Заявка тренера з кабінету ІПРМ. Локальні стани: документа на MM Medic
    # ще НЕМАЄ, і поки заявка в них, жоден штовх статусу її не стосується.
    PENDING_REVIEW = 'pending_review'  # тренер подав, чекає перевірки
    RETURNED = 'returned'              # повернуто тренеру на доопрацювання
    SUBMITTED = 'submitted'  # sent to MM Medic, awaiting approval (no hold yet)
    RESERVED = 'reserved'    # approved by MM Medic (holds active)
    ISSUED = 'issued'        # handed over to the trainer, stock written off
    CONSUMED = 'consumed'    # actuals recorded after the event
    REJECTED = 'rejected'    # approval refused
    CANCELLED = 'cancelled'  # released before the event
    EXPIRED = 'expired'      # holds lapsed on MM Medic (event passed, no actuals)

    ALL = (DRAFT, PENDING_REVIEW, RETURNED, SUBMITTED, RESERVED, ISSUED,
           CONSUMED, REJECTED, CANCELLED, EXPIRED)

    # Стани, що живуть ЛИШЕ тут. Жодного документа на MM Medic їм не
    # відповідає, тож вхідний штовх статусу не має права їх перезаписати
    # (app/api/mm_status.py). Кортеж, а не множина: порядок = порядок циклу,
    # і він читається в тестах.
    LOCAL_STATES = (DRAFT, PENDING_REVIEW, RETURNED)
```

У `BADGES` додати:

```python
        PENDING_REVIEW: 'warning',
        RETURNED: 'cancelled',
```

У `LABELS` додати:

```python
        PENDING_REVIEW: 'На перевірці',
        RETURNED: 'Повернуто тренеру',
```

У класі `MaterialReservationOrigin`:

```python
    IPRM = 'iprm'          # created here, in the IPRM admin
    TRAINER = 'trainer'    # created by a trainer in the MM Medic admin
    # Заявка з кабінету тренера на цьому сайті. Окремо від TRAINER: це два
    # різні канали, і в огляді матеріалів вони не мають виглядати однаково.
    TRAINER_CABINET = 'trainer_cabinet'

    ALL = (IPRM, TRAINER, TRAINER_CABINET)
    LABELS = {
        IPRM: 'Адміністратор ІПРМ',
        TRAINER: 'Тренер (MM Medic)',
        TRAINER_CABINET: 'Тренер (кабінет ІПРМ)',
    }
```

- [ ] **Step 4: Додати колонки й уточнити `is_mm_document`**

У класі `MaterialReservation`, одразу після `trainer_comment`:

```python
    # Заявка з кабінету тренера (спека від 2026-09-22). `created_by_id` нижче
    # тримає того, ХТО ПОДАВ (тренера-користувача), ці чотири -- того, хто
    # ухвалив рішення, і саме рішення.
    trainer_submitted_at = db.Column(db.DateTime(timezone=True), nullable=True)
    reviewed_at = db.Column(db.DateTime(timezone=True), nullable=True)
    reviewed_by_id = db.Column(
        db.BigInteger,
        db.ForeignKey('users.id', ondelete='SET NULL'),
        nullable=True,
    )
    review_comment = db.Column(db.Text, nullable=True)
```

У блоці relationship'ів (поруч із `created_by`):

```python
    reviewed_by = db.relationship('User', foreign_keys=[reviewed_by_id])
```

`created_by` уже задає `foreign_keys=[created_by_id]`, тож другий FK на
`users` неоднозначності не створює.

У `is_mm_document` — додати ранній вихід ПЕРЕД наявною перевіркою статусів
(докстрінг доповнити абзацом):

```python
        # Локальний стан -- документа на MM Medic ще не існує, хай навіть
        # quantity_requested уже заповнений заявкою тренера. Без цієї гілки
        # властивість стверджувала б наявність документа до того, як його
        # створено, і адмінка ховала б дії, які насправді доступні.
        if self.status in MaterialReservationStatus.LOCAL_STATES:
            return False
        if self.status in (MaterialReservationStatus.SUBMITTED,
                           MaterialReservationStatus.ISSUED):
            return True
        return any(item.quantity_requested is not None for item in self.items)
```

- [ ] **Step 5: Зареєструвати тригер листа й тип події**

У `app/models/email_log.py`, у список `TRIGGERS` — ПЕРЕД `('test', 'Тест')`:

```python
        # Заявка тренера на витратні матеріали: подання, повернення,
        # погодження, відхилення. Окремо від 'materials' (це нагадування
        # внести фактичні): дедуп ключується парою адреса+тригер за 60 с, і
        # на спільному тригері нагадування з'їдало б заявку, що прийшла в ту
        # саму хвилину на ту саму адресу.
        ('material_request', 'Заявка на матеріали'),
```

У `app/models/notification_rule.py`, у список `EVENT_TYPES` — після
`('materials', ...)`:

```python
    # Тренер подав заявку на витратні матеріали. Одержувачі -- відповідальні,
    # що перевіряють заявку перед відправленням на склад.
    ('material_request', 'Заявка тренера на матеріали'),
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `venv/Scripts/python -m pytest tests/test_mm_medic_materials.py -v`

Expected: PASS, усі, включно з наявними десятьма.

- [ ] **Step 7: Написати міграцію**

Створити `migrations/versions/mat_request_20260922.py`. Id — 19 символів,
вкладається в `varchar(32)`.

Перед написанням звірити голову: `venv/Scripts/flask db heads` має дати
`email_trainer_reqs_20260919`. Якщо дає інше — підставити фактичне значення
в `down_revision` і не покладатися на записане в плані.

```python
"""Заявка тренера на матеріали: колонки рішення + тригер і тип події

Revision ID: mat_request_20260922
Revises: email_trainer_reqs_20260919
Create Date: 2026-09-22 00:00:00.000000

Чотири колонки в material_reservations під рішення відповідального і дві
перезаливки CHECK.

CHECK на material_reservations.status і .origin НЕМАЄ (mm_material_resv_20260706
створює лише індекс по статусу), тож нові статуси 'pending_review'/'returned' і
походження 'trainer_cabinet' міграції не потребують -- вони живуть у Python.
Перевірено grep-ом по migrations/versions перед написанням; якщо колись CHECK
з'явиться, цю ревізію треба буде доповнити, інакше нові значення відкине база.
"""
from alembic import op
import sqlalchemy as sa


revision = 'mat_request_20260922'
down_revision = 'email_trainer_reqs_20260919'
branch_labels = None
depends_on = None

_TRIGGERS_OLD = (
    "trigger IN ('registration', 'payment', 'reminder', 'status_change', "
    "'email_confirm', 'course_request', 'certificate', 'blog_comment', "
    "'password_reset', 'backup_failure', 'backup_report', 'materials', "
    "'referral', 'meta_lead', 'transfer', 'quiz', 'trainer_proposal', "
    "'trainer_requisites', 'test')"
)
_TRIGGERS_NEW = (
    "trigger IN ('registration', 'payment', 'reminder', 'status_change', "
    "'email_confirm', 'course_request', 'certificate', 'blog_comment', "
    "'password_reset', 'backup_failure', 'backup_report', 'materials', "
    "'referral', 'meta_lead', 'transfer', 'quiz', 'trainer_proposal', "
    "'trainer_requisites', 'material_request', 'test')"
)

_TYPES_OLD = ("event_type IN ('registration', 'payment', 'course_request', "
              "'status_change', 'materials', 'meta_lead', 'certificate')")
_TYPES_NEW = ("event_type IN ('registration', 'payment', 'course_request', "
              "'status_change', 'materials', 'meta_lead', 'certificate', "
              "'material_request')")


def upgrade():
    with op.batch_alter_table('material_reservations', schema=None) as batch_op:
        batch_op.add_column(sa.Column('trainer_submitted_at',
                                      sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column('reviewed_at',
                                      sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column('reviewed_by_id', sa.BigInteger(),
                                      nullable=True))
        batch_op.add_column(sa.Column('review_comment', sa.Text(), nullable=True))
        batch_op.create_foreign_key('fk_material_res_reviewed_by',
                                    'users', ['reviewed_by_id'], ['id'],
                                    ondelete='SET NULL')

    with op.batch_alter_table('email_logs', schema=None) as batch_op:
        batch_op.drop_constraint('ck_email_logs_trigger', type_='check')
        batch_op.create_check_constraint('ck_email_logs_trigger', _TRIGGERS_NEW)

    op.drop_constraint('ck_notification_rules_event_type', 'notification_rules',
                       type_='check')
    op.create_check_constraint('ck_notification_rules_event_type',
                               'notification_rules', _TYPES_NEW)


def downgrade():
    # Перед звуженням CHECK прибираємо рядки з новими значеннями, інакше
    # constraint не створиться (той самий порядок, що в notif_cert_failed_20260913).
    op.execute("DELETE FROM notification_rules WHERE event_type = 'material_request'")
    op.drop_constraint('ck_notification_rules_event_type', 'notification_rules',
                       type_='check')
    op.create_check_constraint('ck_notification_rules_event_type',
                               'notification_rules', _TYPES_OLD)

    op.execute("DELETE FROM email_logs WHERE trigger = 'material_request'")
    with op.batch_alter_table('email_logs', schema=None) as batch_op:
        batch_op.drop_constraint('ck_email_logs_trigger', type_='check')
        batch_op.create_check_constraint('ck_email_logs_trigger', _TRIGGERS_OLD)

    with op.batch_alter_table('material_reservations', schema=None) as batch_op:
        batch_op.drop_constraint('fk_material_res_reviewed_by', type_='foreignkey')
        batch_op.drop_column('review_comment')
        batch_op.drop_column('reviewed_by_id')
        batch_op.drop_column('reviewed_at')
        batch_op.drop_column('trainer_submitted_at')
```

- [ ] **Step 8: Прогнати міграцію в обидва боки на dev-БД**

```bash
venv/Scripts/flask db upgrade
venv/Scripts/flask db heads
venv/Scripts/flask db downgrade
venv/Scripts/flask db upgrade
```

Expected: `heads` показує РІВНО одну голову `mat_request_20260922`;
downgrade і повторний upgrade проходять без помилок.

Не грепати вивід `flask db upgrade` на предмет успіху — grep ховає помилки.
Дивитись на код виходу й повний вивід.

- [ ] **Step 9: Commit**

```bash
git add app/models/material_reservation.py app/models/email_log.py app/models/notification_rule.py migrations/versions/mat_request_20260922.py tests/test_mm_medic_materials.py
git commit -m "feat(materials): статуси заявки тренера, колонки рішення, міграція"
```

---

## Task 2: Сервіс локальних переходів

Новий файл, а не дописування в `material_reservation_service.py`: той уже
970 рядків і відповідає за розмову з MM Medic. Локальний життєвий цикл —
інша відповідальність, і тримати їх окремо дешевше, ніж розплутувати потім.
Новий сервіс делегує наявному, не дублюючи його.

**Files:**
- Create: `app/services/material_request_service.py`
- Test: `tests/test_mm_medic_materials.py`

**Interfaces:**
- Consumes: з Task 1 — `MaterialReservationStatus.{PENDING_REVIEW, RETURNED,
  LOCAL_STATES}`, `MaterialReservationOrigin.TRAINER_CABINET`, колонки
  `trainer_submitted_at` / `reviewed_at` / `reviewed_by_id` / `review_comment`.
  З наявного `material_reservation_service` — `get_reservation`,
  `external_ref_for`, `submit_request`.
- Produces:
  - `class RequestTransitionError(Exception)`
  - `get_or_create_draft(instance, user) -> MaterialReservation`
  - `save_items(reservation, items) -> None`, де `items` — `list[dict]` з
    ключами `sku` (str), `name` (str|None), `image_url` (str|None),
    `quantity` (int > 0)
  - `submit(reservation, user) -> MaterialReservation`
  - `return_to_trainer(reservation, comment, user) -> MaterialReservation`
  - `reject(reservation, comment, user) -> MaterialReservation`
  - `approve(instance, reservation) -> tuple[bool, object]` (`(ok, result)`)
  - `is_editable_by_trainer(reservation) -> bool`
  - `pending_review_count() -> int`

- [ ] **Step 1: Write the failing test**

Додати в `tests/test_mm_medic_materials.py`:

```python
import pytest

from app.models.material_reservation import (
    MaterialReservationStatus as S, MaterialReservationOrigin as O)


def _draft(app_ctx_instance, user):
    """Чернетка з двома рядками -- спільна заготовка для тестів переходів."""
    from app.services import material_request_service as mrq
    res = mrq.get_or_create_draft(app_ctx_instance, user)
    mrq.save_items(res, [
        {'sku': 'NEEDLE-30G', 'name': 'Голки 30G', 'image_url': None,
         'quantity': 12},
        {'sku': 'TUBE-VAC', 'name': 'Пробірки', 'image_url': None,
         'quantity': 24},
    ])
    return res


def test_submit_moves_draft_to_pending_review(app, instance, trainer_user):
    from app.services import material_request_service as mrq

    res = _draft(instance, trainer_user)
    assert res.status == S.DRAFT

    mrq.submit(res, trainer_user)

    assert res.status == S.PENDING_REVIEW
    assert res.trainer_submitted_at is not None
    assert res.origin == O.TRAINER_CABINET
    assert res.created_by_id == trainer_user.id
    # Кількості тренера лягають у quantity_requested; утримання ще немає.
    assert {i.sku: i.quantity_requested for i in res.items} == {
        'NEEDLE-30G': 12, 'TUBE-VAC': 24}
    assert all(i.quantity_reserved == 0 for i in res.items)


def test_return_to_trainer_stores_comment_and_reopens_form(app, instance,
                                                           trainer_user, admin_user):
    from app.services import material_request_service as mrq

    res = _draft(instance, trainer_user)
    mrq.submit(res, trainer_user)
    assert mrq.is_editable_by_trainer(res) is False

    mrq.return_to_trainer(res, '  Забули серветки  ', admin_user)

    assert res.status == S.RETURNED
    assert res.review_comment == 'Забули серветки'
    assert res.reviewed_by_id == admin_user.id
    assert res.reviewed_at is not None
    assert mrq.is_editable_by_trainer(res) is True


def test_resubmit_after_return_clears_the_stale_comment(app, instance,
                                                        trainer_user, admin_user):
    """Коментар стосувався ПОПЕРЕДНЬОЇ версії. Лишити його -- показувати
    тренеру зауваження, яке він щойно виправив цим-таки надсиланням.
    Той самий висновок, що в trainer_cabinet.submit_proposal."""
    from app.services import material_request_service as mrq

    res = _draft(instance, trainer_user)
    mrq.submit(res, trainer_user)
    mrq.return_to_trainer(res, 'Забули серветки', admin_user)

    mrq.submit(res, trainer_user)

    assert res.status == S.PENDING_REVIEW
    assert res.review_comment is None


def test_return_requires_a_reason(app, instance, trainer_user, admin_user):
    from app.services import material_request_service as mrq

    res = _draft(instance, trainer_user)
    mrq.submit(res, trainer_user)

    with pytest.raises(mrq.RequestTransitionError):
        mrq.return_to_trainer(res, '   ', admin_user)
    assert res.status == S.PENDING_REVIEW


def test_reject_closes_the_request_with_a_reason(app, instance, trainer_user,
                                                 admin_user):
    from app.services import material_request_service as mrq

    res = _draft(instance, trainer_user)
    mrq.submit(res, trainer_user)

    mrq.reject(res, 'Захід не потребує матеріалів', admin_user)

    assert res.status == S.REJECTED
    assert res.review_comment == 'Захід не потребує матеріалів'
    assert mrq.is_editable_by_trainer(res) is False


def test_submit_refuses_anything_but_draft_or_returned(app, instance,
                                                       trainer_user):
    from app.services import material_request_service as mrq

    res = _draft(instance, trainer_user)
    res.status = S.RESERVED

    with pytest.raises(mrq.RequestTransitionError):
        mrq.submit(res, trainer_user)


def test_submit_refuses_an_empty_request(app, instance, trainer_user):
    """Порожня заявка -- це не заявка: відповідальний отримав би лист ні про що."""
    from app.services import material_request_service as mrq

    res = mrq.get_or_create_draft(instance, trainer_user)
    mrq.save_items(res, [])

    with pytest.raises(mrq.RequestTransitionError):
        mrq.submit(res, trainer_user)


def test_approve_delegates_to_submit_request_and_advances(app, instance,
                                                          trainer_user, monkeypatch):
    from app.services import material_request_service as mrq

    res = _draft(instance, trainer_user)
    mrq.submit(res, trainer_user)
    sent = {}

    class _Ok:
        ok = True
        data = {'reservation': {'items': [
            {'sku': 'NEEDLE-30G', 'name': 'Голки 30G', 'quantity_requested': 12},
            {'sku': 'TUBE-VAC', 'name': 'Пробірки', 'quantity_requested': 24},
        ]}}

    def _fake_submit_request(inst, items):
        sent['items'] = items
        res.status = S.SUBMITTED
        return True, _Ok(), res

    monkeypatch.setattr(mrq.mrs, 'submit_request', _fake_submit_request)

    ok, _result = mrq.approve(instance, res)

    assert ok is True
    assert res.status == S.SUBMITTED
    assert sorted(sent['items'], key=lambda i: i['sku']) == [
        {'sku': 'NEEDLE-30G', 'quantity': 12},
        {'sku': 'TUBE-VAC', 'quantity': 24},
    ]


def test_approve_keeps_pending_review_when_partner_fails(app, instance,
                                                         trainer_user, monkeypatch):
    """Найважливіший тест задачі: стан «начебто погодили, а не пішло» має
    бути неможливим."""
    from app.services import material_request_service as mrq

    res = _draft(instance, trainer_user)
    mrq.submit(res, trainer_user)

    class _Fail:
        ok = False
        data = {'status': 'stock_shortfall'}

    monkeypatch.setattr(mrq.mrs, 'submit_request',
                        lambda inst, items: (False, _Fail(), None))

    ok, _result = mrq.approve(instance, res)

    assert ok is False
    assert res.status == S.PENDING_REVIEW


def test_second_approval_loses_the_race_instead_of_double_sending(app, instance,
                                                                  trainer_user,
                                                                  monkeypatch):
    """Двоє відповідальних тиснуть «Погодити». Другий мусить отримати відмову,
    а не створити другий документ."""
    from app.services import material_request_service as mrq

    res = _draft(instance, trainer_user)
    mrq.submit(res, trainer_user)
    calls = []

    class _Ok:
        ok = True
        data = {'reservation': {'items': []}}

    def _fake_submit_request(inst, items):
        calls.append(items)
        res.status = S.SUBMITTED
        return True, _Ok(), res

    monkeypatch.setattr(mrq.mrs, 'submit_request', _fake_submit_request)

    mrq.approve(instance, res)
    with pytest.raises(mrq.RequestTransitionError):
        mrq.approve(instance, res)

    assert len(calls) == 1
```

Фікстури `instance`, `trainer_user`, `admin_user` — узяти з наявного
`tests/conftest.py`, якщо там є такі; якщо немає, додати локальні фікстури
у файл тесту, і ОБОВ'ЯЗКОВО прибрати створених користувачів у teardown
(інакше впаде `test_api_v1_clients`):

```python
@pytest.fixture
def trainer_user(app):
    from app.extensions import db
    from app.models.user import User
    user = User(email='trainer-mat@example.com', email_confirmed=True)
    user.set_password('x')
    db.session.add(user)
    db.session.commit()
    yield user
    db.session.delete(user)
    db.session.commit()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `venv/Scripts/python -m pytest tests/test_mm_medic_materials.py -k "submit or return_to_trainer or reject or approve" -v`

Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.material_request_service'`.

- [ ] **Step 3: Написати сервіс**

Створити `app/services/material_request_service.py`:

```python
"""Локальний життєвий цикл заявки тренера на витратні матеріали.

Заявка -- це той самий `MaterialReservation`, що дозріває: три локальні
стани (`draft` -> `pending_review` -> погоджено) стоять ПЕРЕД наявним
`submitted`, з якого починається розмова з MM Medic.

Межа з `material_reservation_service` навмисна. Там -- усе, що стосується
партнера: підпис, ретраї, дзеркалення відповіді, звірка. Тут -- лише
переходи, які нікуди не летять. `approve()` -- єдина точка, де одне
викликає друге, і вона делегує наявному `submit_request()`, а не пише
другий його варіант.
"""
import logging
from datetime import datetime, timezone

from app.extensions import db
from app.models.material_reservation import (
    MaterialReservation,
    MaterialReservationItem,
    MaterialReservationOrigin,
    MaterialReservationStatus,
)
from app.services import material_reservation_service as mrs

logger = logging.getLogger(__name__)

# Стани, з яких тренер може подати. `returned` тут разом із `draft`: заявку
# повернули саме для того, щоб він виправив і надіслав знову.
_SUBMITTABLE = (MaterialReservationStatus.DRAFT,
                MaterialReservationStatus.RETURNED)

# Стани, у яких відповідальний ухвалює рішення.
_REVIEWABLE = (MaterialReservationStatus.PENDING_REVIEW,)


class RequestTransitionError(Exception):
    """Перехід, якого поточний стан не дозволяє.

    Окремий тип, а не ValueError: роути ловлять саме його і показують текст
    людині, тоді як ValueError з глибини ORM має лишитись помилкою 500.
    Той самий патерн, що `ProposalTransitionError` у trainer_cabinet.py.
    """


def get_or_create_draft(instance, user) -> MaterialReservation:
    """Заявка цього заходу; якщо її ще немає -- нова чернетка.

    Рядок один на захід (`external_ref` унікальний), тож повторний виклик
    повертає ту саму заявку, а не плодить другу. `created_by_id`
    проставляється лише при створенні: якщо заявку колись завів адмін і
    тренер відкрив її пізніше, авторство не переписується під тренера.
    """
    reservation = mrs.get_reservation(instance.id)
    if reservation is not None:
        return reservation
    reservation = MaterialReservation(
        instance_id=instance.id,
        external_ref=mrs.external_ref_for(instance.id),
        status=MaterialReservationStatus.DRAFT,
        origin=MaterialReservationOrigin.TRAINER_CABINET,
        created_by_id=getattr(user, 'id', None),
    )
    db.session.add(reservation)
    db.session.commit()
    return reservation


def save_items(reservation, items) -> None:
    """Переписати перелік заявки з того, що надіслала форма.

    `items` -- список dict'ів {sku, name, image_url, quantity}. Кількість
    лягає в `quantity_requested` («скільки просив тренер»), `quantity_reserved`
    лишається нулем: утримання з'являється лише після погодження на MM Medic.

    Рядки, яких у `items` немає, ВИДАЛЯЄМО, а наявні оновлюємо на місці -- у
    `material_reservation_items` є unique (reservation_id, sku), і видалення
    з наступною вставкою того самого sku в одній транзакції дало б
    IntegrityError на порядку flush'ів.
    """
    incoming = {}
    for raw in items or []:
        sku = (raw.get('sku') or '').strip()
        quantity = raw.get('quantity')
        if not sku or not isinstance(quantity, int) or quantity <= 0:
            continue
        incoming[sku] = raw

    existing = {item.sku: item for item in reservation.items}

    for sku, item in existing.items():
        if sku not in incoming:
            reservation.items.remove(item)

    for sku, raw in incoming.items():
        item = existing.get(sku)
        if item is None:
            item = MaterialReservationItem(sku=sku, quantity_reserved=0)
            reservation.items.append(item)
        item.name = mrs.trim(raw.get('name'), 255)
        item.image_url = mrs.trim(raw.get('image_url'), 500)
        item.quantity_requested = raw['quantity']

    db.session.commit()


def is_editable_by_trainer(reservation) -> bool:
    """Чи може тренер зараз правити цю заявку.

    None -- заявки ще немає, тобто форма порожня й редагована.
    """
    if reservation is None:
        return True
    return reservation.status in _SUBMITTABLE


def submit(reservation, user) -> MaterialReservation:
    """Тренер надіслав заявку на перевірку. Нікуди не летить -- лише статус."""
    if reservation.status not in _SUBMITTABLE:
        raise RequestTransitionError(
            'Надіслати можна лише чернетку або повернену заявку')
    if not any((item.quantity_requested or 0) > 0 for item in reservation.items):
        raise RequestTransitionError('Заявка порожня: додайте хоча б одну позицію')

    reservation.status = MaterialReservationStatus.PENDING_REVIEW
    reservation.origin = MaterialReservationOrigin.TRAINER_CABINET
    reservation.trainer_submitted_at = datetime.now(timezone.utc)
    # Коментар стосувався ПОПЕРЕДНЬОЇ версії; це надсилання його виправляє.
    reservation.review_comment = None
    reservation.reviewed_at = None
    reservation.reviewed_by_id = None
    if getattr(user, 'id', None) is not None:
        reservation.created_by_id = user.id
    db.session.commit()
    return reservation


def _decide(reservation, status, comment, user, empty_message):
    """Спільне тіло «повернути» і «відхилити»: обидва потребують причини."""
    if reservation.status not in _REVIEWABLE:
        raise RequestTransitionError('Рішення можна ухвалити лише щодо заявки на перевірці')
    text = (comment or '').strip()
    if not text:
        raise RequestTransitionError(empty_message)

    reservation.status = status
    reservation.review_comment = text
    reservation.reviewed_at = datetime.now(timezone.utc)
    reservation.reviewed_by_id = getattr(user, 'id', None)
    db.session.commit()
    return reservation


def return_to_trainer(reservation, comment, user) -> MaterialReservation:
    return _decide(reservation, MaterialReservationStatus.RETURNED, comment, user,
                   'Вкажіть, що саме тренеру треба виправити')


def reject(reservation, comment, user) -> MaterialReservation:
    return _decide(reservation, MaterialReservationStatus.REJECTED, comment, user,
                   'Вкажіть причину відхилення')


def approve(instance, reservation):
    """Погодити й надіслати на MM Medic. Повертає (ok, result).

    Гейт на статус стоїть ПЕРЕД викликом партнера і є єдиним запобіжником
    від подвійного надсилання, коли двоє відповідальних тиснуть кнопку
    одночасно: перший переводить рядок у `submitted`, другий уже не проходить
    перевірку й отримує помилку замість другого документа.

    При збої партнера статус НЕ чіпаємо: заявка лишається на перевірці, і
    кнопку можна натиснути ще раз. Стан «начебто погодили, а насправді не
    пішло» тут неможливий саме тому, що статус рухає `submit_request()`, а
    не ця функція.
    """
    if reservation.status not in _REVIEWABLE:
        raise RequestTransitionError('Погодити можна лише заявку на перевірці')

    items = [{'sku': item.sku, 'quantity': item.quantity_requested}
             for item in reservation.items
             if (item.quantity_requested or 0) > 0]
    if not items:
        raise RequestTransitionError('Заявка порожня: погоджувати нічого')

    reviewer_id = mrs._submitter_id()
    ok, result, _reservation = mrs.submit_request(instance, items)
    if not ok:
        logger.warning('Не вдалося надіслати заявку %s на MM Medic',
                       reservation.external_ref)
        return False, result

    reservation.reviewed_at = datetime.now(timezone.utc)
    reservation.reviewed_by_id = reviewer_id
    db.session.commit()
    return True, result


def pending_review_count() -> int:
    """Скільки заявок чекає перевірки -- для лічильника в сайдбарі."""
    return (MaterialReservation.query
            .filter(MaterialReservation.status
                    == MaterialReservationStatus.PENDING_REVIEW)
            .count())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `venv/Scripts/python -m pytest tests/test_mm_medic_materials.py -v`

Expected: PASS, усі.

- [ ] **Step 5: Commit**

```bash
git add app/services/material_request_service.py tests/test_mm_medic_materials.py
git commit -m "feat(materials): сервіс локальних переходів заявки тренера"
```

---

## Task 3: Запобіжник вебхука

Штовх статусу від MM Medic не має права перезаписати локальний стан. Для
`pending_review` документа на тому боці ще не існує — але `external_ref`
живе довше за один цикл, і пізній штовх зі старого циклу затер би свіжу
заявку.

**Files:**
- Modify: `app/api/mm_status.py`
- Test: `tests/test_material_notifications.py`

**Interfaces:**
- Consumes: з Task 1 — `MaterialReservationStatus.LOCAL_STATES`.
- Produces: нічого для інших задач.

- [ ] **Step 1: Write the failing test**

Додати в `tests/test_material_notifications.py`. Поруч із наявними тестами
зворотного вебхука вже є хелпер, що підписує запит — використати його; якщо
він приватний до файлу, узяти його ім'я з наявних тестів вебхука в цьому ж
файлі.

```python
def test_status_push_does_not_overwrite_a_local_state(app, client, instance):
    """Пізній штовх зі старого циклу не має з'їсти заявку, яку тренер щойно
    подав: локальним станам документа на MM Medic не відповідає взагалі."""
    from app.extensions import db
    from app.models.material_reservation import (
        MaterialReservation, MaterialReservationStatus as S)
    from app.services import material_reservation_service as mrs

    ref = mrs.external_ref_for(instance.id)
    reservation = MaterialReservation(
        instance_id=instance.id, external_ref=ref,
        status=S.PENDING_REVIEW)
    db.session.add(reservation)
    db.session.commit()

    response = _post_status(client, {'external_ref': ref, 'status': 'cancelled'})

    assert response.status_code == 200
    assert response.get_json()['status'] == 'local_state'
    db.session.refresh(reservation)
    assert reservation.status == S.PENDING_REVIEW
```

- [ ] **Step 2: Run test to verify it fails**

Run: `venv/Scripts/python -m pytest tests/test_material_notifications.py -k local_state -v`

Expected: FAIL — статус став `cancelled`, або відповідь не містить
`local_state`.

- [ ] **Step 3: Додати гілку в приймач**

У `app/api/mm_status.py`, у `reservation_status()`, ОДРАЗУ після того як
знайдено наявний `reservation` і перед тим, як застосовується `local_status`
(тобто після блоку `if reservation is None: ...`):

```python
    else:
        # Локальний стан -- документа на MM Medic для цього ref ще не існує
        # (заявка тренера в кабінеті ІПРМ, чернетка). `external_ref` живе
        # довше за один цикл заходу, тож сюди може прилетіти ПІЗНІЙ штовх зі
        # старого, уже закритого циклу -- і без цієї гілки він перезаписав би
        # свіжу заявку тренера чужим статусом.
        #
        # 200, а не 4xx: для відправника це не помилка, і ретраїв у нього
        # немає. Логуємо, бо мовчазне ігнорування штовха має лишати слід.
        if reservation.status in MaterialReservationStatus.LOCAL_STATES:
            logger.info(
                'MM Medic status push ignored: ref=%s is in local state %s '
                '(remote status=%r)',
                external_ref, reservation.status, remote_status)
            return jsonify({'status': 'local_state'}), 200
```

`MaterialReservationStatus` у цьому модулі вже імпортований.

- [ ] **Step 4: Run tests to verify they pass**

Run: `venv/Scripts/python -m pytest tests/test_material_notifications.py -v`

Expected: PASS, усі, включно з наявними тестами вебхука.

- [ ] **Step 5: Commit**

```bash
git add app/api/mm_status.py tests/test_material_notifications.py
git commit -m "fix(materials): штовх статусу не перезаписує локальний стан заявки"
```

---

## Task 4: Чотири листи

**Files:**
- Modify: `app/services/email_service.py` (додати методи; розширити
  `_send_to_recipients` необов'язковим `idempotency_key`)
- Create: `app/templates/emails/material_request_submitted.html`
- Create: `app/templates/emails/material_request_returned.html`
- Create: `app/templates/emails/material_request_approved.html`
- Create: `app/templates/emails/material_request_rejected.html`
- Test: `tests/test_material_notifications.py`

**Interfaces:**
- Consumes: з Task 1 — тригер `'material_request'`, тип події
  `'material_request'`; з Task 2 — `reservation.review_comment`.
- Produces:
  - `EmailService.send_material_request_submitted(reservation, instance) -> list`
  - `EmailService.send_material_request_decision(reservation, instance, decision) -> object|None`,
    де `decision` ∈ `{'returned', 'approved', 'rejected'}`

- [ ] **Step 1: Write the failing test**

Додати в `tests/test_material_notifications.py`:

```python
def test_submitted_letter_goes_to_the_configured_recipients(app, instance,
                                                            monkeypatch):
    from app.services.email_service import EmailService

    sent = []
    monkeypatch.setattr(
        'app.services.notification_recipients.resolve',
        lambda event_type, instance=None, new_status=None: (
            ['a@example.com', 'b@example.com']
            if event_type == 'material_request' else []))
    monkeypatch.setattr(EmailService, 'send_email',
                        staticmethod(lambda **kw: sent.append(kw) or object()))

    reservation = _reservation_with_items(instance)
    EmailService.send_material_request_submitted(reservation, instance)

    assert [kw['to'] for kw in sent] == ['a@example.com', 'b@example.com']
    assert all(kw['trigger'] == 'material_request' for kw in sent)
    assert all(kw['idempotency_key'] ==
               f'matreq:{reservation.external_ref}:submitted' for kw in sent)


def test_decision_letters_render_for_every_decision(app, instance, trainer_user):
    """Рендер усіх чотирьох листів -- шаблон, якого немає, падає лише тут."""
    from app.services.email_service import EmailService

    reservation = _reservation_with_items(instance)
    reservation.created_by_id = trainer_user.id
    reservation.review_comment = 'Забули серветки'

    for decision in ('returned', 'approved', 'rejected'):
        entry = EmailService.send_material_request_decision(
            reservation, instance, decision)
        assert entry is not None, decision


def test_decision_letter_is_skipped_when_nobody_to_write_to(app, instance):
    from app.services.email_service import EmailService

    reservation = _reservation_with_items(instance)
    reservation.created_by_id = None

    assert EmailService.send_material_request_decision(
        reservation, instance, 'approved') is None


def test_idempotency_key_differs_per_decision(app, instance, trainer_user,
                                              monkeypatch):
    """Дві заявки одного тренера, розведені поспіль, не мають злитись у
    60-секундному вікні дедупу."""
    from app.services.email_service import EmailService

    sent = []
    monkeypatch.setattr(EmailService, 'send_email',
                        staticmethod(lambda **kw: sent.append(kw) or object()))

    reservation = _reservation_with_items(instance)
    reservation.created_by_id = trainer_user.id
    reservation.review_comment = 'Причина'

    EmailService.send_material_request_decision(reservation, instance, 'returned')
    EmailService.send_material_request_decision(reservation, instance, 'approved')

    keys = [kw['idempotency_key'] for kw in sent]
    assert keys == [f'matreq:{reservation.external_ref}:returned',
                    f'matreq:{reservation.external_ref}:approved']
    assert len(set(keys)) == 2
```

Хелпер `_reservation_with_items` додати у той самий файл:

```python
def _reservation_with_items(instance):
    from app.extensions import db
    from app.models.material_reservation import (
        MaterialReservation, MaterialReservationItem,
        MaterialReservationStatus as S)
    from app.services import material_reservation_service as mrs

    reservation = MaterialReservation(
        instance_id=instance.id,
        external_ref=mrs.external_ref_for(instance.id),
        status=S.PENDING_REVIEW)
    reservation.items.append(MaterialReservationItem(
        sku='NEEDLE-30G', name='Голки 30G', quantity_requested=12,
        quantity_reserved=0))
    db.session.add(reservation)
    db.session.commit()
    return reservation
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `venv/Scripts/python -m pytest tests/test_material_notifications.py -k "submitted_letter or decision_letter or idempotency_key_differs" -v`

Expected: FAIL — `AttributeError: type object 'EmailService' has no attribute 'send_material_request_submitted'`.

- [ ] **Step 3: Прокинути `idempotency_key` крізь `_send_to_recipients`**

У `app/services/email_service.py:1800` — розширити підпис і передачу:

```python
    def _send_to_recipients(recipients, *, subject, template_name,
                            context, trigger, registration_id,
                            idempotency_key=None):
```

і в тілі, у виклику `EmailService.send_email(...)`, додати аргумент:

```python
                    idempotency_key=idempotency_key,
```

Решту тіла (try/rollback на кожній ітерації) НЕ чіпати. Наявні виклики не
передають нового аргументу й працюють як раніше.

- [ ] **Step 4: Додати два методи**

У `app/services/email_service.py`, поруч із `send_materials_actuals_reminder`:

```python
    @staticmethod
    def send_material_request_submitted(reservation, instance):
        """Тренер подав заявку -> лист відповідальним.

        Одержувачі -- через `notification_recipients.resolve`, а не список
        адрес у коді: склад відповідальних змінюється без деплою.

        `idempotency_key` обходить 60-секундний дедуп (адреса+тригер). Без
        нього дві заявки від різних тренерів, подані в ту саму хвилину на ту
        саму адресу, дали б один лист замість двох.
        """
        from app.services.notification_recipients import resolve
        recipients = resolve('material_request', instance=instance)
        if not recipients:
            return []
        ctx = EmailService._material_request_context(reservation, instance)
        return EmailService._send_to_recipients(
            recipients,
            subject=f'Заявка на матеріали: {ctx["event_title"]}',
            template_name='material_request_submitted',
            context=ctx,
            trigger='material_request',
            registration_id=None,
            idempotency_key=f'matreq:{reservation.external_ref}:submitted',
        )

    # Рішення -> (шаблон, тема). Словник, а не три майже однакові методи:
    # відрізняються лише ці два рядки, решта тіла спільна.
    _MATERIAL_REQUEST_DECISIONS = {
        'returned': ('material_request_returned',
                     'Заявку на матеріали повернуто: %(title)s'),
        'approved': ('material_request_approved',
                     'Заявку на матеріали прийнято: %(title)s'),
        'rejected': ('material_request_rejected',
                     'Заявку на матеріали відхилено: %(title)s'),
    }

    @staticmethod
    def send_material_request_decision(reservation, instance, decision):
        """Рішення відповідального -> лист тренеру, що подав заявку.

        Адресат -- `created_by_id` (той, хто натиснув «Відправити»), а не
        правило з ролями: тренер може не бути ні адміном, ні менеджером, і
        rule-based список його не дістане. Той самий висновок, що в
        `send_materials_trainer_confirmed`.

        Повертає None, коли писати нікому: заявка старіша за колонку,
        користувача видалили, або в нього немає пошти. Це звичайний випадок,
        а не збій -- ні винятку, ні тривожного рядка в лог.
        """
        template_name, subject_tpl = (
            EmailService._MATERIAL_REQUEST_DECISIONS.get(decision, (None, None)))
        if template_name is None:
            logger.warning('невідоме рішення по заявці: %r', decision)
            return None
        user = reservation.created_by
        if user is None or not user.email:
            return None

        ctx = EmailService._material_request_context(reservation, instance)
        ctx['comment'] = reservation.review_comment
        ctx['trainer_url'] = url_for(
            'trainer_cabinet.materials_request',
            instance_id=reservation.instance_id, _external=True)
        event_title = ctx['event_title']
        return EmailService.send_email(
            to=user.email,
            subject=lambda: _(subject_tpl, title=event_title),
            template_name=template_name,
            context=ctx,
            trigger='material_request',
            registration_id=None,
            idempotency_key=f'matreq:{reservation.external_ref}:{decision}',
        )

    @staticmethod
    def _material_request_context(reservation, instance):
        """Спільний контекст усіх чотирьох листів заявки."""
        return {
            'reservation': reservation,
            'instance': instance,
            'event_title': ((instance.effective_title if instance else None)
                            or 'Захід'),
            'event_date': instance.start_date if instance else None,
            'items': [item for item in reservation.items
                      if (item.quantity_requested or 0) > 0],
            'admin_url': EmailService._materials_admin_url(
                instance.id if instance else reservation.instance_id),
        }
```

`_materials_admin_url` уже існує в цьому класі (використовується
`send_materials_actuals_reminder`).

- [ ] **Step 5: Написати чотири шаблони**

Базовий шаблон -- `emails/base.html`, макроси -- `emails/_macros.html`
(перевірено по `materials_actuals_reminder.html`). Нижче наведено тіло;
за потреби взяти з `_macros.html` готові `button_primary`, `detail_row`,
`alert_warning`, `spacer` замість сирої розмітки -- саме так зроблено в
наявних листах матеріалів.

`material_request_submitted.html` — тіло:

```html
{% extends 'emails/base.html' %}
{% block content %}
<h2>{{ _('Нова заявка на витратні матеріали') }}</h2>
<p>{{ _('Захід') }}: <strong>{{ event_title }}</strong>{% if event_date %} &middot; {{ event_date.strftime('%d.%m.%Y') }}{% endif %}</p>
{% if reservation.created_by %}
<p>{{ _('Подав') }}: {{ reservation.created_by.email }}</p>
{% endif %}
<table>
  <thead>
    <tr><th>{{ _('Матеріал') }}</th><th>{{ _('Артикул') }}</th><th>{{ _('Кількість') }}</th></tr>
  </thead>
  <tbody>
    {% for item in items %}
    <tr><td>{{ item.name or item.sku }}</td><td>{{ item.sku }}</td><td>{{ item.quantity_requested }}</td></tr>
    {% endfor %}
  </tbody>
</table>
{% if reservation.trainer_comment %}
<p>{{ _('Коментар тренера') }}: {{ reservation.trainer_comment }}</p>
{% endif %}
<p><a href="{{ admin_url }}">{{ _('Відкрити заявку') }}</a></p>
<p>{{ _('Заявка не піде на склад, доки її не погодить хтось із відповідальних.') }}</p>
{% endblock %}
```

`material_request_returned.html`:

```html
{% extends 'emails/base.html' %}
{% block content %}
<h2>{{ _('Заявку на матеріали повернуто на доопрацювання') }}</h2>
<p>{{ _('Захід') }}: <strong>{{ event_title }}</strong>{% if event_date %} &middot; {{ event_date.strftime('%d.%m.%Y') }}{% endif %}</p>
<p>{{ _('Що треба виправити') }}: {{ comment }}</p>
<p><a href="{{ trainer_url }}">{{ _('Відкрити заявку') }}</a></p>
{% endblock %}
```

`material_request_approved.html`:

```html
{% extends 'emails/base.html' %}
{% block content %}
<h2>{{ _('Заявку на матеріали прийнято') }}</h2>
<p>{{ _('Захід') }}: <strong>{{ event_title }}</strong>{% if event_date %} &middot; {{ event_date.strftime('%d.%m.%Y') }}{% endif %}</p>
<p>{{ _('Заявку передано на склад. Окремих дій від вас не потрібно.') }}</p>
{% endblock %}
```

`material_request_rejected.html`:

```html
{% extends 'emails/base.html' %}
{% block content %}
<h2>{{ _('Заявку на матеріали відхилено') }}</h2>
<p>{{ _('Захід') }}: <strong>{{ event_title }}</strong>{% if event_date %} &middot; {{ event_date.strftime('%d.%m.%Y') }}{% endif %}</p>
<p>{{ _('Причина') }}: {{ comment }}</p>
{% endblock %}
```

Базовий шаблон — `emails/base.html`, макроси — `emails/_macros.html`
(перевірено по першому рядку `materials_actuals_reminder.html`). Замість
сирої розмітки можна взяти готові `button_primary`, `detail_row`,
`alert_warning`, `spacer` з `_macros.html` — саме так зроблено в наявних
листах матеріалів. Зламаний Jinja або відсутній шаблон падає в тесті
`test_decision_letters_render_for_every_decision`.

- [ ] **Step 6: Run tests to verify they pass**

Run: `venv/Scripts/python -m pytest tests/test_material_notifications.py -v`

Expected: PASS, усі.

- [ ] **Step 7: Commit**

```bash
git add app/services/email_service.py app/templates/emails/material_request_submitted.html app/templates/emails/material_request_returned.html app/templates/emails/material_request_approved.html app/templates/emails/material_request_rejected.html tests/test_material_notifications.py
git commit -m "feat(materials): листи заявки тренера -- подання й три рішення"
```

---

## Task 5: Сторінка тренера — роути й проєкція каталогу

**Files:**
- Modify: `app/trainer_cabinet/routes.py`
- Modify: `app/trainer_cabinet/forms.py`
- Modify: `app/services/material_request_service.py` (додати
  `catalog_for_trainer`, `prefill_rows`)
- Test: `tests/test_trainer_cabinet_materials.py` (новий файл)

**Interfaces:**
- Consumes: з Task 2 — увесь `material_request_service`; з Task 4 —
  `EmailService.send_material_request_submitted`; наявні
  `mrs.get_catalog`, `mrs.kits_for_instance`, `upcoming_instances`.
- Produces:
  - ендпоінт `trainer_cabinet.materials` (`GET /trainer/materials`)
  - ендпоінт `trainer_cabinet.materials_request`
    (`GET, POST /trainer/materials/<int:instance_id>`)
  - ендпоінт `trainer_cabinet.materials_catalog`
    (`GET /trainer/materials/<int:instance_id>/catalog?q=`), JSON
  - `material_request_service.catalog_for_trainer(search=None) -> tuple[list[dict], bool]`
    — `([{sku, name, image_url}], unavailable)`
  - `material_request_service.prefill_rows(instance) -> list[dict]`
    — `[{sku, name, image_url, quantity}]`

- [ ] **Step 1: Write the failing test**

Створити `tests/test_trainer_cabinet_materials.py`:

```python
"""Сторінка заявки на матеріали в кабінеті тренера."""
import pytest

from app.extensions import db
from app.models.material_reservation import MaterialReservationStatus as S


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


def test_submit_creates_a_pending_review_request_and_mails(client, trainer_user,
                                                           instance, monkeypatch):
    from app.services import material_request_service as mrq
    from app.services.email_service import EmailService

    mailed = []
    monkeypatch.setattr(EmailService, 'send_material_request_submitted',
                        staticmethod(lambda res, inst: mailed.append(res)))
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
    assert len(mailed) == 1


def test_save_draft_does_not_mail(client, trainer_user, instance, monkeypatch):
    from app.services import material_request_service as mrq
    from app.services.email_service import EmailService

    mailed = []
    monkeypatch.setattr(EmailService, 'send_material_request_submitted',
                        staticmethod(lambda res, inst: mailed.append(res)))
    _login(client, trainer_user)

    client.post(f'/trainer/materials/{instance.id}', data={
        'csrf_token': _csrf(client, f'/trainer/materials/{instance.id}'),
        'sku': ['NEEDLE-30G'], 'quantity': ['5'], 'action': 'draft',
    })

    assert mrq.mrs.get_reservation(instance.id).status == S.DRAFT
    assert mailed == []


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
```

Фікстури `instance`, `foreign_instance`, `kit`, `trainer_user` і хелпери
`_login` / `_csrf` — додати у цей файл. `_login` мусить використовувати
`switch_user`, якщо тест міняє користувача всередині; для одного
користувача достатньо звичайного логіну через форму. Усіх створених
користувачів прибрати в teardown.

- [ ] **Step 2: Run tests to verify they fail**

Run: `venv/Scripts/python -m pytest tests/test_trainer_cabinet_materials.py -v`

Expected: FAIL — 404 на всіх роутах (`/trainer/materials` не існує).

- [ ] **Step 3: Додати проєкцію каталогу й префіл у сервіс**

У кінець `app/services/material_request_service.py`:

```python
def catalog_for_trainer(search=None):
    """Каталог MM Medic у вигляді, придатному для очей тренера.

    Повертає (items, unavailable). `items` -- лише sku, назва й зображення:
    залишки, ціни й min_stock не ховаються стилями, а НЕ НАДСИЛАЮТЬСЯ. Ціни
    MM Medic -- закупівельні, і зовнішній людині їх знати не треба.

    `unavailable=True` -- партнер мовчить. Це не помилка сторінки: форма
    відкривається з локального комплекту й працює на відправку, недоступним
    стає лише пошук.
    """
    items, error, _stale = mrs.get_catalog(search=search)
    if error:
        return [], True
    return [
        {'sku': raw.get('sku'),
         'name': raw.get('name'),
         'image_url': raw.get('image_url')}
        for raw in (items or [])
        if raw.get('sku')
    ], False


def prefill_rows(instance):
    """Рядки, якими відкривається порожня заявка: стандартний комплект курсу.

    `kits_for_instance` віддає курсові комплекти І універсальні
    (`course_id IS NULL`). Беремо позиції з усіх активних, складаючи
    кількості на однаковий sku: два комплекти, що обидва містять серветки,
    мають дати одну позицію, а не дві.
    """
    merged = {}
    for kit in mrs.kits_for_instance(instance):
        for item in kit.items:
            row = merged.setdefault(item.sku, {
                'sku': item.sku, 'name': item.name_snapshot,
                'image_url': None, 'quantity': 0,
            })
            row['quantity'] += item.quantity or 0
    return [row for row in merged.values() if row['quantity'] > 0]


def rows_for_form(instance, reservation):
    """Що показати у формі: збережена заявка, якщо вона є, інакше префіл."""
    if reservation is not None and reservation.items:
        return [{'sku': item.sku, 'name': item.name,
                 'image_url': item.image_url,
                 'quantity': item.quantity_requested or 0}
                for item in reservation.items]
    return prefill_rows(instance)
```

Дві різні моделі, дві різні назви поля, і сплутати їх легко:
`MaterialKitItem.name_snapshot` (перевірено, `app/models/material_kit.py:69`)
проти `MaterialReservationItem.name` у `rows_for_form` вище. `quantity` у
комплекті — NOT NULL із CHECK > 0, тож відсів `quantity > 0` у кінці
`prefill_rows` — страховка від складання порожніх комплектів, а не фільтр
реальних нулів.

- [ ] **Step 4: Додати форму**

У `app/trainer_cabinet/forms.py`:

```python
class MaterialRequestForm(FlaskForm):
    """Заявка на матеріали. Рядки приходять паралельними списками
    `sku[]`/`quantity[]`, тож полів під них тут немає -- WTForms не вміє
    динамічну кількість рядків без FieldList, а FieldList тут дав би
    складність без користі. Форма потрібна заради CSRF і коментаря.
    """
    comment = TextAreaField(_l('Коментар до заявки'), validators=[Optional()])
```

- [ ] **Step 5: Додати три роути**

У `app/trainer_cabinet/routes.py`:

```python
def _own_instance(instance_id):
    """Захід цього тренера або 404.

    404, а не 403: стороннього не стосується навіть факт існування заявки.
    Той самий висновок, що в `_own_proposal` вище.
    """
    instance = db.session.get(CourseInstance, instance_id)
    if instance is None:
        abort(404)
    if g.trainer.id not in {t.id for t in instance.effective_trainers}:
        abort(404)
    return instance


def _form_rows():
    """Рядки з POST'а: паралельні списки sku[] і quantity[].

    Невалідні (порожній sku, нечислова або недодатна кількість) мовчки
    відкидаються: це не помилка введення, а вилучений рядок -- саме так
    працює кнопка «прибрати» у формі.
    """
    skus = request.form.getlist('sku')
    quantities = request.form.getlist('quantity')
    names = request.form.getlist('name')
    images = request.form.getlist('image_url')
    rows = []
    for index, sku in enumerate(skus):
        sku = (sku or '').strip()
        if not sku:
            continue
        try:
            quantity = int(quantities[index])
        except (IndexError, TypeError, ValueError):
            continue
        if quantity <= 0:
            continue
        rows.append({
            'sku': sku,
            'name': names[index] if index < len(names) else None,
            'image_url': images[index] if index < len(images) else None,
            'quantity': quantity,
        })
    return rows


@trainer_cabinet_bp.route('/materials')
@trainer_required
def materials():
    instances = svc.upcoming_instances(g.trainer)
    reservations = {
        inst.id: mrq.mrs.get_reservation(inst.id) for inst in instances
    }
    return render_template('trainer_cabinet/materials.html',
                           trainer=g.trainer,
                           instances=instances,
                           reservations=reservations)


@trainer_cabinet_bp.route('/materials/<int:instance_id>', methods=['GET', 'POST'])
@trainer_required
def materials_request(instance_id):
    instance = _own_instance(instance_id)
    reservation = mrq.mrs.get_reservation(instance_id)
    editable = mrq.is_editable_by_trainer(reservation)
    form = MaterialRequestForm()

    if request.method == 'POST':
        if not editable:
            flash(_('Заявку вже надіслано на перевірку, редагувати її не можна.'),
                  'warning')
            return redirect(url_for('trainer_cabinet.materials_request',
                                    instance_id=instance_id))
        if form.validate_on_submit():
            reservation = mrq.get_or_create_draft(instance, current_user)
            mrq.save_items(reservation, _form_rows())
            reservation.trainer_comment = (form.comment.data or '').strip() or None
            if request.form.get('action') == 'submit':
                try:
                    mrq.submit(reservation, current_user)
                except mrq.RequestTransitionError as exc:
                    db.session.commit()
                    flash(str(exc), 'danger')
                    return redirect(url_for('trainer_cabinet.materials_request',
                                            instance_id=instance_id))
                _notify_material_request(reservation, instance)
                flash(_('Заявку надіслано на перевірку.'), 'success')
            else:
                db.session.commit()
                flash(_('Чернетку збережено.'), 'success')
            return redirect(url_for('trainer_cabinet.materials_request',
                                    instance_id=instance_id))

    if request.method == 'GET':
        form.comment.data = reservation.trainer_comment if reservation else None
    catalog, catalog_unavailable = mrq.catalog_for_trainer()
    return render_template(
        'trainer_cabinet/materials_request.html',
        form=form,
        instance=instance,
        reservation=reservation,
        editable=editable,
        rows=mrq.rows_for_form(instance, reservation),
        catalog=catalog,
        catalog_unavailable=catalog_unavailable,
    )


def _notify_material_request(reservation, instance):
    """Лист відповідальним. Збій пошти не скасовує надсилання -- заявка вже
    збережена (той самий патерн, що `_after_submit` для пропозицій)."""
    from app.services.email_service import EmailService
    try:
        EmailService.send_material_request_submitted(reservation, instance)
    except Exception:
        logger.exception('Не вдалося сповістити про заявку %s',
                         reservation.external_ref)


@trainer_cabinet_bp.route('/materials/<int:instance_id>/catalog')
@trainer_required
@limiter.limit('30 per minute')
def materials_catalog(instance_id):
    """Пошук по каталогу для випадайки «додати позицію».

    Ліміт не декоративний: КОЖЕН запит із непорожнім `q` -- живий HTTP у
    MM Medic (кешується лише нефільтрований каталог, див. `get_catalog`).
    """
    _own_instance(instance_id)
    query = (request.args.get('q') or '').strip()
    items, unavailable = mrq.catalog_for_trainer(search=query or None)
    return jsonify({'items': items[:50], 'unavailable': unavailable})
```

Дописати імпорти на початку файлу: `abort`, `jsonify`, `request`, `flash`,
`redirect`, `url_for` з `flask` (частина вже є — звірити), `current_user` з
`flask_login`, `db` з `app.extensions`, `limiter` з `app.extensions`,
`CourseInstance` з `app.models.course_instance`,
`from app.services import material_request_service as mrq`,
`from app.trainer_cabinet.forms import MaterialRequestForm`,
`from flask_babel import gettext as _`.

- [ ] **Step 6: Run tests to verify they pass**

Run: `venv/Scripts/python -m pytest tests/test_trainer_cabinet_materials.py -v`

Expected: PASS, усі сім.

- [ ] **Step 7: Commit**

```bash
git add app/trainer_cabinet/routes.py app/trainer_cabinet/forms.py app/services/material_request_service.py tests/test_trainer_cabinet_materials.py
git commit -m "feat(trainer): роути заявки на матеріали й проєкція каталогу"
```

---

## Task 6: Сторінка тренера — шаблони, CSS, JS

**Files:**
- Create: `app/templates/trainer_cabinet/materials.html`
- Create: `app/templates/trainer_cabinet/materials_request.html`
- Create: `app/static/css/page-trainer-materials.css`
- Create: `app/static/js/trainer-materials.js`
- Modify: `app/templates/trainer_cabinet/_nav.html`
- Test: перевірка дизайн-системи (`tests/test_design_system/`)

**Interfaces:**
- Consumes: з Task 5 — ендпоінти `trainer_cabinet.materials`,
  `.materials_request`, `.materials_catalog`; контекст шаблону
  (`form`, `instance`, `reservation`, `editable`, `rows`, `catalog`,
  `catalog_unavailable`).
- Produces: нічого для інших задач.

- [ ] **Step 1: Додати картку в навігацію кабінету**

У `app/templates/trainer_cabinet/_nav.html`, після картки «Анкета тренера»:

```html
  <a href="{{ url_for('trainer_cabinet.materials') }}" class="account-card account-card--link">
    <h3 class="iprm-block-title">{{ _('Матеріали до заходу') }}</h3>
    <p class="account-card__text">{{ _('Заявка на витратні матеріали: перелік, кількості, стан перевірки') }}</p>
  </a>
```

- [ ] **Step 2: Написати шаблон списку**

`app/templates/trainer_cabinet/materials.html` — успадкувати той самий
базовий шаблон, що `trainer_cabinet/profile.html` (звірити його перший
рядок). Таблиця/картки й бейджі — класи дизайн-системи, НЕ власні:

```html
{% extends 'base.html' %}
{% block content %}
<section class="iprm-section">
  <h1 class="iprm-page-title">{{ _('Матеріали до заходу') }}</h1>
  {% if not instances %}
    <p class="empty-state">{{ _('У вас немає найближчих заходів.') }}</p>
  {% else %}
  <ul class="trainer-materials-list">
    {% for instance in instances %}
      {% set reservation = reservations.get(instance.id) %}
      <li class="trainer-materials-list__item">
        <div class="trainer-materials-list__main">
          <a href="{{ url_for('trainer_cabinet.materials_request', instance_id=instance.id) }}">{{ instance.effective_title }}</a>
          <p class="account-card__text">{{ instance.start_date.strftime('%d.%m.%Y') if instance.start_date }}</p>
        </div>
        <span class="badge badge--{{ reservation.status_badge if reservation else 'draft' }}">
          {{ reservation.status_label if reservation else _('Не подано') }}
        </span>
      </li>
    {% endfor %}
  </ul>
  {% endif %}
</section>
{% endblock %}
```

- [ ] **Step 3: Написати шаблон форми**

`app/templates/trainer_cabinet/materials_request.html`:

```html
{% extends 'base.html' %}
{% block styles %}{{ super() }}
<link rel="stylesheet" href="{{ url_for('static', filename='css/page-trainer-materials.css') }}">
{% endblock %}
{% block content %}
<section class="iprm-section">
  <h1 class="iprm-page-title">{{ instance.effective_title }}</h1>
  <p class="account-card__text">
    {{ instance.start_date.strftime('%d.%m.%Y') if instance.start_date }}
    {%- if instance.city %} &middot; {{ instance.city.name }}{% endif %}
  </p>

  {% if reservation and reservation.review_comment %}
    <div class="notice notice--warning">
      <strong>{{ _('Заявку повернуто') }}:</strong> {{ reservation.review_comment }}
    </div>
  {% endif %}

  {% if not editable %}
    <div class="notice notice--info">
      {{ _('Заявку надіслано на перевірку. Редагувати її можна буде, якщо її повернуть.') }}
    </div>
  {% endif %}

  <form method="post" class="trainer-materials-form"
        data-catalog-url="{{ url_for('trainer_cabinet.materials_catalog', instance_id=instance.id) }}">
    {{ form.hidden_tag() }}
    <table class="table trainer-materials-table" data-rows>
      <thead>
        <tr>
          <th>{{ _('Матеріал') }}</th>
          <th>{{ _('Кількість') }}</th>
          <th><span class="visually-hidden">{{ _('Дії') }}</span></th>
        </tr>
      </thead>
      <tbody data-rows-body>
        {% for row in rows %}
        <tr data-row>
          <td>
            {% if row.image_url %}<img src="{{ row.image_url }}" alt="" class="trainer-materials-thumb">{% endif %}
            {{ row.name or row.sku }}
            <input type="hidden" name="sku" value="{{ row.sku }}">
            <input type="hidden" name="name" value="{{ row.name or '' }}">
            <input type="hidden" name="image_url" value="{{ row.image_url or '' }}">
          </td>
          <td>
            <input type="number" name="quantity" class="form-input" min="1" step="1"
                   value="{{ row.quantity }}"{% if not editable %} readonly{% endif %}>
          </td>
          <td>
            {% if editable %}
            <button type="button" class="btn btn--ghost" data-remove-row
                    aria-label="{{ _('Прибрати позицію') }}">&times;</button>
            {% endif %}
          </td>
        </tr>
        {% endfor %}
      </tbody>
    </table>

    {% if editable %}
      {% if catalog_unavailable %}
        <p class="notice notice--warning">
          {{ _('Каталог складу зараз недоступний. Заявку можна надіслати з наявного переліку, а додати нові позиції -- пізніше.') }}
        </p>
      {% else %}
        <div class="trainer-materials-add">
          <label for="materialsAdd" class="form-label">{{ _('Додати позицію') }}</label>
          <input type="search" id="materialsAdd" class="form-input"
                 placeholder="{{ _('Пошук по каталогу') }}" autocomplete="off"
                 data-catalog-search>
          <ul class="trainer-materials-suggest" data-suggest hidden></ul>
        </div>
      {% endif %}

      <div class="form-group">
        {{ form.comment.label(class='form-label') }}
        {{ form.comment(class='form-input', rows=3) }}
      </div>

      <div class="trainer-materials-actions">
        <button type="submit" name="action" value="draft" class="btn btn--secondary">{{ _('Зберегти чернетку') }}</button>
        <button type="submit" name="action" value="submit" class="btn btn--primary">{{ _('Відправити') }}</button>
      </div>
    {% endif %}
  </form>
</section>
{% endblock %}
{% block scripts %}{{ super() }}
<script src="{{ url_for('static', filename='js/trainer-materials.js') }}" defer></script>
{% endblock %}
```

Імена блоків (`styles`, `scripts`, `content`) і класи компонентів (`table`,
`btn`, `btn--primary`, `form-input`, `form-label`, `badge`, `notice`,
`empty-state`, `visually-hidden`) звірити з наявними шаблонами кабінету й
каталогом `/admin/design-system`. Якщо якогось класу в дизайн-системі
немає — узяти найближчий наявний, а НЕ оголошувати свій у `page-*.css`.

- [ ] **Step 4: Написати CSS — лише layout**

`app/static/css/page-trainer-materials.css`:

```css
/* Заявка тренера на матеріали -- ЛИШЕ layout цієї сторінки.
   Декор (колір, шрифт, межа, тінь) береться з дизайн-системи: таблиця --
   .table, кнопки -- .btn, поля -- .form-input, стани -- .badge/.notice.
   Жоден із цих класів тут не перевизначається. */

.trainer-materials-list {
  display: grid;
  gap: 12px;
  list-style: none;
  margin: 0;
  padding: 0;
}

.trainer-materials-list__item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.trainer-materials-list__main {
  min-width: 0;
}

.trainer-materials-table {
  width: 100%;
}

.trainer-materials-table td:nth-child(2) {
  width: 8rem;
}

.trainer-materials-table td:last-child {
  width: 3rem;
  text-align: right;
}

.trainer-materials-thumb {
  width: 2.5rem;
  height: 2.5rem;
  object-fit: contain;
  vertical-align: middle;
  margin-right: 8px;
}

.trainer-materials-add {
  position: relative;
  margin-top: 16px;
}

.trainer-materials-suggest {
  position: absolute;
  z-index: 2;
  inset-inline: 0;
  margin: 0;
  padding: 0;
  list-style: none;
  max-height: 16rem;
  overflow-y: auto;
}

.trainer-materials-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  margin-top: 16px;
}

@media (max-width: 640px) {
  .trainer-materials-list__item {
    flex-direction: column;
    align-items: flex-start;
  }

  .trainer-materials-table td:nth-child(2) {
    width: 5rem;
  }
}
```

Відступи -- сирими px, як у наявних `page-*.css`: токенів `--iprm-space-*`
у `common.css` НЕМАЄ (перевірено), там лише кольори, радіуси й тіні.
Випадайка підказок лишається без рамки й фону тут —
якщо в дизайн-системі немає придатного класу для спливного списку,
використати наявний клас меню/дропдауна замість оголошення свого.

- [ ] **Step 5: Написати JS**

`app/static/js/trainer-materials.js`:

```javascript
/* Заявка тренера на матеріали: прибрати рядок, додати рядок із каталогу.
   Окремо від admin-materials.js: той зав'язаний на адмінську розмітку
   (XLSX, множник, підсвітка залишків), і тут із нього не потрібне ніщо. */
(function () {
  'use strict';

  var form = document.querySelector('.trainer-materials-form');
  if (!form) { return; }

  var body = form.querySelector('[data-rows-body]');
  var search = form.querySelector('[data-catalog-search]');
  var suggest = form.querySelector('[data-suggest]');
  var catalogUrl = form.getAttribute('data-catalog-url');
  var timer = null;

  form.addEventListener('click', function (event) {
    var button = event.target.closest('[data-remove-row]');
    if (!button) { return; }
    var row = button.closest('[data-row]');
    if (row) { row.remove(); }
  });

  function hasSku(sku) {
    return Array.prototype.some.call(
      body.querySelectorAll('input[name="sku"]'),
      function (input) { return input.value === sku; }
    );
  }

  function addRow(item) {
    if (hasSku(item.sku)) { return; }
    var row = document.createElement('tr');
    row.setAttribute('data-row', '');

    var nameCell = document.createElement('td');
    nameCell.textContent = item.name || item.sku;
    ['sku', 'name', 'image_url'].forEach(function (field) {
      var hidden = document.createElement('input');
      hidden.type = 'hidden';
      hidden.name = field;
      hidden.value = item[field] || '';
      nameCell.appendChild(hidden);
    });

    var qtyCell = document.createElement('td');
    var qty = document.createElement('input');
    qty.type = 'number';
    qty.name = 'quantity';
    qty.className = 'form-input';
    qty.min = '1';
    qty.step = '1';
    qty.value = '1';
    qtyCell.appendChild(qty);

    var actionCell = document.createElement('td');
    var remove = document.createElement('button');
    remove.type = 'button';
    remove.className = 'btn btn--ghost';
    remove.setAttribute('data-remove-row', '');
    remove.textContent = '×';
    actionCell.appendChild(remove);

    row.appendChild(nameCell);
    row.appendChild(qtyCell);
    row.appendChild(actionCell);
    body.appendChild(row);
  }

  function renderSuggestions(items) {
    suggest.innerHTML = '';
    if (!items.length) { suggest.hidden = true; return; }
    items.forEach(function (item) {
      var li = document.createElement('li');
      var button = document.createElement('button');
      button.type = 'button';
      button.className = 'btn btn--ghost';
      button.textContent = item.name || item.sku;
      button.addEventListener('click', function () {
        addRow(item);
        suggest.hidden = true;
        search.value = '';
      });
      li.appendChild(button);
      suggest.appendChild(li);
    });
    suggest.hidden = false;
  }

  if (search && suggest && catalogUrl) {
    search.addEventListener('input', function () {
      window.clearTimeout(timer);
      var query = search.value.trim();
      if (query.length < 2) { suggest.hidden = true; return; }
      /* Кожен запит -- живий HTTP у MM Medic, тому пауза, а не пошук на
         кожну літеру. Серверний ліміт -- 30/хв. */
      timer = window.setTimeout(function () {
        window.fetch(catalogUrl + '?q=' + encodeURIComponent(query), {
          headers: { 'Accept': 'application/json' }
        })
          .then(function (response) { return response.json(); })
          .then(function (data) { renderSuggestions(data.items || []); })
          .catch(function () { suggest.hidden = true; });
      }, 300);
    });
  }
}());
```

- [ ] **Step 6: Перевірити синтаксис і дизайн-систему**

```bash
node --check app/static/js/trainer-materials.js
node 1-instruments/design-system/atom-audit.cjs
python 1-instruments/design-system/shadowed_rules.py
python 1-instruments/design-system/layer_check.py
venv/Scripts/python -m pytest tests/test_design_system/ -v
```

Expected: `node --check` мовчить; `layer_check.py` не показує
`page-trainer-materials.css` як компонентний (у нього рівно один
шаблон-споживач — `materials_request.html`, тож ім'я на `page-` правильне);
`shadowed_rules.py` не додає нового класу, оголошеного двічі; тести
дизайн-системи зелені.

Якщо `shadowed_rules.py` показує новий дубль — прибрати оголошення з
`page-trainer-materials.css` і взяти компонентний клас, а не навпаки.

- [ ] **Step 7: Прогнати тести сторінки**

Run: `venv/Scripts/python -m pytest tests/test_trainer_cabinet_materials.py -v`

Expected: PASS — тепер шаблони існують, і тести, що рендерять сторінку,
проходять справжній рендер, а не 500.

- [ ] **Step 8: Commit**

```bash
git add app/templates/trainer_cabinet/materials.html app/templates/trainer_cabinet/materials_request.html app/templates/trainer_cabinet/_nav.html app/static/css/page-trainer-materials.css app/static/js/trainer-materials.js
git commit -m "feat(trainer): сторінка заявки на матеріали -- шаблони, layout, скрипт"
```

---

## Task 7: Адмінка — три дії над заявкою

**Files:**
- Modify: `app/admin/routes_materials.py`
- Modify: `app/templates/admin/materials.html`
- Test: `tests/test_mm_medic_materials.py`

**Interfaces:**
- Consumes: з Task 2 — `material_request_service.{approve, return_to_trainer,
  reject, RequestTransitionError}`; з Task 4 —
  `EmailService.send_material_request_decision`.
- Produces:
  - ендпоінт `admin.instance_materials_approve`
    (`POST /admin/instances/<id>/materials/approve`)
  - ендпоінт `admin.instance_materials_return`
    (`POST /admin/instances/<id>/materials/return`)
  - ендпоінт `admin.instance_materials_reject`
    (`POST /admin/instances/<id>/materials/reject`)

- [ ] **Step 1: Write the failing test**

Додати в `tests/test_mm_medic_materials.py`:

```python
def test_approve_route_requires_materials_manage(client, viewer_user, instance,
                                                  pending_request):
    _login(client, viewer_user)  # має лише materials.view
    response = client.post(f'/admin/instances/{instance.id}/materials/approve',
                           data={'csrf_token': _admin_csrf(client)})
    assert response.status_code in (302, 403)


def test_return_route_refuses_an_empty_reason(client, admin_user, instance,
                                              pending_request):
    from app.models.material_reservation import MaterialReservationStatus as S

    _login(client, admin_user)
    client.post(f'/admin/instances/{instance.id}/materials/return',
                data={'csrf_token': _admin_csrf(client), 'comment': '   '},
                follow_redirects=True)

    db.session.refresh(pending_request)
    assert pending_request.status == S.PENDING_REVIEW


def test_return_route_mails_the_trainer(client, admin_user, instance,
                                        pending_request, monkeypatch):
    from app.models.material_reservation import MaterialReservationStatus as S
    from app.services.email_service import EmailService

    mailed = []
    monkeypatch.setattr(
        EmailService, 'send_material_request_decision',
        staticmethod(lambda res, inst, decision: mailed.append(decision)))
    _login(client, admin_user)

    client.post(f'/admin/instances/{instance.id}/materials/return',
                data={'csrf_token': _admin_csrf(client),
                      'comment': 'Забули серветки'},
                follow_redirects=True)

    db.session.refresh(pending_request)
    assert pending_request.status == S.RETURNED
    assert mailed == ['returned']
```

Фікстуру `pending_request` зібрати через `material_request_service` (як у
Task 2), `viewer_user` — користувач із роллю, що має лише `materials.view`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `venv/Scripts/python -m pytest tests/test_mm_medic_materials.py -k "approve_route or return_route" -v`

Expected: FAIL — 404 (роутів немає).

- [ ] **Step 3: Додати три роути**

У `app/admin/routes_materials.py`, поруч із наявними
`instance_materials_*`. Декоратори прав скопіювати з сусіднього роуту, що
змінює дані (наприклад `instance_materials_reserve`) — там уже стоїть гейт
на `materials.manage`.

```python
def _decision_reservation(instance_id):
    """Заявка цього заходу, придатна для рішення, або редирект зі скаргою."""
    reservation = mrs.get_reservation(instance_id)
    if reservation is None:
        flash('Заявки на цей захід немає', 'warning')
        return None
    return reservation


@admin_bp.route('/instances/<int:instance_id>/materials/approve', methods=['POST'])
@permission_required('materials.manage')
def instance_materials_approve(instance_id):
    """Погодити заявку тренера й надіслати її на MM Medic.

    Далі працює наявний ланцюг: документ на MM Medic, лист комірнику з
    пікінг-листом, погодження складом, видача, фактичні. Комірник отримує
    лише перевірене -- у цьому й сенс кнопки.
    """
    instance = _get_instance(instance_id)
    reservation = _decision_reservation(instance_id)
    if reservation is None:
        return _redirect_page(instance_id)
    try:
        ok, result = mrq.approve(instance, reservation)
    except mrq.RequestTransitionError as exc:
        flash(str(exc), 'warning')
        return _redirect_page(instance_id)
    if not ok:
        _flash_result_error(result)
        return _redirect_page(instance_id)
    _notify_decision(reservation, instance, 'approved')
    flash('Заявку погоджено й надіслано на склад', 'success')
    return _redirect_page(instance_id)


@admin_bp.route('/instances/<int:instance_id>/materials/return', methods=['POST'])
@permission_required('materials.manage')
def instance_materials_return(instance_id):
    instance = _get_instance(instance_id)
    reservation = _decision_reservation(instance_id)
    if reservation is None:
        return _redirect_page(instance_id)
    try:
        mrq.return_to_trainer(reservation, request.form.get('comment'),
                              current_user)
    except mrq.RequestTransitionError as exc:
        flash(str(exc), 'warning')
        return _redirect_page(instance_id)
    _notify_decision(reservation, instance, 'returned')
    flash('Заявку повернуто тренеру', 'success')
    return _redirect_page(instance_id)


@admin_bp.route('/instances/<int:instance_id>/materials/reject', methods=['POST'])
@permission_required('materials.manage')
def instance_materials_reject(instance_id):
    instance = _get_instance(instance_id)
    reservation = _decision_reservation(instance_id)
    if reservation is None:
        return _redirect_page(instance_id)
    try:
        mrq.reject(reservation, request.form.get('comment'), current_user)
    except mrq.RequestTransitionError as exc:
        flash(str(exc), 'warning')
        return _redirect_page(instance_id)
    _notify_decision(reservation, instance, 'rejected')
    flash('Заявку відхилено', 'success')
    return _redirect_page(instance_id)


def _notify_decision(reservation, instance, decision):
    """Лист тренеру. Best-effort: рішення вже збережене, і збій пошти його
    не скасовує."""
    from app.services.email_service import EmailService
    try:
        EmailService.send_material_request_decision(reservation, instance, decision)
    except Exception:
        logger.exception('Не вдалося сповістити тренера про рішення %s по %s',
                         decision, reservation.external_ref)
```

Дописати імпорт `from app.services import material_request_service as mrq` і
переконатись, що `current_user`, `request`, `flash` і `logger` у модулі вже
є (звірити верх файлу). Декоратор прав зветься `permission_required` і в
цьому файлі вже імпортований — `instance_materials` використовує
`@permission_required('materials.view')`.

- [ ] **Step 4: Додати блок дій у шаблон**

У `app/templates/admin/materials.html`, перед наявним блоком кнопок
резервування, додати гілку для заявки на перевірці:

```html
{% if reservation and reservation.status in ['pending_review', 'returned'] %}
<section class="materials-request-review">
  <h2 class="iprm-block-title">{{ _('Заявка тренера') }}</h2>
  <p>
    {{ _('Подано') }}: {{ reservation.trainer_submitted_at.strftime('%d.%m.%Y %H:%M') if reservation.trainer_submitted_at }}
    {%- if reservation.created_by %} &middot; {{ reservation.created_by.email }}{% endif %}
    &middot; <span class="badge badge--{{ reservation.status_badge }}">{{ reservation.status_label }}</span>
  </p>
  {% if reservation.trainer_comment %}
    <p>{{ _('Коментар тренера') }}: {{ reservation.trainer_comment }}</p>
  {% endif %}

  {% if reservation.status == 'pending_review' %}
  <div class="materials-request-review__actions">
    <form method="post" action="{{ url_for('admin.instance_materials_approve', instance_id=instance.id) }}">
      <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
      <button type="submit" class="btn-admin btn-admin--primary">{{ _('Погодити й надіслати') }}</button>
    </form>
    <form method="post" action="{{ url_for('admin.instance_materials_return', instance_id=instance.id) }}">
      <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
      <input type="text" name="comment" class="form-input" required
             placeholder="{{ _('Що виправити') }}">
      <button type="submit" class="btn-admin btn-admin--secondary">{{ _('Повернути тренеру') }}</button>
    </form>
    <form method="post" action="{{ url_for('admin.instance_materials_reject', instance_id=instance.id) }}">
      <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
      <input type="text" name="comment" class="form-input" required
             placeholder="{{ _('Причина відхилення') }}">
      <button type="submit" class="btn-admin btn-admin--danger">{{ _('Відхилити') }}</button>
    </form>
  </div>
  {% endif %}
</section>
{% endif %}
```

Кількості в таблиці лишаються редагованими при `pending_review` — наявна
змінна `readonly` у шаблоні має бути хибною для цього стану; звірити, як
вона обчислюється (`materials.html:17` і далі), і додати новий стан до
редагованих.

Класи `.materials-request-review*` — layout-обгортка; оголосити їх у
наявному `app/static/css/admin-materials.css` (він уже компонентний для
адмінки матеріалів), а не заводити новий файл.

- [ ] **Step 5: Run tests to verify they pass**

Run: `venv/Scripts/python -m pytest tests/test_mm_medic_materials.py -v`

Expected: PASS, усі.

- [ ] **Step 6: Commit**

```bash
git add app/admin/routes_materials.py app/templates/admin/materials.html app/static/css/admin-materials.css tests/test_mm_medic_materials.py
git commit -m "feat(materials): погодження, повернення й відхилення заявки в адмінці"
```

---

## Task 8: Огляд і лічильник

**Files:**
- Modify: `app/admin/routes_materials.py` (`_overview_filters`,
  `_overview_query`)
- Modify: `app/templates/admin/partials/_sidebar.html`
- Modify: `app/admin/__init__.py` або модуль контекст-процесора адмінки
  (там, де вже лічаться інші бейджі сайдбару — знайти грепом)
- Test: `tests/test_mm_medic_materials.py`

**Interfaces:**
- Consumes: з Task 2 — `material_request_service.pending_review_count()`;
  з Task 1 — нові статуси.
- Produces: нічого для інших задач.

- [ ] **Step 1: Write the failing test**

```python
def test_overview_lists_pending_requests_first(client, admin_user, instance,
                                               pending_request, consumed_request):
    """Заявка на перевірці -- єдиний стан, що чекає дії людини, тож вона
    має бути вгорі списку, а не загубитись серед закритих."""
    _login(client, admin_user)
    response = client.get('/admin/materials')
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert body.index(pending_request.external_ref) < body.index(
        consumed_request.external_ref)


def test_pending_review_count_reflects_only_requests_awaiting_review(app,
                                                                     instance,
                                                                     pending_request):
    from app.services import material_request_service as mrq
    from app.models.material_reservation import MaterialReservationStatus as S

    assert mrq.pending_review_count() == 1

    pending_request.status = S.SUBMITTED
    db.session.commit()
    assert mrq.pending_review_count() == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `venv/Scripts/python -m pytest tests/test_mm_medic_materials.py -k "overview_lists or pending_review_count" -v`

Expected: FAIL — порядок у списку довільний.

- [ ] **Step 3: Підняти заявки нагору в огляді**

У `_overview_query` (`app/admin/routes_materials.py:797`) — додати первинне
сортування перед наявним:

```python
    # Заявка на перевірці -- єдиний стан, що чекає дії людини. Решта
    # сортування (за датою заходу) лишається як було, всередині груп.
    awaiting = case(
        (MaterialReservation.status == MaterialReservationStatus.PENDING_REVIEW, 0),
        else_=1,
    )
```

і підставити `awaiting` першим аргументом наявного `.order_by(...)`.
Імпортувати `case` із `sqlalchemy`, якщо його ще немає у файлі.

У `_overview_filters` (`:775`) переконатись, що список допустимих статусів
фільтра будується з `MaterialReservationStatus.ALL`, а не з жорсткого
переліку. Якщо перелік жорсткий — замінити на `ALL`, інакше нові статуси
не пройдуть валідацію фільтра.

- [ ] **Step 4: Додати лічильник у сайдбар**

Лічильники сайдбару -- ПЛОСКІ змінні контексту, не словник: наявний
`inject_pending_refund_requests` (`app/admin/__init__.py:28`) віддає
`{'pending_refund_requests': ...}`, а шаблон читає голе ім'я. Повторюємо
той самий патерн, окремим процесором.

У `app/admin/__init__.py`, одразу після `inject_pending_refund_requests`:

```python
@admin_bp.context_processor
def inject_pending_material_requests():
    """Лічильник неперевірених заявок на матеріали для сайдбара.

    `context_processor` блупринта, а не додатка -- з тієї ж причини, що й
    сусідній лічильник повернень: інакше COUNT їхав би на кожну публічну
    сторінку заради числа, видимого лише в адмінці.

    Fail-soft: сайдбар малюється на КОЖНІЙ адмін-сторінці, і збій цього
    запиту не має класти, скажімо, редагування курсу.
    """
    try:
        from app.services import material_request_service as mrq
        return {'pending_material_requests': mrq.pending_review_count()}
    except Exception:
        return {'pending_material_requests': 0}
```

У `_sidebar.html`, у пункті «Матеріали» -- так само, як зроблено для
повернень у рядку 131:

```html
{% if pending_material_requests %}<span class="badge badge--warning">{{ pending_material_requests }}</span>{% endif %}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `venv/Scripts/python -m pytest tests/test_mm_medic_materials.py -v`

Expected: PASS, усі.

- [ ] **Step 6: Прогнати всю дотичну поверхню**

```bash
venv/Scripts/python -m pytest tests/test_mm_medic_materials.py tests/test_material_notifications.py tests/test_trainer_cabinet_materials.py tests/test_design_system/ -v
venv/Scripts/python -m pytest tests/ -q
```

Expected: усе зелене. Якщо впав `test_api_v1_clients` — це фікстури
користувачів, що не прибрали за собою (див. Global Constraints), а не
регресія фічі.

- [ ] **Step 7: Commit**

```bash
git add app/admin/routes_materials.py app/templates/admin/partials/_sidebar.html tests/test_mm_medic_materials.py
git commit -m "feat(materials): заявки на перевірці вгорі огляду й лічильник у сайдбарі"
```

---

## Після реалізації

Не частина задач — це те, що робить людина перед деплоєм:

1. `venv/Scripts/flask db heads` — переконатись, що голова одна.
2. На проді: міграція ДО коду (модель одразу читає нові колонки).
3. В адмінці налаштувань нотифікацій увімкнути подію «Заявка тренера на
   матеріали» і задати одержувачів.
4. Заповнити комплекти матеріалів (`/admin/material-kits`) для курсів, що
   йдуть найближче: без них тренер отримає порожню форму.

## Self-Review

Звірено з розділами спеки:

| Розділ спеки | Задача |
| --- | --- |
| 1. Дані (статуси, походження, колонки, CHECK) | Task 1 |
| 2. Сторінка тренера (роути, префіл, проєкція, деградація) | Task 5 |
| 2. Сторінка тренера (розкладка, CSS, JS, навігація) | Task 6 |
| 3. Погодження в адмінці (три дії, права, `is_mm_document`) | Task 7 + Task 1 (Step 4) |
| 3. Огляд і лічильник | Task 8 |
| 4. Листи (чотири, одержувачі, тригер, ідемпотентність) | Task 4 |
| 5. Збої: партнер мовчить при погодженні | Task 2 (тест `approve_keeps_pending_review`) |
| 5. Збої: каталог недоступний | Task 5 (тест `form_still_works_when_the_partner_is_silent`) |
| 5. Збої: гонка двох погоджень | Task 2 (тест `second_approval_loses_the_race`) |
| 5. Збої: пізній POST тренера | Task 5 (тест `pending_request_is_read_only`) |
| 5. Збої: пізній штовх вебхука | Task 3 |
| 5. Збої: чужа заявка -> 404 | Task 5 (тест `foreign_instance_is_not_found`) |
| 5. Збої: ліміт на пошук | Task 5 (`@limiter.limit('30 per minute')`) |
| 6. Тести | розподілені по задачах |
| 7. Порядок деплою | «Після реалізації» |

Узгодженість імен, перевірена наскрізно: `material_request_service` як
`mrq` в усіх споживачах; `catalog_for_trainer` повертає
`(items, unavailable)` і так само розпаковується в Task 5 Step 5;
`approve(instance, reservation)` повертає `(ok, result)` і так само
розпаковується в Task 7; `send_material_request_decision(reservation,
instance, decision)` — той самий порядок аргументів у Task 4, Task 7 і в
тестах; `LOCAL_STATES` оголошено в Task 1 і спожито в Task 1 (`is_mm_document`)
і Task 3.

П'ять імен, які спершу були здогадками, перевірено по файлах і підставлено
фактичні: базовий шаблон листів — `emails/base.html` (не `base_email.html`);
декоратор прав — `permission_required` (не `require_permission`); поле
комплекту — `MaterialKitItem.name_snapshot` (не `name`); лічильники сайдбару —
ПЛОСКІ змінні контексту, не словник; токенів `--iprm-space-*` у `common.css`
немає взагалі, відступи — сирими px.

Свідомо лишені без фіксації, бо залежать від файлів, які план не читав
цілком: перший рядок базового шаблону кабінету, набір уже наявних імпортів
у двох модулях, обчислення `readonly` у `admin/materials.html`, точні імена
класів дизайн-системи для спливного списку. У кожному місці сказано, з чим
звіряти, і що робити, якщо потрібного класу в дизайн-системі немає — брати
найближчий наявний, а НЕ оголошувати свій у `page-*.css`.
