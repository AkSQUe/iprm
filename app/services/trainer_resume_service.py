"""Резюме тренерів PDF-таблицею для подачі заходу до реєстру БПР.

Реєстр колонок нижче -- ОДНЕ джерело істини на трьох споживачів: діалог
вибору колонок, шапка PDF і витягання значень у клітинки. Якби підписи жили
в шаблоні, а витягання в маршруті, вони розійшлися б на першій же правці --
і в шапці «Освіта» стояла б над посадами.

Реквізити ФОП, адреси реєстрації та ЄДРПОУ тут НЕМАЄ і бути не повинно:
документ їде в пакеті до реєстру БПР, а замаскований IBAN у поданому
документі виглядав би гірше за його відсутність.
"""
from collections import namedtuple

ResumeColumn = namedtuple('ResumeColumn', 'key label getter requires')


def _profile_field(name):
    """Значення поля анкети; порожньо, якщо анкети ще немає."""
    def getter(trainer):
        profile = trainer.profile
        value = getattr(profile, name, None) if profile is not None else None
        return (value or '').strip() if isinstance(value, str) else (value or '')
    return getter


def _full_name(trainer):
    """ПІБ з анкети, інакше з довідника.

    Тренер без анкети мусить дати рядок із іменем і порожніми клітинками:
    для подачі важливо бачити, кого бракує, а не отримати таблицю, з якої
    людина мовчки зникла.
    """
    profile = trainer.profile
    if profile is not None and (profile.full_name or '').strip():
        return profile.full_name.strip()
    return (trainer.full_name or '').strip()


def _birth_date(trainer):
    profile = trainer.profile
    value = profile.birth_date if profile is not None else None
    return value.strftime('%d.%m.%Y') if value else ''


COLUMNS = (
    ResumeColumn('full_name', 'ПІБ', _full_name, None),
    ResumeColumn('education', 'Освіта',
                 _profile_field('education'), None),
    ResumeColumn('position_titles', 'Посада та регалії',
                 _profile_field('position_titles'), None),
    ResumeColumn('workplace', 'Місце роботи, місто',
                 _profile_field('workplace'), None),
    ResumeColumn('professional_certificates', 'Професійні сертифікати',
                 _profile_field('professional_certificates'), None),
    ResumeColumn('phone', 'Телефон', _profile_field('phone'), None),
    ResumeColumn('email', 'Ел. пошта', _profile_field('email'), None),
    ResumeColumn('social_links', 'Соцмережі',
                 _profile_field('social_links'), None),
    # Персональні дані: та сама межа, що вже діє в анкеті адмінки
    # (TrainerProfile.PRIVATE_FIELDS -- видно лише з trainers.finance).
    ResumeColumn('birth_date', 'Дата народження', _birth_date,
                 'trainers.finance'),
)

# Ядро резюме БПР -- обрані за замовчуванням.
DEFAULT_KEYS = (
    'full_name', 'education', 'position_titles', 'workplace',
    'professional_certificates',
)


def available_columns(user):
    """Колонки, доступні цьому користувачу."""
    from app.rbac import has_permission

    return [c for c in COLUMNS
            if c.requires is None or has_permission(user, c.requires)]


def normalize_keys(raw_keys, user):
    """Обрані ключі -> канонічний порядок реєстру, без невідомих і заборонених.

    Порядок саме канонічний, а не порядок кліків: два вивантаження того самого
    набору мають дати однаковий документ. Порожній набір падає на дефолт.
    """
    allowed = [c.key for c in available_columns(user)]
    picked = {k for k in (raw_keys or []) if k in allowed}
    if not picked:
        return [k for k in DEFAULT_KEYS if k in allowed]
    return [k for k in allowed if k in picked]


def build_rows(trainers, keys):
    """Рядок на тренера, клітинка на колонку -- у порядку keys."""
    by_key = {c.key: c for c in COLUMNS}
    return [[str(by_key[k].getter(t) or '') for k in keys] for t in trainers]


def labels_for(keys):
    """Підписи шапки в тому ж порядку -- з того самого реєстру."""
    by_key = {c.key: c for c in COLUMNS}
    return [by_key[k].label for k in keys]


def render_pdf(trainers, keys, title=None):
    """PDF-таблиця резюме. Рядок -- тренер, колонка -- поле анкети."""
    from flask import current_app, render_template
    # WeasyPrint імпортуємо ліниво: на машинах без GTK імпорт може падати,
    # і він не має валити старт застосунку.
    from weasyprint import HTML

    html = render_template(
        'admin/trainer_resume_pdf.html',
        title=title or 'Резюме тренерів',
        labels=labels_for(keys),
        rows=build_rows(trainers, keys),
    )
    return HTML(string=html, base_url=current_app.static_folder).write_pdf()
