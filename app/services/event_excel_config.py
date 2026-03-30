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
        if val in ('tak', 'yes', 'true', '1'):
            return True
        if val in ('ni', 'no', 'false', '0'):
            return False
    return False


def bool_to_ua(value):
    """Convert boolean to Ukrainian string for export."""
    return 'Tak' if value else 'Ni'


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
        raise ValueError(f"Cannot parse date: '{value}'")
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
        raise ValueError(f"Invalid price value: '{value}'")


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
    ('title', 'Nazva', 40, 'title', str, None),
    ('slug', 'Slug', 30, 'slug', str, None),
    ('subtitle', 'Pidzaholovok', 40, 'subtitle', str, None),
    ('short_description', 'Korotkyi opys', 40, 'short_description', str, None),
    ('description', 'Opys', 50, 'description', str, None),
    ('event_type', 'Typ zakhodu', 18, 'event_type', str, None),
    ('event_format', 'Format', 14, 'event_format', str, None),
    ('status', 'Status', 14, 'status', str, 'draft'),
    ('start_date', 'Data pochatku', 20, 'start_date', convert_datetime_ua, None),
    ('end_date', 'Data zakinchennia', 20, 'end_date', convert_datetime_ua, None),
    ('max_participants', 'Maks. uchasnykiv', 16, 'max_participants', convert_int, None),
    ('price', 'Tsina', 12, 'price', convert_decimal, Decimal('0')),
    ('location', 'Mistse', 30, 'location', str, None),
    ('online_link', 'Posylannia', 30, 'online_link', str, None),
    ('hero_image', 'Hero zobrazhennia', 30, 'hero_image', str, None),
    ('card_image', 'Card zobrazhennia', 30, 'card_image', str, None),
    ('cpd_points', 'CPD baly', 10, 'cpd_points', convert_int, None),
    ('target_audience', 'Tsilova audytoriia', 30, 'target_audience', semicolon_to_list, []),
    ('tags', 'Tehy', 30, 'tags', semicolon_to_list, []),
    ('trainer_name', 'Trener', 25, 'trainer_name', str, None),
    ('is_featured', 'Rekomendovanyi', 14, 'is_featured', convert_bool_ua, False),
    ('is_active', 'Aktyvnyi', 12, 'is_active', convert_bool_ua, True),
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
