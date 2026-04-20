import logging
from flask import render_template, redirect, url_for, flash, request, jsonify
from flask_login import current_user
from sqlalchemy.orm import joinedload
from app.admin import admin_bp
from app.admin.decorators import admin_required
from app.admin.forms import EventForm
from app.extensions import db, limiter
from app.models.event import Event
from app.services import event_service
from app.services.event_service import InvalidStatusTransition

audit_logger = logging.getLogger('audit')
logger = logging.getLogger(__name__)


def _wants_json():
    """Клієнт очікує JSON (AJAX), а не redirect (noscript fallback)."""
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return True
    accept = request.accept_mimetypes
    return accept.best_match(['application/json', 'text/html']) == 'application/json'


def _populate_trainer_choices(form):
    from app.models.trainer import Trainer
    trainers = Trainer.query.filter_by(is_active=True).order_by(Trainer.full_name).all()
    form.trainer_id.choices = [(0, '--- Без тренера ---')] + [
        (t.id, t.full_name) for t in trainers
    ]


@admin_bp.route('/events')
@admin_required
def events_list():
    """Legacy redirect -- старий UI замінено на /admin/courses."""
    return redirect(url_for('admin.courses_list'), code=301)


@admin_bp.route('/events/legacy')
@admin_required
def events_list_legacy():
    """Прямий доступ до старого UI (перевірка legacy даних при потребі)."""
    reg_count = Event.with_registration_count()
    rows = db.session.query(Event, reg_count).options(
        joinedload(Event.trainer),
    ).order_by(Event.created_at.desc()).all()

    events = []
    for event, count in rows:
        event._cached_reg_count = count
        events.append(event)

    return render_template('admin/events.html', events=events)


@admin_bp.route('/events/new', methods=['GET', 'POST'])
@admin_required
def event_create():
    form = EventForm()
    _populate_trainer_choices(form)

    if form.validate_on_submit():
        slug = form.slug.data.strip() or event_service.generate_slug(form.title.data)[0]
        existing = Event.query.filter_by(slug=slug).first()
        if existing:
            flash('Захід з таким slug вже існує', 'error')
            return render_template('admin/event_edit.html', form=form, event=None)

        event = Event(slug=slug, created_by=current_user.id)
        event_service.populate_event_from_form(event, form)
        db.session.add(event)
        db.session.flush()
        event_service.save_program_blocks(event)

        try:
            db.session.commit()
            audit_logger.info('Admin %s created event %s (%s)', current_user.email, event.id, event.title)
            flash('Захід створено', 'success')
            return redirect(url_for('admin.dashboard'))
        except Exception:
            db.session.rollback()
            flash('Помилка при збереженні', 'error')

    return render_template('admin/event_edit.html', form=form, event=None)


@admin_bp.route('/events/<int:event_id>/edit', methods=['GET', 'POST'])
@admin_required
def event_edit(event_id):
    event = db.session.get(Event, event_id)
    if not event:
        flash('Захід не знайдено', 'error')
        return redirect(url_for('admin.dashboard'))

    form = EventForm(obj=event)
    _populate_trainer_choices(form)

    if request.method == 'GET':
        form.target_audience_text.data = event_service.list_to_lines(event.target_audience)
        form.tags_text.data = event_service.list_to_lines(event.tags)
        form.faq_text.data = event_service.faq_list_to_text(event.faq)

    if form.validate_on_submit():
        slug = form.slug.data.strip()
        dup = Event.query.filter(Event.slug == slug, Event.id != event_id).first()
        if dup:
            flash('Захід з таким slug вже існує', 'error')
            return render_template('admin/event_edit.html', form=form, event=event)

        event.slug = slug
        event_service.populate_event_from_form(event, form)
        event_service.save_program_blocks(event)

        try:
            db.session.commit()
            audit_logger.info('Admin %s updated event %s (%s)', current_user.email, event.id, event.title)
            flash('Захід оновлено', 'success')
            return redirect(url_for('admin.dashboard'))
        except Exception:
            db.session.rollback()
            flash('Помилка при збереженні', 'error')

    return render_template('admin/event_edit.html', form=form, event=event)


@admin_bp.route('/events/<int:event_id>/status', methods=['POST'])
@admin_required
@limiter.limit('60 per minute')
def event_status_update(event_id):
    wants_json = _wants_json()
    event = db.session.get(Event, event_id)
    if not event:
        if wants_json:
            return jsonify({'ok': False, 'error': 'Захід не знайдено'}), 404
        flash('Захід не знайдено', 'error')
        return redirect(url_for('admin.events_list'))

    new_status = (request.form.get('status') or '').strip()

    try:
        old_status, _ = event_service.change_status(event, new_status)
    except InvalidStatusTransition as exc:
        if wants_json:
            return jsonify({'ok': False, 'error': str(exc)}), 400
        flash(str(exc), 'error')
        return redirect(url_for('admin.events_list'))

    if old_status == new_status:
        if wants_json:
            return jsonify({
                'ok': True,
                'status': event.status,
                'status_label': event.status_label,
            })
        return redirect(url_for('admin.events_list'))

    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        logger.exception('Failed to update event %s status', event_id)
        if wants_json:
            return jsonify({'ok': False, 'error': 'Помилка при збереженні'}), 500
        flash('Помилка при збереженні', 'error')
        return redirect(url_for('admin.events_list'))

    audit_logger.info(
        'Admin %s changed event %s status: %s -> %s',
        current_user.email, event_id, old_status, new_status,
    )

    if wants_json:
        return jsonify({
            'ok': True,
            'status': event.status,
            'status_label': event.status_label,
        })
    flash(f'Статус змінено на "{event.status_label}"', 'success')
    return redirect(url_for('admin.events_list'))


@admin_bp.route('/events/<int:event_id>/delete', methods=['POST'])
@admin_required
def event_delete(event_id):
    event = db.session.get(Event, event_id)
    if event:
        title = event.title
        db.session.delete(event)
        try:
            db.session.commit()
            audit_logger.info('Admin %s deleted event %s (%s)', current_user.email, event_id, title)
            flash('Захід видалено', 'success')
        except Exception:
            db.session.rollback()
            flash('Помилка при видаленні', 'error')
    return redirect(url_for('admin.dashboard'))
