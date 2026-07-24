"""Синхронність JS-словника: кожен україномовний t('...') у публічних
JS-файлах має бути в app/js_strings.py (інакше не перекладеться)."""
import os
import re

from app.js_strings import JS_STRINGS, js_translations

# t('...') або iprmI18n.t('...') з кириличним рядком (одинарні/подвійні лапки).
_CALL = re.compile(
    r"""(?:iprmI18n\.t|(?<![\w.])t)\(\s*(['"])(.*?[А-Яа-яЇїІіЄєҐґ].*?)\1""",
    re.DOTALL,
)
JS_DIR = os.path.join('app', 'static', 'js')


def _used_strings():
    used = {}
    for fn in os.listdir(JS_DIR):
        if not fn.endswith('.js'):
            continue
        src = open(os.path.join(JS_DIR, fn), encoding='utf-8').read()
        for _q, text in _CALL.findall(src):
            used.setdefault(text, fn)
    return used


def test_every_js_call_is_registered():
    catalog = set(JS_STRINGS)
    missing = {t: fn for t, fn in _used_strings().items() if t not in catalog}
    assert not missing, f'JS t() рядки поза JS_STRINGS: {missing}'


def test_js_translations_returns_full_dict(app):
    with app.test_request_context('/'):
        data = js_translations()
    assert isinstance(data, dict)
    assert len(data) == len(JS_STRINGS)
    # для uk значення = ключ (вихідна мова)
    for key in JS_STRINGS:
        assert data.get(key) == key


def test_js_dict_translated_for_ru(app):
    with app.test_request_context('/ru/'):
        from flask import g
        g.lang_code = 'ru'
        data = js_translations()
    # хоча б частина рядків має відрізнятись від українських ключів
    assert any(v != k for k, v in data.items())
