"""
Event Excel Configuration
Single source of truth for export/import column mapping.

Format: (field_key, excel_label, width, db_field, converter, default)
- field_key: programmatic key
- excel_label: column header in Excel (used for import mapping)
- width: column width in Excel
- db_field: Event model field or special key (e.g. 'trainer_name')
- converter: type converter for import
- default: default value for import
"""

from datetime import datetime
from decimal import Decimal, InvalidOperation


def convert_bool_ua(value):
    """Convert Ukrainian/English boolean values."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        val = value.strip().lower()
        if val in ('\u0442\u0430\u043a', 'tak', 'yes', 'true', '1'):
            return True
        if val in ('\u043d\u0456', 'ni', 'no', 'false', '0'):
            return False
    return False


def bool_to_ua(value):
    """Convert boolean to Ukrainian string for export."""
    return '\u0422\u0430\u043a' if value else '\u041d\u0456'


def convert_datetime_ua(value):
    """Parse datetime from Excel cell.

    Handles native datetime objects and 'DD.MM.YYYY HH:MM' strings.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        value = value.strip()
        if not value:
            return None
        for fmt in ('%d.%m.%Y %H:%M', '%Y-%m-%d %H:%M', '%d.%m.%Y'):
            try:
                return datetime.strptime(value, fmt)
            except ValueError:
                continue
        raise ValueError(f"\u043d\u0435 \u0432\u0434\u0430\u043b\u043e\u0441\u044f \u0440\u043e\u0437\u043f\u0456\u0437\u043d\u0430\u0442\u0438 \u0434\u0430\u0442\u0443 '{value}'")
    return None


def convert_decimal(value):
    """Safe Decimal conversion for price fields."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError(f"\u043d\u0435\u043a\u043e\u0440\u0435\u043a\u0442\u043d\u0430 \u0446\u0456\u043d\u0430: '{value}'")


def convert_int(value):
    """Safe int conversion, returns None for empty."""
    if value is None:
        return None
    if isinstance(value, str):
        value = value.strip()
        if not value:
            return None
    return int(float(value))


def semicolon_to_list(value):
    """Split semicolon-separated string into list."""
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [item.strip() for item in str(value).split(';') if item.strip()]


def list_to_semicolon(items):
    """Join list into semicolon-separated string for export."""
    if not items:
        return ''
    return '; '.join(str(item) for item in items)


COLUMNS_CONFIG = [
    ('id', 'ID', 8, 'id', convert_int, None),
    ('title', '\u041d\u0430\u0437\u0432\u0430', 40, 'title', str, None),
    ('slug', 'Slug', 30, 'slug', str, None),
    ('subtitle', '\u041f\u0456\u0434\u0437\u0430\u0433\u043e\u043b\u043e\u0432\u043e\u043a', 40, 'subtitle', str, None),
    ('short_description', '\u041a\u043e\u0440\u043e\u0442\u043a\u0438\u0439 \u043e\u043f\u0438\u0441', 40, 'short_description', str, None),
    ('description', '\u041e\u043f\u0438\u0441', 50, 'description', str, None),
    ('event_type', '\u0422\u0438\u043f \u0437\u0430\u0445\u043e\u0434\u0443', 18, 'event_type', str, None),
    ('event_format', '\u0424\u043e\u0440\u043c\u0430\u0442', 14, 'event_format', str, None),
    ('status', '\u0421\u0442\u0430\u0442\u0443\u0441', 14, 'status', str, 'draft'),
    ('start_date', '\u0414\u0430\u0442\u0430 \u043f\u043e\u0447\u0430\u0442\u043a\u0443', 20, 'start_date', convert_datetime_ua, None),
    ('end_date', '\u0414\u0430\u0442\u0430 \u0437\u0430\u043a\u0456\u043d\u0447\u0435\u043d\u043d\u044f', 20, 'end_date', convert_datetime_ua, None),
    ('max_participants', '\u041c\u0430\u043a\u0441. \u0443\u0447\u0430\u0441\u043d\u0438\u043a\u0456\u0432', 16, 'max_participants', convert_int, None),
    ('price', '\u0426\u0456\u043d\u0430', 12, 'price', convert_decimal, Decimal('0')),
    ('location', '\u041c\u0456\u0441\u0446\u0435', 30, 'location', str, None),
    ('online_link', '\u041f\u043e\u0441\u0438\u043b\u0430\u043d\u043d\u044f', 30, 'online_link', str, None),
    ('hero_image', 'Hero \u0437\u043e\u0431\u0440\u0430\u0436\u0435\u043d\u043d\u044f', 30, 'hero_image', str, None),
    ('card_image', 'Card \u0437\u043e\u0431\u0440\u0430\u0436\u0435\u043d\u043d\u044f', 30, 'card_image', str, None),
    ('cpd_points', 'CPD \u0431\u0430\u043b\u0438', 10, 'cpd_points', convert_int, None),
    ('target_audience', '\u0426\u0456\u043b\u044c\u043e\u0432\u0430 \u0430\u0443\u0434\u0438\u0442\u043e\u0440\u0456\u044f', 30, 'target_audience', semicolon_to_list, []),
    ('tags', '\u0422\u0435\u0433\u0438', 30, 'tags', semicolon_to_list, []),
    ('trainer_name', '\u0422\u0440\u0435\u043d\u0435\u0440', 25, 'trainer_name', str, None),
    ('is_featured', '\u0420\u0435\u043a\u043e\u043c\u0435\u043d\u0434\u043e\u0432\u0430\u043d\u0438\u0439', 14, 'is_featured', convert_bool_ua, False),
    ('is_active', '\u0410\u043a\u0442\u0438\u0432\u043d\u0438\u0439', 12, 'is_active', convert_bool_ua, True),
]


def get_export_columns():
    """Return list of (field_key, label, width) for export."""
    return [(fk, label, w) for fk, label, w, _, _, _ in COLUMNS_CONFIG]


def get_import_mapping():
    """Return {excel_label: (db_field, converter, default)} for import."""
    return {
        label: (db_field, converter, default)
        for _, label, _, db_field, converter, default in COLUMNS_CONFIG
    }
