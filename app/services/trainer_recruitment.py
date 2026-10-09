"""Залучення тренерів: тексти запрошення, заявки кандидатів, перетворення на тренера.

Маршрути (публічний /trainers/join і адмінка /admin/trainer-applications)
лишаються тонкими: усе, що вирішує, як виглядає заявка й тренер із неї,
живе тут.
"""
import logging
import re

from flask_babel import gettext

from app.data.trainer_application_questions import QUESTIONS
from app.data.trainer_recruit import DEFAULTS
from app.extensions import db
from app.models.site_settings import SiteSettings
from app.models.trainer import Trainer
from app.models.trainer_application import TrainerApplication
from app.models.trainer_profile import TrainerProfile
from app.models.user import User
from app.services.certificate_batch import transliterate

logger = logging.getLogger(__name__)


class AlreadyConverted(Exception):
    """Із заявки вже створено тренера."""


# --- тексти ----------------------------------------------------------------

def recruit_text(field, settings=None):
    """Текст запрошення для поточної локалі.

    Збережений адміном текст (з перекладом ru/en, якщо він є) -- інакше
    дефолт із коду, перекладений каталогом.
    """
    settings = settings or SiteSettings.get()
    if (getattr(settings, field, '') or '').strip():
        return settings.t(field)
    return gettext(DEFAULTS[field])


def paragraphs(text):
    """'А\\nБ\\n\\nВ' -> [['А', 'Б'], ['В']]: абзац -- через порожній рядок."""
    blocks = re.split(r'\n\s*\n', (text or '').replace('\r\n', '\n').strip())
    return [[line.strip() for line in block.split('\n') if line.strip()]
            for block in blocks if block.strip()]


def benefit_lines(text):
    return [line.strip() for line in (text or '').replace('\r\n', '\n').split('\n')
            if line.strip()]


# --- заявка ----------------------------------------------------------------

def _value(form, name):
    return (getattr(form, name).data or '').strip()


def build_answers(form):
    """Відповіді на питання про плазму -- снапшот з українським підписом."""
    return [{'key': q['key'], 'label': q['label'], 'value': _value(form, f"q_{q['key']}")}
            for q in QUESTIONS]


def create_application(form, locale):
    application = TrainerApplication(
        full_name=_value(form, 'full_name'),
        phone=_value(form, 'phone'),
        email=_value(form, 'email'),
        city=_value(form, 'city') or None,
        specialty=_value(form, 'specialty'),
        workplace=_value(form, 'workplace') or None,
        social_links=_value(form, 'social_links') or None,
        topic=_value(form, 'topic'),
        answers=build_answers(form),
        locale=locale or 'uk',
    )
    db.session.add(application)
    return application


def notify(application):
    """Лист команді. Best-effort: заявку вже збережено, збій SMTP не має
    впливати на кандидата."""
    from app.services.email_service import EmailService
    try:
        EmailService.send_trainer_application_notification(application)
    except Exception:
        logger.exception('Failed to notify about TrainerApplication #%s', application.id)


# --- «Створити тренера» ---------------------------------------------------

def _unique_slug(full_name):
    base = re.sub(r'[^a-z0-9]+', '-', transliterate(full_name).lower()).strip('-')[:180]
    base = base or 'trainer'
    slug, n = base, 2
    while Trainer.query.filter_by(slug=slug).first() is not None:
        slug = f'{base}-{n}'
        n += 1
    return slug


def _account_for(trainer, email):
    """Акаунт для прив'язки: (user | None, попередження | None).

    Те саме правило, що в адмінці (_apply_account_link): лише підтверджений
    email і лише акаунт, ще не прив'язаний до іншого тренера.
    """
    user = User.query.filter(User.email == email).first()
    if user is None:
        return None, None
    if not user.email_confirmed:
        return None, 'Акаунт із цим email ще не підтвердив адресу -- прив\'яжіть його в картці тренера пізніше'
    taken = Trainer.query.filter(Trainer.user_id == user.id).first()
    if taken is not None and taken is not trainer:
        return None, f'Акаунт із цим email уже прив\'язано до тренера «{taken.full_name}»'
    return user, None


def create_trainer(application):
    """Неактивна картка тренера й анкета з даних заявки. Не комітить."""
    if application.trainer_id is not None:
        raise AlreadyConverted(application.trainer_id)
    trainer = Trainer(
        full_name=application.full_name,
        slug=_unique_slug(application.full_name),
        email=application.email,
        # На публічний сайт тренер потрапить, коли адмін заповнить картку
        # (фото, біографія) і ввімкне його сам.
        is_active=False,
    )
    user, warning = _account_for(trainer, application.email)
    if user is not None:
        trainer.user_id = user.id
    trainer.profile = TrainerProfile(
        full_name=application.full_name,
        specialty=application.specialty,
        workplace=application.workplace,
        phone=application.phone,
        email=application.email,
        social_links=application.social_links,
    )
    db.session.add(trainer)
    db.session.flush()
    application.trainer_id = trainer.id
    return trainer, warning
