"""Admin: заявки кандидатів у тренери (сторінка /trainers/join)."""
import logging

from flask import abort, flash, redirect, render_template, request, url_for
from flask_login import current_user

from app.admin import _listing, admin_bp
from app.admin.routes_trainers import _audit_account_link
from app.extensions import db
from app.models.trainer_application import TrainerApplication
from app.rbac import permission_required
from app.services import trainer_recruitment

audit_logger = logging.getLogger('audit')


def _filters():
    return {
        'q': _listing.text_arg('q'),
        'status': _listing.choice_arg('status', dict(TrainerApplication.STATUSES)),
        'date_from': _listing.date_arg('date_from'),
        'date_to': _listing.date_arg('date_to'),
        'per_page': _listing.choice_arg('per_page', _listing.PER_PAGE_CHOICES),
    }


def _query(filters):
    query = _listing.apply_search(TrainerApplication.query, filters['q'], [
        TrainerApplication.full_name, TrainerApplication.email,
        TrainerApplication.phone, TrainerApplication.specialty,
        TrainerApplication.topic, TrainerApplication.admin_notes,
    ])
    if filters['status']:
        query = query.filter(TrainerApplication.status == filters['status'])
    query = _listing.apply_date_range(
        query, TrainerApplication.created_at, filters['date_from'], filters['date_to'],
    )
    return query.order_by(TrainerApplication.created_at.desc())


@admin_bp.route('/trainer-applications')
@permission_required('trainer_applications.view')
def trainer_applications_list():
    filters = _filters()
    pagination = _query(filters).paginate(
        page=_listing.page_arg(), per_page=_listing.per_page_arg(), error_out=False,
    )
    filter_args = _listing.filter_args(filters)
    return render_template(
        'admin/trainer_applications.html',
        applications=pagination.items,
        pagination=pagination,
        per_page_options=_listing.PER_PAGE_OPTIONS,
        filters=filters,
        filter_args=filter_args,
        status_options=TrainerApplication.STATUSES,
        new_count=TrainerApplication.query.filter_by(status='new').count(),
    )


def _get_or_404(application_id):
    item = db.session.get(TrainerApplication, application_id)
    if item is None:
        abort(404)
    return item


@admin_bp.route('/trainer-applications/<int:application_id>')
@permission_required('trainer_applications.view')
def trainer_application_detail(application_id):
    return render_template(
        'admin/trainer_application_detail.html',
        application=_get_or_404(application_id),
        status_options=TrainerApplication.STATUSES,
    )


def _back(application_id):
    return redirect(url_for('admin.trainer_application_detail', application_id=application_id))


@admin_bp.route('/trainer-applications/<int:application_id>/update', methods=['POST'])
@permission_required('trainer_applications.manage')
def trainer_application_update(application_id):
    item = _get_or_404(application_id)
    new_status = request.form.get('status', '')
    if new_status not in {code for code, _ in TrainerApplication.STATUSES}:
        flash('Невідомий статус', 'error')
        return _back(item.id)
    item.status = new_status
    item.admin_notes = (request.form.get('admin_notes') or '').strip()[:4000] or None
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        flash('Не вдалося зберегти заявку', 'error')
        return _back(item.id)
    audit_logger.info('Admin %s updated TrainerApplication #%s -> %s',
                      current_user.email, item.id, new_status)
    flash('Заявку оновлено', 'success')
    return _back(item.id)


# permission_required приймає БУДЬ-ЯКЕ з перелічених прав, а тут потрібні обидва
# (заявки і створення тренера), тому декоратори складені стопкою.
@admin_bp.route('/trainer-applications/<int:application_id>/create-trainer', methods=['POST'])
@permission_required('trainer_applications.manage')
@permission_required('trainers.manage')
def trainer_application_create_trainer(application_id):
    item = _get_or_404(application_id)
    if item.status != 'approved':
        flash('Створити тренера можна лише з погодженої заявки', 'error')
        return _back(item.id)
    try:
        trainer, warning = trainer_recruitment.create_trainer(item)
        db.session.commit()
    except trainer_recruitment.AlreadyConverted:
        db.session.rollback()
        flash('Із цієї заявки тренера вже створено', 'warning')
        return _back(item.id)
    except Exception:
        db.session.rollback()
        audit_logger.exception('TrainerApplication #%s: create_trainer failed', item.id)
        flash('Не вдалося створити тренера', 'error')
        return _back(item.id)
    audit_logger.info('Admin %s created trainer %s from TrainerApplication #%s',
                      current_user.email, trainer.id, item.id)
    # Автоприв'язка відкриває людині кабінет так само, як ручна в картці
    # тренера, тож і в журналі вона має лишити той самий рядок.
    _audit_account_link(trainer, None)
    if warning:
        flash(warning, 'warning')
    flash('Тренера створено неактивним: заповніть картку й увімкніть показ на сайті', 'success')
    return redirect(url_for('admin.trainer_edit', trainer_id=trainer.id))
