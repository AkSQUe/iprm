"""Phase 2: перенести дані з events у courses + course_instances.

Для кожного Event створюється рівно один Course (каталог) + один CourseInstance
(проведення). ProgramBlock.course_id та EventRegistration.instance_id
заповнюються через mapping. Таблиця events, її FK-колонка в
program_blocks та event_registrations наразі НЕ чіпаються -- це зробить
Phase 7 після деплою нової адмінки.

Revision ID: a3b4c5d6e7f8
Revises: d1e2f3a4b5c6
Create Date: 2026-04-21 00:30:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = 'a3b4c5d6e7f8'
down_revision = 'd1e2f3a4b5c6'
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()

    events = conn.execute(sa.text("""
        SELECT id, title, slug, subtitle, description, short_description,
               event_type, event_format, status, start_date, end_date,
               max_participants, price, location, online_link,
               hero_image, card_image, cpd_points,
               target_audience, tags, speaker_info, agenda, faq,
               is_featured, is_active, created_by, trainer_id,
               created_at, updated_at
        FROM events
        ORDER BY id
    """)).fetchall()

    event_to_course = {}
    event_to_instance = {}

    for ev in events:
        # 1) Course (каталог -- контентні поля)
        course_row = conn.execute(sa.text("""
            INSERT INTO courses (
                title, slug, subtitle, description, short_description,
                event_type, hero_image, card_image,
                target_audience, tags, speaker_info, agenda, faq,
                base_price, cpd_points, max_participants,
                trainer_id, created_by,
                is_active, is_featured,
                created_at, updated_at
            ) VALUES (
                :title, :slug, :subtitle, :description, :short_description,
                :event_type, :hero_image, :card_image,
                CAST(:target_audience AS JSON), CAST(:tags AS JSON),
                :speaker_info, :agenda, CAST(:faq AS JSON),
                :base_price, :cpd_points, :max_participants,
                :trainer_id, :created_by,
                :is_active, :is_featured,
                :created_at, :updated_at
            )
            RETURNING id
        """), {
            'title': ev.title,
            'slug': ev.slug,
            'subtitle': ev.subtitle,
            'description': ev.description,
            'short_description': ev.short_description,
            'event_type': ev.event_type,
            'hero_image': ev.hero_image,
            'card_image': ev.card_image,
            'target_audience': _to_json(ev.target_audience),
            'tags': _to_json(ev.tags),
            'speaker_info': ev.speaker_info,
            'agenda': ev.agenda,
            'faq': _to_json(ev.faq),
            'base_price': ev.price or 0,
            'cpd_points': ev.cpd_points,
            'max_participants': ev.max_participants,
            'trainer_id': ev.trainer_id,
            'created_by': ev.created_by,
            'is_active': ev.is_active if ev.is_active is not None else True,
            'is_featured': ev.is_featured if ev.is_featured is not None else False,
            'created_at': ev.created_at,
            'updated_at': ev.updated_at,
        }).fetchone()
        course_id = course_row.id
        event_to_course[ev.id] = course_id

        # 2) CourseInstance (проведення -- дата/формат/локація)
        instance_row = conn.execute(sa.text("""
            INSERT INTO course_instances (
                course_id,
                start_date, end_date,
                event_format,
                price, cpd_points, max_participants,
                location, online_link,
                trainer_id,
                status,
                created_at, updated_at
            ) VALUES (
                :course_id,
                :start_date, :end_date,
                :event_format,
                NULL, NULL, NULL,
                :location, :online_link,
                NULL,
                :status,
                :created_at, :updated_at
            )
            RETURNING id
        """), {
            'course_id': course_id,
            'start_date': ev.start_date,
            'end_date': ev.end_date,
            'event_format': ev.event_format,
            'location': ev.location,
            'online_link': ev.online_link,
            'status': ev.status or 'draft',
            'created_at': ev.created_at,
            'updated_at': ev.updated_at,
        }).fetchone()
        event_to_instance[ev.id] = instance_row.id

    # 3) ProgramBlock.course_id -- заповнюємо через mapping
    for event_id, course_id in event_to_course.items():
        conn.execute(
            sa.text("UPDATE program_blocks SET course_id = :cid WHERE event_id = :eid"),
            {'cid': course_id, 'eid': event_id},
        )

    # 4) EventRegistration.instance_id
    for event_id, instance_id in event_to_instance.items():
        conn.execute(
            sa.text("UPDATE event_registrations SET instance_id = :iid WHERE event_id = :eid"),
            {'iid': instance_id, 'eid': event_id},
        )


def downgrade():
    conn = op.get_bind()
    # Очищаємо прив'язки на нові сутності, потім видаляємо рядки з нових таблиць.
    conn.execute(sa.text("UPDATE event_registrations SET instance_id = NULL"))
    conn.execute(sa.text("UPDATE program_blocks SET course_id = NULL"))
    conn.execute(sa.text("DELETE FROM course_instances"))
    conn.execute(sa.text("DELETE FROM course_requests"))
    conn.execute(sa.text("DELETE FROM courses"))


def _to_json(value):
    """Python list/dict/None -> JSON-серіалізований рядок для psycopg/pg8000.

    SQLAlchemy CAST(:col AS JSON) чекає на текст. None передаємо як None
    (буде NULL у БД), все інше -- json.dumps.
    """
    if value is None:
        return None
    if isinstance(value, str):
        return value
    import json
    return json.dumps(value, ensure_ascii=False)
