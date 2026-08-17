"""Виправлення дат реєстрації, привезених історичним імпортом з xlsx.

ЗВІДКИ ПРОБЛЕМА. `scripts/import_xlsx_data.py` ставить
`EventRegistration.created_at` рівним колонці «Дата реєстрації» з файлу
`3. Зареєстровані на захід.md`, БЕЗ жодної перевірки на осмисленість. Файл --
ручна таблиця менеджера, тож у ньому є описки, і вони приїхали в базу як є:

  * одна дата в майбутньому -- реєстрація 3593 (Кузьмич Сергій) датована
    27.10.2027 при заході 08.12.2025. Парний рядок того ж учасника на тому ж
    курсі в джерелі стоїть 25.11.2025, тож зʼїхав саме рік;
  * вісім реєстрацій датовані ПІЗНІШЕ за проведення, на яке зроблені
    (від +2 до +95 днів).

Список реєстрацій в адмінці MM Medic показує ці значення в колонці
«Зареєстровано» (дзеркало тягне `created_at` як `registered_at`), тому
менеджер бачить «зареєстрований у 2027 році» на заході, що вже минув.

ЩО РОБИТЬ СКРИПТ (у цьому порядку):

  1. точкові виправлення описок -- явним списком `TYPO_FIXES`, а не
     евристикою: «дата в майбутньому» не підказує, яка дата правильна, її
     дає лише читання джерела;
  2. підтягує решту імпортованих рядків, де `created_at > instance.start_date`,
     до дати проведення.

ЧОМУ ТІЛЬКИ ІМПОРТОВАНІ. Фільтр -- `admin_notes LIKE 'Імпорт з xlsx%'`.
Справжня реєстрація, зроблена на сайті в день заходу вже після його початку,
цілком законна (напр. 4309: захід 15.08.2026 11:00, запис 16:06) -- правило
«не пізніше заходу» до неї не застосовне, і клампити її не можна.

Скрипт ідемпотентний: повторний запуск нічого не змінює. За замовчуванням --
DRY-RUN (rollback наприкінці).

Запуск з кореня:
    python scripts/fix_imported_registration_dates.py           # dry-run
    python scripts/fix_imported_registration_dates.py --apply   # запис
"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

try:  # консоль Windows за замовчуванням cp1251 -- друкуємо в UTF-8
    sys.stdout.reconfigure(encoding='utf-8')
except (AttributeError, ValueError):
    pass

from app import create_app  # noqa: E402
from app.extensions import db  # noqa: E402
from app.models.course_instance import CourseInstance  # noqa: E402
from app.models.registration import EventRegistration  # noqa: E402

#: Та сама конвенція, що і в імпортері: у джерелі був тільки день, час
#: синтетичний. Інша зона чи інша година зробили б виправлений рядок
#: відмінним від сусідніх, привезених тим самим імпортом.
KYIV = timezone(timedelta(hours=3))
DEFAULT_TIME = (11, 0)

#: Позначка імпортера в `admin_notes` -- єдина ознака, за якою рядок можна
#: впевнено віднести до історичного завантаження.
IMPORT_MARK = 'Імпорт з xlsx'

#: Описки, розібрані вручну по джерелу: id -> (правильна дата, чому саме вона).
TYPO_FIXES = {
    3593: (
        datetime(2025, 10, 27, *DEFAULT_TIME, tzinfo=KYIV),
        'рядок джерела "27.10.2027" при заході 08.12.2025; парний рядок того '
        'самого учасника на тому самому курсі -- 25.11.2025, тобто зʼїхав рік',
    ),
}


def _fmt(value):
    return value.astimezone(KYIV).strftime('%d.%m.%Y %H:%M') if value else '—'


def collect(report):
    """Порахувати правки й видати їх списком UPDATE-ів. Нічого не комітить.

    Читаємо КОЛОНКАМИ, а не сутностями: прод-схема ІПРМ відстає від моделі
    (`quiz_passed_at`, `quiz_extra_attempts` ще не накочені), тож `SELECT *`
    від ORM падає з `column does not exist` -- на діагностиці, яка цих полів
    навіть не торкається. З тієї ж причини запис іде через `query.update()`,
    а не через мутацію завантаженого обʼєкта.
    """
    rows = (
        db.session.query(
            EventRegistration.id,
            EventRegistration.user_id,
            EventRegistration.instance_id,
            EventRegistration.admin_notes,
            EventRegistration.created_at,
            CourseInstance.start_date,
        )
        .join(CourseInstance, CourseInstance.id == EventRegistration.instance_id)
        .order_by(EventRegistration.id)
        .all()
    )

    for reg_id, user_id, instance_id, notes, created_at, start_date in rows:
        imported = (notes or '').startswith(IMPORT_MARK)

        fix = TYPO_FIXES.get(reg_id)
        if fix is not None:
            corrected, reason = fix
            if created_at != corrected:
                report['typo'].append(
                    (reg_id, instance_id, created_at, corrected, start_date, reason))
                report['updates'].append((reg_id, corrected))
                created_at = corrected
            else:
                report['already'] += 1

        if not imported:
            continue
        if start_date is None or created_at is None:
            continue
        if created_at <= start_date:
            continue

        report['clamped'].append((reg_id, user_id, instance_id, created_at, start_date))
        report['updates'].append((reg_id, start_date))

    for reg_id, value in report['updates']:
        (db.session.query(EventRegistration)
         .filter(EventRegistration.id == reg_id)
         .update({EventRegistration.created_at: value}, synchronize_session=False))

    return report


def main(apply):
    app = create_app()
    with app.app_context():
        report = {'typo': [], 'clamped': [], 'updates': [], 'already': 0}
        collect(report)

        print('===== ОПИСКИ (явний список) =====')
        for reg_id, instance_id, before, after, start_date, reason in report['typo']:
            print(f'  reg {reg_id}: {_fmt(before)} -> {_fmt(after)}'
                  f'   (захід {_fmt(start_date)})')
            print(f'      підстава: {reason}')
        if not report['typo']:
            print('  немає (уже виправлено або список порожній)')

        print('\n===== РЕЄСТРАЦІЯ ПІЗНІШЕ ЗАХОДУ -> ДАТА ЗАХОДУ =====')
        for reg_id, user_id, instance_id, before, after in report['clamped']:
            days = (before - after).days
            print(f'  reg {reg_id:>5}  user {user_id:>5}  inst {instance_id:>4}'
                  f'  {_fmt(before)} -> {_fmt(after)}  (+{days} дн)')
        if not report['clamped']:
            print('  немає')

        print(f'\nвиправлено описок: {len(report["typo"])}'
              f'   підтягнуто до дати заходу: {len(report["clamped"])}'
              f'   уже коректних із списку описок: {report["already"]}')

        if apply:
            db.session.commit()
            print('\n>>> ЗМІНИ ЗАСТОСОВАНО (commit).')
        else:
            db.session.rollback()
            print('\n>>> DRY-RUN: нічого не записано. Для запису: --apply')


if __name__ == '__main__':
    main('--apply' in sys.argv)
