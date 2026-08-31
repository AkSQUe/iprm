"""Проведення, на яке записались, не можна повернути в «Чернетку».

ЩО СТАЛОСЬ 31.08.2026. У дзеркалі партнера (MM Medic) не вистачило 25
реєстрацій. Три з них -- через цей шлях: проведення 52 (5 вересня, курс
«Терапевтична сила плазми») перевели в `draft` вже ПІСЛЯ того, як на нього
записалась і заплатила людина -- 1000 грн через LiqPay.

Для партнера це не «стало чернеткою», а «зникло»: `draft` не входить у
`ALLOWED_STATUSES` ендпоінта `/events`, тобто такий рядок не можна навіть
попросити. Партнер вирішив, що проведення видалили, прибрав його в себе -- і
реєстрація пішла слідом по CASCADE. На проведенні 37 так само загубилась
оплата на 7500 грн.

Правильна дія -- `cancelled`: він у видимих статусах саме для того, щоб
партнер ПОКАЗАВ «Захід скасовано», а не мовчки прибрав рядок.

Гвард перевіряється на ОБОХ шляхах запису статусу. Їх справді два, і форма
редагування довго обходила навіть перевірку переходів (`can_transition_to`),
пишучи `instance.status` напряму -- тобто половина гварда створювала б
враження, що шлях закритий.
"""
from datetime import datetime, timedelta, timezone

import pytest

from app.extensions import db
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.registration import EventRegistration
from app.models.user import User
from app.services import course_service


def _published_instance(status='published'):
    course = Course(title='Плазма', slug=f'guard-{status}-{id(object())}',
                    is_active=True, base_price=0)
    db.session.add(course)
    db.session.flush()
    inst = CourseInstance(
        course_id=course.id, status=status, event_format='offline',
        price=1000,
        start_date=datetime.now(timezone.utc) + timedelta(days=5),
    )
    db.session.add(inst)
    db.session.flush()
    return inst


def _register(inst, status='confirmed', payment_status='paid'):
    user = User(email=f'guard-{inst.id}-{status}@test.local',
                password='pw-guard-12345', first_name='Т', last_name='У')
    db.session.add(user)
    db.session.flush()
    reg = EventRegistration(
        user_id=user.id, instance_id=inst.id, phone='+380931889270',
        specialty='реабілітолог', workplace='клініка',
        status=status, payment_status=payment_status,
    )
    db.session.add(reg)
    db.session.flush()
    return reg


class TestUnpublishIsRefusedWhenPeopleAreRegistered:
    def test_status_route_path_is_blocked(self, app):
        inst = _published_instance()
        _register(inst)

        with pytest.raises(course_service.InvalidStatusTransition) as exc:
            course_service.change_instance_status(inst, 'draft')

        assert 'Скасовано' in str(exc.value)
        assert inst.status == 'published'

    def test_edit_form_path_is_blocked_too(self, app):
        """Другий шлях запису. Саме він писав статус повз усі перевірки."""
        inst = _published_instance()
        _register(inst)

        with pytest.raises(course_service.InvalidStatusTransition):
            course_service.ensure_status_change_allowed(inst, 'draft')

    def test_cancelled_is_allowed_and_is_the_way_out(self, app):
        """Захід знімається саме так -- і партнер це побачить."""
        inst = _published_instance()
        _register(inst)

        old, new = course_service.change_instance_status(inst, 'cancelled')

        assert (old, new) == ('published', 'cancelled')
        assert inst.status == 'cancelled'

    def test_an_active_instance_is_guarded_the_same_way(self, app):
        inst = _published_instance(status='active')
        _register(inst)

        with pytest.raises(course_service.InvalidStatusTransition):
            course_service.change_instance_status(inst, 'draft')


class TestWhatTheGuardMustNotBlock:
    """Ховати можна те, чого партнеру ще не показували, і те, від чого відмовились."""

    def test_an_empty_instance_can_go_back_to_draft(self, app):
        inst = _published_instance()

        old, new = course_service.change_instance_status(inst, 'draft')

        assert (old, new) == ('published', 'draft')

    def test_cancelled_registrations_do_not_hold_it(self, app):
        """Знята реєстрація нічого не тримає: копії партнера теж скасовані."""
        inst = _published_instance()
        _register(inst, status='cancelled', payment_status='refunded')

        old, new = course_service.change_instance_status(inst, 'draft')

        assert (old, new) == ('published', 'draft')

    def test_a_draft_instance_is_not_touched(self, app):
        """Чернетка -> чернетка не є переходом, і гвард тут ні до чого."""
        inst = _published_instance(status='draft')
        _register(inst)

        course_service.ensure_status_change_allowed(inst, 'draft')

    def test_publishing_is_never_blocked(self, app):
        inst = _published_instance(status='draft')
        _register(inst)

        old, new = course_service.change_instance_status(inst, 'published')

        assert (old, new) == ('draft', 'published')

    def test_an_unsaved_instance_has_nothing_to_count(self, app):
        """`live_registration_count` не має падати на об'єкті без id."""
        assert course_service.live_registration_count(CourseInstance()) == 0
