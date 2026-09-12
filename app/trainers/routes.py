from flask import render_template, abort

from app.trainers import trainers_bp
from app.models.course import Course
from app.models.trainer import Trainer
from app.services.trainer_links import course_trainer_clause


@trainers_bp.route('/')
def trainer_list():
    trainers = Trainer.query.filter_by(is_active=True).order_by(Trainer.full_name).all()
    return render_template('trainers/list.html', active_nav='trainers', trainers=trainers)


@trainers_bp.route('/<slug>')
def trainer_detail(slug):
    trainer = Trainer.query.filter_by(slug=slug, is_active=True).first()
    if not trainer:
        abort(404)
    # course_trainer_clause, а не Course.trainer_id -- курс тепер веде
    # список тренерів (course_trainers), не одна колонка (Task 13 плану
    # "кілька тренерів"): сторінка тренера мусить бачити курс, навіть якщо
    # він не перший у списку.
    courses = Course.query.filter(
        course_trainer_clause(trainer.id), Course.is_active.is_(True),
    ).order_by(Course.title).all()
    return render_template(
        'trainers/detail.html',
        active_nav='trainers',
        trainer=trainer,
        courses=courses,
    )
