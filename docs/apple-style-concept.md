# Apple-Style Design Concept for IPRM

Концепція дизайну, використана при створенні демо-сторінок IPRM в стилі Apple.
Цей документ є керівництвом для редизайну всіх сторінок сайту.

---

## 1. Філософія

Apple-style базується на трьох принципах:

1. **Контент як герой** -- жодних декоративних елементів, які не несуть сенсу. Великі заголовки, якісні зображення та багато повітря говорять самі за себе.
2. **Прогресивне розкриття** -- інформація подається порціями: спочатку головне, деталі -- нижче. Кожна секція вирішує одне завдання.
3. **Емоційна типографіка** -- шрифт є основним візуальним інструментом. Розмір, вага та колір тексту створюють ієрархію без допоміжних елементів.

---

## 2. Кольорова палітра

### Brand tokens (CSS custom properties)

```css
:root {
    /* Нейтральні */
    --black: #1d1d1f;        /* Основний текст */
    --dark: #1a1a2e;         /* Темні секції (фон) */
    --gray-dark: #424245;    /* Вторинний текст */
    --gray: #86868b;         /* Підтексти, описи */
    --gray-light: #d2d2d7;   /* Підтексти на темному фоні */
    --white: #fbfbfd;        /* Фон навігації */
    --section-bg: #f5f5f7;   /* Сірі секції */

    /* Акцентні */
    --accent: #7055a4;       /* Фіолетовий -- основний акцент */
    --accent-hover: #5d4691; /* Фіолетовий при наведенні */
    --accent-light: #ede9f6; /* Фіолетовий фон (badge, іконки) */
    --orange: #e8913a;       /* Помаранчевий -- другий акцент */
    --orange-light: #fef0e6; /* Помаранчевий фон */
}
```

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

### Правило градієнтів

Градієнт фіолетовий-помаранчевий використовується обмежено і лише для:
- Акцентного слова в заголовку (`.gradient-text`)
- Маркерів списків (кружечки `::before`)
- Великих чисел у статистиці (на темному фоні)

Ніколи не використовувати градієнт для: фону кнопок, цілих секцій, бордерів.

---

## 3. Типографіка

### Шрифт

**Inter** -- основний і єдиний шрифт. Fallback: `-apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif`.

### Шкала розмірів

| Елемент | Desktop | Mobile | Вага | Tracking |
|---------|---------|--------|------|----------|
| Hero h1 | `clamp(2.5rem, 7vw, 4.5rem)` | `clamp(2rem, 8vw, 3rem)` | 800 | -0.04em |
| Section h2 | `clamp(2rem, 5vw, 3.25rem)` | auto | 800 | -0.03em |
| Card h3 | 1.25rem -- 1.5rem | auto | 700 | -0.02em |
| Body text | 1rem -- 1.0625rem | auto | 400 | normal |
| Small text | 0.875rem -- 0.9375rem | auto | 400 | normal |
| Labels, tags | 0.6875rem -- 0.8125rem | auto | 500-600 | 0.08em, uppercase |
| Nav links | 0.8125rem | auto | 400 | normal |

### Правила тексту

- **line-height:** заголовки 1.06-1.1, текст 1.5-1.7
- **max-width:** заголовки hero -- 860-900px, описи -- 620-640px, секції about -- 800px
- **Gradient-text:** обов'язковий в кожному hero-заголовку. Обгортати 1-2 ключових слова в `<span class="apple-gradient-text">`, не цілий заголовок
  - **Статичні заголовки:** вручну обрати ключове слово (напр. "Курси післядипломної `<br>` `<span>` освіти. `</span>`")
  - **Динамічні заголовки:** виділяти останнє слово через Jinja `rsplit(' ', 1)`: `{{ words[0] }} <span class="apple-gradient-text">{{ words[1] }}</span>`
  - Для імен користувачів: gradient на прізвище (останнє слово)
- **Кожен заголовок** має `letter-spacing` з від'ємним значенням (tight)

---

## 4. Компонування (Layout)

### Структура секцій

Кожна секція має одну з трьох тем:
- **Білий фон** -- основна тема
- **Сірий фон** (`.section-gray`) -- `#f5f5f7`
- **Темний фон** (`.section-dark`) -- `#1a1a2e`

Секції чергуються для створення ритму:
```
hero (білий) -> features (сірий) -> stats (темний) -> labs (сірий) -> clinic (білий) -> about (сірий) -> cta (білий) -> footer
```

### Padding секцій

| Breakpoint | Padding |
|------------|---------|
| Desktop | `120px 24px` (landing) / `100px 24px` (internal pages) |
| Tablet (1024px) | `80px 24px` |
| Mobile (768px) | `64px 16px` |

### Content width

- Навігація, грід: `max-width: 1200px; margin: 0 auto;`
- Текстовий контент: `max-width: 800px; margin: 0 auto;`
- Section header: `max-width: 700-780px; margin: 0 auto 64-72px;`
- Hero text: `max-width: 860-900px` (заголовок), `620-640px` (опис)

---

## 5. Компоненти

### 5.1 Навігація

```
[Logo]    [Посилання...]    [CTA кнопка]
```

- **Фіксована зверху**, `z-index: 1000`
- **Blur-ефект:** `backdrop-filter: saturate(180%) blur(20px);`
- **Прозорість:** `rgba(251, 251, 253, 0.72)`, при скролі `0.92`
- **Висота:** 52px
- **Бордер знизу:** `1px solid rgba(0, 0, 0, 0.06)`
- **Mobile:** burger-menu (3 смужки -> X при відкритті)

### 5.2 Hero секція

```
[Badge / Price pill]
[Великий заголовок з gradient-text]   <-- gradient-text обов'язковий
[Підтекст сірим]
[Кнопка Primary]  [Кнопка Secondary >]
```

- `min-height: 100vh` (landing) або `92vh` (internal)
- Flexbox column, `align-items: center; text-align: center`
- **Gradient-text обов'язковий** у кожному hero h1 -- жоден hero не може бути без gradient-слова
- **Декоративні radial-gradient** через `::before` та `::after` (opacity 0.05-0.06)
- **Послідовна анімація fadeUp** з `animation-delay`: badge 0s, h1 0.15s, p 0.3s, actions 0.45s

### 5.3 Section Header

```
[h2 заголовок]
[p підтекст сірим]
```

- Центрований, `max-width: 700px`
- `margin-bottom: 64-72px`
- h2: `font-weight: 800`, p: `color: var(--gray)`

### 5.4 Feature Cards (2-колонковий грід)

```
[Icon 56x56]
[h3]
[p]
```

- Grid: `repeat(2, 1fr)`, gap 20px
- `border-radius: 24px`, padding `48px 36px`
- Hover: `translateY(-4px)`, `box-shadow: 0 12px 40px rgba(112, 85, 164, 0.1)`
- **Featured card:** `grid-column: span 2`, темний gradient-фон

### 5.5 Bento Grid (3-колонковий грід)

```
[Hero card (span 3)]  -- темний, центрований
[Card] [Card] [Card]  -- з visual-area зверху
[Card] [Card] [Card]
```

- Grid: `repeat(3, 1fr)`, gap 20px
- `min-height: 320px`, hero card `400px`
- Visual area: верхня частина картки з іконкою на gradient-фоні
- Hover: `scale(1.01)` -- ледь помітне збільшення

### 5.6 Clinic Cards (3-колонковий грід)

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
- Анімація counter при scroll (requestAnimationFrame)
- На темному фоні

### 5.8 Trainer Section (split layout)

```
[Photo 320px]  [Name / Role / Bio / CTA]
```

- Grid: `320px 1fr`, gap 48px, `align-items: center`
- Photo: `border-radius: 24px`, `aspect-ratio: 3/4`, gradient-фон як placeholder
- Role: `color: var(--accent)`, `font-weight: 500`
- Mobile: 1 колонка, photo зверху `aspect-ratio: 1`

### 5.9 Program Blocks (2-колонковий грід)

```
[TAG (uppercase)]    [TAG (uppercase)]
[h3]                 [h3]
[li dot]             [li dot]
[li dot]             [li dot]
```

- Grid: `1fr 1fr`, gap 24px
- `border-radius: 24px`, padding `40px 36px`
- Tag: `font-size: 0.6875rem`, uppercase, `letter-spacing: 0.08em`, accent color
- List items: кастомний маркер `::before` -- gradient dot 6x6px
- Separator: `border-top: 1px solid rgba(0, 0, 0, 0.05)`

### 5.10 CTA Section (фінальний заклик)

```
[h2 з gradient-text]
[Підтекст]
[Primary button]  [Secondary button >]
```

- Центрований, `max-width: 700px`
- h2 більший ніж звичайний section header: `clamp(2.5rem, 6vw, 4rem)`

### 5.11 Кнопки

| Тип | Стиль |
|-----|-------|
| Primary | `background: var(--accent)`, color white, `border-radius: 980px`, padding `14px 32px` |
| Secondary | Прозорий, `color: var(--accent)`, `::after { content: ' >' }` |
| Nav CTA | Як primary, але менший: padding `8px 20px`, font-size `0.8125rem` |
| Link | `color: var(--accent)`, `::after { content: ' >' }` |

Hover primary: `background: var(--accent-hover)`, `scale(1.02)`.
`border-radius: 980px` -- Apple's "capsule" shape (ніколи не квадратні кути).

### 5.12 Badge / Price Pill

```css
font-size: 0.8125rem - 1rem;
font-weight: 500-600;
color: var(--accent);
background: var(--accent-light);
padding: 6-8px 16-24px;
border-radius: 980px;
```

Використовується в hero для мітки ("Бали БПР") або ціни ("7 500 UAH").

### 5.13 Footer

```
[Copyright]                    [Link]  [Link]  [Link]
```

- `border-top: 1px solid rgba(0, 0, 0, 0.06)`
- Padding `48px 24px`
- Flex, space-between
- Font-size `0.8125rem`, color `var(--gray)`

---

## 6. Анімації

### Scroll-reveal

Всі блоки, крім hero, з'являються при скролі:

```css
.reveal {
    opacity: 0;
    transform: translateY(40px);
    transition: opacity 0.8s ease, transform 0.8s ease;
}
.reveal.visible {
    opacity: 1;
    transform: translateY(0);
}
```

Trigger: `IntersectionObserver` з `threshold: 0.15`, `rootMargin: '0px 0px -60px 0px'`.
Елемент анімується один раз -- після появи observer відключається (`unobserve`).

### Hero fadeUp

```css
@keyframes fadeUp {
    to { opacity: 1; transform: translateY(0); }
}
```

Елементи hero починають з `opacity: 0; transform: translateY(20-30px)` та послідовно з'являються з затримкою 0.15s між кожним.

### Hover-ефекти

- **Картки:** `translateY(-4px)` + shadow
- **Bento:** `scale(1.01)`
- **Кнопки primary:** `scale(1.02)`
- **Посилання:** зміна кольору через `transition: color 0.2s`

Тривалість transitions: 0.2-0.3s. Ніколи не використовувати "bounce", "elastic" або інші агресивні анімації.

### Counter animation (для статистики)

requestAnimationFrame з easeOutCubic (`1 - Math.pow(1 - progress, 3)`), тривалість 2000ms.

### prefers-reduced-motion

```css
@media (prefers-reduced-motion: reduce) {
    .reveal { transition: none; opacity: 1; transform: none; }
    /* Все одразу видиме, без анімацій */
}
```

---

## 7. Responsive

### Breakpoints

| Breakpoint | Зміни |
|------------|-------|
| >1200px | Повний layout |
| 1024px | Grids 2-col, padding зменшується |
| 768px | Grids 1-col, burger-menu, стек-layout |

### Mobile-specific правила

- Навігація: burger замість посилань
- Hero actions: стек (column) замість row
- Feature grid: 1 колонка, featured card не span
- Bento grid: 1 колонка
- Stats: 2x2 grid
- Trainer: 1 колонка, photo зверху (square)
- Program: 1 колонка
- Footer: стек, text-align center

---

## 8. Accessibility

- **Focus-visible:** `outline: 2px solid var(--accent); outline-offset: 2px;`
- **Selection:** `background: var(--accent-light); color: var(--black);`
- **Burger:** `aria-label="Menu"`, `aria-expanded="true/false"`
- **Contrast:** всі комбінації тексту/фону проходять WCAG AA
- **prefers-reduced-motion:** всі анімації вимикаються

---

## 9. Структура HTML (патерн для нової сторінки)

```html
<nav>                        <!-- fixed top, blur -->
<section class="hero">       <!-- min-height 92-100vh -->
<section class="section section-gray">  <!-- альтернуюча секція -->
<section class="section section-dark">  <!-- темна секція -->
<section class="section">               <!-- біла секція -->
<section class="section section-gray">  <!-- сіра секція -->
<section class="section">               <!-- CTA секція -->
<footer>
```

Кожна section має:
```html
<section class="section [section-gray|section-dark]">
    <div class="section-header reveal">
        <h2>...</h2>
        <p>...</p>
    </div>
    <div class="[grid-component] reveal">
        <!-- cards / content -->
    </div>
</section>
```

---

## 10. Чек-лист при редизайні сторінки

- [ ] Шрифт Inter підключено (wght 300-900)
- [ ] CSS custom properties визначені в `:root`
- [ ] Навігація fixed з blur-ефектом
- [ ] Hero займає майже повний екран з fadeUp анімацією
- [ ] Секції чергують фони (білий / сірий / темний)
- [ ] Section headers центровані з обмеженою шириною
- [ ] Всі картки з `border-radius: 24px` та hover-ефектом
- [ ] Кнопки capsule (`border-radius: 980px`)
- [ ] Gradient-text присутній у кожному hero h1 (статичний або динамічний через rsplit)
- [ ] Scroll-reveal анімація через IntersectionObserver
- [ ] Mobile: burger-menu, стек-layouts, зменшені padding
- [ ] Focus-visible стилі
- [ ] prefers-reduced-motion підтримка
- [ ] Жодних декоративних елементів, тіней або бордерів без причини

---

## 11. Приклади реалізації

| Сторінка | Файл |
|----------|------|
| Головна (landing) | `apple-style-demo.html` |
| Курс (internal) | `apple-course-demo.html` |
| Static copies | `app/static/demos/apple-style.html`, `app/static/demos/apple-course.html` |
