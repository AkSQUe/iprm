"""Поведінка довідника спеціальностей, коли БД відповідає помилкою.

Запобіжник у catalog() задуманий, щоб не покласти сторінку. Без rollback
він її й кладе: на Postgres невдалий запит труїть транзакцію, і наступний
запит того ж реквесту гине з InFailedSqlTransaction. Відколи блок
«Цільова аудиторія» читає довідник, цей шлях проходить КОЖНА публічна
сторінка заходу, а не лише видача сертифіката.
"""
from flask import g

from app.services import specialties
from tests.support.session_spy import spy_session_method


def _break_query(monkeypatch):
    from app.models.specialty import Specialty

    class _Boom:
        def all(self):
            raise RuntimeError('relation "specialties" does not exist')

    monkeypatch.setattr(Specialty, 'query', _Boom())


def test_catalog_falls_back_to_empty_mapping(app, monkeypatch):
    with app.test_request_context():
        g.pop('_specialties_catalog', None)
        _break_query(monkeypatch)
        assert specialties.catalog() == {}


def test_catalog_rolls_back_the_poisoned_transaction(app, monkeypatch):
    with app.test_request_context():
        g.pop('_specialties_catalog', None)
        _break_query(monkeypatch)
        with spy_session_method('rollback') as calls:
            specialties.catalog()

    assert calls, 'без rollback наступний запит реквесту помер би'
