from app.rbac.cli import rbac_group


def test_rbac_sync_reports_counts(app):
    runner = app.test_cli_runner()
    result = runner.invoke(rbac_group, ['sync'])
    assert result.exit_code == 0, result.output
    assert 'додано прав: 0' in result.output
    assert 'створено ролей: 0' in result.output


def test_rbac_status_lists_roles(app):
    runner = app.test_cli_runner()
    result = runner.invoke(rbac_group, ['status'])
    assert result.exit_code == 0, result.output
    assert 'super_admin' in result.output
    assert 'viewer' in result.output


def test_can_globals_registered(app):
    assert 'can' in app.jinja_env.globals
    assert 'can_any' in app.jinja_env.globals


def test_rbac_sync_dry_run_writes_nothing(app):
    from app.extensions import db
    from app.models.rbac import Permission

    db.session.add(Permission(name='ghost.view', module='ghost'))
    db.session.flush()
    result = app.test_cli_runner().invoke(rbac_group, ['sync', '--dry-run'])
    assert result.exit_code == 0, result.output
    assert 'dry-run: нічого не записано' in result.output
    assert 'видалено прав: 1 (ghost.view)' in result.output
    assert Permission.query.filter_by(name='ghost.view').first() is not None
    db.session.delete(Permission.query.filter_by(name='ghost.view').one())
    db.session.flush()


def test_rbac_grant_and_revoke(app):
    from app.extensions import db
    from tests.support.rbac import make_user_with_role

    runner = app.test_cli_runner()
    user = make_user_with_role('viewer', email='cli-grant@test.com')
    result = runner.invoke(rbac_group, ['grant', 'CLI-Grant@test.com', 'manager'])
    assert result.exit_code == 0, result.output
    assert 'manager' in result.output and 'viewer' in result.output
    db.session.expire(user, ['roles'])
    assert {r.name for r in user.roles} == {'viewer', 'manager'}

    result = runner.invoke(rbac_group, ['revoke', 'cli-grant@test.com', 'viewer'])
    assert result.exit_code == 0, result.output
    db.session.expire(user, ['roles'])
    assert {r.name for r in user.roles} == {'manager'}

    result = runner.invoke(rbac_group, ['grant', 'nobody@test.com', 'manager'])
    assert result.exit_code != 0
    assert 'не знайдено' in result.output
    result = runner.invoke(rbac_group, ['grant', 'cli-grant@test.com', 'ghost'])
    assert result.exit_code != 0
    assert 'немає' in result.output


def test_rbac_revoke_last_super_admin_refused(app):
    from tests.support.rbac import make_super_admin
    from app.models.rbac import Role, UserRole
    from app.extensions import db

    sa = make_super_admin(email='cli-last-sa@test.com')
    sa_role = Role.query.filter_by(name='super_admin').one()
    for row in UserRole.query.filter_by(role_id=sa_role.id).all():
        if row.user_id != sa.id:
            db.session.delete(row)
    db.session.flush()
    result = app.test_cli_runner().invoke(rbac_group, ['revoke', 'cli-last-sa@test.com', 'super_admin'])
    assert result.exit_code != 0
    assert 'останній super_admin' in result.output
