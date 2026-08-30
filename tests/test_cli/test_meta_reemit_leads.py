"""Бекфіл заявок, уже надісланих партнеру старим payload-ом.

Без цієї команди робота не має сенсу для НАЯВНИХ заявок: вони доїхали до
партнера без `answers` і без `offer`, а самі себе не перевідправлять.

Ідемпотентність тримає ПРИЙМАЧ (унікальний `leadgen_id` на його боці), а
не ця команда. Тут -- лише відбір і `--dry-run`, щоб було видно, що саме
поїде, перш ніж воно поїде.
"""
import itertools
from datetime import datetime, timedelta, timezone

import pytest

from app.extensions import db
from app.models.meta_lead import MetaLead

# Лічильник, а не id(object()): у CPython щойно звільнена адреса тимчасового
# object() детерміновано переюзається наступним викликом у тому самому
# виразі, тож два _lead() з однаковим days_ago в одному тесті інакше
# отримували б однаковий leadgen_id і падали на UNIQUE constraint.
_lead_seq = itertools.count()


def _lead(days_ago, **over):
    params = {
        'leadgen_id': f'lg-{days_ago}-{next(_lead_seq)}',
        'created_time': datetime.now(timezone.utc) - timedelta(days=days_ago),
        'form_id': '900',
        'field_data': {},
        'email': f'lead{days_ago}@test.local',
    }
    params.update(over)
    lead = MetaLead(**params)
    db.session.add(lead)
    db.session.flush()
    return lead


def test_only_leads_since_the_date_are_replayed(app, monkeypatch):
    sent = []
    monkeypatch.setattr('app.services.partner_events.emit_lead_created',
                        lambda lead: sent.append(lead.leadgen_id))
    recent = _lead(2)
    _lead(90)
    db.session.commit()

    runner = app.test_cli_runner()
    since = (datetime.now(timezone.utc) - timedelta(days=7)).date().isoformat()
    result = runner.invoke(args=['meta-reemit-leads', '--since', since])

    assert result.exit_code == 0
    assert sent == [recent.leadgen_id]


def test_dry_run_sends_nothing(app, monkeypatch):
    sent = []
    monkeypatch.setattr('app.services.partner_events.emit_lead_created',
                        lambda lead: sent.append(lead.leadgen_id))
    _lead(1)
    db.session.commit()

    runner = app.test_cli_runner()
    since = (datetime.now(timezone.utc) - timedelta(days=7)).date().isoformat()
    result = runner.invoke(
        args=['meta-reemit-leads', '--since', since, '--dry-run'])

    assert result.exit_code == 0
    assert sent == []
    assert 'буде надіслано' in result.output


def test_test_and_deleted_leads_are_skipped(app, monkeypatch):
    """Ті самі відсіювання, що й у живому шляху: чужу базу не смітимо."""
    sent = []
    monkeypatch.setattr('app.services.partner_events.emit_lead_created',
                        lambda lead: sent.append(lead.leadgen_id))
    _lead(1, is_test=True)
    _lead(1, deleted_at=datetime.now(timezone.utc))
    db.session.commit()

    runner = app.test_cli_runner()
    since = (datetime.now(timezone.utc) - timedelta(days=7)).date().isoformat()
    runner.invoke(args=['meta-reemit-leads', '--since', since])

    assert sent == []
