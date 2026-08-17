"""Видача доступу до навчання після оплати онлайн-курсу.

Ціль редіректу -- посилання реєстрації на трек, згенероване в кабінеті
Sintegrum і збережене адміном у OnlineCourse.access_url. Воно спільне для
всіх покупців і безстрокове, тому назовні не віддається: учасник отримує
НАШЕ посилання з токеном і TTL, а редірект робимо ми.

Провайдер винесено за інтерфейс: якщо Sintegrum колись дасть персональні
посилання через API, зміниться одна реалізація, а платіжний код і кабінет
не помітять різниці.
"""
import logging
from dataclasses import dataclass
from typing import Optional

from app.extensions import db
from app.models.mixins import utcnow
from app.models.site_settings import SiteSettings

logger = logging.getLogger(__name__)

DEFAULT_TTL_HOURS = 72


@dataclass
class AccessResult:
    target_url: str
    student_id: Optional[int] = None


class AccessProvisionError(Exception):
    """Доступ видати неможливо (немає цілі, курс не готовий тощо)."""


class RegistrationLinkProvider:
    """Чинна реалізація (рішення Q1): спільне посилання реєстрації.

    До API Sintegrum не звертається взагалі -- отже видача доступу не
    залежить від його доступності, і сценарій «оплата пройшла, а доступ
    не видався через мережу» неможливий за побудовою. Учень реєструється
    в Sintegrum самостійно, пройшовши за посиланням.
    """

    def provision(self, enrollment) -> AccessResult:
        course = enrollment.course
        target = (getattr(course, 'access_url', '') or '').strip()
        if not target:
            raise AccessProvisionError(
                'У курсу не заданий access_url -- нема куди вести учасника',
            )
        return AccessResult(target_url=target)


def get_provider():
    """Фабрика провайдера. Точка заміни на персональні посилання."""
    return RegistrationLinkProvider()


def ttl_hours_for(course, settings=None):
    """Термін життя токена: значення курсу, інакше загальне з налаштувань."""
    if getattr(course, 'access_ttl_hours', None):
        return course.access_ttl_hours
    settings = settings or SiteSettings.get()
    return settings.sintegrum_access_ttl_hours or DEFAULT_TTL_HOURS


def provision(enrollment, commit=True):
    """Видати доступ до оплаченого замовлення.

    Ідемпотентна щодо оплати: повторний виклик просто перевипускає токен.
    Неоплачене замовлення доступу не отримує ніколи -- це остання лінія
    захисту, навіть якщо викликати функцію напряму.
    """
    if not enrollment.is_paid:
        raise AccessProvisionError('Замовлення не оплачене')

    try:
        result = get_provider().provision(enrollment)
    except AccessProvisionError as exc:
        enrollment.provision_error = str(exc)[:500]
        if commit:
            db.session.commit()
        logger.warning('Access provisioning failed for %s: %s',
                       enrollment.order_id, exc)
        raise

    enrollment.issue_access_token(ttl_hours_for(enrollment.course))
    enrollment.provisioned_at = utcnow()
    enrollment.provision_error = None
    if result.student_id:
        enrollment.sintegrum_student_id = result.student_id

    if commit:
        db.session.commit()

    logger.info('Access provisioned for %s (issue #%d)',
                enrollment.order_id, enrollment.access_issued_count)
    return enrollment.access_token


def access_url_for(enrollment):
    """Абсолютне посилання на наш редірект (не на Sintegrum).

    url_for недоступний поза request-контекстом (джоба «доліковування»),
    тому маємо запасний шлях через website_url із налаштувань.
    """
    from flask import url_for

    try:
        return url_for('online.access', token=enrollment.access_token,
                       _external=True)
    except RuntimeError:
        base = (SiteSettings.get().website_url or '').rstrip('/')
        return f'{base}/online-courses/access/{enrollment.access_token}'


def notify(enrollment):
    """Надіслати учаснику лист із виданим посиланням.

    Окремо від provision: видача доступу не має залежати від пошти.
    Збій листа лишає робоче посилання в кабінеті, а не забирає доступ.
    """
    if not enrollment.access_token:
        return None
    from app.services.email_service import EmailService

    try:
        return EmailService.send_online_access(
            enrollment, access_url_for(enrollment),
        )
    except Exception:
        logger.exception('Failed to queue access email for %s',
                         enrollment.order_id)
        return None


def provision_and_notify(enrollment, commit=True):
    """Видати доступ і сповістити -- саме в такому порядку."""
    token = provision(enrollment, commit=commit)
    notify(enrollment)
    return token


def reissue(enrollment, commit=True):
    """Перевипустити протермінований токен на вимогу учасника.

    Попередній токен тієї ж миті стає недійсним -- перевипуск не множить
    робочі посилання, а замінює одне іншим.
    """
    return provision(enrollment, commit=commit)


def pending_provisioning(older_than_minutes=10):
    """Оплачені замовлення, яким доступ так і не видали.

    У чинному сценарії це майже завжди означає, що в курсу зник
    access_url між оплатою і видачею. Мовчки лишати такий стан не можна:
    людина заплатила.
    """
    from datetime import timedelta

    from app.models.online_enrollment import OnlineEnrollment

    cutoff = utcnow() - timedelta(minutes=older_than_minutes)
    return (
        OnlineEnrollment.query
        .filter(
            OnlineEnrollment.payment_status == 'paid',
            OnlineEnrollment.provisioned_at.is_(None),
            OnlineEnrollment.created_at <= cutoff,
        )
        .all()
    )
