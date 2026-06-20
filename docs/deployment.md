# Деплой та сервер

## Сервер (VPS)

| Параметр | Значення |
|----------|----------|
| Хост | `173.242.48.194` |
| Користувач | `root` |
| SSH-ключ | `keys/iprm-key` |
| Шлях до проекту | `/var/www/iprm/` |
| Systemd-сервіс | `iprm` |
| WSGI-сервер | gunicorn |
| ОС | Ubuntu 24.04 (Python 3.12) |

> Сервер перенесено зі старого хоста `173.242.58.186` (Ubuntu 22.04) на
> `173.242.48.194` 2026-06-19. Зовнішня БД (`tnusv251.psql.tools`) спільна й не
> мігрувала. Старий хост можна вивести з експлуатації після підтвердження
> стабільності нового.

### Підключення до сервера

```bash
ssh -i keys/iprm-key root@173.242.48.194
```

### Корисні команди на сервері

```bash
# Статус сервісу
systemctl status iprm

# Перезапуск
systemctl restart iprm

# Логи
journalctl -u iprm -f

# Шлях до проекту
cd /var/www/iprm
```

## CI/CD

Деплой автоматизований через GitHub Actions (`.github/workflows/deploy.yml`):

1. **Тригер:** push у гілку `main`
2. **Rsync** файлів на VPS (виключаючи `.git`, `keys/`, `.env`, `venv/`)
3. **Перезапуск** сервісу через systemd

### Необхідні секрети GitHub

| Секрет | Опис |
|--------|------|
| `VPS_HOST` | `173.242.48.194` |
| `VPS_USER` | `root` |
| `VPS_SSH_KEY` | Вміст `keys/iprm-key` |

## Сертифікати (WeasyPrint)

Генерація PDF-сертифікатів використовує **WeasyPrint**, який потребує
системних нативних бібліотек (Pango/Cairo/GDK-PixBuf). Їх треба встановити
на VPS **один раз** (pip їх не ставить):

```bash
apt-get update
apt-get install -y libpango-1.0-0 libpangocairo-1.0-0 libgdk-pixbuf-2.0-0 libffi-dev libcairo2 libpangoft2-1.0-0
```

Якщо бібліотек немає, `import weasyprint` падає, а видача сертифіката
завершиться помилкою (інша частина застосунку працює -- імпорт лінивий).

### Сховище згенерованих PDF

- Шлях: `CERTIFICATE_FOLDER` (env), за замовчуванням `/var/www/iprm/certificates/`.
- Тека приватна (поза `app/static`), віддається лише через авторизований роут.
- **Виключена** з `rsync --delete` (`.github/workflows/deploy.yml`), тож видані
  сертифікати **переживають деплой**. У git не комітиться (`.gitignore`).
- Власник процесу gunicorn (root) має мати право запису в цю теку.

## Google Analytics -- first-party проксі (nginx)

Блокувальники відстеження (Brave, Firefox ETP, uBlock, AdGuard, DNS-блок)
ріжуть запити до `googletagmanager.com` / `google-analytics.com` за доменом,
тож частина трафіку не потрапляє в GA4. Щоб це оминути, лоадер `gtag.js` і
маяки збору (`/g/collect`) віддаються через **власний домен** (`/ngx-i/...`),
а nginx проксує їх на Google. Для блокувальників це first-party-запити.

Код застосунку вже налаштований ([partials/_analytics.html](../app/templates/partials/_analytics.html)
+ [analytics.js](../app/static/js/analytics.js)): лоадер вантажиться з
`/ngx-i/loader.js`, а `transport_url` вказує на `/ngx-i`. Залишилось додати
проксі-локації в nginx (у `server {}` сайту, **вище** за `location /`):

```nginx
# --- Google Analytics first-party proxy ---
# Лоадер gtag.js: /ngx-i/loader.js?id=... -> googletagmanager
location = /ngx-i/loader.js {
    proxy_pass https://www.googletagmanager.com/gtag/js;
    proxy_set_header Host www.googletagmanager.com;
    proxy_ssl_server_name on;
    proxy_set_header Accept-Encoding "";
    expires 15m;
}
# Маяки збору: /ngx-i/g/collect -> google-analytics
location /ngx-i/g/ {
    proxy_pass https://www.google-analytics.com/g/;
    proxy_set_header Host www.google-analytics.com;
    proxy_ssl_server_name on;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    add_header Cache-Control "no-store" always;
}
```

Застосувати: вставити блоки в конфіг сайту, далі `nginx -t && systemctl reload nginx`.

**Порядок:** додайте nginx-локації **перед** деплоєм коду (без коду вони просто
не використовуються), інакше буде вікно, коли `/ngx-i/loader.js` віддаватиме 404.

**Перевірка:** `curl -sI https://plasma-regen.com/ngx-i/loader.js?id=G-T2LHJ436ZG`
-> `200` і `content-type: application/javascript`.

**Обмеження (geo):** через проксі Google бачить IP сервера, тож геолокація
користувачів може показуватись як локація сервера (Київ). Кількість візитів і
події відновлюються коректно. Для точного geo потрібен server-side GTM
(окремий сервіс) -- виходить за межі цього проксі.
