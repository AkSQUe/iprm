"""Замок фонових джоб (`scheduler_service._job_lock`).

pg_try_advisory_lock сесійний -- належить зʼєднанню. Коли його брали через
db.session, перший commit у тілі джоби віддавав зʼєднання в пул, unlock ішов
іншим, і замок висів до pool_recycle, а джоба мовчки пропускалась. Тому тут
перевіряється саме те, що lock і unlock йдуть ОДНИМ зʼєднанням, незалежно від
того, що робить db.session усередині.

SQLite не має advisory-функцій, тож зʼєднання підроблене.
"""
import pytest

from app.extensions import db
from app.services import scheduler_service


class FakeResult:
    def __init__(self, value):
        self._value = value

    def scalar(self):
        return self._value


class FakeConnection:
    def __init__(self, lock_free=True, unlock_error=False):
        self.lock_free = lock_free
        self.unlock_error = unlock_error
        self.statements = []
        self.closed = False
        self.invalidated = False

    def execute(self, clause, params=None):
        sql = str(clause)
        self.statements.append(sql)
        if 'pg_advisory_unlock' in sql:
            if self.unlock_error:
                raise RuntimeError('connection lost')
            return FakeResult(True)
        return FakeResult(self.lock_free)

    def commit(self):
        pass

    def invalidate(self):
        self.invalidated = True

    def close(self):
        self.closed = True


@pytest.fixture
def fake_conn(monkeypatch):
    holder = {}

    def install(**kwargs):
        conn = FakeConnection(**kwargs)
        holder['conn'] = conn
        monkeypatch.setattr(scheduler_service, '_lock_connection', lambda: conn)
        return conn

    return install


def test_lock_and_unlock_on_same_connection_despite_session_commit(app, fake_conn):
    conn = fake_conn()
    with scheduler_service._job_lock('some_job') as got:
        assert got is True
        # Тіло джоби комітить сесію -- саме це й розводило lock і unlock.
        db.session.commit()
    assert any('pg_try_advisory_lock' in s for s in conn.statements)
    assert any('pg_advisory_unlock' in s for s in conn.statements)
    assert conn.closed


def test_busy_lock_yields_false_and_does_not_unlock(app, fake_conn):
    conn = fake_conn(lock_free=False)
    with scheduler_service._job_lock('some_job') as got:
        assert got is False
    assert not any('pg_advisory_unlock' in s for s in conn.statements)
    assert conn.closed


def test_unlock_after_job_exception(app, fake_conn):
    conn = fake_conn()
    with pytest.raises(ValueError):
        with scheduler_service._job_lock('some_job'):
            raise ValueError('job failed')
    assert any('pg_advisory_unlock' in s for s in conn.statements)
    assert conn.closed


def test_failed_unlock_invalidates_connection(app, fake_conn):
    """Зʼєднання з незнятим замком не повертається в пул: invalidate закриває
    його, і PostgreSQL звільняє замок разом із сесією."""
    conn = fake_conn(unlock_error=True)
    with scheduler_service._job_lock('some_job'):
        pass
    assert conn.invalidated
    assert conn.closed
