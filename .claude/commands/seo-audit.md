Ти - експерт з SEO-оптимізації веб-сайтів, технічного SEO та структурованих даних.

## Мета

Повний SEO-аудит проекту IPRM з виправленням невідповідностей. Орієнтація на найкращі практики та золотий стандарт SEO.

> **Зона відповідальності:** HTML meta-теги, structured data, sitemap, robots.txt, canonical, OG/Twitter, заголовки, посилання, зображення, продуктивність, доступність (SEO-контекст).
> **НЕ перевіряй:** CSS стилі (це зона `/css-split`, `/ds-unify`), Python-архітектура (це зона `/audit-structure`).

$ARGUMENTS

Якщо аргументи не передано - провести повний SEO-аудит.

## Контекст проекту

- Flask 3.0+ з Jinja2 шаблонами
- Базовий шаблон: `app/templates/base.html` (всі meta-теги, JSON-LD, CSS/JS)
- Публічні сторінки: головна, курси (list + detail), тренери (list + detail), клініки (list + detail), legal-сторінки
- Приватні сторінки (noindex): auth, admin, registration, payments, design-system, errors
- Мова: українська (`lang="uk"`)
- Домен: iprm.space
- Розділювач title: `|` (формат: `Сторінка | IPRM`)

## Крок 1: Збір даних

Прочитай та проаналізуй:

1. `app/templates/base.html` - повний head section
2. Кожен публічний шаблон (main/index, courses/list, courses/event, trainers/list, trainers/detail, clinics/list, clinics/detail, legal-сторінки)
3. `app/main/routes.py` - robots.txt та sitemap.xml маршрути
4. `app/templates/sitemap.xml` - шаблон sitemap
5. Шаблони помилок (`errors/401.html`, `403.html`, `404.html`, `500.html`)
6. `app/__init__.py` - security headers
7. `config.py` - кешування, HTTPS

## Крок 2: Аудит за категоріями

Для кожної категорії перевір стан: OK / WARNING / ISSUE.

### 2.1 Title Tags
- Формат `Сторінка | IPRM` на всіх публічних сторінках
- Довжина: 30-60 символів (оптимально)
- Унікальність: кожна сторінка має свій title
- Динамічні сторінки (курси, тренери): title з БД
- Немає "IPRM - ..." формату (застарілий)
- Головна сторінка: повна назва інституту

### 2.2 Meta Descriptions
- Наявність `{% block meta_description %}` на КОЖНІЙ публічній сторінці
- Довжина: 120-160 символів
- Унікальність: не дублюються між сторінками
- Динамічні сторінки: description з БД (subtitle/short_description)
- Fallback у base.html для сторінок без свого блоку

### 2.3 Open Graph Tags
- `og:title` - автоматично з title
- `og:description` - автоматично з meta description
- `og:image` - є блок для перевизначення, default placeholder існує
- `og:image:width`, `og:image:height`, `og:image:type`, `og:image:alt`
- `og:type` - website (або перевизначений)
- `og:locale` - uk_UA
- `og:site_name` - IPRM
- Курси: og:image з card_image заходу

### 2.4 Twitter Card
- `twitter:card` - summary_large_image
- `twitter:title`, `twitter:description`, `twitter:image`
- Перевірити що значення підставляються з Jinja2 блоків

### 2.5 Canonical URLs
- `<link rel="canonical">` на кожній сторінці
- Блок `{% block canonical %}` для перевизначення
- Canonical без query-параметрів
- Немає дублів (www vs non-www, trailing slash)

### 2.6 Structured Data (JSON-LD)
- **EducationalOrganization** - глобально в base.html (name, url, logo, telephone, address)
- **Course** - на сторінках курсів (name, description, provider, offers, instructor, inLanguage)
- **Person** - на сторінках тренерів (name, jobTitle, description, worksFor)
- **BreadcrumbList** - на всіх list та detail сторінках
- Валідність JSON-LD (правильні лапки, коми, немає trailing comma)

### 2.7 robots.txt
- `Allow: /` для публічних сторінок
- `Disallow:` для auth, admin, registration, payments, design-system
- Посилання на Sitemap
- Немає блокування CSS/JS (Googlebot потребує доступу для рендерингу)

### 2.8 Sitemap.xml
- Динамічна генерація з БД
- Всі публічні сторінки: головна, курси, тренери, клініки, legal
- `<lastmod>` на динамічних сторінках
- `<priority>` та `<changefreq>` задані
- Content-Type: application/xml

### 2.9 Heading Hierarchy
- Кожна публічна сторінка має РІВНО ОДИН `<h1>`
- Послідовність: h1 > h2 > h3 (без пропусків рівнів)
- h1 відповідає темі сторінки (не підсекції)
- Немає дублювання h1/h2 з однаковим текстом

### 2.10 Зображення
- Всі `<img>` мають `alt` з описовим текстом
- `loading="lazy"` на below-fold зображеннях
- Above-fold зображення (header logo) БЕЗ lazy
- Перевірити наявність width/height або CSS aspect-ratio для CLS

### 2.11 Посилання
- Немає `href="#"` на публічних сторінках (крім anchor-посилань)
- Всі `target="_blank"` мають `rel="noopener noreferrer"`
- Внутрішні посилання використовують `url_for()` (не hardcoded)
- Зовнішні посилання мають `rel="noopener noreferrer"`
- Немає broken links (посилання на неіснуючі маршрути)

### 2.12 noindex/nofollow
- Приватні сторінки: `<meta name="robots" content="noindex, nofollow">` через `{% block extra_meta %}`
- Admin blueprint: також X-Robots-Tag header через after_request
- Auth blueprint: також X-Robots-Tag header
- Design System: noindex
- Публічні сторінки: БЕЗ noindex

### 2.13 Performance (SEO-вплив)
- Шрифти: self-hosted з `font-display: swap` і `<link rel="preload">`
- JS: `defer` на некритичних скриптах (molecular-background.js)
- Статичний кеш: `SEND_FILE_MAX_AGE_DEFAULT` у production
- Security headers: HSTS, X-Content-Type-Options, X-Frame-Options

### 2.14 Доступність (SEO-контекст)
- `<html lang="uk">`
- `aria-label` на іконочних посиланнях (соцмережі, кнопки)
- Семантичні теги: `<header>`, `<main>`, `<footer>`, `<nav>`, `<section>`
- 404 сторінка: навігаційні посилання для зменшення bounce rate

## Крок 3: Звіт

### Загальна оцінка
Коротка SEO-оцінка (2-3 речення). Бал від 0 до 100.

### Результати аудиту

Для кожної категорії:

**[Категорія]** - [OK / WARNING / ISSUE]
- Що добре (конкретні файли/факти)
- Що потребує виправлення (якщо є) - з файлами та рядками
- Конкретна рекомендація

### Зведена таблиця

| Категорія | Стан | Пріоритет |
|-----------|------|-----------|
| ... | OK/WARNING/ISSUE | High/Medium/Low |

## Крок 4: Виправлення

Якщо знайдено WARNING або ISSUE - **виправ їх негайно**.

Пріоритет виправлень:
1. **HIGH** - broken links, missing meta, heading issues, missing noindex
2. **MEDIUM** - incomplete OG/Twitter, missing lazy-load, accessibility
3. **LOW** - optimization, nice-to-have improvements

Після кожного виправлення:
- Вкажи що саме змінено (файл, рядок, було/стало)
- Переконайся що desktop-верстку не зламано

## Крок 5: Верифікація

Після всіх виправлень:
1. Перевір через тест-клієнт Flask що всі публічні сторінки рендеряться (200 OK)
2. Перевір що sitemap.xml містить всі очікувані URL
3. Перевір що robots.txt коректний
4. Grep для залишкових `href="#"` на публічних сторінках
5. Grep для `target="_blank"` без `rel="noopener noreferrer"`
6. Перевір що всі noindex на місці

## Обмеження

- НЕ змінюй CSS стилі - це зона `/css-split` та `/ds-unify`
- НЕ змінюй Python-архітектуру - це зона `/audit-structure`
- НЕ додавай нові залежності без обґрунтування
- НЕ видаляй існуючі meta-теги без причини
- Дотримуйся конвенції розділювача `|` в title
- Використовуй тільки `{% block %}` механізм Jinja2 для мета-тегів
- Використовуй українську мову для звіту та вмісту meta-тегів
- JSON-LD: тільки schema.org типи, валідний JSON
