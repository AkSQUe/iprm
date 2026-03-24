from flask import render_template, redirect, url_for, flash, request
from flask_login import current_user
from sqlalchemy.orm import joinedload
from app.admin import admin_bp
from app.admin.decorators import admin_required
from app.admin.forms import EventForm
from app.extensions import db
from app.models.event import Event
from app.models.program_block import ProgramBlock
from app.utils import slugify


def _populate_trainer_choices(form):
    from app.models.trainer import Trainer
    trainers = Trainer.query.filter_by(is_active=True).order_by(Trainer.full_name).all()
    form.trainer_id.choices = [(0, '--- Без тренера ---')] + [
        (t.id, t.full_name) for t in trainers
    ]


def _lines_to_list(text):
    if not text:
        return []
    return [line.strip() for line in text.strip().splitlines() if line.strip()]


def _list_to_lines(items):
    if not items:
        return ''
    return '\n'.join(items)


def _populate_event_from_form(event, form):
    event.title = form.title.data.strip()
    event.subtitle = form.subtitle.data
    event.short_description = form.short_description.data
    event.description = form.description.data
    event.event_type = form.event_type.data
    event.event_format = form.event_format.data
    event.status = form.status.data
    event.start_date = form.start_date.data
    event.end_date = form.end_date.data
    event.max_participants = form.max_participants.data
    event.price = form.price.data or 0
    event.location = form.location.data
    event.online_link = form.online_link.data
    event.hero_image = form.hero_image.data
    event.card_image = form.card_image.data
    event.cpd_points = form.cpd_points.data
    event.trainer_id = form.trainer_id.data or None
    event.target_audience = _lines_to_list(form.target_audience_text.data)
    event.tags = _lines_to_list(form.tags_text.data)
    event.speaker_info = form.speaker_info.data
    event.agenda = form.agenda.data
    event.is_featured = form.is_featured.data


def _save_program_blocks(event):
    existing_ids = {b.id for b in event.program_blocks}
    seen_ids = set()

    idx = 0
    while True:
        heading = request.form.get(f'block_{idx}_heading', '').strip()
        if not heading and f'block_{idx}_heading' not in request.form:
            break
        if heading:
            block_id_str = request.form.get(f'block_{idx}_id', '')
            items_text = request.form.get(f'block_{idx}_items', '')
            items = _lines_to_list(items_text)
            block_id = int(block_id_str) if block_id_str else None

            if block_id and block_id in existing_ids:
                block = db.session.get(ProgramBlock, block_id)
                block.heading = heading
                block.items = items
                block.sort_order = idx
                seen_ids.add(block_id)
            else:
                block = ProgramBlock(
                    event=event,
                    heading=heading,
                    items=items,
                    sort_order=idx,
                )
                db.session.add(block)
        idx += 1

    for old_id in existing_ids - seen_ids:
        old_block = db.session.get(ProgramBlock, old_id)
        if old_block:
            db.session.delete(old_block)


@admin_bp.route('/events')
@admin_required
def events_list():
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
        slug = form.slug.data.strip() or slugify(form.title.data)
        if Event.query.filter_by(slug=slug).first():
            flash('Захід з таким slug вже існує', 'error')
            return render_template('admin/event_edit.html', form=form, event=None)

        event = Event(slug=slug, created_by=current_user.id)
        _populate_event_from_form(event, form)
        db.session.add(event)
        db.session.flush()
        _save_program_blocks(event)

        try:
            db.session.commit()
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
        form.target_audience_text.data = _list_to_lines(event.target_audience)
        form.tags_text.data = _list_to_lines(event.tags)

    if form.validate_on_submit():
        slug = form.slug.data.strip()
        existing = Event.query.filter(Event.slug == slug, Event.id != event_id).first()
        if existing:
            flash('Захід з таким slug вже існує', 'error')
            return render_template('admin/event_edit.html', form=form, event=event)

        event.slug = slug
        _populate_event_from_form(event, form)
        _save_program_blocks(event)

        try:
            db.session.commit()
            flash('Захід оновлено', 'success')
            return redirect(url_for('admin.dashboard'))
        except Exception:
            db.session.rollback()
            flash('Помилка при збереженні', 'error')

    return render_template('admin/event_edit.html', form=form, event=event)


@admin_bp.route('/events/<int:event_id>/delete', methods=['POST'])
@admin_required
def event_delete(event_id):
    event = db.session.get(Event, event_id)
    if event:
        db.session.delete(event)
        try:
            db.session.commit()
            flash('Захід видалено', 'success')
        except Exception:
            db.session.rollback()
            flash('Помилка при видаленні', 'error')
    return redirect(url_for('admin.dashboard'))
