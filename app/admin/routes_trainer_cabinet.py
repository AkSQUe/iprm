"""Адмінка кабінету тренера: анкета, пропозиції курсу, налаштування «Для тренерів»."""
import logging

from flask import abort, flash, redirect, render_template, url_for
from flask_login import current_user

from app.admin import admin_bp
from app.admin.forms import ProposalReturnForm
from app.extensions import db
from app.models.trainer import Trainer
from app.models.trainer_course_proposal import TrainerCourseProposal
from app.models.trainer_profile import TrainerProfile
from app.rbac import permission_required
from app.rbac.access import has_permission
from app.services import trainer_cabinet as svc

audit_logger = logging.getLogger('audit')


@admin_bp.route('/trainers/<int:trainer_id>/questionnaire')
@permission_required('trainers.view')
def trainer_questionnaire(trainer_id):
    trainer = db.session.get(Trainer, trainer_id) or abort(404)
    profile = trainer.profile
    # Реквізити (IBAN, РНОКПП, номер картки, ідентифікаційний код) видно у
    # відкритому вигляді лише тому, у кого є trainers.manage -- перегляд
    # (trainers.view) бачить лише маску з останніх 4 символів.
    reveal = has_permission(current_user, 'trainers.manage')
    secrets = {}
    if profile is not None:
        for name in TrainerProfile.SENSITIVE_FIELDS:
            value = getattr(profile, name)
            secrets[name] = value if reveal else TrainerProfile.mask(value)
    return render_template(
        'admin/trainer_questionnaire.html', trainer=trainer, profile=profile,
        secrets=secrets, can_manage=reveal, proposals=trainer.proposals.all(),
        return_form=ProposalReturnForm(),
    )


def _proposal_or_404(proposal_id):
    return db.session.get(TrainerCourseProposal, proposal_id) or abort(404)


@admin_bp.route('/trainers/proposals/<int:proposal_id>/accept', methods=['POST'])
@permission_required('trainers.manage')
def trainer_proposal_accept(proposal_id):
    proposal = _proposal_or_404(proposal_id)
    try:
        svc.accept_proposal(proposal)
        db.session.commit()
        audit_logger.info('Admin %s accepted trainer proposal %s', current_user.email, proposal.id)
        flash('Пропозицію прийнято', 'success')
    except svc.ProposalTransitionError:
        flash('Неможливо прийняти: пропозиція не на розгляді', 'error')
    return redirect(url_for('admin.trainer_questionnaire', trainer_id=proposal.trainer_id))


@admin_bp.route('/trainers/proposals/<int:proposal_id>/return', methods=['POST'])
@permission_required('trainers.manage')
def trainer_proposal_return(proposal_id):
    proposal = _proposal_or_404(proposal_id)
    form = ProposalReturnForm()
    if not form.validate_on_submit():
        flash('Коментар задовгий', 'error')
    else:
        try:
            svc.return_proposal(proposal, form.comment.data)
            db.session.commit()
            audit_logger.info('Admin %s returned trainer proposal %s', current_user.email, proposal.id)
            flash('Пропозицію повернуто на доопрацювання', 'success')
        except svc.ProposalTransitionError:
            flash('Неможливо повернути: пропозиція не на розгляді', 'error')
    return redirect(url_for('admin.trainer_questionnaire', trainer_id=proposal.trainer_id))
