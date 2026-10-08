"""Журнал адмінських дій ('audit') мусить реально писатися.

Логер 'audit' лежить поза деревом 'app', і довго жив на рівні WARNING без
обробника: усі audit_logger.info ("Admin X changed reg N payment: ...")
мовчки зникали. Коли знадобилося з'ясувати, хто й коли позначив рахунки
оплаченими, у журналі сервера не знайшлося жодного такого рядка.
"""
import logging

from app import _configure_logging


def _audit_handlers():
    return [h for h in logging.getLogger('audit').handlers
            if getattr(h, '_iprm_audit', False)]


def test_audit_info_is_enabled(app):
    assert logging.getLogger('audit').isEnabledFor(logging.INFO)


def test_audit_has_its_own_handler(app):
    assert len(_audit_handlers()) == 1


def test_repeated_setup_does_not_duplicate_lines(app):
    """Саме налаштування логів, а не create_app: кожен зайвий застосунок
    реєструє ще й глобальні слухачі БД, і сусідні тести бачать подію
    партнеру двічі-тричі."""
    _configure_logging(app)
    _configure_logging(app)
    assert len(_audit_handlers()) == 1


def test_record_reaches_the_handler(app, caplog):
    with caplog.at_level(logging.INFO, logger='audit'):
        logging.getLogger('audit').info('Admin %s changed reg %d payment: %s -> %s',
                                        'a@test.com', 1, 'unpaid', 'paid')
    assert 'changed reg 1 payment: unpaid -> paid' in caplog.text


def test_line_actually_reaches_stderr():
    """Справжній симптом: окремий процес, як gunicorn, без caplog, що сам
    піднімає рівень. До виправлення stderr лишався порожнім."""
    import subprocess
    import sys
    from pathlib import Path

    code = ("import logging; from app import create_app; create_app('testing'); "
            "logging.getLogger('audit').info('AUDIT-PROBE-42')")
    result = subprocess.run([sys.executable, '-c', code], capture_output=True,
                            text=True, cwd=Path(__file__).resolve().parents[1],
                            timeout=120)
    assert 'AUDIT-PROBE-42' in result.stderr, result.stderr[-2000:]
