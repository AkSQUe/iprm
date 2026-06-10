"""Flask CLI commands.

Старий seed_courses (на базі Event моделі) видалено -- Events замінено
на Course+CourseInstance через міграцію. Нові курси створюються через
/admin/courses або імпорт (TBD).
"""
import os

import click
from flask.cli import with_appcontext


@click.command('blog-media-migrate')
@click.option('--dry-run', is_flag=True, help='Лише показати, що буде зроблено.')
@with_appcontext
def blog_media_migrate(dry_run):
    """Перенести наявні зображення блогу зі static у медіа-реєстр (Фаза 3).

    Для кожного допису обробляє обкладинку (cover_image) та зображення у
    блоках контенту (image/gallery), що ще посилаються на /static/images/blog/.
    Файли КОПІЮЮТЬСЯ у MEDIA_FOLDER (старі лишаються як бекап -- прибирання у
    Фазі 6), створюються MediaFile (+варіанти), а посилання переписуються на
    /media/... з media_id. Ідемпотентно: вже мігровані посилання пропускаються.
    """
    from flask import current_app
    from app.extensions import db
    from app.models.blog_post import BlogPost
    from app.services import media_service

    static_root = current_app.static_folder
    prefix = '/static/'
    cache = {}   # static_url -> MediaFile (у межах одного допису)
    stats = {'posts': 0, 'covers': 0, 'images': 0, 'missing': 0, 'skipped': 0}

    def _is_static_blog(url):
        return isinstance(url, str) and url.startswith('/static/images/blog/')

    def _abs_for(url):
        rel = url[len(prefix):]                       # images/blog/...
        return os.path.join(static_root, *rel.split('/'))

    def _ingest(url, post, usage):
        """Повертає MediaFile для static-URL (з кешу або створює) або None."""
        if url in cache:
            return cache[url]
        src = _abs_for(url)
        if not os.path.isfile(src):
            stats['missing'] += 1
            click.echo(f'  ! файл відсутній на диску: {url}')
            return None
        if dry_run:
            click.echo(f'  + {usage}: {url} -> (новий MediaFile)')
            cache[url] = None
            return None
        media, err = media_service.create_from_path(
            src, original_name=os.path.basename(src), entity_type='blog_post',
            entity_id=post.id, usage_type=usage,
        )
        if err:
            click.echo(f'  ! помилка обробки {url}: {err}')
            return None
        cache[url] = media
        return media

    posts = BlogPost.query.order_by(BlogPost.id.asc()).all()
    for post in posts:
        cache.clear()
        changed = False
        click.echo(f'Допис #{post.id} "{post.title}"')

        # --- Обкладинка ---
        if post.cover_media_id:
            stats['skipped'] += 1
        elif _is_static_blog(post.cover_image):
            media = _ingest(post.cover_image, post, 'cover')
            if media:
                post.cover_media_id = media.id
                post.cover_image = media.variant_url('card')
                stats['covers'] += 1
                changed = True

        # --- Блоки контенту ---
        new_blocks = []
        for block in (post.content or []):
            if not isinstance(block, dict):
                new_blocks.append(block)
                continue
            data = dict(block.get('data') or {})
            btype = block.get('type')

            if btype == 'image' and not data.get('media_id') and _is_static_blog(data.get('url')):
                media = _ingest(data['url'], post, 'inline')
                if media:
                    data.update(url=media.url, thumb=media.variant_url('thumb'),
                                card=media.variant_url('card'), media_id=media.id,
                                width=media.width, height=media.height)
                    stats['images'] += 1
                    changed = True
                new_blocks.append({'type': btype, 'data': data})

            elif btype == 'gallery':
                imgs = []
                for img in (data.get('images') or []):
                    img = dict(img) if isinstance(img, dict) else {}
                    if not img.get('media_id') and _is_static_blog(img.get('url')):
                        media = _ingest(img['url'], post, 'gallery')
                        if media:
                            img.update(url=media.url, thumb=media.variant_url('thumb'),
                                       card=media.variant_url('card'), media_id=media.id)
                            stats['images'] += 1
                            changed = True
                    imgs.append(img)
                data['images'] = imgs
                new_blocks.append({'type': btype, 'data': data})
            else:
                new_blocks.append(block)

        if changed and not dry_run:
            post.content = new_blocks
            stats['posts'] += 1
            db.session.commit()
        elif changed:
            stats['posts'] += 1

    click.echo(
        f"\nГотово{' (DRY-RUN)' if dry_run else ''}: "
        f"дописів змінено={stats['posts']}, обкладинок={stats['covers']}, "
        f"зображень={stats['images']}, відсутніх файлів={stats['missing']}, "
        f"пропущено обкладинок={stats['skipped']}"
    )


@click.command('trainer-media-migrate')
@click.option('--dry-run', is_flag=True, help='Лише показати, що буде зроблено.')
@with_appcontext
def trainer_media_migrate(dry_run):
    """Перенести фото та регалії-зображення тренерів зі static у медіа-реєстр.

    Обробляє фото (photo), сертифікати (certificates) та скани патентів
    (patents[].image), що ще посилаються на /static/images/trainers/. Файли
    КОПІЮЮТЬСЯ у MEDIA_FOLDER, створюються MediaFile (+варіанти), посилання
    переписуються на /media/... з media_id. Ідемпотентно; static лишається.
    """
    from flask import current_app
    from app.extensions import db
    from app.models.trainer import Trainer
    from app.services import media_service

    static_root = current_app.static_folder
    prefix = '/static/'
    stats = {'trainers': 0, 'photos': 0, 'certs': 0, 'patents': 0, 'missing': 0}

    def _is_static(url):
        return isinstance(url, str) and url.startswith('/static/images/trainers/')

    def _ingest(url, trainer, usage):
        src = os.path.join(static_root, *url[len(prefix):].split('/'))
        if not os.path.isfile(src):
            stats['missing'] += 1
            click.echo(f'  ! файл відсутній: {url}')
            return None
        if dry_run:
            click.echo(f'  + {usage}: {url}')
            return None
        media, err = media_service.create_from_path(
            src, original_name=os.path.basename(src), entity_type='trainer',
            entity_id=trainer.id, usage_type=usage,
        )
        if err:
            click.echo(f'  ! помилка {url}: {err}')
            return None
        return media

    for trainer in Trainer.query.order_by(Trainer.id.asc()).all():
        changed = False
        click.echo(f'Тренер #{trainer.id} "{trainer.full_name}"')

        # --- Фото ---
        if not trainer.photo_media_id and _is_static(trainer.photo):
            media = _ingest(trainer.photo, trainer, 'photo')
            if media:
                trainer.photo_media_id = media.id
                trainer.photo = media.variant_url('card')
                stats['photos'] += 1
                changed = True

        # --- Сертифікати ---
        new_certs = []
        for cert in (trainer.certificates or []):
            cert = dict(cert) if isinstance(cert, dict) else {}
            if not cert.get('media_id') and _is_static(cert.get('url')):
                media = _ingest(cert['url'], trainer, 'certificate')
                if media:
                    cert.update(url=media.url, thumb=media.variant_url('thumb'),
                                card=media.variant_url('card'), media_id=media.id)
                    stats['certs'] += 1
                    changed = True
            new_certs.append(cert)

        # --- Скани патентів ---
        new_patents = []
        for pat in (trainer.patents or []):
            pat = dict(pat) if isinstance(pat, dict) else {}
            if not pat.get('media_id') and _is_static(pat.get('image')):
                media = _ingest(pat['image'], trainer, 'patent')
                if media:
                    pat.update(image=media.url, thumb=media.variant_url('thumb'),
                               card=media.variant_url('card'), media_id=media.id)
                    stats['patents'] += 1
                    changed = True
            new_patents.append(pat)

        if changed and not dry_run:
            trainer.certificates = new_certs
            trainer.patents = new_patents
            stats['trainers'] += 1
            db.session.commit()
        elif changed:
            stats['trainers'] += 1

    click.echo(
        f"\nГотово{' (DRY-RUN)' if dry_run else ''}: "
        f"тренерів змінено={stats['trainers']}, фото={stats['photos']}, "
        f"сертифікатів={stats['certs']}, патентів={stats['patents']}, "
        f"відсутніх файлів={stats['missing']}"
    )


@click.command('course-media-migrate')
@click.option('--dry-run', is_flag=True, help='Лише показати, що буде зроблено.')
@with_appcontext
def course_media_migrate(dry_run):
    """Перенести hero/card-зображення курсів зі static у медіа-реєстр (Фаза 5).

    Обробляє hero_image та card_image, що ще посилаються на
    /static/images/courses/. Файли КОПІЮЮТЬСЯ у MEDIA_FOLDER (+варіанти),
    посилання переписуються на /media/... з *_media_id. Ідемпотентно.
    """
    from flask import current_app
    from app.extensions import db
    from app.models.course import Course
    from app.services import media_service

    static_root = current_app.static_folder
    prefix = '/static/'
    stats = {'courses': 0, 'images': 0, 'missing': 0}

    def _is_static(url):
        return isinstance(url, str) and url.startswith('/static/images/courses/')

    def _ingest(url, course, usage):
        src = os.path.join(static_root, *url[len(prefix):].split('/'))
        if not os.path.isfile(src):
            stats['missing'] += 1
            click.echo(f'  ! файл відсутній: {url}')
            return None
        if dry_run:
            click.echo(f'  + {usage}: {url}')
            return None
        media, err = media_service.create_from_path(
            src, original_name=os.path.basename(src), entity_type='course',
            entity_id=course.id, usage_type=usage,
        )
        if err:
            click.echo(f'  ! помилка {url}: {err}')
            return None
        return media

    for course in Course.query.order_by(Course.id.asc()).all():
        changed = False
        click.echo(f'Курс #{course.id} "{course.title}"')

        if not course.hero_media_id and _is_static(course.hero_image):
            media = _ingest(course.hero_image, course, 'hero')
            if media:
                course.hero_media_id = media.id
                course.hero_image = media.url
                stats['images'] += 1
                changed = True

        if not course.card_media_id and _is_static(course.card_image):
            media = _ingest(course.card_image, course, 'card')
            if media:
                course.card_media_id = media.id
                course.card_image = media.variant_url('card')
                stats['images'] += 1
                changed = True

        if changed and not dry_run:
            stats['courses'] += 1
            db.session.commit()
        elif changed:
            stats['courses'] += 1

    click.echo(
        f"\nГотово{' (DRY-RUN)' if dry_run else ''}: "
        f"курсів змінено={stats['courses']}, зображень={stats['images']}, "
        f"відсутніх файлів={stats['missing']}"
    )


@click.command('seed-courses')
@with_appcontext
def seed_courses():
    """Deprecated: seed тепер виконується через міграції.

    Команда залишена як no-op для сумісності з існуючими Makefile/doc
    посиланнями. Реальний seed виконується під час data-міграції
    a3b4c5d6e7f8 (Phase 2).
    """
    click.echo(
        'seed-courses: no-op. Контент курсів мігровано через '
        'alembic migration a3b4c5d6e7f8. Створюйте нові курси '
        'через /admin/courses.'
    )
