"""Поведінка служби довідника, коли БД відповідає помилкою.

Запобіжник у directory() задуманий, щоб не покласти публічну сторінку.
Без rollback він її й кладе: на Postgres невдалий запит труїть
транзакцію, і наступний запит того ж реквесту гине з
InFailedSqlTransaction.
"""
from app.services import event_types
from tests.support.session_spy import spy_session_method


def _break_query(monkeypatch):
    """Змусити читання довідника впасти так, як падає недоступна таблиця."""
    from app.models.event_type import EventType

    class _Boom:
        def order_by(self, *_args, **_kwargs):
            raise RuntimeError('relation "event_types" does not exist')

    monkeypatch.setattr(EventType, 'query', _Boom())


def test_directory_falls_back_to_empty_mapping(app, monkeypatch):
    with app.test_request_context():
        event_types.reset_cache()
        _break_query(monkeypatch)
        assert event_types.directory() == {}


def test_directory_rolls_back_the_poisoned_transaction(app, monkeypatch):
    with app.test_request_context():
        event_types.reset_cache()
        _break_query(monkeypatch)
        with spy_session_method('rollback') as calls:
            event_types.directory()

    assert calls, 'без rollback наступний запит реквесту помер би'


def test_label_returns_raw_code_when_directory_is_down(app, monkeypatch):
    with app.test_request_context():
        event_types.reset_cache()
        _break_query(monkeypatch)
        assert event_types.label('seminar') == 'seminar'


def test_case_and_label_agree_on_unknown_code(app):
    """Дві сусідні функції не мають давати різні відповіді на одне питання."""
    with app.test_request_context():
        event_types.reset_cache()
        assert event_types.label('no_such_code') == 'no_such_code'
        assert event_types.accusative('no_such_code') == 'no_such_code'
        assert event_types.genitive('no_such_code') == 'no_such_code'
