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
        form.populate_obj(site)
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

    return render_template('admin/settings.html', form=form)
