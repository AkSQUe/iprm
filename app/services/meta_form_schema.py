"""Схеми інстант-форм Meta: підписи питань і варіантів відповіді.

Навіщо цей модуль існує. У `field_data` заявки Graph API кладе для питань
із варіантами не текст варіанта, а його внутрішній КЛЮЧ: нижній регістр,
пробіли замінені підкресленнями. Так само слугіфіковані й назви питань.
Вільний текст (ПІБ, пошта) приходить як є -- саме тому на картці ліда
частина рядків виглядала нормально, а частина ні.

Людські підписи Meta віддає окремо, у полі `questions` самої форми:
`label` для питання і `options[].value` для варіанта під `options[].key`.
Забираємо їх раз на форму (`sync_form`, `sync_page_forms`) і підставляємо
НА ПОКАЗІ (`answers_for`).

Чому на показі, а не при розборі заявки:

* схема цілком може приїхати ПІЗНІШЕ за лід (заявка з вебхука випереджає
  перший похід за формою). Вшита копія означала б, що вже наявні картки не
  полагодяться ніколи -- а це саме той випадок, з якого все й почалося;
* `field_data` за контрактом колонки лишається дослівним. Він страховка на
  випадок помилки в самій підстановці, і переписаний -- уже не страховка.

Форми без схеми (видалена в Meta, лід зі старої кампанії) не лишаються з
ключами: для них працює `humanize` -- підкреслення назад у пробіли. Це
здогадка, а не дані, і регістр вона відновити не може, тож застосовується
ЛИШЕ там, де справжнього підпису немає.
"""
import logging

from app.extensions import db
from app.models.meta_lead import MetaLeadForm
from app.models.mixins import utcnow

logger = logging.getLogger(__name__)

#: Роздільник, яким `flatten_field_data` склеює кілька обраних варіантів.
#: Розібрати назад можна однозначно: у ключі Meta пробіл після коми теж
#: став би підкресленням (`так,_іноді`), тож «кома з пробілом» усередині
#: одного ключа не трапляється.
_MULTI_SEP = ', '

#: Поля Meta, що вже розібрані в окремі колонки заявки. Хто показує або
#: віддає їх окремо (картка ліда, payload партнера), той відсіває їх зі
#: списку відповідей цим набором -- інакше ПІБ, пошта й телефон їдуть двічі.
#: Список один на всіх саме тому: дві копії розійшлися б на першій правці,
#: і одна з них почала б віддавати назовні зайві персональні дані.
STANDARD_FIELDS = frozenset({
    'email', 'phone_number', 'phone', 'full_name', 'first_name', 'last_name',
})


# --- розбір відповіді Graph API -------------------------------------------

def parse_questions(payload):
    """`questions` з Graph API -> `{ключ: {label, type, options}}`.

    Питання без `key` пропускаємо: без нього підпис нема до чого
    прикласти. Варіанти згортаємо в `{key: value}` -- саме `key` лежить у
    відповіді заявки.
    """
    questions = {}
    for item in (payload or {}).get('questions') or []:
        if not isinstance(item, dict):
            continue
        key = str(item.get('key') or '').strip()
        if not key:
            continue
        options = {}
        for option in item.get('options') or []:
            if not isinstance(option, dict):
                continue
            opt_key = str(option.get('key') or '').strip()
            opt_value = str(option.get('value') or '').strip()
            if opt_key and opt_value:
                options[opt_key] = opt_value
        questions[key] = {
            'label': str(item.get('label') or '').strip(),
            'type': str(item.get('type') or '').strip(),
            'options': options,
        }
    return questions


def save_form(payload, page_id=None):
    """Upsert схеми однієї форми. Мутує сесію БЕЗ commit.

    Повертає `MetaLeadForm` або None, якщо у відповіді немає `id`: рядок
    без ідентифікатора форми не прив'яжеться до жодного ліда.
    """
    payload = payload or {}
    form_id = str(payload.get('id') or '').strip()
    if not form_id:
        return None

    form = MetaLeadForm.query.filter_by(form_id=form_id).first()
    if form is None:
        form = MetaLeadForm(form_id=form_id)
        db.session.add(form)

    form.page_id = str(page_id or payload.get('page_id') or '').strip() or form.page_id
    form.name = (str(payload.get('name') or '').strip() or None)
    form.status = (str(payload.get('status') or '').strip() or None)
    form.locale = (str(payload.get('locale') or '').strip() or None)
    form.questions = parse_questions(payload)
    form.synced_at = utcnow()
    return form


# --- походи в Graph API ---------------------------------------------------

def save_forms(payloads, page_id=None):
    """Зберегти схеми зі списку форм і закомітити. Повертає їх кількість.

    Окремою функцією, бо звірка (`meta_lead_queue.reconcile`) уже має цей
    список на руках: `list_page_forms` просить `questions` тим самим
    запитом (див. `FORM_FIELDS`), тож підписи їй дістаються задарма --
    другий похід за ними був би чистою витратою квоти.

    Схеми зберігаються для ВСІХ форм, зокрема зупинених: заявки з них
    нікуди не діваються, і їхні картки теж мусять читатися.
    """
    saved = 0
    for payload in payloads or []:
        if isinstance(payload, dict) and save_form(payload, page_id) is not None:
            saved += 1
    if saved and not _commit(f'save_forms page_id={page_id}'):
        return 0
    return saved


def sync_page_forms(client, page_id):
    """Забрати й оновити схеми всіх форм Сторінки. Комітить сама.

    Повертає кількість збережених схем або None, коли Graph API відмовив:
    нуль ("форм немає") і "не змогли спитати" -- різні новини.
    """
    result = client.list_page_forms(page_id)
    if not result.ok:
        logger.warning('meta_form_schema: cannot list forms of page %s -- %s',
                       page_id, result.error)
        return None
    return save_forms(result.data, page_id)


def sync_form(client, form_id, page_id=None):
    """Забрати схему ОДНІЄЇ форми. Комітить сама; повертає bool успіху."""
    form_id = str(form_id or '').strip()
    if not form_id:
        return False

    result = client.get_form(form_id)
    if not result.ok:
        logger.warning('meta_form_schema: cannot fetch form %s -- %s',
                       form_id, result.error)
        return False

    if save_form(result.data, page_id) is None:
        return False
    return _commit(f'sync_form form_id={form_id}')


def ensure_form(client, form_id, page_id=None):
    """Забрати схему, лише якщо її ще немає.

    Опубліковану форму Meta редагувати не дає (її дублюють), тож перечитувати
    наявну схему на кожен лід -- палити квоту заради незмінних даних. Свіжість
    тримають звірка й кнопка в адмінці.
    """
    form_id = str(form_id or '').strip()
    if not form_id:
        return False
    if MetaLeadForm.query.filter_by(form_id=form_id).first() is not None:
        return False
    return sync_form(client, form_id, page_id)


def _commit(log_context):
    """Коміт без flash: сюди ходить і фоновий воркер, поза запитом.

    `admin._helpers.try_commit` тут не годиться саме тому -- він флешить, а
    flash поза контекстом запиту падає RuntimeError. Збій схеми не має
    валити розбір заявки: лід важливіший за підписи до нього.
    """
    try:
        db.session.commit()
        return True
    except Exception:
        db.session.rollback()
        logger.exception('meta_form_schema: commit failed -- %s', log_context)
        return False


# --- підстановка на показі ------------------------------------------------

def humanize(text):
    """Ключ Meta -> читний рядок, коли справжнього підпису немає.

    Робить рівно те, що можна зробити без даних: підкреслення назад у
    пробіли й велика перша літера. Регістр решти слів відновити
    неможливо -- `p-prp` так і лишиться `p-prp`, і це чесніше, ніж
    вигадати за людину `P-PRP`.
    """
    value = str(text or '').replace('_', ' ').strip()
    value = ' '.join(value.split())
    if not value:
        return ''
    return value[0].upper() + value[1:]


def _looks_like_key(value):
    """Чи схожий рядок на слугіфікований ключ Meta, а не на текст людини.

    Три ознаки разом: є підкреслення, немає жодного пробілу і немає
    великих літер. Саме такий вигляд має ключ варіанта -- і саме такого
    НЕ має вільна відповідь: у ній є або пробіли, або великі літери, або
    немає підкреслень (пошта, номер, одне слово як його ввели).

    Здогадка потрібна лише для форм без схеми. Помилитись тут означає
    підмінити те, що написала людина, тому умова навмисно вузька.
    """
    return '_' in value and ' ' not in value and value == value.lower()


def _pretty_value(options, value):
    """Відповідь у людському вигляді.

    Порядок спроб: точний варіант зі схеми -> кілька варіантів через кому
    -> здогадка `humanize` для форм без схеми -> рядок як є.

    Частковий збіг у multi-select не приймаємо: якщо хоч одна частина не
    знайшлась серед варіантів, це не кілька відповідей, а текст із комою,
    і різати його на шматки означало б показати не те, що написала людина.
    """
    if not value:
        return value
    if value in options:
        return options[value]

    parts = value.split(_MULTI_SEP)
    if len(parts) > 1 and all(part in options for part in parts):
        return _MULTI_SEP.join(options[part] for part in parts)

    # Схеми немає (форму видалили, лід зі старої кампанії) -- лишається
    # здогадка. Вільний текст під неї не підпадає й лишається дослівним.
    if all(_looks_like_key(part) for part in parts):
        return _MULTI_SEP.join(humanize(part) for part in parts)
    return value


def labels_for(form_id):
    """Схема форми як dict або порожній dict, коли її ще не забирали."""
    form_id = str(form_id or '').strip()
    if not form_id:
        return {}
    form = MetaLeadForm.query.filter_by(form_id=form_id).first()
    return (form.questions or {}) if form is not None else {}


def answers_for(field_data, form_id, skip=(), schema=None):
    """Відповіді заявки з людськими підписами: список пар (питання, відповідь).

    Список, а не dict: два питання форми цілком можуть мати однаковий
    підпис ("Ваш коментар" у двох блоках), і dict тихо загубив би одну з
    відповідей.

    Порядок -- як у відповіді Meta, тобто як у самій формі. `skip` --
    ключі, які показані окремо (пошта, телефон, ПІБ), звичайно
    `STANDARD_FIELDS`.

    `schema` -- уже прочитана схема форми. Потрібна тому, що виклик, який
    поруч бере з ТІЄЇ САМОЇ форми ще й прив'язаний захід (payload партнера),
    інакше діставав би той самий рядок двічі -- і множив це на всю історію
    під час бекфілу. None означає «прочитай сам».
    """
    data = field_data if isinstance(field_data, dict) else {}
    if not data:
        return []

    schema = labels_for(form_id) if schema is None else schema
    skip = frozenset(skip)

    answers = []
    for key, value in data.items():
        if key in skip:
            continue
        question = schema.get(key) or {}
        label = question.get('label') or humanize(key)
        text = str(value if value is not None else '')
        answers.append((label, _pretty_value(question.get('options') or {}, text)))
    return answers
