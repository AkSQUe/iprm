"""Адмінка лідів Meta Lead Ads: реєстр заявок, картка, сира черга, налаштування.

Чотири сторінки з різною ціною помилки, тому вони й розділені:

  /admin/meta-leads           -- реєстр заявок із годинником очікування;
  /admin/meta-leads/<id>      -- картка однієї заявки й перша реакція;
  /admin/meta-leads/events    -- сира черга подій leadgen (без видалення);
  /admin/meta-leads/settings  -- облікові дані Meta, стан токена, діагностика.

Головне на реєстрі -- НЕ кількість лідів, а час до першої реакції. Тому
годинник очікування виводиться окремою колонкою з градацією порогів, а
перехід заявки в «у роботі» проставляє `first_touch_at`/`first_touch_by`:
саме ця пара, а не факт зміни статусу, дає метрику швидкості дзвінка.
"""
import hashlib
import hmac
import json
import logging
import uuid
from datetime import datetime, timedelta, timezone

import requests
from flask import flash, redirect, render_template, request, url_for
from flask_login import current_user
from sqlalchemy.orm import joinedload

from app.admin import _listing, admin_bp
from app.admin._helpers import mask_secret, save_integration_settings, try_commit
from app.admin.decorators import admin_required
from app.admin.forms import MetaLeadAdminForm, MetaLeadsSettingsForm
from app.extensions import db, limiter
from app.models.meta_lead import MAX_EVENT_ATTEMPTS, MetaLead, MetaLeadEvent
from app.models.mixins import utcnow
from app.models.site_settings import SiteSettings
from app.services.meta_contracts import DEFAULT_GRAPH_VERSION
from app.services.meta_graph_client import MetaConfigError, MetaGraphClient
from app.undo import offer_undo

logger = logging.getLogger(__name__)
audit_logger = logging.getLogger('audit')


# ---------------------------------------------------------------------------
# Годинник очікування
# ---------------------------------------------------------------------------

# Пороги першої реакції. 15 хвилин -- межа, за якою імовірність додзвонитись
# падає стрімко; година -- межа, за якою лід практично охолов. Тримаємо їх
# тут, а не в шаблоні: те саме значення читає і колонка, і лічильник
# «прострочених» над списком.
WAIT_WARN_SECONDS = 15 * 60
WAIT_LATE_SECONDS = 60 * 60

WAIT_FRESH = 'fresh'
WAIT_WARN = 'warn'
WAIT_LATE = 'late'
WAIT_DONE = 'done'


def wait_level(lead):
    """Градація очікування для CSS-модифікатора колонки.

    Уже взятий у роботу лід виводиться нейтрально незалежно від того,
    скільки чекав: червоний колір на закритій заявці кричав би про роботу,
    яку вже зроблено.
    """
    if lead.first_touch_at is not None:
        return WAIT_DONE
    seconds = lead.waiting_seconds
    if seconds < WAIT_WARN_SECONDS:
        return WAIT_FRESH
    if seconds < WAIT_LATE_SECONDS:
        return WAIT_WARN
    return WAIT_LATE


def wait_text(seconds):
    """Тривалість очікування словами: «7 хв», «2 год 15 хв», «3 дн 4 год»."""
    seconds = max(0, int(seconds or 0))
    minutes, hours = seconds // 60, seconds // 3600
    if minutes < 1:
        return 'щойно'
    if minutes < 60:
        return f'{minutes} хв'
    if hours < 24:
        rest = minutes - hours * 60
        return f'{hours} год {rest} хв' if rest else f'{hours} год'
    days = hours // 24
    rest = hours - days * 24
    return f'{days} дн {rest} год' if rest else f'{days} дн'


# Бейджі спільної адмінської палітри. Мапа, а не властивість моделі: колір
# -- це рішення шару подання, і модель про CSS знати не мусить.
LEAD_STATUS_BADGE = {
    MetaLead.STATUS_NEW: 'warning',
    MetaLead.STATUS_IN_WORK: 'pending',
    MetaLead.STATUS_CLOSED: 'success',
    MetaLead.STATUS_DISMISSED: 'draft',
}

EVENT_STATUS_BADGE = {
    MetaLeadEvent.STATUS_PENDING: 'pending',
    MetaLeadEvent.STATUS_PROCESSING: 'pending',
    MetaLeadEvent.STATUS_RETRYING: 'retrying',
    MetaLeadEvent.STATUS_DONE: 'success',
    MetaLeadEvent.STATUS_SKIPPED: 'draft',
    MetaLeadEvent.STATUS_FAILED: 'failed',
}


# ---------------------------------------------------------------------------
# Реєстр лідів
# ---------------------------------------------------------------------------

_ATTENTION_OPTIONS = {'yes': 'Потребує уваги', 'no': 'Без зауважень'}

# Тестові заявки сховані за замовчуванням (рішення Q7): інструмент Lead Ads
# Testing Tool ллє їх тим самим шляхом, що й реальні, і без цього фільтра
# реєстр менеджера засмічувався б власними перевірками інтеграції.
_TEST_OPTIONS = {'with': 'Разом із тестовими', 'only': 'Лише тестові'}

_PLATFORM_OPTIONS = {'fb': 'Facebook', 'ig': 'Instagram'}


def _lead_filters():
    """Фільтри реєстру -- спільні для сторінки й експорту."""
    return {
        'q': _listing.text_arg('q'),
        'status': _listing.choice_arg('status', dict(MetaLead.STATUSES)),
        'form_id': _listing.text_arg('form_id'),
        'campaign_id': _listing.text_arg('campaign_id'),
        'platform': _listing.choice_arg('platform', _PLATFORM_OPTIONS),
        'attention': _listing.choice_arg('attention', _ATTENTION_OPTIONS),
        'test': _listing.choice_arg('test', _TEST_OPTIONS),
        'date_from': _listing.date_arg('date_from'),
        'date_to': _listing.date_arg('date_to'),
        'per_page': _listing.choice_arg('per_page', _listing.PER_PAGE_CHOICES),
    }


def _leads_query(filters):
    """Заявки під фільтри, найновіші першими. М'яко видалені не показуються."""
    query = MetaLead.alive().options(joinedload(MetaLead.user))

    query = _listing.apply_search(query, filters['q'], [
        MetaLead.full_name, MetaLead.first_name, MetaLead.last_name,
        MetaLead.email, MetaLead.alt_email,
        MetaLead.phone_raw, MetaLead.phone_e164,
    ])
    if filters['status']:
        query = query.filter(MetaLead.status == filters['status'])
    if filters['form_id']:
        query = query.filter(MetaLead.form_id == filters['form_id'])
    if filters['campaign_id']:
        query = query.filter(MetaLead.campaign_id == filters['campaign_id'])
    if filters['platform']:
        query = query.filter(MetaLead.platform == filters['platform'])
    if filters['attention']:
        query = query.filter(
            MetaLead.needs_attention.is_(filters['attention'] == 'yes')
        )
    if filters['test'] == 'only':
        query = query.filter(MetaLead.is_test.is_(True))
    elif filters['test'] != 'with':
        query = query.filter(MetaLead.is_test.is_(False))
    query = _listing.apply_date_range(
        query, MetaLead.created_time, filters['date_from'], filters['date_to'],
    )
    return query.order_by(MetaLead.created_time.desc())


def _source_options(column_id, column_name):
    """Пари (id, назва) для селектів «форма» / «кампанія».

    Беремо з наявних заявок, а не з Graph API: сторінка має відкриватись і
    при мертвому токені, а перелік у селекті потрібен рівно той, за яким у
    базі справді є що показати.
    """
    rows = (
        db.session.query(column_id, column_name)
        .filter(MetaLead.deleted_at.is_(None), column_id.isnot(None))
        .distinct()
        .all()
    )
    seen = {}
    for value, label in rows:
        seen.setdefault(value, label or value)
    return sorted(seen.items(), key=lambda pair: (pair[1] or '').lower())


def _lead_summary():
    """Лічильники над реєстром: скільки чекає і скільки вже прострочено.

    Прострочені рахуються тим самим порогом, що фарбує колонку -- інакше
    цифра над списком і кольори в ньому розповідали б різні історії.
    """
    base = MetaLead.alive().filter(MetaLead.is_test.is_(False))
    late_before = utcnow() - timedelta(seconds=WAIT_LATE_SECONDS)
    return {
        'total': base.count(),
        'new': base.filter(MetaLead.status == MetaLead.STATUS_NEW).count(),
        'in_work': base.filter(MetaLead.status == MetaLead.STATUS_IN_WORK).count(),
        'attention': base.filter(MetaLead.needs_attention.is_(True)).count(),
        'late': base.filter(
            MetaLead.first_touch_at.is_(None),
            MetaLead.status == MetaLead.STATUS_NEW,
            MetaLead.created_time < late_before,
        ).count(),
        'test': MetaLead.alive().filter(MetaLead.is_test.is_(True)).count(),
    }


@admin_bp.route('/meta-leads')
@admin_required
def meta_leads_list():
    filters = _lead_filters()
    pagination = _leads_query(filters).paginate(
        page=request.args.get('page', 1, type=int),
        per_page=_listing.per_page_arg(), error_out=False,
    )
    return render_template(
        'admin/meta_leads.html',
        leads=pagination.items,
        pagination=pagination,
        filters=filters,
        filter_args=_listing.filter_args(filters),
        per_page_options=_listing.PER_PAGE_OPTIONS,
        status_options=MetaLead.STATUSES,
        form_options=_source_options(MetaLead.form_id, MetaLead.form_name),
        campaign_options=_source_options(MetaLead.campaign_id, MetaLead.campaign_name),
        platform_options=list(_PLATFORM_OPTIONS.items()),
        attention_options=list(_ATTENTION_OPTIONS.items()),
        test_options=list(_TEST_OPTIONS.items()),
        summary=_lead_summary(),
        status_badge=LEAD_STATUS_BADGE,
        wait_level=wait_level,
        wait_text=wait_text,
    )


_LEAD_COLS = [
    'created_at', 'waiting', 'name', 'email', 'phone', 'campaign', 'form',
    'platform', 'match', 'user_id', 'status', 'attention', 'first_touch_at',
    'notes', 'leadgen_id',
]
_LEAD_LABELS = {
    'created_at': 'Заявка', 'waiting': 'Очікування', 'name': 'Ім\'я',
    'email': 'Email', 'phone': 'Телефон', 'campaign': 'Кампанія',
    'form': 'Форма', 'platform': 'Платформа', 'match': 'Збіг',
    'user_id': 'Контакт', 'status': 'Статус', 'attention': 'Потребує уваги',
    'first_touch_at': 'Перша реакція', 'notes': 'Нотатки',
    'leadgen_id': 'ID у Meta',
}
_LEAD_WIDTHS = {
    'created_at': 18, 'waiting': 14, 'name': 26, 'email': 28, 'phone': 18,
    'campaign': 30, 'form': 30, 'platform': 12, 'match': 16, 'user_id': 10,
    'status': 14, 'attention': 40, 'first_touch_at': 18, 'notes': 40,
    'leadgen_id': 22,
}


def _kyiv_naive(value):
    """Дата в київському часі без tzinfo -- Excel не розуміє зсув."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value
    return value.astimezone(_listing.KYIV).replace(tzinfo=None)


@admin_bp.route('/meta-leads/export')
@admin_required
def meta_leads_export():
    """Експорт реєстру у xlsx з урахуванням активних фільтрів."""
    from app.services import xlsx_reports

    filters = _lead_filters()
    rows = _leads_query(filters).all()
    data = [
        [
            _kyiv_naive(lead.created_time),
            wait_text(lead.waiting_seconds),
            lead.display_name,
            lead.email or '',
            lead.phone_e164 or lead.phone_raw or '',
            lead.campaign_name or lead.campaign_id or '',
            lead.form_name or lead.form_id or '',
            lead.platform_label,
            lead.match_label,
            lead.user_id or '',
            lead.status_label,
            lead.attention_reason or ('так' if lead.needs_attention else ''),
            _kyiv_naive(lead.first_touch_at),
            lead.admin_notes or '',
            lead.leadgen_id,
        ]
        for lead in rows
    ]
    summary = _listing.export_summary(
        [
            ('Пошук', filters['q'] or '–'),
            ('Статус', dict(MetaLead.STATUSES).get(filters['status'], 'Усі')),
            ('Кампанія', filters['campaign_id'] or 'Усі'),
            ('Форма', filters['form_id'] or 'Усі'),
            ('Платформа', _PLATFORM_OPTIONS.get(filters['platform'], 'Усі')),
            ('Потребує уваги',
             _ATTENTION_OPTIONS.get(filters['attention'], 'Усі')),
            ('Тестові', _TEST_OPTIONS.get(filters['test'], 'Сховані')),
            ('Дата заявки', _listing.date_range_label(filters)),
        ],
        len(data),
    )
    audit_logger.info(
        'Admin %s exported meta leads xlsx (%d rows, filters=%s)',
        current_user.email, len(data), filters,
    )
    return _listing.xlsx_export(
        rows, 'meta-leads',
        lambda: xlsx_reports.build_list_xlsx(
            'Ліди Meta', _LEAD_COLS, _LEAD_LABELS, _LEAD_WIDTHS, data,
            'tblMetaLeads', applied_filters=summary,
        ),
        'admin.meta_leads_list', **_listing.filter_args(filters),
    )


# ---------------------------------------------------------------------------
# Картка ліда
# ---------------------------------------------------------------------------

# Поля Meta, що вже розібрані в окремі колонки. У блоці «відповіді форми»
# їх не дублюємо -- лишаються тільки кастомні питання кампанії.
_STANDARD_FIELDS = frozenset({
    'email', 'phone_number', 'phone', 'full_name', 'first_name', 'last_name',
})


def _custom_answers(lead):
    """Відповіді на нестандартні питання форми: {питання: відповідь}."""
    data = lead.field_data if isinstance(lead.field_data, dict) else {}
    return {
        name: value for name, value in data.items()
        if name not in _STANDARD_FIELDS
    }


@admin_bp.route('/meta-leads/<int:lead_id>', methods=['GET', 'POST'])
@admin_required
def meta_lead_detail(lead_id):
    lead = db.session.get(MetaLead, lead_id)
    if not lead or lead.is_deleted:
        flash('Заявку не знайдено', 'error')
        return redirect(url_for('admin.meta_leads_list'))

    form = MetaLeadAdminForm(obj=lead)

    if form.validate_on_submit():
        old_status = lead.status
        lead.status = form.status.data
        lead.admin_notes = (form.admin_notes.data or '').strip() or None
        lead.is_test = bool(form.is_test.data)

        # Перша реакція фіксується САМЕ тут і лише один раз: повернення
        # заявки в роботу після закриття не має переписувати момент, за
        # яким рахується швидкість першого дзвінка.
        if lead.status == MetaLead.STATUS_IN_WORK and lead.first_touch_at is None:
            lead.first_touch_at = utcnow()
            lead.first_touch_by = current_user.id

        if try_commit(log_context=f'meta_lead_detail id={lead_id}'):
            audit_logger.info(
                'Admin %s updated meta lead %s: status %s -> %s',
                current_user.email, lead_id, old_status, lead.status,
            )
            flash('Заявку оновлено', 'success')
            return redirect(url_for('admin.meta_lead_detail', lead_id=lead_id))

    events = (
        MetaLeadEvent.query
        .filter(db.or_(MetaLeadEvent.lead_id == lead.id,
                       MetaLeadEvent.leadgen_id == lead.leadgen_id))
        .order_by(MetaLeadEvent.created_at.desc())
        .all()
    )

    return render_template(
        'admin/meta_lead_detail.html',
        lead=lead,
        form=form,
        events=events,
        custom_answers=_custom_answers(lead),
        status_badge=LEAD_STATUS_BADGE,
        event_status_badge=EVENT_STATUS_BADGE,
        max_attempts=MAX_EVENT_ATTEMPTS,
        wait_level=wait_level,
        wait_text=wait_text,
        contact_check=_contact_removal_check(lead),
    )


# ---------------------------------------------------------------------------
# Видалення тестових заявок
# ---------------------------------------------------------------------------

def _contact_removal_check(lead):
    """Чи піде контакт під ніж разом із заявкою -- і чому саме так.

    Дві межі, які тут легко перейти:

    * контакт зносимо ЛИШЕ якщо його створила ця сама заявка
      (`match_method='created'`). Заявка, що просто причепилась до наявної
      картки, видаляє тільки себе;
    * і ЛИШЕ якщо в контакта немає жодного іншого сліду: реєстрацій,
      покупок онлайн-курсів, інших заявок, пароля, адмін-прав. Інакше
      прибирання тестового ліда знесло б живого клієнта.

    Повертає {'user', 'can_delete', 'reasons'} -- перелік слідів показуємо
    менеджеру, щоб рішення «чому контакт лишився» не було мовчазним.
    """
    from app.models.online_enrollment import OnlineEnrollment

    user = lead.user
    if user is None:
        return {'user': None, 'can_delete': False, 'reasons': []}
    if lead.match_method != MetaLead.MATCH_CREATED:
        return {
            'user': user, 'can_delete': False,
            'reasons': ['контакт існував до цієї заявки'],
        }

    reasons = []
    if user.registrations.count():
        reasons.append('має реєстрації на заходи')
    if OnlineEnrollment.query.filter_by(user_id=user.id).count():
        reasons.append('має замовлення онлайн-курсів')
    other_leads = MetaLead.query.filter(
        MetaLead.user_id == user.id, MetaLead.id != lead.id,
        MetaLead.deleted_at.is_(None),
    ).count()
    if other_leads:
        reasons.append(f'має інші заявки з Meta ({other_leads})')
    if MetaLead.query.filter(MetaLead.conflict_user_id == user.id).count():
        reasons.append('на нього вказує конфлікт іншої заявки')
    if user.has_password:
        reasons.append('має пароль для входу')
    if user.is_admin:
        reasons.append('має адмін-права')

    return {'user': user, 'can_delete': not reasons, 'reasons': reasons}


def _detach_events(lead):
    """Відв'язати сирі події від заявки, не видаляючи їх.

    Подія leadgen НЕ видаляється ніколи -- саме вона тримає
    ідемпотентність: після видалення заявки повторна доставка того самого
    `leadgen_id` (Meta ретраїть, звірка перечитує 48 годин) упізнає подію
    як уже оброблену і не воскресить видалене.
    """
    for event in MetaLeadEvent.query.filter_by(lead_id=lead.id).all():
        event.lead_id = None


def _remove_lead(lead):
    """М'яко видалити заявку, прибравши контакт лише за суворих умов.

    Повертає True, якщо разом із заявкою знесено й контакт: від цього
    залежить, чи можна пропонувати відкат (видалення контакту незворотне,
    тож undo там був би обіцянкою, якої система не виконає).
    """
    check = _contact_removal_check(lead)
    user = check['user'] if check['can_delete'] else None

    _detach_events(lead)
    lead.soft_delete()

    if user is not None:
        # Зв'язки самої заявки на контакт зануляємо явно: рядок ліда
        # лишається жити (м'яке видалення), і без цього FK вказував би на
        # неіснуючий рядок скрізь, де БД не має ON DELETE SET NULL.
        lead.user_id = None
        lead.conflict_user_id = None
        db.session.delete(user)
    return user is not None


@admin_bp.route('/meta-leads/<int:lead_id>/delete', methods=['POST'])
@admin_required
def meta_lead_delete(lead_id):
    lead = db.session.get(MetaLead, lead_id)
    if not lead or lead.is_deleted:
        flash('Заявку не знайдено', 'error')
        return redirect(url_for('admin.meta_leads_list'))

    label = lead.display_name
    contact_removed = _remove_lead(lead)
    if try_commit(log_context=f'meta_lead_delete id={lead_id}',
                  error_msg='Помилка при видаленні'):
        audit_logger.info(
            'Admin %s deleted meta lead %s (contact_removed=%s)',
            current_user.email, lead_id, contact_removed,
        )
        if contact_removed:
            # Відкат був би неповним: контакт видалено остаточно.
            flash(f'Заявку «{label}» і створений нею контакт видалено', 'success')
        else:
            offer_undo(
                f'Заявку «{label}» видалено',
                url_for('admin.meta_lead_restore', lead_id=lead_id),
            )
    return redirect(url_for('admin.meta_leads_list'))


@admin_bp.route('/meta-leads/<int:lead_id>/restore', methods=['POST'])
@admin_required
def meta_lead_restore(lead_id):
    lead = db.session.get(MetaLead, lead_id)
    if not lead or not lead.is_deleted:
        flash('Заявку вже не можна повернути', 'error')
        return redirect(url_for('admin.meta_leads_list'))

    lead.restore()
    # Повертаємо і зв'язок із сирою подією: вона лишилась у черзі, а
    # знайти її можна за тим самим `leadgen_id`, унікальним в обох таблицях.
    for event in MetaLeadEvent.query.filter_by(leadgen_id=lead.leadgen_id).all():
        event.lead_id = lead.id

    if try_commit(log_context=f'meta_lead_restore id={lead_id}',
                  error_msg='Помилка при відновленні'):
        audit_logger.info('Admin %s restored meta lead %s',
                          current_user.email, lead_id)
        flash('Заявку повернено', 'success')
    return redirect(url_for('admin.meta_lead_detail', lead_id=lead_id))


@admin_bp.route('/meta-leads/delete-test', methods=['POST'])
@admin_required
def meta_leads_delete_test():
    """Пакетне прибирання тестових заявок (рішення Q7).

    Відкату немає навмисно: пакет може знести десятки рядків, і тост із
    однією кнопкою «Повернути» приховував би, що саме повертається.
    """
    leads = MetaLead.alive().filter(MetaLead.is_test.is_(True)).all()
    contacts = 0
    for lead in leads:
        if _remove_lead(lead):
            contacts += 1

    if not leads:
        flash('Тестових заявок немає', 'success')
        return redirect(url_for('admin.meta_leads_list'))

    if try_commit(log_context='meta_leads_delete_test',
                  error_msg='Помилка при видаленні'):
        audit_logger.info(
            'Admin %s bulk-deleted %d test meta leads (%d contacts removed)',
            current_user.email, len(leads), contacts,
        )
        flash(
            f'Видалено тестових заявок: {len(leads)}. '
            f'Прибрано створених ними контактів: {contacts}. '
            'Сирі події лишились у черзі.',
            'success',
        )
    return redirect(url_for('admin.meta_leads_list'))


# ---------------------------------------------------------------------------
# Сира черга
# ---------------------------------------------------------------------------

_EVENT_SOURCES = {
    MetaLeadEvent.SOURCE_WEBHOOK: 'Вебхук',
    MetaLeadEvent.SOURCE_RECONCILE: 'Звірка',
    MetaLeadEvent.SOURCE_MANUAL: 'Вручну',
}


@admin_bp.route('/meta-leads/events')
@admin_required
def meta_lead_events():
    """Сира черга подій leadgen. Видалення тут немає і бути не може."""
    filters = {
        'q': _listing.text_arg('q'),
        'status': _listing.choice_arg('status', dict(MetaLeadEvent.STATUSES)),
        'source': _listing.choice_arg('source', _EVENT_SOURCES),
    }

    query = MetaLeadEvent.query
    query = _listing.apply_search(query, filters['q'], [
        MetaLeadEvent.leadgen_id, MetaLeadEvent.form_id, MetaLeadEvent.last_error,
    ])
    if filters['status']:
        query = query.filter(MetaLeadEvent.status == filters['status'])
    if filters['source']:
        query = query.filter(MetaLeadEvent.source == filters['source'])

    pagination = query.order_by(MetaLeadEvent.received_at.desc()).paginate(
        page=request.args.get('page', 1, type=int),
        per_page=_listing.per_page_arg(), error_out=False,
    )
    counts = dict(
        db.session.query(MetaLeadEvent.status, db.func.count(MetaLeadEvent.id))
        .group_by(MetaLeadEvent.status).all()
    )

    return render_template(
        'admin/meta_lead_events.html',
        events=pagination.items,
        pagination=pagination,
        filters=filters,
        filter_args=_listing.filter_args(filters),
        counts=counts,
        status_options=MetaLeadEvent.STATUSES,
        source_options=list(_EVENT_SOURCES.items()),
        source_labels=_EVENT_SOURCES,
        event_status_badge=EVENT_STATUS_BADGE,
        max_attempts=MAX_EVENT_ATTEMPTS,
    )


@admin_bp.route('/meta-leads/events/<int:event_id>/retry', methods=['POST'])
@admin_required
def meta_lead_event_retry(event_id):
    """Повернути подію в чергу: воркер забере її найближчим прогоном."""
    event = db.session.get(MetaLeadEvent, event_id)
    if not event:
        flash('Подію не знайдено', 'error')
        return redirect(url_for('admin.meta_lead_events'))

    event.status = MetaLeadEvent.STATUS_PENDING
    event.next_retry_at = None
    # Лічильник спроб обнуляємо: подія, що вичерпала ліміт, інакше впала б
    # знову на першій же ітерації, і кнопка нічого не робила б.
    event.attempts = 0
    # Текст останньої помилки лишаємо: доки нова спроба його не перезапише,
    # це єдина підказка, чому подія впала.

    if try_commit(log_context=f'meta_lead_event_retry id={event_id}'):
        audit_logger.info('Admin %s re-queued meta lead event %s (leadgen %s)',
                          current_user.email, event_id, event.leadgen_id)
        flash('Подію повернено в чергу', 'success')
    return redirect(url_for('admin.meta_lead_events', **request.args))


# ---------------------------------------------------------------------------
# Налаштування інтеграції
# ---------------------------------------------------------------------------

WEBHOOK_PATH = '/api/webhooks/meta/leads'
_TEST_EVENT_TIMEOUT = (3.0, 10.0)


def _webhook_url():
    """Публічна адреса нашого вебхука для вставки в налаштування Meta.

    Береться з `website_url` у налаштуваннях сайту, а не з `request.host`:
    адмінка може відкриватись і за внутрішньою адресою, а Meta мусить
    отримати саме бойовий домен.
    """
    base = (SiteSettings.get().website_url or '').strip().rstrip('/')
    return f'{base}{WEBHOOK_PATH}' if base else WEBHOOK_PATH


def _queue_stats():
    """Стан черги для сторінки налаштувань."""
    day_ago = utcnow() - timedelta(days=1)
    return {
        'pending': MetaLeadEvent.query.filter(MetaLeadEvent.status.in_((
            MetaLeadEvent.STATUS_PENDING, MetaLeadEvent.STATUS_PROCESSING,
            MetaLeadEvent.STATUS_RETRYING,
        ))).count(),
        'failed': MetaLeadEvent.query.filter(
            MetaLeadEvent.status == MetaLeadEvent.STATUS_FAILED,
        ).count(),
        'failed_24h': MetaLeadEvent.query.filter(
            MetaLeadEvent.status == MetaLeadEvent.STATUS_FAILED,
            MetaLeadEvent.received_at >= day_ago,
        ).count(),
        'total': MetaLeadEvent.query.count(),
    }


def _settings_config(settings):
    """Усе, що показує сторінка налаштувань -- одним словником."""
    return {
        'enabled': settings.meta_leads_enabled,
        'is_configured': settings.is_meta_leads_configured,
        'app_id': settings.meta_app_id or '',
        'app_secret_masked': mask_secret(settings.meta_app_secret),
        'app_secret_is_set': settings.meta_app_secret_is_set,
        'app_secret_set_at': settings.meta_app_secret_set_at,
        'verify_token_masked': mask_secret(settings.meta_verify_token),
        'verify_token_is_set': settings.meta_verify_token_is_set,
        'page_id': settings.meta_page_id or '',
        'page_name': settings.meta_page_name or '',
        'page_token_is_set': settings.meta_page_token_is_set,
        'page_token_set_at': settings.meta_page_token_set_at,
        'graph_version': settings.meta_graph_version or DEFAULT_GRAPH_VERSION,
        'webhook_url': _webhook_url(),
        'token_valid': settings.meta_token_valid,
        'token_checked_at': settings.meta_token_checked_at,
        'token_expires_at': settings.meta_token_expires_at,
        'token_error': settings.meta_token_error or '',
        'last_lead_at': settings.meta_last_lead_at,
        'last_webhook_at': settings.meta_last_webhook_at,
        'last_reconcile_at': settings.meta_last_reconcile_at,
        'last_reconcile_status': settings.meta_last_reconcile_status or '',
        'last_reconcile_error': settings.meta_last_reconcile_error or '',
        'reconcile_interval': settings.meta_reconcile_interval_minutes,
        'reconcile_lookback': settings.meta_reconcile_lookback_hours,
        'silence_alert_hours': settings.meta_silence_alert_hours,
        'error_alert_threshold': settings.meta_error_alert_threshold,
        'test_mode': settings.meta_test_mode,
        'test_mode_since': settings.meta_test_mode_since,
        'queue': _queue_stats(),
        'leads_total': MetaLead.alive().count(),
        'leads_test': MetaLead.alive().filter(MetaLead.is_test.is_(True)).count(),
    }


def _settings_form(settings):
    """Форма, наповнена поточними значеннями (секрети -- порожні)."""
    form = MetaLeadsSettingsForm()
    if request.method == 'GET':
        form.enabled.data = settings.meta_leads_enabled
        form.app_id.data = settings.meta_app_id or ''
        form.page_id.data = settings.meta_page_id or ''
        form.graph_version.data = settings.meta_graph_version or DEFAULT_GRAPH_VERSION
        form.reconcile_interval_minutes.data = settings.meta_reconcile_interval_minutes
        form.reconcile_lookback_hours.data = settings.meta_reconcile_lookback_hours
        form.silence_alert_hours.data = settings.meta_silence_alert_hours
        form.error_alert_threshold.data = settings.meta_error_alert_threshold
    return form


@admin_bp.route('/meta-leads/settings')
@admin_required
def meta_leads_settings():
    """Стан інтеграції. Мусить відкриватись і без жодного налаштування."""
    settings = SiteSettings.get()
    return render_template(
        'admin/meta_leads_settings.html',
        cfg=_settings_config(settings),
        form=_settings_form(settings),
    )


@admin_bp.route('/meta-leads/settings/save', methods=['POST'])
@admin_required
def meta_leads_settings_save():
    settings = SiteSettings.get()
    form = MetaLeadsSettingsForm()

    if not form.validate_on_submit():
        for field, errors in form.errors.items():
            flash(f'{form[field].label.text}: {"; ".join(errors)}', 'error')
        return redirect(url_for('admin.meta_leads_settings'))

    app_secret = (form.app_secret.data or '').strip()
    verify_token = (form.verify_token.data or '').strip()
    enabled = bool(form.enabled.data)

    # Стан перевіряємо ПІСЛЯ підстановки: порожнє поле секрета означає
    # «лишити наявний», тож увімкнення не має падати через нього.
    final_secret = bool(app_secret) or settings.meta_app_secret_is_set
    if enabled and not ((form.app_id.data or '').strip() and final_secret):
        flash('Щоб увімкнути приймання, потрібні App ID і App Secret', 'error')
        return redirect(url_for('admin.meta_leads_settings'))

    updates = {
        'meta_leads_enabled': enabled,
        'meta_app_id': (form.app_id.data or '').strip(),
        'meta_page_id': (form.page_id.data or '').strip(),
        'meta_graph_version': (
            (form.graph_version.data or '').strip() or DEFAULT_GRAPH_VERSION
        ),
    }
    for field, attr in (
        (form.reconcile_interval_minutes, 'meta_reconcile_interval_minutes'),
        (form.reconcile_lookback_hours, 'meta_reconcile_lookback_hours'),
        (form.silence_alert_hours, 'meta_silence_alert_hours'),
        (form.error_alert_threshold, 'meta_error_alert_threshold'),
    ):
        if field.data is not None:
            updates[attr] = field.data
    if app_secret:
        updates['meta_app_secret'] = app_secret
        updates['meta_app_secret_set_at'] = utcnow()
    if verify_token:
        updates['meta_verify_token'] = verify_token

    save_integration_settings(
        provider='meta_leads',
        settings=settings,
        updates=updates,
        audit_summary={
            'enabled': enabled,
            'app_id': updates['meta_app_id'],
            'page_id': updates['meta_page_id'],
            'app_secret_changed': bool(app_secret),
            'verify_token_changed': bool(verify_token),
        },
        success_msg='Налаштування Meta Lead Ads збережено',
    )
    return redirect(url_for('admin.meta_leads_settings'))


@admin_bp.route('/meta-leads/settings/test-mode', methods=['POST'])
@admin_required
def meta_leads_test_mode():
    """Перемикач «режим тестування».

    Graph API не віддає надійного прапорця «це тест», тож позначку ставимо
    самі: усе, що прийде при увімкненому режимі, лягає з `is_test=True`.
    Час увімкнення зберігаємо окремо -- без нього неможливо відповісти, чи
    був режим активний на момент конкретної заявки.
    """
    settings = SiteSettings.get()
    settings.meta_test_mode = not settings.meta_test_mode
    settings.meta_test_mode_since = utcnow() if settings.meta_test_mode else None

    if try_commit(log_context='meta_leads_test_mode'):
        audit_logger.info('Admin %s set meta test mode = %s',
                          current_user.email, settings.meta_test_mode)
        flash(
            'Режим тестування увімкнено: нові заявки позначатимуться як тестові'
            if settings.meta_test_mode else 'Режим тестування вимкнено',
            'success',
        )
    return redirect(url_for('admin.meta_leads_settings'))


def _client(settings, require_token=True):
    """Graph-клієнт або None (причина -- у flash).

    `require_token=False` для кроків первинного налаштування: Page token
    там ще не існує, його якраз і отримують.
    """
    try:
        return MetaGraphClient.from_settings(settings, require_token=require_token)
    except MetaConfigError as exc:
        flash(str(exc), 'error')
        return None


@admin_bp.route('/meta-leads/settings/check-token', methods=['POST'])
@admin_required
@limiter.limit('10 per minute')
def meta_leads_check_token():
    """`debug_token`: чи живий Page token, доки і з якими дозволами."""
    settings = SiteSettings.get()
    client = _client(settings)
    if client is None:
        return redirect(url_for('admin.meta_leads_settings'))

    result = client.debug_token()
    settings.meta_token_checked_at = utcnow()

    if result.ok and isinstance(result.data, dict):
        data = result.data
        settings.meta_token_valid = bool(data.get('is_valid'))
        expires = data.get('expires_at') or 0
        # 0 -- безстроковий; саме таким і має бути Page token.
        settings.meta_token_expires_at = (
            datetime.fromtimestamp(int(expires), tz=timezone.utc) if expires else None
        )
        settings.meta_token_error = ''
        scopes = ', '.join(data.get('scopes') or []) or 'не вказано'
        if settings.meta_token_valid:
            flash(f'Токен дійсний. Дозволи: {scopes}', 'success')
        else:
            flash('Meta вважає токен недійсним -- обміняйте його заново', 'error')
    else:
        settings.meta_token_valid = False
        settings.meta_token_error = (result.error or 'Невідома помилка')[:2000]
        flash(f'Перевірка не вдалась: {settings.meta_token_error}', 'error')

    try_commit(log_context='meta_leads_check_token')
    audit_logger.info('Admin %s checked meta token: valid=%s',
                      current_user.email, settings.meta_token_valid)
    return redirect(url_for('admin.meta_leads_settings'))


@admin_bp.route('/meta-leads/settings/exchange-token', methods=['POST'])
@admin_required
@limiter.limit('10 per minute')
def meta_leads_exchange_token():
    """Короткоживучий User token -> безстроковий Page token.

    Два кроки в одній дії: обмін на довгоживучий User token і витяг з нього
    токена Сторінки. Розділяти їх немає сенсу -- проміжний токен нікому,
    крім наступного кроку, не потрібен, а зберігати його означало б тримати
    в базі зайвий секрет.
    """
    settings = SiteSettings.get()
    short_token = (request.form.get('user_token') or '').strip()
    page_id = (request.form.get('page_id') or settings.meta_page_id or '').strip()

    if not short_token:
        flash('Вставте User token із Graph API Explorer', 'error')
        return redirect(url_for('admin.meta_leads_settings'))
    if not page_id:
        flash('Вкажіть ID Сторінки', 'error')
        return redirect(url_for('admin.meta_leads_settings'))

    client = _client(settings, require_token=False)
    if client is None:
        return redirect(url_for('admin.meta_leads_settings'))

    long_lived = client.exchange_long_lived_user_token(short_token)
    if not long_lived.ok:
        flash(f'Обмін не вдався: {long_lived.error}', 'error')
        return redirect(url_for('admin.meta_leads_settings'))

    user_token = (long_lived.data or {}).get('access_token')
    if not user_token:
        flash('Meta не повернула довгоживучий токен', 'error')
        return redirect(url_for('admin.meta_leads_settings'))

    page = client.get_page_token(page_id, user_token)
    if not page.ok:
        flash(f'Не вдалося отримати токен Сторінки: {page.error}', 'error')
        return redirect(url_for('admin.meta_leads_settings'))

    page_token = (page.data or {}).get('access_token')
    if not page_token:
        flash(
            'Meta не повернула токен Сторінки: перевірте роль на Сторінці '
            'і дозвіл leads_retrieval',
            'error',
        )
        return redirect(url_for('admin.meta_leads_settings'))

    save_integration_settings(
        provider='meta_leads',
        settings=settings,
        updates={
            'meta_page_token': page_token,
            'meta_page_token_set_at': utcnow(),
            'meta_page_id': page_id,
            'meta_page_name': (page.data or {}).get('name') or settings.meta_page_name,
        },
        audit_summary={'page_id': page_id, 'page_token_changed': True},
        success_msg='Page Access Token отримано і збережено',
    )
    return redirect(url_for('admin.meta_leads_settings'))


@admin_bp.route('/meta-leads/settings/subscribe', methods=['POST'])
@admin_required
@limiter.limit('10 per minute')
def meta_leads_subscribe():
    """Підписати Сторінку на `leadgen`: без цього вебхук мовчить."""
    settings = SiteSettings.get()
    page_id = (settings.meta_page_id or '').strip()
    if not page_id:
        flash('Спершу вкажіть ID Сторінки', 'error')
        return redirect(url_for('admin.meta_leads_settings'))

    client = _client(settings)
    if client is None:
        return redirect(url_for('admin.meta_leads_settings'))

    result = client.subscribe_page(page_id)
    audit_logger.info('Admin %s subscribed page %s to leadgen: ok=%s',
                      current_user.email, page_id, result.ok)
    if result.ok:
        flash('Сторінку підписано на події leadgen', 'success')
    else:
        flash(f'Підписка не вдалась: {result.error}', 'error')
    return redirect(url_for('admin.meta_leads_settings'))


@admin_bp.route('/meta-leads/settings/reconcile', methods=['POST'])
@admin_required
@limiter.limit('10 per minute')
def meta_leads_reconcile():
    """Ручна звірка: добрати ліди, які не доїхали вебхуком."""
    try:
        from app.services.meta_lead_queue import reconcile
    except ImportError:
        # Модуль звірки -- окрема частина роботи. Кнопка мусить сказати про
        # це словами, а не впасти в 500.
        flash('Модуль звірки ще не підключено', 'error')
        return redirect(url_for('admin.meta_leads_settings'))

    try:
        report = reconcile()
    except Exception as exc:
        logger.exception('Manual meta reconcile failed')
        flash(f'Звірка не вдалась: {exc}', 'error')
        return redirect(url_for('admin.meta_leads_settings'))

    audit_logger.info('Admin %s ran meta reconcile manually: %s',
                      current_user.email, report)
    flash(f'Звірку виконано: {report}', 'success')
    return redirect(url_for('admin.meta_leads_settings'))


@admin_bp.route('/meta-leads/settings/test-event', methods=['POST'])
@admin_required
@limiter.limit('10 per minute')
def meta_leads_test_event():
    """Надіслати самим собі коректно підписану подію leadgen.

    Це основний інструмент діагностики етапу без доступів Meta: успішна
    відповідь доводить одразу три речі -- ендпоінт доступний ЗЗОВНІ (запит
    іде публічним URL, а не всередині процесу), App Secret у налаштуваннях
    збігається з тим, яким рахується підпис, і чергу заповнено.
    """
    settings = SiteSettings.get()
    secret = (settings.meta_app_secret or '').strip()
    if not secret:
        flash('Спершу збережіть App Secret -- без нього підпис не порахувати',
              'error')
        return redirect(url_for('admin.meta_leads_settings'))

    leadgen_id = (request.form.get('leadgen_id') or '').strip() \
        or f'test-{uuid.uuid4().hex[:16]}'
    page_id = (settings.meta_page_id or '0').strip() or '0'
    now_ts = int(utcnow().timestamp())

    payload = {
        'object': 'page',
        'entry': [{
            'id': page_id,
            'time': now_ts,
            'changes': [{
                'field': 'leadgen',
                'value': {
                    'leadgen_id': leadgen_id,
                    'page_id': page_id,
                    'form_id': (request.form.get('form_id') or '').strip() or '0',
                    'created_time': now_ts,
                },
            }],
        }],
    }
    # Підпис рахується по ТИХ САМИХ байтах, що підуть у тіло: перерахунок
    # із json.dumps ще раз (з іншими роздільниками чи порядком ключів) дав
    # би інший HMAC і 401 від власного ж ендпоінта.
    body = json.dumps(payload, separators=(',', ':')).encode('utf-8')
    signature = hmac.new(secret.encode('utf-8'), body, hashlib.sha256).hexdigest()

    url = _webhook_url()
    try:
        response = requests.post(
            url, data=body,
            headers={
                'Content-Type': 'application/json',
                'X-Hub-Signature-256': f'sha256={signature}',
            },
            timeout=_TEST_EVENT_TIMEOUT,
        )
    except requests.RequestException as exc:
        logger.warning('Meta test event failed: %s', exc)
        flash(f'Не вдалося достукатись до {url}: {exc}', 'error')
        return redirect(url_for('admin.meta_leads_settings'))

    audit_logger.info('Admin %s sent meta test event %s -> HTTP %s',
                      current_user.email, leadgen_id, response.status_code)
    if response.status_code == 200:
        flash(
            f'Подію {leadgen_id} прийнято: HTTP 200. Дивіться сиру чергу.',
            'success',
        )
    elif response.status_code == 401:
        flash(
            'HTTP 401: підпис відхилено. App Secret у налаштуваннях не той, '
            'яким підписано запит.',
            'error',
        )
    else:
        flash(f'Відповідь ендпоінта: HTTP {response.status_code}', 'error')
    return redirect(url_for('admin.meta_leads_settings'))
