"""Наскрізь: переклад JSON-поля з хеш-ключем доходить до публічної сторінки.

Модельні тести перевіряють t(); тут перевіряється весь ланцюг
translations -> t() -> шаблон -> HTML, бо саме заради нього все й робиться.
"""
from uuid import uuid4

from app.extensions import db
from app.i18n import source_key
from app.models.course import Course


def _course_with_faq(slug):
    c = Course(
        title='Курс', slug=slug, is_active=True,
        faq=[{'question': 'Кому підійде?', 'answer': 'Лікарям.'},
             {'question': 'Скільки балів?', 'answer': '12 балів.'}],
    )
    db.session.add(c)
    db.session.commit()
    return c


def test_faq_translation_renders_and_falls_back(get_localized):
    slug = f'pub-{uuid4().hex[:6]}'
    c = _course_with_faq(slug)
    c.set_translation('ru', 'faq', {
        source_key('Кому підійде?'): 'Кому подойдёт?',
        source_key('Лікарям.'): 'Врачам.',
    })
    db.session.commit()

    ru = get_localized(f'/ru/courses/{slug}').get_data(as_text=True)
    assert 'Кому подойдёт?' in ru
    assert 'Врачам.' in ru
    # Неперекладений листок -> українська, а не діра в UI.
    assert 'Скільки балів?' in ru

    uk = get_localized(f'/courses/{slug}').get_data(as_text=True)
    assert 'Кому підійде?' in uk
    assert 'Кому подойдёт?' not in uk


def test_faq_translation_survives_reorder_on_public_page(get_localized):
    slug = f'pub-{uuid4().hex[:6]}'
    c = _course_with_faq(slug)
    c.set_translation('ru', 'faq', {source_key('Кому підійде?'): 'Кому подойдёт?'})
    db.session.commit()

    # Адмін додає нове питання на початок списку.
    c.faq = [{'question': 'Нове питання?', 'answer': 'Нова відповідь.'}] + c.faq
    db.session.commit()

    ru = get_localized(f'/ru/courses/{slug}').get_data(as_text=True)
    faq_html = ru[ru.find('id="faq-title"'):ru.find('id="request-title"')]
    # Переклад лишився на своєму питанні і не переїхав на нове.
    assert 'Кому подойдёт?' in faq_html
    assert faq_html.index('Нове питання?') < faq_html.index('Кому подойдёт?')
