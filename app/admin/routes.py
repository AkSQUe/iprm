from flask import render_template, redirect, url_for, flash, request
from flask_login import current_user
from sqlalchemy.orm import joinedload
from app.admin import admin_bp
from app.admin.decorators import admin_required
from app.admin.forms import EventForm, TrainerForm
from app.extensions import db
from app.models.event import Event
from app.models.trainer import Trainer
from app.models.program_block import ProgramBlock
from app.models.registration import EventRegistration
from app.utils import slugify


def _populate_trainer_choices(form):
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


@admin_bp.route('/')
@admin_required
def dashboard():
    return redirect(url_for('admin.events_list'))


@admin_bp.route('/events')
@admin_required
def events_list():
    events = Event.query.options(
        joinedload(Event.trainer),
    ).order_by(Event.created_at.desc()).all()
    return render_template('admin/events.html', events=events)


@admin_bp.route('/trainers')
@admin_required
def trainers_list():
    trainers = Trainer.query.order_by(Trainer.full_name).all()
    return render_template('admin/trainers.html', trainers=trainers)


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

        event = Event(
            title=form.title.data.strip(),
            subtitle=form.subtitle.data,
            slug=slug,
            short_description=form.short_description.data,
            description=form.description.data,
            event_type=form.event_type.data,
            event_format=form.event_format.data,
            status=form.status.data,
            start_date=form.start_date.data,
            end_date=form.end_date.data,
            max_participants=form.max_participants.data,
            price=form.price.data or 0,
            location=form.location.data,
            online_link=form.online_link.data,
            hero_image=form.hero_image.data,
            card_image=form.card_image.data,
            cpd_points=form.cpd_points.data,
            trainer_id=form.trainer_id.data or None,
            target_audience=_lines_to_list(form.target_audience_text.data),
            tags=_lines_to_list(form.tags_text.data),
            speaker_info=form.speaker_info.data,
            agenda=form.agenda.data,
            is_featured=form.is_featured.data,
            created_by=current_user.id,
        )
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

        event.title = form.title.data.strip()
        event.subtitle = form.subtitle.data
        event.slug = slug
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


# ========== TRAINERS ==========


@admin_bp.route('/trainers/new', methods=['GET', 'POST'])
@admin_required
def trainer_create():
    form = TrainerForm()

    if form.validate_on_submit():
        slug = form.slug.data.strip() or slugify(form.full_name.data)
        if Trainer.query.filter_by(slug=slug).first():
            flash('Тренер з таким slug вже існує', 'error')
            return render_template('admin/trainer_edit.html', form=form, trainer=None)

        trainer = Trainer(
            full_name=form.full_name.data.strip(),
            slug=slug,
            role=form.role.data,
            bio=form.bio.data,
            photo=form.photo.data,
            experience_years=form.experience_years.data,
            is_active=form.is_active.data,
        )
        db.session.add(trainer)

        try:
            db.session.commit()
            flash('Тренера додано', 'success')
            return redirect(url_for('admin.dashboard'))
        except Exception:
            db.session.rollback()
            flash('Помилка при збереженні', 'error')

    return render_template('admin/trainer_edit.html', form=form, trainer=None)


@admin_bp.route('/trainers/<int:trainer_id>/edit', methods=['GET', 'POST'])
@admin_required
def trainer_edit(trainer_id):
    trainer = db.session.get(Trainer, trainer_id)
    if not trainer:
        flash('Тренера не знайдено', 'error')
        return redirect(url_for('admin.dashboard'))

    form = TrainerForm(obj=trainer)

    if form.validate_on_submit():
        slug = form.slug.data.strip()
        existing = Trainer.query.filter(Trainer.slug == slug, Trainer.id != trainer_id).first()
        if existing:
            flash('Тренер з таким slug вже існує', 'error')
            return render_template('admin/trainer_edit.html', form=form, trainer=trainer)

        trainer.full_name = form.full_name.data.strip()
        trainer.slug = slug
        trainer.role = form.role.data
        trainer.bio = form.bio.data
        trainer.photo = form.photo.data
        trainer.experience_years = form.experience_years.data
        trainer.is_active = form.is_active.data

        try:
            db.session.commit()
            flash('Тренера оновлено', 'success')
            return redirect(url_for('admin.dashboard'))
        except Exception:
            db.session.rollback()
            flash('Помилка при збереженні', 'error')

    return render_template('admin/trainer_edit.html', form=form, trainer=trainer)


@admin_bp.route('/trainers/<int:trainer_id>/delete', methods=['POST'])
@admin_required
def trainer_delete(trainer_id):
    trainer = db.session.get(Trainer, trainer_id)
    if trainer:
        db.session.delete(trainer)
        try:
            db.session.commit()
            flash('Тренера видалено', 'success')
        except Exception:
            db.session.rollback()
            flash('Помилка при видаленні', 'error')
    return redirect(url_for('admin.dashboard'))


# ========== REGISTRATIONS ==========


@admin_bp.route('/events/<int:event_id>/registrations')
@admin_required
def event_registrations(event_id):
    event = db.session.get(Event, event_id)
    if not event:
        flash('Захід не знайдено', 'error')
        return redirect(url_for('admin.dashboard'))

    registrations = EventRegistration.query.options(
        joinedload(EventRegistration.user),
    ).filter_by(event_id=event.id).order_by(
        EventRegistration.created_at.desc()
    ).all()

    return render_template(
        'admin/event_registrations.html',
        event=event,
        registrations=registrations,
    )


@admin_bp.route('/registrations/<int:reg_id>/status', methods=['POST'])
@admin_required
def registration_status(reg_id):
    reg = db.session.get(EventRegistration, reg_id)
    if not reg:
        flash('Реєстрацію не знайдено', 'error')
        return redirect(url_for('admin.dashboard'))

    new_status = request.form.get('status')
    if new_status in dict(EventRegistration.STATUSES):
        reg.status = new_status
        try:
            db.session.commit()
            flash(f'Статус змінено на "{reg.status_label}"', 'success')
        except Exception:
            db.session.rollback()
            flash('Помилка при оновленні', 'error')

    return redirect(url_for('admin.event_registrations', event_id=reg.event_id))


@admin_bp.route('/registrations/<int:reg_id>/attendance', methods=['POST'])
@admin_required
def registration_attendance(reg_id):
    reg = db.session.get(EventRegistration, reg_id)
    if not reg:
        flash('Реєстрацію не знайдено', 'error')
        return redirect(url_for('admin.dashboard'))

    reg.attended = True
    reg.status = 'completed'
    cpd = request.form.get('cpd_points', type=int)
    reg.cpd_points_awarded = cpd if cpd is not None else reg.event.cpd_points

    try:
        db.session.commit()
        flash(f'Присутність підтверджено, нараховано {reg.cpd_points_awarded} балів БПР', 'success')
    except Exception:
        db.session.rollback()
        flash('Помилка при оновленні', 'error')

    return redirect(url_for('admin.event_registrations', event_id=reg.event_id))


# ========== REGISTRATIONS (ALL) ==========


@admin_bp.route('/registrations')
@admin_required
def registrations_all():
    return render_template(
        'admin/stub.html',
        admin_section='registrations',
        page_title='Реєстрації',
        page_subtitle='Всі реєстрації на заходи',
    )


# ========== STUB SECTIONS ==========


@admin_bp.route('/payments')
@admin_required
def payments():
    return render_template(
        'admin/stub.html',
        admin_section='payments',
        page_title='Платежі',
        page_subtitle='Управління платежами та транзакціями',
    )


@admin_bp.route('/liqpay')
@admin_required
def liqpay():
    return render_template(
        'admin/stub.html',
        admin_section='liqpay',
        page_title='LiqPay',
        page_subtitle='Інтеграція з платіжною системою LiqPay',
    )


@admin_bp.route('/certificates')
@admin_required
def certificates():
    return render_template(
        'admin/stub.html',
        admin_section='certificates',
        page_title='Сертифікати',
        page_subtitle='Управління сертифікатами слухачів',
    )


@admin_bp.route('/clients')
@admin_required
def clients():
    return render_template(
        'admin/stub.html',
        admin_section='clients',
        page_title='Клієнти',
        page_subtitle='База клієнтів та учасників',
    )


@admin_bp.route('/reviews')
@admin_required
def reviews():
    return render_template(
        'admin/stub.html',
        admin_section='reviews',
        page_title='Відгуки',
        page_subtitle='Відгуки учасників на заходи',
    )


@admin_bp.route('/marketing')
@admin_required
def marketing():
    return render_template('admin/marketing.html')


@admin_bp.route('/integrations')
@admin_required
def integrations():
    return render_template('admin/integrations.html')


@admin_bp.route('/settings')
@admin_required
def settings():
    return render_template(
        'admin/stub.html',
        admin_section='settings',
        page_title='Налаштування',
        page_subtitle='Загальні налаштування системи',
    )
