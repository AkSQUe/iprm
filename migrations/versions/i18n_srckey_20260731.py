"""i18n: перекласти JSON-оверрайди з ключа-шляху на ключ-хеш джерела

Revision ID: i18n_srckey_20260731
Revises: course_final_cta_20260730
Create Date: 2026-07-31 00:00:00.000000

Переклад JSON-поля (faq, регалії тренера, блоки блогу, items) зберігався
в translations як мапа {шлях: текст} -- '0.answer', '1.q'. Прив'язка до
ПОЗИЦІЇ ламалась при перестановці: вставили нове питання на початок --
шлях '0.answer' лишався валідним, і готовий переклад мовчки з'їжджав на
інше питання. Публічна сторінка показувала неправильний переклад без
жодної ознаки помилки.

Ключем стає хеш українського джерела (sha1[:12]) -- переклад іде за
текстом, тож перестановки, вставки й видалення безпечні.

Міграція НЕ втрачає даних: оверрайди, чий шлях більше не резолвиться в
поточній укр-структурі (вказують на технічні/ассетні листки), лишаються
як є -- читання підтримує обидва формати.

Схему не змінює, лише вміст JSON-колонки translations у 4 таблицях.
"""
import hashlib

from alembic import op
import sqlalchemy as sa


revision = 'i18n_srckey_20260731'
down_revision = 'course_final_cta_20260730'
branch_labels = None
depends_on = None


# Таблиця -> перекладні JSON-поля. Зафіксовано на момент міграції: models
# можуть змінитись, міграція мусить лишитись відтворюваною.
JSON_FIELDS = {
    'courses': ['target_audience', 'tags', 'faq'],
    'trainers': ['certificates', 'patents', 'articles', 'research',
                 'skills', 'education', 'additional_education',
                 'work_experience'],
    'blog_posts': ['content'],
    'program_blocks': ['items'],
}

LANGUAGES = ['ru', 'en']

# --- Копія логіки обходу листків (app.i18n на момент міграції) -------------

TECHNICAL_KEYS = frozenset({
    'type', 'id', 'url', 'src', 'href', 'slug', 'youtube_id', 'video_id',
    'media_id', 'image', 'icon', 'anchor', 'level', 'align', 'alignment',
    'style', 'format', 'code', 'variant', 'target', 'rel', 'lang',
    'thumb', 'card', 'full', 'preview', 'poster', 'file', 'path', 'srcset',
})

_ASSET_PREFIXES = ('/', 'http://', 'https://', 'data:', 'blob:', '#',
                   'mailto:', 'tel:')
_ASSET_EXTS = ('.webp', '.jpg', '.jpeg', '.png', '.gif', '.svg', '.avif',
               '.ico', '.bmp', '.mp4', '.webm', '.mov', '.pdf', '.heic',
               '.heif', '.zip')


def _is_translatable_leaf(value):
    v = value.strip()
    if not v or not any(ch.isalpha() for ch in v):
        return False
    if v.startswith(_ASSET_PREFIXES):
        return False
    if ' ' not in v and v.lower().endswith(_ASSET_EXTS):
        return False
    return True


def _walk_leaves(value, path=''):
    leaves = []
    if isinstance(value, dict):
        for key, item in value.items():
            if '.' in key:
                continue
            child = f'{path}{key}'
            if isinstance(item, (dict, list)):
                leaves += _walk_leaves(item, child + '.')
            elif (isinstance(item, str) and key not in TECHNICAL_KEYS
                  and _is_translatable_leaf(item)):
                leaves.append((child, item))
    elif isinstance(value, list):
        for i, item in enumerate(value):
            child = f'{path}{i}'
            if isinstance(item, (dict, list)):
                leaves += _walk_leaves(item, child + '.')
            elif isinstance(item, str) and _is_translatable_leaf(item):
                leaves.append((child, item))
    return leaves


def _source_key(text):
    return hashlib.sha1(text.strip().encode('utf-8')).hexdigest()[:12]


def _table(name, fields):
    return sa.table(
        name,
        sa.column('id', sa.BigInteger),
        sa.column('translations', sa.JSON),
        *[sa.column(f, sa.JSON) for f in fields],
    )


def _rekey(rows_updater):
    """Пройтись усіма таблицями і перебудувати мапи оверрайдів."""
    conn = op.get_bind()
    changed_rows = 0
    changed_keys = 0
    kept_keys = 0

    for table_name, fields in JSON_FIELDS.items():
        tbl = _table(table_name, fields)
        rows = conn.execute(
            sa.select(tbl.c.id, tbl.c.translations,
                      *[tbl.c[f] for f in fields])
            .where(tbl.c.translations.isnot(None))
        ).mappings().all()

        for row in rows:
            translations = row['translations']
            if not isinstance(translations, dict):
                continue
            new_translations = {
                lang: dict(bucket or {})
                for lang, bucket in translations.items()
            }
            row_touched = False

            for lang in LANGUAGES:
                bucket = new_translations.get(lang)
                if not bucket:
                    continue
                for fld in fields:
                    overrides = bucket.get(fld)
                    if not isinstance(overrides, dict) or not overrides:
                        continue
                    leaves = _walk_leaves(row[fld] or [])
                    rebuilt, n_changed, n_kept = rows_updater(overrides, leaves)
                    if rebuilt != overrides:
                        bucket[fld] = rebuilt
                        row_touched = True
                    changed_keys += n_changed
                    kept_keys += n_kept

            if row_touched:
                conn.execute(
                    tbl.update()
                    .where(tbl.c.id == row['id'])
                    .values(translations=new_translations)
                )
                changed_rows += 1

    print(f'  i18n_srckey: рядків оновлено {changed_rows}, '
          f'ключів переведено {changed_keys}, лишено без змін {kept_keys}')


def _path_to_hash(overrides, leaves):
    """{шлях: текст} -> {хеш джерела: текст}."""
    source_by_path = dict(leaves)
    rebuilt = {}
    n_changed = n_kept = 0
    for key, text in overrides.items():
        source = source_by_path.get(key)
        if source is None:
            # Шлях не резолвиться (технічний листок або застаріла структура) --
            # лишаємо як є, читання підтримує legacy-формат.
            rebuilt[key] = text
            n_kept += 1
            continue
        rebuilt[_source_key(source)] = text
        n_changed += 1
    return rebuilt, n_changed, n_kept


def _hash_to_path(overrides, leaves):
    """{хеш джерела: текст} -> {шлях: текст} (для downgrade)."""
    path_by_hash = {}
    for path, source in leaves:
        path_by_hash.setdefault(_source_key(source), path)
    rebuilt = {}
    n_changed = n_kept = 0
    for key, text in overrides.items():
        path = path_by_hash.get(key)
        if path is None:
            rebuilt[key] = text
            n_kept += 1
            continue
        rebuilt[path] = text
        n_changed += 1
    return rebuilt, n_changed, n_kept


def upgrade():
    _rekey(_path_to_hash)


def downgrade():
    _rekey(_hash_to_path)
