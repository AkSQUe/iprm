"""Адмін-CRUD відгуків випускників (публічний блок на Головній)."""
import logging

from flask import render_template, redirect, url_for, flash, request
from flask_login import current_user

from app.admin import _listing, admin_bp
from app.rbac import permission_required
from app.admin.forms import ReviewForm
from app.extensions import db
from app.models.course import Course
from app.models.review import Review
from app.undo import offer_undo

logger = logging.getLogger(__name__)
audit_logger = logging.getLogger('audit')

_REVIEW_STATES = {'published': 'Опубліковані', 'draft': 'Чернетки'}


def _review_filters():
    """Фільтри списку відгуків -- спільні для сторінки й `_back()`."""
    return {
        'q': _listing.text_arg('q'),
        'state': _listing.choice_arg('state', _REVIEW_STATES),
        'course_id': _listing.int_arg('course_id'),
        'rating': _listing.int_arg('rating'),
        'per_page': _listing.choice_arg('per_page', _listing.PER_PAGE_CHOICES),
    }


def _back():
    """Безпечний POST -> GET редірект назад до списку зі збереженим зрізом
    (фільтр + СТОРІНКА): без сторінки публікація/видалення в рядку на
    третій сторінці щоразу відкидало б адміна на першу. `_listing.back_redirect`
    перечитує й перевіряє кожен параметр тим самим способом, що й роут
    списку (НЕ request.referrer -- той керований клієнтом і відкриває open
    redirect). Джерело значень -- query-string самого запиту дії: форма
    рядка несе зріз у своєму action-URL через `back_args`.
    """
    return _listing.back_redirect('admin.reviews_list', _review_filters())


def _current_back_args():
    """Той самий зріз (фільтр + сторінка), що й у поточному запиті дії --
    для посилань, які ЖИВУТЬ ДАЛІ за цей редірект (undo-тост із
    review_delete): сама дія повертається через `_back()`, а restore_url
    у тості веде на ще один роут дії, тож зріз йому теж треба нести явно.
    """
    page = _listing.page_arg()
    return _listing.back_args(_listing.filter_args(_review_filters()), page)


@admin_bp.route('/reviews')
@permission_required('reviews.view')
def reviews_list():
    filters = _review_filters()
    query = Review.alive().options(db.joinedload(Review.course))
    query = _listing.apply_search(query, filters['q'], [
        Review.author_name, Review.author_role, Review.city, Review.text,
    ])
    if filters['state']:
        query = query.filter(Review.is_published.is_(filters['state'] == 'published'))
    if filters['course_id']:
        query = query.filter(Review.course_id == filters['course_id'])
    if filters['rating']:
        query = query.filter(Review.rating == filters['rating'])

    pagination = query.order_by(
        Review.sort_order, Review.created_at.desc(),
    ).paginate(
        page=_listing.page_arg(),
        per_page=_listing.per_page_arg(), error_out=False,
    )
    filter_args = _listing.filter_args(filters)
    return render_template(
        'admin/reviews.html',
        reviews=pagination.items,
        pagination=pagination,
        per_page_options=_listing.PER_PAGE_OPTIONS,
        filters=filters,
        filter_args=filter_args,
        # Дії з рядка (публікація/видалення) ведуть сюди в action-URL, щоб
        # зберегти й фільтр, і сторінку.
        back_args=_listing.back_args(filter_args, pagination.page),
        state_options=list(_REVIEW_STATES.items()),
        course_options=[
            (c.id, c.title)
            for c in Course.query.order_by(Course.title).all()
        ],
        # «5 з 5», а не рядок зірок: у нативному селекті гліфи не мають
        # шкали, і «★★★★» від «★★★★★» відрізнялось лише довжиною.
        rating_options=[(n, f'{n} з 5') for n in range(5, 0, -1)],
    )


def _course_choices():
    """[('', '—')] + активні курси -- для селектора привʼязки відгуку."""
    courses = Course.query.filter_by(is_active=True).order_by(Course.title).all()
    return [('', '— без курсу —')] + [(str(c.id), c.title) for c in courses]


def _apply(form, review):
    review.author_name = form.author_name.data.strip()
    review.author_role = (form.author_role.data or '').strip() or None
    review.city = (form.city.data or '').strip() or None
    review.text = form.text.data.strip()
    review.rating = int(form.rating.data)
    review.sort_order = form.sort_order.data or 0
    review.course_id = int(form.course_id.data) if form.course_id.data else None
    review.is_published = form.is_published.data


@admin_bp.route('/reviews/new', methods=['GET', 'POST'])
@permission_required('reviews.manage')
def review_create():
    form = ReviewForm()
    form.course_id.choices = _course_choices()
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
    return render_template('admin/review_edit.html', form=form, review=None, back_args={})


@admin_bp.route('/reviews/<int:review_id>/edit', methods=['GET', 'POST'])
@permission_required('reviews.manage')
def review_edit(review_id):
    review = db.session.get(Review, review_id)
    if not review or review.is_deleted:
        flash('Відгук не знайдено', 'error')
        return _back()
    form = ReviewForm(obj=review)
    form.course_id.choices = _course_choices()
    if request.method == 'GET':
        form.rating.data = str(review.rating)
        form.course_id.data = str(review.course_id) if review.course_id else ''
    if form.validate_on_submit():
        _apply(form, review)
        try:
            db.session.commit()
            audit_logger.info('Admin %s updated review %s', current_user.email, review_id)
            flash('Відгук оновлено', 'success')
            return _back()
        except Exception:
            logger.exception('Failed to update review %d', review_id)
            db.session.rollback()
            flash('Помилка при збереженні', 'error')
    return render_template('admin/review_edit.html', form=form, review=review,
                          back_args=_current_back_args())


@admin_bp.route('/reviews/<int:review_id>/toggle', methods=['POST'])
@permission_required('reviews.manage')
def review_toggle(review_id):
    review = db.session.get(Review, review_id)
    if review and not review.is_deleted:
        review.is_published = not review.is_published
        try:
            db.session.commit()
            flash('Публікацію змінено', 'success')
        except Exception:
            logger.exception('Failed to toggle review %d', review_id)
            db.session.rollback()
            flash('Помилка при оновленні', 'error')
    return _back()


@admin_bp.route('/reviews/<int:review_id>/delete', methods=['POST'])
@permission_required('reviews.delete')
def review_delete(review_id):
    """М'яке видалення: діалогу підтвердження немає, натомість тост із
    кнопкою "Повернути" (відкат тут повний -- відновлюється весь рядок)."""
    review = db.session.get(Review, review_id)
    if review and not review.is_deleted:
        review.soft_delete()
        try:
            db.session.commit()
            audit_logger.info('Admin %s deleted review %s', current_user.email, review_id)
            offer_undo(
                'Відгук «%s» видалено' % review.author_name,
                url_for('admin.review_restore', review_id=review_id,
                       **_current_back_args()),
            )
        except Exception:
            logger.exception('Failed to delete review %d', review_id)
            db.session.rollback()
            flash('Помилка при видаленні', 'error')
    return _back()


@admin_bp.route('/reviews/<int:review_id>/restore', methods=['POST'])
@permission_required('reviews.manage')
def review_restore(review_id):
    review = db.session.get(Review, review_id)
    if not review or not review.is_deleted:
        # Рядок уже почистила фонова задача або відкат натиснули двічі.
        flash('Відгук уже не можна повернути', 'error')
        return _back()
    review.restore()
    try:
        db.session.commit()
        audit_logger.info('Admin %s restored review %s', current_user.email, review_id)
        flash('Відгук повернено', 'success')
    except Exception:
        logger.exception('Failed to restore review %d', review_id)
        db.session.rollback()
        flash('Помилка при відновленні', 'error')
    return _back()
