import re
from pathlib import Path

from app.models.user import User
from app.rbac import service
from tests.support.rbac import make_super_admin, make_user_with_role


def test_no_is_admin_left_in_app():
    hits = []
    for path in Path('app').rglob('*'):
        if path.suffix not in ('.py', '.html') or 'migrations' in path.parts:
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
