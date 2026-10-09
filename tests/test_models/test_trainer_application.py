"""Модель заявки кандидата в тренери."""
import pytest

from app.extensions import db
from app.models.trainer_application import TrainerApplication


def _app(**kw):
    data = dict(full_name='Іваненко Іван', phone='+380501112233',
                email='Cand@Example.com', specialty='Дерматологія',
                topic='PRP у трихології')
    data.update(kw)
    return TrainerApplication(**data)


def test_email_is_normalized_and_status_defaults_to_new(app):
    item = _app()
    db.session.add(item)
    db.session.flush()
    assert item.email == 'cand@example.com'
    assert item.status == 'new'
    assert item.status_label == 'Нова'


def test_invalid_email_rejected(app):
    with pytest.raises(ValueError):
        _app(email='not-an-email')


def test_unknown_status_rejected(app):
    item = _app()
    with pytest.raises(ValueError):
        item.status = 'archived'


def test_answer_rows_use_snapshot_labels(app):
    item = _app(answers=[
        {'key': 'plasma_years', 'label': 'Як давно ви використовуєте PRP- та плазмотерапію?',
         'value': '1_3'},
        {'key': 'directions', 'label': 'У яких напрямах застосовуєте плазму?',
         'value': 'Трихологія'},
        # Питання, якого вже немає в переліку: підпис і значення -- зі снапшоту.
        {'key': 'gone', 'label': 'Старе питання', 'value': 'так'},
    ])
    assert item.answer_rows == [
        ('Як давно ви використовуєте PRP- та плазмотерапію?', '1-3 роки'),
        ('У яких напрямах застосовуєте плазму?', 'Трихологія'),
        ('Старе питання', 'так'),
    ]
