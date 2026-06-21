"""Seed an ISOLATED sqlite DB for visual flow preview.

ХАРД-ЗАХИСТ: скрипт відмовляється працювати, якщо SQLALCHEMY_DATABASE_URI
не вказує на sqlite -- щоб ніколи не зачепити спільну прод-БД.
"""
import os
from datetime import datetime, timedelta, timezone

# Має бути виставлено ще до імпорту create_app (config читає DATABASE_URL).
os.environ.setdefault('FLASK_CONFIG', 'development')

from app import create_app
from app.extensions import db

app = create_app('development')

with app.app_context():
    uri = app.config['SQLALCHEMY_DATABASE_URI']
    assert uri.startswith('sqlite'), f'SAFETY ABORT: not sqlite -> {uri}'
    print('DB URI:', uri)

    db.drop_all()
    db.create_all()

    from app.models.site_settings import SiteSettings
    from app.models.trainer import Trainer
    from app.models.course import Course
    from app.models.course_instance import CourseInstance
    from app.models.user import User

    ss = SiteSettings.get()
    ss.website_url = 'http://127.0.0.1:5050'
    ss.company_legal_name = 'ПО "ІПРМ"'
    ss.liqpay_public_key = 'sandbox_i00000000000'
    ss.liqpay_private_key = 'sandbox_secret_demo_key'

    trainer = Trainer(full_name='Валерія Гусак', slug='gusak-valeriia', is_active=True)
    db.session.add(trainer)
    db.session.flush()

    course = Course(
        title='Плазмотерапія: базовий курс',
        slug='plasma-base',
        subtitle='Сучасні протоколи PRP у дерматології та косметології',
        short_description='Дводенний практичний курс із плазмотерапії для лікарів.',
        description='Поглиблений практичний курс із сучасних протоколів PRP.',
        event_type='course',
        base_price=2500,
        cpd_points=12,
        max_participants=30,
        is_active=True,
        trainer_id=trainer.id,
        bpr_event_number='BPR-2026-001',
    )
    db.session.add(course)
    db.session.flush()

    start = datetime.now(timezone.utc) + timedelta(days=21)
    inst = CourseInstance(
        course_id=course.id,
        status='active',
        event_format='online',
        price=2500,
        cpd_points=12,
        max_participants=30,
        start_date=start,
        end_date=start + timedelta(hours=6),
        online_link='https://zoom.us/j/demo',
        trainer_id=trainer.id,
    )
    db.session.add(inst)

    user = User.create_with_password(
        'demo.participant@example.com', 'DemoPass123',
        first_name='Іван', last_name='Петренко', email_confirmed=True,
        is_admin=True,
    )

    db.session.commit()
    print('Seeded: course=%s instance=%s user=%s' % (course.slug, inst.id, user.email))
    print('INSTANCE_ID=%s' % inst.id)
    print('COURSE_SLUG=%s' % course.slug)
