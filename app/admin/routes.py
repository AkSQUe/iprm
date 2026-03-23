import re
from flask import render_template, redirect, url_for, flash, request
from flask_login import current_user
from app.admin import admin_bp
from app.admin.decorators import admin_required
from app.admin.forms import EventForm
from app.extensions import db
from app.models.event import Event


def _slugify(text):
    text = text.lower().strip()
    text = re.sub(r'[^\w\s-]', '', text)
    text = re.sub(r'[\s_]+', '-', text)
    text = re.sub(r'-+', '-', text)
    return text[:200]


@admin_bp.route('/')
@admin_required
def dashboard():
    events = Event.query.order_by(Event.created_at.desc()).all()
    return render_template('admin/dashboard.html', events=events)


@admin_bp.route('/events/new', methods=['GET', 'POST'])
@admin_required
def event_create():
    form = EventForm()
    if form.validate_on_submit():
        slug = form.slug.data.strip() or _slugify(form.title.data)
        if Event.query.filter_by(slug=slug).first():
            flash('Захід з таким slug вже існує', 'error')
            return render_template('admin/event_edit.html', form=form, event=None)

        event = Event(
            title=form.title.data.strip(),
            slug=slug,
            short_description=form.short_description.data,
            description=form.description.data,
            event_type=form.event_type.data,
            format=form.format.data,
            status=form.status.data,
            start_date=form.start_date.data,
            end_date=form.end_date.data,
            max_participants=form.max_participants.data,
            price=form.price.data or 0,
            location=form.location.data,
            online_link=form.online_link.data,
            speaker_info=form.speaker_info.data,
            agenda=form.agenda.data,
            is_featured=form.is_featured.data,
            created_by=current_user.id,
        )
        db.session.add(event)
        db.session.commit()
        flash('Захід створено', 'success')
        return redirect(url_for('admin.dashboard'))

    return render_template('admin/event_edit.html', form=form, event=None)


@admin_bp.route('/events/<int:event_id>/edit', methods=['GET', 'POST'])
@admin_required
def event_edit(event_id):
    event = db.session.get(Event, event_id)
    if not event:
        flash('Захід не знайдено', 'error')
        return redirect(url_for('admin.dashboard'))

    form = EventForm(obj=event)
    if form.validate_on_submit():
        slug = form.slug.data.strip()
        existing = Event.query.filter(Event.slug == slug, Event.id != event_id).first()
        if existing:
            flash('Захід з таким slug вже існує', 'error')
            return render_template('admin/event_edit.html', form=form, event=event)

        form.populate_obj(event)
        db.session.commit()
        flash('Захід оновлено', 'success')
        return redirect(url_for('admin.dashboard'))

    return render_template('admin/event_edit.html', form=form, event=event)


@admin_bp.route('/events/<int:event_id>/delete', methods=['POST'])
@admin_required
def event_delete(event_id):
    event = db.session.get(Event, event_id)
    if event:
        db.session.delete(event)
        db.session.commit()
        flash('Захід видалено', 'success')
    return redirect(url_for('admin.dashboard'))
