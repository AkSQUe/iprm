"""Підгляд за викликами методів db.session без сліду по собі.

`db.session` -- це scoped_session-проксі, а не сама сесія. `monkeypatch`
підставляє атрибут ПРОКСІ, а на відкаті ставить туди те, що прочитав
через getattr, тобто зв'язаний метод конкретної (уже закритої) сесії.
Проксі після такого назавжди носить чужий rollback, і наступний тест, що
робить те саме, бачить не свою заглушку. Ловилось це як падіння в
сусідньому файлі через сотні тестів -- шукати таке дорого.

Тут відновлюємо саме попередній СТАН проксі: не було власного атрибута --
його й не буде.
"""
from contextlib import contextmanager

_MISSING = object()


@contextmanager
def spy_session_method(name):
    """Замінити метод db.session заглушкою і віддати список її викликів.

    Використання:

        with spy_session_method('rollback') as calls:
            service_that_should_roll_back()
        assert calls
    """
    from app.extensions import db

    calls = []
    previous = db.session.__dict__.get(name, _MISSING)
    setattr(db.session, name, lambda *args, **kwargs: calls.append((args, kwargs)))
    try:
        yield calls
    finally:
        if previous is _MISSING:
            db.session.__dict__.pop(name, None)
        else:
            setattr(db.session, name, previous)
