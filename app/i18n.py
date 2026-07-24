"""
Мультимовність (Flask-Babel): вибір локалі та мовний роутинг uk/ru/en.

URL-стратегія: українська (вихідна мова) -- БЕЗ префікса, ru/en -- з префіксом:
    /courses/abc        -> uk (усі історичні URL незмінні)
    /ru/courses/abc     -> ru
    /en/courses/abc     -> en

Реалізація -- LocalizedBlueprint: кожне правило реєструється двічі --
без префікса з defaults={'lang_code': 'uk'} і з префіксом
/<any(ru, en):lang_code>. Werkzeug при build обирає правило з defaults для
uk (непрефіксоване) і префіксоване для ru/en, тож наявні url_for(...) по
всьому коду працюють без змін; активну мову підставляє url_defaults-хук
(див. init_locale_routing).

Admin (/admin), партнерські API і сервісні роути (robots, sitemap,
токен-лінки) навмисно НЕ локалізуються: у роуті передайте localize=False.
"""
import copy

from flask import (
    Blueprint, current_app, g, has_request_context, redirect, request, session,
    url_for,
)

from config import Config

# Єдине джерело правди -- config.Config (config не імпортує app, циклу немає).
LANGUAGES = list(Config.LANGUAGES)
DEFAULT_LANGUAGE = Config.BABEL_DEFAULT_LOCALE
PREFIXED_LANGUAGES = [lang for lang in LANGUAGES if lang != DEFAULT_LANGUAGE]

# og:locale для <meta property="og:locale"> у base.html.
OG_LOCALES = {'uk': 'uk_UA', 'ru': 'ru_RU', 'en': 'en_US'}

# Підписи в перемикачі мов (короткі, без перекладу -- кожен своєю мовою).
LANGUAGE_LABELS = {'uk': 'UA', 'ru': 'RU', 'en': 'EN'}

_LANG_PREFIX = '/<any(' + ', '.join(PREFIXED_LANGUAGES) + '):lang_code>'


# --- Переклади JSON-структур: overrides за шляхом --------------------------
# Переклад JSON-поля (faq, блоки блогу, регалії, items) зберігається як
# ПЛОСКА мапа {шлях: текст}, а не повна копія структури. Читання (t())
# накладає overrides на ПОТОЧНУ українську структуру, тож зміни оригіналу
# (додані/переставлені блоки) підхоплюються автоматично, а застарілі шляхи
# просто ігноруються (фолбек на укр). Шлях -- крапко-роздільна адреса
# (напр. '0.data.html'); ключі структури НЕ можуть містити крапку.

def apply_json_overrides(base, overrides):
    """Повернути копію base з накладеними текстовими overrides {шлях: текст}.
    Перезаписує лише наявні РЯДКОВІ листки -- зміни структури оригіналу
    безпечні (невідповідні шляхи пропускаються)."""
    if not isinstance(overrides, dict):
        return base
    result = copy.deepcopy(base)
    for path, text in overrides.items():
        if isinstance(text, str):
            _set_leaf_if_str(result, path, text)
    return result


def _set_leaf_if_str(root, path, text):
    tokens = path.split('.')
    node = root
    try:
        for tok in tokens[:-1]:
            node = node[int(tok)] if isinstance(node, list) else node[tok]
        last = tokens[-1]
        if isinstance(node, list):
            idx = int(last)
            if 0 <= idx < len(node) and isinstance(node[idx], str):
                node[idx] = text
        elif isinstance(node, dict) and isinstance(node.get(last), str):
            node[last] = text
    except (KeyError, IndexError, TypeError, ValueError):
        return


def get_locale():
    """Селектор локалі для Flask-Babel (викликається ліниво на запит).

    Поза HTTP-запитом (scheduler, фонові рендери листів) повертає дефолт;
    для листів мовою отримувача обгортайте рендер у
    flask_babel.force_locale(...).

    Порядок: g.lang_code (URL-префікс) -> session['lang'] (вибір
    користувача) -> Accept-Language -> BABEL_DEFAULT_LOCALE.
    """
    default = current_app.config.get('BABEL_DEFAULT_LOCALE', DEFAULT_LANGUAGE)
    languages = current_app.config.get('LANGUAGES', [default])

    if not has_request_context():
        return default

    lang = g.get('lang_code')
    if lang in languages:
        return lang

    lang = session.get('lang')
    if lang in languages:
        return lang

    return request.accept_languages.best_match(languages) or default


class LocalizedBlueprint(Blueprint):
    """Blueprint із дзеркальними мовними правилами для кожного роуту.

    url_prefix НЕ передається у Flask, а застосовується поруляно тут --
    інакше мовний префікс опинявся б усередині шляху
    (/courses/ru/... замість /ru/courses/...).

    @bp.route('/path', localize=False) -- зареєструвати лише непрефіксоване
    правило (сервісні URL: robots.txt, sitemap.xml, токен-посилання з листів,
    OAuth-callback'и тощо).
    """

    def __init__(self, name, import_name, **kwargs):
        self._locale_prefix = kwargs.pop('url_prefix', None) or ''
        super().__init__(name, import_name, **kwargs)

    def add_url_rule(self, rule, endpoint=None, view_func=None, **options):
        rule = self._locale_prefix + rule
        if not options.pop('localize', True):
            super().add_url_rule(rule, endpoint, view_func, **options)
            return
        defaults = dict(options.get('defaults') or {})
        defaults['lang_code'] = DEFAULT_LANGUAGE
        super().add_url_rule(
            rule, endpoint, view_func, **{**options, 'defaults': defaults}
        )
        super().add_url_rule(_LANG_PREFIX + rule, endpoint, view_func, **options)


def init_locale_routing(app):
    """App-рівневі хуки мовного роутингу. Викликається з create_app()."""

    @app.url_value_preprocessor
    def pull_lang_code(endpoint, values):
        """Вийняти lang_code з URL у g (view-функції його не отримують)
        і зробити вибір мови "липким" через session."""
        if not values or 'lang_code' not in values:
            return
        g.lang_code = values.pop('lang_code')
        # uk-відвідувачам без сесії cookie не ставимо (відсутність
        # session['lang'] означає дефолтну мову).
        if session.get('lang') != g.lang_code and not (
            g.lang_code == DEFAULT_LANGUAGE and 'lang' not in session
        ):
            session['lang'] = g.lang_code

    @app.url_defaults
    def add_lang_code(endpoint, values):
        """Автопідстановка активної мови в url_for для локалізованих
        ендпоінтів: з /ru/ усі згенеровані посилання лишаються /ru/...
        Для uk нічого не підставляємо -- спрацьовує defaults-правило."""
        if 'lang_code' in values or not has_request_context():
            return
        lang = g.get('lang_code') or session.get('lang')
        if (
            lang in PREFIXED_LANGUAGES
            and app.url_map.is_endpoint_expecting(endpoint, 'lang_code')
        ):
            values['lang_code'] = lang

    # Нормалізація дублів: /uk/... -> 301 на канонічний непрефіксований URL.
    def redirect_uk(rest=''):
        target = '/' + rest
        if request.query_string:
            target += '?' + request.query_string.decode('utf-8', 'ignore')
        return redirect(target, 301)

    app.add_url_rule('/uk/', 'i18n_uk_root', redirect_uk)
    app.add_url_rule('/uk/<path:rest>', 'i18n_uk_path', redirect_uk)

    @app.context_processor
    def inject_i18n():
        from flask_babel import get_locale as babel_locale
        if not has_request_context():
            return {
                'current_lang': DEFAULT_LANGUAGE,
                'og_locale': OG_LOCALES[DEFAULT_LANGUAGE],
                'lang_switcher': [],
            }
        current = str(babel_locale() or DEFAULT_LANGUAGE)
        return {
            'current_lang': current,
            'og_locale': OG_LOCALES.get(current, OG_LOCALES[DEFAULT_LANGUAGE]),
            'hreflang_alternates': _hreflang_alternates(),
            'lang_switcher': [
                {
                    'code': lang,
                    'label': LANGUAGE_LABELS.get(lang, lang.upper()),
                    'active': lang == current,
                    **_switch_link(lang),
                }
                for lang in LANGUAGES
            ],
        }


def localized_urls(endpoint, view_args=None, external=False, x_default=False):
    """Список {lang, url} для ендпоінта на кожну мову (+ опційно x-default).
    Спільна логіка для hreflang (base.html), sitemap і будь-яких мовних
    альтернатив. Кидає, якщо ендпоінт не приймає lang_code -- виклик має
    перевірити is_endpoint_expecting заздалегідь."""
    values = dict(view_args or {})
    values.pop('lang_code', None)
    urls = [
        {'lang': lang, 'url': url_for(endpoint, _external=external, lang_code=lang, **values)}
        for lang in LANGUAGES
    ]
    if x_default:
        urls.append({
            'lang': 'x-default',
            'url': url_for(endpoint, _external=external, lang_code=DEFAULT_LANGUAGE, **values),
        })
    return urls


def _hreflang_alternates():
    """<link rel="alternate" hreflang> для поточної сторінки (base.html):
    усі мовні версії + x-default (укр). Порожньо для нелокалізованих
    ендпоінтів (admin, сервісні, юридичні). Без query string -- альтернативи
    відповідають canonical (request.base_url)."""
    endpoint = request.endpoint
    if not endpoint or not current_app.url_map.is_endpoint_expecting(endpoint, 'lang_code'):
        return []
    try:
        return localized_urls(endpoint, request.view_args, external=True, x_default=True)
    except Exception:
        return []


def _switch_link(lang):
    """URL перемикання на мову lang для ПОТОЧНОЇ сторінки.

    Локалізовані ендпоінти -> пряме альтернативне посилання (crawlable,
    знадобиться і для hreflang у Фазі 6). Інакше (admin, payments, 404) --
    фолбек через main.set_lang з поверненням на поточний шлях (nofollow).
    """
    endpoint = request.endpoint
    if endpoint and current_app.url_map.is_endpoint_expecting(endpoint, 'lang_code'):
        values = dict(request.view_args or {})
        values.pop('lang_code', None)
        values.update(request.args.to_dict())
        values['lang_code'] = lang
        try:
            return {'url': url_for(endpoint, **values), 'nofollow': False}
        except Exception:
            pass
    next_url = request.full_path if request.query_string else request.path
    return {
        'url': url_for('main.set_lang', lang=lang, next=next_url),
        'nofollow': True,
    }
