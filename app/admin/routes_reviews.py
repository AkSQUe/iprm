"""Адмін-CRUD відгуків випускників (публічний блок на Головній)."""
import logging

from flask import render_template, redirect, url_for, flash, request
from flask_login import current_user

from app.admin import admin_bp
from app.admin.decorators import admin_required
from app.admin.forms import ReviewForm
from app.extensions import db
from app.models.review import Review

logger = logging.getLogger(__name__)
audit_logger = logging.getLogger('audit')


@admin_bp.route('/reviews')
@admin_required
def reviews_list():
    reviews = Review.query.order_by(
        Review.sort_order, Review.created_at.desc(),
    ).all()
    return render_template('admin/reviews.html', reviews=reviews)


def _apply(form, review):
    review.author_name = form.author_name.data.strip()
    review.author_role = (form.author_role.data or '').strip() or None
    review.city = (form.city.data or '').strip() or None
    review.text = form.text.data.strip()
    review.rating = int(form.rating.data)
    review.sort_order = form.sort_order.data or 0
    review.is_published = form.is_published.data


@admin_bp.route('/reviews/new', methods=['GET', 'POST'])
@admin_required
def review_create():
    form = ReviewForm()
    if form.validate_on_submit():
        review = Review()
        _apply(form, review)
        db.session.add(review)
        try:
            db.session.commit()
            audit_logger.info('Admin %s created review %s', current_user.email, review.id)
            flash('Відгук додано', 'success')
            return redirect(url_for('admin.reviews_list'))
        except Exception:
            logger.exception('Failed to create review')
            db.session.rollback()
            flash('Помилка при збереженні', 'error')
    return render_template('admin/review_edit.html', form=form, review=None)


@admin_bp.route('/reviews/<int:review_id>/edit', methods=['GET', 'POST'])
@admin_required
def review_edit(review_id):
    review = db.session.get(Review, review_id)
    if not review:
        flash('Відгук не знайдено', 'error')
        return redirect(url_for('admin.reviews_list'))
    form = ReviewForm(obj=review)
    if request.method == 'GET':
        form.rating.data = str(review.rating)
    if form.validate_on_submit():
        _apply(form, review)
        try:
            db.session.commit()
            audit_logger.info('Admin %s updated review %s', current_user.email, review_id)
            flash('Відгук оновлено', 'success')
            return redirect(url_for('admin.reviews_list'))
        except Exception:
            logger.exception('Failed to update review %d', review_id)
            db.session.rollback()
            flash('Помилка при збереженні', 'error')
    return render_template('admin/review_edit.html', form=form, review=review)


@admin_bp.route('/reviews/<int:review_id>/toggle', methods=['POST'])
@admin_required
def review_toggle(review_id):
    review = db.session.get(Review, review_id)
    if review:
        review.is_published = not review.is_published
        db.session.commit()
        flash('Публікацію змінено', 'success')
    return redirect(url_for('admin.reviews_list'))


@admin_bp.route('/reviews/<int:review_id>/delete', methods=['POST'])
@admin_required
def review_delete(review_id):
    review = db.session.get(Review, review_id)
    if review:
        db.session.delete(review)
        db.session.commit()
        audit_logger.info('Admin %s deleted review %s', current_user.email, review_id)
        flash('Відгук видалено', 'success')
    return redirect(url_for('admin.reviews_list'))
