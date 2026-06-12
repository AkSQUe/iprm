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


@click.group('backup')
def backup_group():
    """Управління резервними копіями бази даних."""


@backup_group.command('create')
@click.option('--type', 'backup_type', default='full',
              type=click.Choice(['full', 'schema_only', 'data_only']),
              help='Тип резервної копії.')
@click.option('--description', '-d', default='', help='Опис копії.')
@with_appcontext
def backup_create(backup_type, description):
    """Створити резервну копію бази даних."""
    from app.services.backup_service import BackupService, BackupError

    click.echo(f'Створення резервної копії ({backup_type})...')
    try:
        backup = BackupService.create_backup(
            backup_type=backup_type,
            description=description,
        )
        click.echo(f'Готово: {backup.filename}')
        click.echo(f'  Розмір: {backup.file_size_display}')
        click.echo(f'  Тривалість: {backup.duration_seconds}с')
        click.echo(f'  Checksum: {backup.checksum_sha256[:16]}...')
    except BackupError as exc:
        click.echo(f'Помилка: {exc}', err=True)
        raise SystemExit(1)


@backup_group.command('list')
@click.option('--limit', default=20, type=int, help='Кількість записів.')
@with_appcontext
def backup_list(limit):
    """Показати список резервних копій."""
    from app.models.database_backup import DatabaseBackup

    backups = (
        DatabaseBackup.query
        .order_by(DatabaseBackup.created_at.desc())
        .limit(limit)
        .all()
    )

    if not backups:
        click.echo('Резервних копій немає.')
        return

    click.echo(f'{"ID":>5} {"Тип":<12} {"Статус":<12} {"Розмір":<10} {"Дата":<20} {"Опис"}')
    click.echo('-' * 80)
    for b in backups:
        click.echo(
            f'{b.id:>5} {b.backup_type:<12} {b.status:<12} '
            f'{b.file_size_display:<10} {b.created_at.strftime("%d.%m.%Y %H:%M"):<20} '
            f'{b.description or ""}'
        )


@backup_group.command('restore')
@click.argument('backup_id', type=int)
@click.option('--force', is_flag=True, help='Пропустити pre-restore копію.')
@click.option('--yes', is_flag=True, help='Підтвердити без питання.')
@with_appcontext
def backup_restore(backup_id, force, yes):
    """Відновити базу даних з резервної копії."""
    from app.services.backup_service import BackupService, BackupError
    from app.models.database_backup import DatabaseBackup

    backup = DatabaseBackup.query.get(backup_id)
    if not backup:
        click.echo(f'Копію #{backup_id} не знайдено.', err=True)
        raise SystemExit(1)

    click.echo(f'Відновлення з копії #{backup.id}: {backup.filename}')
    click.echo(f'  Тип: {backup.backup_type}, Дата: {backup.created_at}')

    if not yes:
        if not click.confirm('УВАГА: Це замінить поточну базу даних. Продовжити?'):
            click.echo('Скасовано.')
            return

    try:
        BackupService.restore_backup(backup_id, force=force)
        click.echo('Базу даних успішно відновлено.')
    except BackupError as exc:
        click.echo(f'Помилка: {exc}', err=True)
        raise SystemExit(1)


@backup_group.command('validate')
@click.argument('backup_id', type=int)
@with_appcontext
def backup_validate_cmd(backup_id):
    """Перевірити цілісність резервної копії."""
    from app.services.backup_service import BackupService, BackupError

    try:
        valid = BackupService.validate_backup(backup_id)
        if valid:
            click.echo(f'Копія #{backup_id}: цілісність підтверджена.')
        else:
            click.echo(f'Копія #{backup_id}: ПОШКОДЖЕНА!', err=True)
            raise SystemExit(1)
    except BackupError as exc:
        click.echo(f'Помилка: {exc}', err=True)
        raise SystemExit(1)


@backup_group.command('cleanup')
@click.option('--dry-run', is_flag=True, help='Лише показати, що буде видалено.')
@with_appcontext
def backup_cleanup_cmd(dry_run):
    """Видалити старі резервні копії за retention-політикою."""
    from app.services.backup_service import BackupService

    result = BackupService.cleanup_old_backups(dry_run=dry_run)

    if dry_run:
        click.echo(f'Dry run: буде видалено {result["would_delete"]} копій.')
        for item in result.get('backups', []):
            click.echo(f'  #{item["id"]} {item["filename"]} ({item["date"]})')
    else:
        click.echo(f'Очищення завершено: видалено {result["deleted"]} копій.')
