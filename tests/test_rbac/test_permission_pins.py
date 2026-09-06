"""Пін чутливих ендпоінтів до конкретних прав.

Не дає тихо ослабити захист правки декоратора на в'юсі: якщо хтось
поміняє `@permission_required('integrations.keys')` на щось слабше,
цей тест впаде першим, ще до ручної перевірки в матриці /admin/access.
"""
from tests.support.rbac import make_user_with_role

PINS = {
    'admin.backup_restore': ('backup.restore',),
    'admin.backup_download': ('backup.export',),
    'admin.liqpay_save_keys': ('integrations.keys',),
    'admin.recaptcha_save_keys': ('integrations.keys',),
    'admin.google_oauth_save': ('integrations.keys',),
    'admin.apple_signin_save': ('integrations.keys',),
    'admin.meta_pixel_save': ('integrations.keys',),
    'admin.posthog_save': ('integrations.keys',),
    'admin.sintegrum_save': ('integrations.keys',),
    'admin.integrations_export': ('integrations.keys',),
    'admin.integrations_import_apply': ('integrations.keys',),
    'admin.settings': ('settings.manage',),
    'admin.access_matrix_toggle': ('access.manage',),
    'admin.access_matrix_bulk': ('access.manage',),
    'admin.access_role_new': ('access.manage',),
    'admin.access_role_delete': ('access.manage',),
    'admin.access_role_reset': ('access.manage',),
    'admin.user_roles_update': ('access.assign',),
    'admin.meta_leads_settings_save': ('meta_leads.settings',),
    'admin.users_export': ('users.export',),
    'admin.refund_form': ('registrations.refund',),
}


def test_sensitive_endpoints_pinned_to_expected_permission(app):
    for endpoint, perm in PINS.items():
        view = app.view_functions.get(endpoint)
        assert view is not None, f'ендпоінт не знайдено: {endpoint}'
        assert view._rbac_permissions == perm, (
            f'{endpoint}: очікував {perm}, отримав '
            f'{getattr(view, "_rbac_permissions", None)}'
        )


def test_viewer_reaches_list_but_not_create(app, client):
    with client.session_transaction() as s:
        s['_user_id'] = str(make_user_with_role('viewer').id)
    assert client.get('/admin/courses').status_code == 200
    assert client.get('/admin/courses/new').status_code == 403
