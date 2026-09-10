"""Блок «Цільова аудиторія»: спеціальності підтягуються з довідника.

Перелік спеціальностей НЕ дублюється в target_audience, а рендериться з
bpr_specialty_codes на льоту. target_audience лишається додатковим описом,
який адміністратор пише руками.
"""
from decimal import Decimal
from uuid import uuid4

import pytest

from app.extensions import db
from app.models.course import Course
from app.models.online_course import OnlineCourse
from app.models.specialty import Specialty


@pytest.fixture
def rows():
    db.session.add_all([
        Specialty(code='aud-dermatovenerolohiia', name='Дерматовенерологія',
                  section='medical', sort_order=7),
        Specialty(code='aud-alerholohiia', name='Алергологія',
                  section='medical', sort_order=2),
        Specialty(code='aud-stara-nazva', name='Стара назва',
                  section='medical', sort_order=99, is_active=False),
    ])
    db.session.commit()


def _course(**kwargs):
    kwargs.setdefault('title', 'Курс для перевірки аудиторії')
    kwargs.setdefault('is_active', True)
    kwargs.setdefault('base_price', 6000)
    course = Course(slug=f'aud-{uuid4().hex[:8]}', **kwargs)
    db.session.add(course)
    db.session.commit()
    return course


def _audience_html(client, course, prefix=''):
    html = client.get(f'{prefix}/courses/{course.slug}').get_data(as_text=True)
    start = html.find('id="audience"')
    assert start != -1, 'секції «для кого» немає на сторінці'
    return html[start:html.find('</section>', start)]


def test_specialty_names_render_as_chips(client, rows):
    course = _course(bpr_specialty_codes=['aud-alerholohiia'],
                     target_audience=['Ті, хто вже працює з PRP'])
    block = _audience_html(client, course)
    assert 'iprm-audience-card__specialties' in block
    assert 'Алергологія' in block
    assert 'Ті, хто вже працює з PRP' in block


def test_chips_follow_nomenclature_order(client, rows):
    course = _course(bpr_specialty_codes=['aud-dermatovenerolohiia',
                                          'aud-alerholohiia'])
    block = _audience_html(client, course)
    assert block.find('Алергологія') < block.find('Дерматовенерологія')


def test_section_shows_without_manual_lines(client, rows):
    course = _course(bpr_specialty_codes=['aud-alerholohiia'],
                     target_audience=[])
    block = _audience_html(client, course)
    assert 'Алергологія' in block
    # Заголовок ручного чек-листа без ручних рядків не показується.
    assert 'Вам варто приєднатися' not in block


def test_section_hidden_without_specialties_and_lines(client, rows):
    course = _course(bpr_specialty_codes=[], target_audience=[])
    html = client.get(f'/courses/{course.slug}').get_data(as_text=True)
    assert 'id="audience"' not in html


def test_deactivated_specialty_still_renders(client, rows):
    course = _course(bpr_specialty_codes=['aud-stara-nazva'])
    assert 'Стара назва' in _audience_html(client, course)


def test_ru_page_uses_translated_specialty_name(client, rows):
    row = Specialty.query.filter_by(code='aud-alerholohiia').one()
    row.set_translation('ru', 'name', 'Аллергология')
    db.session.commit()
    course = _course(bpr_specialty_codes=['aud-alerholohiia'])
    block = _audience_html(client, course, prefix='/ru')
    assert 'Аллергология' in block


def test_online_course_audience_still_renders(client):
    item = OnlineCourse(
        sintegrum_id=int(uuid4().int % 10_000_000),
        remote_name='Онлайн-курс',
        slug=f'aud-ol-{uuid4().hex[:8]}',
        price=Decimal('4500'),
        access_url='https://example.com/register/abc',
        duration_hours=12,
        is_published=True,
        target_audience=['Лікарі-косметологи'],
    )
    db.session.add(item)
    db.session.commit()
    html = client.get(f'/online-courses/{item.slug}').get_data(as_text=True)
    assert 'Лікарі-косметологи' in html
    assert 'iprm-audience-card__specialties' not in html
