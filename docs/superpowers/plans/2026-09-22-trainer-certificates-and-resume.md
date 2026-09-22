# Сертифікати тренера й PDF-резюме — план реалізації

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Тренер бачить у кабінеті свої сертифікати за проведені заходи (видані автоматично й надіслані листом) та редагує власні регалії; в анкеті зʼявляється поле «Професійні сертифікати»; адмін вивантажує резюме тренерів PDF-таблицею.

**Architecture:** Перехід проведення в `completed` робить лише INSERT записів `LecturerCertificate` — рендер PDF і розсилка винесені у фонові джоби, тож запит адміна не чекає WeasyPrint, а невідправлений лист лишається видимим (`emailed_at IS NULL`) і повторюється наступним тіком. Уся оркестрація живе в новому `app/services/lecturer_certificates.py`; `certificate_service` не росте.

**Tech Stack:** Flask, SQLAlchemy, Alembic, Jinja2, WTForms, APScheduler, WeasyPrint, pytest.

**Spec:** `docs/superpowers/specs/2026-09-22-trainer-certificates-and-resume-design.md`

## Global Constraints

- Робота ТІЛЬКИ в гілці `main`. Не створювати фіча-гілок, sdd-гілок і worktree.
- Коміт ФАЗАМИ, щойно фаза готова. Файли перелічувати ЯВНО; `git add -A` і `git add .` заборонені — у дереві паралельно може працювати інша сесія.
- Фаза з червоними тестами не комітиться.
- Повідомлення комітів — українською, без згадок про інструмент чи модель.
- Пуш — ніколи без прямого запиту.
- Жодних емодзі в коді. Жодного інлайнового CSS/JS у вебсторінках. Виняток — PDF-шаблони для WeasyPrint: вони самодостатні документи і тримають `<style>` усередині, як уже роблять `templates/certificates/certificate.html`.
- Стилі компонентів — у дизайн-системі; `page-*.css` лише layout. Файл з рівно одним шаблоном-споживачем мусить називатись `page-*`.
- id alembic-ревізії — не довше 32 символів (колонка `varchar(32)`).
- Поточна голова міграцій — `email_trainer_reqs_20260919` (єдина).
- Тести тренерського кабінету складають акаунти з префіксом `tc-` (autouse-фікстура їх прибирає). Нові користувачі в тестах прибирати за собою, інакше валиться `test_api_v1_clients`.
- Планувальник у `TESTING` вимкнено: джоби тестуються викликом сервісної функції, а не обгортки зі `scheduler_service`.

---

## Карта файлів

**Створюються**
- `app/services/lecturer_certificates.py` — оркестрація: видача на захід, розсилка, добір пропущених, звіт адмінам, вибір адреси.
- `app/services/trainer_resume_service.py` — реєстр колонок резюме, збирання рядків, рендер PDF.
- `app/templates/trainer_cabinet/certificates.html` — розділ кабінету.
- `app/templates/emails/lecturer_certificate_issued.html` — лист тренеру.
- `app/templates/emails/admin_lecturer_certificate_failed.html` — лист адмінам: видача не відбулась.
- `app/templates/emails/admin_lecturer_certificate_report.html` — щоденний звіт про зависання.
- `app/templates/emails/admin_lecturer_certificate_complaint.html` — тренер повідомляє про помилку в сертифікаті.
- `app/templates/admin/trainer_resume_pdf.html` — PDF-шаблон таблиці.
- `app/templates/partials/_resume_columns_dialog.html` — діалог вибору колонок (спільний на два входи).
- `app/static/js/trainer-certificates-editor.js` — редактор сертифікатів-зображень, спільний для адмінки й кабінету.
- `app/static/js/resume-columns-dialog.js` — логіка діалогу.
- `app/static/css/page-trainer-certificates.css` — layout розділу кабінету.
- `migrations/versions/lect_cert_emailed_20260922.py`
- `migrations/versions/trainer_prof_certs_20260922.py`
- `tests/test_services/test_lecturer_certificates.py`
- `tests/test_services/test_trainer_resume.py`
- `tests/test_trainer_cabinet/test_routes_certificates.py`
- `tests/test_routes/test_trainer_resume_pdf.py`

**Змінюються**
- `app/models/lecturer_certificate.py` — колонка `emailed_at`.
- `app/models/trainer_profile.py` — колонка `professional_certificates`.
- `app/admin/routes_instances.py` — тригер видачі при `completed`; скидання `emailed_at` у перевидачі.
- `app/admin/routes_trainers.py` — маршрут PDF-резюме.
- `app/services/email_service.py` — три нові методи.
- `app/services/scheduler_service.py` — дві нові джоби.
- `app/trainer_cabinet/routes.py`, `forms.py` — розділ сертифікатів, поле анкети.
- `app/templates/trainer_cabinet/_nav.html`, `profile.html` — картка розділу, поле.
- `app/templates/admin/trainer_edit.html`, `instance_edit.html`, `trainers.html` — редактор, кнопки експорту.
- `app/static/js/admin-trainer-regalia.js` — з нього виноситься блок сертифікатів.

---

# ФАЗА 1 — сертифікати лектора

## Task 1: Колонка `emailed_at`

**Files:**
- Modify: `app/models/lecturer_certificate.py`
- Create: `migrations/versions/lect_cert_emailed_20260922.py`
- Test: `tests/test_db/test_migration_lect_cert_emailed.py`

**Interfaces:**
- Consumes: нічого.
- Produces: `LecturerCertificate.emailed_at` (`DateTime(timezone=True)`, nullable, index).

- [ ] **Step 1: Написати тест міграції**

Файл `tests/test_db/test_migration_lect_cert_emailed.py`. Взірець структури — наявний `tests/test_db/test_migration_bpr_counter.py`.

```python
"""Міграція lect_cert_emailed_20260922: колонка emailed_at.

Наявні сертифікати позначаються як уже опрацьовані (emailed_at = issued_at),
інакше перший же тік джоби розіслав би листи за минулі заходи.
"""
from app.extensions import db
from app.models.lecturer_certificate import LecturerCertificate


def test_emailed_at_defaults_to_null_for_new_rows(app):
    lc = LecturerCertificate(
        instance_id=None, trainer_id=None, number='TEST-100001',
        recipient_name='Тестовому Тренеру', event_title='Захід',
    )
    assert lc.emailed_at is None


def test_column_exists_and_is_nullable(app):
    col = LecturerCertificate.__table__.c.emailed_at
    assert col.nullable is True
    assert col.index is True
```

- [ ] **Step 2: Запустити тест, переконатись що падає**

Run: `venv/Scripts/python.exe -m pytest tests/test_db/test_migration_lect_cert_emailed.py -v`
Expected: FAIL — `AttributeError` / `KeyError: 'emailed_at'`.

- [ ] **Step 3: Додати колонку в модель**

У `app/models/lecturer_certificate.py`, одразу після блоку `issued_at` / `issued_by_id`:

```python
    # Момент, коли сертифікат пішов тренеру листом. NULL = «видано, лист ще
    # не пішов»: саме цей стан дає джобі чергу на розсилку й робить
    # невідправлений лист видимим. Без колонки лист, що не пішов через
    # недоступну пошту, зник би безслідно.
    emailed_at = db.Column(db.DateTime(timezone=True), index=True)
```

- [ ] **Step 4: Написати міграцію**

Файл `migrations/versions/lect_cert_emailed_20260922.py`:

```python
"""Колонка emailed_at у lecturer_certificates.

Стан «видано, лист ще не пішов». Наявні рядки позначаються опрацьованими
(emailed_at = issued_at): інакше перший тік джоби розсилки надіслав би листи
за всі минулі заходи. Позначка явна і не залежить від дати деплою.

Revision ID: lect_cert_emailed_20260922
Revises: email_trainer_reqs_20260919
"""
import sqlalchemy as sa
from alembic import op

revision = 'lect_cert_emailed_20260922'
down_revision = 'email_trainer_reqs_20260919'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('lecturer_certificates', schema=None) as batch_op:
        batch_op.add_column(sa.Column('emailed_at', sa.DateTime(timezone=True)))
        batch_op.create_index(
            'ix_lecturer_certificates_emailed_at', ['emailed_at'])
    op.execute('UPDATE lecturer_certificates SET emailed_at = issued_at')


def downgrade():
    with op.batch_alter_table('lecturer_certificates', schema=None) as batch_op:
        batch_op.drop_index('ix_lecturer_certificates_emailed_at')
        batch_op.drop_column('emailed_at')
```

- [ ] **Step 5: Застосувати міграцію й переконатись, що голова одна**

Run:
```bash
venv/Scripts/python.exe -m flask db upgrade
venv/Scripts/python.exe -m flask db heads
```
Expected: `lect_cert_emailed_20260922 (head)`, рівно один рядок. Голови питати саме цією командою — regex по файлах не бачить кортежних merge-ревізій.

- [ ] **Step 6: Перевірити оборотність**

Run:
```bash
venv/Scripts/python.exe -m flask db downgrade
venv/Scripts/python.exe -m flask db upgrade
```
Expected: обидві команди завершуються без помилки. Не грепати по виводу «успішно» — grep ховає помилки; дивитись код повернення.

- [ ] **Step 7: Запустити тест**

Run: `venv/Scripts/python.exe -m pytest tests/test_db/test_migration_lect_cert_emailed.py -v`
Expected: PASS.

---

## Task 2: Видача сертифікатів на захід

**Files:**
- Create: `app/services/lecturer_certificates.py`
- Create: `app/templates/emails/admin_lecturer_certificate_failed.html`
- Modify: `app/services/email_service.py`
- Test: `tests/test_services/test_lecturer_certificates.py`

**Interfaces:**
- Consumes: `LecturerCertificate.emailed_at` (Task 1); наявні `certificate_service.issue_lecturer_certificate(instance, trainer, issued_by=None)` та `CourseInstance.effective_lecturer_points`.
- Produces:
  - `lecturer_certificates.issue_for_instance(instance, issued_by=None) -> list[LecturerCertificate]`
  - `EmailService.notify_lecturer_certificate_failed(instance, reason) -> list`

- [ ] **Step 1: Написати падаючі тести**

Файл `tests/test_services/test_lecturer_certificates.py`:

```python
"""Автовидача сертифікатів лектора на захід."""
from unittest.mock import patch

from app.extensions import db
from app.models.lecturer_certificate import LecturerCertificate
from app.services import lecturer_certificates as lc_svc
from app.services.trainer_links import set_trainers
from tests.test_trainer_cabinet._factories import (
    make_course, make_instance, make_trainer,
)


def _completed_instance(points=5, trainers=2):
    course = make_course()
    made = [make_trainer(name=f'Тренер {i}') for i in range(trainers)]
    set_trainers(course, [t.id for t in made])
    course.bpr_lecturer_points = points
    inst = make_instance(course, days=-3, status='completed')
    db.session.commit()
    return inst, made


def test_issues_one_certificate_per_trainer(app):
    inst, made = _completed_instance(trainers=2)
    issued = lc_svc.issue_for_instance(inst)
    assert len(issued) == 2
    assert {c.trainer_id for c in issued} == {t.id for t in made}


def test_second_call_does_not_duplicate(app):
    inst, _ = _completed_instance(trainers=2)
    lc_svc.issue_for_instance(inst)
    lc_svc.issue_for_instance(inst)
    assert LecturerCertificate.query.filter_by(instance_id=inst.id).count() == 2


def test_missing_points_issues_nothing_and_notifies_admins(app):
    inst, _ = _completed_instance(points=None, trainers=2)
    with patch(
        'app.services.email_service.EmailService'
        '.notify_lecturer_certificate_failed'
    ) as notify:
        issued = lc_svc.issue_for_instance(inst)
    assert issued == []
    assert LecturerCertificate.query.filter_by(instance_id=inst.id).count() == 0
    assert notify.called


def test_issued_certificates_start_unsent(app):
    inst, _ = _completed_instance(trainers=1)
    issued = lc_svc.issue_for_instance(inst)
    assert issued[0].emailed_at is None
```

Примітка виконавцю: якщо поле курсу для балів лектора зветься інакше, ніж `bpr_lecturer_points`, підставити фактичне — воно те, яке читає `CourseInstance.effective_lecturer_points`. Перевірити: `grep -n "effective_lecturer_points" -A 12 app/models/course_instance.py`.

- [ ] **Step 2: Запустити тести, переконатись що падають**

Run: `venv/Scripts/python.exe -m pytest tests/test_services/test_lecturer_certificates.py -v`
Expected: FAIL — `ModuleNotFoundError: app.services.lecturer_certificates`.

- [ ] **Step 3: Написати сервіс**

Файл `app/services/lecturer_certificates.py`:

```python
"""Автовидача, розсилка й добір сертифікатів лектора.

Оркестрація живе тут, а не в certificate_service: той модуль уже великий і
відповідає за самі документи (номери, знімки, рендер), а це — правила
життєвого циклу навколо них.

Перехід заходу в 'completed' робить лише INSERT записів. Рендер PDF
(WeasyPrint, секунда-дві на документ) і розсилка винесені у фонові джоби:
запит адміна не має на них чекати, а збій рендера не має відкочувати зміну
статусу.
"""
import logging

from app.extensions import db

logger = logging.getLogger(__name__)


def issue_for_instance(instance, issued_by=None):
    """Видати сертифікати всім тренерам заходу. Повертає список записів.

    Бали БПР перевіряються ОДИН раз до циклу: вони в заході одні на всіх, тож
    або падають усі, або ніхто. Перевірка всередині циклу дала б захід із
    частиною виданих сертифікатів — стан, з якого немає чистого виходу.

    Немає балів -> нічого не видається, адмінам іде лист, захід лишається в
    черзі добору (`issue_missing`): щойно бали внесуть, наступний тік видасть
    сертифікати сам.
    """
    from app.services import certificate_service as cs

    trainers = instance.effective_trainers
    if not trainers:
        return []

    if instance.effective_lecturer_points is None:
        _notify_failed(
            instance,
            'Не задано бали БПР тренеру (Адмінка -> Курс або конкретне '
            'проведення -> редагувати).',
        )
        return []

    issued = []
    for trainer in trainers:
        try:
            issued.append(cs.issue_lecturer_certificate(
                instance, trainer, issued_by=issued_by))
        except Exception:
            db.session.rollback()
            logger.exception(
                'Lecturer certificate issue failed: instance=%s trainer=%s',
                instance.id, trainer.id)
    return issued


def _notify_failed(instance, reason):
    """Лист адмінам. Best-effort: збій сповіщення нічого не відкочує."""
    from app.services.email_service import EmailService
    try:
        EmailService.notify_lecturer_certificate_failed(instance, reason)
    except Exception:
        db.session.rollback()
        logger.exception(
            'Failed to notify admins about lecturer cert failure: instance=%s',
            instance.id)
```

- [ ] **Step 4: Додати метод сповіщення в EmailService**

У `app/services/email_service.py`, поряд з іншими `notify_*`:

```python
    @staticmethod
    def notify_lecturer_certificate_failed(instance, reason):
        """Адмінам: захід завершено, а сертифікати тренерам не видались.

        Тренер документа не побачить і листа не отримає, доки хтось не
        виправить причину, тож збій має дійти до людини, а не лише в лог.
        """
        from app.models.site_settings import SiteSettings

        base = (SiteSettings.get().website_url or '').rstrip('/')
        tail = f'/admin/instances/{instance.id}/edit'
        return EmailService.notify_admins_with_template(
            event_type='certificate',
            subject=('Сертифікати тренерам не видано: '
                     f'{instance.effective_title_for("uk") or instance.id}'),
            template_name='admin_lecturer_certificate_failed',
            context={
                'instance': instance,
                'reason': reason,
                'admin_url': f'{base}{tail}' if base else tail,
            },
        )
```

Примітка: `event_type='certificate'` — наявний дозволений тригер. Новий код вимагав би запису в `EmailLog.TRIGGERS` плюс міграції CHECK `ck_email_logs_trigger`; без неї `_safe_trigger` мовчки замінив би його на NULL.

- [ ] **Step 5: Написати шаблон листа**

Файл `app/templates/emails/admin_lecturer_certificate_failed.html` — за зразком `admin_certificate_failed.html`:

```html
{% extends "emails/base.html" %}
{% from "emails/_macros.html" import button_primary, detail_row, spacer %}

{#- Захід завершено, а сертифікати тренерам не видались. Тренер не побачить
    документа в кабінеті й не отримає листа, доки причину не усунуть. -#}

{% block title %}Сертифікати тренерам не видано{% endblock %}

{% block preview_text %}Захід завершено, автоматична видача не вдалася{% endblock %}

{% block content %}
    <h1 class="mobile-h1" style="margin: 0 0 8px 0; font-size: 26px; font-weight: 700; color: #17131D; line-height: 1.25;">
        Сертифікати тренерам не видано
    </h1>

    <p class="mobile-text" style="margin: 0 0 24px 0; font-size: 15px; color: #625A6D; line-height: 1.5;">
        Захід завершено, але автоматична видача сертифікатів тренерам не
        відбулася. Щойно причину буде усунуто, система видасть їх сама —
        повторювати вручну не потрібно.
    </p>

    <table role="presentation" style="width: 100%; margin-bottom: 24px; background-color: #F7F4FB; border: 1px solid #E9E4EF; border-radius: 8px;" cellpadding="0" cellspacing="0" border="0">
        <tr>
            <td style="padding: 20px 24px;">
                <p style="margin: 0 0 16px 0; font-size: 18px; font-weight: 600; color: #17131D; line-height: 1.3;">{{ instance.effective_title_for('uk') }}</p>
                {{ detail_row('Причина', reason) }}
            </td>
        </tr>
    </table>

    {{ button_primary('Відкрити проведення', admin_url) }}
    {{ spacer(16) }}
{% endblock %}
```

- [ ] **Step 6: Запустити тести**

Run: `venv/Scripts/python.exe -m pytest tests/test_services/test_lecturer_certificates.py -v`
Expected: PASS (4 тести).

---

## Task 3: Тригер при переході в `completed`

**Files:**
- Modify: `app/admin/routes_instances.py` (маршрут `instance_status_update`)
- Test: `tests/test_routes/test_instance_status_issues_certs.py`

**Interfaces:**
- Consumes: `lecturer_certificates.issue_for_instance` (Task 2).
- Produces: нічого нового.

- [ ] **Step 1: Написати падаючий тест**

Файл `tests/test_routes/test_instance_status_issues_certs.py`:

```python
"""Перехід проведення в 'completed' видає сертифікати тренерам."""
from app.extensions import db
from app.models.lecturer_certificate import LecturerCertificate
from app.services.trainer_links import set_trainers
from tests.support.rbac import make_super_admin, switch_user
from tests.test_trainer_cabinet._factories import (
    make_course, make_instance, make_trainer,
)


def _setup(client, points=5):
    admin = make_super_admin(email='tc-inst-admin@test.com')
    db.session.commit()
    switch_user(client, admin)
    course = make_course()
    trainer = make_trainer(name='Лектор Л.')
    set_trainers(course, [trainer.id])
    course.bpr_lecturer_points = points
    inst = make_instance(course, days=-2, status='active')
    db.session.commit()
    return inst, trainer


def test_completing_instance_issues_certificate(client):
    inst, trainer = _setup(client)
    resp = client.post(f'/admin/instances/{inst.id}/status',
                       data={'status': 'completed'})
    assert resp.status_code in (200, 302)
    cert = LecturerCertificate.query.filter_by(
        instance_id=inst.id, trainer_id=trainer.id).one()
    assert cert.emailed_at is None


def test_failed_transition_issues_nothing(client):
    inst, _ = _setup(client)
    client.post(f'/admin/instances/{inst.id}/status', data={'status': 'bogus'})
    assert LecturerCertificate.query.filter_by(instance_id=inst.id).count() == 0
```

- [ ] **Step 2: Запустити тест, переконатись що падає**

Run: `venv/Scripts/python.exe -m pytest tests/test_routes/test_instance_status_issues_certs.py -v`
Expected: FAIL — `NoResultFound` на першому тесті.

- [ ] **Step 3: Вставити виклик у маршрут**

У `app/admin/routes_instances.py`, у `instance_status_update`, ПІСЛЯ вдалого `db.session.commit()` зміни статусу (не перед ним) і ПЕРЕД формуванням відповіді, додати:

Саме після коміту: `certificate_service.issue_lecturer_certificate` комітить усередині себе, тож виклик до коміту статусу закомітив би зміну статусу передчасно — разом із чим завгодно ще, що лежало в сесії.

```python
        # Сертифікати тренерам — рівно на переході в 'completed'. Лише INSERT:
        # рендер PDF і лист робить фонова джоба, тож адмін не чекає WeasyPrint,
        # а збій рендера не відкочує зміну статусу.
        if new_status == 'completed' and old_status != 'completed':
            from app.services import lecturer_certificates as lc_svc
            lc_svc.issue_for_instance(instance, issued_by=current_user)
```

Виклик іде саме в маршрут, а не в `course_service.change_instance_status`: той шар навмисно без побічних ефектів і без коміту, і саме туди ходять тести переходів статусів.

- [ ] **Step 4: Запустити тести**

Run: `venv/Scripts/python.exe -m pytest tests/test_routes/test_instance_status_issues_certs.py tests/test_services/test_lecturer_certificates.py -v`
Expected: PASS.

- [ ] **Step 5: Перевірити, що наявні тести переходів не зламались**

Run: `venv/Scripts/python.exe -m pytest tests/test_routes/test_instance_lecturer_certificate.py tests/test_routes/test_instance_lecturer_points.py -v`
Expected: PASS.

---

## Task 4: Лист тренеру з сертифікатом

**Files:**
- Modify: `app/services/email_service.py`
- Create: `app/templates/emails/lecturer_certificate_issued.html`
- Modify: `app/services/lecturer_certificates.py` (вибір адреси)
- Test: `tests/test_services/test_lecturer_certificates.py` (доповнення)

**Interfaces:**
- Consumes: `certificate_service.render_lecturer_pdf(lecturer_cert)`.
- Produces:
  - `lecturer_certificates.recipient_email(trainer) -> str | None`
  - `EmailService.send_lecturer_certificate(lecturer_cert, to_email) -> EmailLog | None`

- [ ] **Step 1: Написати падаючі тести**

Дописати у `tests/test_services/test_lecturer_certificates.py`:

```python
def test_recipient_email_falls_back_to_directory(app):
    trainer = make_trainer(name='Довідниковий Т.')
    trainer.email = 'tc-directory@test.com'
    db.session.commit()
    assert lc_svc.recipient_email(trainer) == 'tc-directory@test.com'


def test_recipient_email_prefers_account_over_directory(app):
    from tests.test_trainer_cabinet._factories import make_user

    user = make_user()
    trainer = make_trainer(user, name='Акаунтний Т.')
    trainer.email = 'tc-directory@test.com'
    db.session.commit()
    assert lc_svc.recipient_email(trainer) == user.email


def test_recipient_email_prefers_profile_over_all(app):
    from app.models.trainer_profile import TrainerProfile
    from tests.test_trainer_cabinet._factories import make_user

    user = make_user()
    trainer = make_trainer(user, name='Анкетний Т.')
    trainer.email = 'tc-directory@test.com'
    db.session.add(TrainerProfile(trainer_id=trainer.id,
                                  email='tc-profile@test.com'))
    db.session.commit()
    db.session.refresh(trainer)
    assert lc_svc.recipient_email(trainer) == 'tc-profile@test.com'


def test_recipient_email_none_when_nothing_filled(app):
    trainer = make_trainer(name='Безадресний Т.')
    db.session.commit()
    assert lc_svc.recipient_email(trainer) is None
```

Примітка виконавцю: назву звʼязку тренера з анкетою звірити — `grep -n "profile" app/models/trainer.py`. У коді сервісу нижче вжито `trainer.profile`, бо саме так до неї ходять наявні маршрути кабінету.

- [ ] **Step 2: Запустити, переконатись що падає**

Run: `venv/Scripts/python.exe -m pytest tests/test_services/test_lecturer_certificates.py -k recipient_email -v`
Expected: FAIL — `AttributeError: module has no attribute 'recipient_email'`.

- [ ] **Step 3: Додати вибір адреси в сервіс**

У `app/services/lecturer_certificates.py`:

```python
def recipient_email(trainer):
    """Куди слати сертифікат: анкета -> акаунт -> довідник.

    Анкета першою: цю адресу тренер вказав сам і сам підтримує. Довідникова
    остання — її заповнює адмін, і вона найчастіше застаріває.
    """
    profile = trainer.profile
    candidates = (
        (profile.email if profile is not None else None),
        (trainer.user.email if trainer.user is not None else None),
        trainer.email,
    )
    for value in candidates:
        value = (value or '').strip()
        if value:
            return value
    return None
```

Примітка: назву звʼязку з `User` звірити — `grep -n "'User', foreign_keys=\[user_id\]" -B 3 app/models/trainer.py`.

- [ ] **Step 4: Додати метод листа в EmailService**

У `app/services/email_service.py`, поряд із `send_certificate`:

```python
    @staticmethod
    def send_lecturer_certificate(lecturer_cert, to_email):
        """Лист тренеру з PDF-сертифікатом лектора у вкладенні.

        Тригер 'certificate' (наявний, транзакційний) з idempotency_key на id
        сертифіката. Ключ обовʼязковий: без нього дедуплікація ключується на
        адресу+тригер у вікні 60 с, і тренер, якому в одному тіку джоби йдуть
        сертифікати за ДВА заходи, отримав би лише один лист.
        """
        from app.services.certificate_service import render_lecturer_pdf

        pdf_bytes = render_lecturer_pdf(lecturer_cert)
        filename = f'lecturer-{lecturer_cert.number}.pdf'
        return EmailService.send_email(
            to=to_email,
            subject=lambda: _('Ваш сертифікат тренера: %(title)s',
                              title=lecturer_cert.event_title),
            template_name='lecturer_certificate_issued',
            context={
                'certificate': lecturer_cert,
                'trainer': lecturer_cert.trainer,
                'cabinet_url': EmailService._trainer_cabinet_url(),
            },
            trigger='certificate',
            idempotency_key=f'lecturer-cert-{lecturer_cert.id}',
            attachments=[(filename, 'application/pdf', pdf_bytes)],
        )
```

- [ ] **Step 5: Додати хелпер посилання на кабінет**

Поряд із `_account_url`:

```python
    @staticmethod
    def _trainer_cabinet_url():
        """Абсолютне посилання на розділ сертифікатів кабінету тренера.

        Як і _account_url: з SiteSettings.website_url, а не url_for(_external),
        бо листи рендеряться і поза request-контекстом (фонові розсилки).
        """
        from app.models.site_settings import SiteSettings

        base = (SiteSettings.get().website_url or '').rstrip('/')
        tail = '/trainer/certificates'
        return f'{base}{tail}' if base else tail
```

Заразом прибрати з `send_lecturer_certificate` рядок-заглушку `base = ... if False else None` — він був лише вказівкою на цей крок.

- [ ] **Step 6: Написати шаблон листа**

Файл `app/templates/emails/lecturer_certificate_issued.html` — за зразком `certificate_issued.html`:

```html
{% extends "emails/base.html" %}
{% from "emails/_macros.html" import button_primary, detail_row, spacer %}

{% block title %}{{ _('Ваш сертифікат тренера') }}{% endblock %}

{% block preview_text %}{% trans title=certificate.event_title %}Сертифікат за проведення заходу {{ title }}{% endtrans %}{% endblock %}

{% block content %}
    <h1 class="mobile-h1" style="margin: 0 0 8px 0; font-size: 28px; font-weight: 700; color: #17131D; line-height: 1.25;">
        {{ _('Ваш сертифікат тренера') }}
    </h1>

    <p class="mobile-text" style="margin: 0 0 32px 0; font-size: 15px; color: #625A6D; line-height: 1.5;">
        {{ _('Дякуємо за проведений захід. Сертифікат додано до цього листа у форматі PDF, а також він завжди доступний у вашому кабінеті.') }}
    </p>

    <table role="presentation" style="width: 100%; margin-bottom: 24px; background-color: #F7F4FB; border: 1px solid #E9E4EF; border-radius: 8px;" cellpadding="0" cellspacing="0" border="0">
        <tr>
            <td style="padding: 20px 24px;">
                <p style="margin: 0 0 16px 0; font-size: 18px; font-weight: 600; color: #17131D; line-height: 1.3;">{{ certificate.event_title }}</p>
                {{ detail_row(_('Номер'), certificate.number) }}
                {% if certificate.event_date %}
                {{ detail_row(_('Дата заходу'), certificate.event_date.strftime('%d.%m.%Y')) }}
                {% endif %}
                {% if certificate.cpd_points %}
                {{ detail_row(_('Бали БПР'), certificate.cpd_points) }}
                {% endif %}
            </td>
        </tr>
    </table>

    {{ button_primary(_('Мої сертифікати'), cabinet_url) }}
    {{ spacer(16) }}
{% endblock %}
```

- [ ] **Step 7: Запустити тести**

Run: `venv/Scripts/python.exe -m pytest tests/test_services/test_lecturer_certificates.py -v`
Expected: PASS.

---

## Task 5: Джоба розсилки

**Files:**
- Modify: `app/services/lecturer_certificates.py`
- Modify: `app/services/scheduler_service.py`
- Test: `tests/test_services/test_lecturer_certificates.py` (доповнення)

**Interfaces:**
- Consumes: `recipient_email`, `EmailService.send_lecturer_certificate` (Task 4).
- Produces: `lecturer_certificates.send_pending(limit=50) -> tuple[int, int]` — `(надіслано, пропущено_без_адреси)`.

- [ ] **Step 1: Написати падаючі тести**

Дописати у `tests/test_services/test_lecturer_certificates.py`:

```python
def test_send_pending_marks_emailed_at(app):
    inst, _ = _completed_instance(trainers=1)
    cert = lc_svc.issue_for_instance(inst)[0]
    cert.trainer.email = 'tc-lect@test.com'
    db.session.commit()
    with patch('app.services.email_service.EmailService'
               '.send_lecturer_certificate') as send:
        sent, skipped = lc_svc.send_pending()
    assert (sent, skipped) == (1, 0)
    assert send.call_count == 1
    db.session.refresh(cert)
    assert cert.emailed_at is not None


def test_send_pending_does_not_send_twice(app):
    inst, _ = _completed_instance(trainers=1)
    cert = lc_svc.issue_for_instance(inst)[0]
    cert.trainer.email = 'tc-lect2@test.com'
    db.session.commit()
    with patch('app.services.email_service.EmailService'
               '.send_lecturer_certificate'):
        lc_svc.send_pending()
        sent, _ = lc_svc.send_pending()
    assert sent == 0


def test_two_certificates_for_one_trainer_give_two_letters(app):
    """60-секундне вікно дедуплікації не має зʼїдати другий сертифікат."""
    course = make_course()
    trainer = make_trainer(name='Двозахідний Т.')
    trainer.email = 'tc-two@test.com'
    set_trainers(course, [trainer.id])
    course.bpr_lecturer_points = 3
    first = make_instance(course, days=-5, status='completed')
    second = make_instance(course, days=-4, status='completed')
    db.session.commit()
    lc_svc.issue_for_instance(first)
    lc_svc.issue_for_instance(second)
    with patch('app.services.email_service.EmailService'
               '.send_lecturer_certificate') as send:
        sent, _ = lc_svc.send_pending()
    assert sent == 2
    keys = {c.kwargs.get('to_email') or c.args[1] for c in send.call_args_list}
    assert keys == {'tc-two@test.com'}


def test_trainer_without_email_is_skipped_but_others_proceed(app):
    inst, made = _completed_instance(trainers=2)
    certs = lc_svc.issue_for_instance(inst)
    certs[0].trainer.email = 'tc-has@test.com'
    certs[1].trainer.email = None
    db.session.commit()
    with patch('app.services.email_service.EmailService'
               '.send_lecturer_certificate'):
        sent, skipped = lc_svc.send_pending()
    assert (sent, skipped) == (1, 1)
    db.session.refresh(certs[1])
    assert certs[1].emailed_at is None
```

- [ ] **Step 2: Запустити, переконатись що падає**

Run: `venv/Scripts/python.exe -m pytest tests/test_services/test_lecturer_certificates.py -k send_pending -v`
Expected: FAIL — `AttributeError: module has no attribute 'send_pending'`.

- [ ] **Step 3: Написати `send_pending`**

У `app/services/lecturer_certificates.py`:

```python
def send_pending(limit=50):
    """Розіслати сертифікати, які ще не пішли листом.

    Повертає (надіслано, пропущено_без_адреси). Черга — `emailed_at IS NULL`.
    Збій на одному записі не ставить `emailed_at` і не зупиняє решту:
    наступний тік спробує знову. Ліміт — щоб один тік не рендерив сотню PDF
    поспіль після довгого простою пошти.
    """
    from app.models.lecturer_certificate import LecturerCertificate
    from app.services.email_service import EmailService

    pending = (
        LecturerCertificate.query
        .filter(LecturerCertificate.emailed_at.is_(None))
        .order_by(LecturerCertificate.issued_at)
        .limit(limit)
        .all()
    )
    sent = skipped = 0
    for cert in pending:
        if cert.trainer is None:
            skipped += 1
            continue
        to_email = recipient_email(cert.trainer)
        if not to_email:
            # Свідомо НЕ ставимо emailed_at: запис лишається видимим як
            # «видано, не надіслано» і потрапляє в щоденний звіт адміну.
            skipped += 1
            continue
        try:
            EmailService.send_lecturer_certificate(cert, to_email)
        except Exception:
            db.session.rollback()
            logger.exception(
                'Failed to email lecturer certificate %s', cert.number)
            continue
        cert.emailed_at = utcnow()
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            logger.exception(
                'Failed to mark lecturer certificate %s as emailed', cert.number)
            continue
        sent += 1
    return sent, skipped
```

Імпорт `utcnow` додати у шапку модуля: `from app.models.mixins import utcnow`.

- [ ] **Step 4: Запустити тести**

Run: `venv/Scripts/python.exe -m pytest tests/test_services/test_lecturer_certificates.py -v`
Expected: PASS.

- [ ] **Step 5: Зареєструвати джобу**

У `app/services/scheduler_service.py` додати функцію поряд з іншими джобами:

```python
def send_lecturer_certificates():
    """Periodic job: розсилка сертифікатів лектора, що ще не пішли листом.

    Вибірка й правила — у lecturer_certificates.send_pending; тут лише
    контекст застосунку й advisory lock проти дублювання між воркерами.
    """
    app = scheduler._app
    with app.app_context():
        with _job_lock('lecturer_certificates_send') as got:
            if not got:
                logger.debug('lecturer_certificates_send: locked, skipping')
                return
            from app.extensions import db
            from app.services import lecturer_certificates as lc_svc
            try:
                sent, skipped = lc_svc.send_pending()
            except Exception:
                db.session.rollback()
                logger.exception('send_lecturer_certificates failed')
                return
            if sent or skipped:
                logger.info(
                    'Сертифікати лектора: надіслано %d, без адреси %d',
                    sent, skipped)
```

І реєстрацію в `init_scheduler`, поряд з іншими `add_job`:

```python
    scheduler.add_job(
        send_lecturer_certificates,
        trigger=CronTrigger(minute='*/5'),
        id='lecturer_certificates_send',
        replace_existing=True,
        name='Розсилка сертифікатів лектора',
    )
```

Додати рядок у docstring модуля (список Jobs угорі файлу):
```
- lecturer_certificates_send: every 5 min, шле сертифікати лектора, що ще не
  пішли листом (emailed_at IS NULL).
```

- [ ] **Step 6: Перевірити, що застосунок піднімається**

Run: `venv/Scripts/python.exe -c "from app import create_app; create_app(); print('ok')"`
Expected: `ok` в останньому рядку.

---

## Task 6: Страхувальна джоба й звіт адмінам

**Files:**
- Modify: `app/services/lecturer_certificates.py`
- Modify: `app/services/email_service.py`
- Modify: `app/services/scheduler_service.py`
- Create: `app/templates/emails/admin_lecturer_certificate_report.html`
- Test: `tests/test_services/test_lecturer_certificates.py` (доповнення)

**Interfaces:**
- Consumes: `issue_for_instance` (Task 2).
- Produces:
  - `lecturer_certificates.issue_missing() -> int`
  - `lecturer_certificates.daily_maintenance() -> dict` з ключами `issued`, `stuck`, `blocked`
  - `EmailService.notify_lecturer_certificate_report(stuck, blocked) -> list`

- [ ] **Step 1: Написати падаючі тести**

Дописати у `tests/test_services/test_lecturer_certificates.py`:

```python
def test_issue_missing_picks_up_instance_after_points_added(app):
    inst, _ = _completed_instance(points=None, trainers=1)
    with patch('app.services.email_service.EmailService'
               '.notify_lecturer_certificate_failed'):
        assert lc_svc.issue_for_instance(inst) == []
    inst.course.bpr_lecturer_points = 4
    db.session.commit()
    assert lc_svc.issue_missing() == 1
    assert LecturerCertificate.query.filter_by(instance_id=inst.id).count() == 1


def test_issue_missing_picks_up_trainer_added_later(app):
    inst, _ = _completed_instance(trainers=1)
    lc_svc.issue_for_instance(inst)
    extra = make_trainer(name='Пізній Т.')
    set_trainers(inst.course, [t.id for t in inst.course.trainers] + [extra.id])
    db.session.commit()
    lc_svc.issue_missing()
    assert LecturerCertificate.query.filter_by(
        instance_id=inst.id, trainer_id=extra.id).count() == 1


def test_daily_maintenance_sends_no_report_when_clean(app):
    with patch('app.services.email_service.EmailService'
               '.notify_lecturer_certificate_report') as report:
        lc_svc.daily_maintenance()
    assert not report.called
```

- [ ] **Step 2: Запустити, переконатись що падає**

Run: `venv/Scripts/python.exe -m pytest tests/test_services/test_lecturer_certificates.py -k "issue_missing or daily_maintenance" -v`
Expected: FAIL — `AttributeError`.

- [ ] **Step 3: Написати добір і звіт**

У `app/services/lecturer_certificates.py`:

```python
STUCK_AFTER_HOURS = 24


def issue_missing():
    """Добрати сертифікати завершеним заходам. Повертає кількість виданих.

    Покриває два реальні сценарії: бали БПР внесли вже після завершення
    заходу; тренера додали до складу після завершення. Обидва лишали б
    тренера без документа назавжди, бо тригер спрацьовує рівно один раз.
    """
    from app.models.course_instance import CourseInstance

    instances = CourseInstance.query.filter_by(status='completed').all()
    issued = 0
    for instance in instances:
        trainers = instance.effective_trainers
        if not trainers:
            continue
        have = _issued_trainer_ids(instance)
        if all(t.id in have for t in trainers):
            continue
        issued += len(issue_for_instance(instance))
    return issued


def _issued_trainer_ids(instance):
    from app.models.lecturer_certificate import LecturerCertificate

    rows = db.session.query(LecturerCertificate.trainer_id).filter_by(
        instance_id=instance.id).all()
    return {row[0] for row in rows}


def daily_maintenance():
    """Добір пропущених + звіт адмінам про те, що застрягло.

    Звіт іде ЛИШЕ коли є про що казати: щоденний лист «усе гаразд» перестають
    читати, і разом із ним перестають помічати справжні.
    """
    from datetime import timedelta

    from app.models.course_instance import CourseInstance
    from app.models.lecturer_certificate import LecturerCertificate
    from app.services.email_service import EmailService

    issued = issue_missing()

    cutoff = utcnow() - timedelta(hours=STUCK_AFTER_HOURS)
    stuck = (
        LecturerCertificate.query
        .filter(LecturerCertificate.emailed_at.is_(None),
                LecturerCertificate.issued_at < cutoff)
        .all()
    )
    blocked = [
        inst for inst in CourseInstance.query.filter_by(status='completed').all()
        if inst.effective_trainers and inst.effective_lecturer_points is None
    ]
    if stuck or blocked:
        try:
            EmailService.notify_lecturer_certificate_report(stuck, blocked)
        except Exception:
            db.session.rollback()
            logger.exception('Failed to send lecturer certificate report')
    return {'issued': issued, 'stuck': len(stuck), 'blocked': len(blocked)}
```

- [ ] **Step 4: Додати метод звіту в EmailService**

```python
    @staticmethod
    def notify_lecturer_certificate_report(stuck, blocked):
        """Щоденний звіт адмінам: що застрягло в сертифікатах лектора.

        `stuck` — видані документи, які добу не можуть піти листом (немає
        жодної адреси тренера або пошта стабільно падає). `blocked` — завершені
        заходи, де видачі не було через відсутні бали БПР.
        """
        from app.models.site_settings import SiteSettings

        base = (SiteSettings.get().website_url or '').rstrip('/')
        return EmailService.notify_admins_with_template(
            event_type='certificate',
            subject=(f'Сертифікати лектора: {len(stuck)} не надіслано, '
                     f'{len(blocked)} заходів без балів'),
            template_name='admin_lecturer_certificate_report',
            context={'stuck': stuck, 'blocked': blocked, 'base_url': base},
        )
```

- [ ] **Step 5: Написати шаблон звіту**

Файл `app/templates/emails/admin_lecturer_certificate_report.html`:

```html
{% extends "emails/base.html" %}
{% from "emails/_macros.html" import section_title, spacer %}

{#- Щоденний звіт. Шлеться лише коли є що показати: порожній лист «усе
    гаразд» перестають читати, а разом із ним і справжні. -#}

{% block title %}Сертифікати лектора: потрібна увага{% endblock %}

{% block preview_text %}Документи, які не пішли тренерам{% endblock %}

{% block content %}
    <h1 class="mobile-h1" style="margin: 0 0 24px 0; font-size: 26px; font-weight: 700; color: #17131D; line-height: 1.25;">
        Сертифікати лектора: потрібна увага
    </h1>

    {% if stuck %}
    {{ section_title('Видано, але не надіслано') }}
    <p class="mobile-text" style="margin: 0 0 12px 0; font-size: 15px; color: #625A6D; line-height: 1.5;">
        У цих тренерів немає жодної адреси в анкеті, акаунті чи довіднику —
        або пошта на неї стабільно не доходить.
    </p>
    <ul style="margin: 0 0 24px 0; padding-left: 20px; font-size: 15px; color: #17131D; line-height: 1.6;">
        {% for cert in stuck %}
        <li>{{ cert.number }} — {{ cert.recipient_name }} ({{ cert.event_title }})</li>
        {% endfor %}
    </ul>
    {% endif %}

    {% if blocked %}
    {{ section_title('Заходи без балів БПР тренеру') }}
    <p class="mobile-text" style="margin: 0 0 12px 0; font-size: 15px; color: #625A6D; line-height: 1.5;">
        Захід завершено, але видати сертифікати неможливо. Щойно бали внесуть,
        система видасть їх сама.
    </p>
    <ul style="margin: 0 0 24px 0; padding-left: 20px; font-size: 15px; color: #17131D; line-height: 1.6;">
        {% for inst in blocked %}
        <li><a href="{{ base_url }}/admin/instances/{{ inst.id }}/edit" style="color: #6B3FA0;">{{ inst.effective_title_for('uk') }}</a></li>
        {% endfor %}
    </ul>
    {% endif %}

    {{ spacer(16) }}
{% endblock %}
```

Примітка виконавцю: звірити, що макрос `section_title` існує в `emails/_macros.html` (він використовується в `admin_certificate_failed.html`). Якщо ні — замінити на звичайний `<p>` із тим самим оформленням, що в сусідніх адмінських листах.

- [ ] **Step 6: Зареєструвати щоденну джобу**

У `app/services/scheduler_service.py`:

```python
def lecturer_certificates_maintenance():
    """Daily job: добір пропущених сертифікатів лектора + звіт адмінам."""
    app = scheduler._app
    with app.app_context():
        with _job_lock('lecturer_certificates_daily') as got:
            if not got:
                logger.debug('lecturer_certificates_daily: locked, skipping')
                return
            from app.extensions import db
            from app.services import lecturer_certificates as lc_svc
            try:
                stats = lc_svc.daily_maintenance()
            except Exception:
                db.session.rollback()
                logger.exception('lecturer_certificates_maintenance failed')
                return
            if any(stats.values()):
                logger.info('Сертифікати лектора (добір): %s', stats)
```

Реєстрація:

```python
    scheduler.add_job(
        lecturer_certificates_maintenance,
        trigger=CronTrigger(hour=6, minute=0),  # daily at 6:00 AM
        id='lecturer_certificates_daily',
        replace_existing=True,
        name='Добір сертифікатів лектора і звіт',
    )
```

- [ ] **Step 7: Запустити тести**

Run: `venv/Scripts/python.exe -m pytest tests/test_services/test_lecturer_certificates.py -v`
Expected: PASS.

---

## Task 7: Перевидача скидає `emailed_at`

**Files:**
- Modify: `app/services/certificate_service.py` (`reissue_lecturer_certificate`)
- Test: `tests/test_services/test_certificate_lecturer_multi.py` (доповнення)

**Interfaces:**
- Consumes: `LecturerCertificate.emailed_at` (Task 1).
- Produces: нічого нового.

- [ ] **Step 1: Написати падаючий тест**

Дописати у `tests/test_services/test_certificate_lecturer_multi.py`:

```python
def test_reissue_resets_emailed_at(app):
    """Виправлений документ мусить долетіти тренеру повторно."""
    from app.services import certificate_service as cs
    from app.models.mixins import utcnow

    instance, trainers = _instance_with_trainers(2)  # наявний хелпер файлу
    cert = cs.issue_lecturer_certificate(instance, trainers[0])
    cert.emailed_at = utcnow()
    db.session.commit()

    again = cs.reissue_lecturer_certificate(instance, trainers[0])
    assert again.emailed_at is None
```

Примітка виконавцю: звірити фактичну назву хелпера підготовки заходу в цьому файлі — `grep -n "^def _" tests/test_services/test_certificate_lecturer_multi.py`.

- [ ] **Step 2: Запустити, переконатись що падає**

Run: `venv/Scripts/python.exe -m pytest tests/test_services/test_certificate_lecturer_multi.py -k reissue_resets -v`
Expected: FAIL — `assert <datetime> is None`.

- [ ] **Step 3: Скинути прапорець у перевидачі**

У `app/services/certificate_service.py`, у `reissue_lecturer_certificate`, після `_apply_lecturer_snapshot(...)` і ПЕРЕД `db.session.commit()`:

```python
    # Перевидача означає, що документ змінився: у тренера на руках застаріла
    # версія. Скидання прапорця ставить сертифікат назад у чергу розсилки, і
    # виправлений PDF долітає автоматично.
    lc.emailed_at = None
```

- [ ] **Step 4: Запустити тести**

Run: `venv/Scripts/python.exe -m pytest tests/test_services/test_certificate_lecturer_multi.py tests/test_services/test_lecturer_certificates.py -v`
Expected: PASS.

---

## Task 8: Розділ кабінету «Сертифікати»

**Files:**
- Modify: `app/trainer_cabinet/routes.py`
- Create: `app/templates/trainer_cabinet/certificates.html`
- Create: `app/static/css/page-trainer-certificates.css`
- Modify: `app/templates/trainer_cabinet/_nav.html`
- Test: `tests/test_trainer_cabinet/test_routes_certificates.py`

**Interfaces:**
- Consumes: `LecturerCertificate`, `certificate_service.render_lecturer_pdf`.
- Produces: маршрути `trainer_cabinet.certificates`, `trainer_cabinet.certificate_download`.

- [ ] **Step 1: Написати падаючі тести**

Файл `tests/test_trainer_cabinet/test_routes_certificates.py`:

```python
"""Розділ сертифікатів у кабінеті тренера."""
from app.extensions import db
from app.services import lecturer_certificates as lc_svc
from app.services.trainer_links import set_trainers
from tests.test_trainer_cabinet._factories import (
    login, make_course, make_instance, make_trainer, make_user,
)


def _trainer_with_certificate():
    user = make_user()
    trainer = make_trainer(user, name='Сертифікований Т.')
    course = make_course('Курс із сертифікатом')
    set_trainers(course, [trainer.id])
    course.bpr_lecturer_points = 6
    inst = make_instance(course, days=-3, status='completed')
    db.session.commit()
    cert = lc_svc.issue_for_instance(inst)[0]
    return user, trainer, cert


def test_anonymous_redirected_to_login(client):
    resp = client.get('/trainer/certificates')
    assert resp.status_code == 302
    assert '/auth/login' in resp.headers['Location']


def test_user_without_card_gets_404(client):
    login(client, make_user())
    assert client.get('/trainer/certificates').status_code == 404


def test_section_lists_own_certificate(client):
    user, _, cert = _trainer_with_certificate()
    login(client, user)
    resp = client.get('/trainer/certificates')
    assert resp.status_code == 200
    assert cert.number.encode() in resp.data


def test_section_does_not_list_foreign_certificate(client):
    _, _, foreign = _trainer_with_certificate()
    other_user = make_user()
    make_trainer(other_user, name='Чужий Т.')
    login(client, other_user)
    resp = client.get('/trainer/certificates')
    assert resp.status_code == 200
    assert foreign.number.encode() not in resp.data


def test_download_own_certificate_returns_pdf(client):
    user, _, cert = _trainer_with_certificate()
    login(client, user)
    resp = client.get(f'/trainer/certificates/{cert.id}/download')
    assert resp.status_code == 200
    assert resp.mimetype == 'application/pdf'
    assert resp.data[:4] == b'%PDF'


def test_download_foreign_certificate_is_404(client):
    _, _, foreign = _trainer_with_certificate()
    other_user = make_user()
    make_trainer(other_user, name='Чужий Т. 2')
    login(client, other_user)
    resp = client.get(f'/trainer/certificates/{foreign.id}/download')
    assert resp.status_code == 404
```

- [ ] **Step 2: Запустити, переконатись що падає**

Run: `venv/Scripts/python.exe -m pytest tests/test_trainer_cabinet/test_routes_certificates.py -v`
Expected: FAIL — 404 на всіх маршрутах (їх ще немає).

- [ ] **Step 3: Додати маршрути**

У `app/trainer_cabinet/routes.py`:

```python
@trainer_cabinet_bp.route('/certificates')
@trainer_required
def certificates():
    """Сертифікати тренера: видані за заходи (читання) і власні регалії."""
    from app.models.lecturer_certificate import LecturerCertificate

    issued = (
        LecturerCertificate.query
        .filter_by(trainer_id=g.trainer.id)
        .order_by(LecturerCertificate.issued_at.desc())
        .all()
    )
    return render_template(
        'trainer_cabinet/certificates.html', trainer=g.trainer, issued=issued,
    )


@trainer_cabinet_bp.route('/certificates/<int:cert_id>/download')
@trainer_required
def certificate_download(cert_id):
    """Завантажити власний сертифікат лектора (перевірка володіння).

    404, а не 403: чужий номер не має підтверджувати сам факт існування
    документа — та сама межа, що й у trainer_required.
    """
    from app.models.lecturer_certificate import LecturerCertificate
    from app.services.certificate_service import render_lecturer_pdf

    cert = LecturerCertificate.query.filter_by(
        id=cert_id, trainer_id=g.trainer.id).first()
    if cert is None:
        abort(404)
    try:
        pdf = render_lecturer_pdf(cert)
    except Exception:
        logger.exception('Failed to render lecturer certificate %s', cert.number)
        flash(_('Не вдалося підготувати PDF. Спробуйте пізніше або '
                'зверніться до підтримки.'), 'error')
        return redirect(url_for('trainer_cabinet.certificates'))
    response = send_file(
        io.BytesIO(pdf), mimetype='application/pdf', as_attachment=True,
        download_name=f'lecturer-{cert.number}.pdf',
    )
    response.headers['Cache-Control'] = 'no-store, private'
    return response
```

- [ ] **Step 4: Написати шаблон**

Файл `app/templates/trainer_cabinet/certificates.html`. Структуру заголовка копіювати з `trainer_cabinet/profile.html` (той самий hero-блок). Тіло:

```html
{% extends "base.html" %}

{% block title %}{{ _('Сертифікати | Кабінет тренера | ІПРМ') }}{% endblock %}
{% block extra_meta %}<meta name="robots" content="noindex, nofollow">{% endblock %}

{% block extra_css %}
<link rel="stylesheet" href="{{ url_for('static', filename='css/account.css') }}?v={{ assets_version }}">
<link rel="stylesheet" href="{{ url_for('static', filename='css/page-trainer-certificates.css') }}?v={{ assets_version }}">
{% endblock %}

{% block content %}
<div class="apple-page">
  <div class="iprm-hero-wrap">
    <section class="iprm-hero" aria-labelledby="trainer-certs-title">
      <div class="iprm-hero__content">
        <span class="iprm-eyebrow">{{ _('Кабінет тренера') }}</span>
        <h1 id="trainer-certs-title" class="iprm-hero__title">{{ _('Сертифікати') }}</h1>
      </div>
    </section>
  </div>

  <section class="iprm-block" aria-labelledby="issued-title">
    <h2 id="issued-title" class="iprm-block-title">{{ _('За проведені заходи') }}</h2>
    <p class="account-card__text">
      {{ _('Ці документи видає ІПРМ після завершення заходу і надсилає вам листом. Змінити їх не можна: номер і дані зафіксовані на момент видачі.') }}
    </p>
    {% if issued %}
    <table class="iprm-table">
      <thead>
        <tr>
          <th scope="col">{{ _('Номер') }}</th>
          <th scope="col">{{ _('Захід') }}</th>
          <th scope="col">{{ _('Дата') }}</th>
          <th scope="col">{{ _('Бали БПР') }}</th>
          <th scope="col"><span class="visually-hidden">{{ _('Дії') }}</span></th>
        </tr>
      </thead>
      <tbody>
        {% for cert in issued %}
        <tr>
          <td>{{ cert.number }}</td>
          <td>{{ cert.event_title }}</td>
          <td>{% if cert.event_date %}{{ cert.event_date.strftime('%d.%m.%Y') }}{% endif %}</td>
          <td>{{ cert.cpd_points or '' }}</td>
          <td>
            <a class="btn btn--secondary btn--sm"
               href="{{ url_for('trainer_cabinet.certificate_download', cert_id=cert.id) }}">
              {{ _('Завантажити PDF') }}
            </a>
          </td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
    {% else %}
    <p class="iprm-empty">{{ _('Сертифікатів поки немає. Вони зʼявляться тут після завершення заходу.') }}</p>
    {% endif %}
  </section>
</div>
{% endblock %}
```

Примітка виконавцю: класи `iprm-table`, `btn--secondary`, `iprm-empty`, `visually-hidden` мають існувати в дизайн-системі. Звірити за каталогом `/admin/design-system`; якщо якогось немає — взяти фактичний аналог із сусіднього шаблону кабінету, а НЕ оголошувати новий клас у `page-trainer-certificates.css`. У цей файл ідуть лише сітка й відступи.

- [ ] **Step 5: Створити CSS-файл layout**

Файл `app/static/css/page-trainer-certificates.css`:

```css
/* Layout розділу сертифікатів кабінету тренера: лише сітка й відступи.
   Декор (колір, шрифт, межа, тінь) живе в дизайн-системі — інакше правка
   компонента до цієї сторінки не дійде. */

.trainer-certs__section + .trainer-certs__section {
  margin-top: var(--space-2xl);
}
```

Звірити фактичні імена токенів відступів: `grep -n "space-2xl\|--space-" app/static/css/common.css | head`.

- [ ] **Step 6: Додати картку в навігацію**

У `app/templates/trainer_cabinet/_nav.html`, після картки анкети:

```html
  <a href="{{ url_for('trainer_cabinet.certificates') }}" class="account-card account-card--link">
    <h3 class="iprm-block-title">{{ _('Сертифікати') }}</h3>
    <p class="account-card__text">{{ _('Документи за проведені заходи та ваші власні сертифікати') }}</p>
  </a>
```

- [ ] **Step 7: Додати тест на «Повідомити про помилку»**

Дописати у `tests/test_trainer_cabinet/test_routes_certificates.py`:

```python
def test_report_error_notifies_curator(client):
    from unittest.mock import patch

    user, _, cert = _trainer_with_certificate()
    login(client, user)
    with patch('app.services.email_service.EmailService'
               '.send_lecturer_certificate_complaint') as notify:
        resp = client.post(f'/trainer/certificates/{cert.id}/report',
                           data={'message': 'Помилка в ПІБ'},
                           follow_redirects=True)
    assert resp.status_code == 200
    assert notify.called


def test_report_error_on_foreign_certificate_is_404(client):
    _, _, foreign = _trainer_with_certificate()
    other_user = make_user()
    make_trainer(other_user, name='Чужий Т. 3')
    login(client, other_user)
    resp = client.post(f'/trainer/certificates/{foreign.id}/report',
                       data={'message': 'X'})
    assert resp.status_code == 404
```

Run: `venv/Scripts/python.exe -m pytest tests/test_trainer_cabinet/test_routes_certificates.py -k report_error -v`
Expected: FAIL — маршруту немає.

- [ ] **Step 8: Додати маршрут скарги і метод листа**

У `app/trainer_cabinet/routes.py`:

```python
@trainer_cabinet_bp.route('/certificates/<int:cert_id>/report', methods=['POST'])
@trainer_required
def certificate_report(cert_id):
    """Повідомити куратора про помилку у виданому сертифікаті.

    Сам документ тренер виправити не може -- це незмінний знімок із номером.
    Перевидати його вміє лише адмінка, тож єдине, що тут можна зробити, --
    донести проблему до людини, яка має таке право.
    """
    from app.models.lecturer_certificate import LecturerCertificate
    from app.services.email_service import EmailService

    cert = LecturerCertificate.query.filter_by(
        id=cert_id, trainer_id=g.trainer.id).first()
    if cert is None:
        abort(404)
    message = (request.form.get('message') or '').strip()[:2000]
    try:
        EmailService.send_lecturer_certificate_complaint(cert, message)
    except Exception:
        logger.exception('Failed to report lecturer certificate %s', cert.number)
        flash(_('Не вдалося надіслати повідомлення. Спробуйте пізніше.'), 'error')
        return redirect(url_for('trainer_cabinet.certificates'))
    audit_logger.info('Trainer %s reported lecturer cert %s',
                      g.trainer.id, cert.number)
    flash(_('Повідомлення надіслано куратору'), 'success')
    return redirect(url_for('trainer_cabinet.certificates'))
```

У `app/services/email_service.py`:

```python
    @staticmethod
    def send_lecturer_certificate_complaint(lecturer_cert, message):
        """Куратору: тренер повідомляє про помилку у своєму сертифікаті."""
        from app.models.site_settings import SiteSettings

        base = (SiteSettings.get().website_url or '').rstrip('/')
        tail = f'/admin/instances/{lecturer_cert.instance_id}/edit'
        return EmailService.notify_admins_with_template(
            event_type='certificate',
            subject=f'Тренер повідомляє про помилку в сертифікаті {lecturer_cert.number}',
            template_name='admin_lecturer_certificate_complaint',
            context={
                'certificate': lecturer_cert,
                'message': message,
                'admin_url': f'{base}{tail}' if base else tail,
            },
        )
```

Шаблон `app/templates/emails/admin_lecturer_certificate_complaint.html` зібрати за зразком `admin_lecturer_certificate_failed.html` із Task 2: той самий каркас, у таблиці деталей — `detail_row('Номер', certificate.number)`, `detail_row('Тренер', certificate.recipient_name)` і абзац із `message`.

У шаблон `certificates.html` до кожного рядка таблиці додати форму-кнопку:

```html
<form method="post" class="inline-form"
      action="{{ url_for('trainer_cabinet.certificate_report', cert_id=cert.id) }}">
  <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
  <input type="text" name="message" class="form-input"
         placeholder="{{ _('Що не так?') }}" maxlength="2000">
  <button type="submit" class="btn btn--tertiary btn--sm">{{ _('Повідомити про помилку') }}</button>
</form>
```

- [ ] **Step 9: Запустити тести**

Run: `venv/Scripts/python.exe -m pytest tests/test_trainer_cabinet/ -v`
Expected: PASS (включно з наявними тестами кабінету).

- [ ] **Step 10: Перевірити сторожів дизайн-системи**

Run:
```bash
venv/Scripts/python.exe -m pytest tests/test_design_system/ -v
venv/Scripts/python.exe 1-instruments/design-system/layer_check.py
```
Expected: тести PASS; `layer_check.py` не показує `page-trainer-certificates.css` як компонентний (у нього рівно один шаблон-споживач, і імʼя вже на `page-`).

- [ ] **Step 11: Коміт фази 1**

```bash
git add app/models/lecturer_certificate.py \
        app/services/lecturer_certificates.py \
        app/services/certificate_service.py \
        app/services/email_service.py \
        app/services/scheduler_service.py \
        app/admin/routes_instances.py \
        app/trainer_cabinet/routes.py \
        app/templates/trainer_cabinet/certificates.html \
        app/templates/trainer_cabinet/_nav.html \
        app/templates/emails/lecturer_certificate_issued.html \
        app/templates/emails/admin_lecturer_certificate_failed.html \
        app/templates/emails/admin_lecturer_certificate_report.html \
        app/templates/emails/admin_lecturer_certificate_complaint.html \
        app/static/css/page-trainer-certificates.css \
        migrations/versions/lect_cert_emailed_20260922.py \
        tests/test_db/test_migration_lect_cert_emailed.py \
        tests/test_services/test_lecturer_certificates.py \
        tests/test_services/test_certificate_lecturer_multi.py \
        tests/test_routes/test_instance_status_issues_certs.py \
        tests/test_trainer_cabinet/test_routes_certificates.py
git commit -m "feat(trainer): автовидача сертифікатів лектора, розсилка й розділ у кабінеті"
```

---

# ФАЗА 2 — поле профсертифікатів і регалії в кабінеті

## Task 9: Поле «Професійні сертифікати» в анкеті

**Files:**
- Modify: `app/models/trainer_profile.py`
- Modify: `app/trainer_cabinet/forms.py`
- Modify: `app/templates/trainer_cabinet/profile.html`
- Modify: `app/templates/admin/trainer_questionnaire.html`
- Create: `migrations/versions/trainer_prof_certs_20260922.py`
- Test: `tests/test_trainer_cabinet/test_routes_profile.py` (доповнення)

**Interfaces:**
- Consumes: нічого.
- Produces: `TrainerProfile.professional_certificates` (`db.Text`, nullable); поле форми `professional_certificates`.

- [ ] **Step 1: Написати падаючі тести**

Дописати у `tests/test_trainer_cabinet/test_routes_profile.py`:

```python
def test_professional_certificates_is_saved(client):
    user = make_user()
    trainer = make_trainer(user)
    login(client, user)
    text = 'Сертифікат A, 2024\nСертифікат B, 2025'
    resp = client.post('/trainer/profile', data={
        'full_name': 'Тестовий Тренер',
        'professional_certificates': text,
    }, follow_redirects=True)
    assert resp.status_code == 200
    db.session.refresh(trainer)
    assert trainer.profile.professional_certificates == text


def test_empty_professional_certificates_does_not_break_completeness(app):
    from app.models.trainer_profile import TrainerProfile

    assert 'professional_certificates' not in TrainerProfile.REQUIRED_FOR_COMPLETE
```

Примітка виконавцю: набір обовʼязкових полів у POST звірити з наявними тестами цього файлу — форма може вимагати ще кілька.

- [ ] **Step 2: Запустити, переконатись що падає**

Run: `venv/Scripts/python.exe -m pytest tests/test_trainer_cabinet/test_routes_profile.py -k professional -v`
Expected: FAIL — `AttributeError: 'TrainerProfile' object has no attribute 'professional_certificates'`.

- [ ] **Step 3: Додати колонку в модель**

У `app/models/trainer_profile.py`, ОДРАЗУ ПІСЛЯ `workplace`:

```python
    # Професійні сертифікати для резюме, яке подають до реєстру БПР. Один
    # рядок = один сертифікат: саме з рядків PDF-експорт робить перелік у
    # клітинці таблиці. НЕ те саме, що Trainer.certificates -- там зображення
    # дипломів для публічної сторінки тренера.
    professional_certificates = db.Column(db.Text)
```

У `REQUIRED_FOR_COMPLETE` поле НЕ додавати: інакше всі вже заповнені анкети одномоментно стали б неповними, а тренери отримали б червоний бейдж за те, чого їх ніхто не просив. Сусідні `education` і `workplace` там теж відсутні.

- [ ] **Step 4: Додати поле у форму**

У `app/trainer_cabinet/forms.py`, ОДРАЗУ ПІСЛЯ `workplace`:

```python
    professional_certificates = TextAreaField(
        _l('Професійні сертифікати (по одному в рядку)'),
        validators=[Optional()])
```

І в `MODEL_FIELDS` — після `'workplace'`:

```python
        'full_name', 'birth_date', 'education', 'position_titles', 'workplace',
        'professional_certificates',
        'phone', 'email', 'social_links', 'photo_url', 'fop_recipient', 'fop_iban',
```

- [ ] **Step 5: Додати поле в шаблони**

У `app/templates/trainer_cabinet/profile.html` знайти блок рендеру `form.workplace` і одразу ПІСЛЯ нього додати такий самий блок для `form.professional_certificates` — розмітку копіювати з сусіднього поля, щоб не розійшлась.

У `app/templates/admin/trainer_questionnaire.html` так само додати рядок показу `profile.professional_certificates` після `profile.workplace`. Це НЕ чутливе поле: воно не в `SENSITIVE_FIELDS` і не в `PRIVATE_FIELDS`, тож маскування не потребує.

- [ ] **Step 6: Написати міграцію**

Файл `migrations/versions/trainer_prof_certs_20260922.py`:

```python
"""Колонка professional_certificates у trainer_profiles.

Професійні сертифікати для резюме до реєстру БПР. Текст, один рядок = один
сертифікат. Необовʼязкове: в REQUIRED_FOR_COMPLETE не входить, тож наявні
анкети не стають неповними.

Revision ID: trainer_prof_certs_20260922
Revises: lect_cert_emailed_20260922
"""
import sqlalchemy as sa
from alembic import op

revision = 'trainer_prof_certs_20260922'
down_revision = 'lect_cert_emailed_20260922'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('trainer_profiles', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('professional_certificates', sa.Text()))


def downgrade():
    with op.batch_alter_table('trainer_profiles', schema=None) as batch_op:
        batch_op.drop_column('professional_certificates')
```

- [ ] **Step 7: Застосувати й перевірити оборотність**

Run:
```bash
venv/Scripts/python.exe -m flask db upgrade
venv/Scripts/python.exe -m flask db heads
venv/Scripts/python.exe -m flask db downgrade
venv/Scripts/python.exe -m flask db upgrade
```
Expected: `trainer_prof_certs_20260922 (head)`, один рядок; downgrade і повторний upgrade без помилок.

- [ ] **Step 8: Запустити тести**

Run: `venv/Scripts/python.exe -m pytest tests/test_trainer_cabinet/ -v`
Expected: PASS.

---

## Task 10: Редагування регалій у кабінеті

**Files:**
- Create: `app/static/js/trainer-certificates-editor.js`
- Modify: `app/static/js/admin-trainer-regalia.js`
- Modify: `app/templates/admin/trainer_edit.html`
- Modify: `app/templates/trainer_cabinet/certificates.html`
- Modify: `app/trainer_cabinet/routes.py`
- Test: `tests/test_trainer_cabinet/test_routes_certificates.py` (доповнення)

**Interfaces:**
- Consumes: `trainer_service.sanitize_certificates(items) -> list[dict]`; `media_service.create_from_upload(file, entity_type, entity_id, usage_type, uploader_id) -> (media, error)`.
- Produces: маршрути `trainer_cabinet.certificates_save` (POST `/trainer/certificates`), `trainer_cabinet.certificate_upload` (POST `/trainer/certificates/upload`).

- [ ] **Step 1: Написати падаючі тести**

Дописати у `tests/test_trainer_cabinet/test_routes_certificates.py`:

```python
import io
import json


def test_trainer_saves_own_regalia(client):
    user = make_user()
    trainer = make_trainer(user, name='Регалійний Т.')
    login(client, user)
    payload = json.dumps([
        {'url': '/media/2026/06/a.webp', 'thumb': '/media/2026/06/a.webp',
         'caption': 'Диплом'},
    ])
    resp = client.post('/trainer/certificates',
                       data={'certificates': payload}, follow_redirects=True)
    assert resp.status_code == 200
    db.session.refresh(trainer)
    assert len(trainer.certificates) == 1
    assert trainer.certificates[0]['caption'] == 'Диплом'


def test_save_rejects_invalid_url(client):
    user = make_user()
    trainer = make_trainer(user, name='Невалідний Т.')
    login(client, user)
    payload = json.dumps([{'url': 'javascript:alert(1)', 'caption': 'X'}])
    client.post('/trainer/certificates', data={'certificates': payload},
                follow_redirects=True)
    db.session.refresh(trainer)
    assert trainer.certificates == []


def test_upload_requires_trainer_card(client):
    login(client, make_user())
    resp = client.post('/trainer/certificates/upload', data={
        'file': (io.BytesIO(b'x'), 'a.png')})
    assert resp.status_code == 404


def test_removing_item_clears_it_from_public_page(client):
    """Кабінет і публічна сторінка читають одне сховище, не два."""
    user = make_user()
    trainer = make_trainer(user, name='Прибиральний Т.')
    trainer.certificates = [
        {'url': '/media/2026/06/a.webp', 'thumb': '/media/2026/06/a.webp',
         'caption': 'Диплом'},
    ]
    db.session.commit()
    login(client, user)
    client.post('/trainer/certificates', data={'certificates': '[]'},
                follow_redirects=True)
    db.session.refresh(trainer)
    assert trainer.certificates == []


def test_trainer_cannot_write_foreign_certificates(client):
    user = make_user()
    make_trainer(user, name='Свій Т.')
    foreign = make_trainer(name='Чужий Т. 4')
    foreign.certificates = [
        {'url': '/media/2026/06/b.webp', 'thumb': '/media/2026/06/b.webp',
         'caption': 'Чуже'},
    ]
    db.session.commit()
    login(client, user)
    client.post('/trainer/certificates', data={'certificates': '[]'},
                follow_redirects=True)
    db.session.refresh(foreign)
    assert len(foreign.certificates) == 1
```

- [ ] **Step 2: Запустити, переконатись що падає**

Run: `venv/Scripts/python.exe -m pytest tests/test_trainer_cabinet/test_routes_certificates.py -k "regalia or invalid_url or upload or removing or foreign_certificates" -v`
Expected: FAIL — 404/405 (маршрутів немає).

- [ ] **Step 3: Додати маршрути**

У `app/trainer_cabinet/routes.py`:

```python
@trainer_cabinet_bp.route('/certificates', methods=['POST'])
@trainer_required
def certificates_save():
    """Зберегти власні сертифікати-зображення тренера.

    Санітизація -- тим самим trainer_service.sanitize_certificates, що й в
    адмінці: один санітизатор на обидва входи, тож тренер не може покласти в
    поле те, чого не може покласти адмін.
    """
    import json

    from app.services import trainer_service

    raw = request.form.get('certificates') or '[]'
    try:
        items = json.loads(raw)
    except ValueError:
        items = []
    g.trainer.certificates = trainer_service.sanitize_certificates(items)
    try:
        db.session.commit()
    except Exception:
        logger.exception('Failed to save trainer %s certificates', g.trainer.id)
        db.session.rollback()
        flash(_('Помилка при збереженні'), 'error')
        return redirect(url_for('trainer_cabinet.certificates'))
    audit_logger.info('Trainer %s updated own certificates (%d items)',
                      g.trainer.id, len(g.trainer.certificates))
    flash(_('Сертифікати збережено'), 'success')
    return redirect(url_for('trainer_cabinet.certificates'))


@trainer_cabinet_bp.route('/certificates/upload', methods=['POST'])
@trainer_required
def certificate_upload():
    """Завантажити зображення сертифіката в медіа-реєстр.

    Дзеркало admin.upload_trainer_certificate: той самий виклик і та сама
    відповідь, інша лише перевірка доступу.
    """
    from app.services import media_service

    media, error = media_service.create_from_upload(
        request.files.get('file'), entity_type=None, entity_id=None,
        usage_type='certificate', uploader_id=current_user.id,
    )
    if error:
        return jsonify({'error': error}), 400
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        logger.exception('Failed to persist trainer certificate upload')
        return jsonify({'error': 'Помилка збереження'}), 500
    audit_logger.info('Trainer %s uploaded certificate (media %s)',
                      g.trainer.id, media.id)
    return jsonify({
        'url': media.url, 'thumb': media.variant_url('thumb'),
        'card': media.variant_url('card'), 'media_id': media.id,
        'width': media.width, 'height': media.height,
    }), 200
```

Додати `jsonify` в імпорт `from flask import ...` угорі файлу.

- [ ] **Step 4: Винести редактор у спільний JS**

Спершу знайти межі блоку, який переїжджає:

```bash
grep -n "Сертифікати (зображення)\|Патенти\|---- " app/static/js/admin-trainer-regalia.js
```

Переїжджає рівно фрагмент від рядка з коментарем `// ---- Сертифікати (зображення) ----` до рядка перед наступним таким роздільником (блок патентів). Разом із ним переїжджають хелпери `el`, `icon`, `notify`, `parse` з голови файлу — вони потрібні обом редакторам, тож у `admin-trainer-regalia.js` вони ЛИШАЮТЬСЯ теж (їх вживають патенти й статті). Дублювання чотирьох дрібних хелперів між двома файлами тут дешевше за третій файл-утиліту заради них.

Логіка всередині блоку не змінюється НІЯК, крім одного: жорстка адреса `'/admin/upload/trainer-certificate'` (два входження — `grep -n "trainer-certificate" app/static/js/admin-trainer-regalia.js`) замінюється на змінну `uploadUrl`, прочитану з поля.

Створити `app/static/js/trainer-certificates-editor.js`:

```js
/* Редактор сертифікатів-зображень тренера. Спільний для адмінки й кабінету:
   правка мусить доходити до обох, тож копії другого редактора тут бути не
   повинно. Адреса завантаження -- з data-upload-url на прихованому полі. */
(function () {
  'use strict';

  // Хелпери -- копія з admin-trainer-regalia.js (el, icon, notify, parse).

  function mount(field, grid, fileInput, addBtn) {
    var uploadUrl = field.getAttribute('data-upload-url');
    // Сюди переноситься тіло блоку "Сертифікати (зображення)" без змін:
    // certs/dragFrom/sync/render, обробники dragstart/dragend/dragover/drop,
    // видалення, підпис. Єдина правка -- у завантаженні файлу:
    //   fetch(uploadUrl, {method: 'POST', body: fd})
    // замість жорсткої адреси '/admin/upload/trainer-certificate'.
  }

  document.addEventListener('DOMContentLoaded', function () {
    var field = document.getElementById('regalia-cert-field');
    var grid = document.getElementById('regalia-certs-grid');
    var fileInput = document.getElementById('regalia-cert-file');
    var addBtn = document.getElementById('regalia-cert-add');
    if (field && grid && fileInput && addBtn) mount(field, grid, fileInput, addBtn);
  });
})();
```

З `admin-trainer-regalia.js` блок сертифікатів ВИДАЛИТИ — там лишаються лише патенти й статті. У `admin/trainer_edit.html` підключити обидва файли й додати атрибут:

```html
{{ form.certificates(id="regalia-cert-field", **{"data-upload-url": url_for("admin.upload_trainer_certificate")}) }}
```

- [ ] **Step 5: Додати блок у шаблон кабінету**

У `app/templates/trainer_cabinet/certificates.html`, другою секцією:

```html
  <section class="iprm-block" aria-labelledby="own-title">
    <h2 id="own-title" class="iprm-block-title">{{ _('Власні сертифікати') }}</h2>
    <p class="account-card__text">
      {{ _('Дипломи й посвідчення, які показуються на вашій публічній сторінці тренера. Це не те саме, що поле «Професійні сертифікати» в анкеті: те поле -- текстовий перелік для резюме до реєстру БПР.') }}
    </p>
    <form method="post" action="{{ url_for('trainer_cabinet.certificates_save') }}">
      <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
      <input type="hidden" name="certificates" id="regalia-cert-field"
             value="{{ trainer.certificates | tojson }}"
             data-upload-url="{{ url_for('trainer_cabinet.certificate_upload') }}">
      <div id="regalia-certs-grid" class="regalia-certs-grid"></div>
      <input type="file" id="regalia-cert-file" accept="image/*" hidden>
      <button type="button" id="regalia-cert-add" class="btn btn--secondary">{{ _('Додати сертифікат') }}</button>
      <button type="submit" class="btn btn--primary">{{ _('Зберегти') }}</button>
    </form>
  </section>
```

І в `extra_js` блоці сторінки підключити `trainer-certificates-editor.js`.

Примітка виконавцю: звірити фактичний хелпер CSRF у шаблонах проєкту (`grep -n "csrf_token" app/templates/trainer_cabinet/profile.html`) і вжити той самий.

- [ ] **Step 6: Запустити тести**

Run: `venv/Scripts/python.exe -m pytest tests/test_trainer_cabinet/ tests/test_lint_templates.py -v`
Expected: PASS.

- [ ] **Step 7: Перевірити, що адмінський редактор не зламався**

Run: `venv/Scripts/python.exe -m pytest tests/test_trainer_cabinet/test_admin.py -v`
Expected: PASS. Додатково вручну відкрити `/admin/trainers/<id>/edit` і переконатись, що сітка сертифікатів рендериться й файл завантажується.

- [ ] **Step 8: Коміт фази 2**

```bash
git add app/models/trainer_profile.py \
        app/trainer_cabinet/forms.py \
        app/trainer_cabinet/routes.py \
        app/templates/trainer_cabinet/profile.html \
        app/templates/trainer_cabinet/certificates.html \
        app/templates/admin/trainer_questionnaire.html \
        app/templates/admin/trainer_edit.html \
        app/static/js/trainer-certificates-editor.js \
        app/static/js/admin-trainer-regalia.js \
        migrations/versions/trainer_prof_certs_20260922.py \
        tests/test_trainer_cabinet/test_routes_profile.py \
        tests/test_trainer_cabinet/test_routes_certificates.py
git commit -m "feat(trainer): поле професійних сертифікатів в анкеті й редагування регалій у кабінеті"
```

---

# ФАЗА 3 — PDF-резюме тренерів

## Task 11: Реєстр колонок і збирання рядків

**Files:**
- Create: `app/services/trainer_resume_service.py`
- Test: `tests/test_services/test_trainer_resume.py`

**Interfaces:**
- Consumes: `TrainerProfile.professional_certificates` (Task 9); `rbac.has_permission(user, code)`.
- Produces:
  - `trainer_resume_service.COLUMNS` — кортеж `ResumeColumn(key, label, getter, requires)`
  - `DEFAULT_KEYS: tuple[str, ...]`
  - `available_columns(user) -> list[ResumeColumn]`
  - `normalize_keys(raw_keys, user) -> list[str]`
  - `build_rows(trainers, keys) -> list[list[str]]`

- [ ] **Step 1: Написати падаючі тести**

Файл `tests/test_services/test_trainer_resume.py`:

```python
"""Реєстр колонок резюме тренера."""
from app.extensions import db
from app.models.trainer_profile import TrainerProfile
from app.services import trainer_resume_service as rs
from tests.support.rbac import make_super_admin, make_user_with_role
from tests.test_trainer_cabinet._factories import make_trainer, make_user


def test_default_keys_are_known_columns(app):
    known = {c.key for c in rs.COLUMNS}
    assert set(rs.DEFAULT_KEYS) <= known


def test_normalize_drops_unknown_keys(app):
    admin = make_super_admin(email='tc-res-admin@test.com')
    db.session.commit()
    keys = rs.normalize_keys(['full_name', 'no_such_column'], admin)
    assert keys == ['full_name']


def test_normalize_falls_back_to_defaults_when_empty(app):
    admin = make_super_admin(email='tc-res-admin2@test.com')
    db.session.commit()
    assert rs.normalize_keys([], admin) == list(rs.DEFAULT_KEYS)


def test_normalize_keeps_canonical_order(app):
    admin = make_super_admin(email='tc-res-admin3@test.com')
    db.session.commit()
    canonical = [c.key for c in rs.COLUMNS]
    reversed_pick = list(reversed(canonical[:3]))
    assert rs.normalize_keys(reversed_pick, admin) == canonical[:3]


def test_requisite_fields_are_not_in_registry(app):
    keys = {c.key for c in rs.COLUMNS}
    forbidden = {'fop_iban', 'fop_rnokpp', 'card_number', 'tax_id',
                 'registration_address', 'edrpou'}
    assert keys & forbidden == set()


def test_birth_date_hidden_without_finance_permission(app):
    # content_editor має trainers.view/manage/delete, але НЕ trainers.finance
    # (явний перелік у rbac/registry.py саме заради цього).
    plain = make_user_with_role('content_editor', email='tc-res-plain@test.com')
    db.session.commit()
    assert 'birth_date' not in {c.key for c in rs.available_columns(plain)}


def test_trainer_without_profile_still_yields_row(app):
    trainer = make_trainer(name='Безанкетний Т.')
    db.session.commit()
    rows = rs.build_rows([trainer], ['full_name', 'workplace'])
    assert rows == [['Безанкетний Т.', '']]


def test_profile_name_wins_over_directory_name(app):
    trainer = make_trainer(name='Довідниковий Т.')
    db.session.add(TrainerProfile(trainer_id=trainer.id,
                                  full_name='Анкетний Т.'))
    db.session.commit()
    db.session.refresh(trainer)
    rows = rs.build_rows([trainer], ['full_name'])
    assert rows == [['Анкетний Т.']]
```

Сигнатура хелпера — `make_user_with_role(role_name, email=None, **kwargs)` (`tests/support/rbac.py:18`): першим іде ІМʼЯ РОЛІ, не код права.

- [ ] **Step 2: Запустити, переконатись що падає**

Run: `venv/Scripts/python.exe -m pytest tests/test_services/test_trainer_resume.py -v`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Написати сервіс**

Файл `app/services/trainer_resume_service.py`:

```python
"""Резюме тренерів PDF-таблицею для подачі заходу до реєстру БПР.

Реєстр колонок нижче -- ОДНЕ джерело істини на трьох споживачів: діалог
вибору колонок, шапка PDF і витягання значень у клітинки. Якби підписи жили
в шаблоні, а витягання в маршруті, вони розійшлися б на першій же правці --
і в шапці «Освіта» стояла б над посадами.

Реквізити ФОП, адреси реєстрації та ЄДРПОУ тут НЕМАЄ і бути не повинно:
документ їде в пакеті до реєстру БПР, а замаскований IBAN у поданому
документі виглядав би гірше за його відсутність.
"""
from collections import namedtuple

ResumeColumn = namedtuple('ResumeColumn', 'key label getter requires')


def _profile_field(name):
    """Значення поля анкети; порожньо, якщо анкети ще немає."""
    def getter(trainer):
        profile = trainer.profile
        value = getattr(profile, name, None) if profile is not None else None
        return (value or '').strip() if isinstance(value, str) else (value or '')
    return getter


def _full_name(trainer):
    """ПІБ з анкети, інакше з довідника.

    Тренер без анкети мусить дати рядок із іменем і порожніми клітинками:
    для подачі важливо бачити, кого бракує, а не отримати таблицю, з якої
    людина мовчки зникла.
    """
    profile = trainer.profile
    if profile is not None and (profile.full_name or '').strip():
        return profile.full_name.strip()
    return (trainer.full_name or '').strip()


def _birth_date(trainer):
    profile = trainer.profile
    value = profile.birth_date if profile is not None else None
    return value.strftime('%d.%m.%Y') if value else ''


COLUMNS = (
    ResumeColumn('full_name', 'ПІБ', _full_name, None),
    ResumeColumn('education', 'Освіта',
                 _profile_field('education'), None),
    ResumeColumn('position_titles', 'Посада та регалії',
                 _profile_field('position_titles'), None),
    ResumeColumn('workplace', 'Місце роботи, місто',
                 _profile_field('workplace'), None),
    ResumeColumn('professional_certificates', 'Професійні сертифікати',
                 _profile_field('professional_certificates'), None),
    ResumeColumn('phone', 'Телефон', _profile_field('phone'), None),
    ResumeColumn('email', 'Ел. пошта', _profile_field('email'), None),
    ResumeColumn('social_links', 'Соцмережі',
                 _profile_field('social_links'), None),
    # Персональні дані: та сама межа, що вже діє в анкеті адмінки
    # (TrainerProfile.PRIVATE_FIELDS -- видно лише з trainers.finance).
    ResumeColumn('birth_date', 'Дата народження', _birth_date,
                 'trainers.finance'),
)

# Ядро резюме БПР -- обрані за замовчуванням.
DEFAULT_KEYS = (
    'full_name', 'education', 'position_titles', 'workplace',
    'professional_certificates',
)


def available_columns(user):
    """Колонки, доступні цьому користувачу."""
    from app.rbac import has_permission

    return [c for c in COLUMNS
            if c.requires is None or has_permission(user, c.requires)]


def normalize_keys(raw_keys, user):
    """Обрані ключі -> канонічний порядок реєстру, без невідомих і заборонених.

    Порядок саме канонічний, а не порядок кліків: два вивантаження того самого
    набору мають дати однаковий документ. Порожній набір падає на дефолт.
    """
    allowed = [c.key for c in available_columns(user)]
    picked = {k for k in (raw_keys or []) if k in allowed}
    if not picked:
        return [k for k in DEFAULT_KEYS if k in allowed]
    return [k for k in allowed if k in picked]


def build_rows(trainers, keys):
    """Рядок на тренера, клітинка на колонку -- у порядку keys."""
    by_key = {c.key: c for c in COLUMNS}
    return [[str(by_key[k].getter(t) or '') for k in keys] for t in trainers]


def labels_for(keys):
    """Підписи шапки в тому ж порядку -- з того самого реєстру."""
    by_key = {c.key: c for c in COLUMNS}
    return [by_key[k].label for k in keys]
```

- [ ] **Step 4: Запустити тести**

Run: `venv/Scripts/python.exe -m pytest tests/test_services/test_trainer_resume.py -v`
Expected: PASS.

---

## Task 12: Рендер PDF і маршрут

**Files:**
- Modify: `app/services/trainer_resume_service.py`
- Create: `app/templates/admin/trainer_resume_pdf.html`
- Modify: `app/admin/routes_trainers.py`
- Test: `tests/test_routes/test_trainer_resume_pdf.py`

**Interfaces:**
- Consumes: `normalize_keys`, `build_rows`, `labels_for` (Task 11).
- Produces:
  - `trainer_resume_service.render_pdf(trainers, keys, title=None) -> bytes`
  - маршрут `admin.trainers_resume_pdf` (POST `/admin/trainers/resume.pdf`)

- [ ] **Step 1: Написати падаючі тести**

Файл `tests/test_routes/test_trainer_resume_pdf.py`:

```python
"""PDF-резюме тренерів."""
from app.extensions import db
from tests.support.rbac import make_super_admin, switch_user
from tests.test_trainer_cabinet._factories import make_trainer


def _admin(client):
    admin = make_super_admin(email='tc-resume-admin@test.com')
    db.session.commit()
    switch_user(client, admin)
    return admin


def test_export_returns_pdf(client):
    _admin(client)
    trainer = make_trainer(name='Експортний Т.')
    db.session.commit()
    resp = client.post('/admin/trainers/resume.pdf', data={
        'ids': [str(trainer.id)],
        'columns': ['full_name', 'workplace'],
    })
    assert resp.status_code == 200
    assert resp.mimetype == 'application/pdf'
    assert resp.data[:4] == b'%PDF'


def test_export_without_ids_redirects(client):
    _admin(client)
    resp = client.post('/admin/trainers/resume.pdf', data={'ids': []})
    assert resp.status_code == 302


def test_export_requires_permission(client):
    from tests.test_trainer_cabinet._factories import login, make_user

    login(client, make_user())
    resp = client.post('/admin/trainers/resume.pdf', data={'ids': ['1']})
    assert resp.status_code in (302, 403, 404)


def test_unknown_column_is_ignored(client):
    _admin(client)
    trainer = make_trainer(name='Колонковий Т.')
    db.session.commit()
    resp = client.post('/admin/trainers/resume.pdf', data={
        'ids': [str(trainer.id)],
        'columns': ['full_name', 'fop_iban'],
    })
    assert resp.status_code == 200
    assert resp.data[:4] == b'%PDF'
```

- [ ] **Step 2: Запустити, переконатись що падає**

Run: `venv/Scripts/python.exe -m pytest tests/test_routes/test_trainer_resume_pdf.py -v`
Expected: FAIL — 404 (маршруту немає).

- [ ] **Step 3: Написати PDF-шаблон**

Файл `app/templates/admin/trainer_resume_pdf.html`. `<style>` усередині — це самодостатній друкований документ для WeasyPrint, як і `templates/certificates/certificate.html`; політика «без інлайну» стосується вебсторінок.

```html
<!DOCTYPE html>
<html lang="uk">
<head>
<meta charset="utf-8">
<title>{{ title }}</title>
<style>
  /* Альбомна: таблиця на десяток тренерів у книжкову не влазить. */
  @page { size: A4 landscape; margin: 12mm 10mm; }
  body { font-family: 'DejaVu Sans', sans-serif; font-size: 9pt; color: #17131D; }
  h1 { font-size: 13pt; margin: 0 0 8mm 0; }
  table { width: 100%; border-collapse: collapse; }
  /* Шапка повторюється на кожній сторінці -- інакше з другої сторінки
     незрозуміло, що в якій колонці. */
  thead { display: table-header-group; }
  th, td { border: 0.4pt solid #B9B2C4; padding: 2mm 2.5mm; text-align: left;
           vertical-align: top; }
  th { background: #F7F4FB; font-weight: 600; }
  tr { page-break-inside: avoid; }
  ul { margin: 0; padding-left: 4mm; }
</style>
</head>
<body>
<h1>{{ title }}</h1>
<table>
  <thead>
    <tr>{% for label in labels %}<th>{{ label }}</th>{% endfor %}</tr>
  </thead>
  <tbody>
    {% for row in rows %}
    <tr>
      {% for cell in row %}
      <td>
        {%- set lines = cell.splitlines() | select | list -%}
        {%- if lines | length > 1 -%}
        <ul>{% for line in lines %}<li>{{ line }}</li>{% endfor %}</ul>
        {%- else -%}
        {{ cell }}
        {%- endif -%}
      </td>
      {% endfor %}
    </tr>
    {% endfor %}
  </tbody>
</table>
</body>
</html>
```

- [ ] **Step 4: Додати рендер у сервіс**

У `app/services/trainer_resume_service.py`:

```python
def render_pdf(trainers, keys, title=None):
    """PDF-таблиця резюме. Рядок -- тренер, колонка -- поле анкети."""
    from flask import current_app, render_template
    # WeasyPrint імпортуємо ліниво: на машинах без GTK імпорт може падати,
    # і він не має валити старт застосунку.
    from weasyprint import HTML

    html = render_template(
        'admin/trainer_resume_pdf.html',
        title=title or 'Резюме тренерів',
        labels=labels_for(keys),
        rows=build_rows(trainers, keys),
    )
    return HTML(string=html, base_url=current_app.static_folder).write_pdf()
```

- [ ] **Step 5: Додати маршрут**

У `app/admin/routes_trainers.py`:

```python
@admin_bp.route('/trainers/resume.pdf', methods=['POST'])
@permission_required('trainers.view')
def trainers_resume_pdf():
    """PDF-резюме обраних тренерів для пакета документів при подачі заходу."""
    import io
    from datetime import date

    from flask import send_file

    from app.services import trainer_resume_service as rs

    ids = [int(v) for v in request.form.getlist('ids') if v.isdigit()]
    if not ids:
        flash('Оберіть хоча б одного тренера', 'error')
        return redirect(request.referrer or url_for('admin.trainers_list'))

    trainers = Trainer.query.filter(Trainer.id.in_(ids)).all()
    # Порядок рядків -- як у запиті, а не як віддала БД: адмін обирав тренерів
    # у тому порядку, у якому вони йдуть у поданні заходу.
    by_id = {t.id: t for t in trainers}
    ordered = [by_id[i] for i in ids if i in by_id]
    if not ordered:
        flash('Тренерів не знайдено', 'error')
        return redirect(request.referrer or url_for('admin.trainers_list'))

    keys = rs.normalize_keys(request.form.getlist('columns'), current_user)
    try:
        pdf = rs.render_pdf(ordered, keys)
    except Exception:
        current_app.logger.exception('trainer resume pdf failed')
        flash('Не вдалося сформувати PDF резюме', 'error')
        return redirect(request.referrer or url_for('admin.trainers_list'))

    audit_logger.info(
        'Admin %s exported trainer resume (%d trainers, columns=%s)',
        current_user.email, len(ordered), ','.join(keys),
    )
    response = send_file(
        io.BytesIO(pdf), mimetype='application/pdf', as_attachment=True,
        download_name=f'rezume-treneriv-{date.today():%Y-%m-%d}.pdf',
    )
    response.headers['Cache-Control'] = 'no-store, private'
    return response
```

Примітка виконавцю: звірити фактичну назву маршруту списку тренерів (`grep -n "def trainers_list\|def trainers(" app/admin/routes_trainers.py`) і підставити її в `url_for`.

- [ ] **Step 6: Запустити тести**

Run: `venv/Scripts/python.exe -m pytest tests/test_routes/test_trainer_resume_pdf.py tests/test_services/test_trainer_resume.py -v`
Expected: PASS.

---

## Task 13: Входи в експорт і діалог колонок

**Files:**
- Create: `app/templates/partials/_resume_columns_dialog.html`
- Create: `app/static/js/resume-columns-dialog.js`
- Modify: `app/templates/admin/trainers.html`
- Modify: `app/templates/admin/instance_edit.html`
- Test: `tests/test_routes/test_trainer_resume_pdf.py` (доповнення)

**Interfaces:**
- Consumes: `trainer_resume_service.available_columns(user)`, `DEFAULT_KEYS` (Task 11); маршрут `admin.trainers_resume_pdf` (Task 12).
- Produces: партіал `_resume_columns_dialog.html` з параметрами `columns`, `default_keys`, `action`.

- [ ] **Step 1: Написати падаючий тест**

Дописати у `tests/test_routes/test_trainer_resume_pdf.py`:

```python
def test_dialog_labels_match_pdf_headers(app):
    """Підписи діалогу й шапка PDF беруться з одного реєстру."""
    from app.services import trainer_resume_service as rs

    keys = ['full_name', 'workplace']
    assert rs.labels_for(keys) == [
        c.label for c in rs.COLUMNS if c.key in keys
    ]


def test_instance_page_offers_export(client):
    from app.services.trainer_links import set_trainers
    from tests.test_trainer_cabinet._factories import make_course, make_instance

    _admin(client)
    course = make_course()
    trainer = make_trainer(name='Діалоговий Т.')
    set_trainers(course, [trainer.id])
    inst = make_instance(course)
    db.session.commit()
    resp = client.get(f'/admin/instances/{inst.id}/edit')
    assert resp.status_code == 200
    assert b'resume.pdf' in resp.data
```

- [ ] **Step 2: Запустити, переконатись що падає**

Run: `venv/Scripts/python.exe -m pytest tests/test_routes/test_trainer_resume_pdf.py -k "dialog or instance_page" -v`
Expected: FAIL на `test_instance_page_offers_export` — кнопки ще немає.

- [ ] **Step 3: Написати партіал діалогу**

Файл `app/templates/partials/_resume_columns_dialog.html`:

```html
{#- Діалог вибору колонок резюме. Один партіал на обидва входи (сторінка
    заходу і список тренерів): розійшовшись, вони давали б різні набори
    колонок для того самого документа.

    Параметри: columns -- список ResumeColumn, default_keys -- ключі, обрані
    за замовчуванням, ids -- приховані id тренерів (може бути порожнім, тоді
    їх додає сторінка). -#}
<dialog id="resume-columns-dialog" class="iprm-dialog">
  <form method="post" action="{{ url_for('admin.trainers_resume_pdf') }}"
        id="resume-columns-form">
    <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
    <h2 class="iprm-block-title">Колонки резюме</h2>
    <p class="account-card__text">Оберіть, які поля анкети увійдуть у таблицю.</p>
    <div class="resume-columns__list">
      {% for column in columns %}
      <label class="resume-columns__item">
        <input type="checkbox" name="columns" value="{{ column.key }}"
               {% if column.key in default_keys %}checked{% endif %}>
        <span>{{ column.label }}</span>
      </label>
      {% endfor %}
    </div>
    <div class="resume-columns__ids" id="resume-columns-ids"></div>
    <div class="iprm-dialog__actions">
      <button type="button" class="btn btn--secondary" data-resume-cancel>Скасувати</button>
      <button type="submit" class="btn btn--primary">Сформувати PDF</button>
    </div>
  </form>
</dialog>
```

- [ ] **Step 4: Написати JS діалогу**

Файл `app/static/js/resume-columns-dialog.js`:

```js
/* Діалог вибору колонок резюме тренерів. Кнопка-відкривач несе id тренерів
   у data-trainer-ids; діалог кладе їх у приховані поля форми. */
(function () {
  'use strict';

  document.addEventListener('DOMContentLoaded', function () {
    var dialog = document.getElementById('resume-columns-dialog');
    var idsBox = document.getElementById('resume-columns-ids');
    if (!dialog || !idsBox) return;

    function openWith(ids) {
      idsBox.innerHTML = '';
      ids.forEach(function (id) {
        var input = document.createElement('input');
        input.type = 'hidden';
        input.name = 'ids';
        input.value = id;
        idsBox.appendChild(input);
      });
      dialog.showModal();
    }

    document.querySelectorAll('[data-resume-open]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var raw = btn.getAttribute('data-trainer-ids') || '';
        var ids = raw.split(',').map(function (s) { return s.trim(); })
          .filter(Boolean);
        if (!ids.length) {
          // Список тренерів: id беремо з відмічених галочок рядків.
          ids = Array.prototype.slice
            .call(document.querySelectorAll('input[name="trainer_ids"]:checked'))
            .map(function (el) { return el.value; });
        }
        if (!ids.length) {
          if (typeof window.iprmToast === 'function') {
            window.iprmToast('Оберіть хоча б одного тренера', 'error');
          }
          return;
        }
        openWith(ids);
      });
    });

    dialog.querySelectorAll('[data-resume-cancel]').forEach(function (btn) {
      btn.addEventListener('click', function () { dialog.close(); });
    });
  });
})();
```

- [ ] **Step 5: Підключити на сторінці заходу**

У `app/templates/admin/instance_edit.html`, поряд із блоком тренерів заходу:

```html
{% set lecturers = instance.effective_trainers if instance else [] %}
{% if lecturers %}
<button type="button" class="btn btn--secondary" data-resume-open
        data-trainer-ids="{{ lecturers | map(attribute='id') | join(',') }}">
  Резюме тренерів (PDF)
</button>
{% endif %}
```

І в кінці шаблону — включення партіалу й скрипта:

```html
{% include 'partials/_resume_columns_dialog.html' %}
```

У блоці `extra_js` сторінки підключити `resume-columns-dialog.js`.

Маршрут `admin.instance_edit` має передати в шаблон `resume_columns` і `resume_default_keys`. У `_render_instance_form` (`app/admin/routes_instances.py`) додати в `render_template`:

```python
        resume_columns=rs.available_columns(current_user),
        resume_default_keys=rs.DEFAULT_KEYS,
```

з імпортом `from app.services import trainer_resume_service as rs` угорі функції. У партіалі відповідно вживати `resume_columns` / `resume_default_keys` як `columns` / `default_keys` — передати їх у `include ... with context` або перейменувати змінні у `{% set %}` перед включенням.

- [ ] **Step 6: Підключити у списку тренерів**

У `app/templates/admin/trainers.html` додати до кожного рядка галочку:

```html
<input type="checkbox" name="trainer_ids" value="{{ trainer.id }}"
       aria-label="{{ _('Обрати тренера') }}">
```

і кнопку над таблицею:

```html
<button type="button" class="btn btn--secondary" data-resume-open>
  Резюме обраних (PDF)
</button>
{% include 'partials/_resume_columns_dialog.html' %}
```

Маршрут списку тренерів так само передає `resume_columns` і `resume_default_keys`.

- [ ] **Step 7: Запустити всі тести фази**

Run: `venv/Scripts/python.exe -m pytest tests/test_routes/test_trainer_resume_pdf.py tests/test_services/test_trainer_resume.py tests/test_lint_templates.py -v`
Expected: PASS.

- [ ] **Step 8: Прогнати весь набір тестів**

Run: `venv/Scripts/python.exe -m pytest -q`
Expected: PASS. Якщо валиться `test_api_v1_clients` — новий тест лишив по собі користувачів; прибрати їх у teardown.

- [ ] **Step 9: Перевірити дизайн-систему**

Run:
```bash
venv/Scripts/python.exe -m pytest tests/test_design_system/ -v
node 1-instruments/design-system/atom-audit.cjs
venv/Scripts/python.exe 1-instruments/design-system/shadowed_rules.py
venv/Scripts/python.exe 1-instruments/design-system/layer_check.py
```
Expected: тести PASS; числа не гірші за пороги в `1-instruments/hygiene-ci/thresholds.json`.

- [ ] **Step 10: Коміт фази 3**

```bash
git add app/services/trainer_resume_service.py \
        app/admin/routes_trainers.py \
        app/admin/routes_instances.py \
        app/templates/admin/trainer_resume_pdf.html \
        app/templates/admin/trainers.html \
        app/templates/admin/instance_edit.html \
        app/templates/partials/_resume_columns_dialog.html \
        app/static/js/resume-columns-dialog.js \
        tests/test_services/test_trainer_resume.py \
        tests/test_routes/test_trainer_resume_pdf.py
git commit -m "feat(trainer): PDF-резюме тренерів із вибором колонок"
```

---

## Після реалізації

- [ ] Оновити `README.md` — розділ про кабінет тренера: новий розділ сертифікатів, дві джоби, поле анкети, експорт резюме.
- [ ] Перед деплоєм на прод застосувати ОБИДВІ міграції в порядку `lect_cert_emailed_20260922` -> `trainer_prof_certs_20260922`.
- [ ] Після деплою переконатись, що обидві джоби видно в `/admin/notifications` (список планувальника).
