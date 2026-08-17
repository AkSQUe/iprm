"""Flask CLI commands.

Старий seed_courses (на базі Event моделі) видалено -- Events замінено
на Course+CourseInstance через міграцію. Нові курси створюються через
/admin/courses або імпорт (TBD).

Одноразові data-міграції медіа (blog/trainer/course-media-migrate, Фази 3-5)
вже відпрацювали на prod і прибрані разом із legacy-колонками (Фаза 6).

seed-plazmogel -- заливка контенту продажної сторінки курсу плазмогелю.
Свідомо команда, а не міграція: це контент, і редакція мусить могти
переписати кожне поле в адмінці, не воюючи з alembic.
"""
from datetime import timedelta
from decimal import Decimal

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
        # М'яко видалені не чіпаємо: у них власний власник -- purge_soft_deleted
        # із витримкою на відкат.
        MediaFile.alive()
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


# ---------------------------------------------------------------------------
# Контент продажної сторінки курсу плазмогелю (еталон
# IPRM-plazmogel-selling-landing.html). Тексти лежать у коді, а не в
# міграції: це КОНТЕНТ, і редакція має могти переписати кожне поле в
# адмінці. Команда лише заповнює порожнє й нічого не затирає без --force.
# ---------------------------------------------------------------------------

PLAZMOGEL_SLUG = 'plasomgel-v-estetichiy-medicini'

# Скалярні поля курсу. Ключ -- колонка Course, значення -- текст еталона.
PLAZMOGEL_TEXTS = {
    'practice_note_title': 'Ви не просто дивитеся — ви робите',
    'practice_note_text': (
        'Ключова цінність практикуму — постановка руки. Тренер контролює '
        'виконання і дає персональні рекомендації, щоб після навчання не '
        'залишилося питання «а чи правильно я роблю?».'
    ),
    'gallery_intro': (
        'Не вебінар і не демонстрація з останнього ряду: учасники працюють '
        'з обладнанням, матеріалом і технікою підготовки під наглядом тренера.'
    ),
    'final_cta_text': (
        'Обидва тарифи включають очне навчання, практику та постановку руки. '
        'Оберіть формат участі та закріпіть місце в групі.'
    ),
}

PLAZMOGEL_PROOF_STATS = [
    {'value': '6+', 'label': 'проведених груп за програмою'},
    {'value': '100%', 'label': 'очна практика під контролем'},
    {'value': '13 років', 'label': 'досвіду тренера в косметології'},
    {'value': '1 метод', 'label': 'який розширює ваш прайс'},
]

PLAZMOGEL_BENEFITS = [
    {
        'title': 'Готуєте плазмогель прогнозовано',
        'text': 'Розумієте різницю між PRP, PPP і PRF, температурні режими та '
                'вибір форми препарату під конкретну задачу.',
    },
    {
        'title': 'Працюєте впевнено руками',
        'text': 'Відпрацьовуєте техніку введення на практиці. Тренер бачить '
                'вашу роботу, коригує кут, глибину та рух.',
    },
    {
        'title': 'Аргументуєте метод пацієнту',
        'text': 'Пояснюєте показання, обмеження та очікуваний результат '
                'простою мовою — без завищених обіцянок.',
    },
    {
        'title': 'Додаєте нову послугу',
        'text': 'Отримуєте готовий протокол, логіку ціноутворення та '
                'розуміння, як інтегрувати процедуру у свій прайс.',
    },
    {
        'title': 'Уникаєте типових помилок',
        'text': 'Знаєте, де найчастіше втрачається якість препарату та як не '
                'допустити помилок на етапі підготовки.',
    },
    {
        'title': 'Підтверджуєте розвиток',
        'text': 'Отримуєте сертифікат учасника та 12 балів БПР за освітній захід.',
    },
]

# Перша колонка секції "для кого". Друга колонка ("є питання?") -- у самому
# партіалі: людині, яка сумнівається, потрібен вихід, а не поле в базі.
PLAZMOGEL_AUDIENCE = [
    'дерматолог або косметолог із медичною освітою',
    'вже працюєте з аутологічною плазмою',
    'хочете розширити практику природним біостимулятором і філером',
    'цінуєте малу групу та персональну корекцію техніки',
    'плануєте впровадити процедуру одразу після навчання',
]

PLAZMOGEL_FAQ = [
    {
        'question': 'Чи можна йти на курс без досвіду роботи з плазмою?',
        'answer': 'Ця програма розрахована на лікарів і косметологів, які вже '
                  'знайомі з базовими принципами аутологічної плазми. Якщо '
                  'досвіду немає, залиште заявку — порадимо базовий курс.',
    },
    {
        'question': 'Чи буде практика саме моїми руками?',
        'answer': 'Так. Ви готуєте плазмогель і відпрацьовуєте техніки '
                  'введення під контролем тренера. Мала група дозволяє '
                  'приділити увагу кожному.',
    },
    {
        'question': 'Що входить у вартість?',
        'answer': 'Навчання, матеріали для практики, робота з обладнанням, '
                  'покроковий протокол, сертифікат учасника та 12 балів БПР.',
    },
    {
        'question': 'Чим відрізняється тариф із менторством?',
        'answer': 'Після практикуму ви проводите один прийом власного '
                  'пацієнта із супроводом ментора: від плану процедури до '
                  'персонального зворотного зв’язку.',
    },
    {
        'question': 'Де відбудеться навчання?',
        'answer': 'У Києві, вул. Андрія Верхогляда, 2а, клініка «Мультимед». '
                  'Точний час і організаційні деталі менеджер підтвердить '
                  'після реєстрації.',
    },
]

PLAZMOGEL_PROGRAM = [
    {
        'heading': 'Теоретичний блок',
        'items': [
            'Можливості аутологічної плазми в естетичній медицині.',
            'PRP, PPP, PRF: характеристики та клінічне призначення.',
            'Обладнання і витратні матеріали.',
            'Особливості отримання плазмогелю.',
            'Температурні режими підготовки.',
            'Показання залежно від клінічної задачі.',
        ],
    },
    {
        'heading': 'Практичний блок',
        'items': [
            'Підготовка обладнання до роботи.',
            'Покрокове приготування плазмогелю.',
            'Техніки введення під контролем тренера.',
            'Вибір методики залежно від показань.',
            'Індивідуальна робота кожного учасника.',
            'Корекція техніки та розбір практичних питань.',
        ],
    },
]

# Підписи галереї -- за порядком фото (MediaFile.sort_order). Прив'язати їх
# інакше нічим: імена файлів у реєстрі свої ({slug}-gallery-N), а не з
# еталона, тож збіг -- позиційний.
PLAZMOGEL_GALLERY_CAPTIONS = [
    'Навчання в обладнаному клінічному кабінеті',
    'Покрокове приготування плазмогелю',
    'Практика на моделі під наглядом тренера',
    'Робота з центрифугою та термостатом',
    'Контроль техніки та персональні підказки',
    'Постановка руки на реальній практиці',
]

PLAZMOGEL_TRAINER_HIGHLIGHTS = [
    {'value': '13 років', 'label': 'у косметології'},
    {'value': '11 років', 'label': 'у дерматології'},
    {'value': 'Практик', 'label': 'із клінічними кейсами'},
]

# Тарифи проведення. `names` -- варіанти назви, за якими шукаємо наявний
# тариф: на проді менторський тариф міг бути названий і за шаблоном моделі
# ("Практикум з менторством"), і як в еталоні.
PLAZMOGEL_TARIFFS = [
    {
        'names': ('Практикум',),
        'price': Decimal('10000'),
        'badge': None,
        'is_featured': False,
        'sort_order': 10,
        'description': '\n'.join([
            'Очне навчання в малій групі',
            'Теорія та покроковий протокол',
            'Демонстрація процедури тренером',
            'Практичне відпрацювання',
            'Постановка руки та корекція техніки',
            'Сертифікат і 12 балів БПР',
        ]),
    },
    {
        'names': ('Практикум + менторство', 'Практикум з менторством'),
        'price': Decimal('15000'),
        'badge': 'З підтримкою після курсу',
        'is_featured': True,
        'sort_order': 20,
        # Рядок із "+" -- перевага над базовим тарифом (див.
        # InstanceTariff.description_entries), а не окреме поле.
        'description': '\n'.join([
            'Усе, що входить до практикуму',
            '+1 прийом власного пацієнта із супроводом',
            '+Допомога з плануванням процедури',
            '+Персональний зворотний зв’язок',
            '+Можливість розширити супровід до 10 прийомів',
        ]),
    },
]

# Плитки "що учасники цінують" з еталона. В еталоні вони без автора й без
# оцінки, а Review показує підпис і п'ять зірок -- тому створюємо їх
# ЧЕРНЕТКАМИ: домалювати комусь оцінку від його імені команда не має права.
PLAZMOGEL_REVIEWS = [
    {
        'author_name': 'Учасники практикуму',
        'text': 'Персональну корекцію: тренер бачить роботу кожного учасника '
                'й допомагає виправити техніку в моменті.',
    },
    {
        'author_name': 'Учасники практикуму',
        'text': 'Малу групу: достатньо часу на запитання, практику та розбір '
                'індивідуальних клінічних ситуацій.',
    },
    {
        'author_name': 'Учасники практикуму',
        'text': 'Готовий алгоритм: після курсу залишається зрозуміла '
                'послідовність дій, а не лише теоретичний конспект.',
    },
]


def _is_blank(value):
    """Чи поле порожнє з погляду заливки.

    Порожній список важливий окремо: JSON-поля контенту мають default=list,
    тож "не заповнено" виглядає як [], а не як NULL.
    """
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, dict, tuple)):
        return not value
    return False


class _SeedLog:
    """Протокол заливки: заповнили / лишили людське / пропустили.

    Заливка контенту йде на живий прод, тож оператор мусить бачити рядок на
    кожне поле окремо, а не одне «готово» в кінці: інакше не відрізнити
    "заповнили" від "лишили як було".
    """

    def __init__(self):
        self.filled = 0
        self.kept = 0
        self.skipped = 0

    def fill(self, what):
        self.filled += 1
        click.echo('  + %s' % what)

    def keep(self, what):
        self.kept += 1
        click.echo('  = %s -- уже заповнено, лишаємо' % what)

    def skip(self, what, why):
        self.skipped += 1
        click.echo('  ! %s -- %s' % (what, why))


def _seed_value(log, obj, field, value, label, force):
    """Записати значення в поле, якщо воно порожнє (або якщо --force).

    Рівність порівнюємо перед записом: інакше --force рапортував би про
    перезапис там, де нічого не змінилося.
    """
    current = getattr(obj, field)
    if _is_blank(current):
        setattr(obj, field, value)
        log.fill(label)
    elif force and current != value:
        setattr(obj, field, value)
        log.fill('%s (перезаписано з --force)' % label)
    else:
        log.keep(label)


def _plazmogel_target_instance(course):
    """Проведення, на яке чіпляємо тарифи.

    Тарифи належать проведенню, а не курсу, тож заливка мусить вибрати одне:
    найближче майбутнє опубліковане (саме воно продається зі сторінки), а
    якщо майбутніх немає -- останнє за датою, щоб тексти не зникли зовсім.
    """
    from app.utils import ensure_utc
    from app.models.mixins import utcnow

    now = utcnow()
    published = [
        i for i in course.instances if i.status in ('published', 'active')
    ]
    upcoming = [
        i for i in published
        if i.start_date is None or ensure_utc(i.start_date) >= now
    ]
    if upcoming:
        return sorted(
            upcoming,
            key=lambda i: (i.start_date is None, ensure_utc(i.start_date) or now),
        )[0]
    pool = published or list(course.instances)
    if not pool:
        return None
    return sorted(
        pool, key=lambda i: (i.start_date is None, ensure_utc(i.start_date) or now),
    )[-1]


def _seed_plazmogel_tariffs(log, course, force):
    """Два тарифи еталона на актуальному проведенні курсу.

    Наявний тариф не перестворюємо: на нього вже посилаються реєстрації й
    посилання з листів (?tariff=<id>). Ціну наявного тарифу не рухаємо
    ніколи без --force -- це не текст, а домовленість із покупцем.
    """
    from app.extensions import db
    from app.models.instance_tariff import InstanceTariff

    instance = _plazmogel_target_instance(course)
    if instance is None:
        log.skip('тарифи', 'у курсу немає жодного проведення')
        return

    click.echo('Тарифи (проведення #%s, %s):' % (
        instance.id,
        instance.start_date.strftime('%d.%m.%Y') if instance.start_date else 'без дати',
    ))
    existing = list(instance.tariffs)
    by_name = {(t.name or '').strip().casefold(): t for t in existing}
    # Виділену картку ставимо лише коли її ще ніхто не обрав: інакше заливка
    # тихо зробила б виділеними два тарифи одразу.
    someone_featured = any(t.is_featured for t in existing)

    for spec in PLAZMOGEL_TARIFFS:
        tariff = next(
            (by_name[n.strip().casefold()] for n in spec['names']
             if n.strip().casefold() in by_name),
            None,
        )
        title = spec['names'][0]
        if tariff is None:
            tariff = InstanceTariff(
                instance_id=instance.id,
                name=title,
                price=spec['price'],
                description=spec['description'],
                badge=spec['badge'],
                is_featured=spec['is_featured'] and not someone_featured,
                event_format='offline',
                sort_order=spec['sort_order'],
                is_active=True,
            )
            db.session.add(tariff)
            if tariff.is_featured:
                someone_featured = True
            log.fill('тариф «%s» створено (%s грн)' % (title, spec['price']))
            continue

        log.keep('тариф «%s» уже існує (#%s)' % (tariff.name, tariff.id))
        _seed_value(log, tariff, 'description', spec['description'],
                    'тариф «%s»: склад' % tariff.name, force)
        if spec['badge']:
            _seed_value(log, tariff, 'badge', spec['badge'],
                        'тариф «%s»: прапорець' % tariff.name, force)
        if spec['is_featured']:
            if tariff.is_featured:
                log.keep('тариф «%s»: виділення' % tariff.name)
            elif someone_featured:
                log.skip('тариф «%s»: виділення' % tariff.name,
                         'виділений тариф уже обрано вручну')
            else:
                tariff.is_featured = True
                someone_featured = True
                log.fill('тариф «%s»: виділення' % tariff.name)
        if force and tariff.price != spec['price']:
            tariff.price = spec['price']
            log.fill('тариф «%s»: ціна %s грн (перезаписано з --force)'
                     % (tariff.name, spec['price']))


@click.command('seed-plazmogel')
@click.option('--slug', default=PLAZMOGEL_SLUG, show_default=True,
              help='Slug курсу, у який заливаємо контент.')
@click.option('--force', is_flag=True,
              help='Перезаписати вже заповнені поля текстами еталона.')
@click.option('--dry-run', is_flag=True,
              help='Показати, що буде змінено, і відкотити транзакцію.')
@with_appcontext
def seed_plazmogel(slug, force, dry_run):
    """Залити контент продажної сторінки курсу плазмогелю з еталона.

    Ідемпотентна: порожнє поле заповнює, заповнене лишає (щоб не з'їсти
    редакторську правку), --force перезаписує. Не міграція: контент має
    жити в адмінці, а не в alembic.

    \b
    Приклади:
      flask seed-plazmogel --dry-run
      flask seed-plazmogel
      flask seed-plazmogel --force
    """
    from app.extensions import db
    from app.models.course import Course
    from app.models.program_block import ProgramBlock
    from app.models.review import Review

    course = Course.query.filter_by(slug=slug).first()
    if course is None:
        click.echo('Курс зі slug «%s» не знайдено.' % slug, err=True)
        raise SystemExit(1)

    log = _SeedLog()
    click.echo('Курс #%s: %s' % (course.id, course.title))
    if dry_run:
        click.echo('DRY RUN: наприкінці транзакцію буде відкочено.')
    click.echo('')

    try:
        click.echo('Поля курсу:')
        _seed_value(log, course, 'proof_stats', PLAZMOGEL_PROOF_STATS,
                    'цифри довіри (4)', force)
        _seed_value(log, course, 'benefits', PLAZMOGEL_BENEFITS,
                    'картки результату (6)', force)
        _seed_value(log, course, 'target_audience', PLAZMOGEL_AUDIENCE,
                    'для кого курс (5 пунктів)', force)
        _seed_value(log, course, 'faq', PLAZMOGEL_FAQ, 'FAQ (5 питань)', force)
        for field, value in PLAZMOGEL_TEXTS.items():
            _seed_value(log, course, field, value, field, force)

        # --- блоки програми: одна одиниця, а не набір полів. Курс із уже
        #     заведеною програмою не доповнюємо -- редактор міг свідомо
        #     злити два блоки в один або переписати пункти.
        click.echo('Блоки програми:')
        if course.program_blocks and not force:
            log.keep('програма (%d блок(и) вже є)' % len(course.program_blocks))
        elif course.program_blocks and force:
            for block in list(course.program_blocks):
                db.session.delete(block)
            db.session.flush()
            for index, spec in enumerate(PLAZMOGEL_PROGRAM):
                db.session.add(ProgramBlock(
                    course_id=course.id, heading=spec['heading'],
                    items=list(spec['items']), sort_order=index,
                ))
            log.fill('програма (%d блоки, перезаписано з --force)'
                     % len(PLAZMOGEL_PROGRAM))
        else:
            for index, spec in enumerate(PLAZMOGEL_PROGRAM):
                db.session.add(ProgramBlock(
                    course_id=course.id, heading=spec['heading'],
                    items=list(spec['items']), sort_order=index,
                ))
            log.fill('програма (%d блоки)' % len(PLAZMOGEL_PROGRAM))

        # --- підписи галереї. Самі фото вантажить людина в адмінці:
        #     файлів еталона в репозиторії немає, тож команда лише підписує
        #     те, що вже прив'язане до курсу.
        click.echo('Галерея:')
        gallery = course.gallery
        if not gallery:
            log.skip('підписи галереї',
                     'до курсу не прив\'язано жодного фото (usage_type=gallery)')
        else:
            for index, media in enumerate(gallery):
                if index >= len(PLAZMOGEL_GALLERY_CAPTIONS):
                    log.skip('фото #%d' % (index + 1),
                             'в еталоні лише %d підписів'
                             % len(PLAZMOGEL_GALLERY_CAPTIONS))
                    continue
                _seed_value(log, media, 'caption',
                            PLAZMOGEL_GALLERY_CAPTIONS[index],
                            'підпис фото #%d' % (index + 1), force)
            missing = len(PLAZMOGEL_GALLERY_CAPTIONS) - len(gallery)
            if missing > 0:
                log.skip('%d підпис(и) галереї' % missing,
                         'у курсі лише %d фото з 6 -- довантажте в адмінці'
                         % len(gallery))

        # --- тарифи
        _seed_plazmogel_tariffs(log, course, force)

        # --- цифри тренера. Це дані ТРЕНЕРА, не курсу: вони показуються на
        #     кожній його сторінці, тому чіпаємо лише порожнє поле.
        click.echo('Тренер:')
        if course.trainer is None:
            log.skip('цифри тренера', 'у курсу не вказано тренера')
        else:
            _seed_value(log, course.trainer, 'highlights',
                        PLAZMOGEL_TRAINER_HIGHLIGHTS,
                        'цифри тренера «%s» (3)' % course.trainer.full_name,
                        force)

        # --- відгуки. Збіг шукаємо за текстом: так повторний запуск не
        #     плодить дублікатів, а видаляти чужі відгуки команда не має
        #     права навіть із --force.
        click.echo('Відгуки:')
        existing_texts = {
            (r.text or '').strip()
            for r in Review.alive().filter_by(course_id=course.id).all()
        }
        for spec in PLAZMOGEL_REVIEWS:
            if spec['text'].strip() in existing_texts:
                log.keep('відгук «%s...»' % spec['text'][:32])
                continue
            db.session.add(Review(
                author_name=spec['author_name'],
                text=spec['text'],
                rating=5,
                # Чернетка: в еталоні ці плитки без автора й без оцінки.
                # Публікує людина, коли підтвердить формулювання.
                is_published=False,
                course_id=course.id,
            ))
            log.fill('відгук-чернетка «%s...»' % spec['text'][:32])

        if dry_run:
            db.session.rollback()
        else:
            db.session.commit()
    except Exception as exc:  # noqa: BLE001 -- заливка або вся, або ніяка
        db.session.rollback()
        click.echo('\nПомилка, зміни відкочено: %s' % exc, err=True)
        raise SystemExit(1)

    click.echo('')
    click.echo('Заповнено: %d, лишено без змін: %d, пропущено: %d.'
               % (log.filled, log.kept, log.skipped))
    if dry_run:
        click.echo('DRY RUN: нічого не збережено.')
    if log.filled:
        click.echo('Відгуки створюються чернетками -- опублікуйте їх у '
                   '/admin/reviews, коли редакція підтвердить формулювання.')


@click.command('legal-docx')
@click.argument('pages', nargs=-1)
@click.option('--all', 'export_all', is_flag=True,
              help='Експортувати всі доступні сторінки.')
@click.option('--output-dir', default=None,
              help='Куди зберегти файли (типово docs/legal).')
@click.option('--no-seal', is_flag=True,
              help='Без підписного блоку з печаткою.')
@with_appcontext
def legal_docx(pages, export_all, output_dir, no_seal):
    """Експортувати юридичні сторінки сайту у .docx на фірмовому бланку.

    Текст береться з тих самих Jinja-шаблонів, що й публічні сторінки,
    тому документ не розходиться із сайтом.

    \b
    Приклади:
      flask legal-docx offer
      flask legal-docx offer privacy --output-dir build
      flask legal-docx --all
    """
    from app.services.legal_docx_service import (
        LEGAL_PAGES, LegalDocxError, export_page,
    )

    if export_all:
        targets = sorted(LEGAL_PAGES)
    elif pages:
        targets = list(pages)
    else:
        click.echo('Вкажіть сторінку або --all. Доступні: %s'
                   % ', '.join(sorted(LEGAL_PAGES)))
        return

    for page in targets:
        try:
            path = export_page(page, output_dir=output_dir,
                               with_seal=not no_seal)
        except LegalDocxError as exc:
            click.echo('Помилка (%s): %s' % (page, exc), err=True)
            raise SystemExit(1)
        click.echo('%s -> %s' % (page, path))


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
