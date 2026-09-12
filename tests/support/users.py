"""Прибирання тестових користувачів.

Тестова БД (sqlite in-memory) спільна на всю pytest-сесію, а фікстури з
``db.session.commit()`` лишають рядки по собі. `/api/v1/participants`
віддає сторінку максимум у 200 рядків, і `test_api_v1_clients` шукає
свого користувача серед них -- кожен залишений тут акаунт витісняє з тієї
сторінки чужий тест, і той падає на ``StopIteration`` за кілометр звідси,
причому лише в повному прогоні.

SQLite не вмикає ``PRAGMA foreign_keys``, тож каскадів немає: identity й
медичний профіль видаляються явно.
"""
from app.extensions import db
from app.models.auth_identity import AuthIdentity
from app.models.medical_profile import MedicalProfile
from app.models.user import User


def wipe_users(*email_prefixes, domain='@test.com'):
    """Видалити користувачів, чий email починається на будь-який із префіксів."""
    if not email_prefixes:
        return
    stale = [
        row.id for row in User.query.filter(db.or_(*[
            User.email.like(f'{prefix}%{domain}') for prefix in email_prefixes
        ])).all()
    ]
    if stale:
        for model in (AuthIdentity, MedicalProfile):
            model.query.filter(model.user_id.in_(stale)).delete(
                synchronize_session=False)
        User.query.filter(User.id.in_(stale)).delete(synchronize_session=False)
    db.session.commit()
