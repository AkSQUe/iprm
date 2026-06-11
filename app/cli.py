"""Flask CLI commands.

Старий seed_courses (на базі Event моделі) видалено -- Events замінено
на Course+CourseInstance через міграцію. Нові курси створюються через
/admin/courses або імпорт (TBD).

Одноразові data-міграції медіа (blog/trainer/course-media-migrate, Фази 3-5)
вже відпрацювали на prod і прибрані разом із legacy-колонками (Фаза 6).
"""
from datetime import timedelta

import click
from flask.cli import with_appcontext


@click.command('media-prune-orphans')
@click.option('--days', default=30, show_default=True, type=int,
              help='Видаляти непривʼязані медіа, старші за N днів.')
@click.option('--dry-run', is_flag=True, help='Лише показати, що буде видалено.')
@with_appcontext
def media_prune_orphans(days, dry_run):
    """Прибрати «осиротілі» медіа: завантажені, але не прив'язані до сутності.

    Редактори завантажують медіа у реєстр одразу (unattached), а прив'язують лише
    при збереженні сутності. Якщо допис/тренера/курс так і не зберегли, медіа
    лишається без прив'язки. Видаляємо такі (entity_type IS NULL) старші за --days.
    """
    from app.extensions import db
    from app.models.media_file import MediaFile
    from app.models.mixins import utcnow
    from app.services import media_service

    cutoff = utcnow() - timedelta(days=days)
    orphans = (
        MediaFile.query
        .filter(MediaFile.entity_type.is_(None), MediaFile.created_at < cutoff)
        .order_by(MediaFile.created_at.asc())
        .all()
    )
    if not orphans:
        click.echo('Осиротілих медіа не знайдено (старших за %d дн.).' % days)
        return
    for m in orphans:
        click.echo('%s %s (%s, %s)' % (
            'WOULD delete' if dry_run else 'delete', m.id, m.file_path, m.created_at))
        if not dry_run:
            media_service.delete_media(m)
    if dry_run:
        click.echo('\nDRY RUN: %d медіа було б видалено.' % len(orphans))
    else:
        db.session.commit()
        click.echo('\nВидалено %d осиротілих медіа.' % len(orphans))


@click.command('seed-courses')
@with_appcontext
def seed_courses():
    """Deprecated: seed тепер виконується через міграції.

    Команда залишена як no-op для сумісності з існуючими Makefile/doc
    посиланнями. Реальний seed виконується під час data-міграції
    a3b4c5d6e7f8 (Phase 2).
    """
    click.echo(
        'seed-courses: no-op. Контент курсів мігровано через '
        'alembic migration a3b4c5d6e7f8. Створюйте нові курси '
        'через /admin/courses.'
    )
