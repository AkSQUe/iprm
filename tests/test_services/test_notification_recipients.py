"""notification_recipients.resolve(): розсилка тренерам заходу.

До цього файлу єдиний виклик resolve() в усьому сьюті --
tests/test_rbac/test_is_admin_removed.py, і той перевіряє notify_admins,
не тренерів. Гілка notify_event_trainer досі не мала жодного тесту, тож
тут пишемо так, ніби про поведінку функції нічого не відомо -- без
припущень з попередніх тестів.
"""
from uuid import uuid4

from app.extensions import db
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.notification_rule import NotificationRule
from app.models.site_settings import SiteSettings
from app.models.trainer import Trainer
from app.services import notification_recipients, trainer_links


def _course():
    c = Course(title=f'Курс {uuid4().hex[:6]}', slug=f'course-{uuid4().hex[:8]}')
    db.session.add(c)
    db.session.flush()
    return c


def _instance(course):
    inst = CourseInstance(course_id=course.id, event_format='offline')
    db.session.add(inst)
    db.session.flush()
    return inst


def _trainer(name, email=None):
    t = Trainer(full_name=name, slug=f'trainer-{uuid4().hex[:8]}', email=email)
    db.session.add(t)
    db.session.flush()
    return t


def _rule(event_type='registration', **flags):
    """Правило для тесту -- усі динамічні джерела вимкнені за замовчуванням,
    щоб тест вмикав рівно те, що перевіряє (a не успадковував True з дефолту
    моделі, як-от notify_admins)."""
    rule = NotificationRule.query.get(event_type)
    if rule is None:
        rule = NotificationRule(event_type=event_type)
        db.session.add(rule)
    rule.enabled = True
    rule.notify_admins = False
    rule.notify_managers = False
    rule.notify_event_trainer = False
    rule.extra_emails = []
    for key, value in flags.items():
        setattr(rule, key, value)
    db.session.flush()
    return rule


def test_notifies_every_trainer_of_the_event():
    """Кожен, хто веде захід, бачить реєстрації.

    Старий код читав лише instance.effective_trainer -- перший зі списку.
    Другий тренер тут ставиться навмисно другим (position=1), тож цей тест
    падав би на старій реалізації: у результаті була б лише перша адреса.
    """
    course = _course()
    instance = _instance(course)
    a = _trainer('Тренер А', email='trainer-a@example.com')
    b = _trainer('Тренер Б', email='trainer-b@example.com')
    trainer_links.set_trainers(instance, [a.id, b.id])
    _rule('registration', notify_event_trainer=True)

    emails = notification_recipients.resolve('registration', instance=instance)

    assert 'trainer-a@example.com' in emails
    assert 'trainer-b@example.com' in emails


def test_trainer_who_is_also_a_manager_gets_one_letter():
    """Дедуплікація за адресою -- разом з адмінами й менеджерами.

    Перевіряємо саме через resolve() (не breakdown _resolve_sources):
    дедуп -- властивість, яку гарантує _dedup_preserve_order на рівні
    resolve(), а не самого збору джерел.
    """
    shared = 'shared@example.com'
    course = _course()
    instance = _instance(course)
    trainer = _trainer('Тренер-менеджер', email=shared)
    trainer_links.set_trainers(instance, [trainer.id])

    settings = SiteSettings.get()
    settings.event_manager_emails = [shared]
    db.session.flush()

    _rule('registration', notify_event_trainer=True, notify_managers=True)

    emails = notification_recipients.resolve('registration', instance=instance)

    assert emails.count(shared) == 1


def test_trainer_without_email_is_skipped_silently():
    """Email у тренера nullable: історично їх додавали без контактної пошти.

    Тренер без email не має ані потрапити в розсилку, ані підняти виняток
    (resolve() fail-soft, але тут навіть падати нема від чого -- getattr
    просто поверне None)."""
    course = _course()
    instance = _instance(course)
    with_email = _trainer('Тренер з поштою', email='has-email@example.com')
    without_email = _trainer('Тренер без пошти', email=None)
    trainer_links.set_trainers(instance, [with_email.id, without_email.id])
    _rule('registration', notify_event_trainer=True)

    emails = notification_recipients.resolve('registration', instance=instance)

    assert emails == ['has-email@example.com']


def test_inherits_course_trainers_when_instance_has_none():
    """effective_trainers на проведенні без власних тренерів бере курсові --
    те саме повне перекриття, яким живе CourseInstance.effective_trainers."""
    course = _course()
    t = _trainer('Курсовий тренер', email='course-trainer@example.com')
    trainer_links.set_trainers(course, [t.id])
    instance = _instance(course)  # без власних тренерів
    _rule('registration', notify_event_trainer=True)

    emails = notification_recipients.resolve('registration', instance=instance)

    assert emails == ['course-trainer@example.com']


def test_flag_off_excludes_trainers_even_when_event_has_them():
    """Прапор notify_event_trainer вимкнено -- тренерів немає у розсилці,
    навіть якщо в заходу вони є."""
    course = _course()
    instance = _instance(course)
    t = _trainer('Тренер', email='trainer@example.com')
    trainer_links.set_trainers(instance, [t.id])
    _rule('registration', notify_event_trainer=False)

    emails = notification_recipients.resolve('registration', instance=instance)

    assert 'trainer@example.com' not in emails
