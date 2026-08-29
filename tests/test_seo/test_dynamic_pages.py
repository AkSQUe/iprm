"""Ті самі структурні твердження -- на сторінках, що живуть із БД.

fetch_public_pages() бачить лише ендпоінти без обов'язкових параметрів,
тож курс, онлайн-курс, тренер, клініка й допис блогу до цього раунду не
перевіряв ЖОДЕН структурний сторож. Доведено відкотом: обидві правки
abs_url із Задачі 4 можна було повернути назад -- сюїта лишалась зеленою.

Фікстури тут навмисно мінімальні: сторінка мусить триматись на порожніх
полях так само, як на заповнених.
"""
import re
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from app.extensions import db
from app.models.blog_post import BlogPost
from app.models.clinic import Clinic
from app.models.course import Course
from app.models.online_course import OnlineCourse
from app.models.trainer import Trainer
from tests.test_seo.helpers import iter_url_values, jsonld_blocks


@pytest.fixture
def dynamic_pages(app, client):
    """[(мітка, url, html)] -- по одній сторінці кожного динамічного типу."""
    course = Course(
        title='Курс структурних даних',
        slug=f'dyn-course-{uuid4().hex[:8]}',
        is_active=True,
    )
    online = OnlineCourse(
        sintegrum_id=int(uuid4().int % 10_000_000),
        remote_name='Онлайн-курс структурних даних',
        slug=f'dyn-online-{uuid4().hex[:8]}',
        is_published=True,
        is_vanished=False,
    )
    trainer = Trainer(
        full_name='Іван Тренер',
        slug=f'dyn-trainer-{uuid4().hex[:8]}',
        is_active=True,
    )
    clinic = Clinic(
        name='Клініка структурних даних',
        slug=f'dyn-clinic-{uuid4().hex[:8]}',
        is_active=True,
    )
    post = BlogPost(
        title='Допис структурних даних',
        slug=f'dyn-post-{uuid4().hex[:8]}',
        content=[],
        status=BlogPost.STATUS_PUBLISHED,
        published_at=datetime.now(timezone.utc),
    )
    db.session.add_all([course, online, trainer, clinic, post])
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
        bad = []
        for label, url, html in dynamic_pages:
            count = len(re.findall(r'<h1[\s>]', html))
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
            if not href.startswith('http'):
                bad.append(f'{label}: canonical не абсолютний -- {href}')
            if '?' in href:
                bad.append(f'{label}: canonical із query -- {href}')
        assert not bad, 'Проблеми canonical:\n' + '\n'.join(bad)

    def test_schema_urls_absolute(self, dynamic_pages):
        bad = []
        for label, url, html in dynamic_pages:
            for block in jsonld_blocks(html):
                for key, value in iter_url_values(block):
                    if not value.startswith('http'):
                        bad.append(f'{label}: {key} = {value}')
        assert not bad, (
            'Відносні URL у структурованих даних:\n' + '\n'.join(bad)
        )

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
        assert person['url'].startswith('http')
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
