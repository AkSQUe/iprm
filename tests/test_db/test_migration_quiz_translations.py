"""Міграція quiz_trans_20260817: колонка translations на course_quizzes.

За цю розбіжність уже заплатили проди: ``CourseQuiz`` успадкував
``TranslatableMixin``, а колонки в базі не було -- /admin/registrations віддавав
500 (``column course_quizzes.translations does not exist``), бо
``quiz_service.build_batch_context()`` вантажить тести пачкою, а SELECT тягне
ВСІ колонки моделі.

Тому тут не лише перевірка самої міграції, а й загальний вартовий: кожна
таблиця з ``TranslatableMixin`` мусить отримувати ``translations`` бодай в
одній міграції. Тестова схема будується з моделей (``create_all``), тож без
такої перевірки розходження моделі й міграцій не видно взагалі -- до проду.

``upgrade()`` не проганяємо: у тестовій схемі колонка вже є з моделі, і
``add_column`` упав би на дублікаті (той самий підхід, що в
test_migration_quiz_intro).
"""
import importlib.util
import inspect as pyinspect
import re
from pathlib import Path

import pytest
from sqlalchemy import inspect

from app.extensions import db
from app.models.course_quiz import CourseQuiz

VERSIONS = Path(__file__).resolve().parents[2] / 'migrations' / 'versions'
MIGRATION_PATH = VERSIONS / 'quiz_translations_20260817.py'


@pytest.fixture(scope='module')
def migration():
    spec = importlib.util.spec_from_file_location('m_quiz_trans', MIGRATION_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_revision_identifiers(migration):
    assert migration.revision == 'quiz_trans_20260817'
    assert migration.down_revision == 'quiz_intro_20260817'


def test_upgrade_and_downgrade_are_symmetric(migration):
    up = pyinspect.getsource(migration.upgrade)
    down = pyinspect.getsource(migration.downgrade)
    assert "add_column('course_quizzes'" in up
    assert 'translations' in up
    assert "drop_column('course_quizzes', 'translations')" in down


def test_column_is_nullable_without_default(app):
    """Відсутність перекладів означає українську -- жодних server_default."""
    columns = {c['name']: c for c in inspect(db.engine).get_columns('course_quizzes')}
    assert columns['translations']['nullable'] is True

    column = CourseQuiz.__table__.columns['translations']
    assert column.server_default is None
    assert column.default is None


MODELS = Path(__file__).resolve().parents[2] / 'app' / 'models'


def _translatable_tables():
    """Таблиці моделей із TranslatableMixin -- читанням коду, без імпорту.

    Імпортувати ``app.models`` цілком тут не можна: побічні ефекти імпорту
    (реєстрація мапперів і слухачів подій) течуть у сусідні тести того ж
    прогону -- на цьому вже попливли тести API учасників.
    """
    tables = []
    for path in MODELS.glob('*.py'):
        source = path.read_text(encoding='utf-8')
        for match in re.finditer(r'class \w+\(([^)]*)\):', source):
            if 'TranslatableMixin' not in match.group(1):
                continue
            tail = source[match.end():match.end() + 600]
            name = re.search(r"__tablename__\s*=\s*'([^']+)'", tail)
            if name:
                tables.append(name.group(1))
    assert tables, 'моделей із TranslatableMixin не знайдено -- зламався розбір'
    return sorted(tables)


COLUMN_DDL = r"sa\.Column\(\s*'translations'"


def _declares_translations(source, table):
    """Чи оголошує ця міграція translations САМЕ для цієї таблиці.

    Трьома способами, якими це роблять наявні міграції:

    * ``op.add_column('<таблиця>', sa.Column('translations', ...))``;
    * ``op.create_table('<таблиця>', ... sa.Column('translations', ...))`` --
      блок обмежуємо наступним ``op.``, інакше сусідня таблиця в тому ж файлі
      зарахувала б колонку і за себе, і за іншу (саме так виглядав
      quiz_20260817: translations були лише в quiz_questions);
    * цикл ``for table in TABLES: op.add_column(table, sa.Column(...))`` --
      тоді достатньо, щоб імʼя таблиці згадувалось у файлі.
    """
    if re.search(rf"add_column\(\s*'{table}'\s*,\s*{COLUMN_DDL}", source, re.S):
        return True

    for block in re.split(r"\n    op\.", source)[1:]:
        head = re.match(r"create_table\(\s*\n?\s*'([^']+)'", block)
        if head and head.group(1) == table and re.search(COLUMN_DDL, block):
            return True

    looped = re.search(rf"add_column\(\s*\w+\s*,\s*{COLUMN_DDL}", source, re.S)
    return bool(looped and re.search(rf"'{table}'", source))


def test_every_translatable_table_gets_the_column_in_some_migration(app):
    """Модель із мікcином без міграції -- це 500 на першому ж SELECT."""
    sources = [path.read_text(encoding='utf-8') for path in VERSIONS.glob('*.py')]

    missing = [
        table for table in _translatable_tables()
        if not any(_declares_translations(src, table) for src in sources)
    ]
    assert not missing, f'немає міграції з translations для: {missing}'
