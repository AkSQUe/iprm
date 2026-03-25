import logging
from flask import render_template, redirect, url_for, flash
from flask_login import current_user
from app.admin import admin_bp
from app.admin.decorators import admin_required
from app.admin.forms import TrainerForm
from app.extensions import db
from app.models.trainer import Trainer
from app.utils import slugify

logger = logging.getLogger(__name__)
audit_logger = logging.getLogger('audit')


@admin_bp.route('/trainers')
@admin_required
def trainers_list():
    trainers = Trainer.query.order_by(Trainer.full_name).all()
    return render_template('admin/trainers.html', trainers=trainers)


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
            audit_logger.info('Admin %s created trainer %s (%s)', current_user.email, trainer.id, trainer.full_name)
            flash('Тренера додано', 'success')
            return redirect(url_for('admin.dashboard'))
        except Exception:
            logger.exception('Failed to create trainer')
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
            logger.exception('Failed to update trainer %d', trainer_id)
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
            logger.exception('Failed to delete trainer %d', trainer_id)
            db.session.rollback()
            flash('Помилка при видаленні', 'error')
    return redirect(url_for('admin.dashboard'))
