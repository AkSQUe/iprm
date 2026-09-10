"""XLSX export/import для адмінки: курси (з program_blocks + faq) і
проведення курсів (CourseInstance).

Загальний контракт:
  - Експорт повертає `io.BytesIO` з готовим xlsx, який віддається через
    `send_file` в роуті.
  - Імпорт працює у дві стадії:
      1. `parse_*_xlsx(file_path) -> ImportPlan` -- read + validate, БЕЗ
         запису в БД. Якщо є помилки, plan.errors заповнений; apply
         відмовляється виконувати.
      2. `apply_*_plan(plan) -> ApplyResult` -- atomic commit. Усе або
         нічого.
  - Тимчасовий xlsx-файл під час preview зберігається у
    `instance/xlsx_imports/{token}.xlsx`, де token = uuid4. Apply
    видаляє файл після успіху.

Дизайн-рішення (узгоджено з admin-користувачем):
  - Рядки, що є в БД, але відсутні у xlsx, -> залишаємо без змін.
  - program_blocks та faq для course_slug, який присутній у відповідній
    sheet, ПОВНІСТЮ замінюються (REPLACE). Якщо course_slug не зустрі-
    чається у sheet -> блоки/FAQ цього курсу не чіпаємо.
  - Тренери у xlsx -- колонка trainer_slugs: список ПІБ (або slug) через
    '; ' на експорті (кома трапляється всередині самого ПІБ, напр.
    «Іванов І. І., PhD», тож нею не можна розділяти), з прийомом і ';',
    і ',' на імпорті (людина, що редагує вручну, радше поставить кому).
    Порядок у списку -- це роль: перший тренер є головним лектором.
    Пишеться через `trainer_links.set_trainers`, а не прямим FK-полем.
"""
#
# Цей пакет замінив однойменний модуль на 2705 рядків, що обслуговував
# чотири різні домени. Імпортний шлях НЕ змінився: `from app.services
# import xlsx_io` і `xlsx_io.<будь-що>` працюють як раніше -- перелік
# нижче навмисно повний, включно з приватними іменами, якими
# користуються тести.
#
# Нове доменне ім'я додавай у свій модуль і сюди ж, поруч із рештою.
#
from ._common import (  # noqa: F401
    BOOL_FALSE_FILL,
    BOOL_TRUE_FILL,
    COURSE_WIDTHS,
    ERROR_COLUMN_LABEL,
    EVENT_FORMAT_FILLS,
    FAQ_WIDTHS,
    FMT_CURRENCY_UAH,
    FMT_DATE,
    FMT_DATETIME,
    FMT_INT,
    FMT_POINTS,
    FORMAT_KEY_BY_LABEL,
    FORMAT_LABEL,
    HEADER_FILL,
    HEADER_FONT,
    INSTANCE_WIDTHS,
    KYIV,
    MAX_CELL_LENGTH,
    NUMBER_FORMATS,
    PROGRAM_WIDTHS,
    SHEET_ALIASES,
    STATUS_FILLS,
    STATUS_KEY_BY_LABEL,
    STATUS_LABEL,
    TRAINER_WIDTHS,
    VALID_FORMATS,
    VALID_STATUSES,
    WRAP,
    ZEBRA_FILL,
    _APPLY_FAILED_MESSAGE,
    _CONTROL_CHARS_RE,
    _DROPDOWN_BUFFER_ROWS,
    _ERROR_FILL,
    _INT4_MAX,
    _NUMERIC_10_2_MAX,
    _NUMERIC_5_2_MAX,
    _TRAINERS_SHEET_NAME,
    _VALUE_LIMITS,
    _add_inline_dropdown,
    _add_trainers_sheet,
    _apply_number_formats,
    _apply_table_style,
    _apply_zebra,
    _bool,
    _check_min_values,
    _decimal,
    _dt,
    _fill,
    _find_sheet,
    _from_lines,
    _import_dir,
    _int,
    _points_cell,
    _read_sheet,
    _resolve_media_id,
    _resolve_trainer_ids,
    _safe_text,
    _set_column_widths,
    _split_trainer_names,
    _str,
    _style_header,
    _to_kyiv_naive,
    _to_lines,
    annotate_errors_xlsx,
    build_trainer_lookup,
    cleanup_stale_xlsx_uploads,
    cleanup_upload,
    event_type_dropdown_options,
    get_uploaded_path,
    logger,
    normalize_event_type,
    record_row_error,
    save_uploaded_xlsx,
    write_cell,
)
from .courses import (  # noqa: F401
    COURSE_COLS,
    COURSE_LABELS,
    CourseChange,
    CoursesImportPlan,
    FAQ_COLS,
    FAQ_LABELS,
    OPTIONAL_COURSE_COLS,
    PROGRAM_COLS,
    PROGRAM_LABELS,
    _diff_course,
    apply_courses_plan,
    export_courses_xlsx,
    parse_courses_xlsx,
)
from .instances import (  # noqa: F401
    INSTANCE_COLS,
    INSTANCE_LABELS,
    InstanceChange,
    InstancesImportPlan,
    _diff_instance,
    apply_instances_plan,
    export_instances_xlsx,
    parse_instances_xlsx,
)
from .participants import (  # noqa: F401
    PARTICIPANT_COLS,
    PARTICIPANT_EXPORT_COLS,
    PARTICIPANT_LABELS,
    PARTICIPANT_TYPE_KEY_BY_LABEL,
    PARTICIPANT_TYPE_LABEL,
    PARTICIPANT_WIDTHS,
    PAYMENT_STATUS_FILLS,
    PAYMENT_STATUS_KEY_BY_LABEL,
    PAYMENT_STATUS_LABEL,
    ParticipantChange,
    ParticipantsImportPlan,
    REG_STATUS_FILLS,
    REG_STATUS_KEY_BY_LABEL,
    REG_STATUS_LABEL,
    SPEC_CODE_BY_LABEL,
    SPEC_LABEL_BY_CODE,
    VALID_PARTICIPANT_TYPES,
    VALID_PAYMENT_STATUSES,
    VALID_REG_STATUSES,
    _EVENTS_SHEET_NAME,
    _PARTICIPANT_DIFF_LABELS,
    _PARTICIPATION_FORMAT_KEY_BY_TEXT,
    _SPEC_SHEET_NAME,
    _add_events_sheet,
    _add_ref_dropdown,
    _add_specializations_sheet,
    _date,
    _diff_participant,
    _parse_participation_format,
    _parse_spec_cell,
    _participant_event_label,
    _resolve_event_to_id,
    apply_participants_plan,
    export_participants_xlsx,
    parse_participants_xlsx,
)
from .materials import (  # noqa: F401
    _MATERIALS_COLS,
    _MATERIALS_LABELS,
    _MATERIALS_THUMB_BUDGET_SECONDS,
    _MATERIALS_THUMB_MAX_BYTES,
    _MATERIALS_THUMB_PX,
    _MATERIALS_WIDTHS,
    _RESV_COLS,
    _RESV_LABELS,
    _RESV_WIDTHS,
    _download_thumb,
    export_material_reservations_xlsx,
    export_materials_template_xlsx,
    parse_materials_xlsx,
)
