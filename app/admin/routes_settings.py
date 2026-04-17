import logging

from flask import render_template, redirect, url_for, flash, request
from flask_login import current_user

from app.admin import admin_bp
from app.admin.decorators import admin_required
from app.admin.forms import SiteSettingsForm
from app.extensions import db
from app.models.site_settings import SiteSettings

audit_logger = logging.getLogger('audit')


@admin_bp.route('/settings', methods=['GET', 'POST'])
@admin_required
def settings():
    site = SiteSettings.get()
    form = SiteSettingsForm(obj=site) if request.method == 'GET' else SiteSettingsForm()

    if form.validate_on_submit():
        # Encrypted secrets: empty form value means "keep existing",
        # so populate_obj would wipe them. Handle manually.
        new_api_key = form.partner_api_key.data
        new_prefill_secret = form.partner_prefill_secret.data
        new_webhook_secret = form.partner_webhook_secret.data
        form.partner_api_key.data = ''
        form.partner_prefill_secret.data = ''
        form.partner_webhook_secret.data = ''

        form.populate_obj(site)

        if new_api_key and new_api_key.strip():
            site.partner_api_key = new_api_key.strip()
        if new_prefill_secret and new_prefill_secret.strip():
            site.partner_prefill_secret = new_prefill_secret.strip()
        if new_webhook_secret and new_webhook_secret.strip():
            site.partner_webhook_secret = new_webhook_secret.strip()

        try:
            db.session.commit()
            audit_logger.info(
                'Admin %s updated site settings', current_user.email,
            )
            flash('Налаштування збережено', 'success')
        except Exception:
            audit_logger.exception('Failed to update site settings')
            db.session.rollback()
            flash('Помилка при збереженні', 'error')
        return redirect(url_for('admin.settings'))

    return render_template('admin/settings.html', form=form, site=site)
