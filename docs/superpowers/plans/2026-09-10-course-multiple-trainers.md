# Кілька тренерів на заході + автоблок спікерів (IPRM)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Захід може мати кількох тренерів у заданому порядку, а блок «Інформація про спікера» збирається з їхніх карток замість переписування руками.

**Architecture:** Дві таблиці звʼязку з колонкою `position` замість колонок `trainer_id` на курсі й проведенні. Читання -- `viewonly`-relationship із `order_by`; запис -- єдина сервісна функція `set_trainers`, яка перезаписує рядки й нумерує позиції з нуля. Перший у порядку -- головний лектор: його підпис на учасницькому сертифікаті, його ПІБ на картці заходу.

**Tech Stack:** Flask, SQLAlchemy 2.x, Alembic, WTForms, Jinja2, vanilla JS (без збірок), pytest.

**Spec:** `docs/superpowers/specs/2026-09-10-course-multiple-trainers-design.md`

**Репозиторій:** цей план покриває лише `site-iprm`. Робота в `site-mm-medic` (дзеркало, видимість ролі «Тренер», міграція) -- окремий план, і за порядком деплою зі спеки вона йде **першою**.

## Global Constraints

- Емодзі в коді немає. Інлайнового CSS і JS немає -- лише зовнішні файли.
- Tailwind не використовується. Стилі -- токени `common.css` + компонентні CSS.
- Компонент, доданий у компонентний CSS, **мусить** зʼявитись у `/admin/design-system`.
- Правка компонента дизайн-системи має впливати на всі сторінки: клас оголошується рівно в одному файлі.
- Коміт напряму в `main`, без фіча-гілок. Автопушу немає.
- Тести, що створюють користувачів, видаляють їх у teardown -- інакше валиться `test_api_v1_clients`.
- Кількість alembic-голів звіряти через `flask db heads`, не регекспом.
- Схема в тестах будується `db.create_all()` з моделей, **не** міграціями. Тому міграція пишеться один раз в останній задачі, а тести лишаються зеленими на кожному коміті.
- Порядок задач обраний так, щоб `trainer_id` лишався в моделях до кінця: колонки й читання перемикаються не одночасно.

---

### Task 1: Таблиці звʼязку і сервіс запису

**Files:**
- Create: `app/models/trainer_links.py`
- Create: `app/services/trainer_links.py`
- Create: `tests/test_services/test_trainer_links.py`

**Interfaces:**
- Produces: `app.models.trainer_links.course_trainers`, `app.models.trainer_links.course_instance_trainers` (обидва `db.Table` з колонкою `position`); `app.services.trainer_links.set_trainers(entity, trainer_ids) -> None`.

- [ ] **Step 1: Write the failing test**

Створити `tests/test_services/test_trainer_links.py`:

```python
"""Запис переліку тренерів заходу зі збереженням порядку."""
from uuid import uuid4

import pytest

from app.extensions import db
from app.models.course import Course
from app.models.trainer import Trainer
from app.models.trainer_links import course_trainers
from app.services import trainer_links


def _trainer(name):
    t = Trainer(full_name=name, slug=uuid4().hex[:8])
    db.session.add(t)
    db.session.commit()
    return t


def _course():
    c = Course(title=f'Курс {uuid4().hex[:4]}', slug=uuid4().hex[:8])
    db.session.add(c)
    db.session.commit()
    return c


def _positions(course):
    rows = db.session.execute(
        course_trainers.select()
        .where(course_trainers.c.course_id == course.id)
        .order_by(course_trainers.c.position)
    ).all()
    return [(r.trainer_id, r.position) for r in rows]


def test_numbers_positions_from_zero():
    course, a, b = _course(), _trainer('А'), _trainer('Б')
    trainer_links.set_trainers(course, [a.id, b.id])
    db.session.commit()
    assert _positions(course) == [(a.id, 0), (b.id, 1)]


def test_drops_duplicates_keeping_first_occurrence():
    course, a, b = _course(), _trainer('А'), _trainer('Б')
    trainer_links.set_trainers(course, [a.id, b.id, a.id])
    db.session.commit()
    assert _positions(course) == [(a.id, 0), (b.id, 1)]


def test_rewrites_the_whole_list():
    course, a, b, c = _course(), _trainer('А'), _trainer('Б'), _trainer('В')
    trainer_links.set_trainers(course, [a.id, b.id])
    db.session.commit()
    trainer_links.set_trainers(course, [c.id])
    db.session.commit()
    assert _positions(course) == [(c.id, 0)]


def test_empty_list_clears():
    course, a = _course(), _trainer('А')
    trainer_links.set_trainers(course, [a.id])
    db.session.commit()
    trainer_links.set_trainers(course, [])
    db.session.commit()
    assert _positions(course) == []


def test_rejects_unknown_entity_type():
    with pytest.raises(TypeError):
        trainer_links.set_trainers(object(), [])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `venv/Scripts/python.exe -m pytest tests/test_services/test_trainer_links.py -v`
Expected: FAIL -- `ModuleNotFoundError: No module named 'app.models.trainer_links'`

- [ ] **Step 3: Create the association tables**

`app/models/trainer_links.py`:

```python
"""Таблиці звʼязку «захід -- тренери» з позицією.

Окремий модуль, а не всередині course.py чи course_instance.py: обидві
таблиці потрібні обом моделям, і оголошення в будь-якій із них дало б
циклічний імпорт.

Складений PK замість сурогатного id дає унікальність пари даром: одного
тренера двічі в один захід не додати. ON DELETE CASCADE, а не SET NULL:
рядок «у заходу є тренер, і це ніхто» сенсу не має.

position без UNIQUE(захід, position) -- обмеження заважало б перестановці
(проміжний стан завжди має дублікат), а нумерує позиції одна функція,
set_trainers, з нуля й без пропусків.
"""
from app.extensions import db

course_trainers = db.Table(
    'course_trainers',
    db.Column('course_id', db.BigInteger,
              db.ForeignKey('courses.id', ondelete='CASCADE'),
              primary_key=True),
    db.Column('trainer_id', db.BigInteger,
              db.ForeignKey('trainers.id', ondelete='CASCADE'),
              primary_key=True),
    db.Column('position', db.Integer, nullable=False),
    # Окремий індекс на тренера -- для запиту у зворотному напрямку
    # («заходи цього тренера»); складений PK для нього не годиться.
    db.Index('ix_course_trainers_trainer_id', 'trainer_id'),
)

course_instance_trainers = db.Table(
    'course_instance_trainers',
    db.Column('instance_id', db.BigInteger,
              db.ForeignKey('course_instances.id', ondelete='CASCADE'),
              primary_key=True),
    db.Column('trainer_id', db.BigInteger,
              db.ForeignKey('trainers.id', ondelete='CASCADE'),
              primary_key=True),
    db.Column('position', db.Integer, nullable=False),
    db.Index('ix_course_instance_trainers_trainer_id', 'trainer_id'),
)
```

- [ ] **Step 4: Create the write service**

`app/services/trainer_links.py`:

```python
"""Запис і запити по звʼязку «захід -- тренери».

Одна функція запису на обидві таблиці: три переклади того самого
правила розійшлись би, і розбіжність було б видно лише як «у фільтрі
захід є, у списку немає».
"""
from app.extensions import db
from app.models.trainer_links import course_instance_trainers, course_trainers


def _table_and_key(entity):
    from app.models.course import Course
    from app.models.course_instance import CourseInstance
    if isinstance(entity, Course):
        return course_trainers, 'course_id'
    if isinstance(entity, CourseInstance):
        return course_instance_trainers, 'instance_id'
    raise TypeError(
        f'Немає таблиці звʼязку тренерів для {type(entity).__name__}'
    )


def set_trainers(entity, trainer_ids):
    """Перезаписати перелік тренерів сутності, зберігши порядок.

    Дублікати відсіюються зі збереженням ПЕРШОГО входження; position
    нумерується з нуля без пропусків. Commit -- на викликачі.
    """
    table, key = _table_and_key(entity)
    if entity.id is None:
        # Нова сутність ще не має id: без flush INSERT пішов би з NULL.
        db.session.flush()

    ordered, seen = [], set()
    for raw in trainer_ids or []:
        tid = int(raw)
        if tid and tid not in seen:
            seen.add(tid)
            ordered.append(tid)

    db.session.execute(table.delete().where(table.c[key] == entity.id))
    if ordered:
        db.session.execute(table.insert(), [
            {key: entity.id, 'trainer_id': tid, 'position': pos}
            for pos, tid in enumerate(ordered)
        ])
    # Relationship уже міг завантажитись у цій сесії -- без expire читач
    # побачив би старий список.
    db.session.expire(entity)
```

- [ ] **Step 5: Register the tables so create_all sees them**

У `app/models/__init__.py` додати імпорт поруч із рештою моделей, щоб
`db.create_all()` у тестах створював таблиці:

```python
from app.models import trainer_links  # noqa: F401
```

Перевірити наявний стиль файлу і вписатись у нього -- якщо там перелік
`from app.models.x import Y`, додати рядок у тому ж вигляді.

- [ ] **Step 6: Run tests to verify they pass**

Run: `venv/Scripts/python.exe -m pytest tests/test_services/test_trainer_links.py -v`
Expected: PASS (5 tests)

- [ ] **Step 7: Commit**

```bash
git add app/models/trainer_links.py app/services/trainer_links.py app/models/__init__.py tests/test_services/test_trainer_links.py
git commit -m "feat(trainers): таблиці звʼязку заходу з тренерами і сервіс запису"
```

---

### Task 2: Читання переліку на моделях

**Files:**
- Modify: `app/models/course.py` (relationship `trainer` на рядку 125-127)
- Modify: `app/models/course_instance.py` (`trainer` рядок 98, `effective_trainer` рядки 287-294)
- Modify: `app/models/online_course.py` (після рядка 140)
- Create: `tests/test_models/test_course_trainers.py`

**Interfaces:**
- Consumes: `course_trainers`, `course_instance_trainers` з Task 1.
- Produces: `Course.trainers -> list[Trainer]`, `Course.trainer -> Trainer | None`, `CourseInstance.trainers -> list[Trainer]`, `CourseInstance.effective_trainers -> list[Trainer]`, `CourseInstance.effective_trainer -> Trainer | None`, `OnlineCourse.trainers -> list[Trainer]`.

**Увага:** колонки `trainer_id` тут **не** чіпаються -- їх прибирає Task 13. Змінюється лише те, звідки читається список.

- [ ] **Step 1: Write the failing test**

Створити `tests/test_models/test_course_trainers.py`:

```python
"""Перелік тренерів заходу: порядок, успадкування, головний."""
from uuid import uuid4

from app.extensions import db
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.trainer import Trainer
from app.services import trainer_links


def _trainer(name):
    t = Trainer(full_name=name, slug=uuid4().hex[:8])
    db.session.add(t)
    db.session.commit()
    return t


def _course():
    c = Course(title=f'Курс {uuid4().hex[:4]}', slug=uuid4().hex[:8])
    db.session.add(c)
    db.session.commit()
    return c


def _instance(course):
    i = CourseInstance(course_id=course.id)
    db.session.add(i)
    db.session.commit()
    return i


def test_trainers_follow_position_not_insertion_id():
    course, a, b = _course(), _trainer('Яременко'), _trainer('Андрієнко')
    trainer_links.set_trainers(course, [b.id, a.id])
    db.session.commit()
    assert [t.id for t in course.trainers] == [b.id, a.id]


def test_course_trainer_is_the_first_one():
    course, a, b = _course(), _trainer('А'), _trainer('Б')
    trainer_links.set_trainers(course, [b.id, a.id])
    db.session.commit()
    assert course.trainer.id == b.id


def test_course_without_trainers_has_none():
    assert _course().trainer is None


def test_instance_inherits_course_list_when_empty():
    course, a, b = _course(), _trainer('А'), _trainer('Б')
    trainer_links.set_trainers(course, [a.id, b.id])
    db.session.commit()
    instance = _instance(course)
    assert [t.id for t in instance.effective_trainers] == [a.id, b.id]


def test_instance_list_overrides_course_list_entirely():
    course, a, b, c = _course(), _trainer('А'), _trainer('Б'), _trainer('В')
    trainer_links.set_trainers(course, [a.id, b.id])
    db.session.commit()
    instance = _instance(course)
    trainer_links.set_trainers(instance, [c.id])
    db.session.commit()
    # Часткового злиття немає: проведення вказало тренерів -- отже, всіх.
    assert [t.id for t in instance.effective_trainers] == [c.id]


def test_effective_trainer_is_first_of_effective_list():
    course, a, b = _course(), _trainer('А'), _trainer('Б')
    trainer_links.set_trainers(course, [a.id, b.id])
    db.session.commit()
    assert _instance(course).effective_trainer.id == a.id


def test_online_course_exposes_single_trainer_as_list():
    from app.models.online_course import OnlineCourse
    a = _trainer('А')
    oc = OnlineCourse(title='Онлайн', slug=uuid4().hex[:8], trainer_id=a.id)
    db.session.add(oc)
    db.session.commit()
    assert [t.id for t in oc.trainers] == [a.id]
    oc.trainer_id = None
    db.session.commit()
    assert oc.trainers == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `venv/Scripts/python.exe -m pytest tests/test_models/test_course_trainers.py -v`
Expected: FAIL -- `AttributeError: 'Course' object has no attribute 'trainers'`

- [ ] **Step 3: Replace the Course relationship with a list plus a property**

У `app/models/course.py` замінити наявний блок

```python
    trainer = db.relationship(
        'Trainer', foreign_keys=[trainer_id], back_populates='courses',
    )
```

на

```python
    trainers = db.relationship(
        'Trainer', secondary=course_trainers,
        order_by=course_trainers.c.position,
        viewonly=True, lazy='select',
    )

    @property
    def trainer(self):
        """Головний тренер -- перший у порядку.

        Властивість, а не колонка: денормалізований «головний» другим
        джерелом істини розходився б із переліком непомітно. Місць, де
        потрібен рівно один (ПІБ на картці, підпис на сертифікаті),
        більше, ніж місць, де потрібні всі.
        """
        return self.trainers[0] if self.trainers else None
```

Таблицю імпортувати **обʼєктом**, не рядком:
`from app.models.trainer_links import course_trainers` угорі файлу.
`secondary='course_trainers'` SQLAlchemy розвʼязав би за назвою, але
`order_by='course_trainers.c.position'` рядком обчислюється в просторі
імен реєстру моделей, куди `db.Table` не потрапляє -- і впало б на
першому ж читанні з `NameError`.

`viewonly=True` свідомо: через `secondary` SQLAlchemy не вміє писати
`position`, і мовчазна втрата порядку при `course.trainers = [...]` була
б найгіршим наслідком. Запис -- лише `trainer_links.set_trainers`.

У `app/models/trainer.py` прибрати `back_populates='courses'` з боку
тренера: relationship `Trainer.courses` (рядки 75-80) тепер має вести
через ту саму таблицю звʼязку --

```python
    courses = db.relationship(
        'Course', secondary=course_trainers,
        viewonly=True, lazy='dynamic',
    )
```

- [ ] **Step 4: Do the same for CourseInstance**

У `app/models/course_instance.py` замінити

```python
    trainer = db.relationship('Trainer', foreign_keys=[trainer_id])
```

на

```python
    trainers = db.relationship(
        'Trainer', secondary=course_instance_trainers,
        order_by=course_instance_trainers.c.position,
        viewonly=True, lazy='select',
    )
```

Імпорт так само обʼєктом:
`from app.models.trainer_links import course_instance_trainers`.

і замінити властивість `effective_trainer` на пару:

```python
    @property
    def effective_trainers(self):
        """Тренери проведення, інакше -- курсу. Повне перекриття, не злиття."""
        if self.trainers:
            return list(self.trainers)
        if self.course is None:
            self._warn_orphan('trainers')
            return []
        return list(self.course.trainers)

    @property
    def effective_trainer(self):
        """Головний тренер заходу -- перший зі списку."""
        trainers = self.effective_trainers
        return trainers[0] if trainers else None
```

- [ ] **Step 5: Add the OnlineCourse shim**

У `app/models/online_course.py` після relationship `trainer` (рядок 140):

```python
    @property
    def trainers(self):
        """Список із нуля або одного елемента.

        Партіал блоку тренера (_course_trainer.html) спільний із курсами
        і ходить по списку. Без цієї властивості цикл по неіснуючому
        атрибуту рендерився б порожнечею -- блок тренера мовчки зник би
        з усіх сторінок онлайн-курсів, без винятку в логах.

        Множинність онлайн-курсам не потрібна: колонка, форма й адмінка
        лишаються одиничними.
        """
        return [self.trainer] if self.trainer else []
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `venv/Scripts/python.exe -m pytest tests/test_models/test_course_trainers.py -v`
Expected: PASS (7 tests)

- [ ] **Step 7: Run the full suite to find readers this broke**

Run: `venv/Scripts/python.exe -m pytest -q`
Expected: падіння лише там, де код досі **пише** `trainer_id` (форми й
xlsx -- Task 3 і Task 11) або будує SQL по колонці (Task 4). Виписати
перелік у коміт-меседж, щоб наступні задачі мали чек-лист. Якщо падає
щось поза цим переліком -- зупинитись і розібратись, а не правити
навмання.

- [ ] **Step 8: Commit**

```bash
git add app/models/course.py app/models/course_instance.py app/models/online_course.py app/models/trainer.py tests/test_models/test_course_trainers.py
git commit -m "feat(trainers): читання переліку тренерів заходу з таблиць звʼязку"
```

---

### Task 3: Форма заходу і запис із адмінки

**Files:**
- Modify: `app/admin/forms.py:584` (CourseForm), `app/admin/forms.py:782` (CourseInstanceForm)
- Modify: `app/admin/_helpers.py:363-373` (`populate_trainer_choices`)
- Modify: `app/admin/routes_courses.py:100,145`; `app/admin/routes_instances.py:47`
- Modify: `app/services/course_service.py` (`populate_course_from_form` рядок 385, `duplicate` рядок 594)
- Modify: `app/templates/admin/course_edit.html:169-172`, `app/templates/admin/instance_edit.html:155-158`
- Create: `tests/test_routes/test_admin_course_trainers.py`

**Interfaces:**
- Consumes: `trainer_links.set_trainers` (Task 1), `Course.trainers` (Task 2).
- Produces: поле форми `trainer_ids` (`SelectMultipleField`, `coerce=int`); `populate_trainer_choices(form)` без аргументу `empty_label`.

- [ ] **Step 1: Write the failing test**

Створити `tests/test_routes/test_admin_course_trainers.py`:

```python
"""Збереження переліку тренерів курсу через адмінську форму."""
from uuid import uuid4

import pytest

from tests.support.rbac import grant_role

from app.extensions import db
from app.models.course import Course
from app.models.trainer import Trainer
from app.models.user import User


@pytest.fixture
def admin():
    user = User.create_with_password(
        f'tr-{uuid4().hex[:6]}@test.com', 'password123',
        first_name='A', last_name='D', email_confirmed=True,
    )
    grant_role(user, 'super_admin')
    db.session.commit()
    yield user
    # Прибираємо за собою: інакше валиться test_api_v1_clients.
    db.session.delete(user)
    db.session.commit()


@pytest.fixture
def trainers():
    rows = [
        Trainer(full_name='Андрієнко А.', slug=uuid4().hex[:8], is_active=True),
        Trainer(full_name='Богданенко Б.', slug=uuid4().hex[:8], is_active=True),
    ]
    db.session.add_all(rows)
    db.session.commit()
    return rows


def _login(client, user):
    with client.session_transaction() as session:
        session['_user_id'] = str(user.id)


def _course():
    course = Course(title=f'Курс {uuid4().hex[:4]}', slug=uuid4().hex[:8])
    db.session.add(course)
    db.session.commit()
    return course


def _post(client, course, trainer_ids):
    return client.post(f'/admin/courses/{course.id}/edit', data={
        'title': course.title, 'slug': course.slug, 'event_type': 'seminar',
        'trainer_ids': [str(i) for i in trainer_ids],
    }, follow_redirects=True)


def test_saves_submitted_order_as_is(client, admin, trainers):
    _login(client, admin)
    course = _course()
    second, first = trainers[1], trainers[0]
    assert _post(client, course, [second.id, first.id]).status_code == 200
    saved = db.session.get(Course, course.id)
    # Порядок сабміту, а не алфавіт: перший у списку -- головний лектор.
    assert [t.id for t in saved.trainers] == [second.id, first.id]


def test_reordering_rewrites_positions(client, admin, trainers):
    _login(client, admin)
    course = _course()
    a, b = trainers
    _post(client, course, [a.id, b.id])
    _post(client, course, [b.id, a.id])
    assert [t.id for t in db.session.get(Course, course.id).trainers] == [b.id, a.id]


def test_empty_submission_clears_the_list(client, admin, trainers):
    _login(client, admin)
    course = _course()
    _post(client, course, [trainers[0].id])
    _post(client, course, [])
    assert db.session.get(Course, course.id).trainers == []


def test_duplicate_copies_trainers_with_order(client, admin, trainers):
    from app.services import course_service
    course = _course()
    a, b = trainers
    from app.services import trainer_links
    trainer_links.set_trainers(course, [b.id, a.id])
    db.session.commit()
    clone = course_service.duplicate(course, created_by_id=admin.id)
    db.session.commit()
    assert [t.id for t in clone.trainers] == [b.id, a.id]
```

Перед запуском звірити точну назву й підпис функції дублювання в
`app/services/course_service.py` (близько рядка 560) і виправити виклик
у тесті, якщо вона зветься інакше.

- [ ] **Step 2: Run test to verify it fails**

Run: `venv/Scripts/python.exe -m pytest tests/test_routes/test_admin_course_trainers.py -v`
Expected: FAIL -- збережений перелік порожній (форма ще не знає поля `trainer_ids`)

- [ ] **Step 3: Swap the form fields**

У `app/admin/forms.py` замінити обидва `trainer_id = SelectField(...)`
(рядки 584 і 782) на:

```python
    trainer_ids = SelectMultipleField(
        'Тренери',
        coerce=int,
        validators=[Optional()],
        description='Порядок має значення: перший -- головний лектор, '
                    'його підпис іде на сертифікат учасника.',
    )
```

Додати `SelectMultipleField` до імпорту з `wtforms` угорі файлу.

- [ ] **Step 4: Update the choices helper and its callers**

`app/admin/_helpers.py` -- замінити `populate_trainer_choices`:

```python
def populate_trainer_choices(form):
    """Заповнити form.trainer_ids.choices активними тренерами.

    Порожнього пункту немає: у мультиселекті порожнеча виражається
    порожнім вибором, а окремий пункт «не обрано» став би значенням,
    яке треба відсіювати на кожному записі.
    """
    from app.models.trainer import Trainer
    trainers = (
        Trainer.query.filter_by(is_active=True)
        .order_by(Trainer.full_name)
        .all()
    )
    form.trainer_ids.choices = [(t.id, t.full_name) for t in trainers]
```

У `app/admin/routes_instances.py:47` прибрати аргумент:
`populate_trainer_choices(form)`.

Виклики в `routes_courses.py:100,145` уже без аргументу -- не чіпати.

- [ ] **Step 5: Route the write through the service**

У `app/services/course_service.py`, у `populate_course_from_form`,
замінити рядок `course.trainer_id = form.trainer_id.data or None` на
нічого (запис переліку робить маршрут після того, як курс отримав id).

У `app/admin/routes_courses.py` в обох гілках -- створення й
редагування -- після `populate_course_from_form(course, form)` додати:

```python
        from app.services import trainer_links
        trainer_links.set_trainers(course, form.trainer_ids.data)
```

Те саме в `app/admin/routes_instances.py` після заповнення проведення з
форми.

Заповнення форми на GET: там, де форма створюється з обʼєкта, виставити
`form.trainer_ids.data = [t.id for t in course.trainers]` (для
проведення -- `instance.trainers`, **не** `effective_trainers`: у полі
має бути власний перелік проведення, порожній означає «успадкувати»).

У `duplicate` (`course_service.py`, близько рядка 594) прибрати
`trainer_id=source.trainer_id` з конструктора `Course(...)` і після
`db.session.add(clone)` додати:

```python
    db.session.flush()  # копії потрібен id, перш ніж вішати звʼязки
    trainer_links.set_trainers(clone, [t.id for t in source.trainers])
```

- [ ] **Step 6: Swap the template widgets**

`app/templates/admin/course_edit.html`, рядки 169-172:

```html
        <div class="form-group admin-form__full">
          <label for="trainer_ids">Тренери</label>
          {{ form.trainer_ids(class="form-input", id="trainer_ids", size=8, **{'data-multiselect': '', 'data-multiselect-ordered': ''}) }}
          <small class="form-hint">{{ form.trainer_ids.description }}</small>
        </div>
```

`app/templates/admin/instance_edit.html`, рядки 155-158 -- те саме, але
з підказкою «Залиште порожнім, щоб узяти тренерів курсу».

Атрибут `data-multiselect-ordered` поки нічого не робить -- його вмикає
Task 5.

- [ ] **Step 7: Run tests to verify they pass**

Run: `venv/Scripts/python.exe -m pytest tests/test_routes/test_admin_course_trainers.py -v`
Expected: PASS (4 tests)

- [ ] **Step 8: Commit**

```bash
git add app/admin/forms.py app/admin/_helpers.py app/admin/routes_courses.py app/admin/routes_instances.py app/services/course_service.py app/templates/admin/course_edit.html app/templates/admin/instance_edit.html tests/test_routes/test_admin_course_trainers.py
git commit -m "feat(trainers): мультиселект тренерів у формах курсу й проведення"
```

---

### Task 4: SQL-фільтри й eager loading

**Files:**
- Modify: `app/services/trainer_links.py` (додати `instance_trainer_clause`, `course_trainer_clause`)
- Modify: `app/admin/routes_registrations.py:563-570`, `app/admin/routes_courses.py:54,61`, `app/admin/routes_instances.py:100`
- Modify: `app/courses/routes.py:259,293-294`, `app/main/routes.py:129`
- Create: `tests/test_services/test_trainer_clause.py`

**Interfaces:**
- Consumes: таблиці з Task 1.
- Produces: `trainer_links.instance_trainer_clause(trainer_id)` -- SQLAlchemy-вираз для фільтра по `CourseInstance`; `trainer_links.course_trainer_clause(trainer_id)` -- те саме по `Course`.

- [ ] **Step 1: Write the failing test**

Створити `tests/test_services/test_trainer_clause.py` з перевіркою всіх
чотирьох комбінацій -- тренер на проведенні / на курсі / на обох / ніде:

```python
"""Фільтр «заходи цього тренера» з тим самим fallback, що й у моделі."""
from uuid import uuid4

from app.extensions import db
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.trainer import Trainer
from app.services import trainer_links


def _trainer():
    t = Trainer(full_name=f'Т {uuid4().hex[:4]}', slug=uuid4().hex[:8])
    db.session.add(t)
    db.session.commit()
    return t


def _instance(course_trainers_ids=(), own_ids=()):
    course = Course(title=f'К {uuid4().hex[:4]}', slug=uuid4().hex[:8])
    db.session.add(course)
    db.session.commit()
    trainer_links.set_trainers(course, list(course_trainers_ids))
    instance = CourseInstance(course_id=course.id)
    db.session.add(instance)
    db.session.commit()
    trainer_links.set_trainers(instance, list(own_ids))
    db.session.commit()
    return instance


def _matches(trainer_id):
    return {
        row.id for row in CourseInstance.query.filter(
            trainer_links.instance_trainer_clause(trainer_id)
        ).all()
    }


def test_matches_when_trainer_is_on_the_instance():
    t = _trainer()
    inst = _instance(own_ids=[t.id])
    assert inst.id in _matches(t.id)


def test_matches_when_inherited_from_course():
    t = _trainer()
    inst = _instance(course_trainers_ids=[t.id])
    assert inst.id in _matches(t.id)


def test_instance_list_hides_course_trainer():
    """Проведення вказало своїх -- курсові більше не рахуються."""
    course_only, own = _trainer(), _trainer()
    inst = _instance(course_trainers_ids=[course_only.id], own_ids=[own.id])
    assert inst.id in _matches(own.id)
    assert inst.id not in _matches(course_only.id)


def test_no_match_when_trainer_is_elsewhere():
    t, other = _trainer(), _trainer()
    inst = _instance(course_trainers_ids=[other.id])
    assert inst.id not in _matches(t.id)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `venv/Scripts/python.exe -m pytest tests/test_services/test_trainer_clause.py -v`
Expected: FAIL -- `AttributeError: module 'app.services.trainer_links' has no attribute 'instance_trainer_clause'`

- [ ] **Step 3: Add the clauses**

У `app/services/trainer_links.py` дописати:

```python
from sqlalchemy import and_, exists, not_, or_, select


def course_trainer_clause(trainer_id):
    """Курс веде цей тренер. Без fallback -- курсу успадковувати нема від кого."""
    from app.models.course import Course
    return exists(select(1).where(and_(
        course_trainers.c.course_id == Course.id,
        course_trainers.c.trainer_id == trainer_id,
    )))


def instance_trainer_clause(trainer_id):
    """Проведення веде цей тренер -- із тим самим fallback, що й у моделі.

    Перелік проведення перекриває курсовий ПОВНІСТЮ, тож курс
    перевіряється лише тоді, коли у проведення немає ЖОДНОГО свого
    тренера. Одна функція на всіх споживачів: три переклади цього
    правила розійшлись би, і розбіжність було б видно лише як
    «у фільтрі захід є, у списку немає».
    """
    from app.models.course import Course
    from app.models.course_instance import CourseInstance

    own = exists(select(1).where(and_(
        course_instance_trainers.c.instance_id == CourseInstance.id,
        course_instance_trainers.c.trainer_id == trainer_id,
    )))
    has_any_own = exists(select(1).where(
        course_instance_trainers.c.instance_id == CourseInstance.id
    ))
    inherited = exists(select(1).where(and_(
        course_trainers.c.course_id == CourseInstance.course_id,
        course_trainers.c.trainer_id == trainer_id,
    )))
    return or_(own, and_(not_(has_any_own), inherited))
```

- [ ] **Step 4: Replace the call sites**

`app/admin/routes_registrations.py`, рядки 563-570 -- замінити блок з
`func.coalesce(...)` на:

```python
        if trainer_id_filter:
            from app.services.trainer_links import instance_trainer_clause
            query = query.filter(instance_trainer_clause(trainer_id_filter))
```

`app/admin/routes_courses.py:61`:

```python
    if filters['trainer_id']:
        from app.services.trainer_links import course_trainer_clause
        query = query.filter(course_trainer_clause(filters['trainer_id']))
```

Усі `joinedload(Course.trainer)` -> `selectinload(Course.trainers)` і
`joinedload(CourseInstance.trainer)` -> `selectinload(CourseInstance.trainers)`
у: `routes_courses.py:54`, `routes_instances.py:100`,
`routes_registrations.py:780-782`, `courses/routes.py:259,293-294`,
`main/routes.py:129`. `selectinload`, а не `joinedload`: на списку
заходів `joinedload` по many-to-many розмножив би рядки.

Імпорт `selectinload` додати там, де його ще немає.

- [ ] **Step 5: Run the full suite**

Run: `venv/Scripts/python.exe -m pytest -q`
Expected: PASS. Якщо десь лишився `Course.trainer` у SQL-контексті
(`filter`, `order_by`, `joinedload`), тест впаде на
`AttributeError`/`ArgumentError` -- це і є перелік недоправлених місць.

- [ ] **Step 6: Commit**

```bash
git add app/services/trainer_links.py app/admin/routes_registrations.py app/admin/routes_courses.py app/admin/routes_instances.py app/courses/routes.py app/main/routes.py tests/test_services/test_trainer_clause.py
git commit -m "feat(trainers): фільтри й eager loading через таблиці звʼязку"
```

---

### Task 5: Впорядкування чіпів у мультиселекті

**Files:**
- Modify: `app/static/js/admin-multiselect.js` (`renderChips`, близько рядка 88)
- Modify: `app/static/css/admin.css` (біля `.admin-multiselect__chip`, рядок 3664)
- Modify: `app/templates/design_system/_tab_molecules.html`
- Create: `tests/test_design_system/test_ordered_multiselect.py`

**Interfaces:**
- Consumes: атрибут `data-multiselect-ordered` з Task 3.
- Produces: чіпи з кнопками переміщення; порядок `<option>` у DOM = порядок сабміту.

Це **компонентна** правка: вона їде на всі сторінки з мультиселектом,
включно зі «Спеціальностями», де впорядкування доти сенсу не мало, але
й не шкодить. Кнопки зʼявляються лише за наявності
`data-multiselect-ordered`.

- [ ] **Step 1: Write the failing test**

`tests/test_design_system/test_ordered_multiselect.py` -- сторожі того,
що компонент є в каталозі й що форма заходу його вмикає:

```python
"""Впорядковуваний мультиселект: у каталозі й на формі заходу."""


def test_catalog_shows_ordered_multiselect(client, admin_client):
    response = admin_client.get('/admin/design-system')
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert 'admin-multiselect__chip-move' in body


def test_course_form_enables_ordering(admin_client, course):
    response = admin_client.get(f'/admin/courses/{course.id}/edit')
    assert 'data-multiselect-ordered' in response.get_data(as_text=True)
```

Звірити наявні фікстури в `tests/test_design_system/` -- якщо там немає
`admin_client`/`course`, скопіювати спосіб логіну з
`tests/test_routes/test_admin_course_specialties.py` (фікстура `admin`
+ `_login`) і прибирати користувача в teardown.

- [ ] **Step 2: Run test to verify it fails**

Run: `venv/Scripts/python.exe -m pytest tests/test_design_system/test_ordered_multiselect.py -v`
Expected: FAIL -- `admin-multiselect__chip-move` у каталозі немає

- [ ] **Step 3: Add move buttons to the chips**

У `app/static/js/admin-multiselect.js`, у `renderChips`, після кнопки
видалення додати пару кнопок -- лише коли ввімкнено впорядкування:

```javascript
      if (select.hasAttribute('data-multiselect-ordered')) {
        // Перестановка чіпа фізично рухає <option> у DOM прихованого
        // <select>: браузер сабмітить обрані значення саме в DOM-порядку,
        // тож порядок доїжджає на сервер без окремого поля з індексами.
        [['◀', -1, 'Перемістити ліворуч'],
         ['▶', 1, 'Перемістити праворуч']].forEach(function (spec) {
          var move = document.createElement('button');
          move.type = 'button';
          move.className = 'admin-multiselect__chip-move';
          move.textContent = spec[0];
          move.setAttribute(
            'aria-label', spec[2] + ': ' + option.textContent.trim()
          );
          move.addEventListener('click', function () {
            swapSelected(select, option, spec[1]);
            sync(select, ui);
          });
          chip.appendChild(move);
        });
      }
```

Поруч із `renderChips` додати:

```javascript
  // Поміняти місцями обраний <option> із сусіднім ОБРАНИМ у бік step.
  // Невибрані пункти пропускаємо: між двома чіпами їх у списку не видно,
  // і зупинка на них виглядала б як кнопка, що нічого не робить.
  function swapSelected(select, option, step) {
    var chosen = Array.prototype.filter.call(select.options, function (o) {
      return o.selected;
    });
    var at = chosen.indexOf(option);
    var target = chosen[at + step];
    if (!target) { return; }
    var parent = select;
    if (step < 0) {
      parent.insertBefore(option, target);
    } else {
      parent.insertBefore(target, option);
    }
  }
```

Перший чіп позначити головним -- у `renderChips`, там, де чіп
створюється:

```javascript
      if (select.hasAttribute('data-multiselect-ordered') && isFirstSelected) {
        chip.classList.add('admin-multiselect__chip--primary');
        chip.title = 'Головний: його підпис іде на сертифікат учасника';
      }
```

де `isFirstSelected` -- прапорець, що виставляється на першій ітерації
`forEach` (індекс 0).

- [ ] **Step 4: Add the CSS**

У `app/static/css/admin.css`, поруч із `.admin-multiselect__chip-remove`
(рядок 3670):

```css
.admin-multiselect__chip-move {
  border: 0;
  background: none;
  cursor: pointer;
  padding: 0 2px;
  color: var(--iprm-text-secondary);
  font-size: 11px;
  line-height: 1;
}
.admin-multiselect__chip-move:hover { color: var(--iprm-text-primary); }
.admin-multiselect__chip--primary {
  border: 1px solid var(--iprm-accent);
  font-weight: 600;
}
```

Токени звірити з наявними в `common.css` -- вигаданих імен не вводити.

- [ ] **Step 5: Show it in the design system catalog**

У `app/templates/design_system/_tab_molecules.html`, у секції з
мультиселектом, додати живий приклад із `data-multiselect-ordered` і
підказкою `ds-hint`, що порядок чіпів = порядок сабміту, а перший чіп --
головний. Повторити стиль наявних прикладів у файлі.

- [ ] **Step 6: Run tests to verify they pass**

Run: `venv/Scripts/python.exe -m pytest tests/test_design_system/ -v`
Expected: PASS

- [ ] **Step 7: Check it by hand**

Відкрити `/admin/courses/<id>/edit`, обрати трьох тренерів, переставити
чіпи, зберегти, перезавантажити. Порядок має вижити. Потім вимкнути JS
у DevTools і перезавантажити: має лишитись робочий нативний
мультиселект (порядок алфавітний -- прийнятний відкат).

- [ ] **Step 8: Commit**

```bash
git add app/static/js/admin-multiselect.js app/static/css/admin.css app/templates/design_system/_tab_molecules.html tests/test_design_system/test_ordered_multiselect.py
git commit -m "feat(ds): впорядкування обраних у мультиселекті"
```

---

### Task 6: Прев'ю карток спікерів у формі заходу

**Files:**
- Modify: `app/admin/routes_trainers.py` (новий маршрут наприкінці файлу)
- Create: `app/static/js/admin-course-speakers.js`
- Modify: `app/static/css/admin.css`
- Modify: `app/templates/admin/course_edit.html`, `app/templates/admin/instance_edit.html`
- Modify: `app/templates/design_system/_tab_molecules.html`
- Create: `tests/test_routes/test_admin_speaker_preview.py`

**Interfaces:**
- Consumes: `Trainer.photo_thumb`, поле `trainer_ids` (Task 3).
- Produces: `GET /admin/trainers/<id>/card.json` -> `{id, full_name, role, bio, photo, missing[], edit_url}`, де `missing` -- підмножина `['bio', 'role', 'photo']`.

- [ ] **Step 1: Write the failing test**

`tests/test_routes/test_admin_speaker_preview.py`:

```python
"""Дані картки тренера для прев'ю блоку спікерів."""
from uuid import uuid4

import pytest

from tests.support.rbac import grant_role

from app.extensions import db
from app.models.trainer import Trainer
from app.models.user import User


@pytest.fixture
def admin():
    user = User.create_with_password(
        f'prev-{uuid4().hex[:6]}@test.com', 'password123',
        first_name='A', last_name='D', email_confirmed=True,
    )
    grant_role(user, 'super_admin')
    db.session.commit()
    yield user
    db.session.delete(user)
    db.session.commit()


def _login(client, user):
    with client.session_transaction() as session:
        session['_user_id'] = str(user.id)


def _trainer(**kwargs):
    t = Trainer(full_name='Тренер Т.', slug=uuid4().hex[:8], **kwargs)
    db.session.add(t)
    db.session.commit()
    return t


def test_reports_every_empty_field(client, admin):
    _login(client, admin)
    trainer = _trainer()  # ні bio, ні ролі, ні фото
    payload = client.get(f'/admin/trainers/{trainer.id}/card.json').get_json()
    assert sorted(payload['missing']) == ['bio', 'photo', 'role']
    assert payload['full_name'] == 'Тренер Т.'


def test_filled_text_fields_drop_out_of_missing(client, admin):
    _login(client, admin)
    trainer = _trainer(bio='Біографія', role='Лікар')
    payload = client.get(f'/admin/trainers/{trainer.id}/card.json').get_json()
    assert payload['missing'] == ['photo']


def test_whitespace_only_bio_counts_as_empty(client, admin):
    _login(client, admin)
    trainer = _trainer(bio='   ', role='Лікар')
    payload = client.get(f'/admin/trainers/{trainer.id}/card.json').get_json()
    assert 'bio' in payload['missing']


def test_unknown_trainer_is_404(client, admin):
    _login(client, admin)
    assert client.get('/admin/trainers/99999999/card.json').status_code == 404


def test_anonymous_is_not_served(client):
    trainer = _trainer()
    assert client.get(
        f'/admin/trainers/{trainer.id}/card.json'
    ).status_code in (302, 401, 403)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `venv/Scripts/python.exe -m pytest tests/test_routes/test_admin_speaker_preview.py -v`
Expected: FAIL -- 404 на всіх (маршруту немає)

- [ ] **Step 3: Add the endpoint**

У кінець `app/admin/routes_trainers.py`:

```python
@admin_bp.route('/trainers/<int:trainer_id>/card.json')
@permission_required('trainers.view')
def trainer_card_json(trainer_id):
    """Картка тренера для прев'ю блоку спікерів у формі заходу.

    Окремий ендпоінт, а не JSON усіх тренерів у data-атрибуті: тренерів
    десятки, у кожного bio -- абзац, і вбудований масив зробив би форму
    заходу помітно важчою заради даних, з яких знадобиться два-три записи.
    """
    from flask import jsonify

    trainer = db.session.get(Trainer, trainer_id)
    if trainer is None:
        return jsonify({'error': 'not_found'}), 404

    # «Заповнена картка» = те, що рендерить публічний блок.
    missing = []
    if not (trainer.bio or '').strip():
        missing.append('bio')
    if not (trainer.role or '').strip():
        missing.append('role')
    if not trainer.photo_thumb:
        missing.append('photo')

    return jsonify({
        'id': trainer.id,
        'full_name': trainer.full_name,
        'role': (trainer.role or '').strip(),
        'bio': (trainer.bio or '').strip(),
        'photo': trainer.photo_thumb or '',
        'missing': missing,
        'edit_url': url_for('admin.trainer_edit', trainer_id=trainer.id),
    })
```

Перевірити, що `url_for` імпортовано у файлі.

- [ ] **Step 4: Add the preview container to both forms**

У `course_edit.html` і `instance_edit.html` одразу під полем
`trainer_ids`:

```html
          <div class="admin-speakers" data-speakers-preview
               data-speakers-source="trainer_ids"
               data-speakers-url="/admin/trainers/__ID__/card.json"
               data-speakers-empty="Тренерів не обрано -- блок спікерів на сторінці заходу не зʼявиться.">
          </div>
```

- [ ] **Step 5: Write the preview script**

`app/static/js/admin-course-speakers.js`:

```javascript
/* Прев'ю блоку спікерів у формі заходу.
 *
 * Показує, що саме збереться на сторінці заходу з карток обраних
 * тренерів, і попереджає про незаповнені -- щоб редактор не переписував
 * біографію руками і бачив дірку до збереження, а не після.
 *
 * Джерело правди -- сам <select> тренерів, як у admin-audience-preview.js:
 * слухаємо його change, а не внутрішні події компонента чіпів. Тому прев'ю
 * працює й тоді, коли мультиселект не піднявся.
 */
(function () {
  'use strict';

  var LABELS = { bio: 'немає біографії', role: 'немає ролі', photo: 'немає фото' };

  function selectedIds(select) {
    return Array.prototype.filter.call(select.options, function (option) {
      return option.selected;
    }).map(function (option) { return option.value; });
  }

  function card(data, isPrimary) {
    var box = document.createElement('div');
    box.className = 'admin-speaker-card';
    if (isPrimary) { box.classList.add('admin-speaker-card--primary'); }

    if (data.photo) {
      var img = document.createElement('img');
      img.className = 'admin-speaker-card__photo';
      img.src = data.photo;
      img.alt = '';
      img.loading = 'lazy';
      box.appendChild(img);
    }

    var body = document.createElement('div');
    body.className = 'admin-speaker-card__body';

    var name = document.createElement('strong');
    name.textContent = data.full_name + (isPrimary ? ' -- головний' : '');
    body.appendChild(name);

    if (data.role) {
      var role = document.createElement('span');
      role.className = 'admin-speaker-card__role';
      role.textContent = data.role;
      body.appendChild(role);
    }
    if (data.bio) {
      var bio = document.createElement('p');
      bio.className = 'admin-speaker-card__bio';
      bio.textContent = data.bio;
      body.appendChild(bio);
    }

    if (data.missing && data.missing.length) {
      var warn = document.createElement('p');
      warn.className = 'admin-speaker-card__warning';
      // Адресно, а не «картку не заповнено»: редактор має бачити, що
      // саме йти дописувати.
      warn.textContent = 'У картці ' + data.missing.map(function (key) {
        return LABELS[key] || key;
      }).join(', ') + '. ';
      var link = document.createElement('a');
      link.href = data.edit_url;
      link.target = '_blank';
      link.rel = 'noopener';
      link.textContent = 'Доповнити картку';
      warn.appendChild(link);
      body.appendChild(warn);
    }

    box.appendChild(body);
    return box;
  }

  function render(box, select, cache) {
    var ids = selectedIds(select);
    box.textContent = '';

    if (!ids.length) {
      var empty = document.createElement('p');
      empty.className = 'admin-speakers__empty';
      empty.textContent = box.dataset.speakersEmpty || '';
      box.appendChild(empty);
      return;
    }

    ids.forEach(function (id, index) {
      var slot = document.createElement('div');
      box.appendChild(slot);

      var draw = function (data) {
        slot.replaceWith(card(data, index === 0));
      };

      if (cache[id]) { draw(cache[id]); return; }

      fetch(box.dataset.speakersUrl.replace('__ID__', id), {
        credentials: 'same-origin'
      }).then(function (response) {
        if (!response.ok) { throw new Error('card ' + response.status); }
        return response.json();
      }).then(function (data) {
        cache[id] = data;
        draw(data);
      }).catch(function () {
        // Мережа впала -- показуємо ПІБ з <option>, а не порожнє місце:
        // редактор має бачити, що тренер обраний.
        var option = select.querySelector('option[value="' + id + '"]');
        draw({
          full_name: option ? option.textContent.trim() : ('#' + id),
          role: '', bio: '', photo: '', missing: [], edit_url: '#'
        });
      });
    });
  }

  document.addEventListener('DOMContentLoaded', function () {
    Array.prototype.forEach.call(
      document.querySelectorAll('[data-speakers-preview]'),
      function (box) {
        var select = document.getElementById(box.dataset.speakersSource);
        if (!select) { return; }
        // Кеш на сторінку: перестановка чіпів не має ходити в мережу за
        // тим, що вже показано.
        var cache = {};
        select.addEventListener('change', function () {
          render(box, select, cache);
        });
        render(box, select, cache);
      }
    );
  });
})();
```

Підключити скрипт у тих самих шаблонах, де вже підключено
`admin-multiselect.js`, у блоці скриптів -- **після** нього.

- [ ] **Step 6: Add the CSS and put the card in the catalog**

У `admin.css` додати блок `.admin-speakers`, `.admin-speaker-card`,
`__photo`, `__body`, `__role`, `__bio`, `__warning`, `--primary`,
`.admin-speakers__empty` -- на токенах, без вигаданих кольорів.

У `_tab_molecules.html` показати картку у **трьох** станах: повна,
з попередженням, порожній стан «тренерів не обрано». Компонент, якого в
каталозі не видно, наступний напише заново.

- [ ] **Step 7: Run tests to verify they pass**

Run: `venv/Scripts/python.exe -m pytest tests/test_routes/test_admin_speaker_preview.py tests/test_design_system/ -v`
Expected: PASS

- [ ] **Step 8: Check it by hand**

`/admin/courses/<id>/edit`: додати тренера з повною карткою -- зʼявилась
картка; додати тренера без bio -- зʼявилось попередження з робочим
посиланням; прибрати всіх -- зʼявився порожній стан. Зберегти форму:
попередження **не блокує** збереження.

- [ ] **Step 9: Commit**

```bash
git add app/admin/routes_trainers.py app/static/js/admin-course-speakers.js app/static/css/admin.css app/templates/admin/course_edit.html app/templates/admin/instance_edit.html app/templates/design_system/_tab_molecules.html tests/test_routes/test_admin_speaker_preview.py
git commit -m "feat(admin): прев'ю карток спікерів у формі заходу"
```

---

### Task 7: Публічний блок спікерів

**Files:**
- Modify: `app/templates/partials/_course_trainer.html`
- Modify: `app/templates/courses/detail.html:73-75` (JSON-LD)
- Modify: `app/static/css/course-landing.css` (біля `.iprm-trainer-block`, рядок 870)
- Modify: `app/templates/design_system/_tab_molecules.html:135`
- Create: `tests/test_routes/test_course_speakers_block.py`
- Create: `tests/test_routes/test_online_course_trainer_block.py`

**Interfaces:**
- Consumes: `course.trainers` / `OnlineCourse.trainers` (Task 2).

- [ ] **Step 1: Write the failing tests**

`tests/test_routes/test_course_speakers_block.py` -- дві картки на
сторінці заходу з двома тренерами, порядок збережено, заголовок у
множині.

`tests/test_routes/test_online_course_trainer_block.py` -- сторінка
онлайн-курсу з тренером **показує** блок. Це тест на регресію рівно
того мовчазного зникнення, заради якого заведено `OnlineCourse.trainers`:

```python
"""Блок тренера на сторінці онлайн-курсу не має зникнути.

Партіал спільний із курсами і ходить по списку; у OnlineCourse список
дає властивість-перехідник. Якби її не було, цикл по неіснуючому
атрибуту рендерився б порожнечею -- без помилки й без ознак у логах.
"""
```

Точні шляхи публічних сторінок звірити в `app/courses/routes.py` і
`app/online/` -- у тесті мають бути справжні URL, а не вгадані.

- [ ] **Step 2: Run tests to verify they fail**

Run: `venv/Scripts/python.exe -m pytest tests/test_routes/test_course_speakers_block.py -v`
Expected: FAIL -- на сторінці одна картка

- [ ] **Step 3: Loop the partial over the list**

У `_course_trainer.html` замінити `{% if course.trainer %}` /
`{% set trainer = course.trainer %}` на цикл по `course.trainers`,
винісши обчислення `tags` / `highlights` / `is_rich` **всередину**
циклу -- вони рахуються для кожного спікера окремо.

Заголовок:

```jinja
    <h2 id="trainer-title" class="iprm-section__title apple-reveal">
      {% if course.trainers | length > 1 %}
      {{ _('Ваші <span class="apple-gradient-text">тренери</span>') }}
      {% else %}
      {{ _('Ваш <span class="apple-gradient-text">тренер</span>') }}
      {% endif %}
    </h2>
```

Обгортка карток -- `<div class="iprm-trainer-grid">` лише коли
тренерів більше одного: **один тренер має рендеритись байт-у-байт як
зараз**, інакше знімок у кроці 6 покаже зміну на всіх наявних сторінках.

Обидва рядки заголовка додати в каталоги перекладів (`uk`, `ru`, `en`)
і скомпілювати -- звірити процедуру з `babel.cfg` і наявними
`app/translations/`.

- [ ] **Step 4: Update the JSON-LD**

`courses/detail.html`, рядки 73-75 -- `instructor` стає масивом
`Person`. Один тренер віддається масивом з одного елемента: schema.org
це дозволяє, і розгалуження в шаблоні не потрібне.

- [ ] **Step 5: Add the grid CSS and update the catalog**

У `course-landing.css`, поруч із `.iprm-trainer-block` (рядок 870):

```css
.iprm-trainer-grid {
  display: grid;
  gap: 24px;
  grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
}
```

Це поведінка компонента при кількох екземплярах, тож живе в
компонентному файлі, не в `page-*`.

У `_tab_molecules.html:135` доповнити наявний приклад блоку тренера
варіантом «кілька спікерів».

- [ ] **Step 6: Prove nothing moved for single-trainer pages**

Run: `venv/Scripts/python.exe tools/ds/html_snapshot.py`
Expected: сторінка заходу з одним тренером **не змінилась**. Будь-яка
різниця тут означає, що множинність зачепила наявну верстку -- це
регресія, а не покращення.

- [ ] **Step 7: Run tests to verify they pass**

Run: `venv/Scripts/python.exe -m pytest tests/test_routes/test_course_speakers_block.py tests/test_routes/test_online_course_trainer_block.py tests/test_design_system/ -v`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add app/templates/partials/_course_trainer.html app/templates/courses/detail.html app/static/css/course-landing.css app/templates/design_system/_tab_molecules.html app/translations tests/test_routes/test_course_speakers_block.py tests/test_routes/test_online_course_trainer_block.py
git commit -m "feat(courses): блок спікерів із карток тренерів"
```

---

### Task 8: Сертифікат лектора кожному тренеру

**Files:**
- Modify: `app/models/lecturer_certificate.py:24-36` (унікальність) і докстрінг файлу
- Modify: `app/services/certificate_service.py:721-781`
- Modify: `app/admin/routes_instances.py:367-393`
- Modify: `app/templates/admin/instance_edit.html` (блок лекторського сертифіката)
- Create: `tests/test_services/test_certificate_lecturer_multi.py`

**Interfaces:**
- Consumes: `CourseInstance.effective_trainers` (Task 2).
- Produces: `issue_lecturer_certificate(instance, trainer, issued_by=None) -> LecturerCertificate` -- **обовʼязковий** другий позиційний аргумент.

**Увага:** зміна на рівні БД (`UNIQUE(instance_id)` -> `UNIQUE(instance_id, trainer_id)`) їде в ревізії Task 13. Тут змінюється модель -- цього досить, бо тести будують схему з моделей.

- [ ] **Step 1: Write the failing test**

```python
"""Лекторський сертифікат -- кожному тренеру заходу окремо."""


def test_three_trainers_get_three_numbers_in_position_order():
    """Номери йдуть за позицією тренера, а не за порядком натискань."""


def test_reissue_returns_the_same_number_per_trainer():
    """Ідемпотентність на новому ключі (instance_id, trainer_id)."""


def test_participant_certificate_still_signed_by_the_first():
    """Учасницький сертифікат не змінює вигляд: підпис -- головного."""


def test_missing_trainer_raises_value_error():
    """Захід без тренерів -- зрозуміла помилка, а не AttributeError."""
```

Тіла дописати за зразком наявних тестів сертифікатів у
`tests/test_services/` -- звірити, які фікстури там уже готують
`SiteSettings.bpr_provider_number`, `bpr_event_number` і
`bpr_lecturer_points`, і перевикористати їх. Без цих трьох значень
`issue_lecturer_certificate` кидає `ValueError` ще до перевірки тренера.

- [ ] **Step 2: Run tests to verify they fail**

Run: `venv/Scripts/python.exe -m pytest tests/test_services/test_certificate_lecturer_multi.py -v`
Expected: FAIL -- `issue_lecturer_certificate() takes 1 positional argument`

- [ ] **Step 3: Change the model constraint**

У `app/models/lecturer_certificate.py` прибрати `unique=True` з
`instance_id` (лишити `index=True`) і додати:

```python
    __table_args__ = (
        # Один запис -- це пара «проведення + тренер». Після видалення
        # тренера пара стає (instance_id, NULL), і PostgreSQL вважає такі
        # рядки різними -- UNIQUE їх не блокує. Це правильно: два знімки
        # на двох різних видалених людей мусять співіснувати.
        db.UniqueConstraint(
            'instance_id', 'trainer_id',
            name='uq_lecturer_certificates_instance_trainer',
        ),
    )
```

Виправити докстрінг файлу: «Один запис на проведення (instance_id
unique)» більше не відповідає дійсності.

- [ ] **Step 4: Take the trainer as an argument**

У `certificate_service.py` замінити підпис і два рядки на початку:

```python
def issue_lecturer_certificate(instance, trainer, issued_by=None):
    """Видати (або повернути наявний) сертифікат лектора для пари
    «проведення + тренер».
    ...
    """
    existing = LecturerCertificate.query.filter_by(
        instance_id=instance.id, trainer_id=trainer.id,
    ).first()
    if existing is not None:
        return existing

    course = instance.course
    if trainer is None:
        raise ValueError('Не задано лектора для сертифіката.')
```

Решта тіла не змінюється -- `trainer` тепер приходить ззовні.

- [ ] **Step 5: Update the admin route and template**

`routes_instances.py:367` -- приймати `trainer_id` формою, резолвити
його **серед тренерів заходу** (чужого не приймати):

```python
    trainer_id = request.form.get('trainer_id', type=int)
    trainer = next(
        (t for t in instance.effective_trainers if t.id == trainer_id), None
    )
    if trainer is None:
        flash('Оберіть лектора зі списку тренерів заходу', 'error')
        return redirect(url_for('admin.instance_edit', instance_id=instance_id))
```

`instance_edit.html` -- рядок на кожного тренера заходу: ПІБ, номер уже
виданого сертифіката (з посиланням) або кнопка «Видати». Кнопки «видати
всім» немає: видача кожного лишається свідомою дією. Якщо тренерів
немає -- показати теперішнє повідомлення про незаданого лектора.

- [ ] **Step 6: Run tests to verify they pass**

Run: `venv/Scripts/python.exe -m pytest tests/test_services/ -q`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add app/models/lecturer_certificate.py app/services/certificate_service.py app/admin/routes_instances.py app/templates/admin/instance_edit.html tests/test_services/test_certificate_lecturer_multi.py
git commit -m "feat(certificates): лекторський сертифікат кожному тренеру заходу"
```

---

### Task 9: Розсилка всім тренерам заходу

**Files:**
- Modify: `app/services/notification_recipients.py:70-74` і докстрінг файлу (рядок 10)
- Modify: `app/admin/routes_notifications_recipients.py` (підпис у UI)
- Modify: `tests/test_services/test_notification_recipients.py` (додати випадки)

- [ ] **Step 1: Write the failing test**

Додати до наявного `tests/test_services/test_notification_recipients.py`:

```python
def test_notifies_every_trainer_of_the_event():
    """Кожен, хто веде захід, бачить реєстрації."""


def test_trainer_who_is_also_a_manager_gets_one_letter():
    """Дедуплікація за адресою -- разом з адмінами й менеджерами."""


def test_trainer_without_email_is_skipped_silently():
    """Email у тренера nullable: історично їх додавали без пошти."""
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `venv/Scripts/python.exe -m pytest tests/test_services/test_notification_recipients.py -v`
Expected: FAIL -- у `breakdown['trainer']` одна адреса замість двох

- [ ] **Step 3: Collect every trainer**

Замінити блок на рядках 70-74:

```python
    if rule.notify_event_trainer and instance is not None:
        # Структура breakdown не змінюється -- 'trainer' уже список,
        # лише наповнюється циклом.
        for trainer in getattr(instance, 'effective_trainers', None) or []:
            email = getattr(trainer, 'email', None)
            if email:
                breakdown['trainer'].append(email)
```

Виправити докстрінг файлу (рядок 10):
`- notify_event_trainer -> email кожного з instance.effective_trainers`.

- [ ] **Step 4: Update the admin label**

У `routes_notifications_recipients.py` і відповідному шаблоні підпис
правила -- «Тренери заходу» замість «Тренер заходу». Зміст правила не
змінюється.

- [ ] **Step 5: Run tests to verify they pass**

Run: `venv/Scripts/python.exe -m pytest tests/test_services/test_notification_recipients.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add app/services/notification_recipients.py app/admin/routes_notifications_recipients.py app/templates tests/test_services/test_notification_recipients.py
git commit -m "feat(notifications): розсилка всім тренерам заходу"
```

---

### Task 10: API v1 -- `trainers` замість `trainer`

**Files:**
- Modify: `app/api/v1/serializers.py:245-247`
- Modify: `app/api/v1/events.py:280-281,354-355,385-386`
- Modify: `tests/test_routes/test_api_v1.py` (звірити точну назву файла)

- [ ] **Step 1: Write the failing test**

```python
def test_event_card_serializes_trainers_as_ordered_array():
    """Порядок у відповіді -- порядок position, не id."""


def test_trainer_key_is_gone():
    """Поле замінюється, не дублюється: гілка сумісності назавжди --
    це другий формат, про який ніхто не знатиме, який актуальний."""


def test_events_list_does_not_n_plus_one_on_trainers():
    """Список заходів -- рівно та форма запиту, де N+1 виникає непомітно."""
```

Для третього використати наявний у проєкті спосіб рахувати запити
(пошукати в `tests/` за `assert_num_queries` або лічильником подій
SQLAlchemy; якщо такого немає -- порахувати через
`sqlalchemy.event.listen(engine, 'before_cursor_execute', ...)`).

- [ ] **Step 2: Run tests to verify they fail**

Run: `venv/Scripts/python.exe -m pytest tests/test_routes/test_api_v1.py -v`
Expected: FAIL -- ключа `trainers` немає

- [ ] **Step 3: Swap the serializer field**

`serializers.py`, рядки 245-247:

```python
        'trainers': [serialize_trainer(t) for t in (
            instance.effective_trainers if instance else course.trainers
        )],
```

`serialize_trainer` не змінюється.

- [ ] **Step 4: Fix the eager loads**

Шість місць у `events.py` (280, 281, 354, 355, 385, 386):
`joinedload(Course.trainer)` -> `selectinload(Course.trainers)`,
`joinedload(CourseInstance.trainer)` -> `selectinload(CourseInstance.trainers)`.

Перевірити **всі шість** на N+1 після правки: `effective_trainers`
падає на `course.trainers`, коли у проведення немає своїх, тож
підвантажувати треба обидва боки.

- [ ] **Step 5: Run tests to verify they pass**

Run: `venv/Scripts/python.exe -m pytest tests/test_routes/test_api_v1.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add app/api/v1/serializers.py app/api/v1/events.py tests/test_routes/test_api_v1.py
git commit -m "feat(api): trainers масивом замість одиничного trainer"
```

---

### Task 11: xlsx -- колонка `trainer_slugs`

**Files:**
- Modify: `app/services/xlsx_io.py` (рядки 180, 202, 523, 543, 679-687, 751, 772, 842-847, 959-991)
- Create: `tests/test_services/test_xlsx_trainers.py`

- [ ] **Step 1: Write the failing test**

```python
def test_round_trip_keeps_order_of_several_trainers():
    """Експорт -> імпорт не міняє порядок: перший лишається головним."""


def test_semicolon_is_the_separator():
    """Кома не годиться: колонка містить ПІБ, а «Іванов І. І., PhD» --
    цілком можливий."""


def test_comma_is_accepted_on_import():
    """Людина, яка друкує вручну, поставить кому."""


def test_unknown_slug_reports_every_bad_value_at_once():
    """Одна помилка рядка з переліком усіх нерозпізнаних, а не падіння
    на першому."""
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `venv/Scripts/python.exe -m pytest tests/test_services/test_xlsx_trainers.py -v`
Expected: FAIL -- колонки `trainer_slugs` немає

- [ ] **Step 3: Rename the column and export a list**

`trainer_slug` -> `trainer_slugs` у ширинах (рядки 180, 202), у
`COURSE_COLS` (523) і в підписах (543: `'trainer_slugs': 'Тренери'`).

Експорт (рядок 772) -- зʼєднати ПІБ усіх тренерів через `'; '`.

- [ ] **Step 4: Drop the drop-down, keep the reference sheet**

Прибрати виклик `_add_trainer_dropdown` (рядки 842-847). Аркуш-довідник
тренерів (`_add_trainers_sheet`) **лишається**: він потрібен людині як
джерело точних написань. Excel не вміє валідувати клітинку з кількома
значеннями, і залишений drop-down мовчки блокував би правильне введення.

- [ ] **Step 5: Parse the list on import**

Замість резолву одного значення (рядки 989-991) -- розбити по `;` і `,`,
зарезолвити кожен елемент тією самою парою словників
(`trainer_id_by_slug`, `trainer_id_by_name`), зібрати всі нерозпізнані
в **одну** помилку рядка, і на успіху викликати
`trainer_links.set_trainers(course, ids)` у порядку запису.

- [ ] **Step 6: Run tests to verify they pass**

Run: `venv/Scripts/python.exe -m pytest tests/test_services/test_xlsx_trainers.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add app/services/xlsx_io.py tests/test_services/test_xlsx_trainers.py
git commit -m "feat(xlsx): колонка trainer_slugs зі списком тренерів"
```

---

### Task 12: Видалення `speaker_info` з коду

**Files:**
- Modify: `app/admin/forms.py:500-503`
- Modify: `app/templates/admin/course_edit.html:242-246`
- Modify: `app/services/course_service.py:365,584`
- Modify: `app/services/translation_registry.py:27`
- Modify: `app/services/xlsx_io.py:183,523,546,777,1017,1153,1213`
- Modify: `app/api/v1/serializers.py:262`
- Create: `tests/test_routes/test_course_speaker_info_removed.py`

**Увага:** колонку `courses.speaker_info` з моделі прибирає Task 13
разом із міграцією. Тут прибираються всі **читачі й писачі**.

- [ ] **Step 1: Write the failing test**

```python
"""Поле speaker_info прибрано: його заміщає блок спікерів із карток."""


def test_course_form_has_no_speaker_info_field(admin_client, course):
    body = admin_client.get(f'/admin/courses/{course.id}/edit').get_data(as_text=True)
    assert 'speaker_info' not in body


def test_api_event_detail_has_no_speaker_info_key(client, course):
    ...


def test_xlsx_export_has_no_speaker_info_column():
    ...


def test_xlsx_import_tolerates_files_with_the_old_column():
    """Зайві колонки імпорт ігнорує -- старі файли лишаються робочими."""
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `venv/Scripts/python.exe -m pytest tests/test_routes/test_course_speaker_info_removed.py -v`
Expected: FAIL -- поле ще на місці

- [ ] **Step 3: Remove every reader and writer**

- `forms.py:500-503` -- поле `speaker_info`.
- `course_edit.html:242-246` -- блок разом із `i18n.panes`.
- `course_service.py:365` (`populate_course_from_form`) і `:584`
  (`duplicate`).
- `translation_registry.py:27` -- запис `'speaker_info': 'Про спікера'`.
  Реєстр і є переліком того, що перекладається, тож окремої чистки
  таблиці перекладів не треба.
- `xlsx_io.py` -- ширини (183), `COURSE_COLS` (523), підпис (546),
  експорт (777), парсер (1017), перелік полів (1153), запис (1213).
- `serializers.py:262` -- ключ у `serialize_event_detail`.

Прибрати `'speaker_info'` з `Course.__translatable__` (`course.py:16`).

- [ ] **Step 4: Run the full suite**

Run: `venv/Scripts/python.exe -m pytest -q`
Expected: PASS. Модель ще має колонку -- це нормально, її знімає Task 13.

- [ ] **Step 5: Commit**

```bash
git add app/admin/forms.py app/templates/admin/course_edit.html app/services/course_service.py app/services/translation_registry.py app/services/xlsx_io.py app/api/v1/serializers.py app/models/course.py tests/test_routes/test_course_speaker_info_removed.py
git commit -m "refactor(courses): прибрати speaker_info -- його заміщає блок спікерів"
```

---

### Task 13: Міграція і зняття колонок

**Files:**
- Create: `migrations/versions/course_trainers_20260910.py`
- Modify: `app/models/course.py` (прибрати `trainer_id`, `speaker_info`)
- Modify: `app/models/course_instance.py` (прибрати `trainer_id`)
- Create: `tests/test_db/test_migration_course_trainers.py`

**Interfaces:**
- Consumes: усе з Task 1-12.

- [ ] **Step 1: Check the current head**

Run: `venv/Scripts/python.exe -m flask db heads`
Expected: рівно одна голова. Її revision -- це `down_revision` нової
ревізії. Регекспом по файлах не рахувати: кортежні merge-ревізії він не
бачить.

- [ ] **Step 2: Write the failing test**

`tests/test_db/test_migration_course_trainers.py` -- за зразком наявних
тестів у `tests/test_db/`:

```python
def test_upgrade_moves_trainer_id_to_position_zero():
    """Бекфіл: наявний тренер стає головним."""


def test_downgrade_restores_the_first_trainer():
    """Дзеркально -- перший повертається в колонку."""


def test_downgrade_fails_loudly_on_multiple_lecturer_certificates():
    """Ревізія має впасти зрозуміло, з переліком проведень, що
    заважають, а не помилкою БД про порушення UNIQUE."""
```

- [ ] **Step 3: Write the revision**

`migrations/versions/course_trainers_20260910.py`, `revision =
'course_trainers_20260910'`, `down_revision` -- зі Step 1. П'ять кроків
у `upgrade`:

1. `create_table` `course_trainers` і `course_instance_trainers` +
   індекси на `trainer_id`.
2. Бекфіл:
   ```sql
   INSERT INTO course_trainers (course_id, trainer_id, position)
   SELECT id, trainer_id, 0 FROM courses WHERE trainer_id IS NOT NULL
   ```
   і те саме з `course_instances` у `course_instance_trainers`.
3. `drop_column` `courses.trainer_id`, `course_instances.trainer_id`.
4. `lecturer_certificates`: зняти `UNIQUE(instance_id)`, поставити
   `UNIQUE(instance_id, trainer_id)`.
5. `drop_column` `courses.speaker_info`.

`downgrade` -- дзеркально, і **обовʼязково з коментарем у самій
ревізії**, а не лише в спеці:

```python
def downgrade():
    """УВАГА: тренери з позицій 1+ при відкаті ВТРАЧАЮТЬСЯ -- колонка
    вміщає одного. Колонка speaker_info повертається порожньою: її вміст
    -- переписані руками біографії, які вже є в картках тренерів.

    Перед поверненням UNIQUE(instance_id) перевіряємо дублікати й
    падаємо зі зрозумілим текстом: інакше БД скаже лише «violates unique
    constraint», не назвавши проведень.
    """
```

- [ ] **Step 4: Drop the columns from the models**

`course.py` -- прибрати `trainer_id` (рядки 86-91) і `speaker_info`
(рядок 42). `course_instance.py` -- прибрати `trainer_id` (рядки 59-63).

- [ ] **Step 5: Run the migration against the dev database**

Run: `venv/Scripts/python.exe -m flask db upgrade`

Dev-БД відокремлена від прод (`DATABASE_URL_DEV`). `DATABASE_URL` з
командного рядка **мовчки ігнорується** -- перевірити, що застосувалось
саме до dev, перш ніж радіти.

Потім перевірити відкат і повернення:

```bash
venv/Scripts/python.exe -m flask db downgrade
venv/Scripts/python.exe -m flask db upgrade
```

- [ ] **Step 6: Run everything**

Run: `venv/Scripts/python.exe -m pytest -q`
Expected: PASS -- усе.

Run: `venv/Scripts/python.exe tools/ds/html_snapshot.py`
Expected: сторінка заходу з одним тренером не змінилась.

Run: `venv/Scripts/python.exe tools/ds/ds_audit.py`
Expected: без нових порушень дизайн-системи.

- [ ] **Step 7: Commit**

```bash
git add migrations/versions/course_trainers_20260910.py app/models/course.py app/models/course_instance.py tests/test_db/test_migration_course_trainers.py
git commit -m "feat(trainers): міграція на таблиці звʼязку, зняття trainer_id і speaker_info"
```

---

## Після плану

Робота **не деплоїться сама по собі**. За порядком зі спеки:

1. `site-mm-medic` -- міграція + читання обох форматів (окремий план).
2. `site-iprm` -- цей план.
3. Ресинк каталогу на боці mm-medic.
4. `site-mm-medic` -- прибрати читання старого формату.

Крок 4 -- не «колись потім»: залишена гілка сумісності означає, що
наступний, хто читатиме код, не знатиме, який формат актуальний.
