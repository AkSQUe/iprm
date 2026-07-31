"""Міграція i18n_srckey_20260731: path-ключі -> хеш-ключі джерела.

Міграція чіпає вміст translations у 4 таблицях на проді, тож перевіряємо
її не лише на чистих функціях, а й наскрізь -- через справжній
alembic-контекст на тестовій БД: так ловиться і SQL-обв'язка (визначення
таблиць, серіалізація JSON, update по id).
"""
import importlib.util
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext

from app.extensions import db
from app.i18n import source_key
from app.models.blog_post import BlogPost
from app.models.course import Course

MIGRATION_PATH = (
    Path(__file__).resolve().parents[2]
    / 'migrations' / 'versions' / 'i18n_srckey_20260731.py'
)


@pytest.fixture(scope='module')
def migration():
    spec = importlib.util.spec_from_file_location('m_i18n_srckey', MIGRATION_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _run(migration, direction='upgrade'):
    """Виконати міграцію на з'єднанні поточної тестової сесії."""
    db.session.flush()
    conn = db.session.connection()
    ctx = MigrationContext.configure(conn)
    with Operations.context(ctx):
        getattr(migration, direction)()
    db.session.expire_all()


# --- чисті функції перекодування ключів ------------------------------------

def test_path_to_hash_rekeys_resolvable_paths(migration):
    leaves = [('0.question', 'Питання?'), ('0.answer', 'Відповідь.')]
    rebuilt, changed, kept = migration._path_to_hash(
        {'0.question': 'Вопрос?'}, leaves)
    assert rebuilt == {source_key('Питання?'): 'Вопрос?'}
    assert (changed, kept) == (1, 0)


def test_path_to_hash_keeps_unresolvable_paths(migration):
    """Нерезолвний шлях не викидаємо -- читання підтримує legacy-формат."""
    rebuilt, changed, kept = migration._path_to_hash(
        {'9.zzz': 'сирота'}, [('0.question', 'Питання?')])
    assert rebuilt == {'9.zzz': 'сирота'}
    assert (changed, kept) == (0, 1)


def test_hash_to_path_is_inverse(migration):
    leaves = [('0.question', 'Питання?')]
    forward, _, _ = migration._path_to_hash({'0.question': 'Вопрос?'}, leaves)
    back, _, _ = migration._hash_to_path(forward, leaves)
    assert back == {'0.question': 'Вопрос?'}


def test_walk_leaves_copy_matches_app_logic(migration):
    """Заморожена копія обходу не повинна розійтися з поточною реалізацією."""
    from app.i18n import walk_leaves
    content = [
        {'type': 'paragraph', 'data': {'html': 'Абзац.'}},
        {'type': 'image', 'data': {'thumb': '/media/x.webp', 'caption': 'Підпис'}},
    ]
    assert migration._walk_leaves(content) == walk_leaves(content)


# --- наскрізний прогін ------------------------------------------------------

def test_upgrade_converts_course_faq(client, migration):
    c = Course(title='Курс', slug=f'c-{uuid4().hex[:6]}',
               faq=[{'question': 'Питання?', 'answer': 'Відповідь.'}])
    c.translations = {'ru': {'faq': {'0.question': 'Вопрос?'},
                             'title': 'Курс-РУ'}}
    db.session.add(c)
    db.session.commit()

    _run(migration, 'upgrade')

    fetched = db.session.get(Course, c.id)
    assert fetched.translations['ru']['faq'] == {source_key('Питання?'): 'Вопрос?'}
    # Скалярні переклади не чіпаються.
    assert fetched.translations['ru']['title'] == 'Курс-РУ'
    assert fetched.t('faq', lang='ru')[0]['question'] == 'Вопрос?'


def test_upgrade_result_survives_reorder(client, migration):
    """Заради цього все й робиться: після міграції переклад іде за текстом."""
    c = Course(title='Курс', slug=f'c-{uuid4().hex[:6]}',
               faq=[{'question': 'A?', 'answer': 'A.'},
                    {'question': 'B?', 'answer': 'B.'}])
    c.translations = {'en': {'faq': {'0.question': 'A-en?', '1.question': 'B-en?'}}}
    db.session.add(c)
    db.session.commit()

    _run(migration, 'upgrade')

    fetched = db.session.get(Course, c.id)
    fetched.faq = [{'question': 'C?', 'answer': 'C.'},
                   {'question': 'A?', 'answer': 'A.'},
                   {'question': 'B?', 'answer': 'B.'}]
    db.session.commit()

    en = db.session.get(Course, c.id).t('faq', lang='en')
    assert [i['question'] for i in en] == ['C?', 'A-en?', 'B-en?']


def test_upgrade_then_downgrade_round_trip(client, migration):
    p = BlogPost(slug=f'p-{uuid4().hex[:6]}', title='T', status='published',
                 content=[{'type': 'paragraph', 'data': {'html': 'Оригінал.'}}])
    p.translations = {'ru': {'content': {'0.data.html': 'Оригинал.'}}}
    db.session.add(p)
    db.session.commit()

    _run(migration, 'upgrade')
    assert db.session.get(BlogPost, p.id).translations['ru']['content'] == {
        source_key('Оригінал.'): 'Оригинал.'
    }

    _run(migration, 'downgrade')
    assert db.session.get(BlogPost, p.id).translations['ru']['content'] == {
        '0.data.html': 'Оригинал.'
    }


def test_upgrade_is_idempotent(client, migration):
    c = Course(title='Курс', slug=f'c-{uuid4().hex[:6]}',
               faq=[{'question': 'Питання?', 'answer': 'Відповідь.'}])
    c.translations = {'ru': {'faq': {'0.question': 'Вопрос?'}}}
    db.session.add(c)
    db.session.commit()

    _run(migration, 'upgrade')
    first = dict(db.session.get(Course, c.id).translations['ru']['faq'])
    _run(migration, 'upgrade')
    assert db.session.get(Course, c.id).translations['ru']['faq'] == first


def test_upgrade_ignores_rows_without_translations(client, migration):
    c = Course(title='Курс', slug=f'c-{uuid4().hex[:6]}',
               faq=[{'question': 'Питання?', 'answer': 'Відповідь.'}])
    db.session.add(c)
    db.session.commit()

    _run(migration, 'upgrade')

    assert db.session.get(Course, c.id).translations is None
