"""Ті самі структурні твердження -- на сторінках, що живуть із БД.

fetch_public_pages() бачить лише ендпоінти без обов'язкових параметрів,
тож курс, онлайн-курс, тренер, клініка й допис блогу до цього раунду не
перевіряв ЖОДЕН структурний сторож. Доведено відкотом: обидві правки
abs_url із Задачі 4 можна було повернути назад -- сюїта лишалась зеленою.

Фікстури тут навмисно мінімальні: сторінка мусить триматись на порожніх
полях так само, як на заповнених. Виняток -- зображення: доти жодна
фікстура не прикріплювала MediaFile, тож `image` НІКОЛИ не потрапляв у
JSON-LD, і десять викликів abs_url(...) у п'яти шаблонах (og:image і/або
image в JSON-LD -- blog/post.html, clinics/detail.html,
courses/detail.html, online/detail.html, trainers/detail.html) можна було
повернути до відносного шляху -- суїта лишалась зеленою: перевірка
абсолютності проходила над порожнечею. Тепер кожна сутність має реальне
зображення, і `{% if x.photo_full %}`-гілки справді виконуються.

Раунд 1 цього фіксу сам недорахував один виклик: online/detail.html:11
бере og:image з `course.hero_src`, а не з `card_src` (на відміну від
courses/detail.html) -- фікстура онлайн-курсу прикріпила лише
card_media_id, і `{% if course.hero_src %}` лишалась хибною. Дев'ять із
десяти справді почали виконуватись, десятий -- ні, а докстрінг і звіт
раунду 1 стверджували "усі десять". Тепер online-фікстура несе окремий
`hero_media_id`, і всі десять виконуються насправді.
"""
import re
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from flask_babel import refresh

from app.extensions import db
from app.models.blog_post import BlogPost
from app.models.clinic import Clinic
from app.models.course import Course
from app.models.media_file import MediaFile
from app.models.online_course import OnlineCourse
from app.models.trainer import Trainer
from app.i18n import PREFIXED_LANGUAGES
from tests.test_seo.helpers import (
    canonical_org_id, count_h1, find_nodes_by_type, is_absolute_url,
    iter_url_values, jsonld_blocks, organization_ids, provider_ids,
    reference_ids, rendered_lang,
)


def _media(suffix):
    """Мінімальний MediaFile-рядок (як у test_course_landing_content.py).

    Файл на диску не потрібен: `url`/`variant_url()` лише будують рядок з
    `file_path`, дискового читання не роблять, а саме рядок -- усе, що
    цікавить SEO-сторожів у HTML-відповіді.
    """
    media = MediaFile(
        filename=f'{suffix}.webp',
        file_path=f'2026/08/{suffix}-{uuid4().hex[:8]}.webp',
        mime_type='image/webp',
    )
    db.session.add(media)
    db.session.flush()
    return media


@pytest.fixture
def dynamic_pages(app, client):
    """[(мітка, url, html)] -- по одній сторінці кожного динамічного типу."""
    course_card = _media('course-card')
    online_card = _media('online-card')
    # online/detail.html:11 бере og:image з course.hero_src, а НЕ
    # card_src (на відміну від courses/detail.html) -- card_media_id сам
    # по собі лишає цю гілку хибною. Пропущено в першому раунді: суїта
    # лишалась зеленою на відкоті саме цього abs_url-виклику. hero_src і
    # card_src -- різні MediaFile, бо в бойовому коді це різні поля.
    online_hero = _media('online-hero')
    trainer_photo = _media('trainer-photo')
    blog_cover = _media('blog-cover')

    course = Course(
        title='Курс структурних даних',
        slug=f'dyn-course-{uuid4().hex[:8]}',
        is_active=True,
        card_media_id=course_card.id,
    )
    online = OnlineCourse(
        sintegrum_id=int(uuid4().int % 10_000_000),
        remote_name='Онлайн-курс структурних даних',
        slug=f'dyn-online-{uuid4().hex[:8]}',
        is_published=True,
        is_vanished=False,
        card_media_id=online_card.id,
        hero_media_id=online_hero.id,
    )
    trainer = Trainer(
        full_name='Іван Тренер',
        slug=f'dyn-trainer-{uuid4().hex[:8]}',
        is_active=True,
        photo_media_id=trainer_photo.id,
    )
    # Clinic.photo -- звичайний рядковий стовпець (НЕ медіа-реєстр, на
    # відміну від решти): og:image читає його напряму, MediaFile тут
    # взагалі не задіяний.
    clinic = Clinic(
        name='Клініка структурних даних',
        slug=f'dyn-clinic-{uuid4().hex[:8]}',
        is_active=True,
        photo='/media/2026/08/clinic-photo.webp',
    )
    post = BlogPost(
        title='Допис структурних даних',
        slug=f'dyn-post-{uuid4().hex[:8]}',
        content=[],
        status=BlogPost.STATUS_PUBLISHED,
        published_at=datetime.now(timezone.utc),
        cover_media_id=blog_cover.id,
    )
    db.session.add_all([course, online, trainer, clinic, post])
    db.session.flush()

    # Галерея курсу -- окремий запит MediaFile.for_entity() (потребує вже
    # присвоєного course.id), а не relationship. courses/detail.html має
    # ДРУГИЙ abs_url-виклик саме під елементи галереї (окремо від card_src)
    # -- без рядка в галереї він лишався б непокритим.
    gallery_media = _media('course-gallery')
    gallery_media.entity_type = 'course'
    gallery_media.entity_id = course.id
    gallery_media.usage_type = 'gallery'
    db.session.flush()

    targets = [
        ('course', f'/courses/{course.slug}'),
        ('online', f'/online-courses/{online.slug}'),
        ('trainer', f'/trainers/{trainer.slug}'),
        ('clinic', f'/clinics/{clinic.slug}'),
        ('blog post', f'/blog/{post.slug}'),
    ]
    pages = []
    for label, url in targets:
        resp = client.get(url)
        assert resp.status_code == 200, f'{label} ({url}): {resp.status_code}'
        pages.append((label, url, resp.data.decode('utf-8')))
    return pages


@pytest.fixture
def dynamic_pages_by_locale(app, dynamic_pages):
    """[(мітка, локаль, url, html)] -- ті самі сторінки в uk/ru/en.

    Без цього прогону вся структурна перевірка динамічних сторінок жила
    ЛИШЕ в українському рендері, і саме там локале-залежний @id збігався
    з канонічним випадково. Доведено мутацією: відкат provider у
    courses/detail.html (або в online/detail.html) до
    url_for('main.index', _external=True) лишав сюїту зеленою -- на /ru/
    сторінка публікувала provider.@id = ".../ru/#org" при власному вузлі
    організації ".../#org", тобто висяче посилання, а подивитись туди не
    було кому: fetch_public_pages() динамічних сторінок не бачить
    (потрібні параметри), а тутешні тести не виходили за межі uk.

    Клієнт СВІЙ на кожну локаль і refresh() перед кожним запитом -- з тієї
    самої причини, що й у fetch_public_pages(): вибір мови липкий через
    session['lang'], а flask_babel кешує локаль на g в межах контексту.
    Звірка <html lang> лишає прогін чесним: інакше "ru-прогін" міг би
    мовчки віддавати український рендер.
    """
    pages = [('uk', label, url, html) for label, url, html in dynamic_pages]
    for lang in PREFIXED_LANGUAGES:
        client = app.test_client()
        for label, url, _html in dynamic_pages:
            refresh()
            localized = f'/{lang}{url}'
            resp = client.get(localized)
            assert resp.status_code == 200, (
                f'{label} ({localized}): {resp.status_code}'
            )
            html = resp.data.decode('utf-8')
            actual = rendered_lang(html)
            assert actual == lang, (
                f'{label} ({localized}): просили локаль {lang!r}, сторінка '
                f'оголосила <html lang={actual!r}> -- обвал локалі'
            )
            pages.append((lang, label, localized, html))
    return pages


class TestDynamicPageStructure:
    def test_jsonld_parses_and_is_typed(self, dynamic_pages):
        bad = []
        for label, url, html in dynamic_pages:
            try:
                blocks = jsonld_blocks(html)
            except ValueError as exc:
                bad.append(f'{label}: невалідний JSON-LD -- {exc}')
                continue
            if not blocks:
                bad.append(f'{label}: жодного блоку JSON-LD')
            for block in blocks:
                if '@context' not in block:
                    bad.append(f'{label}: блок без @context')
                elif '@type' not in block and '@graph' not in block:
                    bad.append(f'{label}: блок без @type і без @graph')
        assert not bad, 'Проблеми JSON-LD:\n' + '\n'.join(bad)

    def test_exactly_one_h1(self, dynamic_pages):
        """count_h1, а не регексп по сирому HTML.

        Лічильників <h1> у сюїті було два, і виправили спершу лише той,
        що в test_page_seo.py. Розбіжність гірша за спільну ваду: із
        літералом "<h1" усередині inline-скрипта сусідній тест
        правильно проходив, а ЦЕЙ падав -- червона збірка на коректній
        розмітці, тобто рівно те, заради чого лічильник і переписували.
        """
        bad = []
        for label, url, html in dynamic_pages:
            count = count_h1(html)
            if count != 1:
                bad.append(f'{label} ({url}): {count} <h1>')
        assert not bad, 'Сторінки не з одним <h1>:\n' + '\n'.join(bad)

    def test_canonical_absolute_and_clean(self, dynamic_pages):
        bad = []
        for label, url, html in dynamic_pages:
            found = re.search(r'<link rel="canonical" href="([^"]*)"', html)
            if not found:
                bad.append(f'{label}: canonical відсутній')
                continue
            href = found.group(1)
            if not is_absolute_url(href):
                bad.append(f'{label}: canonical не абсолютний -- {href}')
            if '?' in href:
                bad.append(f'{label}: canonical із query -- {href}')
        assert not bad, 'Проблеми canonical:\n' + '\n'.join(bad)

    def test_schema_urls_absolute(self, dynamic_pages):
        bad = []
        for label, url, html in dynamic_pages:
            for block in jsonld_blocks(html):
                for key, value in iter_url_values(block):
                    if not is_absolute_url(value):
                        bad.append(f'{label}: {key} = {value}')
        assert not bad, (
            'Відносні URL у структурованих даних:\n' + '\n'.join(bad)
        )

    def test_og_image_absolute(self, dynamic_pages):
        """Твердження вище бачить лише JSON-LD, а abs_url обслуговує ще й
        og:image / twitter:image (base.html -- twitter:image бере те саме
        значення через self.og_image()). Фікстури тепер прикріплюють медіа
        до кожної сутності, тож `{% if x.photo_full %}`-гілка з
        abs_url(...) справді виконується -- а не мовчки пропускається на
        користь уже абсолютного дефолту з base.html."""
        bad = []
        for label, url, html in dynamic_pages:
            found = re.search(r'<meta property="og:image" content="([^"]*)"', html)
            if not found:
                bad.append(f'{label}: og:image відсутній')
                continue
            if not is_absolute_url(found.group(1)):
                bad.append(f'{label}: og:image не абсолютний -- {found.group(1)}')
        assert not bad, 'Проблеми og:image:\n' + '\n'.join(bad)

    def test_breadcrumbs_present(self, dynamic_pages):
        """Динамічні сторінки -- саме ті, що потрапляють у видачу."""
        bad = []
        for label, url, html in dynamic_pages:
            crumbs = [
                b for b in jsonld_blocks(html)
                if b.get('@type') == 'BreadcrumbList'
            ]
            if len(crumbs) != 1:
                bad.append(f'{label}: BreadcrumbList {len(crumbs)} шт.')
        assert not bad, 'Проблеми крихт:\n' + '\n'.join(bad)

    def test_inherited_organization_is_not_dropped(self, dynamic_pages):
        """Перевизначений {% block jsonld %} без {{ super() }} мовчки
        викидає успадковану з base.html EducationalOrganization.

        Саме так вона зникла зі сторінок тренера й клініки. Вузол
        шукається за @id: сторінка курсу посилається на нього з provider,
        і посилання на неоголошений @id -- висяче."""
        bad = []
        for label, url, html in dynamic_pages:
            found = False
            for block in jsonld_blocks(html):
                for node in block.get('@graph', [block]):
                    if not isinstance(node, dict):
                        continue
                    if node.get('@type') == 'EducationalOrganization' and node.get('@id'):
                        found = True
            if not found:
                bad.append(label)
        assert not bad, (
            'Сторінки без EducationalOrganization з base.html (немає '
            '{{ super() }} у block jsonld): ' + ', '.join(bad)
        )


class TestProviderLinkage:
    """provider.@id мусить збігатися з реальним @id організації на
    сторінці символ-у-символ, а не просто "щось таке є на сторінці".

    test_inherited_organization_is_not_dropped вище перевіряє лише факт
    присутності ЯКОГОСЬ вузла EducationalOrganization з ЯКИМСЬ @id -- сам
    зв'язок provider -> @id не звірявся ніяк. Доведено мутацією: підміна
    '#org' на '#ORG-TYPO' у provider курсу (курс і онлайн-курс -- єдині
    сторінки з provider) лишала сюїту зеленою.
    """

    def test_reference_ids_match_an_organization_node(self, dynamic_pages):
        """reference_ids, а не provider_ids: ключ, під яким лежить
        посилання, для дефекту значення не має. publisher і author не
        читав ЖОДЕН хелпер, тож висяче посилання під ними лишалось
        невидимим цілком -- відкат publisher на головній до
        локале-залежного значення проходив зеленим."""
        bad = []
        for label, url, html in dynamic_pages:
            blocks = jsonld_blocks(html)
            org_ids = organization_ids(blocks)
            for ref_id in reference_ids(blocks):
                if ref_id not in org_ids:
                    bad.append(
                        f'{label}: посилання @id={ref_id!r} немає '
                        f'серед вузлів організації {sorted(org_ids)}'
                    )
        assert not bad, (
            'Розірвані посилання на організацію:\n' + '\n'.join(bad)
        )

    def test_course_node_has_provider(self, dynamic_pages):
        """Тест вище звіряє provider.@id, ЯКЩО він є -- цикл `for
        provider_id in provider_ids(blocks)` над порожнім списком минає
        вакуумно (0 ітерацій -- не помилка). Доведено мутацією: видалення
        всього рядка `'provider': {...}` із courses/detail.html лишало
        суїту зеленою, хоча приналежність курсу до організації в JSON-LD
        зникала повністю. Тому вузол Course мусить МАТИ ключ provider, а
        не лише "мати правильний, якщо він узагалі є"."""
        bad = []
        for label, url, html in dynamic_pages:
            blocks = jsonld_blocks(html)
            for node in find_nodes_by_type(blocks, 'Course'):
                if 'provider' not in node:
                    bad.append(f'{label}: вузол Course без provider')
        assert not bad, 'Course без provider:\n' + '\n'.join(bad)


class TestDynamicOrganizationIdIsLocaleIndependent:
    """@id організації на динамічних сторінках -- канонічний у всіх локалях.

    Симптом P1 жив саме тут: provider на сторінці курсу й онлайн-курсу.
    Сторож у test_urls_and_locales.py туди не дістає (ці сторінки
    потребують параметрів і в public_endpoints не потрапляють), а
    TestProviderLinkage вище ходить лише по українських URL, де
    локале-залежне значення збігається з канонічним і розбіжності не
    видно. Доведено мутацією: відкат provider у courses/detail.html АБО в
    online/detail.html поодинці лишав сюїту зеленою.
    """

    def test_every_reference_and_node_uses_the_canonical_id(
        self, app, dynamic_pages_by_locale,
    ):
        expected = canonical_org_id(app)
        bad = []
        for lang, label, url, html in dynamic_pages_by_locale:
            blocks = jsonld_blocks(html)
            ids = organization_ids(blocks) | set(reference_ids(blocks))
            assert ids, f'[{lang}] {label}: жодного @id організації'
            for value in sorted(ids):
                if value != expected:
                    bad.append(f'[{lang}] {label} ({url}): {value!r}')
        assert not bad, (
            f'@id організації не дорівнює канонічному {expected!r} -- '
            'Google читає це як різні сутності, а посилання provider і '
            'publisher стають висячими:\n' + '\n'.join(bad)
        )

    def test_course_provider_survives_every_locale(
        self, app, dynamic_pages_by_locale,
    ):
        """Друга половина: твердження вище минає вакуумно, якщо ключ
        provider узагалі зник. Сторінки курсу й онлайн-курсу мусять
        нести його в КОЖНІЙ локалі, а не лише в українській."""
        without = []
        locales = set()
        for lang, label, url, html in dynamic_pages_by_locale:
            for node in find_nodes_by_type(jsonld_blocks(html), 'Course'):
                locales.add(lang)
                if 'provider' not in node:
                    without.append(f'[{lang}] {label}')
        assert not without, f'Вузол Course без provider: {sorted(without)}'
        assert locales == {'uk', *PREFIXED_LANGUAGES}, (
            f'Вузол Course знайдено не в усіх локалях: {sorted(locales)}'
        )


class TestTrainerPersonSchema:
    """C1: Person будувався літеральним JSON із інтерпольованими рядками.

    Jinja екранує в JSON-рядку лапки, але НЕ переводи рядка. Біографія
    тренера пишеться абзацами (сторінка й рендерить її як <p>), тож один
    абзацний розрив робив увесь вузол невалідним JSON -- і Google втрачав
    не лише опис, а ім'я, посаду, фото й worksFor разом із ним. Друга вада
    того ж роду: автоекранування перетворювало лапки в імені на &#34;, а
    всередині <script> HTML-сутності не декодуються.
    """

    @pytest.fixture
    def hostile_trainer(self, app, client):
        trainer = Trainer(
            full_name='Іван "Док" Тренер',
            slug=f'hostile-{uuid4().hex[:8]}',
            role='Лікар-дослідник',
            bio='Перший абзац біографії.\n\nДругий абзац біографії.',
            is_active=True,
        )
        db.session.add(trainer)
        db.session.flush()
        resp = client.get(f'/trainers/{trainer.slug}')
        assert resp.status_code == 200
        return trainer, resp.data.decode('utf-8')

    def _person(self, html):
        for block in jsonld_blocks(html):
            if block.get('@type') == 'Person':
                return block
        raise AssertionError('Person-схеми на сторінці немає')

    def test_multiline_bio_keeps_the_whole_person_node(self, hostile_trainer):
        trainer, html = hostile_trainer
        person = self._person(html)
        assert person['name'] == 'Іван "Док" Тренер'
        assert person['jobTitle'] == 'Лікар-дослідник'
        assert person['worksFor']['@type'] == 'EducationalOrganization'
        assert is_absolute_url(person['url'])
        assert '\n\n' in person['description']

    def test_quotes_in_name_are_not_html_entities(self, hostile_trainer):
        trainer, html = hostile_trainer
        person = self._person(html)
        assert '&#34;' not in person['name']
        assert '&quot;' not in person['name']

    def test_empty_role_is_omitted_not_empty_string(self, app, client):
        """Порожній рядок у JSON-LD -- заявлене й порожнє значення."""
        trainer = Trainer(
            full_name='Тренер Без Посади',
            slug=f'norole-{uuid4().hex[:8]}',
            is_active=True,
        )
        db.session.add(trainer)
        db.session.flush()
        resp = client.get(f'/trainers/{trainer.slug}')
        person = self._person(resp.data.decode('utf-8'))
        assert 'jobTitle' not in person
        assert 'description' not in person
        assert 'image' not in person
