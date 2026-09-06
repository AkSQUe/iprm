import re
from pathlib import Path

from app.models.user import User
from tests.support.rbac import make_super_admin, make_user_with_role

SCAN_ROOTS = ('app', 'deploy', 'tools', '.preview')
# snapshots/computed -- згенеровані html_snapshot/computed_snapshot (гігабайти,
# gitignored): без пропуску тест ходив би по них після кожного capture.
SKIP_DIR_PARTS = ('migrations', '__pycache__', 'snapshots', 'computed', 'node_modules')


def test_no_is_admin_left_in_app():
    hits = []
    for root in SCAN_ROOTS:
        root_path = Path(root)
        if not root_path.exists():
            continue
        for path in root_path.rglob('*'):
            if not path.is_file() or path.suffix == '.pyc':
                continue
            if path.suffix not in ('.py', '.html'):
                continue
            if any(part in SKIP_DIR_PARTS for part in path.parts):
                continue
            for n, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
                if re.search(r'\bis_admin\b', line):
                    hits.append(f'{path}:{n}')
    assert not hits, hits


def test_user_has_no_is_admin_column():
    assert not hasattr(User, 'is_admin')


def test_admin_alert_recipients_come_from_permission(app):
    from app.models.notification_rule import NotificationRule
    from app.services import notification_recipients
    with app.test_request_context():
        sa = make_super_admin()
        viewer = make_user_with_role('viewer')
        rule = NotificationRule.query.first()
        if rule is None:
            return  # правила сідяться окремим сідером; тоді перевіряє test_service
        rule.enabled = True
        rule.notify_admins = True
        emails = notification_recipients.resolve(rule.event_type)
        assert sa.email in emails
        assert viewer.email not in emails
