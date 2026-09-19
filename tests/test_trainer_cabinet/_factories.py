"""Фабрики тестових даних кабінету тренера.

Усі акаунти -- з префіксом 'tc-', їх прибирає autouse-фікстура в conftest.
"""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from app.extensions import db
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.registration import EventRegistration
from app.models.trainer import Trainer
from app.models.user import User
from tests.support.rbac import switch_user


def make_user(prefix='tc-'):
    user = User.create_with_password(
        f'{prefix}{uuid4().hex[:8]}@test.com', 'password123',
        first_name='Тест', last_name='Тренер', email_confirmed=True,
    )
    db.session.commit()
    return user


def make_trainer(user=None, is_active=True, name='Тренер Т.'):
    trainer = Trainer(
        full_name=name, slug=f'tc-{uuid4().hex[:10]}', is_active=is_active,
        user_id=user.id if user else None,
    )
    db.session.add(trainer)
    db.session.commit()
    return trainer


def make_course(title=None):
    course = Course(title=title or f'Курс {uuid4().hex[:4]}', slug=f'tc-{uuid4().hex[:10]}')
    db.session.add(course)
    db.session.commit()
    return course


def make_instance(course, *, days=7, status='published', event_format='offline',
                  max_participants=20):
    inst = CourseInstance(
        course_id=course.id, status=status, event_format=event_format,
        start_date=datetime.now(timezone.utc) + timedelta(days=days),
        max_participants=max_participants,
    )
    db.session.add(inst)
    db.session.commit()
    return inst


def make_registration(instance, *, status='confirmed', payment_status='unpaid',
                      participation_format=None):
    user = make_user()
    reg = EventRegistration(
        user_id=user.id, instance_id=instance.id, phone='+380671234567',
        specialty='Лікар', workplace='Клініка', status=status,
        payment_status=payment_status, participation_format=participation_format,
    )
    db.session.add(reg)
    db.session.commit()
    return reg


def login(client, user):
    return switch_user(client, user)
