import logging

from flask import g, render_template

from app.services import trainer_cabinet as svc
from app.trainer_cabinet import trainer_cabinet_bp
from app.trainer_cabinet.decorators import trainer_required

logger = logging.getLogger(__name__)


@trainer_cabinet_bp.route('/')
@trainer_required
def index():
    trainer = g.trainer
    upcoming = svc.upcoming_instances(trainer)
    return render_template(
        'trainer_cabinet/index.html',
        trainer=trainer,
        upcoming=upcoming,
        counts=svc.registration_counts([i.id for i in upcoming]),
        courses=svc.trainer_courses(trainer),
        profile_complete=bool(trainer.profile and trainer.profile.is_complete),
    )


@trainer_cabinet_bp.route('/profile', methods=['GET', 'POST'])
@trainer_required
def profile():
    return render_template('trainer_cabinet/profile.html', trainer=g.trainer)


@trainer_cabinet_bp.route('/contract')
@trainer_required
def contract():
    return render_template('trainer_cabinet/contract.html', trainer=g.trainer)


@trainer_cabinet_bp.route('/faq')
@trainer_required
def faq():
    from app.models.site_settings import SiteSettings
    return render_template(
        'trainer_cabinet/faq.html', trainer=g.trainer,
        faq_html=svc.faq_html(SiteSettings.get()),
    )
