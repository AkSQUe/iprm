"""Flask CLI commands.

Старий seed_courses (на базі Event моделі) видалено -- Events замінено
на Course+CourseInstance через міграцію. Нові курси створюються через
/admin/courses або імпорт (TBD).
"""
import click
from flask.cli import with_appcontext


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
