"""Бекфіл вихідних вебхуків до партнера (mm-medic) для імпортованих заходів.

Імпорт розкладу (scripts/import_xlsx_data.py) додав/оновив CourseInstance
напряму через ORM. Лісенери (course_webhook_listener) ставлять вебхук у чергу
лише якщо на момент commit вебхук УВІМКНЕНО. Якщо його вмикають пізніше -- ці
заходи не досинхронізуються самі. Цей скрипт ставить у чергу event.updated для
кожного УНІКАЛЬНОГО курсу, якого торкнувся імпорт (payload несе лише slug --
mm-medic за ним підтягне всі заходи курсу через API).

Запуск з кореня:
    python scripts/backfill_partner_webhook.py            # dry-run (перевірка)
    python scripts/backfill_partner_webhook.py --apply     # поставити в чергу

Працює лише якщо вебхук УВІМКНЕНО в адмінці (partner_webhook_enabled + URL).
Інакше enqueue() нічого не створює -- спершу налаштуйте /admin/settings.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

try:
    sys.stdout.reconfigure(encoding='utf-8')
except (AttributeError, ValueError):
    pass

from app import create_app  # noqa: E402
from app.models.course import Course  # noqa: E402
from app.models.site_settings import SiteSettings  # noqa: E402
from app.services.webhook_queue import enqueue  # noqa: E402
from scripts.import_xlsx_data import parse_table, slug_for_title, FILE_SCHEDULE  # noqa: E402


def main(apply):
    app = create_app()
    with app.app_context():
        # Унікальні slug курсів, яких торкнувся імпорт розкладу.
        slugs = []
        for row in parse_table(FILE_SCHEDULE):
            slug = slug_for_title(row['Курс'])
            if slug and slug not in slugs:
                slugs.append(slug)

        course_by_slug = {c.slug: c for c in Course.query.filter(Course.slug.in_(slugs))}

        s = SiteSettings.get()
        enabled = s.partner_integration_enabled and s.partner_webhook_enabled
        url = (s.partner_webhook_url or '').strip()
        print('=== Конфіг вебхука ===')
        print(f'  integration_enabled: {s.partner_integration_enabled}')
        print(f'  webhook_enabled:     {s.partner_webhook_enabled}')
        print(f'  url:                 {url or "<порожній>"}')
        print(f'  secret:              {"<задано>" if s.partner_webhook_secret else "<порожній>"}')

        print(f'\n=== Курси для бекфілу ({len(slugs)}) ===')
        missing = [sl for sl in slugs if sl not in course_by_slug]
        for sl in slugs:
            c = course_by_slug.get(sl)
            print(f'  {"OK " if c else "??? "} {sl}' + (f'  (id={c.id})' if c else '  -- НЕ ЗНАЙДЕНО'))
        if missing:
            print(f'  ! Увага: {len(missing)} slug(ів) не знайдено серед курсів.')

        if not apply:
            print('\n>>> DRY-RUN: нічого не поставлено в чергу. Для запуску: --apply')
            if not (enabled and url):
                print('    УВАГА: вебхук вимкнено/без URL -- спершу увімкніть у /admin/settings,')
                print('    інакше --apply теж нічого не створить.')
            return

        if not (enabled and url):
            print('\n!!! Вебхук вимкнено або URL порожній -- enqueue нічого не створить.')
            print('    Увімкніть у /admin/settings і повторіть. Нічого не зроблено.')
            return

        queued = 0
        for sl in slugs:
            c = course_by_slug.get(sl)
            if not c:
                continue
            d = enqueue(c.id, c.slug, 'updated')
            if d:
                queued += 1
                print(f'  enqueued id={d.id}  {c.slug}')
        print(f'\n>>> Поставлено в чергу: {queued}. Планувальник у gunicorn розішле їх протягом ~1 хв.')


if __name__ == '__main__':
    main(apply='--apply' in sys.argv)
