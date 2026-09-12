"""Модель DatabaseBackup: показ розмірів і статистика."""
from app.models.database_backup import DatabaseBackup


def test_file_size_display_leaves_attribute_intact():
    """Показ розміру НЕ має псувати сам атрибут.

    Властивість ділила `self.file_size_bytes` у циклі, тобто кожен рендер
    списку перетворював 5 МБ на число 5. Інстанс після цього «брудний», і
    найближчий commit у тому ж запиті записував у базу 5 замість 5242880.
    """
    backup = DatabaseBackup(file_size_bytes=5 * 1024 * 1024)

    assert backup.file_size_display == '5.0 MB'
    assert backup.file_size_bytes == 5 * 1024 * 1024
