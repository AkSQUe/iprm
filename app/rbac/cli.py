"""flask rbac sync | status | grant | revoke."""
import click
from flask.cli import with_appcontext
from sqlalchemy import func

from app.extensions import db
from app.models.rbac import Permission, Role, UserRole
from . import registry, service


@click.group('rbac')
def rbac_group():
    """Ролі та права адмін-панелі."""


def _echo_sync(result):
    for label, key in (('додано прав', 'added'), ('видалено прав', 'removed'),
                       ('створено ролей', 'roles_created')):
        names = result[key]
        click.echo(f'{label}: {len(names)}' + (f" ({', '.join(names)})" if names else ''))


@rbac_group.command('sync')
@click.option('--dry-run', is_flag=True, help='Лише показати, що змінилося б.')
@with_appcontext
def rbac_sync(dry_run):
    """Права з реєстру -> БД; відсутні системні ролі -> створити.

    Право, якого більше немає в реєстрі, ВИДАЛЯЄТЬСЯ разом із видачами
    ролям. --dry-run показує це до того, як щось запишеться.
    """
    result = service.sync(dry_run=dry_run)
    if dry_run:
        click.echo('dry-run: нічого не записано')
    else:
        db.session.commit()
    _echo_sync(result)


@rbac_group.command('status')
@with_appcontext
def rbac_status():
    """Ролі з кількістю прав і носіїв; розбіжності реєстру й БД."""
    holders = dict(db.session.query(UserRole.role_id, func.count()).group_by(UserRole.role_id))
    total = len(registry.ALL_PERMISSION_NAMES)
    for role in Role.query.order_by(Role.sort_order, Role.display_name):
        count = total if role.name == registry.SUPER_ADMIN else len(role.permissions)
        click.echo(f'{role.name:<18} {role.display_name:<24} прав {count:>3}/{total}  носіїв {holders.get(role.id, 0)}')
    in_db = {p.name for p in Permission.query.all()}
    missing = sorted(registry.ALL_PERMISSION_NAMES - in_db)
    orphan = sorted(in_db - registry.ALL_PERMISSION_NAMES)
    click.echo(f'немає в БД: {", ".join(missing) or "-"}')
    click.echo(f'немає в реєстрі: {", ".join(orphan) or "-"}')


def _user_and_role(email, role_name):
    from app.models.user import User
    user = User.query.filter_by(email=email.strip().lower()).first()
    if user is None:
        raise click.ClickException(f'Користувача {email} не знайдено')
    role = Role.query.filter_by(name=role_name).first()
    if role is None:
        known = ', '.join(r.name for r in Role.query.order_by(Role.sort_order))
        raise click.ClickException(f'Ролі {role_name} немає. Є: {known}')
    return user, role


def _reassign(user, role_ids):
    try:
        service.assign_roles(user, role_ids, service.SystemActor())
        db.session.commit()
    except service.AccessError as exc:
        db.session.rollback()
        raise click.ClickException(str(exc))
    db.session.refresh(user)
    click.echo(f'{user.email}: ' + (', '.join(r.name for r in user.roles) or 'без ролей'))


@rbac_group.command('grant')
@click.argument('email')
@click.argument('role_name')
@with_appcontext
def rbac_grant(email, role_name):
    """Видати користувачу роль (бутстрап першого super_admin на свіжій базі)."""
    user, role = _user_and_role(email, role_name)
    _reassign(user, {r.id for r in user.roles} | {role.id})


@rbac_group.command('revoke')
@click.argument('email')
@click.argument('role_name')
@with_appcontext
def rbac_revoke(email, role_name):
    """Зняти з користувача роль. Запобіжники ті самі, що в адмінці."""
    user, role = _user_and_role(email, role_name)
    _reassign(user, {r.id for r in user.roles} - {role.id})
