"""flask rbac sync | status."""
import click
from flask.cli import with_appcontext

from app.extensions import db
from . import registry, service


@click.group('rbac')
def rbac_group():
    """Ролі та права адмін-панелі."""


@rbac_group.command('sync')
@with_appcontext
def rbac_sync():
    """Права з реєстру -> БД; відсутні системні ролі -> створити."""
    result = service.sync()
    db.session.commit()
    click.echo(f"додано прав: {len(result['added'])}"
               + (f" ({', '.join(result['added'])})" if result['added'] else ''))
    click.echo(f"видалено прав: {len(result['removed'])}"
               + (f" ({', '.join(result['removed'])})" if result['removed'] else ''))
    click.echo(f"створено ролей: {len(result['roles_created'])}"
               + (f" ({', '.join(result['roles_created'])})" if result['roles_created'] else ''))


@rbac_group.command('status')
@with_appcontext
def rbac_status():
    """Ролі з кількістю прав і носіїв; розбіжності реєстру й БД."""
    from app.models.rbac import Permission, Role, UserRole
    from sqlalchemy import func

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
