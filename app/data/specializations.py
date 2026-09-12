"""Довідник медичних спеціалізацій для multi-select на реєстраційній формі.

Загальний список з номенклатури МОЗ України, доповнений найпоширенішими
позиціями. Зберігаємо як константу (не таблицю), бо:
  - значення стабільні, рідко змінюються
  - не потрібен окремий CRUD в адмінці
  - простіше міграції / зміна списку = звичайний код-чейндж

У `User.specializations` (JSON-array) лежать `code`-значення. Label-и беремо
з цього модуля для відображення.
"""

# (code, label) — code зберігається в БД, label показується користувачу.
# Список згруповано умовно за галузями для зручності перегляду в коді.
#
# i18n: label-и звідси серіалізуються (XLSX-експорт/імпорт у services/xlsx_io,
# снапшоти reg.specialty у БД через labels_for_codes), тому значення в списку
# ЛИШАЮТЬСЯ звичайними str. `_` нижче — no-op маркер для pybabel-екстракції;
# переклад для відображення робиться на льоту (localized_specializations).
def _(text):
    """No-op маркер: pybabel витягує рядок у каталог, значення не змінюється."""
    return text


SPECIALIZATIONS = [
    # ----- Терапевтичні -----
    ('therapy', _('Терапія')),
    ('family_medicine', _('Загальна практика — сімейна медицина')),
    ('pediatrics', _('Педіатрія')),
    ('cardiology', _('Кардіологія')),
    ('endocrinology', _('Ендокринологія')),
    ('gastroenterology', _('Гастроентерологія')),
    ('nephrology', _('Нефрологія')),
    ('pulmonology', _('Пульмонологія')),
    ('rheumatology', _('Ревматологія')),
    ('hematology', _('Гематологія')),
    ('infectious_diseases', _('Інфекційні хвороби')),
    ('allergology', _('Алергологія')),
    ('immunology', _('Імунологія')),
    ('dermatology', _('Дерматовенерологія')),
    ('dermato_oncology', _('Дерматоонкологія')),
    ('trichology', _('Трихологія')),

    # ----- Хірургічні -----
    ('surgery', _('Хірургія')),
    ('orthopedics_traumatology', _('Травматологія та ортопедія')),
    ('neurosurgery', _('Нейрохірургія')),
    ('vascular_surgery', _('Судинна хірургія')),
    ('cardiac_surgery', _('Кардіохірургія')),
    ('plastic_surgery', _('Пластична хірургія')),
    ('urology', _('Урологія')),
    ('proctology', _('Проктологія')),
    ('maxillofacial_surgery', _('Щелепно-лицева хірургія')),
    ('oncosurgery', _('Онкохірургія')),
    ('pediatric_surgery', _('Дитяча хірургія')),

    # ----- Жіноче здоров'я -----
    ('obstetrics_gynecology', _('Акушерство та гінекологія')),
    ('gynecology_endocrinology', _('Гінекологія-ендокринологія')),
    ('reproductive_medicine', _('Репродуктивна медицина')),

    # ----- Стоматологія -----
    ('dentistry', _('Стоматологія')),
    ('therapeutic_dentistry', _('Терапевтична стоматологія')),
    ('surgical_dentistry', _('Хірургічна стоматологія')),
    ('pediatric_dentistry', _('Дитяча стоматологія')),
    ('orthodontics', _('Ортодонтія')),
    ('prosthodontics', _('Ортопедична стоматологія')),
    ('periodontics', _('Пародонтологія')),

    # ----- Естетична медицина / косметологія -----
    ('cosmetology', _('Косметологія')),
    ('aesthetic_medicine', _('Естетична медицина')),
    ('regenerative_medicine', _('Регенеративна медицина')),
    ('anti_aging', _('Антивіковa медицина')),

    # ----- Нервова система / реабілітація -----
    ('neurology', _('Неврологія')),
    ('psychiatry', _('Психіатрія')),
    ('narcology', _('Наркологія')),
    ('rehabilitation', _('Фізична та реабілітаційна медицина')),
    ('physical_therapy', _('Фізична терапія')),
    ('ergotherapy', _('Ерготерапія')),

    # ----- Діагностика -----
    ('ultrasound_diagnostics', _('Ультразвукова діагностика')),
    ('radiology', _('Променева діагностика')),
    ('endoscopy', _('Ендоскопія')),
    ('endoscopist', _('Лікар-ендоскопіст')),
    ('functional_diagnostics', _('Функціональна діагностика')),
    ('clinical_lab_diagnostics', _('Клінічна лабораторна діагностика')),
    ('clinical_biochemistry', _('Клінічна біохімія')),
    ('lab_immunology', _('Лабораторна імунологія')),
    ('lab_biochemistry_doctor', _('Лікар-лаборант з клінічної біохімії')),
    ('lab_assistant', _('Лікар-лаборант')),
    ('pathomorphology', _('Патоморфологія')),
    ('genetics', _('Генетика медична')),

    # ----- Інше -----
    ('anesthesiology', _('Анестезіологія')),
    ('intensive_care', _('Інтенсивна терапія')),
    ('ophthalmology', _('Офтальмологія')),
    ('otolaryngology', _('Оториноларингологія')),
    ('oncology', _('Онкологія')),
    ('hematology_oncology', _('Дитяча онкологія/гематологія')),
    ('dietetics', _('Дієтологія')),
    ('dietologist', _('Лікар-дієтолог')),
    ('sports_medicine', _('Спортивна медицина')),
    ('emergency_medicine', _('Медицина невідкладних станів')),
    ('occupational_medicine', _('Медицина праці')),
    ('public_health', _('Громадське здоров\'я')),
    ('forensic_medicine', _('Судово-медична експертиза')),
    ('pharmacology', _('Клінічна фармакологія')),
    ('pharmacy', _('Фармація')),
    ('nursing', _('Сестринська справа')),
    ('other', _('Інша спеціалізація')),
]


# Допоміжні лук-апи -----------------------------------------------------
SPECIALIZATION_LABEL_BY_CODE = dict(SPECIALIZATIONS)
SPECIALIZATION_CODES = set(SPECIALIZATION_LABEL_BY_CODE.keys())


def labels_for_codes(codes):
    """Список labels (українських назв) за переданими codes. Невалідні
    codes ігноруються.

    УВАГА: повертає КАНОНІЧНІ (неперекладені) label-и -- саме вони пишуться
    у снапшоти БД (reg.specialty) та XLSX. Для відображення користувачу
    використовуйте localized_label / localized_specializations."""
    if not codes:
        return []
    return [
        SPECIALIZATION_LABEL_BY_CODE[c]
        for c in codes
        if c in SPECIALIZATION_LABEL_BY_CODE
    ]


def localized_label(code):
    """Перекладений label за code (на льоту, для відображення). Невідомий
    code повертається як є."""
    from flask_babel import gettext
    label = SPECIALIZATION_LABEL_BY_CODE.get(code)
    return gettext(label) if label else code


def localized_specializations():
    """(code, перекладений label) для WTForms choices. Викликається як
    callable choices при інстанціюванні форми (у request-контексті), тож
    жодних LazyString у модульних константах не з'являється."""
    from flask_babel import gettext
    return [(code, gettext(label)) for code, label in SPECIALIZATIONS]
