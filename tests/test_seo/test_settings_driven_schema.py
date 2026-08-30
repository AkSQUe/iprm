"""Сторожі полів JSON-LD, що приходять із налаштувань сайту.

Цілий клас дефектів був невидимий ТУТ ЗА КОНСТРУКЦІЄЮ: у порожній
тестовій БД SiteSettings не має перекладів, тож `t('company_name')` і сирий
`company_name` віддають те саме значення. Шаблон, що читає не те поле,
нічим не відрізнявся від шаблону, що читає те. Доведено: поточна сюїта,
прогнана проти шаблонів ДО правок (`git archive 6f134fc~1`), лишалась
зеленою на всіх трьох багах одразу -- сирий company_full_name у
contact.html, захардкоджений inLanguage='uk' у home.html і порожній рядок
у dateModified блогу.

Умова, за якої такі речі взагалі можна перевірити, -- налаштування з
РІЗНИМИ значеннями по локалях. Звідси фікстура нижче.
"""
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from flask import render_template
from flask_babel import refresh

from app.extensions import db
from app.models.blog_comment import BlogComment
from app.models.blog_post import BlogPost
from app.models.site_settings import SiteSettings
from app.models.trainer import Trainer
from tests.test_seo.helpers import (
    LOCALE_PASSES, ORGANIZATION_TYPES, fetch_public_pages, find_nodes_by_type,
    jsonld_blocks, pass_label,
)

# Навмисно неперекладні, ні на що не схожі рядки: якби значення були
# справжніми перекладами, помилка "взяли не ту локаль" читалась би як
# правдоподібний текст, а не як розбіжність.
NAMES = {'uk': 'NAME-UK', 'ru': 'NAME-RU', 'en': 'NAME-EN'}
FULL_NAMES = {'uk': 'FULL-UK', 'ru': 'FULL-RU', 'en': 'FULL-EN'}

# Запасний варіант у шаблонах -- це `_('ІПРМ')`, тобто gettext-рядок, а не
# константа: ru віддає "ИПРМ", en -- "IPRM". Тому твердження нижче звіряє
# вузли МІЖ СОБОЮ і вимагає непорожнього імені, а не дорівнює конкретному
# рядку -- інакше воно перевіряло б каталог перекладів, а не узгодженість
# схеми.


@pytest.fixture
def translated_settings(db_session):
    """SiteSettings із РІЗНИМИ назвами компанії для uk/ru/en."""
    settings = SiteSettings.get()
    settings.company_name = NAMES['uk']
    settings.company_full_name = FULL_NAMES['uk']
    for lang in ('ru', 'en'):
        settings.set_translation(lang, 'company_name', NAMES[lang])
        settings.set_translation(lang, 'company_full_name', FULL_NAMES[lang])
    db.session.flush()
    return NAMES


@pytest.fixture
def blank_company_name(db_session):
    """Порожня назва компанії -- випадок, на якому вузли організації
    розходились: один брав запасний літерал, другий лишався порожнім."""
    settings = SiteSettings.get()
    settings.company_name = ''
    db.session.flush()
    return ''


def _org_nodes(html):
    """Усі вузли організації сторінки (обидва типи, рекурсивно)."""
    blocks = jsonld_blocks(html)
    nodes = []
    for type_name in sorted(ORGANIZATION_TYPES):
        nodes.extend(find_nodes_by_type(blocks, type_name))
    return nodes


@pytest.fixture
def dynamic_slugs(db_session):
    """Тренер і допис: їхні сторінки в public_endpoints не потрапляють
    (потребують параметра), а саме там живуть worksFor, author і
    publisher -- вузли організації, яких немає на жодній сторінці зі
    списку."""
    trainer = Trainer(
        full_name='Іван Тренер',
        slug=f'seo-trainer-{uuid4().hex[:8]}',
        is_active=True,
    )
    post = BlogPost(
        title='Допис для схеми',
        slug=f'seo-post-{uuid4().hex[:8]}',
        content=[],
        status=BlogPost.STATUS_PUBLISHED,
        published_at=datetime(2026, 5, 4, 10, 30, tzinfo=timezone.utc),
    )
    db.session.add_all([trainer, post])
    db.session.flush()
    return {'trainer': trainer.slug, 'post': post.slug}


class TestOrganizationNameFollowsLocale:
    """Кожен вузол організації мусить нести ПЕРЕКЛАДЕНУ назву.

    Твердження свідомо ширше за два поля, які лагодив цей раунд: воно
    накриває будь-яке поле назви, що зісковзне на сиру колонку, у будь-якому
    вузлі організації на будь-якій публічній сторінці.
    """

    def test_every_organization_node_carries_translated_names(
        self, app, translated_settings,
    ):
        bad = []
        for lang in LOCALE_PASSES:
            label = pass_label(lang)
            for endpoint, url, html in fetch_public_pages(app, lang=lang)[0]:
                for node in _org_nodes(html):
                    marker = node.get('@id', node.get('@type'))
                    if node.get('name') != NAMES[label]:
                        bad.append(
                            f'[{label}] {endpoint} {marker}: name = '
                            f'{node.get("name")!r}, очікували {NAMES[label]!r}'
                        )
                    if 'alternateName' not in node:
                        continue
                    if node['alternateName'] != FULL_NAMES[label]:
                        bad.append(
                            f'[{label}] {endpoint} {marker}: alternateName = '
                            f'{node["alternateName"]!r}, очікували '
                            f'{FULL_NAMES[label]!r}'
                        )
        assert not bad, (
            'Вузли організації з неперекладеною назвою (шаблон читає сиру '
            'колонку замість t()):\n' + '\n'.join(bad)
        )

    def test_dynamic_pages_organization_nodes_follow_locale(
        self, app, translated_settings, dynamic_slugs,
    ):
        """worksFor у тренера, author і publisher у дописі."""
        client = app.test_client()
        bad = []
        for lang in LOCALE_PASSES:
            label = pass_label(lang)
            prefix = f'/{lang}' if lang else ''
            for url in (
                f'{prefix}/trainers/{dynamic_slugs["trainer"]}',
                f'{prefix}/blog/{dynamic_slugs["post"]}',
            ):
                refresh()
                resp = client.get(url)
                assert resp.status_code == 200, f'{url}: {resp.status_code}'
                for node in _org_nodes(resp.data.decode('utf-8')):
                    if node.get('name') != NAMES[label]:
                        marker = node.get('@id', node.get('@type'))
                        bad.append(
                            f'[{label}] {url} {marker}: name = '
                            f'{node.get("name")!r}, очікували {NAMES[label]!r}'
                        )
        assert not bad, (
            'Вузли організації динамічних сторінок не пішли за локаллю:\n'
            + '\n'.join(bad)
        )


class TestWebSiteInLanguage:
    def test_inlanguage_matches_page_locale(self, app):
        """inLanguage був захардкоджений 'uk', тож /ru/ і /en/ оголошували
        себе українськими. Поле описує МОВУ САМОГО РЕНДЕРУ, тобто єдине
        його правильне значення -- локаль сторінки."""
        bad = []
        for lang in LOCALE_PASSES:
            label = pass_label(lang)
            for endpoint, url, html in fetch_public_pages(app, lang=lang)[0]:
                for node in find_nodes_by_type(jsonld_blocks(html), 'WebSite'):
                    if node.get('inLanguage') != label:
                        bad.append(
                            f'[{label}] {endpoint}: inLanguage = '
                            f'{node.get("inLanguage")!r}'
                        )
        assert not bad, (
            'WebSite оголошує не ту мову, якою віддано сторінку:\n'
            + '\n'.join(bad)
        )


class TestBlogPostDateModified:
    def test_absent_when_post_has_no_dates(self, app):
        """Порожній рядок замість дати -- невалідне значення структурованих
        даних. Через маршрут ця гілка недосяжна (published_at IS NOT NULL),
        тож перевіряється прямим рендером шаблону: саме так вона й чекала
        на перший чернетковий чи прев'ю-маршрут, який її оприлюднить."""
        post = BlogPost(
            title='Допис без дат',
            slug='seo-post-no-dates',
            content=[],
            status=BlogPost.STATUS_PUBLISHED,
        )
        assert post.published_at is None and post.updated_at is None
        with app.test_request_context(f'/blog/{post.slug}'):
            html = render_template(
                'blog/post.html',
                active_nav='blog',
                post=post,
                comment_children={},
                comment_roots=[],
                comment_count=0,
                max_comment_depth=BlogComment.MAX_DEPTH,
            )
        posting = find_nodes_by_type(jsonld_blocks(html), 'BlogPosting')
        assert len(posting) == 1, f'Очікували один BlogPosting, є {len(posting)}'
        assert 'dateModified' not in posting[0], (
            'dateModified присутній без жодного джерела дати: '
            f'{posting[0].get("dateModified")!r}. Порожнє значення дати -- '
            'заявлене й невалідне поле, а не відсутнє.'
        )

    def test_present_when_post_has_a_date(self, app, dynamic_slugs):
        """Друга половина твердження: умова не мусить З'ЇСТИ поле там, де
        дата є. Без цього тест вище проходив би й на шаблоні, який
        dateModified не віддає ніколи."""
        client = app.test_client()
        resp = client.get(f'/blog/{dynamic_slugs["post"]}')
        assert resp.status_code == 200
        posting = find_nodes_by_type(
            jsonld_blocks(resp.data.decode('utf-8')), 'BlogPosting',
        )
        assert len(posting) == 1
        assert posting[0].get('dateModified'), (
            'dateModified зник на дописі, що має дату'
        )


class TestOrganizationNodesAgreeOnEmptySetting:
    def test_both_nodes_fall_back_to_the_same_name(self, app, blank_company_name):
        """/contact публікує ДВІ організації: #org із base.html і mainEntity
        без @id (для Google -- окрема сутність). Доки запасний літерал мав
        лише один із них, порожнє налаштування розводило їх назвами:
        #org без імені, mainEntity -- з літералом."""
        client = app.test_client()
        bad = []
        for lang in LOCALE_PASSES:
            label = pass_label(lang)
            refresh()
            resp = client.get(f'/{lang}/contact' if lang else '/contact')
            assert resp.status_code == 200
            nodes = _org_nodes(resp.data.decode('utf-8'))
            assert len(nodes) == 2, (
                f'[{label}] очікували дві організації на /contact, є {len(nodes)}'
            )
            names = {node.get('name') for node in nodes}
            if len(names) != 1:
                bad.append(
                    f'[{label}] вузли назвались по-різному: '
                    f'{sorted(map(repr, names))}'
                )
            elif not next(iter(names)):
                bad.append(
                    f'[{label}] обидва вузли без імені -- порожня назва '
                    'організації гірша за запасний літерал'
                )
        assert not bad, (
            'Вузли організації на порожньому company_name:\n' + '\n'.join(bad)
        )
