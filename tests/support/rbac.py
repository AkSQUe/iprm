"""Хелпери RBAC для тестів: користувач із роллю замість колишнього прапорця адміна."""
from uuid import uuid4

from app.extensions import db
from app.models.rbac import Role, UserRole
from app.models.user import User


def grant_role(user, role_name):
    role = Role.query.filter_by(name=role_name).one()
    if not any(r.id == role.id for r in user.roles):
        db.session.add(UserRole(user_id=user.id, role_id=role.id))
        db.session.flush()
        db.session.expire(user, ['roles'])
    return user


def make_user_with_role(role_name, email=None, **kwargs):
    kwargs.setdefault('email_confirmed', True)
    user = User.create_with_password(
        email or f'{role_name}-{uuid4().hex[:6]}@test.com', 'password123', **kwargs,
    )
    db.session.flush()
    return grant_role(user, role_name)


def make_super_admin(email=None, **kwargs):
    return make_user_with_role('super_admin', email, **kwargs)


def switch_user(client, user):
    """Перелогінити тестовий клієнт на іншого користувача.

    Одного запису в сесію мало. `conftest.app` тримає піднятий app-context
    на весь тест, тож Flask не створює новий на кожен запит клієнта -- а `g`
    належить саме app-контексту. Flask-Login кладе туди `_login_user` при
    першому ж запиті й наступного разу бере користувача звідти, не заглядаючи
    в сесію: сторінка рендериться від імені ПОПЕРЕДНЬОГО користувача, хоча в
    сесії вже інший id. У проді цього не буває -- там кожен запит має свій
    app-контекст, -- тому симптом видно лише в тестах, і виглядає він як
    «перевірка прав не працює».
    """
    from flask import g

    g.pop('_login_user', None)
    with client.session_transaction() as session:
        session['_user_id'] = str(user.id)
    return user
