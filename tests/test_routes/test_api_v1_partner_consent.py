"""Партнерське API: згода, довідник спеціалізацій і стабільна пагінація.

Три речі, яких бракувало для того, щоб партнер міг сегментувати розсилки й
не порушувати відписку.

**Згода.** Партнер не знав, кому в нас заборонено писати, і його розсилка
обходила нашу відписку. Для людини це ОДИН відправник, і претензія була б до
обох. Тепер картка учасника несе `email_opt_out`, посилання відписки й ознаку
живої адреси, а зворотний ендпоінт приймає відписку, зроблену в партнера.

**Довідник.** Коди спеціалізацій партнер уже отримував, підписи -- ні, і
менеджер бачив `orthopedics_traumatology` замість «Травматологія та
ортопедія». Скопійований один раз перелік розійшовся б із нашим за місяці.

**Тайбрейкер.** Коментар у `_listing` стверджував, що сортування має другу
колонку, а в коді її не було. Масовий імпорт ставить сотням рядків однаковий
`updated_at`, і рядки «плавали» між сторінками: партнер бачив одних двічі, а
інших не бачив зовсім.
"""
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from app.extensions import db
from app.models.email_suppression import EmailSuppression
from app.models.site_settings import SiteSettings
from app.models.user import User

API_KEY = 'test-partner-api-key-12345678901234567890'
HEADERS = {'X-API-Key': API_KEY}


def _uid():
    return uuid4().hex[:8]


@pytest.fixture
def partner_settings(app):
    s = SiteSettings.get()
    s.partner_integration_enabled = True
    s.partner_api_key = API_KEY
    db.session.commit()
    yield s
    s.partner_integration_enabled = False
    s.partner_api_key = ''
    db.session.commit()


@pytest.fixture
def learner(app):
    user = User(
        email=f'consent-{_uid()}@example.com',
        first_name='Тест', last_name='Учасник',
        email_confirmed=True, is_active=True,
    )
    db.session.add(user)
    db.session.commit()
    return user


def _fetch(client, learner):
    """Картка учасника з видачі партнера.

    Через `updated_since`, а не «перша сторінка»: у спільній тестовій базі
    учасників сотні, і на першій сторінці нашого може не бути — тест падав
    би від сусідніх тестів, а не від власного коду.
    """
    since = learner.updated_at.isoformat()
    response = client.get(
        f'/api/v1/participants?per_page=200&updated_since={since}',
        headers=HEADERS,
    )
    assert response.status_code == 200
    return next(i for i in response.get_json()['items'] if i['id'] == learner.id)


class TestParticipantConsentFields:
    def test_opt_out_is_visible_to_the_partner(self, client, partner_settings,
                                               learner):
        learner.email_opt_out = True
        db.session.commit()

        assert _fetch(client, learner)['email_opt_out'] is True

    def test_unsubscribe_url_is_given_when_a_token_exists(
        self, client, partner_settings, learner
    ):
        """Партнер показує НАШЕ посилання, тож відписка лишається одна."""
        learner.get_unsubscribe_token()
        settings = SiteSettings.get()
        settings.website_url = 'https://iprm.space'
        db.session.commit()

        assert _fetch(client, learner)['unsubscribe_url'].startswith(
            'https://iprm.space/unsubscribe/')

    def test_no_token_means_no_link(self, client, partner_settings, learner):
        """Токен видається записом у БД; GET бази не змінює."""
        assert _fetch(client, learner)['unsubscribe_url'] is None

    def test_dead_address_is_flagged(self, client, partner_settings, learner):
        db.session.add(EmailSuppression(
            email=EmailSuppression.normalize(learner.email),
            reason=EmailSuppression.REASON_BOUNCE,
        ))
        db.session.commit()

        assert _fetch(client, learner)['email_deliverable'] is False

    def test_live_address_is_flagged_too(self, client, partner_settings, learner):
        assert _fetch(client, learner)['email_deliverable'] is True


class TestOptOutEndpoint:
    URL = '/api/v1/participants/{}/opt-out'

    def test_partner_can_unsubscribe_a_participant(self, client, partner_settings,
                                                   learner):
        response = client.post(self.URL.format(learner.id), headers=HEADERS,
                               json={'reason': 'відписався в MM Medic'})

        assert response.status_code == 200
        assert response.get_json()['email_opt_out'] is True
        db.session.refresh(learner)
        assert learner.email_opt_out is True

    def test_repeat_is_idempotent(self, client, partner_settings, learner):
        """Партнер ретраїть при мережевих збоях: 409 крутив би його вічно."""
        client.post(self.URL.format(learner.id), headers=HEADERS, json={})
        second = client.post(self.URL.format(learner.id), headers=HEADERS, json={})

        assert second.status_code == 200
        assert second.get_json()['changed'] is False

    def test_resubscribe_returns_consent(self, client, partner_settings, learner):
        learner.email_opt_out = True
        db.session.commit()

        response = client.post(self.URL.format(learner.id), headers=HEADERS,
                               json={'action': 'resubscribe'})

        assert response.get_json()['email_opt_out'] is False

    def test_unknown_participant_is_404(self, client, partner_settings):
        assert client.post(self.URL.format(999999), headers=HEADERS,
                           json={}).status_code == 404

    def test_without_a_key_nothing_happens(self, client, partner_settings, learner):
        response = client.post(self.URL.format(learner.id), json={})

        assert response.status_code in (401, 403, 404)
        db.session.refresh(learner)
        assert learner.email_opt_out is False


class TestSpecializationsDirectory:
    def test_directory_is_served(self, client, partner_settings):
        response = client.get('/api/v1/specializations', headers=HEADERS)

        assert response.status_code == 200
        body = response.get_json()
        assert body['total'] == len(body['items'])
        assert {'code', 'title'} <= set(body['items'][0])

    def test_codes_match_the_source_of_truth(self, client, partner_settings):
        """Другий перелік розійшовся б із першим — тому віддаємо саме його."""
        from app.models.specializations import SPECIALIZATION_CODES

        response = client.get('/api/v1/specializations', headers=HEADERS)

        codes = {item['code'] for item in response.get_json()['items']}
        assert codes == SPECIALIZATION_CODES

    def test_key_is_required(self, client, partner_settings):
        assert client.get('/api/v1/specializations').status_code in (401, 403, 404)


class TestPaginationTiebreaker:
    def test_rows_with_the_same_timestamp_do_not_float(self, client,
                                                       partner_settings):
        """Без другої колонки сортування партнер губить частину бази."""
        stamp = datetime(2026, 8, 14, 10, 0, tzinfo=timezone.utc)
        created = []
        for _ in range(6):
            user = User(email=f'same-{_uid()}@example.com', first_name='Т',
                        last_name='Т', email_confirmed=True, is_active=True)
            db.session.add(user)
            created.append(user)
        db.session.commit()
        for user in created:
            user.updated_at = stamp
        db.session.commit()

        first = client.get('/api/v1/participants?per_page=3&page=1',
                           headers=HEADERS).get_json()['items']
        second = client.get('/api/v1/participants?per_page=3&page=2',
                            headers=HEADERS).get_json()['items']

        ids = [row['id'] for row in first] + [row['id'] for row in second]
        assert len(ids) == len(set(ids)), 'рядок потрапив на дві сторінки'
