"""Міграція trainer_recruit_20261009: ланцюжок і збіг CHECK-ів із моделями.

`upgrade()` тут не проганяється -- тестова схема будується create_all (та
сама причина, що в test_migration_lect_cert_emailed.py).
"""
import importlib.util
import re
from pathlib import Path

import pytest

from app.models.email_log import EmailLog
from app.models.notification_rule import EVENT_TYPES

MIGRATION_PATH = (Path(__file__).resolve().parents[2]
                  / 'migrations' / 'versions' / 'trainer_recruit_20261009.py')


@pytest.fixture(scope='module')
def migration():
    spec = importlib.util.spec_from_file_location('m_trainer_recruit', MIGRATION_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _codes(check_sql):
    return set(re.findall(r"'([a-z_]+)'", check_sql))


def test_revision_id_fits_varchar32(migration):
    assert len(migration.revision) <= 32


def test_email_trigger_check_matches_model(migration):
    assert _codes(migration._TRIGGERS_NEW) == set(EmailLog.ALLOWED_TRIGGERS)


def test_event_type_check_matches_model(migration):
    assert _codes(migration._TYPES_NEW) == {code for code, _ in EVENT_TYPES}
