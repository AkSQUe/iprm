"""Програма курсу: нумерований акордеон замість сітки карток.

Двоколонкова сітка розкладала блоки 1-3-5 ліворуч і 2-4 праворуч, тож
послідовність читалась ламано, а різна висота карток лишала порожні зони.
Тепер блок один за одним, і розкритий рівно один.

Партіал спільний для очного й онлайн-курсу -- перевіряємо обидві сторінки:
одна регресія в партіалі ламає дві сторінки.
"""
import re

from decimal import Decimal

from app.extensions import db
from app.models.course import Course
from app.models.online_course import OnlineCourse
from app.models.program_block import ProgramBlock
from app.models.trainer import Trainer
from app.services import trainer_links


HEADINGS = ['Основи', 'Критичні етапи', 'Клінічне застосування']


def _trainer(slug):
    trainer = Trainer(slug=slug, full_name='Тренер Тест', role='Лікар')
    db.session.add(trainer)
    db.session.flush()
    return trainer


def _blocks(**owner):
    for index, heading in enumerate(HEADINGS):
        db.session.add(ProgramBlock(heading=heading, items=[f'Пункт {index}'],
                                    sort_order=index, **owner))


def _course(slug='program-accordion'):
    course = Course(slug=slug, title='Курс програми', is_active=True,
                    description='<p>Опис</p>')
    db.session.add(course)
    db.session.flush()
    trainer_links.set_trainers(course, [_trainer(f'{slug}-t').id])
    _blocks(course_id=course.id)
    db.session.commit()
    return course


def _online(slug='program-accordion-online'):
    course = OnlineCourse(sintegrum_id=abs(hash(slug)) % 100000,
                          remote_name='Remote', slug=slug, is_published=True,
                          price=Decimal('2500'), trainer_id=_trainer(f'{slug}-t').id)
    db.session.add(course)
    db.session.flush()
    _blocks(online_course_id=course.id)
    db.session.commit()
    return course


def _program(html):
    """Розмітка секції програми -- від контейнера до кінця секції."""
    start = html.find('class="iprm-program ')
    assert start != -1, 'контейнера програми немає на сторінці'
    return html[start:html.find('</section>', start)]


def _triggers(program):
    return re.findall(r'<button[^>]*class="iprm-program__trigger"[^>]*>', program)


def test_every_block_becomes_a_trigger_and_a_panel(client):
    program = _program(client.get(f'/courses/{_course().slug}').get_data(as_text=True))
    assert len(_triggers(program)) == len(HEADINGS)
    assert program.count('class="iprm-program__panel"') == len(HEADINGS)
    for heading in HEADINGS:
        assert heading in program


def test_trigger_points_at_its_own_panel(client):
    """aria-controls мусить вести на id, який на сторінці реально є."""
    program = _program(client.get(f'/courses/{_course('program-aria').slug}')
                       .get_data(as_text=True))
    controlled = re.findall(r'aria-controls="([^"]+)"', program)
    assert len(controlled) == len(HEADINGS)
    assert len(set(controlled)) == len(HEADINGS), 'id панелей повторюються'
    for panel_id in controlled:
        assert f'id="{panel_id}"' in program


def test_panel_names_itself_by_its_trigger(client):
    program = _program(client.get(f'/courses/{_course('program-region').slug}')
                       .get_data(as_text=True))
    labelled = re.findall(r'aria-labelledby="(iprm-program-head[^"]+)"', program)
    assert len(labelled) == len(HEADINGS)
    for head_id in labelled:
        assert f'id="{head_id}"' in program
    assert program.count('role="region"') == len(HEADINGS)


def test_only_the_first_block_starts_open(client):
    """Права колонка десктопа не має стартувати порожньою."""
    program = _program(client.get(f'/courses/{_course('program-open').slug}')
                       .get_data(as_text=True))
    expanded = re.findall(r'aria-expanded="(true|false)"', program)
    assert expanded == ['true'] + ['false'] * (len(HEADINGS) - 1)


def test_card_grid_is_gone(client):
    """Сторож проти повернення сітки карток."""
    program = _program(client.get(f'/courses/{_course('program-nogrid').slug}')
                       .get_data(as_text=True))
    assert 'iprm-program__block' not in program


def test_online_course_gets_the_same_accordion(client):
    program = _program(client.get(f'/online-courses/{_online().slug}')
                       .get_data(as_text=True))
    assert len(_triggers(program)) == len(HEADINGS)
    assert program.count('aria-expanded="true"') == 1
