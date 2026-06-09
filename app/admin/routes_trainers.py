import json
import logging
from flask import render_template, redirect, url_for, flash, request
from flask_login import current_user
from app.admin import admin_bp
from app.admin.decorators import admin_required
from app.admin.forms import TrainerForm
from app.extensions import db
from app.models.trainer import Trainer
from app.services import trainer_service
from app.utils import slugify

logger = logging.getLogger(__name__)
audit_logger = logging.getLogger('audit')


def _parse_json_list(raw):
    try:
        val = json.loads(raw or '[]')
    except (ValueError, TypeError):
        return []
    return val if isinstance(val, list) else []


def _apply_regalia(trainer, form):
    """Санітизувати й перенести регалії з форми у модель."""
    trainer.certificates = trainer_service.sanitize_certificates(_parse_json_list(form.certificates.data))
    trainer.patents = trainer_service.sanitize_links(_parse_json_list(form.patents.data))
    trainer.articles = trainer_service.sanitize_links(_parse_json_list(form.articles.data))
    trainer.research = trainer_service.sanitize_research(form.research.data)


def _load_regalia_into_form(trainer, form):
    """Серіалізувати наявні регалії у приховані поля для редактора (GET)."""
    form.certificates.data = json.dumps(trainer.certificates or [], ensure_ascii=False)
    form.patents.data = json.dumps(trainer.patents or [], ensure_ascii=False)
    form.articles.data = json.dumps(trainer.articles or [], ensure_ascii=False)
    form.research.data = '\n'.join(trainer.research or [])


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
            full_name_dative=(form.full_name_dative.data or '').strip() or None,
            slug=slug,
            role=form.role.data,
            bio=form.bio.data,
            photo=form.photo.data,
            signature=(form.signature.data or '').strip() or None,
            experience_years=form.experience_years.data,
            email=(form.email.data or '').strip().lower() or None,
            is_active=form.is_active.data,
        )
        _apply_regalia(trainer, form)
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
    if request.method == 'GET':
        _load_regalia_into_form(trainer, form)

    if form.validate_on_submit():
        slug = form.slug.data.strip()
        existing = Trainer.query.filter(Trainer.slug == slug, Trainer.id != trainer_id).first()
        if existing:
            flash('Тренер з таким slug вже існує', 'error')
            return render_template('admin/trainer_edit.html', form=form, trainer=trainer)

        trainer.full_name = form.full_name.data.strip()
        trainer.full_name_dative = (form.full_name_dative.data or '').strip() or None
        trainer.slug = slug
        trainer.role = form.role.data
        trainer.bio = form.bio.data
        trainer.photo = form.photo.data
        trainer.signature = (form.signature.data or '').strip() or None
        trainer.experience_years = form.experience_years.data
        trainer.email = (form.email.data or '').strip().lower() or None
        trainer.is_active = form.is_active.data
        _apply_regalia(trainer, form)

        try:
            db.session.commit()
            audit_logger.info('Admin %s updated trainer %s (%s)', current_user.email, trainer_id, trainer.full_name)
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
        name = trainer.full_name
        db.session.delete(trainer)
        try:
            db.session.commit()
            audit_logger.info('Admin %s deleted trainer %s (%s)', current_user.email, trainer_id, name)
            flash('Тренера видалено', 'success')
        except Exception:
            logger.exception('Failed to delete trainer %d', trainer_id)
            db.session.rollback()
            flash('Помилка при видаленні', 'error')
    return redirect(url_for('admin.dashboard'))
