"""Блок тренера на сторінці онлайн-курсу не має зникнути.

Партіал спільний із курсами і ходить по списку; у OnlineCourse список
дає властивість-перехідник (OnlineCourse.trainers -- 0 або 1 елемент).
Якби її не було, цикл по неіснуючому атрибуту рендерився б порожнечею --
без помилки й без ознак у логах. Це тест саме на це мовчазне зникнення.
"""
from decimal import Decimal
from uuid import uuid4

import pytest

from app.extensions import db
from app.models.online_course import OnlineCourse
from app.models.trainer import Trainer


@pytest.fixture(autouse=True)
def clean_catalog():
    """Каталог онлайн-курсів спільний для тестового набору (див.
    test_online_courses.py) -- прибираємо за собою, щоб не лишати сміття
    для сусідніх тестів каталогу."""
    yield
    OnlineCourse.query.delete()
    db.session.commit()


def _online_course_with_trainer():
    trainer = Trainer(
        full_name='Онлайн Тренер', slug=f'oc-trainer-{uuid4().hex[:8]}',
        role='Лектор', is_active=True,
    )
    db.session.add(trainer)
    db.session.flush()
    course = OnlineCourse(
        sintegrum_id=int(uuid4().int % 10_000_000),
        remote_name='Онлайн-курс з тренером',
        slug=f'oc-{uuid4().hex[:8]}',
        is_published=True,
        price=Decimal('1000'),
        access_url='https://multimededu.sintegrum.com/register/secret-token',
        trainer_id=trainer.id,
    )
    db.session.add(course)
    db.session.commit()
    return course, trainer


def test_online_course_page_shows_trainer_block(client):
    course, trainer = _online_course_with_trainer()

    resp = client.get(f'/online-courses/{course.slug}')
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)

    assert 'id="trainer-title"' in html
    assert trainer.full_name in html
    assert 'Ваш <span class="apple-gradient-text">тренер</span>' in html
