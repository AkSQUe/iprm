"""Сервіс залучення тренерів."""
from types import SimpleNamespace
from uuid import uuid4

import pytest
from flask_babel import force_locale

from app.data.trainer_recruit import DEFAULTS
from app.extensions import db
from app.models.site_settings import SiteSettings
from app.models.trainer import Trainer
from app.models.trainer_application import TrainerApplication
from app.models.user import User
from app.services import trainer_recruitment as svc


def _uid():
    return uuid4().hex[:8]


def _form(**kw):
    data = {
        'full_name': 'Іваненко Іван Петрович', 'phone': '+380501112233',
        'email': f'cand-{_uid()}@example.com', 'city': 'Київ',
        'specialty': 'Дерматологія', 'workplace': 'Клініка, лікар',
        'social_links': 'https://instagram.com/x', 'topic': 'PRP у трихології',
        'q_plasma_years': '1_3', 'q_tubes_per_day': '6_10',
        'q_directions': 'Трихологія', 'q_equipment': 'Regen Lab',
        'q_teaching': 'webinars',
    }
    data.update(kw)
    return SimpleNamespace(**{k: SimpleNamespace(data=v) for k, v in data.items()})


def _application(**kw):
    item = svc.create_application(_form(**kw), 'uk')
    db.session.flush()
    return item


# --- тексти ----------------------------------------------------------------

def test_empty_setting_falls_back_to_default(app):
    settings = SiteSettings.get()
    settings.recruit_page_title = ''
    assert svc.recruit_text('recruit_page_title', settings) == DEFAULTS['recruit_page_title']


def test_custom_setting_wins(app):
    settings = SiteSettings.get()
    settings.recruit_page_title = 'Свій заголовок'
    assert svc.recruit_text('recruit_page_title', settings) == 'Свій заголовок'


def test_default_is_translated_for_english(app):
    settings = SiteSettings.get()
    settings.recruit_page_title = ''
    with app.test_request_context('/en/'), force_locale('en'):
        assert svc.recruit_text('recruit_page_title', settings) != DEFAULTS['recruit_page_title']


def test_paragraphs_split_on_blank_line_and_keep_lines():
    assert svc.paragraphs('А\nБ\n\nВ') == [['А', 'Б'], ['В']]
    assert svc.paragraphs('') == []


def test_benefit_lines_skip_blanks():
    assert svc.benefit_lines('Перша\n\n Друга \n') == ['Перша', 'Друга']


# --- заявка ----------------------------------------------------------------

def test_answers_store_ukrainian_label_and_code(app):
    item = _application()
    first = item.answers[0]
    assert first == {'key': 'plasma_years',
                     'label': 'Як давно ви використовуєте PRP- та плазмотерапію?',
                     'value': '1_3'}


def test_answers_snapshot_stays_ukrainian_for_english_applicant(app):
    with app.test_request_context('/en/'), force_locale('en'):
        item = svc.create_application(_form(), 'en')
    assert item.locale == 'en'
    assert item.answers[0]['label'] == 'Як давно ви використовуєте PRP- та плазмотерапію?'
    assert item.answer_rows[0] == ('Як давно ви використовуєте PRP- та плазмотерапію?', '1-3 роки')


def test_empty_optional_answer_is_kept_as_empty_string(app):
    item = _application(q_equipment='')
    assert {'key': 'equipment',
            'label': 'З якими системами пробірок і обладнанням працюєте?',
            'value': ''} in item.answers


# --- лист ------------------------------------------------------------------

def test_notify_never_raises(app, monkeypatch):
    item = _application()

    def boom(_application):
        raise RuntimeError('smtp down')

    monkeypatch.setattr('app.services.email_service.EmailService.'
                        'send_trainer_application_notification', staticmethod(boom))
    svc.notify(item)  # без винятку


def test_notification_goes_to_rule_recipients(app, monkeypatch):
    from app.models.notification_rule import NotificationRule
    from app.services.email_service import EmailService

    rule = db.session.get(NotificationRule, 'trainer_application') or NotificationRule(
        event_type='trainer_application')
    rule.enabled = True
    rule.notify_admins = False
    rule.extra_emails = ['dmytro@example.com']
    db.session.add(rule)
    db.session.flush()

    sent = []
    monkeypatch.setattr(EmailService, '_send_to_recipients',
                        staticmethod(lambda recipients, **kw: sent.append((recipients, kw)) or []))
    EmailService.send_trainer_application_notification(_application())
    assert sent[0][0] == ['dmytro@example.com']
    assert sent[0][1]['trigger'] == 'trainer_application'
    assert 'Іваненко Іван Петрович' in sent[0][1]['subject']


def test_notification_template_renders_answers(app):
    from flask import render_template
    item = _application()
    with app.test_request_context('/'):
        html = render_template('emails/trainer_application_notification.html',
                               application=item, admin_url='/admin/trainer-applications/1')
    assert 'Як давно ви використовуєте PRP- та плазмотерапію?' in html
    assert '1-3 роки' in html
    assert 'PRP у трихології' in html


# --- «Створити тренера» ---------------------------------------------------

def test_create_trainer_copies_fields_and_stays_inactive(app):
    item = _application()
    trainer, warning = svc.create_trainer(item)
    db.session.flush()
    assert warning is None
    assert trainer.is_active is False
    assert trainer.full_name == 'Іваненко Іван Петрович'
    assert trainer.email == item.email
    assert trainer.slug.startswith('ivanenko-ivan-petrovych')
    assert trainer.profile.specialty == 'Дерматологія'
    assert trainer.profile.phone == '+380501112233'
    assert trainer.profile.workplace == 'Клініка, лікар'
    assert item.trainer_id == trainer.id


def test_create_trainer_twice_is_refused(app):
    item = _application()
    svc.create_trainer(item)
    db.session.flush()
    with pytest.raises(svc.AlreadyConverted):
        svc.create_trainer(item)


def test_duplicate_name_gets_unique_slug(app):
    first, _ = svc.create_trainer(_application())
    db.session.flush()
    second, _ = svc.create_trainer(_application())
    db.session.flush()
    assert first.slug != second.slug
    assert second.slug.startswith(first.slug)


def test_confirmed_account_is_linked(app):
    email = f'acc-{_uid()}@example.com'
    user = User.create_with_password(email, 'password123', first_name='I', last_name='I',
                                     email_confirmed=True)
    db.session.flush()
    trainer, warning = svc.create_trainer(_application(email=email))
    assert warning is None
    assert trainer.user_id == user.id


def test_unconfirmed_account_not_linked_with_warning(app):
    email = f'acc-{_uid()}@example.com'
    User.create_with_password(email, 'password123', first_name='I', last_name='I',
                              email_confirmed=False)
    db.session.flush()
    trainer, warning = svc.create_trainer(_application(email=email))
    assert trainer.user_id is None
    assert warning


def test_account_of_another_trainer_not_linked(app):
    email = f'acc-{_uid()}@example.com'
    user = User.create_with_password(email, 'password123', first_name='I', last_name='I',
                                     email_confirmed=True)
    db.session.add(Trainer(full_name='Інший', slug=f'other-{_uid()}', user_id=user.id))
    db.session.flush()
    trainer, warning = svc.create_trainer(_application(email=email))
    assert trainer.user_id is None
    assert warning
