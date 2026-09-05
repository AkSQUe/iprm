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
