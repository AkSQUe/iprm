"""Прибирання за тестами повернення коштів.

Не `test_*`, тож pytest це не збирає -- це помічник, а не набір тестів.

Навіщо взагалі: сервіси повернення КОМІТЯТЬ (інакше не перевірити, що саме
лягло в базу), а тестова БД одна на всю сесію. Тож кожен такий тест лишає
по собі рядки, які бачать усі наступні.

Ціна недбалості тут не теоретична: залишені курси й проведення зламали
`test_xlsx_participants` -- вивантаження учасників іде по ВСІХ рядках, і
чужий тест спіткнувся об наші. Тому чистимо не лише користувачів, а й
каталог, який створили фікстури.

Порядок ручний і саме такий: ORM-видалення користувача обнуляє `user_id`
у реєстраціях (NOT NULL -> падіння), а bulk-delete не проганяє каскади й
лишає осиротілі профілі та особи входу, чиї UNIQUE потім б'ються з
перевикористаним id у SQLite.
"""
from app.extensions import db
from app.models.auth_identity import AuthIdentity
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.email_log import EmailLog
from app.models.medical_profile import MedicalProfile
from app.models.online_course import OnlineCourse
from app.models.online_enrollment import OnlineEnrollment
from app.models.payment_transaction import PaymentTransaction
from app.models.refund_request import RefundRequest
from app.models.registration import EventRegistration
from app.models.registration_transfer import RegistrationTransfer
from app.models.user import User


def purge(email_prefix, slug_prefix=None, wipe_online=False):
    """Прибрати все, що створили фікстури з цим префіксом.

    email_prefix -- префікс email користувачів фікстур ('refund-', 'rrf-'...).
    slug_prefix  -- префікс slug курсів; None -- каталог не чіпаємо.
    wipe_online  -- чистити ВСІ онлайн-курси й замовлення (їх фікстури
                    створюють без спільного префікса).
    """
    db.session.rollback()

    users = [row.id for row in User.query.filter(
        User.email.like(f'{email_prefix}%')).all()]

    if users:
        regs = [row.id for row in EventRegistration.query.filter(
            EventRegistration.user_id.in_(users)).all()]
        RefundRequest.query.filter(
            RefundRequest.user_id.in_(users)).delete(synchronize_session=False)
        if regs:
            PaymentTransaction.query.filter(
                PaymentTransaction.registration_id.in_(regs)).delete(
                    synchronize_session=False)
            EmailLog.query.filter(
                EmailLog.registration_id.in_(regs)).delete(
                    synchronize_session=False)
            RegistrationTransfer.query.filter(
                RegistrationTransfer.registration_id.in_(regs)).delete(
                    synchronize_session=False)
            EventRegistration.query.filter(
                EventRegistration.id.in_(regs)).delete(synchronize_session=False)

    if wipe_online:
        OnlineEnrollment.query.delete()
        OnlineCourse.query.delete()

    if slug_prefix:
        courses = [row.id for row in Course.query.filter(
            Course.slug.like(f'{slug_prefix}%')).all()]
        if courses:
            CourseInstance.query.filter(
                CourseInstance.course_id.in_(courses)).delete(
                    synchronize_session=False)
            Course.query.filter(
                Course.id.in_(courses)).delete(synchronize_session=False)

    if users:
        MedicalProfile.query.filter(
            MedicalProfile.user_id.in_(users)).delete(synchronize_session=False)
        AuthIdentity.query.filter(
            AuthIdentity.user_id.in_(users)).delete(synchronize_session=False)
        User.query.filter(User.id.in_(users)).delete(synchronize_session=False)

    db.session.commit()
