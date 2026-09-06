"""Інлайн-переклади в адмін-формах: JSON-поля, блоки програми, тарифи,
індикатори покриття.

До Фази 4 JSON-поля (FAQ, теги, аудиторія) редагувались лише на окремій
сторінці /admin/translations, а блоки й тарифи -- на власних сторінках:
курс із 5 блоками і 3 тарифами означав 9 переходів.
"""
from tests.support.rbac import grant_role
from uuid import uuid4

import pytest

from app.extensions import db
from app.i18n import source_key
from app.models.course import Course
from app.models.course_tariff import CourseTariff
from app.models.program_block import ProgramBlock
from app.models.user import User


@pytest.fixture
def admin():
    u = User.create_with_password(
        f'a-{uuid4().hex[:6]}@test.com', 'password123',
        first_name='A', last_name='D', email_confirmed=True,
    )
    grant_role(u, 'super_admin')
    db.session.commit()
    return u


def _login(client, user):
    with client.session_transaction() as s:
        s['_user_id'] = str(user.id)


def _course(**kw):
    kw.setdefault('title', f'Курс {uuid4().hex[:4]}')
    c = Course(slug=f'in-{uuid4().hex[:6]}', is_active=True, event_type='course', **kw)
    db.session.add(c)
    db.session.commit()
    return c


def _post_data(course, **extra):
    """Мінімальний валідний сабміт форми курсу."""
    data = {
        'title': course.title,
        'slug': course.slug,
        'event_type': course.event_type or 'course',
        'base_price': '0',
        'sort_order': '0',
        'faq_text': _faq_text(course),
        'target_audience_text': '\n'.join(course.target_audience or []),
        'tags_text': '\n'.join(course.tags or []),
    }
    data.update(extra)
    return data


def _faq_text(course):
    blocks = []
    for item in (course.faq or []):
        blocks.append(f"{item.get('question', '')}\n{item.get('answer', '')}".strip())
    return '\n\n'.join(blocks)


# --- JSON-поля у формі курсу ------------------------------------------------

def test_course_form_renders_json_panes(client, admin):
    _login(client, admin)
    c = _course(faq=[{'question': 'Питання?', 'answer': 'Відповідь.'}],
                tags=['PRP'])
    html = client.get(f'/admin/courses/{c.id}/edit').get_data(as_text=True)

    assert f'tr__ru__faq__{source_key("Питання?")}' in html
    assert f'tr__en__faq__{source_key("Відповідь.")}' in html
    assert f'tr__ru__tags__{source_key("PRP")}' in html


def test_course_form_saves_json_translation(client, admin):
    _login(client, admin)
    c = _course(faq=[{'question': 'Питання?', 'answer': 'Відповідь.'}])
    key = source_key('Питання?')

    r = client.post(f'/admin/courses/{c.id}/edit',
                    data=_post_data(c, **{f'tr__ru__faq__{key}': 'Вопрос?'}))
    assert r.status_code == 302

    fetched = db.session.get(Course, c.id)
    assert fetched.t('faq', lang='ru')[0]['question'] == 'Вопрос?'
    assert fetched.t('faq', lang='ru')[0]['answer'] == 'Відповідь.'


def test_editing_text_and_translation_in_one_submit(client, admin):
    """Порядок обробки: спершу укр-контент, потім переклади. Переклад
    фрагмента, що вцілів, застосовується; для переписаного -- ні."""
    _login(client, admin)
    c = _course(faq=[{'question': 'Стале?', 'answer': 'Буде переписано.'}])
    stable_key = source_key('Стале?')
    doomed_key = source_key('Буде переписано.')

    client.post(f'/admin/courses/{c.id}/edit', data=_post_data(
        c,
        faq_text='Стале?\nНовий текст відповіді.',
        **{f'tr__ru__faq__{stable_key}': 'Стабильный?',
           f'tr__ru__faq__{doomed_key}': 'Не має застосуватись'},
    ))

    fetched = db.session.get(Course, c.id)
    ru = fetched.t('faq', lang='ru')[0]
    assert ru['question'] == 'Стабильный?'
    assert ru['answer'] == 'Новий текст відповіді.'
    assert 'Не має застосуватись' not in str(fetched.translations)


def test_scalar_translation_still_saves(client, admin):
    _login(client, admin)
    c = _course()
    client.post(f'/admin/courses/{c.id}/edit',
                data=_post_data(c, tr__ru__title='Курс-РУ'))
    assert db.session.get(Course, c.id).t('title', lang='ru') == 'Курс-РУ'


def test_untouched_field_keeps_translation(client, admin):
    """Сабміт без інпутів поля не має його стирати."""
    _login(client, admin)
    c = _course(faq=[{'question': 'Питання?', 'answer': 'Відповідь.'}])
    c.set_translation('ru', 'title', 'Курс-РУ')
    db.session.commit()

    data = _post_data(c)
    data.pop('tr__ru__title', None)
    client.post(f'/admin/courses/{c.id}/edit', data=data)

    assert db.session.get(Course, c.id).t('title', lang='ru') == 'Курс-РУ'


# --- блоки програми ---------------------------------------------------------

def test_program_block_translation_saved_from_course_form(client, admin):
    _login(client, admin)
    c = _course()
    block = ProgramBlock(course_id=c.id, heading='Теорія',
                         items=['Забір крові'], sort_order=0)
    db.session.add(block)
    db.session.commit()
    bid = block.id
    item_key = source_key('Забір крові')

    html = client.get(f'/admin/courses/{c.id}/edit').get_data(as_text=True)
    assert f'trblk__{bid}__ru__heading' in html
    assert f'trblk__{bid}__ru__items__{item_key}' in html

    client.post(f'/admin/courses/{c.id}/edit', data=_post_data(
        c,
        **{f'block_0_id': str(bid),
           'block_0_heading': 'Теорія',
           'block_0_items': 'Забір крові',
           f'trblk__{bid}__ru__heading': 'Теория',
           f'trblk__{bid}__ru__items__{item_key}': 'Забор крови'},
    ))

    fetched = db.session.get(ProgramBlock, bid)
    assert fetched.t('heading', lang='ru') == 'Теория'
    assert fetched.t('items', lang='ru') == ['Забор крови']


# --- тарифи -----------------------------------------------------------------

def test_tariff_translation_saved_inline(client, admin):
    _login(client, admin)
    c = _course()
    tariff = CourseTariff(course_id=c.id, name='Практикум', price=6000,
                          description='Лекція наживо', sort_order=0,
                          is_active=True)
    db.session.add(tariff)
    db.session.commit()

    html = client.get(f'/admin/course-tariffs/{tariff.id}/edit').get_data(as_text=True)
    assert 'tr__ru__name' in html

    r = client.post(f'/admin/course-tariffs/{tariff.id}/edit', data={
        'name': 'Практикум', 'price': '6000', 'sort_order': '0',
        'description': 'Лекція наживо', 'is_active': 'y',
        'tr__ru__name': 'Практикум-РУ',
        'tr__ru__description': 'Лекция вживую',
    })
    assert r.status_code == 302
    fetched = db.session.get(CourseTariff, tariff.id)
    assert fetched.t('name', lang='ru') == 'Практикум-РУ'
    assert fetched.t('description', lang='ru') == 'Лекция вживую'


def test_trainer_form_does_not_wipe_regalia_translations(client, admin):
    """Форма тренера має 8 JSON-полів і не рендерить для них панелей.
    apply_inline_translations тепер бачить JSON-одиниці, тож важливо, щоб
    відсутність інпутів означала "не чіпати", а не "стерти"."""
    from app.models.trainer import Trainer

    _login(client, admin)
    t = Trainer(slug=f'tr-{uuid4().hex[:6]}', full_name='Тренер Тест',
                role='Лікар', skills=['Плазмотерапія'])
    db.session.add(t)
    db.session.commit()
    t.set_translation('ru', 'skills', {source_key('Плазмотерапія'): 'Плазмотерапия'})
    t.set_translation('ru', 'role', 'Врач')
    db.session.commit()

    r = client.post(f'/admin/trainers/{t.id}/edit', data={
        'full_name': 'Тренер Тест', 'slug': t.slug, 'role': 'Лікар',
        'tr__ru__role': 'Врач',
    })
    assert r.status_code in (200, 302)

    fetched = db.session.get(Trainer, t.id)
    assert fetched.t('skills', lang='ru') == ['Плазмотерапия']
    assert fetched.t('role', lang='ru') == 'Врач'


# --- індикатори -------------------------------------------------------------

def test_form_shows_coverage_counters(client, admin):
    _login(client, admin)
    c = _course(faq=[{'question': 'Q1?', 'answer': 'A1'}])
    c.set_translation('ru', 'title', 'Курс-РУ')
    db.session.commit()

    html = client.get(f'/admin/courses/{c.id}/edit').get_data(as_text=True)
    assert 'i18n-tabs__count' in html
    assert 'i18n-status__chip' in html


def test_create_form_works_without_object(client, admin):
    """Форма створення не має об'єкта -- індикатори й JSON-панелі мовчать."""
    _login(client, admin)
    html = client.get('/admin/courses/new').get_data(as_text=True)
    assert html.count('name="title"') == 1
    assert 'i18n-tabs' in html
    assert 'i18n-status__chip' not in html
