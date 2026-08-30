"""Міграція quiz_intro_20260817: вступний текст і дедлайн складання.

DDL тут простий, тож перевіряємо не його, а те, за що платили б у проді:

* обидві колонки nullable і без server_default -- наявні тести (у проді їх два)
  мусять поводитись точно як досі, доки адмін не заповнить поля сам;
* ланцюг ревізій не розгалужений -- інакше ``flask db upgrade`` на деплої
  впаде з "Multiple head revisions", і не застосується жодна міграція;
* CHECK не пускає відʼємну кількість днів -- «-1» закрив би тест до початку
  заходу.

Саму ``upgrade()`` не проганяємо: у тестовій схемі (``create_all`` з моделей)
колонки вже є, тож ``add_column`` упав би на дублікаті. Той самий підхід, що в
test_migration_bpr_counter.
"""
import importlib.util
import re
from pathlib import Path

import pytest
from sqlalchemy import inspect

from app.extensions import db
from app.models.course_quiz import CourseQuiz

VERSIONS = Path(__file__).resolve().parents[2] / 'migrations' / 'versions'
MIGRATION_PATH = VERSIONS / 'quiz_intro_20260817_intro_deadline.py'


@pytest.fixture(scope='module')
def migration():
    spec = importlib.util.spec_from_file_location('m_quiz_intro', MIGRATION_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_revision_identifiers(migration):
    assert migration.revision == 'quiz_intro_20260817'
    assert migration.down_revision == 'thankyou_online_20260817'


def test_chain_has_a_single_head():
    """Дві голови означають, що на деплої не застосується НІЧОГО."""
    revisions, parents = {}, set()
    for path in VERSIONS.glob('*.py'):
        text = path.read_text(encoding='utf-8')
        rev = re.search(r"^revision = '([^']+)'", text, re.M)
        # Батько буває ОДИН (`'abc'`) і буває КІЛЬКА (`('abc', 'def')`) --
        # друге це ревізія-злиття, якою зводять дві гілки. Регулярка на
        # один рядок їх не бачила, тож після кожного злиття обидві зведені
        # гілки й далі рахувались головами: тест червонів саме тоді, коли
        # проблему вже полагодили.
        down = re.search(r'^down_revision = (.+)$', text, re.M)
        if rev:
            revisions[rev.group(1)] = path.name
        if down:
            parents.update(re.findall(r"'([^']+)'", down.group(1)))
    heads = [r for r in revisions if r not in parents]
    # Перевіряємо кількість, а не імʼя голови: інакше кожна наступна міграція
    # «ламала» б цей тест, і його правили б машинально, не читаючи.
    assert len(heads) == 1, f'голови: {heads}'


def test_upgrade_and_downgrade_are_symmetric(migration):
    import inspect as pyinspect
    up = pyinspect.getsource(migration.upgrade)
    down = pyinspect.getsource(migration.downgrade)
    for column in ('intro', 'deadline_days_after_end'):
        assert column in up
        assert column in down


def test_columns_are_nullable(app):
    """Наявні тести мусять поводитись як досі: NULL -- це «як раніше»."""
    columns = {c['name']: c for c in inspect(db.engine).get_columns('course_quizzes')}
    assert columns['intro']['nullable'] is True
    assert columns['deadline_days_after_end']['nullable'] is True


def test_columns_have_no_server_default(app):
    """server_default перетворив би «без обмеження» на дедлайн для всіх."""
    for name in ('intro', 'deadline_days_after_end'):
        column = CourseQuiz.__table__.columns[name]
        assert column.server_default is None, name
        assert column.default is None, name


def test_existing_quiz_keeps_previous_behaviour(app):
    """Тест, створений до міграції, лишається без дедлайну й без вступу."""
    quiz = CourseQuiz(course_id=None, instance_id=1)
    db.session.add(quiz)
    db.session.flush()
    assert quiz.intro is None
    assert quiz.deadline_days_after_end is None


def test_negative_deadline_is_refused_by_the_database(app):
    from sqlalchemy.exc import IntegrityError

    quiz = CourseQuiz(course_id=None, instance_id=2, deadline_days_after_end=-1)
    db.session.add(quiz)
    with pytest.raises(IntegrityError):
        db.session.flush()
    db.session.rollback()


def test_zero_deadline_is_allowed(app):
    """0 -- легальне значення й саме те, що просить роздатка учасникам."""
    quiz = CourseQuiz(course_id=None, instance_id=3, deadline_days_after_end=0)
    db.session.add(quiz)
    db.session.flush()
    assert quiz.deadline_days_after_end == 0


def test_intro_is_registered_as_translatable():
    assert 'intro' in CourseQuiz.__translatable__
