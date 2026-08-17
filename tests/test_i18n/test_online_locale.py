"""Локалізація публічного розділу онлайн-курсів.

Курси продаються трьома мовами, тож блюпринт мусить мати мовні префікси, а
нові рядки -- справжні переклади. Без цієї перевірки каталог легко лишити з
порожніми msgstr: сторінка тоді просто показує українську, і помітять це
нескоро.
"""
from decimal import Decimal
from uuid import uuid4

import pytest

from app.extensions import db
from app.models.online_course import OnlineCourse


@pytest.fixture
def course(app):
    OnlineCourse.query.delete()
    db.session.commit()
    item = OnlineCourse(
        sintegrum_id=int(uuid4().int % 10_000_000),
        remote_name='Плазмотерапія в косметології',
        slug=f'ol-{uuid4().hex[:8]}',
        price=Decimal('4500'),
        access_url='https://multimededu.sintegrum.com/register/abc',
        duration_hours=12,
        is_published=True,
    )
    db.session.add(item)
    db.session.commit()
    yield item
    OnlineCourse.query.delete()
    db.session.commit()


def test_urls_have_language_prefixes(client, course):
    for prefix in ('', '/ru', '/en'):
        assert client.get(f'{prefix}/online-courses/').status_code == 200, prefix
        assert client.get(
            f'{prefix}/online-courses/{course.slug}'
        ).status_code == 200, prefix


def test_catalog_subtitle_is_translated(get_localized, course):
    uk = get_localized('/online-courses/').get_data(as_text=True)
    ru = get_localized('/ru/online-courses/').get_data(as_text=True)
    en = get_localized('/en/online-courses/').get_data(as_text=True)

    assert 'у власному темпі' in uk
    assert 'в своём темпе' in ru
    assert 'at your own pace' in en


def test_detail_buy_block_is_translated(get_localized, course):
    ru = get_localized(f'/ru/online-courses/{course.slug}').get_data(as_text=True)
    en = get_localized(f'/en/online-courses/{course.slug}').get_data(as_text=True)

    assert 'Доступ к учебной платформе' in ru
    assert 'Access to the learning platform' in en


def test_detail_facts_are_translated(get_localized, course):
    ru = get_localized(f'/ru/online-courses/{course.slug}').get_data(as_text=True)
    en = get_localized(f'/en/online-courses/{course.slug}').get_data(as_text=True)

    assert 'Онлайн, в своём темпе' in ru
    assert 'Online, at your own pace' in en


def test_empty_state_is_translated(get_localized, app):
    OnlineCourse.query.delete()
    db.session.commit()

    ru = get_localized('/ru/online-courses/').get_data(as_text=True)
    en = get_localized('/en/online-courses/').get_data(as_text=True)

    assert 'Онлайн-курсы скоро появятся' in ru
    assert 'coming soon' in en


def test_online_messages_have_translations(app):
    """Рядки розділу присутні в каталогах і не порожні."""
    from babel.messages.pofile import read_po

    watched = {
        'Онлайн, у власному темпі',
        'Доступ до навчальної платформи',
        'Навчання у зручний час',
        'Посилання надійде на пошту після оплати',
        'Навчання у власному темпі: доступ відкривається одразу після оплати',
        'год',
    }
    for lang in ('ru', 'en'):
        path = f'app/translations/{lang}/LC_MESSAGES/messages.po'
        with open(path, encoding='utf-8') as fh:
            catalog = read_po(fh)
        for msgid in watched:
            message = catalog.get(msgid)
            assert message is not None, f'{lang}: немає msgid {msgid!r}'
            assert message.string, f'{lang}: немає перекладу для {msgid!r}'
