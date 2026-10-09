from flask import abort, current_app, flash, redirect, render_template, request, url_for
from flask_babel import get_locale, gettext as _

from app.data.trainer_application_questions import QUESTIONS
from app.extensions import db, limiter
from app.trainers import trainers_bp
from app.models.course import Course
from app.models.trainer import Trainer
from app.services import trainer_recruitment
from app.services.recaptcha import verify_request as verify_recaptcha
from app.services.trainer_links import course_trainer_clause
from app.trainers.forms import TrainerApplicationForm


@trainers_bp.route('/')
def trainer_list():
    trainers = Trainer.query.filter_by(is_active=True).order_by(Trainer.full_name).all()
    return render_template('trainers/list.html', active_nav='trainers', trainers=trainers)


@trainers_bp.route('/join', methods=['GET', 'POST'])
@limiter.limit('5 per hour; 20 per day', methods=['POST'])
def join():
    """«Стати тренером»: текст запрошення й анкета кандидата."""
    form = TrainerApplicationForm()
    if request.method == 'POST':
        # Honeypot: боту -- «успіх», у базу нічого.
        if (form.website.data or '').strip():
            current_app.logger.info('trainer_join honeypot triggered')
            return redirect(url_for('trainers.join', sent=1))
        if not verify_recaptcha(action='trainer_join'):
            flash(_('Перевірка reCAPTCHA не пройдена. Спробуйте ще раз.'), 'error')
        elif form.validate():
            application = trainer_recruitment.create_application(form, str(get_locale() or 'uk'))
            try:
                db.session.commit()
            except Exception:
                db.session.rollback()
                current_app.logger.exception('Failed to save TrainerApplication')
                flash(_('Помилка при надсиланні заявки. Спробуйте ще раз.'), 'error')
            else:
                # Лист -- лише після коміту: заявка вже в базі, і збій пошти
                # (notify сам його ковтає) не загубить її.
                trainer_recruitment.notify(application)
                return redirect(url_for('trainers.join', sent=1))
    texts = {name: trainer_recruitment.recruit_text(name) for name in (
        'recruit_page_title', 'recruit_page_intro', 'recruit_page_benefits',
        'recruit_page_closing')}
    return render_template(
        'trainers/join.html',
        active_nav='trainers',
        form=form,
        questions=QUESTIONS,
        sent=request.args.get('sent') == '1',
        title=texts['recruit_page_title'],
        intro=trainer_recruitment.paragraphs(texts['recruit_page_intro']),
        benefits=trainer_recruitment.benefit_lines(texts['recruit_page_benefits']),
        closing=trainer_recruitment.paragraphs(texts['recruit_page_closing']),
    )


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
