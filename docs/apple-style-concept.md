# Apple-Style Design Concept for IPRM

Концепція дизайну сайту IPRM, побудована на аналізі apple.com (2024-2026),
Apple Human Interface Guidelines, Liquid Glass та найкращих практик медичних сайтів.

---

## 1. Філософія

Apple-style базується на п'яти принципах (HIG 2025):

1. **Clarity** -- текст завжди легко читається, іконки точні, орнамент не конкурує з контентом.
2. **Deference** -- UI обслуговує контент, а не навпаки; інтерфейс відступає, коли не потрібен.
3. **Depth** -- шари, напівпрозорість та рух комунікують ієрархію.
4. **Прогресивне розкриття** -- спочатку головне, деталі нижче. Кожна секція вирішує одне завдання.
5. **Емоційна типографіка** -- шрифт є основним візуальним інструментом. Розмір, вага та колір створюють ієрархію без допоміжних елементів.

### Адаптація для медичного сайту

- Медичний контент (дослідження, клінічні дані, кваліфікація лікарів) завжди візуально домінує.
- Білий простір між секціями комунікує впевненість організації.
- Glass-ефекти лише для навігації та cookie-банера, ніколи на основному тексті -- легкість читання клінічної інформації не повинна страждати від blur.
- Оригінальна фотографія замість стокових ілюстрацій (реальні лікарі, реальні процедури, реальні приміщення).

---

## 2. Кольорова палітра

### Brand tokens (CSS custom properties)

```css
:root {
    /* Нейтральні (apple.com exact values) */
    --black: #1d1d1f;        /* Основний текст (не pure black) */
    --dark: #1a1a2e;         /* Темні секції (фон) */
    --gray-dark: #424245;    /* Вторинний текст */
    --gray: #86868b;         /* Підтексти, описи (apple: #6e6e73 alt) */
    --gray-light: #d2d2d7;   /* Підтексти на темному фоні */
    --white: #fbfbfd;        /* Фон навігації */
    --section-bg: #f5f5f7;   /* Сірі секції (apple.com page bg) */

    /* Акцентні (IPRM brand) */
    --accent: #7055a4;       /* Фіолетовий -- основний акцент */
    --accent-hover: #5d4691; /* Фіолетовий при наведенні */
    --accent-light: #ede9f6; /* Фіолетовий фон (badge, іконки) */
    --orange: #e8913a;       /* Помаранчевий -- другий акцент */
    --orange-light: #fef0e6; /* Помаранчевий фон */

    /* Семантичні (apple system colors) */
    --success: #34c759;
    --warning: #ff9f0a;
    --error: #ff3b30;
}
```

### Правило нейтральності (Apple-first)

Apple не веде кольором. Палітра будується на нейтральних з одним акцентом на секцію. Акцент -- це завжди бренд (#7055a4), ніколи не декоративний.

### Правила застосування кольорів

| Контекст | Колір |
|----------|-------|
| Заголовки h1-h3 | `--black` (#1d1d1f) |
| Описи, підтексти | `--gray` (#86868b) |
| Тіло тексту | `--gray-dark` (#424245) |
| Кнопки, посилання, badge | `--accent` (#7055a4) |
| Градієнтний текст | `linear-gradient(135deg, --accent, #9b59b6, --orange)` |
| Градієнтні маркери | `linear-gradient(135deg, --accent, --orange)` |
| Темні секції (фон) | `--dark` (#1a1a2e) |
| Сірі секції (фон) | `--section-bg` (#f5f5f7) |
| Текст на темному фоні | `#f5f5f7` |
| Посилання на темному фоні | `#c4b5fd` (light purple) |

### Правило градієнтів

Градієнт використовується обмежено і лише для:
- Акцентного слова в заголовку (`.apple-gradient-text`)
- Маркерів списків (кружечки `::before`)
- Великих чисел у статистиці (на темному фоні)
- Subtle radial-gradient для depth в hero `::before` / `::after`

Ніколи не використовувати градієнт для: фону кнопок, цілих секцій, бордерів.

### Dark section gradient (Apple pattern)

```css
/* Плавний перехід, не різкий колір */
background: linear-gradient(180deg, #1d1d1f 0%, #2d2d2f 40%, #1a1a2e 100%);

/* Radial glow для depth */
::before {
    background: radial-gradient(ellipse 80% 60% at 50% 0%,
        rgba(112, 85, 164, 0.15) 0%, transparent 70%);
}
```

---

## 3. Типографіка

### Шрифт

**Inter** з variable axes (optical sizing 14-32). При великих розмірах Inter автоматично застосовує тісніший spacing та контраст штрихів, наближаючись до SF Pro Display.

```html
<link href="https://fonts.googleapis.com/css2?family=Inter:opsz,wght@14..32,300..700&display=swap" rel="stylesheet">
```

Fallback: `-apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif`

### Шкала розмірів

| Елемент | Розмір | Вага | Tracking | Line-height |
|---------|--------|------|----------|-------------|
| Hero h1 | `clamp(2.5rem, 7vw, 4.5rem)` | 800 | -0.04em | 1.05-1.08 |
| Section h2 | `clamp(2rem, 5vw, 3.25rem)` | 800 | -0.03em | 1.07 |
| Card h3 | 1.25rem -- 1.5rem | 700 | -0.02em | 1.2 |
| Body text | 17px (fixed!) | 400 | normal | 24px |
| Small text | 0.9375rem | 400 | normal | 1.5 |
| Labels, tags | 0.6875rem | 600 | 0.08em, uppercase | 1.2 |
| Nav links | 0.8125rem | 400 | normal | 1 |
| Caption | 13px | 400 | 0.01em | 1.4 |

### Body text -- фіксований, не fluid

Apple свідомо НЕ робить body text fluid. Body text залишається 17px на desktop та tablet, бо користувачі читають тіло тексту на схожій відстані. Fluid body text створює некомфортно малий текст на вузьких viewport.

### Letter-spacing -- прогресивне стиснення

Негативний letter-spacing на великих заголовках -- це те, що робить Apple-типографіку преміальною. Без нього великий display text виглядає розрідженим.

```css
/* Headings: progressively tighter */
--tracking-h4:   -0.02em;
--tracking-h3:   -0.025em;
--tracking-h2:   -0.03em;
--tracking-h1:   -0.035em;
--tracking-hero: -0.04em;

/* Labels: slightly open */
--tracking-label: 0.03em;
--tracking-caption: 0.01em;
```

### Font-weight контраст

Контраст між light (300) та bold (700) при однаковому розмірі -- це core Apple typographic signature:
- **700** для заголовків модулів та сертифікацій
- **300** для описів під великими числами або статистикою
- **400** для body text

### Gradient-text -- обов'язковий в кожному hero

Обгортати 1-2 ключових слова в `<span class="apple-gradient-text">`, не цілий заголовок.

- **Статичні заголовки:** вручну обрати ключове слово
  ```html
  <h1>Курси післядипломної<br><span class="apple-gradient-text">освіти.</span></h1>
  ```
- **Динамічні заголовки:** виділяти останнє слово через Jinja `rsplit(' ', 1)`:
  ```jinja2
  {% set words = event.title.rsplit(' ', 1) %}
  {{ words[0] }} <span class="apple-gradient-text">{{ words[1] }}</span>
  ```
- Для імен користувачів: gradient на прізвище (останнє слово)

---

## 4. Компонування (Layout)

### 8px сітка (spacing grid)

Всі padding та margin -- кратні 8px: `8, 16, 24, 32, 48, 64, 80, 120px`. Це створює візуальний ритм, який Apple досягає на своїх сторінках.

### Структура секцій -- три теми фону

- **Білий фон** (`#ffffff`) -- основна тема
- **Сірий фон** (`.apple-section-gray`) -- `#f5f5f7`
- **Темний фон** (`.apple-section-dark`) -- `#1a1a2e`

Секції чергуються для створення ритму:
```
hero (white) -> features (gray) -> stats (dark) -> courses (white) -> labs (gray) -> clinic (white) -> history (gray) -> cta (white)
```

### Padding секцій

| Breakpoint | Landing | Internal |
|------------|---------|----------|
| Desktop (>1200px) | `120px 24px` | `100px 24px` |
| Tablet (1024px) | `80px 24px` | `80px 24px` |
| Mobile (768px) | `64px 16px` | `64px 16px` |

### Content width (Apple pattern: три ширини)

| Тип | Max-width | Використання |
|-----|-----------|-------------|
| Wide | `1200px` | Грід карток, навігація |
| Default | `980px` | Section headers, hero content |
| Narrow | `800px` | Текстовий контент (about, legal, description) |

### CSS Containment для performance

```css
/* Below-fold секції */
.iprm-section {
    content-visibility: auto;
    contain-intrinsic-size: auto 600px;
}
```

---

## 5. Компоненти

### 5.1 Навігація (Glass)

```
[Logo "IPRM"]    [Посилання...]    [CTA кнопка]
```

- **Фіксована зверху**, `z-index: 1000`
- **Glass-ефект:** `backdrop-filter: saturate(180%) blur(20px);`
- **Прозорість:** `rgba(255, 255, 255, 0.72)`, при скролі `0.95`
- **Висота:** 52px (Apple: 44px, ми використовуємо 52px для кращої touch-зони)
- **Бордер знизу:** `1px solid rgba(0, 0, 0, 0.06)`
- **Logo:** текстом "IPRM" (`font-weight: 700; color: #7055a4`), не SVG
- **Dropdown:** blur backdrop + border-radius 12px + staggered fade-in
- **Mobile:** burger-menu (3 смужки -> X) з `aria-label="Menu"`, `aria-expanded`
- **Scroll effect:** JS toggle `.scrolled` class при `scrollY > 10`

```css
/* Accessibility fallback */
@media (prefers-reduced-transparency: reduce) {
    .nav { background: rgba(255, 255, 255, 0.95); backdrop-filter: none; }
}
```

### 5.2 Hero секція

```
[Badge / Price pill]
[Великий заголовок з gradient-text]   <-- gradient-text обов'язковий
[Підтекст сірим]
[Кнопка Primary]  [Кнопка Secondary >]
```

- `min-height: 100vh` (landing) або `92vh` (internal)
- Flexbox column, `align-items: center; text-align: center`
- **Gradient-text обов'язковий** в кожному hero h1
- **Декоративні radial-gradient** через `::before` та `::after` (opacity 0.05-0.06)
- **Послідовна анімація fadeUp** з `animation-delay`: badge 0s, h1 0.15s, p 0.3s, actions 0.45s
- **Easing:** `cubic-bezier(0.28, 0.11, 0.32, 1)` (Apple's reveal curve)

### 5.3 Section Header

```
[h2 заголовок]
[p підтекст сірим]
```

- Центрований, `max-width: 780px`
- `margin-bottom: 64-72px`
- h2: `font-weight: 800`, p: `color: var(--gray)`

### 5.4 Feature Cards (2-col grid)

```
[Icon 56x56]
[h3]
[p]
```

- Grid: `repeat(2, 1fr)`, gap 20px
- `border-radius: 24px`, padding `48px 36px`
- Hover: `translateY(-4px)`, `box-shadow: 0 12px 40px rgba(112, 85, 164, 0.1)`
- **Featured card:** `grid-column: span 2`, темний gradient-фон
- **Easing:** `cubic-bezier(0.25, 0.46, 0.45, 0.94)` (Apple's interaction curve)

### 5.5 Bento Grid (3-col grid)

```
[Hero card (span 3)]  -- темний, центрований
[Card] [Card] [Card]  -- з visual-area зверху
[Card] [Card] [Card]
```

- Grid: `repeat(3, 1fr)`, gap 20px
- `min-height: 320px`, hero card `400px`
- Visual area: gradient-фон placeholder
- Hover: `scale(1.01)` -- ледь помітне збільшення
- Apple reference: `border-radius: 18px` (bento cards on apple.com)

### 5.6 Clinic Cards (3-col grid)

```
[Image area (220px)]
[h3 + link >]
```

- `border-radius: 24px`, overflow hidden
- Image area: gradient-фон як placeholder
- Hover: `translateY(-4px)`, shadow

### 5.7 Stats Row

```
[Number+]  [Number+]  [Number+]  [Number+]
[label]    [label]    [label]    [label]
```

- Grid: `repeat(4, 1fr)`, text-align center
- Числа: `font-weight: 800`, gradient text
- Анімація: fade-in через `animation-timeline: view()` (CSS-only) або fallback через IntersectionObserver
- На темному фоні
- Label: `font-size: 0.9375rem`, `letter-spacing: 0.01em`

### 5.8 Trainer Section (split layout)

```
[Photo 320px]  [Name / Role / Bio / CTA]
```

- Grid: `320px 1fr`, gap 48px, `align-items: center`
- Photo: `border-radius: 24px`, `aspect-ratio: 3/4`, gradient-фон placeholder
- Role: `color: var(--accent)`, `font-weight: 500`
- Mobile: 1 колонка, photo зверху `aspect-ratio: 1`

### 5.9 Program Blocks (2-col grid)

```
[TAG (uppercase)]    [TAG (uppercase)]
[h3]                 [h3]
[li dot]             [li dot]
[li dot]             [li dot]
```

- Grid: `1fr 1fr`, gap 24px
- `border-radius: 24px`, padding `40px 36px`
- Tag: `font-size: 0.6875rem`, uppercase, `letter-spacing: 0.08em`, accent color
- List items: gradient dot `::before` 6x6px
- Separator: `border-top: 1px solid rgba(0, 0, 0, 0.05)`

### 5.10 CTA Section

```
[h2 з gradient-text]
[Підтекст]
[Primary button]  [Secondary button >]
```

- Центрований, `max-width: 700px`
- h2: `clamp(2.5rem, 6vw, 4rem)`

### 5.11 Кнопки

| Тип | Стиль |
|-----|-------|
| Primary | `background: var(--accent)`, color white, `border-radius: 980px`, padding `14px 32px` |
| Secondary | Прозорий, `color: var(--accent)`, `::after { content: ' >' }` |
| Nav CTA | Як primary, але менший: padding `8px 20px`, font-size `0.8125rem` |
| Link | `color: var(--accent)`, `::after { content: ' >' }` |

**Три стани взаємодії (Apple pattern):**
```css
.btn:hover {
    transform: scale(1.02) translateY(-1px);
    box-shadow: 0 8px 24px rgba(0, 0, 0, 0.18);
}
.btn:active {
    transform: scale(0.98) translateY(0);
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.12);
}
.btn:focus-visible {
    outline: 2px solid var(--accent);
    outline-offset: 3px;
}
```

`border-radius: 980px` -- Apple's "capsule" shape.

### 5.12 Badge / Price Pill

```css
font-size: 0.8125rem - 1rem;
font-weight: 500-600;
color: var(--accent);
background: var(--accent-light);
padding: 6-8px 16-24px;
border-radius: 980px;
```

### 5.13 Footer

```
[Brand + Copy]    [Link Link Link...]    [Socials + Phone]
```

- `border-top: 1px solid rgba(0, 0, 0, 0.06)`
- Padding `48px 24px`
- Flex, space-between, three columns
- Font-size `0.8125rem`, color `var(--gray)`
- Brand "IPRM" текстом, не SVG logo

### 5.14 Cookie Banner (floating glass)

```
[Text + link]                    [Accept]  [Required only]
```

- `position: fixed; bottom: 16px; left: 50%; transform: translateX(-50%);`
- `max-width: 800px; border-radius: 20px;`
- Glass: `backdrop-filter: blur(20px) saturate(180%);` on dark bg `rgba(29, 29, 31, 0.88)`
- Buttons: `border-radius: 980px`

---

## 6. Анімації

### Easing curves (Apple-specific)

Apple ніколи не використовує `ease` або `linear`. Конкретні криві:

```css
/* Reveal / fade-in */
--ease-reveal: cubic-bezier(0.28, 0.11, 0.32, 1);

/* Interaction (hover, press) */
--ease-interact: cubic-bezier(0.25, 0.46, 0.45, 0.94);

/* Spring-like bounce */
--ease-spring: cubic-bezier(0.32, 0.08, 0.24, 1);
```

### Scroll-reveal (CSS-first, JS fallback)

**Сучасний підхід (CSS Scroll-Driven Animations):**

```css
@media not (prefers-reduced-motion: reduce) {
    .apple-reveal {
        opacity: 0;
        transform: translateY(24px);
        animation: enter-view linear both;
        animation-timeline: view();
        animation-range: entry 0% entry 40%;
    }

    @keyframes enter-view {
        to { opacity: 1; transform: translateY(0); }
    }
}

/* Default: visible (для reduced-motion та fallback) */
.apple-reveal { opacity: 1; transform: none; }
```

**Fallback (IntersectionObserver):**

```javascript
// apple-reveal.js
var els = document.querySelectorAll('.apple-reveal');
var obs = new IntersectionObserver(function (entries) {
    entries.forEach(function (e) {
        if (e.isIntersecting) { e.target.classList.add('visible'); obs.unobserve(e.target); }
    });
}, { threshold: 0.12, rootMargin: '0px 0px -40px 0px' });
els.forEach(function (el) { obs.observe(el); });
```

### Hero fadeUp

```css
@keyframes appleHeroFadeUp {
    to { opacity: 1; transform: translateY(0); }
}
```

Елементи починають з `opacity: 0; transform: translateY(20-30px)` та з'являються послідовно: badge 0s, h1 0.15s, p 0.3s, actions 0.45s. Duration: `0.8s`.

### Hover-ефекти

| Елемент | Transform | Shadow | Duration |
|---------|-----------|--------|----------|
| Cards | `translateY(-4px)` | `0 12px 40px rgba(0,0,0,0.1)` | 0.3s |
| Bento | `scale(1.01)` | -- | 0.3s |
| Buttons | `scale(1.02) translateY(-1px)` | `0 8px 24px rgba(0,0,0,0.18)` | 0.15s |
| Links | `color` change | -- | 0.2s |

### Чотири правила Apple-руху

1. **Duration < 300ms** для UI-відповідей -- довше відчувається повільним
2. **Ease curves, ніколи linear** -- cubic-bezier з уповільненням в кінці (фізичний матеріал)
3. **Рух має сенс** -- кожна анімація комунікує (зв'язок, стан, ієрархію)
4. **Субтильність > спектакль** -- найкращі анімації ті, що користувач відчуває, але не може описати

### Dropdown staggered fade-in (Apple menu pattern)

```css
.dropdown-item:nth-child(1) { transition-delay: 0.02s; }
.dropdown-item:nth-child(2) { transition-delay: 0.05s; }
.dropdown-item:nth-child(3) { transition-delay: 0.08s; }
.dropdown-item:nth-child(4) { transition-delay: 0.11s; }
```

### prefers-reduced-motion

Правило Apple: **видаляти**, не сповільнювати. Сповільнені анімації можуть викликати більше нудоти у вестибулярно-чутливих користувачів.

```css
@media (prefers-reduced-motion: reduce) {
    .apple-reveal { transition: none; opacity: 1; transform: none; animation: none; }
}
```

---

## 7. Responsive

### Breakpoints (Apple reference: 1068px, 734px)

| Breakpoint | Наш | Зміни |
|------------|-----|-------|
| >1200px | Desktop | Повний layout |
| 1024px | Tablet | Grids 2-col, padding зменшується |
| 768px | Mobile | Grids 1-col, burger-menu, стек-layout |

### Mobile-specific правила

- Навігація: burger замість посилань, dropdown на всю ширину
- Hero actions: стек (column) замість row
- Feature grid: 1 колонка, featured card не span
- Bento grid: 1 колонка, hero card min-height зменшений
- Stats: 2x2 grid
- Trainer: 1 колонка, photo зверху `aspect-ratio: 1`
- Program: 1 колонка
- Footer: стек, text-align center

---

## 8. Accessibility

### Focus indicators (Apple pattern)

```css
:focus-visible {
    outline: 2px solid var(--accent);
    outline-offset: 3px;
}

/* Pill buttons -- match radius */
.apple-btn:focus-visible {
    outline: 2px solid var(--accent);
    outline-offset: 4px;
    border-radius: 980px;
}
```

### Prefers-reduced-transparency

```css
@media (prefers-reduced-transparency: reduce) {
    .iprm-header, .cookie-banner, .dropdown {
        background: rgba(255, 255, 255, 0.95);
        backdrop-filter: none;
    }
}
```

### Prefers-contrast: high

```css
@media (prefers-contrast: more) {
    :root {
        --black: #000000;
        --gray: #000000;
        --section-bg: #ffffff;
    }
    .glass-panel { backdrop-filter: none; border: 2px solid #000; }
}
```

### Selection

```css
::selection { background: var(--accent-light); color: var(--black); }
```

### Semantic HTML

- `<nav>` з `aria-label` для кожного navigation region
- `<main>` з skip-link target
- `<section>` з `aria-labelledby` на `<h2>`
- Course cards як `<article>` з heading hierarchy
- Burger: `aria-label="Menu"`, `aria-expanded="true/false"`
- Контраст тексту/фону: WCAG AA (4.5:1 мінімум, навіть після blur)

---

## 9. Performance (Apple patterns)

### CSS Containment

```css
/* Below-fold секції не рендеряться до потреби */
.iprm-section {
    content-visibility: auto;
    contain-intrinsic-size: auto 600px;
}
```

### Font loading

```html
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preload" href="/static/fonts/inter-400.woff2" as="font" type="font/woff2" crossorigin>
```

`font-display: swap` для Inter.

### Images

- `<picture>` з WebP + JPEG fallback
- Above-fold: `loading="eager" fetchpriority="high"`
- Below-fold: `loading="lazy"`
- Завжди explicit `width` та `height` для запобігання CLS

### will-change

Використовувати лише під час анімації, ніколи постійно:
```css
.card:hover { will-change: transform; }
```

---

## 10. Сучасні CSS-техніки (progressive enhancement)

### Container Queries

Компоненти адаптуються до контейнера, а не до viewport:

```css
.card-container { container-type: inline-size; }
@container (min-width: 400px) {
    .card-body { grid-template-columns: 1fr 1fr; }
}
```

### CSS Scroll-Driven Animations

Замінюють JavaScript scroll listeners для reveal-анімацій:

```css
.apple-reveal {
    animation: enter-view linear both;
    animation-timeline: view();
    animation-range: entry 0% entry 40%;
}
```

### View Transitions (page navigation)

```css
@view-transition { navigation: auto; }
::view-transition-old(root) { animation: fade-out 0.25s ease-out; }
::view-transition-new(root) { animation: fade-in 0.25s ease-in; }
```

### color-mix() для hover states

```css
.btn:hover {
    background: color-mix(in oklch, var(--accent), black 15%);
}
```

---

## 11. Структура HTML (патерн для нової сторінки)

```html
<div class="apple-page">
    <div class="iprm-hero-wrap">
        <section class="iprm-hero">            <!-- min-height 92-100vh -->
            <div class="iprm-hero__content">
                <div class="iprm-hero__badge">...</div>
                <h1 class="iprm-hero__title">...<span class="apple-gradient-text">...</span></h1>
                <p class="iprm-hero__subtitle">...</p>
                <div class="iprm-hero__actions">
                    <a class="apple-btn apple-btn--primary">...</a>
                    <a class="apple-btn apple-btn--secondary">...</a>
                </div>
            </div>
        </section>
    </div>
    <section class="iprm-section apple-section-gray">  <!-- alternating -->
        <div class="iprm-section__inner">
            <h2 class="iprm-section__title">...</h2>
            <p class="iprm-section__subtitle">...</p>
            <div class="apple-reveal"><!-- grid content --></div>
        </div>
    </section>
    <!-- ...more sections alternating white/gray/dark... -->
</div>
```

---

## 12. Чек-лист при редизайні сторінки

- [ ] Шрифт Inter з optical sizing підключено
- [ ] CSS custom properties визначені в `:root`
- [ ] Навігація fixed з glass-ефектом (`backdrop-filter`)
- [ ] Hero займає 92-100vh з fadeUp анімацією
- [ ] Gradient-text присутній у кожному hero h1 (статичний або через rsplit)
- [ ] Секції чергують фони (білий / сірий / темний)
- [ ] Section headers центровані з `max-width: 780px`
- [ ] Всі картки з `border-radius: 24px` та hover translateY(-4px)
- [ ] Кнопки capsule (`border-radius: 980px`) з 3 станами (hover/active/focus)
- [ ] Scroll-reveal через CSS `animation-timeline: view()` з JS fallback
- [ ] Easing: `cubic-bezier(0.28, 0.11, 0.32, 1)` для reveals, не `ease`
- [ ] Spacing кратний 8px (8, 16, 24, 32, 48, 64, 80, 120)
- [ ] Body text 17px fixed, не fluid
- [ ] Mobile: burger-menu, стек-layouts, padding 64px 16px
- [ ] `prefers-reduced-motion`: анімації видаляються, не сповільнюються
- [ ] `prefers-reduced-transparency`: solid fallback для glass
- [ ] Focus-visible з `outline-offset: 3px`
- [ ] Images: lazy loading, explicit dimensions, WebP
- [ ] `content-visibility: auto` на below-fold секціях
- [ ] Жодних декоративних елементів, тіней або бордерів без причини
- [ ] Semantic HTML: nav, main, section з aria-labelledby, article для карток

---

## 13. Джерела та посилання

- [Apple Human Interface Guidelines](https://developer.apple.com/design/human-interface-guidelines/)
- [Apple's Liquid Glass (WWDC 2025)](https://css-tricks.com/getting-clarity-on-apples-liquid-glass/)
- [CSS Scroll-Driven Animations (WebKit)](https://webkit.org/blog/17101/a-guide-to-scroll-driven-animations-with-just-css/)
- [Apple-style scroll animations (Builder.io)](https://www.builder.io/blog/view-timeline)
- [Healthcare UX Design Trends 2025 (Webstacks)](https://www.webstacks.com/blog/healthcare-ux-design)
- [CSS Wrapped 2025 (Smashing Magazine)](https://www.smashingmagazine.com/2025/12/state-logic-native-power-css-wrapped-2025/)
