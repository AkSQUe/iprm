"""Публічний блок спікерів: сторінка заходу з кількома тренерами.

Партіал (_course_trainer.html) досі рендерив рівно одного тренера
(`{% if course.trainer %}`), тож другий і третій спікер, збережені в
БД (Задача 1-6), ніколи не потрапляли на публічну сторінку -- лише в
адмінський превʼю. Тут перевіряється, що цикл справді показує ВСІХ
тренерів у збереженому порядку, а не тільки головного лектора.
"""
from uuid import uuid4

import pytest

from app.extensions import db
from app.models.course import Course
from app.models.trainer import Trainer
from app.services import trainer_links


def _trainer(name, **kwargs):
    trainer = Trainer(
        full_name=name, slug=f'spk-{uuid4().hex[:8]}', is_active=True, **kwargs,
    )
    db.session.add(trainer)
    db.session.flush()
    return trainer


def _course(trainers):
    course = Course(
        title=f'Курс {uuid4().hex[:4]}', slug=f'crs-{uuid4().hex[:8]}',
        is_active=True, description='<p>Опис</p>', short_description='Короткий опис',
    )
    db.session.add(course)
    db.session.flush()
    trainer_links.set_trainers(course, [t.id for t in trainers])
    db.session.commit()
    return course


def test_two_trainers_render_two_cards_in_saved_order(client):
    """Обидва спікери мають зʼявитись на сторінці, у порядку збереження.

    Хибна реалізація, яка й далі бере лише course.trainer (перший),
    покаже картку Андрієнко і НЕ покаже Богданенко -- тест мусить це
    ловити.
    """
    first = _trainer('Андрієнко Перший', role='Лікар-дерматолог')
    second = _trainer('Богданенко Другий', role='Косметолог')
    course = _course([first, second])

    resp = client.get(f'/courses/{course.slug}')
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)

    assert first.full_name in html
    assert second.full_name in html
    # Порядок у розмітці -- саме порядок збереження (перший лектор раніше).
    assert html.index(first.full_name) < html.index(second.full_name)


def test_two_trainers_get_plural_heading(client):
    first = _trainer('Валенко Валентин')
    second = _trainer('Гриценко Григорій')
    course = _course([first, second])

    html = client.get(f'/courses/{course.slug}').get_data(as_text=True)
    assert 'тренери</span>' in html
    assert 'Ваш <span class="apple-gradient-text">тренер</span>' not in html


def test_two_trainers_wrapped_in_grid(client):
    """Обгортка сітки з'являється лише коли тренерів більше одного."""
    first = _trainer('Дзюба Дмитро')
    second = _trainer('Єременко Євген')
    course = _course([first, second])

    html = client.get(f'/courses/{course.slug}').get_data(as_text=True)
    assert 'iprm-trainer-grid' in html


def test_single_trainer_has_no_grid_and_singular_heading(client):
    """Регресія: один тренер має рендеритись так само, як і до задачі 7 --
    без обгортки сітки й з однинним заголовком. Хибна реалізація, яка
    завжди обгортає картки в iprm-trainer-grid, провалить цю перевірку.
    """
    only = _trainer('Одинокий Тренер', role='Викладач')
    course = _course([only])

    html = client.get(f'/courses/{course.slug}').get_data(as_text=True)
    assert 'iprm-trainer-grid' not in html
    assert 'Ваш <span class="apple-gradient-text">тренер</span>' in html
    assert 'тренери</span>' not in html


def test_each_speaker_gets_own_tags_and_highlights(client):
    """tags / highlights рахуються ПОКОМПЛЕКТНО: один спікер із тегами,
    інший -- без, і кожен показує лише своє. Хибна реалізація, що рахує
    is_rich/tags один раз на весь список, або показала б теги обом, або
    не показала б жодному.
    """
    rich = _trainer(
        'Жовтневий Жора', role='Хірург',
        skills=['Дерматологія', 'Плазмотерапія'],
        highlights=[{'value': '10 років', 'label': 'досвіду'}],
    )
    plain = _trainer('Зайцева Зоя', role='Асистент')
    course = _course([rich, plain])

    html = client.get(f'/courses/{course.slug}').get_data(as_text=True)
    assert 'Дерматологія' in html
    assert '10 років' in html
    # Клас "rich" картки не повинен зʼявитись у другого спікера без тегів.
    body = html
    # Рахуємо кількість карток --rich: має бути рівно одна.
    assert body.count('iprm-trainer-block--rich') == 1
