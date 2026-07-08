"""Merge NRP online + offline into one course with per-instance formats

Revision ID: nrp_merge_20260708
Revises: courses_roi_20260708
Create Date: 2026-07-08 00:00:00.000000

Data migration (Дмитро, 08.07.2026): the catalog had two near-duplicate
courses "NRP. Neuro-Relax Protocol (онлайн)" and "(офлайн)". Online/offline
is a property of the run (CourseInstance.event_format), not the course, so:

1. Materialize effective values (price / cpd / max / trainer) onto the
   offline course's instances -- otherwise after the move they would fall
   back to the ONLINE course defaults (2500 замість 7500).
2. Move offline instances, requests, program blocks (sort_order +100 to
   append after the online programme) and media links to the online course.
3. Rename the merged course to "NRP. Neuro-Relax Protocol", merge tags.
4. Delete the offline course row. The old slug 301-redirects via
   LEGACY_REDIRECTS in app/courses/routes.py.

Defensive: no-op unless BOTH slugs exist. Downgrade is intentionally a
no-op (data merge is not mechanically reversible).
"""
from alembic import op
import sqlalchemy as sa
import json


revision = 'nrp_merge_20260708'
down_revision = 'courses_roi_20260708'
branch_labels = None
depends_on = None

KEEP_SLUG = 'nrp-neuro-relax-protocol'
DROP_SLUG = 'nrp-neuro-relax-protocol-offline'
MERGED_TITLE = 'NRP. Neuro-Relax Protocol'


def upgrade():
    conn = op.get_bind()
    rows = dict(conn.execute(
        sa.text('SELECT slug, id FROM courses WHERE slug IN (:keep, :drop)'),
        {'keep': KEEP_SLUG, 'drop': DROP_SLUG},
    ).fetchall())
    keep_id, drop_id = rows.get(KEEP_SLUG), rows.get(DROP_SLUG)
    if keep_id is None or drop_id is None:
        return

    params = {'keep': keep_id, 'drop': drop_id}

    # 1. Матеріалізуємо ефективні значення на проведеннях офлайн-курсу,
    #    щоб перенесення не змінило їхню фактичну ціну/ліміт/бали/тренера.
    conn.execute(sa.text('''
        UPDATE course_instances SET
            price = COALESCE(price, (SELECT base_price FROM courses WHERE id = :drop)),
            cpd_points = COALESCE(cpd_points, (SELECT cpd_points FROM courses WHERE id = :drop)),
            max_participants = COALESCE(max_participants, (SELECT max_participants FROM courses WHERE id = :drop)),
            trainer_id = COALESCE(trainer_id, (SELECT trainer_id FROM courses WHERE id = :drop))
        WHERE course_id = :drop
    '''), params)

    # 2. Переносимо все, що посилається на офлайн-курс.
    conn.execute(sa.text(
        'UPDATE course_instances SET course_id = :keep WHERE course_id = :drop'), params)
    conn.execute(sa.text(
        'UPDATE course_requests SET course_id = :keep WHERE course_id = :drop'), params)
    conn.execute(sa.text('''
        UPDATE program_blocks SET course_id = :keep, sort_order = sort_order + 100
        WHERE course_id = :drop
    '''), params)
    conn.execute(sa.text('''
        UPDATE media_files SET entity_id = :keep
        WHERE entity_type = 'course' AND entity_id = :drop
    '''), params)

    # 3. Об'єднана назва + злиті теги (union зі збереженням порядку keep-курсу).
    tag_rows = conn.execute(
        sa.text('SELECT id, tags FROM courses WHERE id IN (:keep, :drop)'),
        params,
    ).fetchall()
    tags_by_id = {}
    for cid, raw in tag_rows:
        tags_by_id[cid] = raw if isinstance(raw, list) else json.loads(raw or '[]')
    merged_tags = list(tags_by_id.get(keep_id, []))
    for tag in tags_by_id.get(drop_id, []):
        if tag not in merged_tags:
            merged_tags.append(tag)
    conn.execute(
        sa.text('UPDATE courses SET title = :title, tags = :tags WHERE id = :keep'),
        {'title': MERGED_TITLE, 'tags': json.dumps(merged_tags, ensure_ascii=False),
         'keep': keep_id},
    )

    # 4. Офлайн-курс більше нічим не тримається -- видаляємо.
    conn.execute(sa.text('DELETE FROM courses WHERE id = :drop'), params)


def downgrade():
    # Дані злито незворотно; відкат схеми не потрібен (schema не змінювалась).
    pass
