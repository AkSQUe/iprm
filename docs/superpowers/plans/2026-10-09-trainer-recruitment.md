# Залучення тренерів -- план реалізації

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** заклик «стати тренером» на головній і в `/trainers`, публічна сторінка `/trainers/join` з текстом і анкетою кандидата, заявки в БД з листом Дмитру, адмін-реєстр зі статусами й кнопкою «Створити тренера», тексти сторінки редаговані в адмінці.

**Architecture:** нова модель `TrainerApplication` за зразком `B2BRequest`; перелік питань про плазму -- модуль даних `app/data/trainer_application_questions.py` (no-op `_` для pybabel, як `app/data/specializations.py`); логіка -- сервіс `app/services/trainer_recruitment.py`; публічний маршрут у blueprint `trainers`; адмінка -- `app/admin/routes_trainer_applications.py` через `_listing`; лист -- тип події `trainer_application` у механізмі одержувачів; тексти -- 5 колонок `SiteSettings` з дефолтами в коді (порожнє поле = дефолт, як FAQ кабінету).

**Tech Stack:** Flask, Flask-WTF, SQLAlchemy, Alembic, Jinja2, Flask-Babel, Flask-Limiter, pytest.

**Spec:** `docs/superpowers/specs/2026-10-08-trainer-recruitment-design.md`

## Global Constraints

* Одна гілка `main`, без гілок і ворктрі; коміт після КОЖНОЇ задачі, лише її файли переліком: `git commit -F msg -- <файли>`. `git add -A`, `git add .`, `git commit -a` заборонені. Пуш -- ні.
* Повідомлення комітів українською, без згадок про інструмент чи модель, кінцевий рядок `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`.
* Перед комітом спільних файлів: `git diff -U0 -- <файл> | grep '^@@'` -- усі ханки мають бути свої (у дереві паралельно працюють інші сесії).
* Файл міграції комітиться в ту саму мить, коли створений (див. пам'ять `feedback_untracked_migration`).
* id ревізії alembic <= 32 символів; `down_revision` -- те, що покаже `venv/Scripts/flask.exe db heads` у момент виконання (на 09.10.2026: `paid_at_precision_20261008`).
* Новий тригер листа -- в ОБОХ місцях `EmailLog`: список `TRIGGERS` і хардкод CHECK у `__table_args__`.
* Ні emoji, ні inline-стилів, ні inline-скриптів; без Tailwind.
* CSS: декор -- у компонентних файлах; `page-trainer-join.css` -- лише розкладка. Новий компонент -- у каталозі `/admin/design-system`.
* `tojson` в HTML-атрибуті -- лише в одинарних лапках.
* Переклади ru/en: нові msgid ДОПИСУВАТИ текстом у кінець `app/translations/{ru,en}/LC_MESSAGES/messages.po`; `pybabel update`/`write_po` не вживати; компіляція `cd app && ../venv/Scripts/pybabel.exe compile -d translations`.
* Зелений прогін -- за рядком підсумку pytest (`N passed`), не за exit code після пайпа.
* Публічна сторінка доступна мовами uk/ru/en; анкета не містить ФОП, IBAN, РНОКПП, адреси, дати народження.

## Review Focus

1. Кандидат подає анкету двічі (подвійний клік, кнопка «Назад») -- маємо дві заявки, а не 500; ліміт частоти `5 per hour` не дає засипати Дмитра. Тест у Задачі 3: друга подача з тими самими даними зберігає другу заявку і не падає.
2. «Створити тренера» для кандидата з ПІБ, чий slug уже зайнятий (два «Іваненко Іван») -- другий тренер отримує slug із суфіксом, а не IntegrityError. Тест у Задачі 2.
3. Email кандидата збігається з акаунтом, що вже прив'язаний до іншого тренера, або з непідтвердженим акаунтом -- тренер створюється без прив'язки, адмін бачить попередження. Тест у Задачі 2.
4. Відповідь на питання з вибором приходить зі значенням поза переліком (підроблений POST) -- форма відмовляє, нічого не зберігається. Тест у Задачі 3.
5. Заявка, подана англійською чи російською, показується в адмінці українськими підписами питань (снапшот підпису -- укр. джерело). Тест у Задачі 2.

---

## Структура файлів

| Файл | Відповідальність |
|---|---|
| `app/data/trainer_application_questions.py` (новий) | перелік питань про плазму: key, підпис, тип, варіанти |
| `app/data/trainer_recruit.py` (новий) | дефолтні тексти заклику й сторінки |
| `app/models/trainer_application.py` (новий) | модель заявки |
| `app/models/__init__.py` | реєстрація моделі |
| `app/models/site_settings.py` | 5 колонок текстів + `__translatable__` |
| `app/models/email_log.py`, `app/models/notification_rule.py` | тип події `trainer_application` |
| `migrations/versions/trainer_recruit_20261009.py` (новий) | таблиця, колонки, CHECK-и, рядок правила |
| `app/services/trainer_recruitment.py` (новий) | тексти, абзаци, побудова відповідей, створення заявки, лист, «Створити тренера» |
| `app/services/email_service.py` | `send_trainer_application_notification` |
| `app/templates/emails/trainer_application_notification.html` (новий) | лист |
| `app/trainers/forms.py` (новий) | `TrainerApplicationForm` |
| `app/trainers/routes.py` | `GET/POST /trainers/join` |
| `app/templates/trainers/join.html` (новий) | сторінка |
| `app/templates/partials/_recruit_cta.html` (новий) | смуга заклику |
| `app/static/css/recruit-cta.css` (новий) | компонент смуги |
| `app/static/css/page-trainer-join.css` (новий) | розкладка сторінки |
| `app/templates/main/home.html`, `app/templates/trainers/list.html` | підключення смуги |
| `app/templates/admin/design_system.html`, `app/templates/design_system/_tab_molecules.html` | смуга в каталозі |
| `app/rbac/registry.py` | модуль `trainer_applications` |
| `app/admin/routes_trainer_applications.py` (новий), `app/admin/routes.py` | реєстр, картка, статус, «Створити тренера» |
| `app/templates/admin/trainer_applications.html`, `app/templates/admin/trainer_application_detail.html` (нові) | шаблони адмінки |
| `app/templates/admin/partials/_sidebar.html` | пункт меню |
| `app/admin/routes_notifications.py` | прев'ю листа |
| `app/admin/forms.py`, `app/admin/routes_trainer_cabinet.py`, `app/templates/admin/settings_trainers.html` | редагування текстів |
| `app/services/sitemap_service.py` | сторінка в sitemap |
| `app/translations/{ru,en}/LC_MESSAGES/messages.po` | переклади |

Відхилення від спеки (свідоме): спека казала «міграція заповнює тексти». Натомість колонки порожні, а порожнє поле = дефолт із коду (той самий прийом, що `trainer_faq_html`). Причина: дефолти тоді перекладаються звичайним каталогом `.po` на ru/en, тести бачать ті самі тексти без міграції, а правка дефолту в коді доходить до сайту, поки адмін текст не змінював.

---

### Task 1: Схема даних -- модель, колонки текстів, тип події, міграція

**Files:**
- Create: `app/data/trainer_application_questions.py`
- Create: `app/models/trainer_application.py`
- Create: `migrations/versions/trainer_recruit_20261009.py`
- Modify: `app/models/__init__.py`
- Modify: `app/models/site_settings.py` (після `trainer_contract_uploaded_at`, рядок ~120; і `__translatable__`, рядок 33)
- Modify: `app/models/email_log.py` (CHECK у `__table_args__` ~рядок 71 і `TRIGGERS` ~рядок 133)
- Modify: `app/models/notification_rule.py` (`EVENT_TYPES`)
- Test: `tests/test_models/test_trainer_application.py`, `tests/test_db/test_migration_trainer_recruit.py`

**Interfaces:**
- Produces: `QUESTIONS` -- list[dict] з ключами `key: str`, `label: str` (укр. джерело), `kind: 'choice' | 'text'`, `options: list[tuple[str, str]]` (для `choice`); `question_by_key(key) -> dict | None`.
- Produces: `TrainerApplication` з полями `full_name, phone, email, city, specialty, workplace, social_links, topic, answers (list[{'key','label','value'}]), status, admin_notes, trainer_id, locale, created_at, updated_at`; константа `STATUSES`; властивості `status_label`, `status_badge`, `answer_rows` (list[tuple[label, value_label]]).
- Produces: колонки `SiteSettings.recruit_teaser_title, recruit_teaser_text, recruit_page_title, recruit_page_intro, recruit_page_benefits, recruit_page_closing` (Text, default '').
- Produces: тип події/тригер `'trainer_application'`.

- [ ] **Step 1: Модуль питань**

`app/data/trainer_application_questions.py`:

```python
"""Питання анкети кандидата в тренери про досвід у плазмотерапії.

Перелік живе в коді, а не в таблиці: питання ще уточнюються (Дмитро Бараш
надішле свої), і заміна -- це правка цього файлу без міграції. Подана
заявка зберігає снапшот підпису питання й відповіді (TrainerApplication.
answers), тож зміна переліку не робить старі заявки нечитабельними.

`_` нижче -- no-op маркер для pybabel (той самий прийом, що в
app/data/specializations.py): у переліку лежать українські рядки-джерела,
а переклад для показу робиться на льоту через gettext.
"""


def _(text):
    """No-op маркер: pybabel витягує рядок у каталог, значення не змінюється."""
    return text


QUESTIONS = [
    {
        'key': 'plasma_years',
        'label': _('Як давно ви використовуєте PRP- та плазмотерапію?'),
        'kind': 'choice',
        'options': [
            ('lt1', _('Менше року')),
            ('1_3', _('1-3 роки')),
            ('3_5', _('3-5 років')),
            ('gt5', _('Понад 5 років')),
        ],
    },
    {
        'key': 'tubes_per_day',
        'label': _('Скільки пробірок (процедур) у середньому за день?'),
        'kind': 'choice',
        'options': [
            ('lt5', _('До 5')),
            ('6_10', _('6-10')),
            ('11_20', _('11-20')),
            ('gt20', _('Понад 20')),
        ],
    },
    {
        'key': 'directions',
        'label': _('У яких напрямах застосовуєте плазму?'),
        'kind': 'text',
        'options': [],
    },
    {
        'key': 'equipment',
        'label': _('З якими системами пробірок і обладнанням працюєте?'),
        'kind': 'text',
        'options': [],
    },
    {
        'key': 'teaching',
        'label': _('Чи є досвід виступів або викладання?'),
        'kind': 'choice',
        'options': [
            ('none', _('Немає')),
            ('webinars', _('Вебінари')),
            ('conferences', _('Конференції')),
            ('own_courses', _('Власні курси')),
        ],
    },
]


def question_by_key(key):
    for question in QUESTIONS:
        if question['key'] == key:
            return question
    return None
```

- [ ] **Step 2: Тест моделі (падає)**

`tests/test_models/test_trainer_application.py`:

```python
"""Модель заявки кандидата в тренери."""
import pytest

from app.extensions import db
from app.models.trainer_application import TrainerApplication


def _app(**kw):
    data = dict(full_name='Іваненко Іван', phone='+380501112233',
                email='Cand@Example.com', specialty='Дерматологія',
                topic='PRP у трихології')
    data.update(kw)
    return TrainerApplication(**data)


def test_email_is_normalized_and_status_defaults_to_new(app):
    item = _app()
    db.session.add(item)
    db.session.flush()
    assert item.email == 'cand@example.com'
    assert item.status == 'new'
    assert item.status_label == 'Нова'


def test_invalid_email_rejected(app):
    with pytest.raises(ValueError):
        _app(email='not-an-email')


def test_unknown_status_rejected(app):
    item = _app()
    with pytest.raises(ValueError):
        item.status = 'archived'


def test_answer_rows_use_snapshot_labels(app):
    item = _app(answers=[
        {'key': 'plasma_years', 'label': 'Як давно ви використовуєте PRP- та плазмотерапію?',
         'value': '1_3'},
        {'key': 'directions', 'label': 'У яких напрямах застосовуєте плазму?',
         'value': 'Трихологія'},
        # Питання, якого вже немає в переліку: підпис і значення -- зі снапшоту.
        {'key': 'gone', 'label': 'Старе питання', 'value': 'так'},
    ])
    assert item.answer_rows == [
        ('Як давно ви використовуєте PRP- та плазмотерапію?', '1-3 роки'),
        ('У яких напрямах застосовуєте плазму?', 'Трихологія'),
        ('Старе питання', 'так'),
    ]
```

- [ ] **Step 3: Запустити -- має впасти**

Run: `venv/Scripts/python.exe -m pytest tests/test_models/test_trainer_application.py -q -p no:cacheprovider`
Expected: ERROR `ModuleNotFoundError: No module named 'app.models.trainer_application'`

- [ ] **Step 4: Модель**

`app/models/trainer_application.py`:

```python
"""TrainerApplication -- заявка кандидата в тренери зі сторінки /trainers/join.

Лід-форма за зразком B2BRequest: кандидат лишає контакти, досвід у
плазмотерапії й тему, команда веде заявку в /admin/trainer-applications до
рішення, а погодженого кандидата перетворює на тренера (trainer_id).
"""
import re

from sqlalchemy.orm import validates

from app.data.trainer_application_questions import question_by_key
from app.extensions import db
from app.models.mixins import TimestampMixin, BigIntPK

_EMAIL_RE = re.compile(r'^[^\s@]+@[^\s@]+\.[^\s@]+$')


class TrainerApplication(TimestampMixin, db.Model):
    __tablename__ = 'trainer_applications'

    id = db.Column(BigIntPK, primary_key=True)

    full_name = db.Column(db.String(200), nullable=False)
    phone = db.Column(db.String(20), nullable=False)
    email = db.Column(db.String(255), nullable=False, index=True)
    city = db.Column(db.String(120))
    specialty = db.Column(db.String(255), nullable=False)
    workplace = db.Column(db.Text)
    social_links = db.Column(db.Text)
    topic = db.Column(db.Text, nullable=False)
    # [{'key', 'label', 'value'}] -- снапшот на момент подачі: підпис
    # українським джерелом, значення -- код варіанта або текст відповіді.
    answers = db.Column(db.JSON, default=list, nullable=False)
    # Мова, якою кандидат заповнював сторінку: відповідати йому варто нею.
    locale = db.Column(db.String(5), nullable=False, default='uk')

    status = db.Column(db.String(20), default='new', nullable=False, index=True)
    admin_notes = db.Column(db.Text)
    trainer_id = db.Column(
        db.BigInteger, db.ForeignKey('trainers.id', ondelete='SET NULL'),
        nullable=True,
    )
    trainer = db.relationship('Trainer', foreign_keys=[trainer_id])

    __table_args__ = (
        db.Index('ix_trainer_applications_created_at', 'created_at'),
        db.CheckConstraint(
            "status IN ('new', 'in_progress', 'approved', 'rejected')",
            name='ck_trainer_applications_status',
        ),
    )

    STATUSES = [
        ('new', 'Нова'),
        ('in_progress', 'У роботі'),
        ('approved', 'Погоджено'),
        ('rejected', 'Відмова'),
    ]
    # Модифікатор .badge--* на кожен стан (той самий набір, що в EmailLog).
    STATUS_BADGES = {
        'new': 'pending',
        'in_progress': 'info',
        'approved': 'active',
        'rejected': 'cancelled',
    }

    @property
    def status_label(self):
        return dict(self.STATUSES).get(self.status, self.status)

    @property
    def status_badge(self):
        return self.STATUS_BADGES.get(self.status, 'pending')

    @property
    def answer_rows(self):
        """[(підпис, відповідь)] для адмінки й листа -- українською.

        Код варіанта перекладається підписом із поточного переліку питань;
        якщо питання чи варіанта вже немає, показуємо те, що збережено.
        """
        rows = []
        for item in self.answers or []:
            value = item.get('value') or ''
            question = question_by_key(item.get('key'))
            if question and question['kind'] == 'choice':
                value = dict(question['options']).get(value, value)
            rows.append((item.get('label') or item.get('key') or '', value))
        return rows

    @validates('email')
    def _validate_email(self, _key, value):
        normalized = (value or '').strip().lower()
        if not normalized or len(normalized) > 255 or not _EMAIL_RE.match(normalized):
            raise ValueError(f'невалідний email: {value!r}')
        return normalized

    @validates('status')
    def _validate_status(self, _key, value):
        if value not in {code for code, _ in self.STATUSES}:
            raise ValueError(f'невідомий status: {value!r}')
        return value

    def __repr__(self):
        return f'<TrainerApplication {self.email} {self.status}>'
```

Перевірити, що модифікатор `badge--info` існує: `grep -n "\.badge--info" app/static/css/common.css`. Якщо його немає, замінити `'info'` на `'pending'`.

У `app/models/__init__.py` дописати імпорт поряд із `B2BRequest` (той самий стиль, що в файлі; знайти рядок `grep -n "b2b_request" app/models/__init__.py`):

```python
from app.models.trainer_application import TrainerApplication  # noqa: F401
```

(якщо файл має `__all__`, дописати туди `'TrainerApplication'`).

- [ ] **Step 5: Колонки текстів у SiteSettings**

`app/models/site_settings.py`, у `__translatable__` (рядок 33) дописати поля:

```python
    __translatable__ = (
        'company_name', 'company_full_name', 'address', 'city', 'business_hours',
        'recruit_teaser_title', 'recruit_teaser_text', 'recruit_page_title',
        'recruit_page_intro', 'recruit_page_benefits', 'recruit_page_closing',
    )
```

Після `trainer_contract_uploaded_at`:

```python
    # Запрошення тренерів: заклик на головній і сторінка /trainers/join.
    # Порожнє поле -- дефолтний текст із app/data/trainer_recruit.py (його
    # переклади -- у звичайному каталозі .po), як у trainer_faq_html: правка
    # дефолту в коді доходить до сайту, доки адмін текст не змінював.
    recruit_teaser_title = db.Column(db.Text, nullable=False, default='', server_default='')
    recruit_teaser_text = db.Column(db.Text, nullable=False, default='', server_default='')
    recruit_page_title = db.Column(db.Text, nullable=False, default='', server_default='')
    recruit_page_intro = db.Column(db.Text, nullable=False, default='', server_default='')
    recruit_page_benefits = db.Column(db.Text, nullable=False, default='', server_default='')
    recruit_page_closing = db.Column(db.Text, nullable=False, default='', server_default='')
```

- [ ] **Step 6: Тип події**

`app/models/notification_rule.py`, в кінець `EVENT_TYPES`:

```python
    # Кандидат подав анкету на /trainers/join. Одержувач за замовчуванням --
    # Дмитро Бараш (рядок правила створює міграція trainer_recruit_20261009).
    ('trainer_application', 'Заявка кандидата в тренери'),
```

`app/models/email_log.py`: у CHECK `ck_email_logs_trigger` вставити `'trainer_application', ` перед `'test'`:

```python
            "'trainer_requisites', 'material_request', 'trainer_presentation', "
            "'trainer_application', 'test')",
```

і в `TRIGGERS` перед `('test', 'Тест')`:

```python
        # Лист команді про нову заявку кандидата в тренери (/trainers/join).
        ('trainer_application', 'Заявка кандидата в тренери'),
```

Перевірити, чи CHECK у моделі збігається з останньою міграцією: `grep -n "trainer_presentation" migrations/versions/*.py`. Якщо після `trainer_presentations_20260924` якась ревізія вже змінювала CHECK, `_TRIGGERS_OLD` у міграції нижче брати з НЕЇ.

- [ ] **Step 7: Запустити тест моделі -- проходить**

Run: `venv/Scripts/python.exe -m pytest tests/test_models/test_trainer_application.py -q -p no:cacheprovider`
Expected: `4 passed`

- [ ] **Step 8: Міграція**

Взяти голову: `venv/Scripts/flask.exe db heads` -> `<HEAD>`. `migrations/versions/trainer_recruit_20261009.py`:

```python
"""Залучення тренерів: заявки кандидатів, тексти запрошення, тип листа.

* таблиця trainer_applications;
* 6 колонок site_settings із текстами запрошення (порожнє = дефолт із коду);
* 'trainer_application' у CHECK ck_email_logs_trigger (той самий перелік, що
  в EmailLog.__table_args__ і EmailLog.TRIGGERS) і в
  ck_notification_rules_event_type;
* рядок правила одержувачів: адмінам -- ні, лише додаткова адреса. Адреси
  Дмитра Бараша в репозиторії немає, тож туди лягає email сайту, а якщо й
  його немає -- лист іде адмінам, щоб заявки не губились. Змінюється на
  /admin/notifications/recipients.

Revision ID: trainer_recruit_20261009
Revises: <HEAD>
"""
from datetime import datetime, timezone

import sqlalchemy as sa
from alembic import op

revision = 'trainer_recruit_20261009'
down_revision = '<HEAD>'
branch_labels = None
depends_on = None

_TRIGGERS_OLD = (
    "trigger IN ('registration', 'payment', 'reminder', 'status_change', "
    "'email_confirm', 'course_request', 'certificate', 'blog_comment', "
    "'password_reset', 'backup_failure', 'backup_report', 'materials', "
    "'referral', 'meta_lead', 'transfer', 'quiz', 'trainer_proposal', "
    "'trainer_requisites', 'material_request', 'trainer_presentation', 'test')"
)
_TRIGGERS_NEW = (
    "trigger IN ('registration', 'payment', 'reminder', 'status_change', "
    "'email_confirm', 'course_request', 'certificate', 'blog_comment', "
    "'password_reset', 'backup_failure', 'backup_report', 'materials', "
    "'referral', 'meta_lead', 'transfer', 'quiz', 'trainer_proposal', "
    "'trainer_requisites', 'material_request', 'trainer_presentation', "
    "'trainer_application', 'test')"
)
_TYPES_OLD = ("event_type IN ('registration', 'payment', 'course_request', "
              "'status_change', 'materials', 'meta_lead', 'certificate', "
              "'material_request')")
_TYPES_NEW = ("event_type IN ('registration', 'payment', 'course_request', "
              "'status_change', 'materials', 'meta_lead', 'certificate', "
              "'material_request', 'trainer_application')")

_TEXT_COLUMNS = (
    'recruit_teaser_title', 'recruit_teaser_text', 'recruit_page_title',
    'recruit_page_intro', 'recruit_page_benefits', 'recruit_page_closing',
)


def upgrade():
    op.create_table(
        'trainer_applications',
        sa.Column('id', sa.BigInteger(), primary_key=True),
        sa.Column('full_name', sa.String(length=200), nullable=False),
        sa.Column('phone', sa.String(length=20), nullable=False),
        sa.Column('email', sa.String(length=255), nullable=False),
        sa.Column('city', sa.String(length=120), nullable=True),
        sa.Column('specialty', sa.String(length=255), nullable=False),
        sa.Column('workplace', sa.Text(), nullable=True),
        sa.Column('social_links', sa.Text(), nullable=True),
        sa.Column('topic', sa.Text(), nullable=False),
        sa.Column('answers', sa.JSON(), nullable=False),
        sa.Column('locale', sa.String(length=5), nullable=False, server_default='uk'),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='new'),
        sa.Column('admin_notes', sa.Text(), nullable=True),
        sa.Column('trainer_id', sa.BigInteger(),
                  sa.ForeignKey('trainers.id', ondelete='SET NULL'), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True)),
        sa.Column('updated_at', sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "status IN ('new', 'in_progress', 'approved', 'rejected')",
            name='ck_trainer_applications_status',
        ),
    )
    op.create_index('ix_trainer_applications_email', 'trainer_applications', ['email'])
    op.create_index('ix_trainer_applications_status', 'trainer_applications', ['status'])
    op.create_index('ix_trainer_applications_created_at', 'trainer_applications',
                    ['created_at'])

    with op.batch_alter_table('site_settings', schema=None) as batch_op:
        for name in _TEXT_COLUMNS:
            batch_op.add_column(sa.Column(name, sa.Text(), nullable=False,
                                          server_default=''))

    with op.batch_alter_table('email_logs', schema=None) as batch_op:
        batch_op.drop_constraint('ck_email_logs_trigger', type_='check')
        batch_op.create_check_constraint('ck_email_logs_trigger', _TRIGGERS_NEW)

    op.drop_constraint('ck_notification_rules_event_type', 'notification_rules',
                       type_='check')
    op.create_check_constraint('ck_notification_rules_event_type',
                               'notification_rules', _TYPES_NEW)

    bind = op.get_bind()
    site_email = bind.execute(sa.text('SELECT email FROM site_settings WHERE id = 1')).scalar()
    site_email = (site_email or '').strip().lower()
    rules = sa.table(
        'notification_rules',
        sa.column('event_type', sa.String), sa.column('enabled', sa.Boolean),
        sa.column('notify_admins', sa.Boolean), sa.column('notify_managers', sa.Boolean),
        sa.column('notify_event_trainer', sa.Boolean), sa.column('extra_emails', sa.JSON),
        sa.column('created_at', sa.DateTime(timezone=True)),
        sa.column('updated_at', sa.DateTime(timezone=True)),
    )
    op.bulk_insert(rules, [{
        'event_type': 'trainer_application', 'enabled': True,
        'notify_admins': not site_email, 'notify_managers': False,
        'notify_event_trainer': False,
        'extra_emails': [site_email] if site_email else [],
        'created_at': datetime.now(timezone.utc), 'updated_at': datetime.now(timezone.utc),
    }])


def downgrade():
    op.execute("DELETE FROM notification_rules WHERE event_type = 'trainer_application'")
    op.drop_constraint('ck_notification_rules_event_type', 'notification_rules',
                       type_='check')
    op.create_check_constraint('ck_notification_rules_event_type',
                               'notification_rules', _TYPES_OLD)

    op.execute("DELETE FROM email_logs WHERE trigger = 'trainer_application'")
    with op.batch_alter_table('email_logs', schema=None) as batch_op:
        batch_op.drop_constraint('ck_email_logs_trigger', type_='check')
        batch_op.create_check_constraint('ck_email_logs_trigger', _TRIGGERS_OLD)

    with op.batch_alter_table('site_settings', schema=None) as batch_op:
        for name in reversed(_TEXT_COLUMNS):
            batch_op.drop_column(name)

    op.drop_index('ix_trainer_applications_created_at', table_name='trainer_applications')
    op.drop_index('ix_trainer_applications_status', table_name='trainer_applications')
    op.drop_index('ix_trainer_applications_email', table_name='trainer_applications')
    op.drop_table('trainer_applications')
```

Примітка виконавцю:
* `_TYPES_OLD` звірити з поточним CHECK: `grep -rn "ck_notification_rules_event_type" migrations/versions/*.py` -- останнє значення має збігатися з `_TYPES_OLD`.

- [ ] **Step 9: Тест міграції**

`tests/test_db/test_migration_trainer_recruit.py`:

```python
"""Міграція trainer_recruit_20261009: ланцюжок і збіг CHECK-ів із моделями.

`upgrade()` тут не проганяється -- тестова схема будується create_all (та
сама причина, що в test_migration_lect_cert_emailed.py).
"""
import importlib.util
import re
from pathlib import Path

import pytest

from app.models.email_log import EmailLog
from app.models.notification_rule import EVENT_TYPES

MIGRATION_PATH = (Path(__file__).resolve().parents[2]
                  / 'migrations' / 'versions' / 'trainer_recruit_20261009.py')


@pytest.fixture(scope='module')
def migration():
    spec = importlib.util.spec_from_file_location('m_trainer_recruit', MIGRATION_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _codes(check_sql):
    return set(re.findall(r"'([a-z_]+)'", check_sql))


def test_revision_id_fits_varchar32(migration):
    assert len(migration.revision) <= 32


def test_email_trigger_check_matches_model(migration):
    assert _codes(migration._TRIGGERS_NEW) == set(EmailLog.ALLOWED_TRIGGERS)


def test_event_type_check_matches_model(migration):
    assert _codes(migration._TYPES_NEW) == {code for code, _ in EVENT_TYPES}
```

Run: `venv/Scripts/python.exe -m pytest tests/test_db/test_migration_trainer_recruit.py tests/test_models -q -p no:cacheprovider`
Expected: усі passed.

- [ ] **Step 10: Застосувати на dev-БД і перевірити голову**

Run: `venv/Scripts/flask.exe db upgrade` (без `| grep`), потім `venv/Scripts/flask.exe db heads`
Expected: одна голова `trainer_recruit_20261009 (head)`. Downgrade-upgrade для перевірки оборотності: `venv/Scripts/flask.exe db downgrade -1 && venv/Scripts/flask.exe db upgrade`.

- [ ] **Step 11: Коміт (одразу, з міграцією)**

```bash
git add -- app/data/trainer_application_questions.py app/models/trainer_application.py migrations/versions/trainer_recruit_20261009.py tests/test_models/test_trainer_application.py tests/test_db/test_migration_trainer_recruit.py
git commit -F msg.txt -- app/data/trainer_application_questions.py app/models/trainer_application.py app/models/__init__.py app/models/site_settings.py app/models/email_log.py app/models/notification_rule.py migrations/versions/trainer_recruit_20261009.py tests/test_models/test_trainer_application.py tests/test_db/test_migration_trainer_recruit.py
```

Повідомлення: `feat(trainer-recruit): модель заявки кандидата в тренери, тексти запрошення, тип листа`.

---

### Task 2: Сервіс -- тексти, заявка, лист, «Створити тренера»

**Files:**
- Create: `app/data/trainer_recruit.py`
- Create: `app/services/trainer_recruitment.py`
- Create: `app/templates/emails/trainer_application_notification.html`
- Modify: `app/services/email_service.py` (новий метод після `send_b2b_request_notification`, ~рядок 1742)
- Test: `tests/test_services/test_trainer_recruitment.py`

**Interfaces:**
- Consumes: `QUESTIONS`, `TrainerApplication`, `SiteSettings.recruit_*` (Task 1).
- Produces:
  - `DEFAULTS: dict[str, str]` у `app/data/trainer_recruit.py` -- ключі `recruit_teaser_title`, `recruit_teaser_text`, `recruit_page_title`, `recruit_page_intro`, `recruit_page_benefits`, `recruit_page_closing`.
  - `recruit_text(field, settings=None) -> str` -- текст для поточної локалі.
  - `paragraphs(text) -> list[list[str]]` -- абзаци (порожній рядок) з рядками.
  - `benefit_lines(text) -> list[str]`.
  - `build_answers(form) -> list[dict]`.
  - `create_application(form, locale) -> TrainerApplication` (додає в сесію, не комітить).
  - `notify(application) -> None` (best-effort, ловить винятки).
  - `create_trainer(application) -> tuple[Trainer, str | None]` -- тренер і попередження про прив'язку акаунта (None, якщо все гаразд); кидає `AlreadyConverted`, якщо `trainer_id` уже стоїть. Не комітить.
  - `EmailService.send_trainer_application_notification(application) -> list`.

- [ ] **Step 1: Дефолтні тексти**

`app/data/trainer_recruit.py`:

```python
"""Дефолтні тексти запрошення тренерів (заклик + сторінка /trainers/join).

Текст сторінки -- Альона Вакулін (переписка команди, 10.2026); заклик --
чернетка, доки вона не надішле свій. Порожнє поле SiteSettings.recruit_* =
текст звідси, перекладений каталогом .po. `_` -- no-op маркер для pybabel.
"""


def _(text):
    """No-op маркер: pybabel витягує рядок у каталог, значення не змінюється."""
    return text


DEFAULTS = {
    'recruit_teaser_title': _(
        'Хочете ділитися досвідом у плазмотерапії й отримувати за це гідну винагороду?'),
    'recruit_teaser_text': _(
        'Ставайте тренером ІПРМ: виступи перед колегами, власні курси й команда однодумців.'),
    'recruit_page_title': _('Ваш досвід може стати цінним для інших'),
    'recruit_page_intro': _(
        'Ви використовуєте PRP- та плазмотерапію у своїй практиці, маєте власні '
        'клінічні кейси й результати та відчуваєте, що готові ділитися своїм '
        'досвідом із колегами?\n'
        'Можливо, настав час спробувати себе у ролі тренера ІПРМ.\n'
        '\n'
        'Інститут плазмотерапії та регенеративної медицини запрошує до співпраці '
        'практикуючих спеціалістів, які хочуть не лише розвиватися у своїй '
        'професії, а й навчати, надихати та формувати сильне професійне '
        'середовище навколо себе.'),
    'recruit_page_benefits': _(
        'Ділитися власним практичним досвідом і знаннями\n'
        'Розвивати особистий бренд та експертність\n'
        'Виступати перед професійною аудиторією\n'
        'Бути частиною команди спеціалістів у сфері регенеративної медицини\n'
        'Отримувати задоволення від викладання та гідну матеріальну винагороду '
        'за свою експертність'),
    'recruit_page_closing': _(
        'Маєте досвід. Маєте що передати колегам. Готові зробити наступний '
        'професійний крок?\n'
        '\n'
        'Приєднуйтесь до команди тренерів ІПРМ.\n'
        'Ваш досвід вартий того, щоб ним ділилися.'),
}
```

- [ ] **Step 2: Тести сервісу (падають)**

`tests/test_services/test_trainer_recruitment.py`:

```python
"""Сервіс залучення тренерів."""
from types import SimpleNamespace
from uuid import uuid4

import pytest
from flask_babel import force_locale

from app.data.trainer_recruit import DEFAULTS
from app.extensions import db
from app.models.site_settings import SiteSettings
from app.models.trainer import Trainer
from app.models.trainer_application import TrainerApplication
from app.models.user import User
from app.services import trainer_recruitment as svc


def _uid():
    return uuid4().hex[:8]


def _form(**kw):
    data = {
        'full_name': 'Іваненко Іван Петрович', 'phone': '+380501112233',
        'email': f'cand-{_uid()}@example.com', 'city': 'Київ',
        'specialty': 'Дерматологія', 'workplace': 'Клініка, лікар',
        'social_links': 'https://instagram.com/x', 'topic': 'PRP у трихології',
        'q_plasma_years': '1_3', 'q_tubes_per_day': '6_10',
        'q_directions': 'Трихологія', 'q_equipment': 'Regen Lab',
        'q_teaching': 'webinars',
    }
    data.update(kw)
    return SimpleNamespace(**{k: SimpleNamespace(data=v) for k, v in data.items()})


def _application(**kw):
    item = svc.create_application(_form(**kw), 'uk')
    db.session.flush()
    return item


# --- тексти ----------------------------------------------------------------

def test_empty_setting_falls_back_to_default(app):
    settings = SiteSettings.get()
    settings.recruit_page_title = ''
    assert svc.recruit_text('recruit_page_title', settings) == DEFAULTS['recruit_page_title']


def test_custom_setting_wins(app):
    settings = SiteSettings.get()
    settings.recruit_page_title = 'Свій заголовок'
    assert svc.recruit_text('recruit_page_title', settings) == 'Свій заголовок'


def test_default_is_translated_for_english(app):
    settings = SiteSettings.get()
    settings.recruit_page_title = ''
    with app.test_request_context('/en/'), force_locale('en'):
        assert svc.recruit_text('recruit_page_title', settings) != DEFAULTS['recruit_page_title']


def test_paragraphs_split_on_blank_line_and_keep_lines():
    assert svc.paragraphs('А\nБ\n\nВ') == [['А', 'Б'], ['В']]
    assert svc.paragraphs('') == []


def test_benefit_lines_skip_blanks():
    assert svc.benefit_lines('Перша\n\n Друга \n') == ['Перша', 'Друга']


# --- заявка ----------------------------------------------------------------

def test_answers_store_ukrainian_label_and_code(app):
    item = _application()
    first = item.answers[0]
    assert first == {'key': 'plasma_years',
                     'label': 'Як давно ви використовуєте PRP- та плазмотерапію?',
                     'value': '1_3'}


def test_answers_snapshot_stays_ukrainian_for_english_applicant(app):
    with app.test_request_context('/en/'), force_locale('en'):
        item = svc.create_application(_form(), 'en')
    assert item.locale == 'en'
    assert item.answers[0]['label'] == 'Як давно ви використовуєте PRP- та плазмотерапію?'
    assert item.answer_rows[0] == ('Як давно ви використовуєте PRP- та плазмотерапію?', '1-3 роки')


def test_empty_optional_answer_is_kept_as_empty_string(app):
    item = _application(q_equipment='')
    assert {'key': 'equipment',
            'label': 'З якими системами пробірок і обладнанням працюєте?',
            'value': ''} in item.answers


# --- лист ------------------------------------------------------------------

def test_notify_never_raises(app, monkeypatch):
    item = _application()

    def boom(_application):
        raise RuntimeError('smtp down')

    monkeypatch.setattr('app.services.email_service.EmailService.'
                        'send_trainer_application_notification', staticmethod(boom))
    svc.notify(item)  # без винятку


def test_notification_goes_to_rule_recipients(app, monkeypatch):
    from app.models.notification_rule import NotificationRule
    from app.services.email_service import EmailService

    rule = db.session.get(NotificationRule, 'trainer_application') or NotificationRule(
        event_type='trainer_application')
    rule.enabled = True
    rule.notify_admins = False
    rule.extra_emails = ['dmytro@example.com']
    db.session.add(rule)
    db.session.flush()

    sent = []
    monkeypatch.setattr(EmailService, '_send_to_recipients',
                        staticmethod(lambda recipients, **kw: sent.append((recipients, kw)) or []))
    EmailService.send_trainer_application_notification(_application())
    assert sent[0][0] == ['dmytro@example.com']
    assert sent[0][1]['trigger'] == 'trainer_application'
    assert 'Іваненко Іван Петрович' in sent[0][1]['subject']


def test_notification_template_renders_answers(app):
    from flask import render_template
    item = _application()
    with app.test_request_context('/'):
        html = render_template('emails/trainer_application_notification.html',
                               application=item, admin_url='/admin/trainer-applications/1')
    assert 'Як давно ви використовуєте PRP- та плазмотерапію?' in html
    assert '1-3 роки' in html
    assert 'PRP у трихології' in html


# --- «Створити тренера» ---------------------------------------------------

def test_create_trainer_copies_fields_and_stays_inactive(app):
    item = _application()
    trainer, warning = svc.create_trainer(item)
    db.session.flush()
    assert warning is None
    assert trainer.is_active is False
    assert trainer.full_name == 'Іваненко Іван Петрович'
    assert trainer.email == item.email
    assert trainer.slug.startswith('ivanenko-ivan-petrovych')
    assert trainer.profile.specialty == 'Дерматологія'
    assert trainer.profile.phone == '+380501112233'
    assert trainer.profile.workplace == 'Клініка, лікар'
    assert item.trainer_id == trainer.id


def test_create_trainer_twice_is_refused(app):
    item = _application()
    svc.create_trainer(item)
    db.session.flush()
    with pytest.raises(svc.AlreadyConverted):
        svc.create_trainer(item)


def test_duplicate_name_gets_unique_slug(app):
    first, _ = svc.create_trainer(_application())
    db.session.flush()
    second, _ = svc.create_trainer(_application())
    db.session.flush()
    assert first.slug != second.slug
    assert second.slug.startswith(first.slug)


def test_confirmed_account_is_linked(app):
    email = f'acc-{_uid()}@example.com'
    user = User.create_with_password(email, 'password123', first_name='I', last_name='I',
                                     email_confirmed=True)
    db.session.flush()
    trainer, warning = svc.create_trainer(_application(email=email))
    assert warning is None
    assert trainer.user_id == user.id


def test_unconfirmed_account_not_linked_with_warning(app):
    email = f'acc-{_uid()}@example.com'
    User.create_with_password(email, 'password123', first_name='I', last_name='I',
                              email_confirmed=False)
    db.session.flush()
    trainer, warning = svc.create_trainer(_application(email=email))
    assert trainer.user_id is None
    assert warning


def test_account_of_another_trainer_not_linked(app):
    email = f'acc-{_uid()}@example.com'
    user = User.create_with_password(email, 'password123', first_name='I', last_name='I',
                                     email_confirmed=True)
    db.session.add(Trainer(full_name='Інший', slug=f'other-{_uid()}', user_id=user.id))
    db.session.flush()
    trainer, warning = svc.create_trainer(_application(email=email))
    assert trainer.user_id is None
    assert warning
```

Run: `venv/Scripts/python.exe -m pytest tests/test_services/test_trainer_recruitment.py -q -p no:cacheprovider`
Expected: ERROR `cannot import name 'trainer_recruitment'`.

- [ ] **Step 3: Сервіс**

`app/services/trainer_recruitment.py`:

```python
"""Залучення тренерів: тексти запрошення, заявки кандидатів, перетворення на тренера.

Маршрути (публічний /trainers/join і адмінка /admin/trainer-applications)
лишаються тонкими: усе, що вирішує, як виглядає заявка й тренер із неї,
живе тут.
"""
import logging
import re

from flask_babel import gettext

from app.data.trainer_application_questions import QUESTIONS
from app.data.trainer_recruit import DEFAULTS
from app.extensions import db
from app.models.site_settings import SiteSettings
from app.models.trainer import Trainer
from app.models.trainer_application import TrainerApplication
from app.models.trainer_profile import TrainerProfile
from app.models.user import User
from app.services.certificate_batch import transliterate

logger = logging.getLogger(__name__)


class AlreadyConverted(Exception):
    """Із заявки вже створено тренера."""


# --- тексти ----------------------------------------------------------------

def recruit_text(field, settings=None):
    """Текст запрошення для поточної локалі.

    Збережений адміном текст (з перекладом ru/en, якщо він є) -- інакше
    дефолт із коду, перекладений каталогом.
    """
    settings = settings or SiteSettings.get()
    if (getattr(settings, field, '') or '').strip():
        return settings.t(field)
    return gettext(DEFAULTS[field])


def paragraphs(text):
    """'А\\nБ\\n\\nВ' -> [['А', 'Б'], ['В']]: абзац -- через порожній рядок."""
    blocks = re.split(r'\n\s*\n', (text or '').replace('\r\n', '\n').strip())
    return [[line.strip() for line in block.split('\n') if line.strip()]
            for block in blocks if block.strip()]


def benefit_lines(text):
    return [line.strip() for line in (text or '').replace('\r\n', '\n').split('\n')
            if line.strip()]


# --- заявка ----------------------------------------------------------------

def _value(form, name):
    return (getattr(form, name).data or '').strip()


def build_answers(form):
    """Відповіді на питання про плазму -- снапшот з українським підписом."""
    return [{'key': q['key'], 'label': q['label'], 'value': _value(form, f"q_{q['key']}")}
            for q in QUESTIONS]


def create_application(form, locale):
    application = TrainerApplication(
        full_name=_value(form, 'full_name'),
        phone=_value(form, 'phone'),
        email=_value(form, 'email'),
        city=_value(form, 'city') or None,
        specialty=_value(form, 'specialty'),
        workplace=_value(form, 'workplace') or None,
        social_links=_value(form, 'social_links') or None,
        topic=_value(form, 'topic'),
        answers=build_answers(form),
        locale=locale or 'uk',
    )
    db.session.add(application)
    return application


def notify(application):
    """Лист команді. Best-effort: заявку вже збережено, збій SMTP не має
    впливати на кандидата."""
    from app.services.email_service import EmailService
    try:
        EmailService.send_trainer_application_notification(application)
    except Exception:
        logger.exception('Failed to notify about TrainerApplication #%s', application.id)


# --- «Створити тренера» ---------------------------------------------------

def _unique_slug(full_name):
    base = re.sub(r'[^a-z0-9]+', '-', transliterate(full_name).lower()).strip('-')[:180]
    base = base or 'trainer'
    slug, n = base, 2
    while Trainer.query.filter_by(slug=slug).first() is not None:
        slug = f'{base}-{n}'
        n += 1
    return slug


def _account_for(trainer, email):
    """Акаунт для прив'язки: (user | None, попередження | None).

    Те саме правило, що в адмінці (_apply_account_link): лише підтверджений
    email і лише акаунт, ще не прив'язаний до іншого тренера.
    """
    user = User.query.filter(User.email == email).first()
    if user is None:
        return None, None
    if not user.email_confirmed:
        return None, 'Акаунт із цим email ще не підтвердив адресу -- прив\'яжіть його в картці тренера пізніше'
    taken = Trainer.query.filter(Trainer.user_id == user.id).first()
    if taken is not None and taken is not trainer:
        return None, f'Акаунт із цим email уже прив\'язано до тренера «{taken.full_name}»'
    return user, None


def create_trainer(application):
    """Неактивна картка тренера й анкета з даних заявки. Не комітить."""
    if application.trainer_id is not None:
        raise AlreadyConverted(application.trainer_id)
    trainer = Trainer(
        full_name=application.full_name,
        slug=_unique_slug(application.full_name),
        email=application.email,
        # На публічний сайт тренер потрапить, коли адмін заповнить картку
        # (фото, біографія) і ввімкне його сам.
        is_active=False,
    )
    user, warning = _account_for(trainer, application.email)
    if user is not None:
        trainer.user_id = user.id
    trainer.profile = TrainerProfile(
        full_name=application.full_name,
        specialty=application.specialty,
        workplace=application.workplace,
        phone=application.phone,
        email=application.email,
        social_links=application.social_links,
    )
    db.session.add(trainer)
    db.session.flush()
    application.trainer_id = trainer.id
    return trainer, warning
```

Перевірити, що `Trainer.profile` -- relationship з `uselist=False` (`grep -n "profile = db.relationship" -A3 app/models/trainer.py`). Якщо ні, створювати `TrainerProfile(trainer_id=trainer.id, ...)` після `flush()` і `db.session.add(...)`.

- [ ] **Step 4: Лист і шаблон**

`app/services/email_service.py`, після `send_b2b_request_notification`:

```python
    @staticmethod
    def send_trainer_application_notification(application):
        """Команді: кандидат подав анкету на /trainers/join.

        Власний тригер 'trainer_application': на спільному 'course_request'
        60-секундний dedup за адресою+тригером ковтав би лист, що прийшов у
        ту саму хвилину, що й заявка на курс. Одержувачі -- правило
        /admin/notifications/recipients (за замовчуванням Дмитро Бараш).
        """
        from app.models.site_settings import SiteSettings
        base = (SiteSettings.get().website_url or '').rstrip('/')
        tail = f'/admin/trainer-applications/{application.id}'
        return EmailService.notify_admins_with_template(
            event_type='trainer_application',
            subject=f'Нова заявка кандидата в тренери: {application.full_name}',
            template_name='trainer_application_notification',
            context={
                'application': application,
                'admin_url': f'{base}{tail}' if base else tail,
            },
        )
```

`app/templates/emails/trainer_application_notification.html` (стиль листа -- копія `b2b_request_notification.html`; inline-стилі в листах -- виняток проєкту, бо поштові клієнти не читають зовнішній CSS):

```html
{% extends "emails/base.html" %}
{% from "emails/_macros.html" import button_primary, detail_row, spacer %}

{% block title %}Нова заявка кандидата в тренери{% endblock %}

{% block preview_text %}{{ application.full_name }} -- {{ application.specialty }}{% endblock %}

{% block content %}
    <h1 class="mobile-h1" style="margin: 0 0 8px 0; font-size: 28px; font-weight: 700; color: #17131D; line-height: 1.25;">
        Нова заявка кандидата в тренери
    </h1>

    <p class="mobile-text" style="margin: 0 0 24px 0; font-size: 15px; color: #625A6D; line-height: 1.5;">
        Анкета зі сторінки «Стати тренером». Зв'яжіться з кандидатом і змініть статус заявки в адмінці.
    </p>

    <table role="presentation" style="width: 100%; margin-bottom: 24px; background-color: #F7F4FB; border: 1px solid #E9E4EF; border-radius: 8px;" cellpadding="0" cellspacing="0" border="0">
        <tr>
            <td style="padding: 20px 24px;">
                <p style="margin: 0 0 16px 0; font-size: 18px; font-weight: 600; color: #17131D; line-height: 1.3;">
                    {{ application.full_name }}
                </p>
                {{ detail_row("Телефон", application.phone) }}
                {{ detail_row("Email", application.email) }}
                {% if application.city %}{{ detail_row("Місто", application.city) }}{% endif %}
                {{ detail_row("Спеціальність", application.specialty) }}
                {% if application.workplace %}{{ detail_row("Місце роботи та посада", application.workplace) }}{% endif %}
                {% if application.social_links %}{{ detail_row("Соцмережі або сайт", application.social_links) }}{% endif %}
                {% for label, value in application.answer_rows %}
                {{ detail_row(label, value or '–') }}
                {% endfor %}
                {{ detail_row("Тема", application.topic) }}
            </td>
        </tr>
    </table>

    {{ button_primary("Відкрити заявку в адмінці", admin_url) }}

    {{ spacer(16) }}
{% endblock %}
```

- [ ] **Step 5: Тести проходять**

Run: `venv/Scripts/python.exe -m pytest tests/test_services/test_trainer_recruitment.py -q -p no:cacheprovider`
Expected: усі passed, окрім `test_default_is_translated_for_english` -- він зелений лише після Task 3 Step 9 (переклади). Позначити його `@pytest.mark.xfail(reason='переклади -- Task 3', strict=True)` і зняти позначку в Task 3.

- [ ] **Step 6: Коміт**

Файли: `app/data/trainer_recruit.py app/services/trainer_recruitment.py app/services/email_service.py app/templates/emails/trainer_application_notification.html tests/test_services/test_trainer_recruitment.py` (новим -- `git add --` перед `git commit -F msg -- <ті самі файли>`). Повідомлення: `feat(trainer-recruit): сервіс заявок кандидатів -- тексти, лист, створення тренера`.

---

### Task 3: Публічна сторінка `/trainers/join` і заклик

**Files:**
- Create: `app/trainers/forms.py`
- Modify: `app/trainers/routes.py`
- Create: `app/templates/trainers/join.html`
- Create: `app/templates/partials/_recruit_cta.html`
- Create: `app/static/css/recruit-cta.css`
- Create: `app/static/css/page-trainer-join.css`
- Modify: `app/templates/main/home.html` (після блоку `home-section-cta` у секції тренерів, ~рядок 241; і `extra_css` ~рядок 61)
- Modify: `app/templates/trainers/list.html` (перед `<!-- ===== WHY US ===== -->`; і `extra_css`)
- Modify: `app/templates/admin/design_system.html`, `app/templates/design_system/_tab_molecules.html`
- Modify: `app/services/sitemap_service.py` (`STATIC_URLS`)
- Modify: `app/translations/ru/LC_MESSAGES/messages.po`, `app/translations/en/LC_MESSAGES/messages.po`
- Test: `tests/test_routes/test_trainer_join.py`

**Interfaces:**
- Consumes: `recruit_text`, `paragraphs`, `benefit_lines`, `create_application`, `notify` (Task 2); `QUESTIONS` (Task 1).
- Produces: endpoint `trainers.join` (GET/POST `/trainers/join`); partial `partials/_recruit_cta.html` (чекає змінні контексту відсутні -- сам бере тексти через глобал `recruit_text`); CSS-клас `.iprm-recruit-cta` з елементами `__title`, `__text`, `__actions`.

- [ ] **Step 1: Тести маршруту (падають)**

`tests/test_routes/test_trainer_join.py`:

```python
"""Публічна сторінка «Стати тренером»: рендер, анкета, заклик."""
from uuid import uuid4

import pytest

from app.extensions import db
from app.models.trainer_application import TrainerApplication


def _payload(**kw):
    data = {
        'full_name': 'Іваненко Іван', 'phone': '+380501112233',
        'email': f'cand-{uuid4().hex[:8]}@example.com', 'city': 'Київ',
        'specialty': 'Дерматологія', 'workplace': '', 'social_links': '',
        'topic': 'PRP у трихології', 'consent': 'y',
        'q_plasma_years': '1_3', 'q_tubes_per_day': '6_10',
        'q_directions': 'Трихологія', 'q_equipment': '', 'q_teaching': 'none',
    }
    data.update(kw)
    return data


@pytest.fixture(autouse=True)
def _no_csrf(app):
    prev = app.config.get('WTF_CSRF_ENABLED')
    app.config['WTF_CSRF_ENABLED'] = False
    yield
    app.config['WTF_CSRF_ENABLED'] = prev


@pytest.mark.parametrize('prefix', ['', '/ru', '/en'])
def test_page_renders_in_every_language(client, prefix):
    resp = client.get(f'{prefix}/trainers/join')
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert 'name="q_plasma_years"' in html
    assert 'name="consent"' in html


def test_page_shows_alyona_text_by_default(client):
    html = client.get('/trainers/join').get_data(as_text=True)
    assert 'Ваш досвід може стати цінним для інших' in html
    assert 'Виступати перед професійною аудиторією' in html


def test_submit_saves_application_and_notifies(client, monkeypatch):
    calls = []
    monkeypatch.setattr('app.services.trainer_recruitment.notify', calls.append)
    payload = _payload()
    resp = client.post('/trainers/join', data=payload)
    assert resp.status_code == 302
    assert resp.headers['Location'].endswith('/trainers/join?sent=1')
    item = TrainerApplication.query.filter_by(email=payload['email']).one()
    assert item.topic == 'PRP у трихології'
    assert item.locale == 'uk'
    assert calls == [item]


def test_english_submission_records_locale(client, monkeypatch):
    monkeypatch.setattr('app.services.trainer_recruitment.notify', lambda a: None)
    payload = _payload()
    client.post('/en/trainers/join', data=payload)
    assert TrainerApplication.query.filter_by(email=payload['email']).one().locale == 'en'


def test_thank_you_state(client):
    html = client.get('/trainers/join?sent=1').get_data(as_text=True)
    assert 'Дякуємо' in html
    assert 'name="q_plasma_years"' not in html


@pytest.mark.parametrize('field', ['full_name', 'phone', 'email', 'specialty', 'topic',
                                   'consent', 'q_plasma_years'])
def test_required_field_missing_is_refused(client, monkeypatch, field):
    monkeypatch.setattr('app.services.trainer_recruitment.notify', lambda a: None)
    payload = _payload()
    payload.pop(field)
    resp = client.post('/trainers/join', data=payload)
    assert resp.status_code == 200
    assert TrainerApplication.query.filter_by(email=payload.get('email', '')).count() == 0


def test_choice_outside_options_is_refused(client, monkeypatch):
    monkeypatch.setattr('app.services.trainer_recruitment.notify', lambda a: None)
    payload = _payload(q_tubes_per_day='999')
    resp = client.post('/trainers/join', data=payload)
    assert resp.status_code == 200
    assert TrainerApplication.query.filter_by(email=payload['email']).count() == 0


def test_honeypot_pretends_success_and_saves_nothing(client):
    payload = _payload(website='http://spam.example')
    resp = client.post('/trainers/join', data=payload)
    assert resp.status_code == 302
    assert TrainerApplication.query.filter_by(email=payload['email']).count() == 0


def test_double_submit_keeps_both_and_does_not_fail(client, monkeypatch):
    monkeypatch.setattr('app.services.trainer_recruitment.notify', lambda a: None)
    payload = _payload()
    assert client.post('/trainers/join', data=payload).status_code == 302
    assert client.post('/trainers/join', data=payload).status_code == 302
    assert TrainerApplication.query.filter_by(email=payload['email']).count() == 2


def test_teaser_on_home_and_trainers_list(client):
    from app.models.trainer import Trainer
    # Блок тренерів на головній показується лише за наявності тренерів.
    db.session.add(Trainer(full_name='Тренер', slug=f't-{uuid4().hex[:8]}', is_active=True))
    db.session.commit()
    for url in ('/', '/trainers/'):
        html = client.get(url).get_data(as_text=True)
        assert 'iprm-recruit-cta' in html, url
        assert '/trainers/join' in html, url
```

Run: `venv/Scripts/python.exe -m pytest tests/test_routes/test_trainer_join.py -q -p no:cacheprovider`
Expected: FAIL (404 на `/trainers/join`).

- [ ] **Step 2: Форма**

`app/trainers/forms.py`:

```python
"""Анкета кандидата в тренери (/trainers/join).

Поля питань про плазму будуються з app/data/trainer_application_questions:
префікс q_ + key. Вибір перевіряється проти переліку варіантів (WTForms
SelectField/RadioField відкидає значення поза choices), тож підроблений POST
нічого не збереже.
"""
from flask_babel import lazy_gettext as _l
from flask_wtf import FlaskForm
from wtforms import BooleanField, RadioField, StringField, TextAreaField
from wtforms.validators import DataRequired, Email, InputRequired, Length, Optional

from app.data.trainer_application_questions import QUESTIONS


class _BaseTrainerApplicationForm(FlaskForm):
    full_name = StringField(_l('ПІБ'), validators=[DataRequired(), Length(max=200)])
    phone = StringField(_l('Телефон'), validators=[DataRequired(), Length(max=20)])
    email = StringField(_l('Email'), validators=[
        DataRequired(), Email(message=_l('Вкажіть валідний email')), Length(max=254)])
    city = StringField(_l('Місто'), validators=[Optional(), Length(max=120)])
    specialty = StringField(_l('Спеціальність'), validators=[DataRequired(), Length(max=255)])
    workplace = TextAreaField(_l('Місце роботи та посада'),
                              validators=[Optional(), Length(max=2000)])
    social_links = TextAreaField(_l('Соцмережі або сайт'),
                                 validators=[Optional(), Length(max=2000)])
    topic = TextAreaField(_l('Тема або напрям, з яким готові вийти до колег'),
                          validators=[DataRequired(), Length(max=4000)])
    consent = BooleanField(_l('Погоджуюсь на обробку персональних даних'),
                           validators=[DataRequired()])
    # Honeypot: справжня людина поле не бачить і не заповнює.
    website = StringField()


def _question_field(question):
    label = _l(question['label'])
    if question['kind'] == 'choice':
        return RadioField(label, choices=[(code, _l(text)) for code, text in question['options']],
                          validators=[InputRequired()])
    return TextAreaField(label, validators=[Optional(), Length(max=2000)])


TrainerApplicationForm = type(
    'TrainerApplicationForm',
    (_BaseTrainerApplicationForm,),
    {f"q_{q['key']}": _question_field(q) for q in QUESTIONS},
)
```

Нюанс: `_l(question['label'])` -- аргумент не літерал, pybabel його не побачить; витяг забезпечує no-op `_` у модулі питань. Переклад працює, бо msgid збігається.

- [ ] **Step 3: Маршрут**

`app/trainers/routes.py` -- імпорти доповнити і додати маршрут ПЕРЕД `trainer_detail` (статичний шлях `/join` пріоритетніший за `/<slug>` у Werkzeug і так, але поряд зі списком він читається природніше):

```python
from flask import abort, current_app, flash, redirect, render_template, request, url_for
from flask_babel import get_locale, gettext as _

from app.data.trainer_application_questions import QUESTIONS
from app.extensions import db, limiter
from app.services import trainer_recruitment
from app.services.recaptcha import verify_request as verify_recaptcha
from app.trainers.forms import TrainerApplicationForm
```

```python
@trainers_bp.route('/join', methods=['GET', 'POST'])
@limiter.limit('5 per hour; 20 per day', methods=['POST'])
def join():
    """«Стати тренером»: текст запрошення й анкета кандидата."""
    form = TrainerApplicationForm()
    if request.method == 'POST':
        # Honeypot: боту -- «успіх», у базу нічого.
        if (form.website.data or '').strip():
            current_app.logger.info('trainer_join honeypot triggered')
            return redirect(url_for('trainers.join', sent=1))
        if not verify_recaptcha(action='trainer_join'):
            flash(_('Перевірка reCAPTCHA не пройдена. Спробуйте ще раз.'), 'error')
        elif form.validate():
            application = trainer_recruitment.create_application(form, str(get_locale() or 'uk'))
            try:
                db.session.commit()
            except Exception:
                db.session.rollback()
                current_app.logger.exception('Failed to save TrainerApplication')
                flash(_('Помилка при надсиланні заявки. Спробуйте ще раз.'), 'error')
            else:
                trainer_recruitment.notify(application)
                return redirect(url_for('trainers.join', sent=1))
    texts = {name: trainer_recruitment.recruit_text(name) for name in (
        'recruit_page_title', 'recruit_page_intro', 'recruit_page_benefits',
        'recruit_page_closing')}
    return render_template(
        'trainers/join.html',
        active_nav='trainers',
        form=form,
        questions=QUESTIONS,
        sent=request.args.get('sent') == '1',
        title=texts['recruit_page_title'],
        intro=trainer_recruitment.paragraphs(texts['recruit_page_intro']),
        benefits=trainer_recruitment.benefit_lines(texts['recruit_page_benefits']),
        closing=trainer_recruitment.paragraphs(texts['recruit_page_closing']),
    )
```

Тест підміняє `app.services.trainer_recruitment.notify` -- маршрут викликає його через модуль (`trainer_recruitment.notify`), тож підміна діє.

Тексти заклику партіал бере сам: зареєструвати глобал Jinja в `app/__init__.py` поряд із фільтрами (~рядок 300):

```python
    from app.services.trainer_recruitment import recruit_text
    app.jinja_env.globals['recruit_text'] = recruit_text
```

(Якщо `app/__init__.py` правлять інші сесії -- перевірити ханки перед комітом.)

- [ ] **Step 4: Партіал заклику і компонент**

`app/templates/partials/_recruit_cta.html`:

```html
{# Заклик «стати тренером»: головна (секція тренерів) і /trainers. Тексти --
   SiteSettings.recruit_teaser_* або дефолт (app/data/trainer_recruit.py). #}
<div class="iprm-recruit-cta apple-reveal">
  <p class="iprm-recruit-cta__title">{{ recruit_text('recruit_teaser_title') }}</p>
  <p class="iprm-recruit-cta__text">{{ recruit_text('recruit_teaser_text') }}</p>
  <div class="iprm-recruit-cta__actions">
    <a href="{{ url_for('trainers.join') }}" class="apple-btn apple-btn--primary">{{ _('Долучитися') }}</a>
  </div>
</div>
```

`app/static/css/recruit-cta.css`:

```css
/* ===== Заклик «стати тренером» =====
   Компонент: головна (секція тренерів) і /trainers. Плашка з
   заголовком-обіцянкою, рядком і кнопкою на /trainers/join. */
.iprm-recruit-cta {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
  max-width: 760px;
  margin: 48px auto 0;
  padding: 32px 24px;
  text-align: center;
  background: var(--iprm-surface);
  border: 1px solid var(--iprm-border);
  border-radius: var(--iprm-radius-lg);
}

.iprm-recruit-cta__title {
  margin: 0;
  font-size: clamp(1.125rem, 2.4vw, 1.5rem);
  font-weight: 600;
  line-height: 1.35;
  letter-spacing: -0.01em;
  color: var(--iprm-text);
}

.iprm-recruit-cta__text {
  margin: 0;
  font-size: 1rem;
  line-height: 1.5;
  color: var(--iprm-text-secondary);
}

.iprm-recruit-cta__actions {
  margin-top: 8px;
}

@media (max-width: 768px) {
  .iprm-recruit-cta {
    margin-top: 32px;
    padding: 24px 16px;
  }
}
```

Перед цим звірити назви токенів: `grep -oE "\-\-iprm-(surface|border|radius-lg|text-secondary)[a-z-]*:" app/static/css/common.css | sort -u`. Якщо якогось немає, взяти найближчий наявний (той, яким користується `.apple-feature-card` у `apple-pages.css`).

Підключити на головній (`main/home.html`, у `extra_css` поряд із `page-home.css`) і в `trainers/list.html` (поряд із `trainers.css`):

```html
<link rel="stylesheet" href="{{ url_for('static', filename='css/recruit-cta.css') }}?v={{ assets_version }}">
```

У `main/home.html` після `<div class="home-section-cta apple-reveal">...</div>` секції тренерів:

```html
      {% include 'partials/_recruit_cta.html' %}
```

У `trainers/list.html` -- новою секцією перед `<!-- ===== WHY US ===== -->`:

```html
  <section class="iprm-section iprm-section--compact" aria-label="{{ _('Стати тренером') }}">
    <div class="iprm-section__inner">
      {% include 'partials/_recruit_cta.html' %}
    </div>
  </section>
```

- [ ] **Step 5: Шаблон сторінки**

`app/templates/trainers/join.html`:

```html
{% extends "base.html" %}

{% block title %}{{ _('Стати тренером ІПРМ') }}{% endblock %}
{% block meta_description %}{{ title }}{% endblock %}

{% block extra_css %}
<link rel="stylesheet" href="{{ url_for('static', filename='css/trainers.css') }}?v={{ assets_version }}">
<link rel="stylesheet" href="{{ url_for('static', filename='css/page-trainer-join.css') }}?v={{ assets_version }}">
{% endblock %}

{% block content %}
<div class="apple-page page-trainer-join">
  <div class="iprm-hero-wrap">
    <section class="iprm-hero" aria-labelledby="join-title">
      <div class="iprm-hero__content">
        <span class="iprm-eyebrow">{{ _('Стати тренером') }}</span>
        <h1 id="join-title" class="iprm-hero__title">{{ title }}</h1>
        {% for block in intro %}
        <p class="iprm-hero__subtitle">{% for line in block %}{{ line }}{% if not loop.last %}<br>{% endif %}{% endfor %}</p>
        {% endfor %}
        {% if not sent %}
        <div class="iprm-hero__actions">
          <a href="#application" class="apple-btn apple-btn--primary">{{ _('Заповнити анкету') }}</a>
        </div>
        {% endif %}
      </div>
    </section>
  </div>

  {% if benefits %}
  <section class="iprm-section" aria-labelledby="join-benefits-title">
    <div class="iprm-section__inner">
      <h2 id="join-benefits-title" class="iprm-section__title apple-reveal">{{ _('Тренерство в ІПРМ -- це можливість') }}</h2>
      <div class="apple-features-grid">
        {% for item in benefits %}
        <div class="apple-feature-card apple-reveal"><p>{{ item }}</p></div>
        {% endfor %}
      </div>
    </div>
  </section>
  {% endif %}

  {% if closing %}
  <section class="iprm-section iprm-section--compact" aria-label="{{ _('Запрошення') }}">
    <div class="iprm-section__inner page-trainer-join__closing">
      {% for block in closing %}
      <p class="iprm-section__subtitle">{% for line in block %}{{ line }}{% if not loop.last %}<br>{% endif %}{% endfor %}</p>
      {% endfor %}
    </div>
  </section>
  {% endif %}

  <section id="application" class="iprm-section apple-section-gray" aria-labelledby="join-form-title">
    <div class="iprm-section__inner page-trainer-join__form-wrap">
      {% if sent %}
      <div class="iprm-empty-state" role="status">
        <h2 id="join-form-title" class="iprm-section__title">{{ _('Дякуємо!') }}</h2>
        <p>{{ _('Заявку отримано. Ми зв\'яжемося з вами найближчим часом.') }}</p>
      </div>
      {% else %}
      <h2 id="join-form-title" class="iprm-section__title">{{ _('Анкета кандидата') }}</h2>
      {% include 'partials/flash_messages.html' %}
      <form method="post" action="{{ url_for('trainers.join') }}#application" class="form-stack" novalidate>
        {{ form.hidden_tag() }}
        <div class="form-honeypot" aria-hidden="true">
          <label for="website">Website</label>
          {{ form.website(id='website', tabindex='-1', autocomplete='off') }}
        </div>

        <fieldset class="form-fieldset">
          <legend class="form-legend">{{ _('Про себе') }}</legend>
          {% for name in ['full_name', 'phone', 'email', 'city', 'specialty', 'workplace', 'social_links'] %}
          {% set field = form[name] %}
          <div class="form-group">
            <label for="{{ field.id }}">{{ field.label.text }}{% if field.flags.required %} <span class="required">*</span>{% endif %}</label>
            {{ field(class="form-input" + (" is-invalid" if field.errors else ""), rows=3 if field.type == 'TextAreaField' else none) }}
            {% for error in field.errors %}<div class="form-error">{{ error }}</div>{% endfor %}
          </div>
          {% endfor %}
        </fieldset>

        <fieldset class="form-fieldset">
          <legend class="form-legend">{{ _('Досвід у плазмотерапії') }}</legend>
          {% for q in questions %}
          {% set field = form['q_' ~ q.key] %}
          <div class="form-group">
            {% if q.kind == 'choice' %}
            <span class="form-label" id="{{ field.id }}-label">{{ field.label.text }} <span class="required">*</span></span>
            <div class="form-choices" role="radiogroup" aria-labelledby="{{ field.id }}-label">
              {% for option in field %}
              <label class="form-choice">{{ option() }} {{ option.label.text }}</label>
              {% endfor %}
            </div>
            {% else %}
            <label for="{{ field.id }}">{{ field.label.text }}</label>
            {{ field(class="form-input", rows=2) }}
            {% endif %}
            {% for error in field.errors %}<div class="form-error">{{ error }}</div>{% endfor %}
          </div>
          {% endfor %}
        </fieldset>

        <fieldset class="form-fieldset">
          <legend class="form-legend">{{ _('Що хочете викладати') }}</legend>
          <div class="form-group">
            <label for="{{ form.topic.id }}">{{ form.topic.label.text }} <span class="required">*</span></label>
            {{ form.topic(class="form-input" + (" is-invalid" if form.topic.errors else ""), rows=4) }}
            {% for error in form.topic.errors %}<div class="form-error">{{ error }}</div>{% endfor %}
          </div>
          <div class="form-checkbox">
            {{ form.consent(id='consent') }}
            <label for="consent">{{ form.consent.label.text }} (<a href="{{ url_for('main.privacy') }}" target="_blank" rel="noopener">{{ _('політика конфіденційності') }}</a>)</label>
            {% for error in form.consent.errors %}<div class="form-error">{{ error }}</div>{% endfor %}
          </div>
        </fieldset>

        <button type="submit" class="apple-btn apple-btn--primary">{{ _('Надіслати анкету') }}</button>
      </form>
      {% endif %}
    </div>
  </section>
</div>
{% endblock %}

{% block extra_scripts %}
<script src="{{ url_for('static', filename='js/apple-reveal.js') }}" defer></script>
{% endblock %}
```

Перед цим звірити, які класи форм уже є в дизайн-системі (`grep -nE "\.(form-stack|form-fieldset|form-legend|form-label|form-choices|form-choice|form-honeypot|form-checkbox)\b" app/static/css/*.css`). Для кожного ВІДСУТНЬОГО -- взяти наявний аналог (як зроблено honeypot у B2B-формі `courses/list.html`: `grep -n "website" app/templates/courses/list.html`) і НЕ оголошувати новий декор у `page-trainer-join.css`. Якщо аналога для радіо-груп немає, додати `.form-choices`/`.form-choice` у той компонентний CSS, де живе `.form-checkbox`, і показати в каталозі (Step 6).

Якщо блоку `meta_description` у `base.html` немає (`grep -n "block meta_description" app/templates/base.html`), прибрати цей рядок.

`app/static/css/page-trainer-join.css` (лише розкладка):

```css
/* Сторінка «Стати тренером» (/trainers/join): лише розкладка. */
.page-trainer-join__closing {
  max-width: 760px;
  text-align: center;
}

.page-trainer-join__form-wrap {
  max-width: 720px;
}
```

- [ ] **Step 6: Каталог дизайн-системи**

`app/templates/admin/design_system.html` -- поряд із `course-landing.css` (рядок ~65):

```html
<link rel="stylesheet" href="{{ url_for('static', filename='css/recruit-cta.css') }}?v={{ assets_version }}">
```

`app/templates/design_system/_tab_molecules.html` -- нова секція поруч із CTA-блоками (знайти `grep -n "cta" app/templates/design_system/_tab_molecules.html`):

```html
  <!-- ===== ЗАКЛИК «СТАТИ ТРЕНЕРОМ» ===== -->
  <div class="ds-section" id="recruit-cta">
    <p class="ds-label">Components</p>
    <h2 class="ds-title">Заклик «стати тренером»</h2>
    <div class="ds-demo">
      <div class="iprm-recruit-cta">
        <p class="iprm-recruit-cta__title">Хочете ділитися досвідом у плазмотерапії й отримувати за це гідну винагороду?</p>
        <p class="iprm-recruit-cta__text">Ставайте тренером ІПРМ: виступи перед колегами, власні курси й команда однодумців.</p>
        <div class="iprm-recruit-cta__actions"><a href="#" class="apple-btn apple-btn--primary">Долучитися</a></div>
      </div>
    </div>
    <p class="ds-hint">Партіал <code class="ds-code">partials/_recruit_cta.html</code>, CSS <code class="ds-code">recruit-cta.css</code>. Головна (секція тренерів) і <code class="ds-code">/trainers</code>. Тексти -- «Налаштування -> Для тренерів».</p>
  </div>
```

Якщо в табі є навігація за id (`grep -n 'href="#feature-cards"' app/templates/design_system/*.html app/templates/admin/design_system.html`), додати туди пункт `#recruit-cta`.

- [ ] **Step 7: Sitemap**

`app/services/sitemap_service.py`, у `STATIC_URLS` після `('trainers.trainer_list', '0.8', 'weekly'),`:

```python
    ('trainers.join', '0.6', 'monthly'),
```

- [ ] **Step 8: Тести маршруту проходять**

Run: `venv/Scripts/python.exe -m pytest tests/test_routes/test_trainer_join.py -q -p no:cacheprovider`
Expected: усі passed. Якщо тест із `consent` падає, бо `BooleanField` + `DataRequired` на відсутньому полі дає 200 -- це і є очікувана відмова; перевірити лише, що заявка не збережена.

- [ ] **Step 9: Переклади ru/en**

Зібрати всі нові msgid (дефолтні тексти з `app/data/trainer_recruit.py`, питання й варіанти з `app/data/trainer_application_questions.py`, мітки форми, рядки шаблонів `join.html` і `_recruit_cta.html`). Перевірити, яких ще немає в каталогах:

```bash
venv/Scripts/python.exe -c "from babel.messages.pofile import read_po; import sys; ids={m.id for m in read_po(open('app/translations/ru/LC_MESSAGES/messages.po','rb')) if m.id}; [print(s) for s in sys.argv[1:] if s not in ids]" "ПІБ" "Телефон" "Email" "Місто" "Спеціальність"
```

Для відсутніх ДОПИСАТИ записи в кінець обох `.po` (UTF-8, без BOM; багаторядкові msgid -- з `\n` усередині рядка, як у Python-джерелі, `"` і `\` екранувати). Переклади:

| uk | ru | en |
|---|---|---|
| Хочете ділитися досвідом у плазмотерапії й отримувати за це гідну винагороду? | Хотите делиться опытом в плазмотерапии и получать за это достойное вознаграждение? | Want to share your plasma therapy expertise and be well rewarded for it? |
| Ставайте тренером ІПРМ: виступи перед колегами, власні курси й команда однодумців. | Становитесь тренером ИПРМ: выступления перед коллегами, собственные курсы и команда единомышленников. | Become an IPRM trainer: speak to colleagues, run your own courses and join a like-minded team. |
| Ваш досвід може стати цінним для інших | Ваш опыт может стать ценным для других | Your experience can be valuable to others |
| (вступ, 3 частини) | Вы используете PRP- и плазмотерапию в своей практике, имеете собственные клинические кейсы и результаты и чувствуете, что готовы делиться своим опытом с коллегами?\nВозможно, пришло время попробовать себя в роли тренера ИПРМ.\n\nИнститут плазмотерапии и регенеративной медицины приглашает к сотрудничеству практикующих специалистов, которые хотят не только развиваться в своей профессии, но и обучать, вдохновлять и формировать сильную профессиональную среду вокруг себя. | Do you use PRP and plasma therapy in your practice, have your own clinical cases and results, and feel ready to share your experience with colleagues?\nPerhaps it is time to try yourself as an IPRM trainer.\n\nThe Institute of Plasma Therapy and Regenerative Medicine invites practising specialists who want not only to grow in their profession but also to teach, inspire and build a strong professional community around them. |
| (переваги, 5 рядків) | Делиться собственным практическим опытом и знаниями\nРазвивать личный бренд и экспертность\nВыступать перед профессиональной аудиторией\nБыть частью команды специалистов в сфере регенеративной медицины\nПолучать удовольствие от преподавания и достойное материальное вознаграждение за свою экспертность | Share your own practical experience and knowledge\nGrow your personal brand and expertise\nSpeak to a professional audience\nBe part of a team of regenerative medicine specialists\nEnjoy teaching and earn a fair reward for your expertise |
| (закриття) | Есть опыт. Есть что передать коллегам. Готовы сделать следующий профессиональный шаг?\n\nПрисоединяйтесь к команде тренеров ИПРМ.\nВаш опыт стоит того, чтобы им делились. | You have experience. You have something to pass on to colleagues. Ready to take the next professional step?\n\nJoin the IPRM trainer team.\nYour experience is worth sharing. |
| Як давно ви використовуєте PRP- та плазмотерапію? | Как давно вы используете PRP- и плазмотерапию? | How long have you been using PRP and plasma therapy? |
| Менше року / 1-3 роки / 3-5 років / Понад 5 років | Меньше года / 1-3 года / 3-5 лет / Более 5 лет | Less than a year / 1-3 years / 3-5 years / Over 5 years |
| Скільки пробірок (процедур) у середньому за день? | Сколько пробирок (процедур) в среднем в день? | How many tubes (procedures) per day on average? |
| До 5 / 6-10 / 11-20 / Понад 20 | До 5 / 6-10 / 11-20 / Более 20 | Up to 5 / 6-10 / 11-20 / Over 20 |
| У яких напрямах застосовуєте плазму? | В каких направлениях применяете плазму? | In which fields do you use plasma? |
| З якими системами пробірок і обладнанням працюєте? | С какими системами пробирок и оборудованием работаете? | Which tube systems and equipment do you work with? |
| Чи є досвід виступів або викладання? | Есть ли опыт выступлений или преподавания? | Do you have speaking or teaching experience? |
| Немає / Вебінари / Конференції / Власні курси | Нет / Вебинары / Конференции / Собственные курсы | None / Webinars / Conferences / Own courses |
| ПІБ | ФИО | Full name |
| Місто | Город | City |
| Місце роботи та посада | Место работы и должность | Workplace and position |
| Соцмережі або сайт | Соцсети или сайт | Social media or website |
| Тема або напрям, з яким готові вийти до колег | Тема или направление, с которым готовы выйти к коллегам | Topic or field you are ready to present to colleagues |
| Погоджуюсь на обробку персональних даних | Согласен на обработку персональных данных | I agree to the processing of my personal data |
| політика конфіденційності | политика конфиденциальности | privacy policy |
| Стати тренером ІПРМ | Стать тренером ИПРМ | Become an IPRM trainer |
| Стати тренером | Стать тренером | Become a trainer |
| Заповнити анкету | Заполнить анкету | Fill in the application |
| Тренерство в ІПРМ -- це можливість | Тренерство в ИПРМ -- это возможность | Training at IPRM is a chance to |
| Запрошення | Приглашение | Invitation |
| Дякуємо! | Спасибо! | Thank you! |
| Заявку отримано. Ми зв'яжемося з вами найближчим часом. | Заявка получена. Мы свяжемся с вами в ближайшее время. | Application received. We will contact you shortly. |
| Анкета кандидата | Анкета кандидата | Application form |
| Про себе | О себе | About you |
| Досвід у плазмотерапії | Опыт в плазмотерапии | Plasma therapy experience |
| Що хочете викладати | Что хотите преподавать | What you want to teach |
| Надіслати анкету | Отправить анкету | Send application |
| Долучитися | Присоединиться | Join |

Компіляція: `cd app && ../venv/Scripts/pybabel.exe compile -d translations && cd ..`. Зняти `xfail` з `test_default_is_translated_for_english` (Task 2).

Run: `venv/Scripts/python.exe -m pytest tests/test_seo/test_catalogs.py tests/test_i18n tests/test_services/test_trainer_recruitment.py tests/test_routes/test_trainer_join.py -q -p no:cacheprovider`
Expected: усі passed.

- [ ] **Step 10: Сторожі дизайн-системи**

Run: `venv/Scripts/python.exe tools/ds/ds_audit.py` (exit 0) і `venv/Scripts/python.exe -m pytest tests/test_design_system tests/test_lint_templates.py -q -p no:cacheprovider`
Expected: passed. Якщо `ds_audit` бачить `recruit-cta.css` поза каталогом -- перевірити Step 6; якщо `page-trainer-join.css` має декор -- перенести.

- [ ] **Step 11: Перевірка в браузері**

Пам'ять `reference_visual_check`: playwright у venv працює системним Chrome. Запустити dev-сервер, відкрити `/trainers/join` на 375px і 1280px, `/` (секція тренерів) і `/trainers`; подати анкету з порожніми полями (видно помилки), повністю (сторінка подяки); світла й темна тема. Знімки -- у scratchpad.

- [ ] **Step 12: Коміт**

Файли: `app/trainers/forms.py app/trainers/routes.py app/__init__.py app/templates/trainers/join.html app/templates/partials/_recruit_cta.html app/static/css/recruit-cta.css app/static/css/page-trainer-join.css app/templates/main/home.html app/templates/trainers/list.html app/templates/admin/design_system.html app/templates/design_system/_tab_molecules.html app/services/sitemap_service.py app/translations/ru/LC_MESSAGES/messages.po app/translations/en/LC_MESSAGES/messages.po app/translations/ru/LC_MESSAGES/messages.mo app/translations/en/LC_MESSAGES/messages.mo tests/test_routes/test_trainer_join.py tests/test_services/test_trainer_recruitment.py` (+ компонентний CSS форм, якщо правився). Чи версіонуються `.mo` -- `git ls-files app/translations | grep "\.mo$"`; якщо ні, не додавати. Повідомлення: `feat(trainer-recruit): сторінка «Стати тренером» з анкетою і заклик на головній`.

---

### Task 4: Адмінка заявок -- реєстр, картка, статус, «Створити тренера», лист у прев'ю

**Files:**
- Modify: `app/rbac/registry.py` (модуль після `b2b_requests`, ролі `manager`, `marketer`)
- Create: `app/admin/routes_trainer_applications.py`
- Modify: `app/admin/routes.py` (імпорт поряд із `routes_b2b_requests`)
- Create: `app/templates/admin/trainer_applications.html`
- Create: `app/templates/admin/trainer_application_detail.html`
- Modify: `app/templates/admin/partials/_sidebar.html` (група заявок, ~рядок 67-80)
- Modify: `app/admin/routes_notifications.py` (прев'ю, поряд із `'b2b-request'` ~рядок 550)
- Test: `tests/test_routes/test_admin_trainer_applications.py`

**Interfaces:**
- Consumes: `TrainerApplication`, `create_trainer`, `AlreadyConverted` (Task 1-2).
- Produces: endpoints `admin.trainer_applications_list` (GET `/admin/trainer-applications`), `admin.trainer_application_detail` (GET `/admin/trainer-applications/<id>`), `admin.trainer_application_update` (POST `.../<id>/update`), `admin.trainer_application_create_trainer` (POST `.../<id>/create-trainer`); права `trainer_applications.view`, `trainer_applications.manage`.

- [ ] **Step 1: Тести (падають)**

`tests/test_routes/test_admin_trainer_applications.py`:

```python
"""Адмінка заявок кандидатів у тренери."""
from uuid import uuid4

import pytest

from app.extensions import db
from app.models.trainer import Trainer
from app.models.trainer_application import TrainerApplication
from tests.support.rbac import make_super_admin, make_user_with_role, switch_user


@pytest.fixture(autouse=True)
def _no_csrf(app):
    prev = app.config.get('WTF_CSRF_ENABLED')
    app.config['WTF_CSRF_ENABLED'] = False
    yield
    app.config['WTF_CSRF_ENABLED'] = prev


@pytest.fixture
def application(app):
    item = TrainerApplication(
        full_name='Петренко Олена', phone='+380671112233',
        email=f'olena-{uuid4().hex[:8]}@example.com', specialty='Гінекологія',
        topic='PRP у гінекології',
        answers=[{'key': 'plasma_years',
                  'label': 'Як давно ви використовуєте PRP- та плазмотерапію?', 'value': 'gt5'}],
    )
    db.session.add(item)
    db.session.commit()
    return item


@pytest.fixture
def admin(app):
    user = make_super_admin()
    db.session.commit()
    return user


def test_role_without_permission_gets_403(client, application):
    # content_editor не має trainer_applications.* (RoleSpec у registry.py).
    user = make_user_with_role('content_editor')
    db.session.commit()
    switch_user(client, user)
    assert client.get('/admin/trainer-applications').status_code == 403


def test_anonymous_is_sent_away(app, application):
    resp = app.test_client().get('/admin/trainer-applications')
    assert resp.status_code in (302, 401, 403)


def test_list_shows_application(client, admin, application):
    switch_user(client, admin)
    html = client.get('/admin/trainer-applications').get_data(as_text=True)
    assert 'Петренко Олена' in html
    assert f'/admin/trainer-applications/{application.id}' in html


def test_detail_shows_answers_in_ukrainian(client, admin, application):
    switch_user(client, admin)
    html = client.get(f'/admin/trainer-applications/{application.id}').get_data(as_text=True)
    assert 'Як давно ви використовуєте PRP- та плазмотерапію?' in html
    assert 'Понад 5 років' in html
    assert 'PRP у гінекології' in html


def test_update_status_and_notes(client, admin, application):
    switch_user(client, admin)
    resp = client.post(f'/admin/trainer-applications/{application.id}/update',
                       data={'status': 'in_progress', 'admin_notes': 'Подзвонити в понеділок'})
    assert resp.status_code == 302
    db.session.refresh(application)
    assert application.status == 'in_progress'
    assert application.admin_notes == 'Подзвонити в понеділок'


def test_update_unknown_status_refused(client, admin, application):
    switch_user(client, admin)
    client.post(f'/admin/trainer-applications/{application.id}/update',
                data={'status': 'archived'})
    db.session.refresh(application)
    assert application.status == 'new'


def test_create_trainer_only_for_approved(client, admin, application):
    switch_user(client, admin)
    client.post(f'/admin/trainer-applications/{application.id}/create-trainer')
    db.session.refresh(application)
    assert application.trainer_id is None


def test_create_trainer_redirects_to_trainer_edit(client, admin, application):
    application.status = 'approved'
    db.session.commit()
    switch_user(client, admin)
    resp = client.post(f'/admin/trainer-applications/{application.id}/create-trainer')
    db.session.refresh(application)
    assert application.trainer_id is not None
    assert resp.status_code == 302
    assert resp.headers['Location'].endswith(f'/admin/trainers/{application.trainer_id}/edit')
    trainer = db.session.get(Trainer, application.trainer_id)
    assert trainer.is_active is False


def test_second_create_does_not_duplicate(client, admin, application):
    application.status = 'approved'
    db.session.commit()
    switch_user(client, admin)
    client.post(f'/admin/trainer-applications/{application.id}/create-trainer')
    count = Trainer.query.count()
    client.post(f'/admin/trainer-applications/{application.id}/create-trainer')
    assert Trainer.query.count() == count


def test_detail_links_existing_trainer(client, admin, application):
    application.status = 'approved'
    db.session.commit()
    switch_user(client, admin)
    client.post(f'/admin/trainer-applications/{application.id}/create-trainer')
    html = client.get(f'/admin/trainer-applications/{application.id}').get_data(as_text=True)
    assert f'/admin/trainers/{application.trainer_id}/edit' in html
    assert 'create-trainer' not in html


def test_email_preview_lists_trainer_application(client, admin):
    switch_user(client, admin)
    html = client.get('/admin/notifications/templates').get_data(as_text=True)
    assert 'Заявка кандидата в тренери' in html
```

Перед запуском звірити сигнатури хелперів: `sed -n 1,40p tests/support/rbac.py` (чи `make_super_admin` комітить сам, чи `switch_user(client, user)` -- саме такий порядок аргументів) і маршрут прев'ю листів: `grep -n "@admin_bp.route('/notifications" app/admin/routes_notifications.py`.

Run: `venv/Scripts/python.exe -m pytest tests/test_routes/test_admin_trainer_applications.py -q -p no:cacheprovider`
Expected: FAIL (404).

- [ ] **Step 2: RBAC**

`app/rbac/registry.py` після модуля `b2b_requests`:

```python
    Module('trainer_applications', 'Кандидати в тренери', 'requests', ('view', 'manage'),
           endpoint='admin.trainer_applications_list'),
```

У `RoleSpec('manager', ...)` дописати `'trainer_applications.*'` поряд із `'b2b_requests.*'`; у `RoleSpec('marketer', ...)` -- `'trainer_applications.view'` поряд із `'b2b_requests.view'`. (`flask rbac sync` під час деплою створить права; наявним ролям на проді їх видають у матриці `/admin/access` -- див. Task 6.)

- [ ] **Step 3: Маршрути**

`app/admin/routes_trainer_applications.py`:

```python
"""Admin: заявки кандидатів у тренери (сторінка /trainers/join)."""
import logging

from flask import flash, redirect, render_template, request, url_for
from flask_login import current_user

from app.admin import _listing, admin_bp
from app.extensions import db
from app.models.trainer_application import TrainerApplication
from app.rbac import permission_required
from app.services import trainer_recruitment

audit_logger = logging.getLogger('audit')


def _filters():
    return {
        'q': _listing.text_arg('q'),
        'status': _listing.choice_arg('status', dict(TrainerApplication.STATUSES)),
        'date_from': _listing.date_arg('date_from'),
        'date_to': _listing.date_arg('date_to'),
        'per_page': _listing.choice_arg('per_page', _listing.PER_PAGE_CHOICES),
    }


def _query(filters):
    query = _listing.apply_search(TrainerApplication.query, filters['q'], [
        TrainerApplication.full_name, TrainerApplication.email,
        TrainerApplication.phone, TrainerApplication.specialty,
        TrainerApplication.topic, TrainerApplication.admin_notes,
    ])
    if filters['status']:
        query = query.filter(TrainerApplication.status == filters['status'])
    query = _listing.apply_date_range(
        query, TrainerApplication.created_at, filters['date_from'], filters['date_to'],
    )
    return query.order_by(TrainerApplication.created_at.desc())


@admin_bp.route('/trainer-applications')
@permission_required('trainer_applications.view')
def trainer_applications_list():
    filters = _filters()
    pagination = _query(filters).paginate(
        page=_listing.page_arg(), per_page=_listing.per_page_arg(), error_out=False,
    )
    filter_args = _listing.filter_args(filters)
    return render_template(
        'admin/trainer_applications.html',
        applications=pagination.items,
        pagination=pagination,
        per_page_options=_listing.PER_PAGE_OPTIONS,
        filters=filters,
        filter_args=filter_args,
        status_options=TrainerApplication.STATUSES,
        new_count=TrainerApplication.query.filter_by(status='new').count(),
    )


def _get_or_404(application_id):
    item = db.session.get(TrainerApplication, application_id)
    if item is None:
        from flask import abort
        abort(404)
    return item


@admin_bp.route('/trainer-applications/<int:application_id>')
@permission_required('trainer_applications.view')
def trainer_application_detail(application_id):
    return render_template(
        'admin/trainer_application_detail.html',
        application=_get_or_404(application_id),
        status_options=TrainerApplication.STATUSES,
    )


def _back(application_id):
    return redirect(url_for('admin.trainer_application_detail', application_id=application_id))


@admin_bp.route('/trainer-applications/<int:application_id>/update', methods=['POST'])
@permission_required('trainer_applications.manage')
def trainer_application_update(application_id):
    item = _get_or_404(application_id)
    new_status = request.form.get('status', '')
    if new_status not in {code for code, _ in TrainerApplication.STATUSES}:
        flash('Невідомий статус', 'error')
        return _back(item.id)
    item.status = new_status
    item.admin_notes = (request.form.get('admin_notes') or '').strip()[:4000] or None
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        flash('Не вдалося зберегти заявку', 'error')
        return _back(item.id)
    audit_logger.info('Admin %s updated TrainerApplication #%s -> %s',
                      current_user.email, item.id, new_status)
    flash('Заявку оновлено', 'success')
    return _back(item.id)


@admin_bp.route('/trainer-applications/<int:application_id>/create-trainer', methods=['POST'])
@permission_required('trainer_applications.manage')
@permission_required('trainers.manage')
def trainer_application_create_trainer(application_id):
    item = _get_or_404(application_id)
    if item.status != 'approved':
        flash('Створити тренера можна лише з погодженої заявки', 'error')
        return _back(item.id)
    try:
        trainer, warning = trainer_recruitment.create_trainer(item)
        db.session.commit()
    except trainer_recruitment.AlreadyConverted:
        db.session.rollback()
        flash('Із цієї заявки тренера вже створено', 'warning')
        return _back(item.id)
    except Exception:
        db.session.rollback()
        flash('Не вдалося створити тренера', 'error')
        return _back(item.id)
    audit_logger.info('Admin %s created trainer %s from TrainerApplication #%s',
                      current_user.email, trainer.id, item.id)
    if warning:
        flash(warning, 'warning')
    flash('Тренера створено неактивним: заповніть картку й увімкніть показ на сайті', 'success')
    return redirect(url_for('admin.trainer_edit', trainer_id=trainer.id))
```

Звірити: ім'я ендпоінта редагування тренера (`grep -n "def trainer_edit\|def edit_trainer" app/admin/routes_trainers.py`); чи `permission_required` можна ставити двічі, чи він приймає кілька прав (`sed -n 1,60p app/rbac/decorators.py`) -- використати той спосіб, що підтримується; `abort` імпортувати вгорі файлу, а не у функції.

`app/admin/routes.py` поряд із `routes_b2b_requests`:

```python
from app.admin import routes_trainer_applications  # noqa: F401
```

- [ ] **Step 4: Шаблони адмінки**

`app/templates/admin/trainer_applications.html` -- за зразком `admin/b2b_requests.html` (той самий каркас: `admin-with-sidebar`, `admin-hero`, `filter_bar`, `admin-table`, `empty_state`, `pager`), без `export_endpoint`:

```html
{% extends "admin/base_admin.html" %}

{% block title %}Кандидати в тренери | ІПРМ{% endblock %}
{% block extra_meta %}<meta name="robots" content="noindex, nofollow">{% endblock %}

{% block extra_css %}
<link rel="stylesheet" href="{{ url_for('static', filename='css/admin.css') }}?v={{ assets_version }}">
{% endblock %}

{% from 'admin/partials/_filter_bar.html' import filter_bar, pager, empty_state %}

{% block content %}
<div class="admin-with-sidebar">
  {% include 'admin/partials/_sidebar.html' %}
  <div class="admin-layout admin-layout--wide">

  <div class="admin-hero">
    <div>
      <div class="admin-breadcrumb">
        <a href="{{ url_for('admin.dashboard') }}" class="admin-breadcrumb__link">Панель</a>
        <span class="admin-breadcrumb__sep">/</span>
        <span class="admin-breadcrumb__current">Кандидати в тренери</span>
      </div>
      <h1 class="admin-hero__title">Кандидати в тренери</h1>
      <p class="admin-hero__subtitle">Анкети зі сторінки «Стати тренером». Нових: {{ new_count }}</p>
    </div>
    <div class="admin-hero__actions">
      <a href="{{ url_for('trainers.join') }}" class="btn-admin btn-admin--secondary" target="_blank" rel="noopener">{{ icon('open_in_new') }} Сторінка на сайті</a>
    </div>
  </div>

  {% include 'partials/flash_messages.html' %}

  {{ filter_bar(
       endpoint='admin.trainer_applications_list',
       values=filters,
       search={'name': 'q', 'placeholder': 'Пошук за ПІБ, email, телефоном, спеціальністю, темою'},
       fields=[
         {'name': 'status', 'label': 'Статус', 'placeholder': 'Усі статуси', 'options': status_options},
         {'name': 'date_from', 'label': 'Отримані з', 'type': 'date'},
         {'name': 'date_to', 'label': 'Отримані по', 'type': 'date'},
         {'name': 'per_page', 'label': 'Рядків на сторінці', 'placeholder': '50 (типово)', 'options': per_page_options, 'narrowing': False},
       ],
     ) }}

  {% if applications %}
  <div class="admin-table-wrap">
  <table class="admin-table">
    <thead>
      <tr>
        <th>Отримано</th>
        <th>Кандидат</th>
        <th>Спеціальність</th>
        <th>Контакти</th>
        <th>Статус</th>
      </tr>
    </thead>
    <tbody>
      {% for item in applications %}
      <tr>
        <td>{{ item.created_at | kyiv if item.created_at else '–' }}</td>
        <td><a href="{{ url_for('admin.trainer_application_detail', application_id=item.id) }}">{{ item.full_name }}</a></td>
        <td>{{ item.specialty }}</td>
        <td><a href="tel:{{ item.phone }}">{{ item.phone }}</a><br><a href="mailto:{{ item.email }}">{{ item.email }}</a></td>
        <td><span class="badge badge--{{ item.status_badge }}">{{ item.status_label }}</span>{% if item.trainer_id %} <span class="badge badge--active">тренер</span>{% endif %}</td>
      </tr>
      {% endfor %}
    </tbody>
  </table>
  </div>
  {% else %}
  {% call empty_state('admin.trainer_applications_list',
                      filter_args,
                      narrow_args={'page': pagination.page if pagination.page > 1 else none,
                                   'per_page': False},
                      icon_name='school',
                      title='Заявок поки немає') %}
    <p>Анкети зі сторінки «Стати тренером» з'являться тут</p>
  {% endcall %}
  {% endif %}

  {{ pager('admin.trainer_applications_list', pagination, filter_args) }}

  </div>
</div>
{% endblock %}
```

Звірити: чи `filter_bar` приймає відсутній `export_endpoint` (`sed -n 30,45p app/templates/admin/partials/_filter_bar.html`); формат фільтра `kyiv` (`grep -n "def kyiv_dt" -A5 -r app`).

`app/templates/admin/trainer_application_detail.html`:

```html
{% extends "admin/base_admin.html" %}

{% block title %}{{ application.full_name }} | Кандидати в тренери | ІПРМ{% endblock %}
{% block extra_meta %}<meta name="robots" content="noindex, nofollow">{% endblock %}

{% block extra_css %}
<link rel="stylesheet" href="{{ url_for('static', filename='css/admin.css') }}?v={{ assets_version }}">
{% endblock %}

{% block content %}
<div class="admin-with-sidebar">
  {% include 'admin/partials/_sidebar.html' %}
  <div class="admin-layout">
  <div class="admin-hero">
    <div>
      <div class="admin-breadcrumb">
        <a href="{{ url_for('admin.trainer_applications_list') }}" class="admin-breadcrumb__link">Кандидати в тренери</a>
        <span class="admin-breadcrumb__sep">/</span>
        <span class="admin-breadcrumb__current">{{ application.full_name }}</span>
      </div>
      <h1 class="admin-hero__title">{{ application.full_name }}</h1>
      <p class="admin-hero__subtitle">
        <span class="badge badge--{{ application.status_badge }}">{{ application.status_label }}</span>
        Отримано {{ application.created_at | kyiv }}{% if application.locale != 'uk' %} &middot; мова сторінки: {{ application.locale }}{% endif %}
      </p>
    </div>
    <div class="admin-hero__actions">
      {% if application.trainer %}
      <a href="{{ url_for('admin.trainer_edit', trainer_id=application.trainer_id) }}" class="btn-admin btn-admin--secondary">{{ icon('person') }} Картка тренера</a>
      {% elif application.status == 'approved' and can('trainer_applications.manage') and can('trainers.manage') %}
      <form method="POST" action="{{ url_for('admin.trainer_application_create_trainer', application_id=application.id) }}">
        <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
        <button type="submit" class="btn-admin btn-admin--primary">{{ icon('person_add') }} Створити тренера</button>
      </form>
      {% endif %}
    </div>
  </div>

  {% include 'partials/flash_messages.html' %}

  <div class="form-section">
    <h3 class="admin-form__section-title">Контакти</h3>
    <dl class="admin-dl">
      <dt>Телефон</dt><dd><a href="tel:{{ application.phone }}">{{ application.phone }}</a></dd>
      <dt>Email</dt><dd><a href="mailto:{{ application.email }}">{{ application.email }}</a></dd>
      {% if application.city %}<dt>Місто</dt><dd>{{ application.city }}</dd>{% endif %}
      <dt>Спеціальність</dt><dd>{{ application.specialty }}</dd>
      {% if application.workplace %}<dt>Місце роботи та посада</dt><dd>{{ application.workplace }}</dd>{% endif %}
      {% if application.social_links %}<dt>Соцмережі або сайт</dt><dd>{{ application.social_links }}</dd>{% endif %}
    </dl>
  </div>

  <div class="form-section">
    <h3 class="admin-form__section-title">Досвід у плазмотерапії</h3>
    <dl class="admin-dl">
      {% for label, value in application.answer_rows %}
      <dt>{{ label }}</dt><dd>{{ value or '–' }}</dd>
      {% endfor %}
    </dl>
  </div>

  <div class="form-section">
    <h3 class="admin-form__section-title">Що хоче викладати</h3>
    <p>{{ application.topic }}</p>
  </div>

  {% if can('trainer_applications.manage') %}
  <form method="POST" action="{{ url_for('admin.trainer_application_update', application_id=application.id) }}" class="admin-form">
    <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
    <div class="form-section">
      <h3 class="admin-form__section-title">Робота із заявкою</h3>
      <div class="admin-form__grid">
        <div class="form-group">
          <label for="status">Статус</label>
          <select name="status" id="status" class="form-input">
            {% for code, label in status_options %}
            <option value="{{ code }}"{% if application.status == code %} selected{% endif %}>{{ label }}</option>
            {% endfor %}
          </select>
        </div>
        <div class="form-group admin-form__full">
          <label for="admin_notes">Нотатки</label>
          <textarea name="admin_notes" id="admin_notes" class="form-input" rows="4" maxlength="4000">{{ application.admin_notes or '' }}</textarea>
        </div>
      </div>
    </div>
    <div class="admin-form__actions">
      <button type="submit" class="btn-admin btn-admin--primary">{{ icon('check') }} Зберегти</button>
    </div>
  </form>
  {% endif %}
  </div>
</div>
{% endblock %}
```

Звірити наявність `.admin-dl` (`grep -n "\.admin-dl\b" app/static/css/admin.css`). Якщо немає -- узяти наявний компонент списку «підпис -- значення» з адмінки (наприклад той, що в `admin/meta_lead_detail.html`: `grep -n "<dl" app/templates/admin/*.html | head`), а не створювати новий.

- [ ] **Step 5: Сайдбар**

`app/templates/admin/partials/_sidebar.html`: умову групи (рядок ~67) розширити `'trainer_applications.view'`, а після пункту B2B (рядок ~76-80) додати:

```html
      {% if can('trainer_applications.view') %}
      <a href="{{ url_for('admin.trainer_applications_list') }}" class="admin-sidebar__link{% if ep in ('admin.trainer_applications_list', 'admin.trainer_application_detail') %} admin-sidebar__link--active{% endif %}">
        {{ icon('school') }} Кандидати в тренери
      </a>
      {% endif %}
```

(розмітку пункту скопіювати з сусіднього B2B -- іконка/клас мають збігатися з тим, як оформлені сусіди).

- [ ] **Step 6: Прев'ю листа**

`app/admin/routes_notifications.py`: поряд із `MockB2BRequest` (~рядок 358) створити мок і поряд із записом `'b2b-request'` (~рядок 550) -- запис прев'ю:

```python
    class MockTrainerApplication:
        id = 1
        full_name = 'Петренко Олена Іванівна'
        phone = '+380671112233'
        email = 'olena@example.com'
        city = 'Львів'
        specialty = 'Гінекологія'
        workplace = 'Клініка «Здоров\'я», лікар-гінеколог'
        social_links = 'https://instagram.com/dr.olena'
        topic = 'PRP у гінекології: показання й протоколи'
        answer_rows = [
            ('Як давно ви використовуєте PRP- та плазмотерапію?', 'Понад 5 років'),
            ('Скільки пробірок (процедур) у середньому за день?', '6-10'),
            ('Чи є досвід виступів або викладання?', 'Конференції'),
        ]
```

```python
        {
            'key': 'trainer-application',
            'label': 'Кандидат у тренери: команді',
            'template_name': 'trainer_application_notification.html',
            'subject': 'Нова заявка кандидата в тренери',
            'html': render_template('emails/trainer_application_notification.html',
                                    application=MockTrainerApplication(),
                                    admin_url=mock_admin_url),
        },
```

(ключі словника звірити із сусіднім записом `'b2b-request'` -- скопіювати точний набір).

Тест `test_email_preview_lists_trainer_application` перевіряє текст `'Заявка кандидата в тренери'` -- він приходить із `EVENT_TYPES` на сторінці одержувачів або з label прев'ю. Якщо сторінка прев'ю показує лише `label` (`'Кандидат у тренери: команді'`), виправити очікування тесту на нього.

- [ ] **Step 7: Тести проходять**

Run: `venv/Scripts/python.exe -m pytest tests/test_routes/test_admin_trainer_applications.py tests/test_rbac -q -p no:cacheprovider`
Expected: passed. RBAC-сторожі можуть вимагати опис модуля в матриці -- виправити за їхнім повідомленням.

- [ ] **Step 8: Коміт**

Файли: `app/rbac/registry.py app/admin/routes_trainer_applications.py app/admin/routes.py app/templates/admin/trainer_applications.html app/templates/admin/trainer_application_detail.html app/templates/admin/partials/_sidebar.html app/admin/routes_notifications.py tests/test_routes/test_admin_trainer_applications.py`. Повідомлення: `feat(trainer-recruit): адмінка заявок кандидатів -- реєстр, картка, створення тренера`.

---

### Task 5: Тексти запрошення в «Налаштуваннях для тренерів»

**Files:**
- Modify: `app/admin/forms.py` (`TrainerSettingsForm`, ~рядок 1352)
- Modify: `app/admin/routes_trainer_cabinet.py` (`settings_trainers`, ~рядок 144-182)
- Modify: `app/templates/admin/settings_trainers.html` (нова секція перед «Часті питання»)
- Test: `tests/test_routes/test_admin_recruit_texts.py`

**Interfaces:**
- Consumes: `DEFAULTS` (Task 2), колонки `recruit_*` (Task 1).
- Produces: поля форми `recruit_teaser_title`, `recruit_teaser_text`, `recruit_page_title`, `recruit_page_intro`, `recruit_page_benefits`, `recruit_page_closing`.

- [ ] **Step 1: Тести (падають)**

`tests/test_routes/test_admin_recruit_texts.py`:

```python
"""Тексти запрошення тренерів редагуються в «Налаштуваннях для тренерів»."""
import pytest

from app.data.trainer_recruit import DEFAULTS
from app.extensions import db
from app.models.site_settings import SiteSettings
from tests.support.rbac import make_super_admin, switch_user

FIELDS = list(DEFAULTS)


@pytest.fixture(autouse=True)
def _no_csrf(app):
    prev = app.config.get('WTF_CSRF_ENABLED')
    app.config['WTF_CSRF_ENABLED'] = False
    yield
    app.config['WTF_CSRF_ENABLED'] = prev


@pytest.fixture
def admin(client):
    user = make_super_admin()
    db.session.commit()
    switch_user(client, user)
    return user


def _post(client, **overrides):
    data = {'faq_html': '', 'contract_email': ''}
    data.update({name: DEFAULTS[name] for name in FIELDS})
    data.update(overrides)
    return client.post('/admin/settings/trainers', data=data)


def test_form_prefilled_with_defaults(client, admin):
    html = client.get('/admin/settings/trainers').get_data(as_text=True)
    assert 'Ваш досвід може стати цінним для інших' in html
    assert 'name="recruit_page_benefits"' in html


def test_unchanged_default_is_stored_empty(client, admin):
    assert _post(client).status_code == 302
    settings = SiteSettings.get()
    assert all(getattr(settings, name) == '' for name in FIELDS)


def test_custom_text_is_stored_and_shown_on_page(client, admin):
    _post(client, recruit_page_title='Станьте голосом плазмотерапії')
    assert SiteSettings.get().recruit_page_title == 'Станьте голосом плазмотерапії'
    html = client.get('/trainers/join').get_data(as_text=True)
    assert 'Станьте голосом плазмотерапії' in html


def test_windows_line_endings_match_default(client, admin):
    _post(client, recruit_page_intro=DEFAULTS['recruit_page_intro'].replace('\n', '\r\n'))
    assert SiteSettings.get().recruit_page_intro == ''
```

Run: `venv/Scripts/python.exe -m pytest tests/test_routes/test_admin_recruit_texts.py -q -p no:cacheprovider`
Expected: FAIL.

- [ ] **Step 2: Поля форми**

`app/admin/forms.py`, у `TrainerSettingsForm` перед `faq_html`:

```python
    recruit_teaser_title = TextAreaField(
        'Заклик: заголовок', validators=[Optional(), Length(max=300)],
        description='Смуга під тренерами на головній і в /trainers. Порожнє -- текст за замовчуванням.',
    )
    recruit_teaser_text = TextAreaField(
        'Заклик: рядок під заголовком', validators=[Optional(), Length(max=500)],
    )
    recruit_page_title = TextAreaField(
        'Сторінка «Стати тренером»: заголовок', validators=[Optional(), Length(max=300)],
    )
    recruit_page_intro = TextAreaField(
        'Сторінка: вступ', validators=[Optional(), Length(max=4000)],
        description='Простий текст. Абзац -- через порожній рядок.',
    )
    recruit_page_benefits = TextAreaField(
        'Сторінка: переваги', validators=[Optional(), Length(max=2000)],
        description='По одній на рядок -- кожна стає карткою.',
    )
    recruit_page_closing = TextAreaField(
        'Сторінка: закриття', validators=[Optional(), Length(max=2000)],
    )
```

(`Length` уже імпортований у файлі -- перевірити `grep -n "^from wtforms.validators" app/admin/forms.py`.)

- [ ] **Step 3: Маршрут**

`app/admin/routes_trainer_cabinet.py`, у `settings_trainers`:

на GET (після `form.contract_email.data = ...`):

```python
        from app.data.trainer_recruit import DEFAULTS as RECRUIT_DEFAULTS
        for name, default in RECRUIT_DEFAULTS.items():
            getattr(form, name).data = getattr(site, name) or default
```

на POST (поряд із збереженням `faq`):

```python
        # Той самий прийом, що з FAQ: незмінений дефолт зберігаємо порожнім,
        # щоб правка дефолту в коді (і його переклади в .po) доходили до сайту.
        from app.data.trainer_recruit import DEFAULTS as RECRUIT_DEFAULTS
        for name, default in RECRUIT_DEFAULTS.items():
            value = (getattr(form, name).data or '').strip().replace('\r\n', '\n').replace('\r', '\n')
            setattr(site, name, '' if value == default.strip() else value)
```

Імпорт `DEFAULTS` -- угорі файлу, а не у функції (поряд з іншими `from app.data...`; перевірити, чи там уже є `from app.data.trainer_faq import ...` на рівні модуля -- у коді вище він усередині функції, тож лишити в тому самому стилі, що сусід).

- [ ] **Step 4: Секція в шаблоні**

`app/templates/admin/settings_trainers.html`, перед `<div class="form-section" id="faq">`:

```html
    <div class="form-section" id="recruit">
      <h3 class="admin-form__section-title">Запрошення тренерів</h3>
      <p class="admin-form__section-hint">
        Заклик на головній і в <a href="{{ url_for('trainers.trainer_list') }}" target="_blank" rel="noopener">/trainers</a>,
        сторінка <a href="{{ url_for('trainers.join') }}" target="_blank" rel="noopener">«Стати тренером»</a>.
        Переклади ru/en -- кнопка «Переклади» в <a href="{{ url_for('admin.settings') }}">налаштуваннях сайту</a>
        (з'являються, коли текст змінено тут).
      </p>
      <div class="admin-form__grid">
        {% for name in ['recruit_teaser_title', 'recruit_teaser_text', 'recruit_page_title', 'recruit_page_intro', 'recruit_page_benefits', 'recruit_page_closing'] %}
        {% set field = form[name] %}
        <div class="form-group admin-form__full">
          <label for="{{ name }}">{{ field.label.text }}</label>
          {{ field(class="form-input" + (" is-invalid" if field.errors else ""), id=name, rows=2 if name in ('recruit_teaser_title', 'recruit_teaser_text', 'recruit_page_title') else 7) }}
          {% if field.description %}<small class="form-hint">{{ field.description }}</small>{% endif %}
          {% for error in field.errors %}<div class="form-error">{{ error }}</div>{% endfor %}
        </div>
        {% endfor %}
      </div>
    </div>
```

Підзаголовок hero змінити на `Запрошення тренерів, договір і часті питання в кабінеті тренера`.

- [ ] **Step 5: Переклади на сторінці «Переклади»**

Перевірити, що нові поля видно в `/admin/translations/site_settings/1` після зміни тексту: `grep -n "FIELD_LABELS" -A40 app/services/translation_registry.py | grep -n "company_name"` -- якщо підписи полів задано словником, дописати:

```python
    'recruit_teaser_title': 'Заклик тренерів: заголовок',
    'recruit_teaser_text': 'Заклик тренерів: рядок',
    'recruit_page_title': '«Стати тренером»: заголовок',
    'recruit_page_intro': '«Стати тренером»: вступ',
    'recruit_page_benefits': '«Стати тренером»: переваги',
    'recruit_page_closing': '«Стати тренером»: закриття',
```

і тест у `tests/test_routes/test_admin_recruit_texts.py`:

```python
def test_translation_of_custom_text_reaches_english_page(client, admin):
    from tests.support.rbac import switch_user  # noqa: F401
    _post(client, recruit_page_title='Станьте голосом плазмотерапії')
    settings = SiteSettings.get()
    settings.set_translation('en', 'recruit_page_title', 'Become the voice of plasma therapy')
    db.session.commit()
    from flask_babel import refresh
    html = client.get('/en/trainers/join').get_data(as_text=True)
    assert 'Become the voice of plasma therapy' in html
```

(сигнатуру `set_translation` звірити: `grep -n "def set_translation" -A6 app/models/mixins.py`; кеш локалі між запитами скидає фікстура `get_localized` із `tests/test_i18n/conftest.py` -- якщо тест бачить укр. текст, перенести його в `tests/test_i18n/` і вжити `get_localized`).

- [ ] **Step 6: Тести проходять**

Run: `venv/Scripts/python.exe -m pytest tests/test_routes/test_admin_recruit_texts.py tests/test_routes -k "settings_trainers or trainer_settings or recruit" -q -p no:cacheprovider`
Expected: passed.

- [ ] **Step 7: Коміт**

Файли: `app/admin/forms.py app/admin/routes_trainer_cabinet.py app/templates/admin/settings_trainers.html app/services/translation_registry.py tests/test_routes/test_admin_recruit_texts.py`. Повідомлення: `feat(trainer-recruit): тексти запрошення редагуються в налаштуваннях для тренерів`.

---

### Task 6: Документація і фінальна перевірка

**Files:**
- Modify: `README.md` (розділ про тренерів/кабінет -- знайти `grep -n "кабінет тренера\|Кабінет тренера" README.md | head`)

- [ ] **Step 1: README**

Додати підрозділ «Залучення тренерів» поряд із розділом про кабінет тренера:

```markdown
### Залучення тренерів

* Заклик «стати тренером» -- `partials/_recruit_cta.html` (головна, секція тренерів; `/trainers`).
* Сторінка `/trainers/join` (`trainers.join`): текст запрошення й анкета кандидата. Захист: honeypot `website`, reCAPTCHA, `5 per hour; 20 per day`.
* Питання про плазму -- `app/data/trainer_application_questions.py`. Заміна переліку -- правка файлу без міграції; заявка зберігає снапшот підпису (`TrainerApplication.answers`).
* Тексти -- «Налаштування -> Для тренерів», розділ «Запрошення тренерів». Порожнє поле = дефолт із `app/data/trainer_recruit.py` (перекладається каталогом `.po`); змінений текст перекладається на сторінці «Переклади» налаштувань сайту.
* Заявки -- `/admin/trainer-applications` (право `trainer_applications.view` / `.manage`). «Створити тренера» на погодженій заявці заводить неактивну картку тренера й анкету; підтверджений акаунт із тим самим email прив'язується.
* Лист -- тип події `trainer_application`; одержувачі на `/admin/notifications/recipients`. Міграція `trainer_recruit_20261009` кладе туди email сайту (адреси Дмитра Бараша в репозиторії немає) -- замініть на його адресу.
```

- [ ] **Step 2: Повний прогін**

Run: `venv/Scripts/python.exe -m pytest tests -q -p no:cacheprovider > "$TEMP/full.txt" 2>&1; tail -3 "$TEMP/full.txt"`
Expected: рядок підсумку `N passed` без `failed`/`error`.

Також: `venv/Scripts/python.exe tools/ds/ds_audit.py` (exit 0), `venv/Scripts/flask.exe db heads` (одна голова), `python -c "from app import create_app; create_app('testing')"`.

- [ ] **Step 3: Коміт**

`README.md`. Повідомлення: `docs: залучення тренерів у README`.

- [ ] **Step 4: Що передати користувачу після деплою**

* вписати email Дмитра Бараша в правило «Заявка кандидата в тренери» на `/admin/notifications/recipients` (зараз там email сайту) і надіслати тестовий лист кнопкою «Тест»;
* видати права `trainer_applications.*` ролям у матриці `/admin/access` (наявним ролям `flask rbac sync` прав не додає);
* коли Альона надішле короткий текст -- вписати його в «Налаштування -> Для тренерів»;
* коли Дмитро надішле питання -- замінити перелік у `app/data/trainer_application_questions.py` (+ переклади в `.po`).
