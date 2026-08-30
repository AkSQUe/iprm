# Захід і людські підписи в події `lead.created` — план реалізації (ІПРМ)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** менеджер MM Medic, який бере трубку по заявці з реклами, бачить питання й відповіді так, як їх бачила людина, і знає, який саме захід їй пропонувати.

**Architecture:** форма Meta отримує необов'язкове посилання на захід, і подія `lead.created` починає везти партнеру два нові ключі — `answers` (пари питання/відповідь із людськими підписами зі схеми форми) і `offer` (захід). Наявні поля payload не змінюються, тому приймач старої версії нічого не помічає.

**Tech Stack:** Flask, SQLAlchemy, Alembic, Jinja2, Click, pytest.

**Spec:** `docs/superpowers/specs/2026-08-30-iprm-leads-in-mm-medic-work-plan-design.md`

## Global Constraints

- Мова коментарів і докстрінгів — українська, як у решті `app/services/`.
- Жодних емодзі в коді; жодного inline-CSS і inline-JS (`CLAUDE.md`).
- Стилі — з дизайн-системи; сторінкові файли звуться `page-*.css` і містять лише layout.
- Міграція чіпляється за голову `meta_form_schema_20260830`.
- `custom_fields` у payload НЕ змінюється: приймач старої версії має працювати без правок.
- Деплой цієї роботи йде ПІСЛЯ деплою MM Medic (див. спеку, розділ «Порядок деплою»).

**Передумова:** робота «підписи питань Meta-форми» (`docs/superpowers/plans/2026-08-30-meta-form-question-labels.md`) має бути в `main` і на проді. Звідси беруться таблиця `meta_lead_forms` і `meta_form_schema.answers_for`.

## File Structure

| Файл | Відповідальність |
|---|---|
| `app/models/meta_lead.py` (змінити) | `MetaLeadForm.course_instance_id` — яка форма про який захід |
| `migrations/versions/meta_form_offer_20260831.py` (створити) | Колонка + FK |
| `app/admin/routes_meta_leads.py` (змінити) | Сторінка форм: список, прив'язка, кнопка синхронізації |
| `app/templates/admin/meta_lead_forms.html` (створити) | Верстка сторінки |
| `app/services/partner_events.py` (змінити) | `answers` і `offer` у payload |
| `app/cli.py` (змінити) | `meta-reemit-leads` — бекфіл уже надісланих заявок |

---

### Task 1: Форма знає свій захід

**Files:**
- Modify: `app/models/meta_lead.py` (клас `MetaLeadForm`)
- Create: `migrations/versions/meta_form_offer_20260831.py`
- Test: `tests/test_models/test_meta_lead_form_offer.py`

**Interfaces:**
- Produces: `MetaLeadForm.course_instance_id` (nullable BigInteger FK на `course_instances.id`, `ondelete='SET NULL'`) і relationship `MetaLeadForm.course_instance`.

- [ ] **Step 1: Write the failing test**

```python
"""Прив'язка Meta-форми до заходу ІПРМ.

Прив'язка саме до ФОРМИ, а не до кампанії: людина заповнювала форму, і одна
кампанія цілком веде дві форми на різні заходи.

Найдорожча межа тут -- видалення заходу. Знести разом із ним схему форми
означало б втратити підписи питань для ВСІХ уже наявних заявок, і картка
ліда знову показувала б внутрішні ключі Meta.
"""
from datetime import datetime, timedelta, timezone

import pytest

from app.extensions import db
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.meta_lead import MetaLeadForm


def _instance():
    course = Course(title='Плазмотерапія: базовий курс', slug=f'pl-{id(object())}')
    db.session.add(course)
    db.session.flush()
    instance = CourseInstance(
        course_id=course.id,
        start_date=datetime.now(timezone.utc) + timedelta(days=14),
        status='published',
    )
    db.session.add(instance)
    db.session.flush()
    return instance


def test_form_can_point_at_an_event(app):
    instance = _instance()
    form = MetaLeadForm(form_id='900', questions={},
                        course_instance_id=instance.id)
    db.session.add(form)
    db.session.commit()

    assert form.course_instance.id == instance.id


def test_form_without_an_event_is_valid(app):
    """Форма може бути не про конкретний захід -- прив'язка необов'язкова."""
    form = MetaLeadForm(form_id='901', questions={})
    db.session.add(form)
    db.session.commit()

    assert form.course_instance_id is None


def test_deleting_the_event_keeps_the_schema(app):
    """Схема переживає видалення заходу: без неї підписи питань зникли б."""
    instance = _instance()
    form = MetaLeadForm(form_id='902', questions={'q': {'label': 'Питання'}},
                        course_instance_id=instance.id)
    db.session.add(form)
    db.session.commit()

    db.session.delete(instance)
    db.session.commit()

    fresh = MetaLeadForm.query.filter_by(form_id='902').one()
    assert fresh.course_instance_id is None
    assert fresh.questions == {'q': {'label': 'Питання'}}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_models/test_meta_lead_form_offer.py -v`
Expected: FAIL — `TypeError: 'course_instance_id' is an invalid keyword argument for MetaLeadForm`

- [ ] **Step 3: Add the column**

У `app/models/meta_lead.py`, у клас `MetaLeadForm`, після `locale`:

```python
    # Захід, про який ця форма. Прив'язка руками в адмінці: Meta про наші
    # курси не знає нічого, а вгадувати захід із назви форми означало б
    # мовчки помилятись на другому потоці того самого курсу.
    #
    # SET NULL, а не CASCADE: видалення заходу не має забирати з собою
    # схему форми -- на ній тримаються підписи питань УСІХ уже наявних
    # заявок, і картка ліда без неї знову показувала б внутрішні ключі.
    course_instance_id = db.Column(
        db.BigInteger,
        db.ForeignKey('course_instances.id', ondelete='SET NULL'),
        index=True,
    )

    course_instance = db.relationship('CourseInstance')
```

- [ ] **Step 4: Write the migration**

```python
"""Meta-форма знає, про який захід вона.

Партнерська подія `lead.created` має нести менеджеру MM Medic не лише
відповіді людини, а й те, що саме їй пропонувати. Meta про наші курси не
знає нічого, тож зв'язок ставиться руками в адмінці.

SET NULL, а не CASCADE: видалення заходу не має забирати з собою схему
форми. На ній тримаються підписи питань усіх уже наявних заявок, і без неї
картка ліда знову показувала б внутрішні ключі Meta.

Revision ID: meta_form_offer_20260831
Revises: meta_form_schema_20260830
"""
import sqlalchemy as sa
from alembic import op

revision = 'meta_form_offer_20260831'
down_revision = 'meta_form_schema_20260830'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'meta_lead_forms',
        sa.Column('course_instance_id', sa.BigInteger(), nullable=True),
    )
    op.create_foreign_key(
        'fk_meta_lead_forms_course_instance', 'meta_lead_forms',
        'course_instances', ['course_instance_id'], ['id'], ondelete='SET NULL',
    )
    op.create_index('ix_meta_lead_forms_course_instance_id', 'meta_lead_forms',
                    ['course_instance_id'])


def downgrade():
    op.drop_index('ix_meta_lead_forms_course_instance_id',
                  table_name='meta_lead_forms')
    op.drop_constraint('fk_meta_lead_forms_course_instance', 'meta_lead_forms',
                       type_='foreignkey')
    op.drop_column('meta_lead_forms', 'course_instance_id')
```

- [ ] **Step 5: Run tests**

Run: `pytest tests/test_models/test_meta_lead_form_offer.py -v`
Expected: PASS (3 tests)

- [ ] **Step 6: Check the migration reverses**

Run: `python -m flask db upgrade && python -m flask db downgrade -1 && python -m flask db upgrade`
Expected: три успішні прогони.

- [ ] **Step 7: Commit**

```bash
git add app/models/meta_lead.py migrations/versions/meta_form_offer_20260831.py tests/test_models/test_meta_lead_form_offer.py
git commit -m "feat(meta): форма знає, про який захід вона"
```

---

### Task 2: Сторінка форм у адмінці

**Files:**
- Modify: `app/admin/routes_meta_leads.py`
- Create: `app/templates/admin/meta_lead_forms.html`
- Modify: `app/templates/admin/meta_leads_settings.html` (прибрати звідти кнопку синхронізації)
- Modify: `app/templates/admin/partials/_sidebar.html` (посилання на сторінку)
- Test: `tests/test_routes/test_meta_forms_admin.py`

**Interfaces:**
- Consumes: `MetaLeadForm.course_instance_id` (Task 1), `meta_form_schema.sync_page_forms`.
- Produces: роути `admin.meta_lead_forms` (`GET /admin/meta-leads/forms`) і `admin.meta_lead_form_offer` (`POST /admin/meta-leads/forms/<int:form_row_id>/offer`).

- [ ] **Step 1: Write the failing test**

```python
"""Сторінка Meta-форм: що показує і що дозволяє змінити.

Сторінка існує заради однієї дії -- сказати системі, про який захід кожна
форма. Усе інше на ній довідкове.

Межа, яку легко зламати: випадайка мусить показувати ВЖЕ ПРИВ'ЯЗАНИЙ захід
навіть тоді, коли він минув. Інакше відкриття сторінки мовчки показувало б
«не обрано» там, де прив'язка є, і перше ж збереження її б стерло.
"""
from datetime import datetime, timedelta, timezone

import pytest

from app.extensions import db
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.meta_lead import MetaLeadForm


def _instance(days, status='published'):
    course = Course(title=f'Курс {days}', slug=f'c{days}-{uuid4().hex[:6]}')
    db.session.add(course)
    db.session.flush()
    instance = CourseInstance(
        course_id=course.id, status=status,
        start_date=datetime.now(timezone.utc) + timedelta(days=days),
    )
    db.session.add(instance)
    db.session.flush()
    return instance


def test_page_lists_synced_forms(client, admin):
    _login(client, admin)
    db.session.add(MetaLeadForm(form_id='900', name='Плазмотерапія',
                                questions={'q': {'label': 'Питання'}}))
    db.session.flush()

    page = client.get('/admin/meta-leads/forms')

    assert page.status_code == 200
    assert 'Плазмотерапія'.encode() in page.data


def test_offer_can_be_attached(client, admin):
    _login(client, admin)
    form = MetaLeadForm(form_id='901', questions={})
    db.session.add(form)
    db.session.flush()
    instance = _instance(14)

    client.post(f'/admin/meta-leads/forms/{form.id}/offer',
                data={'course_instance_id': str(instance.id)},
                follow_redirects=True)

    assert MetaLeadForm.query.get(form.id).course_instance_id == instance.id


def test_offer_can_be_detached(client, admin):
    _login(client, admin)
    instance = _instance(14)
    form = MetaLeadForm(form_id='902', questions={},
                        course_instance_id=instance.id)
    db.session.add(form)
    db.session.flush()

    client.post(f'/admin/meta-leads/forms/{form.id}/offer',
                data={'course_instance_id': ''},
                follow_redirects=True)

    assert MetaLeadForm.query.get(form.id).course_instance_id is None


def test_past_event_stays_visible_when_attached(client, admin):
    """Минулий, але прив'язаний захід має лишатись у списку варіантів."""
    _login(client, admin)
    past = _instance(-30)
    form = MetaLeadForm(form_id='903', questions={},
                        course_instance_id=past.id)
    db.session.add(form)
    db.session.flush()

    body = client.get('/admin/meta-leads/forms').data.decode()

    assert f'value="{past.id}" selected' in body


def test_page_requires_admin(client, plain_user):
    _login(client, plain_user)

    assert client.get('/admin/meta-leads/forms').status_code in (302, 403, 404)
```

Хелпери й фікстури для цього файлу — додати вгорі. `csrf_token` у POST не передається: `TestingConfig` вимикає `WTF_CSRF_ENABLED` (`config.py:186`).

```python
from uuid import uuid4

from app.models.user import User


def _uid():
    return uuid4().hex[:8]


def _login(client, user):
    with client.session_transaction() as session:
        session['_user_id'] = str(user.id)


@pytest.fixture
def admin(app):
    user = User.create_with_password(
        f'mf-adm-{_uid()}@test.com', 'password123',
        first_name='М', last_name='Адмін', is_admin=True, email_confirmed=True,
    )
    db.session.flush()
    return user


@pytest.fixture
def plain_user(app):
    user = User.create_with_password(
        f'mf-usr-{_uid()}@test.com', 'password123',
        first_name='Б', last_name='Юзер', email_confirmed=True,
    )
    db.session.flush()
    return user
```

Прибирання за собою: користувачі комітяться роутами адмінки, тож у цьому файлі потрібна та сама автоприбиральна фікстура, що в `tests/test_routes/test_meta_admin.py` (`cleanup`) -- інакше падатиме не цей тест, а сусідній.

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_routes/test_meta_forms_admin.py -v`
Expected: FAIL — 404, роуту немає.

- [ ] **Step 3: Add the routes**

У `app/admin/routes_meta_leads.py`, у розділ картки лідів:

```python
def _offer_choices(current_id=None):
    """Заходи для випадайки прив'язки.

    Опубліковані й майбутні -- бо саме на них ведуть кампанії. Плюс уже
    прив'язаний захід, навіть якщо він минув: без нього сторінка мовчки
    показувала б «не обрано» там, де прив'язка є, і перше ж збереження
    форми її б стерло.
    """
    from app.models.course_instance import CourseInstance

    query = CourseInstance.query.filter(
        CourseInstance.status == 'published',
        CourseInstance.start_date >= utcnow(),
    )
    instances = query.order_by(CourseInstance.start_date.asc()).limit(100).all()

    if current_id and all(i.id != current_id for i in instances):
        current = db.session.get(CourseInstance, current_id)
        if current is not None:
            instances = [current] + instances
    return instances


@admin_bp.route('/meta-leads/forms')
@admin_required
def meta_lead_forms():
    """Схеми Meta-форм і прив'язка кожної до заходу.

    Сторінка існує заради однієї дії. Підписи питань система забирає сама,
    а от про який захід форма -- знає лише людина: Meta про наші курси не
    знає нічого, і вгадати захід із назви форми означало б мовчки
    помилятись на другому потоці того самого курсу.
    """
    forms = MetaLeadForm.query.order_by(
        MetaLeadForm.status.asc(), MetaLeadForm.name.asc()).all()
    return render_template(
        'admin/meta_lead_forms.html',
        forms=forms,
        offer_choices={f.id: _offer_choices(f.course_instance_id) for f in forms},
    )


@admin_bp.route('/meta-leads/forms/<int:form_row_id>/offer', methods=['POST'])
@admin_required
def meta_lead_form_offer(form_row_id):
    """Прив'язати форму до заходу або зняти прив'язку."""
    form = db.session.get(MetaLeadForm, form_row_id)
    if form is None:
        flash('Форму не знайдено', 'error')
        return redirect(url_for('admin.meta_lead_forms'))

    raw = (request.form.get('course_instance_id') or '').strip()
    form.course_instance_id = int(raw) if raw.isdigit() else None

    if try_commit(log_context=f'meta_lead_form_offer id={form_row_id}'):
        audit_logger.info('Admin %s linked meta form %s to instance %s',
                          current_user.email, form.form_id,
                          form.course_instance_id)
        flash('Прив\'язку збережено', 'success')
    return redirect(url_for('admin.meta_lead_forms'))
```

Додати імпорт `MetaLeadForm` у наявний рядок імпорту моделей.

- [ ] **Step 4: Move the sync button and add the template**

Створити `app/templates/admin/meta_lead_forms.html` за зразком `admin/meta_leads_settings.html` (та сама структура `admin-with-sidebar` / `admin-layout` / `admin-hero`), з таблицею форм: назва, `form_id`, стан, кількість питань, коли синхронізували, і формою прив'язки на кожному рядку:

```html
<form method="POST" action="{{ url_for('admin.meta_lead_form_offer', form_row_id=form.id) }}">
  <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
  <select name="course_instance_id" class="form-input">
    <option value="">{{ '– не прив\'язано –' }}</option>
    {% for instance in offer_choices[form.id] %}
    <option value="{{ instance.id }}"
            {% if instance.id == form.course_instance_id %}selected{% endif %}>
      {{ instance.course.title }} — {{ instance.start_date.strftime('%d.%m.%Y') }}
    </option>
    {% endfor %}
  </select>
  <button type="submit" class="btn-admin btn-admin--sm">Зберегти</button>
</form>
```

Кнопку «Оновити підписи форм» перенести сюди з `meta_leads_settings.html` (сам роут `admin.meta_leads_sync_forms` не змінюється), лишивши в налаштуваннях посилання на нову сторінку. Додати пункт у `_sidebar.html` поряд із «Ліди Meta».

Нових класів не вводити: таблиця, кнопки й поля беруться з дизайн-системи. Якщо знадобиться layout — тільки `page-*.css`.

- [ ] **Step 5: Run tests**

Run: `pytest tests/test_routes/test_meta_forms_admin.py tests/test_routes/test_meta_admin.py -v`
Expected: PASS

- [ ] **Step 6: Check the design system did not drift**

Run: `pytest tests/test_design_system/ -q && python tools/ds/ds_audit.py`
Expected: сторожі зелені; аудит без нових розбіжностей.

- [ ] **Step 7: Commit**

```bash
git add app/admin/routes_meta_leads.py app/templates/admin/meta_lead_forms.html app/templates/admin/meta_leads_settings.html app/templates/admin/partials/_sidebar.html tests/test_routes/test_meta_forms_admin.py
git commit -m "feat(admin): сторінка Meta-форм із прив'язкою до заходу"
```

---

### Task 3: Подія `lead.created` везе підписи й захід

**Files:**
- Modify: `app/services/partner_events.py` (`_lead_payload`)
- Test: `tests/test_services/test_partner_lead_payload.py`

**Interfaces:**
- Consumes: `meta_form_schema.answers_for` (робота з підписами), `MetaLeadForm.course_instance` (Task 1).
- Produces: у payload з'являються `answers: list[{'question': str, 'answer': str}]` і `offer: dict | None` із ключами `course_instance_id`, `title`, `starts_at`, `city`, `price`, `url`.

- [ ] **Step 1: Write the failing test**

```python
"""Що саме ІПРМ розповідає партнеру про заявку з реклами.

Два нові ключі й одна обіцянка сумісності.

`answers` -- пари питання/відповідь із ЛЮДСЬКИМИ підписами. У `field_data`
Meta кладе внутрішні ключі варіантів (`ортопедія_/_травматологія`), і
віддавати їх менеджеру означало б показати те, чого людина у формі не
бачила.

`custom_fields` при цьому лишається ДОСЛІВНИМ. Порядок деплою -- MM Medic
першим, і кілька днів він працює саме на цьому ключі; змінити його
означало б зламати робочу інтеграцію заради косметики.
"""
from datetime import datetime, timedelta, timezone

import pytest

from app.extensions import db
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.meta_lead import MetaLead, MetaLeadForm
from app.services import meta_form_schema, partner_events
from tests.support.fake_meta_graph import make_form


def _lead(**over):
    params = {
        'leadgen_id': f'lg-{id(object())}',
        'created_time': datetime.now(timezone.utc),
        'form_id': '9988776655',
        'field_data': {'ваша_спеціальність?': 'ортопедія_/_травматологія'},
    }
    params.update(over)
    lead = MetaLead(**params)
    db.session.add(lead)
    db.session.flush()
    return lead


def test_answers_carry_human_labels(app):
    meta_form_schema.save_form(make_form('9988776655'))
    db.session.flush()

    payload = partner_events._lead_payload(_lead())

    assert payload['answers'] == [
        {'question': 'Ваша спеціальність?',
         'answer': 'Ортопедія / травматологія'},
    ]


def test_custom_fields_stay_verbatim(app):
    """Обіцянка сумісності: старий приймач не має помітити змін."""
    meta_form_schema.save_form(make_form('9988776655'))
    db.session.flush()

    payload = partner_events._lead_payload(_lead())

    assert payload['custom_fields'] == {
        'ваша_спеціальність?': 'ортопедія_/_травматологія',
    }


def test_offer_is_built_from_the_linked_event(app):
    course = Course(title='Плазмотерапія: базовий курс', slug='pl-base')
    db.session.add(course)
    db.session.flush()
    instance = CourseInstance(
        course_id=course.id, status='published', price=4500,
        start_date=datetime.now(timezone.utc) + timedelta(days=13),
        location='Харків',
    )
    db.session.add(instance)
    db.session.flush()
    form = meta_form_schema.save_form(make_form('9988776655'))
    form.course_instance_id = instance.id
    db.session.flush()

    offer = partner_events._lead_payload(_lead())['offer']

    assert offer['course_instance_id'] == instance.id
    assert offer['title'] == 'Плазмотерапія: базовий курс'
    assert offer['price'] == '4500.00'
    assert offer['url'].startswith('http')


def test_offer_is_none_without_a_link(app):
    """Форму не прив'язали -- підказки немає, решта payload ціла."""
    meta_form_schema.save_form(make_form('9988776655'))
    db.session.flush()

    payload = partner_events._lead_payload(_lead())

    assert payload['offer'] is None
    assert payload['email'] is None or 'email' in payload


def test_lead_of_an_unknown_form_still_builds(app):
    """Схеми немає взагалі -- подія мусить піти, хай і з машинними підписами."""
    payload = partner_events._lead_payload(_lead(form_id='форма-без-схеми'))

    assert payload['offer'] is None
    assert payload['answers'][0]['question'] == 'Ваша спеціальність?'
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_services/test_partner_lead_payload.py -v`
Expected: FAIL — `KeyError: 'answers'`

- [ ] **Step 3: Build the offer**

У `app/services/partner_events.py`, перед `_lead_payload`:

```python
def _lead_offer(form_id):
    """Захід, на який реагувала заявка, або None.

    Партнеру це потрібно як підказка «що пропонувати»: менеджер бере
    трубку й має бачити дату, місто й ціну, а не шукати їх на нашому
    сайті посеред розмови.

    None -- нормальний стан, а не збій: форму могли не прив'язати, схеми
    форми могло ще не бути, захід могли видалити. Жоден із цих випадків не
    привід не відправити заявку.
    """
    from app.models.meta_lead import MetaLeadForm

    form_id = str(form_id or '').strip()
    if not form_id:
        return None

    form = MetaLeadForm.query.filter_by(form_id=form_id).first()
    instance = getattr(form, 'course_instance', None) if form else None
    if instance is None:
        return None

    course = getattr(instance, 'course', None)
    city = getattr(getattr(instance, 'city', None), 'name', None)
    return {
        'course_instance_id': instance.id,
        'title': getattr(course, 'title', None),
        'starts_at': instance.start_date.isoformat() if instance.start_date else None,
        # Місто зі структурованого довідника, а якщо його немає -- адреса:
        # менеджеру потрібне будь-яке «де», і порожнє поле гірше за адресу.
        'city': city or instance.location or None,
        'price': f'{instance.price:.2f}' if instance.price is not None else None,
        'url': _instance_url(instance),
    }


def _instance_url(instance):
    """Публічне посилання на захід. Абсолютне: його відкриють з іншого сайту.

    Ендпоінт саме `courses.course_by_slug` -- той самий, яким будує
    посилання `app/api/v1/serializers.py:_detail_url`. Друга назва тут
    означала б два різні посилання на ту саму сторінку.
    """
    from flask import url_for

    course = getattr(instance, 'course', None)
    slug = getattr(course, 'slug', None)
    if not slug:
        return None
    try:
        return url_for('courses.course_by_slug', slug=slug, _external=True)
    except Exception:
        # Подія може будуватись поза запитом (черга розбору), а SERVER_NAME
        # налаштований не в кожному середовищі. Посилання -- зручність, і
        # його відсутність не привід не відправити заявку.
        logger.warning('Cannot build absolute URL for course instance %s',
                       instance.id)
        return None
```

- [ ] **Step 4: Add both keys to the payload**

У `_lead_payload`, у словник, що повертається:

```python
        'is_repeat': bool(lead.is_repeat),
        # Дослівно, як віддала Meta. НЕ змінювати: приймач партнера читає
        # саме цей ключ, поки не оновиться, і це його штатний режим на час
        # деплою.
        'custom_fields': lead.field_data or {},
        # Те саме, але з людськими підписами зі схеми форми. Менеджер має
        # бачити питання й відповідь так, як їх бачила людина.
        'answers': [
            {'question': question, 'answer': answer}
            for question, answer in meta_form_schema.answers_for(
                lead.field_data, lead.form_id)
        ],
        'offer': _lead_offer(lead.form_id),
```

Додати імпорт на початку функції (не на рівні модуля — `partner_events` свідомо тримає імпорти локально):

```python
    from app.services import meta_form_schema
```

- [ ] **Step 5: Run tests**

Run: `pytest tests/test_services/test_partner_lead_payload.py tests/test_services/test_partner_events.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add app/services/partner_events.py tests/test_services/test_partner_lead_payload.py
git commit -m "feat(partner): подія lead.created везе людські підписи й захід"
```

---

### Task 4: Бекфіл уже надісланих заявок

**Files:**
- Modify: `app/cli.py`
- Modify: `app/__init__.py` (реєстрація команди)
- Test: `tests/test_cli/test_meta_reemit_leads.py`

**Interfaces:**
- Consumes: `partner_events.emit_lead_created` (Task 3).
- Produces: команда `flask meta-reemit-leads --since=YYYY-MM-DD [--dry-run] [--limit N]`; повертає кількість переграних заявок.

- [ ] **Step 1: Write the failing test**

```python
"""Бекфіл заявок, уже надісланих партнеру старим payload-ом.

Без цієї команди робота не має сенсу для НАЯВНИХ заявок: вони доїхали до
партнера без `answers` і без `offer`, а самі себе не перевідправлять.

Ідемпотентність тримає ПРИЙМАЧ (унікальний `leadgen_id` на його боці), а
не ця команда. Тут -- лише відбір і `--dry-run`, щоб було видно, що саме
поїде, перш ніж воно поїде.
"""
from datetime import datetime, timedelta, timezone

import pytest

from app.extensions import db
from app.models.meta_lead import MetaLead


def _lead(days_ago, **over):
    params = {
        'leadgen_id': f'lg-{days_ago}-{id(object())}',
        'created_time': datetime.now(timezone.utc) - timedelta(days=days_ago),
        'form_id': '900',
        'field_data': {},
        'email': f'lead{days_ago}@test.local',
    }
    params.update(over)
    lead = MetaLead(**params)
    db.session.add(lead)
    db.session.flush()
    return lead


def test_only_leads_since_the_date_are_replayed(app, monkeypatch):
    sent = []
    monkeypatch.setattr('app.services.partner_events.emit_lead_created',
                        lambda lead: sent.append(lead.leadgen_id))
    recent = _lead(2)
    _lead(90)
    db.session.commit()

    runner = app.test_cli_runner()
    since = (datetime.now(timezone.utc) - timedelta(days=7)).date().isoformat()
    result = runner.invoke(args=['meta-reemit-leads', '--since', since])

    assert result.exit_code == 0
    assert sent == [recent.leadgen_id]


def test_dry_run_sends_nothing(app, monkeypatch):
    sent = []
    monkeypatch.setattr('app.services.partner_events.emit_lead_created',
                        lambda lead: sent.append(lead.leadgen_id))
    _lead(1)
    db.session.commit()

    runner = app.test_cli_runner()
    since = (datetime.now(timezone.utc) - timedelta(days=7)).date().isoformat()
    result = runner.invoke(
        args=['meta-reemit-leads', '--since', since, '--dry-run'])

    assert result.exit_code == 0
    assert sent == []
    assert 'буде надіслано' in result.output


def test_test_and_deleted_leads_are_skipped(app, monkeypatch):
    """Ті самі відсіювання, що й у живому шляху: чужу базу не смітимо."""
    sent = []
    monkeypatch.setattr('app.services.partner_events.emit_lead_created',
                        lambda lead: sent.append(lead.leadgen_id))
    _lead(1, is_test=True)
    _lead(1, deleted_at=datetime.now(timezone.utc))
    db.session.commit()

    runner = app.test_cli_runner()
    since = (datetime.now(timezone.utc) - timedelta(days=7)).date().isoformat()
    runner.invoke(args=['meta-reemit-leads', '--since', since])

    assert sent == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_cli/test_meta_reemit_leads.py -v`
Expected: FAIL — `No such command 'meta-reemit-leads'`

- [ ] **Step 3: Add the command**

У `app/cli.py`:

```python
@click.command('meta-reemit-leads')
@click.option('--since', required=True,
              help='Дата у форматі YYYY-MM-DD: заявки від неї і новіші.')
@click.option('--limit', default=0, type=int,
              help='Стеля кількості заявок; 0 -- без стелі.')
@click.option('--dry-run', is_flag=True, help='Лише показати, що поїде.')
@with_appcontext
def meta_reemit_leads(since, limit, dry_run):
    """Переграти партнеру подію lead.created за вже розібраними заявками.

    Навіщо: заявки, доставлені до появи `answers` і `offer`, поїхали
    старим payload-ом і самі себе не перевідправлять. Без цієї команди
    робота не має сенсу для всього, що вже сталося.

    Ідемпотентність тримає ПРИЙМАЧ: у MM Medic `leadgen_id` унікальний, і
    повтор там відповідає `skipped`. Тому переграти можна скільки завгодно
    разів, і безпечніше переграти зайве, ніж недобрати.

    Тестові й видалені заявки не йдуть -- ті самі відсіювання, що й у
    живому шляху `emit_lead_created`.
    """
    from datetime import datetime, timezone

    from app.models.meta_lead import MetaLead
    from app.services import partner_events

    try:
        start = datetime.strptime(since, '%Y-%m-%d').replace(
            tzinfo=timezone.utc)
    except ValueError:
        raise click.BadParameter('Дата має бути у форматі YYYY-MM-DD')

    query = (
        MetaLead.query
        .filter(MetaLead.created_time >= start,
                MetaLead.deleted_at.is_(None),
                MetaLead.is_test.is_(False))
        .order_by(MetaLead.created_time.asc())
    )
    if limit:
        query = query.limit(limit)
    leads = query.all()

    if dry_run:
        click.echo(f'Заявок буде надіслано: {len(leads)}')
        for lead in leads[:20]:
            click.echo(f'  {lead.leadgen_id}  {lead.created_time}  '
                       f'{lead.display_name}')
        return

    sent = 0
    for lead in leads:
        try:
            partner_events.emit_lead_created(lead)
            sent += 1
        except Exception as exc:
            # Одна заявка, що не пішла, не має зупиняти решту: повторний
            # прогін безпечний, а зупинка посеред партії лишила б половину
            # історії неперенесеною й непомітно.
            click.echo(f'  ПОМИЛКА {lead.leadgen_id}: {exc}', err=True)

    click.echo(f'Надіслано подій: {sent} із {len(leads)}')
```

Зареєструвати в `app/__init__.py` поряд із рештою:

```python
    app.cli.add_command(meta_reemit_leads)
```

(і додати до наявного імпорту з `app.cli`).

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_cli/test_meta_reemit_leads.py -v`
Expected: PASS

- [ ] **Step 5: Run the whole suite**

Run: `python -m pytest -q`
Expected: PASS без нових падінь.

- [ ] **Step 6: Commit**

```bash
git add app/cli.py app/__init__.py tests/test_cli/test_meta_reemit_leads.py
git commit -m "feat(cli): meta-reemit-leads -- переграти партнеру вже розібрані заявки"
```

---

## Після реалізації

1. Деплой MM Medic (його план) має бути ВЖЕ на проді.
2. `flask db upgrade` на ІПРМ.
3. `/admin/meta-leads/forms` — прив'язати активні форми до заходів.
4. `flask meta-reemit-leads --since=<дата> --dry-run`, звірити список, потім без `--dry-run`.
5. Перевірити на живій заявці: подати форму й переконатися, що в картці клієнта MM Medic з'явився блок із заходом, а в рядку плану — підказка.
