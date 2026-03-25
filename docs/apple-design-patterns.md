# Apple.com Design Implementation Patterns
## Actionable CSS and HTML Reference (2025-2026)

Compiled from reverse-engineering apple.com, developer documentation, and community analysis.

---

## 1. Color System

### Core Palette (extracted from apple.com)

```css
:root {
  /* ---- Text ---- */
  --color-text-primary:    #1d1d1f;   /* "Shark" - primary headings, body */
  --color-text-secondary:  #424245;   /* secondary body text */
  --color-text-tertiary:   #6e6e73;   /* captions, metadata */
  --color-text-muted:      #86868b;   /* footnotes, disabled */

  /* ---- Backgrounds ---- */
  --color-bg-primary:      #ffffff;   /* white sections */
  --color-bg-secondary:    #f5f5f7;   /* "Athens Gray" - alternating light sections */
  --color-bg-dark:         #000000;   /* dark hero sections */
  --color-bg-dark-alt:     #1d1d1f;   /* dark card/section variant */
  --color-bg-elevated:     #fbfbfd;   /* elevated surfaces */

  /* ---- Accent / Interactive ---- */
  --color-link:            #0066cc;   /* "Science Blue" - text links */
  --color-link-hover:      #0077ed;   /* link hover state */
  --color-cta-primary:     #0071e3;   /* primary CTA background */
  --color-cta-primary-hover: #0077ed; /* primary CTA hover */
  --color-cta-text:        #ffffff;   /* CTA text on blue */

  /* ---- Semantic ---- */
  --color-separator:       #d2d2d7;   /* dividers and borders */
  --color-separator-light: #e8e8ed;   /* subtle dividers */

  /* ---- Dark section text ---- */
  --color-text-on-dark:        #f5f5f7;
  --color-text-on-dark-muted:  #86868b;
  --color-link-on-dark:        #2997ff;  /* links on dark backgrounds */
}
```

### Dark / Light Alternating Sections

Apple alternates between `#ffffff`, `#f5f5f7`, and `#000000` backgrounds. The pattern is NOT random -- it follows a rhythm:

```css
/* Light section */
.section-light {
  background-color: #f5f5f7;
  color: #1d1d1f;
}

/* White section */
.section-white {
  background-color: #ffffff;
  color: #1d1d1f;
}

/* Dark section */
.section-dark {
  background-color: #000000;
  color: #f5f5f7;
}

/* Dark sections use lighter link blue */
.section-dark a {
  color: #2997ff;
}

/* Light sections use standard link blue */
.section-light a,
.section-white a {
  color: #0066cc;
}
```

### Modern light-dark() usage (2025+)

```css
:root {
  color-scheme: light dark;
}

body {
  background-color: light-dark(#ffffff, #000000);
  color: light-dark(#1d1d1f, #f5f5f7);
}

a {
  color: light-dark(#0066cc, #2997ff);
}
```

---

## 2. Typography

### Font Stack

```css
body {
  /* Apple uses SF Pro on apple.com via @font-face.
     For non-Apple projects, use the system font stack: */
  font-family:
    -apple-system,
    BlinkMacSystemFont,
    "SF Pro Text",
    "SF Pro Display",
    "Helvetica Neue",
    "Helvetica",
    "Arial",
    sans-serif;

  font-size: 17px;          /* base size on apple.com */
  line-height: 1.47059;     /* Apple's precise line-height */
  letter-spacing: -0.022em; /* slight negative tracking */
  font-weight: 400;
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
}
```

### Typography Scale (observed from apple.com)

```css
/* Hero / Display headings */
.headline-hero {
  font-size: clamp(40px, 7vw, 96px);
  line-height: 1.05;
  font-weight: 700;
  letter-spacing: -0.015em;
}

/* Section headline (large) */
.headline-section {
  font-size: clamp(32px, 5vw, 64px);
  line-height: 1.0625;
  font-weight: 700;
  letter-spacing: -0.009em;
}

/* Section headline (medium) */
.headline-medium {
  font-size: clamp(28px, 4vw, 48px);
  line-height: 1.08349;
  font-weight: 600;
  letter-spacing: -0.003em;
}

/* Subheadline / intro text */
.subheadline {
  font-size: clamp(19px, 2.5vw, 28px);
  line-height: 1.28577;
  font-weight: 400;
  letter-spacing: 0.007em;
  color: #6e6e73;
}

/* Body copy */
.body-text {
  font-size: 17px;
  line-height: 1.47059;
  font-weight: 400;
  letter-spacing: -0.022em;
}

/* Caption / footnote */
.caption {
  font-size: 12px;
  line-height: 1.33337;
  font-weight: 400;
  letter-spacing: -0.01em;
  color: #6e6e73;
}

/* Link text ("Learn more >") */
.cta-link {
  font-size: 17px;
  line-height: 1.47059;
  font-weight: 400;
  color: #0066cc;
}

.cta-link:hover {
  text-decoration: underline;
}

/* Chevron after link */
.cta-link::after {
  content: "\00A0\203A"; /* non-breaking space + single right angle */
}
```

### Font Loading Strategy

```css
@font-face {
  font-family: "SF Pro Display";
  src: url("/fonts/sf-pro-display-regular.woff2") format("woff2");
  font-weight: 400;
  font-style: normal;
  font-display: swap;           /* prevent FOIT */
  unicode-range: U+0000-00FF;   /* subset for Latin */
}

@font-face {
  font-family: "SF Pro Display";
  src: url("/fonts/sf-pro-display-semibold.woff2") format("woff2");
  font-weight: 600;
  font-style: normal;
  font-display: swap;
  unicode-range: U+0000-00FF;
}

@font-face {
  font-family: "SF Pro Display";
  src: url("/fonts/sf-pro-display-bold.woff2") format("woff2");
  font-weight: 700;
  font-style: normal;
  font-display: swap;
  unicode-range: U+0000-00FF;
}
```

Preload the most critical weight:

```html
<link rel="preload" href="/fonts/sf-pro-display-semibold.woff2"
      as="font" type="font/woff2" crossorigin>
```

---

## 3. Navigation (Sticky Glassmorphism Bar)

### HTML Structure

```html
<nav class="globalnav" data-sticky>
  <div class="globalnav-content">
    <a href="/" class="globalnav-logo" aria-label="Home">
      <!-- SVG logo -->
    </a>
    <ul class="globalnav-list">
      <li><a href="/courses">Courses</a></li>
      <li><a href="/about">About</a></li>
      <li><a href="/contact">Contact</a></li>
    </ul>
    <div class="globalnav-actions">
      <button class="globalnav-search" aria-label="Search">
        <!-- search icon SVG -->
      </button>
      <a href="/account" class="globalnav-account" aria-label="Account">
        <!-- account icon SVG -->
      </a>
    </div>
  </div>
</nav>
```

### CSS Implementation

```css
.globalnav {
  position: sticky;
  top: 0;
  z-index: 9999;
  height: 44px;
  /* Initial state: semi-transparent with blur */
  background-color: rgba(251, 251, 253, 0.8);
  -webkit-backdrop-filter: saturate(180%) blur(20px);
  backdrop-filter: saturate(180%) blur(20px);
  border-bottom: 1px solid rgba(0, 0, 0, 0.08);
  transition: background-color 0.36s cubic-bezier(0.32, 0.08, 0.24, 1),
              border-color 0.36s cubic-bezier(0.32, 0.08, 0.24, 1);
}

/* Scrolled state - more opaque */
.globalnav.is-scrolled {
  background-color: rgba(251, 251, 253, 0.92);
}

/* Dark variant for dark hero sections */
.globalnav.is-dark {
  background-color: rgba(29, 29, 31, 0.8);
  -webkit-backdrop-filter: saturate(180%) blur(20px);
  backdrop-filter: saturate(180%) blur(20px);
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
}

.globalnav-content {
  max-width: 980px;
  margin: 0 auto;
  padding: 0 22px;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.globalnav-list {
  display: flex;
  gap: 0;
  list-style: none;
}

.globalnav-list a {
  display: block;
  padding: 0 12px;
  font-size: 12px;
  line-height: 44px;
  font-weight: 400;
  letter-spacing: -0.01em;
  color: #1d1d1f;
  text-decoration: none;
  opacity: 0.8;
  transition: opacity 0.3s ease;
}

.globalnav-list a:hover {
  opacity: 1;
}

.globalnav.is-dark .globalnav-list a {
  color: #f5f5f7;
}
```

### Scroll detection (minimal JS for CSS-driven approach)

```css
/* 2025+ CSS-only approach using scroll-state queries */
.globalnav-wrapper {
  container-type: scroll-state;
  position: sticky;
  top: 0;
  z-index: 9999;
}

.globalnav-wrapper nav {
  background-color: rgba(251, 251, 253, 0.8);
  backdrop-filter: saturate(180%) blur(20px);
  transition: background-color 0.36s ease;
}

@container scroll-state(stuck: top) {
  nav {
    background-color: rgba(251, 251, 253, 0.95);
    box-shadow: 0 1px 0 rgba(0, 0, 0, 0.08);
  }
}
```

---

## 4. Buttons and CTAs

### Primary Button (filled pill)

```css
.btn-primary {
  display: inline-block;
  padding: 8px 22px;
  min-width: 28px;
  border: none;
  border-radius: 980px;   /* Apple's "infinite" pill radius */
  background-color: #0071e3;
  color: #ffffff;
  font-size: 17px;
  line-height: 1.17648;
  font-weight: 400;
  letter-spacing: -0.022em;
  text-align: center;
  text-decoration: none;
  white-space: nowrap;
  cursor: pointer;
  transition: background-color 0.3s ease;
}

.btn-primary:hover {
  background-color: #0077ed;
}

.btn-primary:active {
  background-color: #006edb;
}

/* Focus visible for accessibility */
.btn-primary:focus-visible {
  outline: 4px solid rgba(0, 125, 250, 0.6);
  outline-offset: 1px;
}
```

### Secondary Button (outlined pill)

```css
.btn-secondary {
  display: inline-block;
  padding: 8px 22px;
  border: 2px solid #0071e3;
  border-radius: 980px;
  background-color: transparent;
  color: #0071e3;
  font-size: 17px;
  line-height: 1.17648;
  font-weight: 400;
  letter-spacing: -0.022em;
  text-align: center;
  text-decoration: none;
  white-space: nowrap;
  cursor: pointer;
  transition: background-color 0.3s ease, color 0.3s ease;
}

.btn-secondary:hover {
  background-color: #0071e3;
  color: #ffffff;
}
```

### Text Link CTA ("Learn more")

```css
.cta-link {
  display: inline-block;
  font-size: 21px;
  line-height: 1.381;
  font-weight: 400;
  color: #0066cc;
  text-decoration: none;
  cursor: pointer;
}

.cta-link:hover {
  text-decoration: underline;
}

/* Right-pointing chevron */
.cta-link > .chevron {
  display: inline-block;
  margin-left: 0.3em;
  transition: transform 0.2s ease;
}

.cta-link:hover > .chevron {
  transform: translateX(4px);
}
```

### Button on Dark Background

```css
.section-dark .btn-primary {
  background-color: #ffffff;
  color: #1d1d1f;
}

.section-dark .btn-primary:hover {
  background-color: rgba(255, 255, 255, 0.85);
}

.section-dark .btn-secondary {
  border-color: #ffffff;
  color: #ffffff;
}

.section-dark .btn-secondary:hover {
  background-color: #ffffff;
  color: #1d1d1f;
}

.section-dark .cta-link {
  color: #2997ff;
}
```

### CTA Pair Layout

```css
.cta-group {
  display: flex;
  gap: 16px;
  justify-content: center;
  flex-wrap: wrap;
  margin-top: 20px;
}
```

---

## 5. Grid and Layout Patterns

### Content Widths

```css
/* Apple's observed max-widths */
.container-wide    { max-width: 1440px; margin: 0 auto; padding: 0 22px; }
.container-default { max-width: 980px;  margin: 0 auto; padding: 0 22px; }
.container-narrow  { max-width: 692px;  margin: 0 auto; padding: 0 22px; }

/* Responsive horizontal padding */
@media (max-width: 1068px) {
  .container-wide,
  .container-default,
  .container-narrow {
    padding: 0 24px;
  }
}

@media (max-width: 734px) {
  .container-wide,
  .container-default,
  .container-narrow {
    padding: 0 20px;
  }
}
```

### Section Vertical Spacing

```css
.section {
  padding: 80px 0;
}

/* Large hero sections */
.section-hero {
  padding: 120px 0;
}

/* Compact sections */
.section-compact {
  padding: 48px 0;
}

@media (max-width: 734px) {
  .section        { padding: 48px 0; }
  .section-hero   { padding: 64px 0; }
  .section-compact { padding: 32px 0; }
}
```

### Bento Grid

```css
:root {
  --bento-cols: 4;
  --bento-rows: 3;
  --bento-gap: 12px;
  --bento-radius: 18px;
}

.bento-grid {
  display: grid;
  grid-template-columns: repeat(var(--bento-cols), 1fr);
  grid-template-rows: repeat(var(--bento-rows), auto);
  gap: var(--bento-gap);
  max-width: 1200px;
  margin: 0 auto;
}

.bento-item {
  overflow: hidden;
  border-radius: var(--bento-radius);
  background-color: #f5f5f7;
  position: relative;
}

/* Featured item (2x2 span) */
.bento-item--featured {
  grid-column: span 2;
  grid-row: span 2;
}

/* Wide item */
.bento-item--wide {
  grid-column: span 2;
}

/* Tall item */
.bento-item--tall {
  grid-row: span 2;
}

/* Dark bento item */
.bento-item--dark {
  background-color: #1d1d1f;
  color: #f5f5f7;
}

/* Responsive */
@media (max-width: 1068px) {
  :root {
    --bento-cols: 2;
    --bento-gap: 10px;
    --bento-radius: 14px;
  }
}

@media (max-width: 734px) {
  :root {
    --bento-cols: 1;
  }
  .bento-item--featured,
  .bento-item--wide {
    grid-column: span 1;
  }
}
```

### Bento Item with Hover Micro-Animation

```css
.bento-item {
  transition: transform 0.3s ease-out, box-shadow 0.3s ease-out;
}

.bento-item:hover {
  transform: scale(1.02);
  box-shadow: 0 8px 30px rgba(0, 0, 0, 0.12);
}

/* Content inside bento items */
.bento-item__content {
  padding: 30px;
  display: flex;
  flex-direction: column;
  height: 100%;
}

.bento-item__title {
  font-size: clamp(21px, 2.5vw, 28px);
  font-weight: 600;
  line-height: 1.14286;
  letter-spacing: 0.007em;
  margin-bottom: 8px;
}

.bento-item__description {
  font-size: 14px;
  line-height: 1.42859;
  color: #6e6e73;
}
```

---

## 6. Scroll Animations

### CSS-Only Scroll-Driven Animations (modern browsers, no JS)

```css
/* Fade-up on scroll into view */
@keyframes fade-up {
  from {
    opacity: 0;
    transform: translateY(30px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

/* Apply to elements */
@media (prefers-reduced-motion: no-preference) {
  @supports (animation-timeline: view()) {
    .animate-on-scroll {
      animation: fade-up ease both;
      animation-timeline: view();
      animation-range: entry 0% entry 100%;
    }
  }
}
```

### Scale-In on Scroll

```css
@keyframes scale-in {
  from {
    opacity: 0;
    scale: 0.92;
  }
  to {
    opacity: 1;
    scale: 1;
  }
}

@media (prefers-reduced-motion: no-preference) {
  @supports (animation-timeline: view()) {
    .animate-scale-in {
      animation: scale-in ease both;
      animation-timeline: view();
      animation-range: entry 10% entry 80%;
    }
  }
}
```

### Scroll-Triggered via Style Queries (CSS-only, persistent after trigger)

```css
/* The trigger animation sets a custom property when element enters view */
@keyframes trigger-visible {
  to {
    --is-visible: 1;
  }
}

.reveal-container {
  animation: trigger-visible steps(1) both;
  animation-timeline: view();
  animation-range: entry 20% entry 80%;
}

/* Children animate only when parent has --is-visible */
@container style(--is-visible: 1) {
  .reveal-content {
    opacity: 1;
    transform: translateY(0);
  }
}

.reveal-content {
  opacity: 0;
  transform: translateY(30px);
  transition: opacity 0.8s cubic-bezier(0.25, 0.46, 0.45, 0.94),
              transform 0.8s cubic-bezier(0.25, 0.46, 0.45, 0.94);
}
```

### JavaScript Fallback (Intersection Observer Pattern)

Apple uses a combined approach -- CSS for the animation, JS for the trigger:

```css
/* Initial hidden state */
[data-animate] {
  opacity: 0;
  transform: translateY(20px);
  transition: opacity 0.8s cubic-bezier(0.28, 0.11, 0.32, 1),
              transform 0.8s cubic-bezier(0.28, 0.11, 0.32, 1);
}

/* Revealed state */
[data-animate].is-visible {
  opacity: 1;
  transform: translateY(0);
}

/* Staggered children */
[data-animate-stagger] > * {
  opacity: 0;
  transform: translateY(20px);
  transition: opacity 0.6s cubic-bezier(0.28, 0.11, 0.32, 1),
              transform 0.6s cubic-bezier(0.28, 0.11, 0.32, 1);
}

[data-animate-stagger].is-visible > *:nth-child(1) { transition-delay: 0s; }
[data-animate-stagger].is-visible > *:nth-child(2) { transition-delay: 0.1s; }
[data-animate-stagger].is-visible > *:nth-child(3) { transition-delay: 0.2s; }
[data-animate-stagger].is-visible > *:nth-child(4) { transition-delay: 0.3s; }
[data-animate-stagger].is-visible > *:nth-child(5) { transition-delay: 0.4s; }

[data-animate-stagger].is-visible > * {
  opacity: 1;
  transform: translateY(0);
}
```

```javascript
/* Minimal Intersection Observer (Apple-style parameters) */
const observer = new IntersectionObserver(
  (entries) => {
    entries.forEach((entry) => {
      if (entry.isIntersecting) {
        entry.target.classList.add('is-visible');
        observer.unobserve(entry.target);  /* fire once */
      }
    });
  },
  {
    threshold: 0.1,       /* trigger at 10% visibility */
    rootMargin: '0px 0px -60px 0px'  /* offset from bottom */
  }
);

document.querySelectorAll('[data-animate], [data-animate-stagger]')
  .forEach((el) => observer.observe(el));
```

### Apple's Easing Functions (observed)

```css
:root {
  /* Apple commonly uses these cubic-bezier curves: */
  --ease-apple-default:  cubic-bezier(0.25, 0.1, 0.25, 1);     /* smooth default */
  --ease-apple-in-out:   cubic-bezier(0.42, 0, 0.58, 1);       /* symmetric ease */
  --ease-apple-out:      cubic-bezier(0.28, 0.11, 0.32, 1);    /* fast out, slow end */
  --ease-apple-spring:   cubic-bezier(0.32, 0.08, 0.24, 1);    /* spring-like overshoot */
  --ease-apple-bounce:   cubic-bezier(0.175, 0.885, 0.32, 1.275); /* subtle bounce */
}
```

---

## 7. Image and Media Handling

### Responsive Images with Art Direction

```html
<picture>
  <!-- Large desktop (2x retina) -->
  <source
    srcset="/images/hero-large_2x.webp 2x, /images/hero-large.webp 1x"
    media="(min-width: 1069px)"
    type="image/webp"
  >
  <!-- Medium tablet -->
  <source
    srcset="/images/hero-medium_2x.webp 2x, /images/hero-medium.webp 1x"
    media="(min-width: 735px)"
    type="image/webp"
  >
  <!-- Small mobile -->
  <source
    srcset="/images/hero-small_2x.webp 2x, /images/hero-small.webp 1x"
    type="image/webp"
  >
  <!-- Fallback -->
  <img
    src="/images/hero-large.jpg"
    alt="Descriptive alt text"
    width="2880"
    height="1300"
    loading="eager"
    decoding="async"
    fetchpriority="high"
  >
</picture>
```

### Apple's Breakpoint Approach for Images

```
Desktop:  min-width 1069px   ->  large image  (typically 2880px wide at 2x)
Tablet:   735px - 1068px     ->  medium image (typically 1488px wide at 2x)
Mobile:   0px - 734px        ->  small image  (typically 736px wide at 2x)
```

### Lazy Loading for Below-the-Fold

```html
<!-- Above the fold: eager, high priority -->
<img src="hero.webp" loading="eager" fetchpriority="high"
     width="2880" height="1300" alt="Hero" decoding="async">

<!-- Below the fold: lazy, auto priority -->
<img src="feature.webp" loading="lazy"
     width="1200" height="800" alt="Feature" decoding="async">
```

### Image Aspect Ratio Containers

```css
.media-container {
  position: relative;
  overflow: hidden;
  border-radius: 18px;
}

/* Force aspect ratio without layout shift */
.media-container--hero {
  aspect-ratio: 16 / 9;
}

.media-container--square {
  aspect-ratio: 1 / 1;
}

.media-container--portrait {
  aspect-ratio: 3 / 4;
}

.media-container img,
.media-container video {
  width: 100%;
  height: 100%;
  object-fit: cover;
}
```

### Placeholder / Skeleton Strategy

```css
.image-placeholder {
  background: linear-gradient(
    110deg,
    #f5f5f7 30%,
    #ebebed 50%,
    #f5f5f7 70%
  );
  background-size: 200% 100%;
  animation: shimmer 1.5s ease-in-out infinite;
}

@keyframes shimmer {
  from { background-position: 200% 0; }
  to   { background-position: -200% 0; }
}
```

---

## 8. Glassmorphism / Liquid Glass Effects

### Standard Glass Panel

```css
.glass-panel {
  background: rgba(255, 255, 255, 0.15);
  -webkit-backdrop-filter: blur(20px) saturate(180%);
  backdrop-filter: blur(20px) saturate(180%);
  border: 1px solid rgba(255, 255, 255, 0.18);
  border-radius: 20px;
  box-shadow:
    0 8px 32px rgba(31, 38, 135, 0.15),
    inset 0 1px 0 rgba(255, 255, 255, 0.25);
}
```

### Liquid Glass Effect (Apple 2025)

```css
.liquid-glass {
  position: relative;
  background: rgba(255, 255, 255, 0.15);
  -webkit-backdrop-filter: blur(2px) saturate(180%);
  backdrop-filter: blur(2px) saturate(180%);
  border: 1px solid rgba(255, 255, 255, 0.8);
  border-radius: 2rem;
  box-shadow:
    0 8px 32px rgba(31, 38, 135, 0.2),
    inset 0 4px 20px rgba(255, 255, 255, 0.3);
}

/* Shine / reflection pseudo-element */
.liquid-glass::after {
  content: "";
  position: absolute;
  inset: 0;
  border-radius: inherit;
  background: rgba(255, 255, 255, 0.1);
  backdrop-filter: blur(1px);
  box-shadow:
    inset -10px -8px 0 -11px rgba(255, 255, 255, 1),
    inset 0 -9px 0 -8px rgba(255, 255, 255, 1);
  opacity: 0.6;
  z-index: -1;
  filter: blur(1px) drop-shadow(10px 4px 6px rgba(0, 0, 0, 0.2)) brightness(115%);
  pointer-events: none;
}
```

---

## 9. Modern CSS Features (2025 Production-Ready)

### Container Queries

```css
.card-wrapper {
  container-type: inline-size;
  container-name: card;
}

.card {
  padding: 20px;
}

@container card (min-width: 400px) {
  .card {
    display: flex;
    gap: 20px;
    padding: 30px;
  }

  .card__image {
    flex: 0 0 40%;
  }
}

@container card (min-width: 700px) {
  .card {
    padding: 40px;
  }

  .card__title {
    font-size: 28px;
  }
}
```

### :has() Selector

```css
/* Card with image gets different layout */
.card:has(img) {
  grid-template-rows: auto 1fr;
}

/* Section after dark section has no top border */
.section-dark + .section:has(.container) {
  border-top: none;
}

/* Form field with invalid input gets error styling */
.form-group:has(:invalid) .form-label {
  color: #ff3b30;
}

/* Nav item with active link */
.nav-item:has(a[aria-current="page"]) {
  font-weight: 600;
}
```

### Scroll Snap (Horizontal Carousel)

```css
.carousel {
  display: flex;
  overflow-x: auto;
  scroll-snap-type: x mandatory;
  scroll-behavior: smooth;
  gap: 16px;
  padding: 20px;

  /* Hide scrollbar */
  scrollbar-width: none;
  -ms-overflow-style: none;
}

.carousel::-webkit-scrollbar {
  display: none;
}

.carousel-item {
  flex: 0 0 min(85vw, 380px);
  scroll-snap-align: center;
  border-radius: 18px;
  overflow: hidden;
}
```

### CSS Scroll Markers (2025+, progressive enhancement)

```css
@supports (scroll-marker-group: after) {
  .carousel {
    scroll-marker-group: after;
  }

  .carousel-item::scroll-marker {
    content: "";
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: #d2d2d7;
    border: none;
  }

  .carousel-item::scroll-marker:target-current {
    background: #1d1d1f;
  }
}
```

### Scroll-State Queries

```css
/* Style sticky header differently when stuck */
.sticky-header-wrapper {
  container-type: scroll-state;
  position: sticky;
  top: 0;
}

@container scroll-state(stuck: top) {
  .sticky-header {
    box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);
    backdrop-filter: saturate(180%) blur(20px);
    background-color: rgba(255, 255, 255, 0.9);
  }
}
```

### color-mix() for Dynamic Tints

```css
.btn:hover {
  background-color: color-mix(in srgb, var(--color-cta-primary) 85%, white);
}

.text-subtle {
  color: color-mix(in srgb, var(--color-text-primary) 60%, transparent);
}

/* Tinted backgrounds */
.section-tinted {
  background-color: color-mix(in srgb, var(--accent-color) 10%, white 90%);
}
```

### Staggered Animations with sibling-index() (2025+)

```css
@supports (animation-delay: calc(sibling-index() * 0.1s)) {
  .grid-item {
    animation: fade-up 0.6s ease-out both;
    animation-delay: calc(sibling-index() * 0.08s);
  }
}
```

---

## 10. Performance Patterns

### CSS Containment

```css
/* Below-the-fold sections */
.section:nth-of-type(n + 3) {
  contain: content;
  content-visibility: auto;
  contain-intrinsic-size: auto 600px;  /* estimated height */
}

/* Footer */
.footer {
  contain: content;
  content-visibility: auto;
  contain-intrinsic-size: auto 400px;
}

/* Individual cards in large lists */
.product-card {
  contain: layout style;
}
```

### will-change (Use Sparingly)

```css
/* Only on elements about to animate */
.about-to-animate {
  will-change: transform, opacity;
}

/* Remove after animation completes (via JS) */
.animation-complete {
  will-change: auto;
}

/* For persistent animations like the sticky nav blur: */
.globalnav {
  will-change: backdrop-filter;
}
```

### Reduce Motion Respect

```css
@media (prefers-reduced-motion: reduce) {
  *,
  *::before,
  *::after {
    animation-duration: 0.01ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.01ms !important;
    scroll-behavior: auto !important;
  }

  [data-animate] {
    opacity: 1 !important;
    transform: none !important;
  }
}
```

### Critical CSS Inlining Strategy

```html
<head>
  <!-- Critical CSS inline for above-the-fold -->
  <style>
    /* nav, hero section, first fold typography */
  </style>

  <!-- Remaining CSS loaded async -->
  <link rel="preload" href="/css/main.css" as="style"
        onload="this.onload=null;this.rel='stylesheet'">
  <noscript><link rel="stylesheet" href="/css/main.css"></noscript>
</head>
```

### Image Performance Checklist

```html
<!-- Hero image: eager load, high priority, explicit dimensions -->
<img src="hero.webp" loading="eager" fetchpriority="high"
     width="2880" height="1300" decoding="async" alt="...">

<!-- Below fold: lazy load, explicit dimensions -->
<img src="feature.webp" loading="lazy"
     width="1200" height="800" decoding="async" alt="...">
```

---

## 11. Breakpoints (Apple's Observed System)

```css
/* Apple uses these primary breakpoints: */

/* Large desktop: >= 1441px */
/* Desktop:       1069px - 1440px */
/* Tablet:        735px - 1068px */
/* Mobile:        0px - 734px */

@media only screen and (max-width: 1068px) {
  /* Tablet layout adjustments */
}

@media only screen and (max-width: 734px) {
  /* Mobile layout adjustments */
}

/* Additional intermediate breakpoints used: */
@media only screen and (max-width: 480px) {
  /* Small mobile */
}

@media only screen and (min-width: 1441px) {
  /* Large desktop enhancements */
}
```

---

## 12. Complete Section Template

Putting it all together -- a full Apple-style section:

```html
<section class="section section-light" data-animate>
  <div class="container-default">
    <div class="section-header" data-animate-stagger>
      <h2 class="headline-section">Section Title</h2>
      <p class="subheadline">Supporting text that describes the section content.</p>
    </div>

    <div class="bento-grid" data-animate-stagger>
      <div class="bento-item bento-item--featured bento-item--dark">
        <picture>
          <source srcset="feature-large.webp" media="(min-width: 1069px)" type="image/webp">
          <source srcset="feature-medium.webp" media="(min-width: 735px)" type="image/webp">
          <img src="feature-small.webp" alt="Feature" loading="lazy"
               width="960" height="640" decoding="async">
        </picture>
        <div class="bento-item__content">
          <h3 class="bento-item__title">Featured Item</h3>
          <p class="bento-item__description">Description of the feature.</p>
        </div>
      </div>
      <div class="bento-item">
        <div class="bento-item__content">
          <h3 class="bento-item__title">Item Two</h3>
          <p class="bento-item__description">Another feature.</p>
        </div>
      </div>
      <div class="bento-item">
        <div class="bento-item__content">
          <h3 class="bento-item__title">Item Three</h3>
          <p class="bento-item__description">Yet another feature.</p>
        </div>
      </div>
    </div>

    <div class="cta-group">
      <a href="/learn-more" class="btn-primary">Get Started</a>
      <a href="/details" class="btn-secondary">Learn More</a>
    </div>
  </div>
</section>
```

---

## Quick Reference Table

| Element | Key CSS Values |
|---------|---------------|
| Nav height | `44px` |
| Nav blur | `saturate(180%) blur(20px)` |
| Nav bg (light) | `rgba(251, 251, 253, 0.8)` |
| Nav bg (dark) | `rgba(29, 29, 31, 0.8)` |
| Max-width (wide) | `1440px` |
| Max-width (default) | `980px` |
| Max-width (narrow) | `692px` |
| Horizontal padding | `22px` (desktop), `24px` (tablet), `20px` (mobile) |
| Section padding | `80px 0` (desktop), `48px 0` (mobile) |
| Button radius | `980px` (pill) |
| Button padding | `8px 22px` |
| Card radius | `18px` |
| Bento gap | `12px` |
| Primary blue | `#0071e3` |
| Link blue | `#0066cc` |
| Link on dark | `#2997ff` |
| Text primary | `#1d1d1f` |
| Text muted | `#86868b` |
| Background gray | `#f5f5f7` |
| Separator | `#d2d2d7` |
| Easing (default) | `cubic-bezier(0.25, 0.1, 0.25, 1)` |
| Easing (spring) | `cubic-bezier(0.32, 0.08, 0.24, 1)` |
| Breakpoint tablet | `1068px` |
| Breakpoint mobile | `734px` |
| Font base size | `17px` |
| Font base line-height | `1.47059` |
