"""Наповнення банку питань: підсумкове тестування «Терапевтична сила плазми».

Прив'язка -- до ПРОВЕДЕННЯ 43 (15.08.2026, Харків), а не до курсу 8. Курс має
вісім проведень, серед них два минулих із реєстраціями; прив'язка до курсу
відкрила б тестування і їхнім учасникам, чого не просили. Розширити на весь
курс -- замінити INSTANCE_ID на COURSE_ID у INSERT нижче.

Одноразовий сід контенту, як scripts/seed_trainers_from_anketa.py. Лишається в
репозиторії, бо це джерело правди для того, що зараз лежить у проді: 10 питань
українською з перекладами ru/en.

ЧОМУ БЕЗ APP-КОНТЕКСТУ. `create_app()` у кінці підіймає APScheduler, тож
локальний запуск з контекстом міг би розіслати заплановані листи живим людям.
Тут прямий pg8000 і лише INSERT-и.

ІДЕМПОТЕНТНІСТЬ. Якщо в тесту курсу вже є питання -- скрипт нічого не робить і
повідомляє про це. Повторний запуск не подвоїть банк.

КЛЮЧІ ПЕРЕКЛАДУ. JSON-поле `answers` перекладається плоскою мапою
{ключ: текст}, де ключ -- sha1 українського джерела, перші 12 символів
(app.i18n.source_key). Саме хеш, а не шлях `0.text`: шляхи лишились як legacy і
з'їжджають, якщо переставити варіанти. Варіанти, що збігаються з українськими
(PPP, P-PRP, PRF), у переклад не пишемо -- фолбек і так віддасть оригінал.

Запуск:  venv/Scripts/python.exe scripts/seed_quiz_plasma_basics.py
"""
import hashlib
import json
import os
import re

import pg8000.dbapi

INSTANCE_ID = 43

# Налаштування тесту: «не менше 80% правильних відповідей (8 із 10)».
QUESTIONS_PER_ATTEMPT = 10
PASSING_SCORE = 8
MAX_ATTEMPTS = 3
SHUFFLE_ANSWERS = True

# (питання, [(варіант, чи правильний), ...]) -- порядок як у джерелі замовника.
QUESTIONS = [
    {
        'uk': ('Що є ключовою характеристикою PRP?', [
            ("Підвищена концентрація тромбоцитів порівняно з вихідною кров'ю", True),
            ('Повна відсутність тромбоцитів', False),
            ('Підвищена концентрація еритроцитів', False),
            ('Наявність лише фібрину', False),
        ]),
        'ru': ('Что является ключевой характеристикой PRP?', [
            'Повышенная концентрация тромбоцитов по сравнению с исходной кровью',
            'Полное отсутствие тромбоцитов',
            'Повышенная концентрация эритроцитов',
            'Наличие только фибрина',
        ]),
        'en': ('What is the key characteristic of PRP?', [
            'An increased platelet concentration compared with baseline whole blood',
            'Complete absence of platelets',
            'An increased red blood cell concentration',
            'Presence of fibrin only',
        ]),
    },
    {
        'uk': ('Яка основна відмінність L-PRP від P-PRP?', [
            ('Відсутність тромбоцитів', False),
            ('Вища концентрація лейкоцитів у L-PRP', True),
            ('Відсутність плазми', False),
            ("Обов'язкова термічна обробка", False),
        ]),
        'ru': ('В чем заключается основное отличие L-PRP от P-PRP?', [
            'Отсутствие тромбоцитов',
            'Более высокая концентрация лейкоцитов в L-PRP',
            'Отсутствие плазмы',
            'Обязательная термическая обработка',
        ]),
        'en': ('What is the main difference between L-PRP and P-PRP?', [
            'Absence of platelets',
            'A higher leukocyte concentration in L-PRP',
            'Absence of plasma',
            'Mandatory heat treatment',
        ]),
    },
    {
        'uk': ('Що означає абревіатура PPP?', [
            ('Platelet Protein Plasma', False),
            ('Platelet-Poor Plasma', True),
            ('Platelet-Protective Plasma', False),
            ('Plasma Preparation Protocol', False),
        ]),
        'ru': ('Что означает аббревиатура PPP?', [
            'Platelet Protein Plasma',
            'Platelet-Poor Plasma',
            'Platelet-Protective Plasma',
            'Plasma Preparation Protocol',
        ]),
        'en': ('What does the abbreviation PPP stand for?', [
            'Platelet Protein Plasma',
            'Platelet-Poor Plasma',
            'Platelet-Protective Plasma',
            'Plasma Preparation Protocol',
        ]),
    },
    {
        'uk': ('Що безпосередньо впливає на характеристики отриманого PRP?', [
            ('Лише вік пацієнта', False),
            ("Лише об'єм пробірки", False),
            ('Параметри центрифугування та дотримання протоколу', True),
            ('Колір пробірки', False),
        ]),
        'ru': ('Что непосредственно влияет на характеристики полученного PRP?', [
            'Только возраст пациента',
            'Только объем пробирки',
            'Параметры центрифугирования и соблюдение протокола',
            'Цвет пробирки',
        ]),
        'en': ('What directly affects the characteristics of the PRP obtained?', [
            "Only the patient's age",
            'Only the volume of the collection tube',
            'Centrifugation parameters and adherence to the protocol',
            'The color of the collection tube',
        ]),
    },
    {
        'uk': ('З якою метою при отриманні певних аутологічних продуктів крові '
               'використовують антикоагулянт?', [
            ('Для збільшення кількості еритроцитів', False),
            ('Для запобігання передчасному згортанню крові', True),
            ('Для руйнування тромбоцитів', False),
            ('Для підвищення температури плазми', False),
        ]),
        'ru': ('С какой целью при получении определенных аутологичных продуктов '
               'крови используют антикоагулянт?', [
            'Для увеличения количества эритроцитов',
            'Для предотвращения преждевременного свертывания крови',
            'Для разрушения тромбоцитов',
            'Для повышения температуры плазмы',
        ]),
        'en': ('Why is an anticoagulant used when preparing certain autologous '
               'blood products?', [
            'To increase the number of red blood cells',
            'To prevent premature blood clotting',
            'To destroy platelets',
            'To increase the temperature of the plasma',
        ]),
    },
    {
        'uk': ('До якого етапу належать правильний забір та підготовка крові до '
               'центрифугування?', [
            ('Преаналітичного', True),
            ('Постаналітичного', False),
            ('Реабілітаційного', False),
            ("Ін'єкційного", False),
        ]),
        'ru': ('К какому этапу относятся правильный забор и подготовка крови к '
               'центрифугированию?', [
            'К преаналитическому',
            'К постаналитическому',
            'К реабилитационному',
            'К инъекционному',
        ]),
        'en': ('Which stage includes proper blood collection and preparation '
               'prior to centrifugation?', [
            'The pre-analytical stage',
            'The post-analytical stage',
            'The rehabilitation stage',
            'The injection stage',
        ]),
    },
    {
        'uk': ('Що необхідно враховувати при виборі режиму центрифугування?', [
            ('Тільки тривалість процедури', False),
            ('Тільки кількість пробірок', False),
            ('Необхідний тип кінцевого продукту та параметри центрифуги', True),
            ('Лише вік пацієнта', False),
        ]),
        'ru': ('Что необходимо учитывать при выборе режима центрифугирования?', [
            'Только продолжительность процедуры',
            'Только количество пробирок',
            'Необходимый тип конечного продукта и параметры центрифуги',
            'Только возраст пациента',
        ]),
        'en': ('What should be considered when selecting centrifugation '
               'parameters?', [
            'Only the duration of the procedure',
            'Only the number of collection tubes',
            'The required type of final product and the centrifuge parameters',
            "Only the patient's age",
        ]),
    },
    {
        'uk': ('Для якого з наведених аутологічних продуктів характерне '
               'формування фібринової матриці?', [
            ('PPP', False),
            ('P-PRP', False),
            ('PRF', True),
            ('Цільна кров', False),
        ]),
        'ru': ('Для какого из перечисленных аутологичных продуктов характерно '
               'формирование фибриновой матрицы?', [
            'PPP', 'P-PRP', 'PRF', 'Цельная кровь',
        ]),
        'en': ('Which of the following autologous blood products is '
               'characterized by the formation of a fibrin matrix?', [
            'PPP', 'P-PRP', 'PRF', 'Whole blood',
        ]),
    },
    {
        'uk': ('Чому важливо дотримуватися стандартизованого протоколу '
               'отримання аутологічної плазми?', [
            ('Виключно для скорочення часу процедури', False),
            ('Для забезпечення відтворюваних характеристик отриманого продукту', True),
            ('Для усунення індивідуальних особливостей пацієнта', False),
            ('Щоб не враховувати параметри центрифуги', False),
        ]),
        'ru': ('Почему важно соблюдать стандартизированный протокол получения '
               'аутологичной плазмы?', [
            'Исключительно для сокращения времени процедуры',
            'Для обеспечения воспроизводимых характеристик полученного продукта',
            'Для устранения индивидуальных особенностей пациента',
            'Чтобы не учитывать параметры центрифуги',
        ]),
        'en': ('Why is it important to follow a standardized protocol for '
               'preparing autologous plasma?', [
            'Solely to reduce the duration of the procedure',
            'To ensure reproducible characteristics of the final product',
            'To eliminate individual patient variability',
            'To avoid considering centrifuge parameters',
        ]),
    },
    {
        'uk': ('Що слід враховувати при виборі типу аутологічного продукту '
               'крові?', [
            ('Для всіх клінічних ситуацій використовується однакова форма', False),
            ('Виключно вартість процедури', False),
            ('Завжди обирається продукт із максимальною кількістю лейкоцитів', False),
            ('Клінічну задачу, характеристики продукту та протокол його застосування', True),
        ]),
        'ru': ('Что следует учитывать при выборе типа аутологичного продукта '
               'крови?', [
            'Для всех клинических ситуаций используется одна и та же форма',
            'Исключительно стоимость процедуры',
            'Всегда выбирается продукт с максимальным количеством лейкоцитов',
            'Клиническую задачу, характеристики продукта и протокол его применения',
        ]),
        'en': ('What should be considered when selecting the type of autologous '
               'blood product?', [
            'The same product is used for all clinical situations',
            'Only the cost of the procedure',
            'The product with the highest leukocyte count should always be selected',
            'The clinical objective, product characteristics, and protocol for its use',
        ]),
    },
]


def source_key(text):
    """Копія app.i18n.source_key -- щоб не тягнути застосунок (і планувальник)."""
    return hashlib.sha1(text.strip().encode('utf-8')).hexdigest()[:12]


def build_rows():
    """(text, answers, translations) на кожне питання."""
    rows = []
    for item in QUESTIONS:
        uk_text, uk_answers = item['uk']
        answers = [{'text': text, 'is_correct': correct}
                   for text, correct in uk_answers]

        translations = {}
        for lang in ('ru', 'en'):
            lang_text, lang_answers = item[lang]
            if len(lang_answers) != len(uk_answers):
                raise ValueError(
                    f'{lang}: {len(lang_answers)} варіантів проти '
                    f'{len(uk_answers)} українських -- {uk_text[:40]}'
                )
            overrides = {}
            for (uk_answer, _correct), translated in zip(uk_answers, lang_answers):
                # Однакові тексти (PPP, PRF) у переклад не пишемо: фолбек
                # віддасть українське значення, тобто те саме.
                if translated.strip() != uk_answer.strip():
                    overrides[source_key(uk_answer)] = translated
            bucket = {'text': lang_text}
            if overrides:
                bucket['answers'] = overrides
            translations[lang] = bucket

        rows.append((uk_text, answers, translations))
    return rows


def connect():
    env_path = os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), '.env')
    with open(env_path, encoding='utf-8') as fh:
        env = fh.read()
    m = re.search(
        r'DATABASE_URL=postgresql\+pg8000://([^:]+):([^@]+)@([^:]+):(\d+)/(\S+)',
        env)
    if not m:
        raise SystemExit('DATABASE_URL не знайдено у .env')
    return pg8000.dbapi.connect(
        user=m.group(1), password=m.group(2), host=m.group(3),
        port=int(m.group(4)), database=m.group(5).strip(), ssl_context=True,
    )


def main():
    rows = build_rows()
    if len(rows) < QUESTIONS_PER_ATTEMPT:
        raise SystemExit(
            f'у банку {len(rows)} питань, а на спробу треба {QUESTIONS_PER_ATTEMPT}')

    con = connect()
    cur = con.cursor()
    try:
        cur.execute('SELECT id FROM course_quizzes WHERE instance_id = %s',
                    (INSTANCE_ID,))
        found = cur.fetchone()
        if found:
            quiz_id = found[0]
            cur.execute('SELECT count(*) FROM quiz_questions WHERE quiz_id = %s',
                        (quiz_id,))
            existing = cur.fetchone()[0]
            if existing:
                print(f'Тест {quiz_id} уже має {existing} питань -- нічого не роблю.')
                return
        else:
            cur.execute(
                'INSERT INTO course_quizzes (instance_id, questions_per_attempt, '
                'passing_score, max_attempts, shuffle_answers, is_active, '
                'created_at, updated_at) '
                'VALUES (%s, %s, %s, %s, %s, %s, now(), now()) RETURNING id',
                (INSTANCE_ID, QUESTIONS_PER_ATTEMPT, PASSING_SCORE, MAX_ATTEMPTS,
                 SHUFFLE_ANSWERS, True),
            )
            quiz_id = cur.fetchone()[0]
            print(f'Створено тест {quiz_id} для проведення {INSTANCE_ID}.')

        for order, (text, answers, translations) in enumerate(rows):
            cur.execute(
                'INSERT INTO quiz_questions (quiz_id, text, answers, sort_order, '
                'is_active, translations, created_at, updated_at) '
                'VALUES (%s, %s, CAST(%s AS json), %s, %s, CAST(%s AS json), '
                'now(), now())',
                (quiz_id, text, json.dumps(answers, ensure_ascii=False), order,
                 True, json.dumps(translations, ensure_ascii=False)),
            )
        con.commit()
        print(f'Додано питань: {len(rows)}. Поріг {PASSING_SCORE} з '
              f'{QUESTIONS_PER_ATTEMPT}, спроб {MAX_ATTEMPTS}.')
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


if __name__ == '__main__':
    main()
