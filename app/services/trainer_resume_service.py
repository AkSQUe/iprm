"""Резюме тренерів у PDF для подачі заходу до реєстру БПР.

Два виходи з одних даних: офіційна форма «Резюме викладача/тренера» (аркуш
на тренера, `render_form_pdf`) -- те, що вкладається в пакет документів, і
зведена таблиця (рядок на тренера, `render_pdf`) -- для огляду.

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
    ResumeColumn('specialty', 'Спеціальність',
                 _profile_field('specialty'), None),
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

# Ядро резюме БПР -- обрані за замовчуванням: усе, з чого складається
# офіційна форма (FORM_ROWS нижче). Без телефону й пошти перше ж
# вивантаження форми мало б порожні «Засоби зв'язку». Дата народження тут
# теж, але `normalize_keys` пропускає її лише тим, хто має trainers.finance.
DEFAULT_KEYS = (
    'full_name', 'birth_date', 'email', 'phone', 'education', 'specialty',
    'position_titles', 'workplace', 'professional_certificates',
)

# Офіційна форма «Резюме викладача/тренера» для пакета документів до реєстру
# БПР: (підпис рядка форми, ключі колонок реєстру, з яких він складається).
# Підписи й порядок -- дослівно з форми. Дані -- з тих самих геттерів COLUMNS,
# тож форма й таблиця не можуть розійтися в тому, що показують.
# «Інші відомості» -- посада та регалії: окремого рядка для них форма не має.
# Спеціальність -- так само без свого рядка, тож іде в рядок освіти.
FORM_ROWS = (
    ('Прізвище, власне ім’я, по батькові (за наявності)', ('full_name',)),
    ('Дата народження', ('birth_date',)),
    ('Засоби зв’язку (електронна адреса, номер телефону)', ('email', 'phone')),
    ('Освіта (рівень освіти та навчальні заклади)', ('education', 'specialty')),
    ('Місце роботи', ('workplace',)),
    ('Професійні сертифікати', ('professional_certificates',)),
    ('Інші відомості', ('position_titles',)),
)


# Підпис значення всередині рядка форми, де воно стоїть поруч з іншими:
# «Дерматовенерологія» під назвою закладу читалась би як ще один заклад.
FORM_CAPTIONS = {'specialty': 'Спеціальність: '}


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


def load_trainers(ids):
    """Тренери за id -- у порядку `ids`, з анкетою наперед.

    Порядок саме запиту, а не БД: адмін обирає тренерів у тому порядку, у
    якому вони йдуть у поданні заходу. Анкета вантажиться одним запитом разом
    із тренерами -- кожна клітинка таблиці читає поле анкети, і ліниво це
    був би окремий запит на кожен рядок документа. Невідомі id відкидаються.
    """
    from sqlalchemy.orm import joinedload

    from app.models.trainer import Trainer

    if not ids:
        return []
    found = (
        Trainer.query.options(joinedload(Trainer.profile))
        .filter(Trainer.id.in_(ids)).all()
    )
    by_id = {t.id: t for t in found}
    return [by_id[i] for i in ids if i in by_id]


def build_rows(trainers, keys):
    """Рядок на тренера, клітинка на колонку -- у порядку keys."""
    by_key = {c.key: c for c in COLUMNS}
    return [[str(by_key[k].getter(t) or '') for k in keys] for t in trainers]


def labels_for(keys):
    """Підписи шапки в тому ж порядку -- з того самого реєстру."""
    by_key = {c.key: c for c in COLUMNS}
    return [by_key[k].label for k in keys]


def build_form(trainers, keys):
    """Сторінка форми на тренера: [[(підпис рядка, значення), ...], ...].

    Рядки -- ЗАВЖДИ всі й у порядку офіційної форми. Вибір колонок вирішує,
    що ЗАПОВНИТИ, а не що показати: без рядка документ перестав би бути тією
    формою, яку приймає реєстр. Невибраний чи недоступний (дата народження
    без trainers.finance -- `normalize_keys` її вже відкинув) рядок лишається
    порожнім для ручного заповнення. Кілька колонок в одному рядку (пошта й
    телефон) -- окремими рядками тексту.

    Тренерів -- з `load_trainers`: анкети там приходять разом із ними, і цикл
    нижче не робить жодного запиту.
    """
    by_key = {c.key: c for c in COLUMNS}
    picked = set(keys)
    pages = []
    for trainer in trainers:
        rows = []
        for label, row_keys in FORM_ROWS:
            parts = []
            for k in row_keys:
                value = str(by_key[k].getter(trainer) or '').strip() if k in picked else ''
                if value:
                    parts.append(FORM_CAPTIONS.get(k, '') + value)
            rows.append((label, '\n'.join(parts)))
        pages.append(rows)
    return pages


def render_form_html(trainers, keys):
    """HTML офіційної форми -- окремо від PDF, щоб його можна було перевірити
    без WeasyPrint (на машинах без GTK він не імпортується)."""
    from flask import render_template

    return render_template('admin/trainer_resume_form_pdf.html',
                           pages=build_form(trainers, keys))


def render_form_pdf(trainers, keys):
    """PDF офіційної форми: книжковий аркуш на кожного тренера."""
    from flask import current_app
    from weasyprint import HTML

    return HTML(string=render_form_html(trainers, keys),
                base_url=current_app.static_folder).write_pdf()


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
