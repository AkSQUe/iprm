"""Дані картки тренера для прев'ю блоку спікерів."""
from uuid import uuid4

import pytest

from tests.support.rbac import grant_role

from app.extensions import db
from app.models.trainer import Trainer
from app.models.user import User


@pytest.fixture
def admin():
    user = User.create_with_password(
        f'prev-{uuid4().hex[:6]}@test.com', 'password123',
        first_name='A', last_name='D', email_confirmed=True,
    )
    grant_role(user, 'super_admin')
    db.session.commit()
    yield user
    db.session.delete(user)
    db.session.commit()


def _login(client, user):
    with client.session_transaction() as session:
        session['_user_id'] = str(user.id)


def _trainer(**kwargs):
    t = Trainer(full_name='Тренер Т.', slug=uuid4().hex[:8], **kwargs)
    db.session.add(t)
    db.session.commit()
    return t


def test_reports_every_empty_field(client, admin):
    _login(client, admin)
    trainer = _trainer()  # ні bio, ні ролі, ні фото
    payload = client.get(f'/admin/trainers/{trainer.id}/card.json').get_json()
    assert sorted(payload['missing']) == ['bio', 'photo', 'role']
    assert payload['full_name'] == 'Тренер Т.'


def test_filled_text_fields_drop_out_of_missing(client, admin):
    _login(client, admin)
    trainer = _trainer(bio='Біографія', role='Лікар')
    payload = client.get(f'/admin/trainers/{trainer.id}/card.json').get_json()
    assert payload['missing'] == ['photo']


def test_whitespace_only_bio_counts_as_empty(client, admin):
    _login(client, admin)
    trainer = _trainer(bio='   ', role='Лікар')
    payload = client.get(f'/admin/trainers/{trainer.id}/card.json').get_json()
    assert 'bio' in payload['missing']


def test_unknown_trainer_is_404(client, admin):
    _login(client, admin)
    assert client.get('/admin/trainers/99999999/card.json').status_code == 404


def test_anonymous_is_not_served(client):
    trainer = _trainer()
    assert client.get(
        f'/admin/trainers/{trainer.id}/card.json'
    ).status_code in (302, 401, 403)
