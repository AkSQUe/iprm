# IPRM Design System - Style Guide

## 1. Foundations

### 1.1 CSS Variables (`:root`)

| Variable                | Value       | Призначення            |
|-------------------------|-------------|------------------------|
| `--iprm-font`           | `'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif` | Base font stack |
| `--iprm-dark`           | `#1a1a2e`   | Dark text, headings    |
| `--iprm-text`           | `#333`      | Body text              |
| `--iprm-text-light`     | `#666`      | Secondary text, hints  |
| `--iprm-bg`             | `#f8f9fa`   | Page background (alt)  |
| `--iprm-white`          | `#fff`      | White background       |
| `--iprm-border`         | `#e5e7eb`   | Borders, dividers      |
| `--iprm-accent`         | `#0ea5e9`   | Accent (links, hover)  |
| `--iprm-accent-light`   | `#e0f2fe`   | Accent tint (bg icons) |
| `--iprm-radius`         | `12px`      | Large border-radius    |
| `--iprm-radius-sm`      | `8px`       | Small border-radius    |
| `--iprm-transition`     | `0.25s ease`| Default transition     |
| `--iprm-max-content`    | `1200px`    | Max content width      |
| `--iprm-card-bg`        | `#F6F7F7`   | Card background        |

### 1.2 Palette

| Swatch   | HEX       | Role           |
|----------|-----------|----------------|
| Dark     | `#1a1a2e` | Headings, hero |
| Text     | `#333333` | Body text      |
| Text Light | `#666666` | Subtitles, hints |
| Card BG  | `#F6F7F7` | Cards, blocks  |
| Border   | `#e5e7eb` | Borders, tags  |
| Accent   | `#0ea5e9` | Links, active  |
| Accent Light | `#e0f2fe` | Icon bg tint |
| Button   | `#000000` | Primary button |

### 1.3 Typography

Font: **Inter** (fallback: `system-ui, -apple-system, sans-serif`)

| Role             | Size  | Weight | Color             |
|------------------|-------|--------|-------------------|
| Hero Title       | 32px  | 700    | `--iprm-dark`     |
| Section Title    | 24px  | 700    | `--iprm-dark`     |
| Card Heading     | 18px  | 700    | `--iprm-dark`     |
| Program Heading  | 16px  | 700    | `--iprm-dark`     |
| Body Text        | 15px  | 400    | `--iprm-text`     |
| Card Text        | 14px  | 400    | `--iprm-text`     |
| Button Text      | 14px  | 600    | inherit           |
| Subtitle         | 13px  | 400    | `--iprm-text-light` |
| Tag / Small      | 12px  | 500    | `--iprm-text-light` |

---

## 2. Global Resets

```css
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: var(--iprm-font); color: var(--iprm-text); background: var(--iprm-white); line-height: 1.6; }
img  { max-width: 100%; display: block; }
a    { text-decoration: none; color: inherit; }
```

---

## 3. Components

### 3.1 Header (`.iprm-header`)

Sticky header with logo + navigation.

| Property        | Value                       |
|-----------------|-----------------------------|
| display         | `flex` column               |
| align-items     | `center`                    |
| gap             | `20px`                      |
| padding         | `8px 32px`                  |
| background      | `--iprm-white`              |
| border-bottom   | `1px solid --iprm-border`   |
| position        | `sticky`, top: 0, z-index: 100 |

**`.iprm-header__top`** - flex row, centered, `position: relative`, full width.

**`.iprm-header__ds-link`** - absolute right, accent border badge (11px/500).

#### Logo (`.iprm-logo`)

```
display: flex; align-items: center; gap: 12px;
```

**`.iprm-logo__icon`** - SVG logo image, `width: 240px`, `height: auto`, `flex-shrink: 0`.

#### Navigation (`.iprm-nav`)

```
display: flex; gap: 32px; list-style: none;
```

Links: `15px / 500`, color `--iprm-text`, hover `--iprm-accent`.
Active: `.iprm-nav--active` color `--iprm-accent`.

---

### 3.2 Hero (`.iprm-hero`)

Dark full-width block with gradient background.

**Wrapper `.iprm-hero-wrap`:**
- `background: --iprm-card-bg`
- `padding: 24px 32px`

**Container `.iprm-hero`:**

| Property        | Value                              |
|-----------------|------------------------------------|
| position        | `relative`                         |
| height          | `420px` (`.iprm-hero--tall`: 480px)|
| max-width       | `--iprm-max-content` (1200px)      |
| margin          | `0 auto`                           |
| border-radius   | `--iprm-radius` (12px)             |
| background      | `--iprm-dark`                      |
| overflow        | `hidden`                           |

**Background `.iprm-hero__bg`:**
- `linear-gradient(135deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%)`, opacity 0.9
- `::after` - radial accent glow overlays

**Content `.iprm-hero__content`:**
- z-index 2, centered flex column, padding `40px`, white text

**Title `.iprm-hero__title`:** `24px / 700`, line-height 1.25, max-width 520px.
**Subtitle `.iprm-hero__subtitle`:** `13px`, max-width 480px, opacity 0.8.

**Price badge `.iprm-hero__price`:**

| Property      | Value                    |
|---------------|--------------------------|
| padding       | `4px 16px`               |
| font-size     | `14px`                   |
| font-weight   | `600`                    |
| color         | `--iprm-text`            |
| background    | `--iprm-white`           |
| border-radius | `10px`                   |

**Navigation dots `.iprm-hero__nav`:**
- Absolute bottom center (bottom: 24px)
- Arrows: no bg/border, white 60% opacity, 24px font
- Dots: 10x10px circles, transparent bg, 1.5px white 60% border
- Active dot: `.iprm-hero__dot--active` - filled white

---

### 3.3 Buttons (`.iprm-btn`)

Base styles for all buttons:

| Property      | Value               |
|---------------|---------------------|
| display       | `inline-flex`       |
| align-items   | `center`            |
| gap           | `8px`               |
| padding       | `4px 18px`          |
| font-size     | `14px`              |
| font-weight   | `600`               |
| border-radius | `10px`              |
| border        | `none`              |
| cursor        | `pointer`           |
| transition    | `--iprm-transition` |

**Variants:**

| Class               | Background | Color         | Hover BG | Notes            |
|---------------------|------------|---------------|----------|------------------|
| `.iprm-btn--primary`| `#000`     | `--iprm-white`| `#222`   | Default button   |
| `.iprm-btn--outline`| `#000`     | `--iprm-white`| `#222`   | On dark hero bg  |
| `.iprm-btn--sm`     | -          | -             | -        | `3px 14px`, 13px |

**Arrow `.iprm-btn__arrow`:** `font-size: 16px`, arrow character `&#x2197;`.

### 3.4 Tags (`.iprm-tag`)

| Property      | Value                     |
|---------------|---------------------------|
| padding       | `4px 12px`                |
| font-size     | `12px`                    |
| font-weight   | `500`                     |
| color         | `--iprm-text`             |
| background    | `--iprm-white`            |
| border        | `1px solid --iprm-border` |
| border-radius | `10px`                    |

---

### 3.5 Sections (`.iprm-section`)

| Property   | Value             |
|------------|-------------------|
| padding    | `32px 32px`       |

**`.iprm-section--alt`:** background `--iprm-bg`.
**`.iprm-section__inner`:** max-width `--iprm-max-content`, centered.
**`.iprm-section__title`:** `24px / 700`, color `--iprm-dark`.
**`.iprm-section__subtitle`:** `15px`, color `--iprm-text-light`.
**`.iprm-section__cta`:** flex centered, margin-top 18px.

---

### 3.6 Icon Cards (`.iprm-cards` / `.iprm-card`)

Grid 3 columns, gap 24px.

**Card `.iprm-card`:**

| Property      | Value                          |
|---------------|--------------------------------|
| text-align    | `center`                       |
| background    | `--iprm-card-bg`               |
| border        | `1px solid --iprm-card-bg`     |
| border-radius | `4%`                           |
| padding       | `24px`                         |

**`.iprm-card--left`:** text-align left, icon aligned left.

**Icon `.iprm-card__icon`:** `80x80px`, centered, bg `--iprm-accent-light`, dashed border, radius `--iprm-radius-sm`.
**Text `.iprm-card__text`:** `14px`, line-height 1.6, color `--iprm-text`.

---

### 3.7 Photo Cards (`.iprm-photo-cards` / `.iprm-photo-card`)

Grid 3 columns, gap 24px.

**Card `.iprm-photo-card`:**

| Property      | Value                      |
|---------------|----------------------------|
| background    | `--iprm-card-bg`           |
| border        | `1px solid --iprm-card-bg` |
| border-radius | `4%`                       |
| overflow      | `hidden`                   |
| padding       | `16px`                     |

**Image `.iprm-photo-card__image`:** `aspect-ratio: 1/1`, gradient placeholder, dashed border, radius `--iprm-radius-sm`.
**Title `.iprm-photo-card__title`:** `14px`, line-height 1.5, margin-bottom 12px.

---

### 3.8 Course Cards (`.iprm-course-cards` / `.iprm-course-card`)

Grid 3 columns, gap 24px.

**Card `.iprm-course-card`:**

| Property      | Value                      |
|---------------|----------------------------|
| background    | `--iprm-card-bg`           |
| border        | `1px solid --iprm-card-bg` |
| border-radius | `4%`                       |
| padding       | `16px`                     |

**Image `.iprm-course-card__image`:** `aspect-ratio: 4/3`, gradient placeholder, dashed border, radius `--iprm-radius-sm`, margin-bottom 12px.
**Title `.iprm-course-card__title`:** `14px / 600`, line-height 1.5, margin-bottom 12px.
**Tags `.iprm-course-card__tags`:** flex wrap, gap 6px (uses `.iprm-tag`).

---

### 3.9 Courses Grid - Home (`.iprm-courses`)

Masonry-style 2-column grid for homepage.

```
grid-template-columns: 1fr 1fr;
grid-template-rows: 2fr 1fr auto;
gap: 12px;
```

**Item `.iprm-courses__item`:**

| Property      | Value                      |
|---------------|----------------------------|
| display       | `flex`, gap 16px           |
| background    | `--iprm-card-bg`           |
| border        | `1px solid --iprm-card-bg` |
| border-radius | `4%`                       |
| padding       | `12px 16px`                |

**Modifiers:**
- `--col` - flex column, icon 144x144px
- `--tall` - spans 2 grid rows
- `--icon-abs` - icon absolute bottom-right
- `--full` - spans full width

**Icon `.iprm-courses__icon`:** `96x96px` (sm: 32x32), bg `--iprm-accent-light`, dashed border.
**Text `.iprm-courses__text`:** `14px`, `strong` block 15px dark.

---

### 3.10 Target Grid (`.iprm-target-grid`)

2-column grid, gap 12px.

**Card `.iprm-target-card`:**

| Property      | Value                      |
|---------------|----------------------------|
| background    | `--iprm-card-bg`           |
| border        | `1px solid --iprm-card-bg` |
| border-radius | `4%`                       |
| padding       | `20px 24px`                |

**`.iprm-target-card--full`:** `grid-column: 1 / -1` (spans both columns).
**Text:** `14px`, line-height 1.6, color `--iprm-text`.

---

### 3.11 Trainer (`.iprm-trainer`)

Flex row, gap 24px, card-style background.

| Property      | Value                      |
|---------------|----------------------------|
| display       | `flex`, gap 24px           |
| background    | `--iprm-card-bg`           |
| border        | `1px solid --iprm-card-bg` |
| border-radius | `4%`                       |
| padding       | `24px`                     |

**Photo `.iprm-trainer__photo`:** `180x220px`, gradient placeholder, dashed border, radius `--iprm-radius-sm`.
**Name `.iprm-trainer__name`:** `18px / 700`, color `--iprm-dark`.
**Role `.iprm-trainer__role`:** `14px`, color `--iprm-text-light`.
**Description `.iprm-trainer__desc`:** `14px`, line-height 1.6, color `--iprm-text`.

---

### 3.12 Program (`.iprm-program`)

Stacked blocks, flex column, gap 12px.

**Block `.iprm-program__block`:**

| Property      | Value                      |
|---------------|----------------------------|
| background    | `--iprm-card-bg`           |
| border        | `1px solid --iprm-card-bg` |
| border-radius | `4%`                       |
| padding       | `24px`                     |

**Heading `.iprm-program__heading`:** `16px / 700`, color `--iprm-dark`.
**List `.iprm-program__list`:** no list-style, middot (`\00B7`) pseudo-bullets, items `14px`, line-height 1.6, padding 4px 0.

---

### 3.13 History (`.iprm-history__text`)

| Property   | Value           |
|------------|-----------------|
| font-size  | `15px`          |
| line-height| `1.75`          |
| max-width  | `900px`         |

List: `disc` style, padding-left 24px, items 15px.

---

### 3.14 Footer (`.iprm-footer`)

| Property      | Value                     |
|---------------|---------------------------|
| border-top    | `1px solid --iprm-border` |
| padding       | `24px 32px`               |

**Inner `.iprm-footer__inner`:** max-width `--iprm-max-content`, flex row, space-between.
**Copyright `.iprm-footer__copy`:** `13px`, color `--iprm-text-light`.
**Logo `.iprm-footer__logo`:** flex row, gap 10px. Uses `.iprm-logo__icon` (SVG 240px).

**Socials `.iprm-footer__socials`:** flex, gap 10px.
**Social icon `.iprm-footer__social-icon`:** `32x32px`, img fills container with dark-grey filter:
```css
filter: brightness(0) saturate(100%) invert(30%) sepia(0%) saturate(0%) hue-rotate(0deg) brightness(90%);
```

**Phone `.iprm-footer__phone`:** `14px / 500`, color `--iprm-text`.

---

## 4. Responsive Breakpoints

### `@media (max-width: 768px)`

| Component          | Change                              |
|--------------------|-------------------------------------|
| `.iprm-header`     | padding `12px 16px`, gap 12px       |
| `.iprm-nav`        | gap 20px, flex-wrap, centered       |
| `.iprm-hero`       | height auto, min-height 320px       |
| `.iprm-hero__content` | padding `48px 20px 60px`         |
| `.iprm-section`    | padding `20px 16px`                 |
| `.iprm-section__title` | 20px                            |
| `.iprm-cards`      | 1 column, gap 32px                  |
| `.iprm-photo-cards`| 1 column, gap 24px                  |
| `.iprm-course-cards`| 1 column, gap 24px                 |
| `.iprm-courses`    | 1 column, auto rows                 |
| `.iprm-target-grid`| 1 column                            |
| `.iprm-trainer`    | column direction, photo 100% / 200h |
| `.iprm-footer__inner` | column, gap 16px, centered       |

### `@media (max-width: 480px)`

| Component              | Change   |
|------------------------|----------|
| `.iprm-hero__title`    | 20px     |
| `.iprm-hero__subtitle` | 14px     |
| `.iprm-courses__icon`  | 60x60px  |

---

## 5. Common Card Pattern

All card-type components share the same visual base:

```
background:    var(--iprm-card-bg)   /* #F6F7F7 */
border:        1px solid var(--iprm-card-bg)
border-radius: 4%
```

Components using this pattern: `.iprm-card`, `.iprm-photo-card`, `.iprm-course-card`, `.iprm-courses__item`, `.iprm-target-card`, `.iprm-trainer`, `.iprm-program__block`.

---

## 6. File Structure

| File              | Content                                     |
|-------------------|---------------------------------------------|
| `common.css`      | Variables, resets, header, hero, buttons, sections, cards, photo-cards, history, target-grid, trainer, program, footer, responsive |
| `page-home.css`   | Courses masonry grid (homepage)             |
| `page-courses.css`| Course cards grid, tags                     |
| `page-404.css`    | 404 page layout and responsive              |

---

## 7. Assets

| Asset                                  | Usage              |
|----------------------------------------|---------------------|
| `/static/svg/IPRM-logo-complex.svg`   | Header + footer logo |
| `/static/svg/social/facebook.svg`      | Footer social icon  |
| `/static/svg/social/instagram.svg`     | Footer social icon  |
