"""Автовидача, розсилка й добір сертифікатів лектора.

Оркестрація живе тут, а не в certificate_service: той модуль уже великий і
відповідає за самі документи (номери, знімки, рендер), а це — правила
життєвого циклу навколо них.

Перехід заходу в 'completed' робить лише INSERT записів. Рендер PDF
(WeasyPrint, секунда-дві на документ) і розсилка винесені у фонові джоби:
запит адміна не має на них чекати, а збій рендера не має відкочувати зміну
статусу.
"""
import logging

from app.extensions import db
from app.models.mixins import utcnow

logger = logging.getLogger(__name__)

# Через скільки годин виданий, але не надісланий сертифікат вважається
# "застряглим" і потрапляє у щоденний звіт адміну (а не в звичайний тік
# розсилки -- той намагається знову щоп'ять хвилин сам).
STUCK_AFTER_HOURS = 24

# Автоматичний добір (щоденна джоба) і блок «заблоковано» у звіті бачать лише
# заходи, що завершились не раніше стількох днів тому. Без межі перший же
# запуск видав би й розіслав сертифікати за ВСІ історичні заходи: xlsx-імпорт
# (scripts/import_xlsx_data.py) заводить минулі заходи одразу в 'completed',
# і тренери отримали б пачку листів за роки назад -- або щоденний звіт вічно
# перелічував би старі заходи без балів, і його перестали б читати. Перехід
# статусу адміном (issue_for_instance з маршрутів) межі не має: там людина
# діє свідомо.
LECTURER_AUTO_ISSUE_WINDOW_DAYS = 30

# Скільки днів після позначки «надіслано» перевіряти, чи лист зрештою дійшов.
# Автоповтор пошти ходить у межах години, тож остаточна доля листа відома
# задовго до цього; запас -- на випадок, коли пошта лежала довше.
REQUEUE_LOOKBACK_DAYS = 3


def issue_for_instance(instance, issued_by=None):
    """Видати сертифікати всім тренерам заходу. Повертає список записів.

    Окремої пре-циклової перевірки балів БПР тут немає навмисно: усі
    передумови видачі (бали лектора, номер провайдера БПР, номер заходу
    БПР) `certificate_service.issue_lecturer_certificate` перевіряє сам і
    кидає `ValueError` з готовим людським текстом причини -- тримати ще
    одну перевірку тієї самої речі тут означало б два джерела правди, які
    рано чи пізно розійдуться.

    Спиняємось на ПЕРШОМУ збої, а не продовжуємо цикл по решті тренерів:
    - `ValueError` -- це завжди передумова заходу в цілому (бали, номер
      провайдера, номер заходу), а не конкретного тренера. Вона однаково
      завалить кожну наступну ітерацію, тож продовжувати цикл -- це лише
      наплодити однакових листів адмінам.
    - будь-який інший виняток -- технічний збій. `issue_lecturer_certificate`
      комітить сам на кожного тренера, тож збій на третьому тренері з п'яти
      лишив би перших двох із сертифікатами, а решту без -- захід у
      частковому стані, з якого немає чистого виходу. Тому й тут не
      продовжуємо, а повертаємо те, що встигло видатись, і сповіщаємо
      адмінів.
    """
    from app.services import certificate_service as cs

    trainers = instance.effective_trainers
    if not trainers:
        return []

    issued = []
    for trainer in trainers:
        try:
            issued.append(cs.issue_lecturer_certificate(
                instance, trainer, issued_by=issued_by))
        except ValueError as exc:
            db.session.rollback()
            _notify_failed(instance, str(exc))
            return issued
        except Exception:
            db.session.rollback()
            logger.exception(
                'Lecturer certificate issue failed: instance=%s trainer=%s',
                instance.id, trainer.id)
            _notify_failed(
                instance,
                'Технічний збій під час видачі -- подробиці в лозі сервера.',
            )
            return issued
    return issued


def recipient_email(trainer):
    """Куди слати сертифікат: анкета -> акаунт -> довідник.

    Анкета першою: цю адресу тренер вказав сам і сам підтримує. Довідникова
    остання -- її заповнює адмін, і вона найчастіше застаріває.
    """
    profile = trainer.profile
    candidates = (
        (profile.email if profile is not None else None),
        (trainer.user.email if trainer.user is not None else None),
        trainer.email,
    )
    for value in candidates:
        value = (value or '').strip()
        if value:
            return value
    return None


def send_pending(limit=50):
    """Розіслати сертифікати, які ще не пішли листом.

    Повертає (надіслано, пропущено). Черга -- `emailed_at IS NULL` серед
    записів, що мають тренера: сирота (`trainer_id IS NULL`) -- незмінний
    знімок видачі видаленому з довідника тренеру, слати його нікому, і в
    черзі він лише вічно займав би її голову.

    "Пропущено" -- тренер без жодної адреси або адреса в suppression: листа
    не може бути взагалі, тож ліміт на такі записи не витрачається. Інакше
    півсотні безадресних із раннім issued_at назавжди закрили б чергу для
    тих, кому слати є куди. Ліміт рахує лише справжні спроби відправки --
    щоб один тік не рендерив сотню PDF поспіль після довгого простою пошти.

    `emailed_at` ставиться лише тоді, коли лист цієї версії справді
    поставлено в чергу або вже надіслано (див. `_delivered`). Збій на одному
    записі не зупиняє решту: наступний тік спробує знову. Виняток --
    'failed' від самого send_email (вимкнена пошта, відкритий circuit
    breaker, збій рендеру шаблону): це стан пошти, а не листа, і кожна
    наступна спроба в тому ж тіку дала б ще один 'failed' у журналі. Для
    breaker-а це самопідживлення -- 'failed' від черги тримали б його
    відкритим, і пошта всього сайту не відновилась би.
    """
    from sqlalchemy.orm import joinedload

    from app.models.lecturer_certificate import LecturerCertificate
    from app.models.trainer import Trainer
    from app.services.email_service import EmailService

    # Адресу кожного запису рахуємо наперед, одним запитом разом із
    # тренером, анкетою й акаунтом, -- ДО першого коміту нижче. Коміт
    # expire-ить сесію, і після нього ліниві звʼязки давали б по кілька
    # запитів на запис. Безадресні лишаються в черзі назавжди (їх не
    # позначаємо, щоб вони дійшли до звіту), тож без цього кожен тік раз на
    # п'ять хвилин ставав би дорожчим. Ліміт спроб на LIMIT запиту не
    # перекладаємо: пропущені записи в нього не входять.
    trainer_path = joinedload(LecturerCertificate.trainer)
    queue = [
        (cert.id, recipient_email(cert.trainer))
        for cert in (
            LecturerCertificate.query
            .options(trainer_path.joinedload(Trainer.profile),
                     trainer_path.joinedload(Trainer.user))
            .filter(LecturerCertificate.emailed_at.is_(None),
                    LecturerCertificate.trainer_id.isnot(None))
            .order_by(LecturerCertificate.issued_at, LecturerCertificate.id)
            .all()
        )
        if cert.trainer is not None
    ]
    # Suppression -- властивість адреси, а не запису: у тренера з кількома
    # сертифікатами вона одна на всі, і питати БД щоразу нема навіщо.
    suppressed = {}
    sent = skipped = attempts = 0
    for cert_id, to_email in queue:
        if attempts >= limit:
            break
        if to_email and to_email not in suppressed:
            suppressed[to_email] = EmailService.is_suppressed(to_email, 'certificate')
        if not to_email or suppressed[to_email]:
            # Свідомо НЕ ставимо emailed_at: запис лишається видимим як
            # «видано, не надіслано» і потрапляє в щоденний звіт адміну.
            skipped += 1
            continue
        cert = db.session.get(LecturerCertificate, cert_id)
        if cert is None:
            continue
        attempts += 1
        try:
            log = EmailService.send_lecturer_certificate(cert, to_email)
        except Exception:
            db.session.rollback()
            logger.exception(
                'Failed to email lecturer certificate %s', cert.number)
            continue
        if not _delivered(cert, log):
            logger.warning(
                'Lecturer certificate %s not queued (%s), left for next tick',
                cert.number, getattr(log, 'error_message', None) or 'skipped')
            if log is not None and log.status == 'failed':
                break
            continue
        cert.emailed_at = utcnow()
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            logger.exception(
                'Failed to mark lecturer certificate %s as emailed', cert.number)
            continue
        sent += 1
    return sent, skipped


def _delivered(cert, log):
    """Чи лист ЦІЄЇ версії сертифіката поставлено в чергу або надіслано.

    send_email повертає EmailLog або None. EmailLog -- дивимось статус:
    'failed' означає, що лист не пішов (вимкнена пошта, circuit breaker,
    збій рендеру). None буває з двох причин, і лише одна з них -- успіх:
    idempotent skip (лист цієї версії вже в журналі) чи suppression адреси.
    Розрізняємо тим самим запитом, яким send_email вирішував про skip:
    запис із цим ключем у статусі pending/sent є лише в першому випадку.
    """
    from app.services.email_service import EmailService

    if log is not None:
        return log.status in ('pending', 'sent')
    key = EmailService.lecturer_certificate_idempotency_key(cert)
    return EmailService.is_already_queued(key)


def requeue_undelivered():
    """Повернути в чергу сертифікати, чий лист зрештою не дійшов.

    `_delivered` зараховує лист у статусі 'pending' -- він уже переданий
    пошті. Якщо потім відправка впала, а автоповтори вичерпались, журнал
    лишається 'failed', а сертифікат -- позначеним як надісланий, і тренер
    його так і не отримує. Скидаємо `emailed_at`, щоб наступний тік розсилки
    зібрав лист заново. Лише після ТИМЧАСОВИХ збоїв: поки повтор ще можливий,
    його робить сама пошта, а постійна помилка (нема такої скриньки)
    повторилась би щодня. Повертає кількість повернених у чергу.
    """
    from datetime import timedelta

    from app.models.email_log import EmailLog, MAX_RETRIES, PERMANENT_ERROR_MARKERS
    from app.models.lecturer_certificate import LecturerCertificate
    from app.services.email_service import EmailService

    since = utcnow() - timedelta(days=REQUEUE_LOOKBACK_DAYS)
    certs = (
        LecturerCertificate.query
        .filter(LecturerCertificate.emailed_at.isnot(None),
                LecturerCertificate.emailed_at >= since)
        .all()
    )
    by_key = {EmailService.lecturer_certificate_idempotency_key(c): c for c in certs}
    if not by_key:
        return 0
    logs_by_key = {}
    for log in EmailLog.query.filter(EmailLog.idempotency_key.in_(list(by_key))).all():
        logs_by_key.setdefault(log.idempotency_key, []).append(log)

    requeued = 0
    for key, logs in logs_by_key.items():
        if any(log.status in ('pending', 'sent') for log in logs):
            continue
        latest = max(logs, key=lambda log: log.id)
        error = latest.error_message or ''
        exhausted = (latest.retry_count or 0) >= MAX_RETRIES
        permanent = any(marker in error for marker in PERMANENT_ERROR_MARKERS)
        if latest.status == 'failed' and exhausted and not permanent:
            by_key[key].emailed_at = None
            requeued += 1
    if requeued:
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            logger.exception('Failed to requeue undelivered lecturer certificates')
            return 0
        logger.info('Requeued %d lecturer certificates after failed delivery', requeued)
    return requeued


def _notify_failed(instance, reason):
    """Лист адмінам. Best-effort: збій сповіщення нічого не відкочує."""
    from app.services.email_service import EmailService
    try:
        EmailService.notify_lecturer_certificate_failed(instance, reason)
    except Exception:
        db.session.rollback()
        logger.exception(
            'Failed to notify admins about lecturer cert failure: instance=%s',
            instance.id)


def blocking_reason(instance):
    """Чому видача на цей захід неможлива -- текстом, або None, якщо можлива.

    Передумов три (бали БПР тренеру, номер провайдера БПР, номер заходу
    БПР), і кожна вже несе точне пояснення у своєму ValueError. Питаємо саме
    `certificate_service`, а не повторюємо перевірки тут: дві копії однієї
    умови розходяться, і тоді звіт адміну каже одне, а видача падає з іншого.
    """
    from app.services import certificate_service as cs

    try:
        cs._bpr_number_inputs(instance)
        cs._lecturer_points(instance)
    except ValueError as exc:
        return str(exc)
    return None


def _completed_instances():
    """Завершені заходи в межах вікна автодобору.

    Кінець заходу -- `end_date`, а для одноденних (без неї) -- `start_date`.
    Фільтр у SQL, а не в циклі: історичних заходів з імпорту на порядки
    більше, ніж свіжих, і тягнути їх у пам'ять щодня нема навіщо. Захід без
    жодної дати у вікно не потрапляє -- коли він відбувся, невідомо.
    """
    from datetime import timedelta

    from sqlalchemy.orm import joinedload, selectinload

    from app.models.course import Course
    from app.models.course_instance import CourseInstance

    since = utcnow() - timedelta(days=LECTURER_AUTO_ISSUE_WINDOW_DAYS)
    ended_at = db.func.coalesce(CourseInstance.end_date, CourseInstance.start_date)
    # Тренери дати й курсу -- наперед: `effective_trainers` і
    # `blocking_reason` (номер заходу й бали беруться з курсу) звертаються
    # до них на кожному заході, і ліниво це три запити на захід.
    return (
        CourseInstance.query
        .options(selectinload(CourseInstance.trainers),
                 joinedload(CourseInstance.course).selectinload(Course.trainers))
        .filter(CourseInstance.status == 'completed', ended_at >= since)
        .all()
    )


def _missing_trainers_by_instance(instances):
    """{instance.id: [тренери БЕЗ сертифіката]} для переданих заходів.

    Спільна вибірка для `issue_missing` (кого добирати) і `daily_maintenance`
    (кого рахувати заблокованим): один запит пар (instance_id, trainer_id)
    наперед для ВСІХ переданих заходів, а не по одному на ітерацію циклу --
    джоба щоденна й ходить по всіх завершених заходах, яких з часом стає
    багато. Захід, де всі тренери вже мають сертифікат, у результат не
    потрапляє взагалі -- саме це відрізняє «немає що добирати» від
    «заблоковано».
    """
    from app.models.lecturer_certificate import LecturerCertificate

    if not instances:
        return {}

    rows = (
        db.session.query(LecturerCertificate.instance_id,
                          LecturerCertificate.trainer_id)
        .filter(LecturerCertificate.instance_id.in_(
            [inst.id for inst in instances]))
        .all()
    )
    issued_by_instance = {}
    for instance_id, trainer_id in rows:
        issued_by_instance.setdefault(instance_id, set()).add(trainer_id)

    missing = {}
    for instance in instances:
        trainers = instance.effective_trainers
        if not trainers:
            continue
        have = issued_by_instance.get(instance.id, set())
        gap = [t for t in trainers if t.id not in have]
        if gap:
            missing[instance.id] = gap
    return missing


def _issue_for_missing(instances, missing):
    """Добрати сертифікати заходам із `missing`. Повертає кількість виданих.

    Захід із відомою причиною блокування пропускаємо, а не пробуємо видачу:
    `issue_for_instance` на ньому впала б на тій самій передумові й вислала б
    адмінам лист «не видано» -- уже вдруге, бо перший пішов у мить завершення
    заходу. Про такий захід нагадує щоденний звіт (`daily_maintenance`), і
    окремий лист до нього щоранку був би дублем про одне й те саме.
    """
    issued = 0
    for instance in instances:
        if instance.id not in missing or blocking_reason(instance) is not None:
            continue
        issued += len(issue_for_instance(instance))
    return issued


def on_status_changed(instance, old_status, issued_by=None):
    """Видати сертифікати тренерам, якщо захід щойно перейшов у 'completed'.

    Статус змінюють два маршрути -- швидкий перемикач і форма редагування
    проведення, -- і умова переходу живе тут одна: розійшовшись у двох
    місцях, вона вже раз лишила форму без видачі. Викликати ПІСЛЯ вдалого
    коміту статусу: видача комітить сама, і збій у ній не має відкочувати
    зміну статусу.
    """
    if old_status != 'completed' and instance.status == 'completed':
        return issue_for_instance(instance, issued_by=issued_by)
    return []


def issue_missing():
    """Добрати сертифікати завершеним заходам. Повертає кількість виданих.

    Покриває два реальні сценарії: бали БПР внесли вже після завершення
    заходу; тренера додали до складу після завершення. Обидва лишали б
    тренера без документа назавжди, бо тригер спрацьовує рівно один раз.
    """
    instances = _completed_instances()
    missing = _missing_trainers_by_instance(instances)
    return _issue_for_missing(instances, missing)


def daily_maintenance():
    """Добір пропущених + звіт адмінам про те, що застрягло.

    Звіт іде ЛИШЕ коли є про що казати: щоденний лист «усе гаразд» перестають
    читати, і разом із ним перестають помічати справжні.
    """
    from datetime import timedelta

    from app.models.lecturer_certificate import LecturerCertificate
    from app.services.email_service import EmailService

    instances = _completed_instances()
    missing = _missing_trainers_by_instance(instances)
    issued = _issue_for_missing(instances, missing)
    requeued = requeue_undelivered()

    cutoff = utcnow() - timedelta(hours=STUCK_AFTER_HOURS)
    # Сироти (trainer_id IS NULL) -- поза звітом, як і поза чергою: тренера
    # видалено з довідника, і адміну з таким записом нічого зробити.
    stuck = (
        LecturerCertificate.query
        .filter(LecturerCertificate.emailed_at.is_(None),
                LecturerCertificate.trainer_id.isnot(None),
                LecturerCertificate.issued_at < cutoff)
        .all()
    )
    # `missing` порахований ДО спроби видачі вище, і саме тому його можна
    # перевикористати тут: захід, де сертифікати вже видані ВСІМ тренерам, у
    # ньому відсутній -- навіть якщо налаштування (номер провайдера)
    # спорожніли ПІСЛЯ видачі. Добирати там нічого, і щоденний звіт не має
    # нагадувати про такий захід знову й знову.
    # Пари (захід, причина): причин блокування три, і звіт мусить назвати
    # справжню, а не одну на всіх.
    blocked = []
    for inst in instances:
        if inst.id not in missing:
            continue
        reason = blocking_reason(inst)
        if reason is not None:
            blocked.append((inst, reason))
    if stuck or blocked:
        try:
            EmailService.notify_lecturer_certificate_report(stuck, blocked)
        except Exception:
            db.session.rollback()
            logger.exception('Failed to send lecturer certificate report')
    return {'issued': issued, 'requeued': requeued, 'stuck': len(stuck),
            'blocked': len(blocked)}
