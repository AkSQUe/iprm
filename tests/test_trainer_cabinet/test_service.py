import pytest

from app.extensions import db
from app.models.site_settings import SiteSettings
from app.models.trainer_course_proposal import TrainerCourseProposal
from app.services import trainer_cabinet as svc
from app.services.trainer_links import set_trainers
from tests.test_trainer_cabinet._factories import (
    make_course, make_instance, make_registration, make_trainer, make_user,
)


@pytest.fixture
def trainer():
    return make_trainer(make_user())


def _ids(rows):
    return [r.id for r in rows]


def test_instance_level_assignment(trainer):
    inst = make_instance(make_course())
    set_trainers(inst, [trainer.id])
    db.session.commit()
    assert _ids(svc.upcoming_instances(trainer)) == [inst.id]


def test_course_level_assignment_inherited(trainer):
    course = make_course()
    set_trainers(course, [trainer.id])
    db.session.commit()
    inst = make_instance(course)
    assert _ids(svc.upcoming_instances(trainer)) == [inst.id]


def test_instance_with_own_trainers_overrides_course(trainer):
    other = make_trainer(name='Інший')
    course = make_course()
    set_trainers(course, [trainer.id])
    inst = make_instance(course)
    set_trainers(inst, [other.id])
    db.session.commit()
    assert svc.upcoming_instances(trainer) == []
    assert _ids(svc.upcoming_instances(other)) == [inst.id]


def test_past_and_draft_excluded(trainer):
    course = make_course()
    set_trainers(course, [trainer.id])
    db.session.commit()
    make_instance(course, days=-3)
    make_instance(course, status='draft')
    future = make_instance(course, days=10)
    soon = make_instance(course, days=2)
    assert _ids(svc.upcoming_instances(trainer)) == [soon.id, future.id]


def test_registration_counts():
    inst = make_instance(make_course(), event_format='hybrid')
    make_registration(inst, payment_status='paid', participation_format='online')
    make_registration(inst, participation_format='offline')
    make_registration(inst)  # hybrid без формату -> очно
    make_registration(inst, status='cancelled', payment_status='paid')
    counts = svc.registration_counts([inst.id])
    assert counts[inst.id] == {'total': 3, 'paid': 1, 'online': 1, 'offline': 2}
    assert svc.registration_counts([]) == {}


def test_trainer_courses(trainer):
    course = make_course()
    set_trainers(course, [trainer.id])
    db.session.commit()
    assert _ids(svc.trainer_courses(trainer)) == [course.id]


def test_trainer_courses_includes_inactive(trainer):
    """C19: тренер лишається автором курсу, навіть якщо курс приховали --
    приховування курсу не питання тренера, а сторінка про це не бреше."""
    course = make_course()
    course.is_active = False
    set_trainers(course, [trainer.id])
    db.session.commit()
    assert _ids(svc.trainer_courses(trainer)) == [course.id]


def test_proposal_transitions(trainer):
    p = TrainerCourseProposal(trainer_id=trainer.id, title='Т', theses=['a'])
    db.session.add(p)
    db.session.commit()
    with pytest.raises(svc.ProposalTransitionError):
        svc.accept_proposal(p)
    svc.submit_proposal(p)
    assert p.status == 'submitted' and p.submitted_at is not None
    with pytest.raises(svc.ProposalTransitionError):
        svc.submit_proposal(p)
    svc.return_proposal(p, 'Уточніть тези')
    assert p.status == 'draft' and p.curator_comment == 'Уточніть тези'
    svc.submit_proposal(p)
    svc.accept_proposal(p)
    assert p.status == 'accepted'


# --- C10: повторне надсилання не тягне за собою старий коментар куратора ---

def test_submit_clears_curator_comment(trainer):
    """Коментар куратора стосується ПОПЕРЕДНЬОЇ (повернутої) версії. Якщо він
    лишається після повторного надсилання, і адмінка, і сам тренер бачать
    зауваження, що вже неактуальне -- вже виправлену чернетку."""
    p = TrainerCourseProposal(trainer_id=trainer.id, title='Т', theses=['a'])
    db.session.add(p)
    db.session.commit()
    svc.submit_proposal(p)
    svc.return_proposal(p, 'Уточніть тези')
    assert p.curator_comment == 'Уточніть тези'
    svc.submit_proposal(p)
    assert p.status == 'submitted' and p.curator_comment is None


def test_faq_uses_default_and_email_fallback():
    s = SiteSettings.get()
    s.trainer_faq_html = ''
    s.trainer_contract_email = ''
    s.email = 'office@test.com'
    html = str(svc.faq_html(s))
    assert 'Вітаємо із приєднанням' in html
    assert 'office@test.com' in html
    s.trainer_contract_email = 'curator@test.com'
    assert 'curator@test.com' in str(svc.faq_html(s))


def test_faq_is_sanitized():
    s = SiteSettings.get()
    s.trainer_faq_html = '<p>ok {email}</p><script>alert(1)</script>'
    html = str(svc.faq_html(s))
    assert '<script>' not in html
    assert '<p>ok ' in html


def test_get_or_create_profile(trainer):
    p1 = svc.get_or_create_profile(trainer)
    p2 = svc.get_or_create_profile(trainer)
    assert p1 is p2 and p1.trainer_id == trainer.id


# --- B7: захід не зникає з кабінету в день проведення ---

from datetime import datetime, timedelta, timezone  # noqa: E402

from app.models.course_instance import CourseInstance  # noqa: E402

# 12:00 UTC = 15:00 за Києвом (літній час): київська доба 19.09 почалась
# 18.09 о 21:00 UTC.
_NOW = datetime(2026, 9, 19, 12, 0, tzinfo=timezone.utc)


def _dated(trainer, start, end=None):
    course = make_course()
    set_trainers(course, [trainer.id])
    inst = CourseInstance(course_id=course.id, status='published',
                          event_format='offline', start_date=start, end_date=end)
    db.session.add(inst)
    db.session.commit()
    return inst


def test_event_started_hour_ago_today_is_shown(trainer):
    inst = _dated(trainer, _NOW - timedelta(hours=1))
    assert _ids(svc.upcoming_instances(trainer, now=_NOW)) == [inst.id]


def test_event_started_after_kyiv_midnight_is_shown(trainer):
    """00:30 за Києвом -- це ще вчора за UTC, але вже сьогоднішній захід."""
    inst = _dated(trainer, datetime(2026, 9, 18, 21, 30, tzinfo=timezone.utc))
    assert _ids(svc.upcoming_instances(trainer, now=_NOW)) == [inst.id]


def test_multi_day_event_ending_tomorrow_is_shown(trainer):
    inst = _dated(trainer, _NOW - timedelta(days=2), _NOW + timedelta(days=1))
    assert _ids(svc.upcoming_instances(trainer, now=_NOW)) == [inst.id]


def test_event_ended_yesterday_is_hidden(trainer):
    _dated(trainer, _NOW - timedelta(days=2), _NOW - timedelta(days=1))
    # 23:30 за Києвом учора -- теж учора, хоч за UTC до півночі ще далеко.
    _dated(trainer, datetime(2026, 9, 18, 20, 30, tzinfo=timezone.utc))
    assert svc.upcoming_instances(trainer, now=_NOW) == []


def test_event_without_date_still_listed(trainer):
    inst = _dated(trainer, None)
    assert _ids(svc.upcoming_instances(trainer, now=_NOW)) == [inst.id]


def test_kyiv_day_start_utc():
    from app.utils import kyiv_day_start_utc
    assert kyiv_day_start_utc(_NOW) == datetime(2026, 9, 18, 21, 0, tzinfo=timezone.utc)
    # Зимовий час: +2, доба починається о 22:00 UTC.
    winter = datetime(2026, 1, 15, 10, 0, tzinfo=timezone.utc)
    assert kyiv_day_start_utc(winter) == datetime(2026, 1, 14, 22, 0, tzinfo=timezone.utc)


# --- B8: прийняття можна скасувати ---

def test_unaccept_proposal(trainer):
    p = TrainerCourseProposal(trainer_id=trainer.id, title='Т', theses=['a'],
                              status=TrainerCourseProposal.ACCEPTED)
    db.session.add(p)
    db.session.commit()
    svc.unaccept_proposal(p)
    assert p.status == TrainerCourseProposal.SUBMITTED
    with pytest.raises(svc.ProposalTransitionError):
        svc.unaccept_proposal(p)


def test_unaccept_rejects_draft(trainer):
    p = TrainerCourseProposal(trainer_id=trainer.id, title='Т', theses=['a'],
                              status=TrainerCourseProposal.DRAFT)
    with pytest.raises(svc.ProposalTransitionError):
        svc.unaccept_proposal(p)
