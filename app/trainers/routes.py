from flask import render_template, abort

from app.trainers import trainers_bp
from app.models.event import Event
from app.models.trainer import Trainer


@trainers_bp.route('/')
def trainer_list():
    trainers = Trainer.query.filter_by(is_active=True).order_by(Trainer.full_name).all()
    return render_template('trainers/list.html', active_nav='trainers', trainers=trainers)


@trainers_bp.route('/<slug>')
def trainer_detail(slug):
    trainer = Trainer.query.filter_by(slug=slug, is_active=True).first()
    if not trainer:
        abort(404)
    events = Event.query.filter_by(
        trainer_id=trainer.id, is_active=True,
    ).order_by(Event.start_date).all()
    return render_template(
        'trainers/detail.html',
        active_nav='trainers',
        trainer=trainer,
        events=events,
    )
