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
    """Запасний шлях: готове посилання, збережене адміном у картці курсу.

    До API Sintegrum не звертається взагалі. Лишається для курсів, де
    посилання справді існує (наприклад, відкрита реєстрація на трек), і як
    аварійний обхід, якщо API партнера недоступне надовго.
    """

    def provision(self, enrollment) -> AccessResult:
        course = enrollment.course
        target = (getattr(course, 'access_url', '') or '').strip()
        if not target:
            raise AccessProvisionError(
                'У курсу не заданий access_url -- нема куди вести учасника',
            )
        return AccessResult(target_url=target)


class StudentApiProvider:
    """Основна реалізація: заводимо студента й відкриваємо йому курс.

    Повторює руками перевірений порядок дій із кабінету Sintegrum: людина
    заводиться як студент, після чого їй відкривається доступ до
    конкретного курсу. Обидва кроки є в API:

        POST /external/{company}/student                       -- завести
        POST /external/{company}/user/{id}/positions/{course}  -- відкрити

    (Курс у Sintegrum -- це "position"; у схемі Course поля так і описані.)

    Пошук ПЕРЕД створенням обов'язковий: та сама людина купує другий курс,
    і завести її вдруге означало б два кабінети на один email, у кожному по
    половині навчання.

    Ціль редіректу -- навчальний портал компанії. Персонального посилання
    Sintegrum не видає: учасник заходить під собою й бачить курс у своєму
    списку.
    """

    def __init__(self, client=None, settings=None):
        self._client = client
        self._settings = settings

    @property
    def settings(self):
        if self._settings is None:
            self._settings = SiteSettings.get()
        return self._settings

    @property
    def client(self):
        if self._client is None:
            from app.services.sintegrum_client import (
                SintegrumClient, SintegrumConfigError,
            )
            try:
                self._client = SintegrumClient.from_settings(self.settings)
            except SintegrumConfigError as exc:
                raise AccessProvisionError(str(exc)) from exc
        return self._client

    def provision(self, enrollment) -> AccessResult:
        course = enrollment.course
        remote_course_id = getattr(course, 'sintegrum_id', None)
        if not remote_course_id:
            raise AccessProvisionError('У курсу немає ідентифікатора Sintegrum')

        student_id = (
            enrollment.sintegrum_student_id
            or known_student_id(enrollment.user_id)
            or self._resolve_student(enrollment)
        )

        assigned = self.client.assign_course(student_id, remote_course_id)
        if not assigned.ok:
            raise AccessProvisionError(
                f'Не вдалося відкрити доступ до курсу: {assigned.error}')

        self._confirm_assignment(student_id, remote_course_id)

        return AccessResult(target_url=portal_url(self.settings),
                            student_id=student_id)

    def _confirm_assignment(self, student_id, remote_course_id):
        """Звірити з партнером, що курс справді призначений.

        `POST .../positions/...` відповідає порожнім 200 -- це "запит
        прийнято", а не "людина бачить курс". Без звірки будь-яке
        непорозуміння (не той простір ідентифікаторів, не той курс) виглядає
        як успіх: замовлення позначається виданим, лист іде, а людина
        відкриває платформу й нічого там не знаходить. Саме так і сталося
        20.08.2026.

        Якщо звірка неможлива (партнер недоступний, формат несподіваний) --
        НЕ валимо видачу: краще видати доступ і не знати напевно, ніж
        відмовити людині через власну перевірку. Пишемо в лог.
        """
        progress = self.client.assigned_positions(student_id)
        if not progress.ok:
            logger.warning(
                'Не вдалося звірити призначення курсу %s учню %s: %s',
                remote_course_id, student_id, progress.error)
            return

        rows = progress.data if isinstance(progress.data, list) else None
        if rows is None:
            logger.warning(
                'Sintegrum віддав несподіваний формат прогресу для учня %s',
                student_id)
            return

        assigned_ids = {
            row.get('position_id') for row in rows if isinstance(row, dict)
        }
        if remote_course_id not in assigned_ids:
            raise AccessProvisionError(
                'Sintegrum прийняв запит, але курс у списку призначених не '
                f'з\'явився (учень {student_id}, курс {remote_course_id}). '
                'Найімовірніше, ідентифікатор учня не збігається з тим, '
                'якого чекає призначення позиції.')

    def _resolve_student(self, enrollment):
        """Знайти студента за email у Sintegrum або завести нового.

        Викликається лише тоді, коли свого запису про цю людину немає (див.
        `known_student_id`): звернення до чужого API дорожче за SELECT і
        залежить від того, чи partner правильно зрозумів наш фільтр.
        """
        user = enrollment.user
        email = (getattr(user, 'email', '') or '').strip()
        if not email:
            raise AccessProvisionError('У покупця немає email')

        found = self.client.find_student_by_email(email)
        if found.ok and isinstance(found.data, dict) and found.data.get('id'):
            return found.data['id']

        created = self.client.create_student(
            email=email,
            first_name=getattr(user, 'first_name', '') or '',
            last_name=getattr(user, 'last_name', '') or '',
            language=getattr(user, 'preferred_language', None) or 'uk',
        )
        if not created.ok:
            raise AccessProvisionError(
                f'Не вдалося завести студента: {created.error}')

        student_id = (created.data or {}).get('id') if isinstance(
            created.data, dict) else None
        if not student_id:
            raise AccessProvisionError(
                'Sintegrum не повернув ідентифікатор створеного студента')
        return student_id


def known_student_id(user_id):
    """Ідентифікатор учня Sintegrum, який ми вже отримували для цієї людини.

    Найнадійніше джерело: його записало НАШЕ попереднє замовлення. Пошук за
    email на боці партнера лишається запасним шляхом -- він залежить від
    того, чи спрацював фільтр, а не знайшовши, ми заводимо ще одного учня на
    ту саму адресу. Тобто два кабінети, у кожному по половині навчання.
    """
    if not user_id:
        return None

    from app.models.online_enrollment import OnlineEnrollment

    row = (
        db.session.query(OnlineEnrollment.sintegrum_student_id)
        .filter(
            OnlineEnrollment.user_id == user_id,
            OnlineEnrollment.sintegrum_student_id.isnot(None),
        )
        .order_by(OnlineEnrollment.id.desc())
        .first()
    )
    return row[0] if row else None


def portal_url(settings=None):
    """Адреса навчального порталу компанії у Sintegrum.

    Виводиться з аліаса (`<аліас>.sintegrum.com`), а не тримається окремим
    полем: аліас і так обов'язковий для роботи API, тож друге поле лише
    давало б їм змогу розійтися.
    """
    settings = settings or SiteSettings.get()
    alias = (settings.sintegrum_company_alias or '').strip()
    return f'https://{alias}.sintegrum.com' if alias else ''


def target_url_for(enrollment):
    """Куди веде видане посилання.

    Готове посилання курсу, якщо адмін його вписав; інакше -- навчальний
    портал компанії, де учасник уже має відкритий курс. Порожній рядок
    означає, що вести нікуди: аліас не налаштований.
    """
    course_url = (getattr(enrollment.course, 'access_url', '') or '').strip()
    return course_url or portal_url()


def get_provider(course=None, settings=None):
    """Яким шляхом відкривати доступ.

    Готове посилання в картці курсу перемагає: якщо адмін його вписав, він
    зробив це свідомо і саме воно має спрацювати. У решті випадків --
    автоматична видача через API.
    """
    if course is not None and (getattr(course, 'access_url', '') or '').strip():
        return RegistrationLinkProvider()
    return StudentApiProvider(settings=settings)


def ttl_hours_for(course, settings=None):
    """Термін життя токена: значення курсу, інакше загальне з налаштувань."""
    if getattr(course, 'access_ttl_hours', None):
        return course.access_ttl_hours
    settings = settings or SiteSettings.get()
    return settings.sintegrum_access_ttl_hours or DEFAULT_TTL_HOURS


def close_transaction_before_network():
    """Закрити транзакцію перед зверненням до партнера.

    Виклик читає замовлення SELECT-ом, і цим уже відкриває транзакцію. Далі
    йдуть HTTP-запити на десятки секунд, і на PostgreSQL це чистий
    idle-in-transaction. Коміт саме тут, а не всередині `provision`: тут
    відомо, що в сесії нема нічого недописаного.
    """
    db.session.commit()


def provision(enrollment, commit=True):
    """Видати доступ до оплаченого замовлення.

    Транзакцію ЗАКРИВАЄ ВИКЛИК, а не ця функція: клієнт партнера має
    таймаути 3/10 секунд і три спроби, тож відкритий SELECT перетворився б
    на idle-in-transaction на весь цей час. Комітити тут було б гірше --
    функція зафіксувала б і будь-що незавершене, що caller лишив у сесії.
    Див. `close_transaction_before_network`.

    Ідемпотентна щодо оплати: повторний виклик просто перевипускає токен.
    Неоплачене замовлення доступу не отримує ніколи -- це остання лінія
    захисту, навіть якщо викликати функцію напряму.
    """
    if not enrollment.is_paid:
        raise AccessProvisionError('Замовлення не оплачене')

    try:
        result = get_provider(enrollment.course).provision(enrollment)
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

    promo = _thankyou_code(enrollment)

    try:
        return EmailService.send_online_access(
            enrollment, access_url_for(enrollment), promo=promo,
        )
    except Exception:
        logger.exception('Failed to queue access email for %s',
                         enrollment.order_id)
        return None


def _thankyou_code(enrollment):
    """Код на наступний курс -- причина повернутись на сайт.

    Best-effort: механіка маркетингова, і її збій не має чіпати ані доступ,
    ані лист. Видача ідемпотентна, тож повторний лист несе той самий код.
    """
    from app.services import promo_service

    try:
        promo = promo_service.issue_thankyou_code_for_enrollment(enrollment)
        if promo is not None:
            db.session.commit()
        return promo
    except Exception:
        db.session.rollback()
        logger.exception('Thankyou promo failed for %s', enrollment.order_id)
        return None


def provision_and_notify(enrollment, commit=True):
    """Видати доступ і сповістити -- саме в такому порядку."""
    token = provision(enrollment, commit=commit)
    notify(enrollment)
    return token


def revoke_local(enrollment):
    """Зняти НАШ токен доступу. Лише БД, жодної мережі.

    Викликається всередині транзакції зміни платіжного статусу: чуже API
    туди пускати не можна (див. `revoke_remote`).
    """
    enrollment.revoke_access()


def revoke_remote(enrollment):
    """Забрати призначення курсу на боці Sintegrum.

    ОКРЕМО від `revoke_local` і ЗАВЖДИ поза транзакцією: клієнт має таймаути
    3/10 секунд і три спроби, тобто до ~30 секунд. Усередині транзакції це
    тримало б заблокований рядок замовлення під час callback LiqPay, а той
    на затримку відповідає повторним запитом.

    Best-effort: якщо API недоступне, наш токен усе одно вже знято. Лишити
    людині робочий доступ після повернення коштів гірше, ніж розійтися з
    партнером на один курс у списку, і це видно в логах.
    """
    student_id = enrollment.sintegrum_student_id
    remote_course_id = getattr(enrollment.course, 'sintegrum_id', None)
    if not (student_id and remote_course_id):
        return False

    try:
        from app.services.sintegrum_client import (
            SintegrumClient, SintegrumConfigError,
        )
        client = SintegrumClient.from_settings(SiteSettings.get())
    except SintegrumConfigError as exc:
        logger.warning('Cannot revoke Sintegrum access for %s: %s',
                       enrollment.order_id, exc)
        return False
    except Exception:
        logger.exception('Could not build Sintegrum client for %s',
                         enrollment.order_id)
        return False

    try:
        result = client.revoke_course(student_id, remote_course_id)
    except Exception:
        logger.exception('Could not revoke Sintegrum access for %s',
                         enrollment.order_id)
        return False

    if not result.ok:
        logger.warning('Failed to revoke course in Sintegrum for %s: %s',
                       enrollment.order_id, result.error)
    return result.ok


def revoke(enrollment, commit=True):
    """Зняти доступ повністю: наш токен і призначення в Sintegrum.

    Зручний шов для викликів ПОЗА транзакцією платежу (адмінка, скрипти).
    Платіжний шлях користується `revoke_local` / `revoke_remote` окремо.
    """
    revoke_local(enrollment)
    if commit:
        db.session.commit()
    revoke_remote(enrollment)


def reissue(enrollment, commit=True):
    """Перевипустити протермінований токен на вимогу учасника.

    Попередній токен тієї ж миті стає недійсним -- перевипуск не множить
    робочі посилання, а замінює одне іншим.
    """
    return provision(enrollment, commit=commit)


def pending_provisioning(older_than_minutes=10):
    """Оплачені замовлення, яким доступ так і не видали.

    Відлік -- від ОПЛАТИ, а не від оформлення. Замовлення живе від чекауту
    до платежу, і за рахунком це дні: до моменту оплати воно вже давно
    "старе", тож джоба бралася б за нього тієї ж хвилини, коли доступ
    видає callback. Два одночасні прогони означають два токени -- другий
    гасить перший, той самий, що вже пішов листом.

    `created_at` лишається запасним джерелом: у давніх замовлень і в тих,
    що їх проставили руками до появи поля, paid_at може бути порожнім.
    """
    from datetime import timedelta

    from sqlalchemy import func

    from app.models.online_enrollment import OnlineEnrollment

    cutoff = utcnow() - timedelta(minutes=older_than_minutes)
    paid_moment = func.coalesce(
        OnlineEnrollment.paid_at, OnlineEnrollment.created_at,
    )
    return (
        OnlineEnrollment.query
        .filter(
            OnlineEnrollment.payment_status == 'paid',
            OnlineEnrollment.provisioned_at.is_(None),
            paid_moment <= cutoff,
        )
        .all()
    )
