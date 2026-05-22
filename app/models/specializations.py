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
SPECIALIZATIONS = [
    # ----- Терапевтичні -----
    ('therapy', 'Терапія'),
    ('family_medicine', 'Загальна практика — сімейна медицина'),
    ('pediatrics', 'Педіатрія'),
    ('cardiology', 'Кардіологія'),
    ('endocrinology', 'Ендокринологія'),
    ('gastroenterology', 'Гастроентерологія'),
    ('nephrology', 'Нефрологія'),
    ('pulmonology', 'Пульмонологія'),
    ('rheumatology', 'Ревматологія'),
    ('hematology', 'Гематологія'),
    ('infectious_diseases', 'Інфекційні хвороби'),
    ('allergology', 'Алергологія'),
    ('immunology', 'Імунологія'),
    ('dermatology', 'Дерматовенерологія'),
    ('dermato_oncology', 'Дерматоонкологія'),
    ('trichology', 'Трихологія'),

    # ----- Хірургічні -----
    ('surgery', 'Хірургія'),
    ('orthopedics_traumatology', 'Травматологія та ортопедія'),
    ('neurosurgery', 'Нейрохірургія'),
    ('vascular_surgery', 'Судинна хірургія'),
    ('cardiac_surgery', 'Кардіохірургія'),
    ('plastic_surgery', 'Пластична хірургія'),
    ('urology', 'Урологія'),
    ('proctology', 'Проктологія'),
    ('maxillofacial_surgery', 'Щелепно-лицева хірургія'),
    ('oncosurgery', 'Онкохірургія'),
    ('pediatric_surgery', 'Дитяча хірургія'),

    # ----- Жіноче здоров'я -----
    ('obstetrics_gynecology', 'Акушерство та гінекологія'),
    ('gynecology_endocrinology', 'Гінекологія-ендокринологія'),
    ('reproductive_medicine', 'Репродуктивна медицина'),

    # ----- Стоматологія -----
    ('dentistry', 'Стоматологія'),
    ('therapeutic_dentistry', 'Терапевтична стоматологія'),
    ('surgical_dentistry', 'Хірургічна стоматологія'),
    ('pediatric_dentistry', 'Дитяча стоматологія'),
    ('orthodontics', 'Ортодонтія'),
    ('prosthodontics', 'Ортопедична стоматологія'),
    ('periodontics', 'Пародонтологія'),

    # ----- Естетична медицина / косметологія -----
    ('cosmetology', 'Косметологія'),
    ('aesthetic_medicine', 'Естетична медицина'),
    ('regenerative_medicine', 'Регенеративна медицина'),
    ('anti_aging', 'Антивіковa медицина'),

    # ----- Нервова система / реабілітація -----
    ('neurology', 'Неврологія'),
    ('psychiatry', 'Психіатрія'),
    ('narcology', 'Наркологія'),
    ('rehabilitation', 'Фізична та реабілітаційна медицина'),
    ('physical_therapy', 'Фізична терапія'),
    ('ergotherapy', 'Ерготерапія'),

    # ----- Діагностика -----
    ('ultrasound_diagnostics', 'Ультразвукова діагностика'),
    ('radiology', 'Променева діагностика'),
    ('endoscopy', 'Ендоскопія'),
    ('endoscopist', 'Лікар-ендоскопіст'),
    ('functional_diagnostics', 'Функціональна діагностика'),
    ('clinical_lab_diagnostics', 'Клінічна лабораторна діагностика'),
    ('clinical_biochemistry', 'Клінічна біохімія'),
    ('lab_immunology', 'Лабораторна імунологія'),
    ('lab_biochemistry_doctor', 'Лікар-лаборант з клінічної біохімії'),
    ('lab_assistant', 'Лікар-лаборант'),
    ('pathomorphology', 'Патоморфологія'),
    ('genetics', 'Генетика медична'),

    # ----- Інше -----
    ('anesthesiology', 'Анестезіологія'),
    ('intensive_care', 'Інтенсивна терапія'),
    ('ophthalmology', 'Офтальмологія'),
    ('otolaryngology', 'Оториноларингологія'),
    ('oncology', 'Онкологія'),
    ('hematology_oncology', 'Дитяча онкологія/гематологія'),
    ('dietetics', 'Дієтологія'),
    ('dietologist', 'Лікар-дієтолог'),
    ('sports_medicine', 'Спортивна медицина'),
    ('emergency_medicine', 'Медицина невідкладних станів'),
    ('occupational_medicine', 'Медицина праці'),
    ('public_health', 'Громадське здоров\'я'),
    ('forensic_medicine', 'Судово-медична експертиза'),
    ('pharmacology', 'Клінічна фармакологія'),
    ('pharmacy', 'Фармація'),
    ('nursing', 'Сестринська справа'),
    ('other', 'Інша спеціалізація'),
]


# Допоміжні лук-апи -----------------------------------------------------
SPECIALIZATION_LABEL_BY_CODE = dict(SPECIALIZATIONS)
SPECIALIZATION_CODES = set(SPECIALIZATION_LABEL_BY_CODE.keys())


def labels_for_codes(codes):
    """Список labels (українських назв) за переданими codes. Невалідні
    codes ігноруються."""
    if not codes:
        return []
    return [
        SPECIALIZATION_LABEL_BY_CODE[c]
        for c in codes
        if c in SPECIALIZATION_LABEL_BY_CODE
    ]
