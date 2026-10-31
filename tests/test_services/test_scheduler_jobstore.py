"""Сховище джоб APScheduler ходить через спільний пул застосунку.

З `SQLAlchemyJobStore(url=...)` APScheduler будував у кожному gunicorn-воркері
ще один власний engine із власним пулом. На проді 31.10.2026 кожен воркер
тримав 11 зʼєднань: 10 у пулі застосунку й одне в пулі планувальника.
"""
from app.extensions import db
from app.services import scheduler_service


class _FakeScheduler:
    """Ловить конфіг замість справжнього запуску фонового потоку."""

    def __init__(self):
        self.jobstores = None
        self.started = False

    def configure(self, jobstores, **kwargs):
        self.jobstores = jobstores

    def add_job(self, *args, **kwargs):
        pass

    def start(self):
        self.started = True


def test_jobstore_reuses_app_engine(app, monkeypatch):
    fake = _FakeScheduler()
    monkeypatch.setattr(scheduler_service, 'scheduler', fake)
    monkeypatch.setattr(scheduler_service, '_initialized', False)
    monkeypatch.setitem(app.config, 'TESTING', False)

    scheduler_service.init_scheduler(app)

    assert fake.started
    assert fake.jobstores['default'].engine is db.engine
