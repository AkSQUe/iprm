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

Після `flask db upgrade` виконується `flask rbac sync`: він додає нові права з коду й створює відсутні системні ролі, не чіпаючи наявних налаштувань матриці.

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

Хости зовнішніх апстрімів **обов'язково** зберігаються у змінних (`set $...`), а не
пишуться буквально в `proxy_pass` -- див. попередження нижче.

```nginx
# --- Google Analytics first-party proxy ---
resolver 127.0.0.53 1.1.1.1 8.8.8.8 valid=300s;
resolver_timeout 5s;
set $gtm_upstream www.googletagmanager.com;
set $ga_upstream www.google-analytics.com;

# Лоадер gtag.js: /ngx-i/loader.js?id=... -> googletagmanager
location = /ngx-i/loader.js {
    rewrite ^ /gtag/js break;
    proxy_pass https://$gtm_upstream;
    proxy_set_header Host www.googletagmanager.com;
    proxy_ssl_server_name on;
    proxy_ssl_name www.googletagmanager.com;
    proxy_set_header Accept-Encoding "";
    expires 15m;
}
# Маяки збору: /ngx-i/g/collect -> google-analytics
location /ngx-i/g/ {
    rewrite ^/ngx-i/g/(.*)$ /g/$1 break;
    proxy_pass https://$ga_upstream;
    proxy_set_header Host www.google-analytics.com;
    proxy_ssl_server_name on;
    proxy_ssl_name www.google-analytics.com;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    add_header Cache-Control "no-store" always;
}
```

Застосувати: вставити блоки в конфіг сайту, далі `nginx -t && systemctl reload nginx`.

> **НЕ пишіть хост буквально в `proxy_pass`.** З буквальним хостом nginx резолвить
> DNS **на старті** і відмовляється стартувати з `[emerg] host not found in
> upstream`, якщо DNS у ту мить недоступний. Саме так сайт ліг 29.07.2026: нічний
> `apt-daily-upgrade` перезапустив systemd-resolved і nginx одночасно, nginx впав і
> не піднявся сам. Зі змінною резолв відбувається на кожен запит, тож збій DNS дає
> 502 лише на `/ngx-i/`, а не кладе весь сайт.
>
> Через змінну nginx **не** підставляє URI автоматично і не додає query-рядок --
> тому префікси переписуються через `rewrite ... break` (він зберігає args сам).
>
> Додатково стоїть drop-in `/etc/systemd/system/nginx.service.d/restart.conf`
> (`Restart=on-failure`, `RestartSec=10s`, `StartLimitBurst=10`) -- штатний юніт
> nginx не має політики рестарту взагалі.

**Порядок:** додайте nginx-локації **перед** деплоєм коду (без коду вони просто
не використовуються), інакше буде вікно, коли `/ngx-i/loader.js` віддаватиме 404.

**Перевірка:** `curl -sI https://plasma-regen.com/ngx-i/loader.js?id=G-T2LHJ436ZG`
-> `200` і `content-type: application/javascript`.

**Обмеження (geo):** через проксі Google бачить IP сервера, тож геолокація
користувачів може показуватись як локація сервера (Київ). Кількість візитів і
події відновлюються коректно. Для точного geo потрібен server-side GTM
(окремий сервіс) -- виходить за межі цього проксі.

## PostHog -- first-party проксі (nginx)

Той самий прийом, інший вендор і власний префікс `/ngx-e/`. Локації живуть у
[deploy/nginx/snippets/iprm-app.conf](../deploy/nginx/snippets/iprm-app.conf)
поруч із GA-шними, тож окремо їх вставляти не треба -- досить `deploy/apply.sh`.

Три відмінності від GA-проксі, кожна з яких при недогляді дає тиху відмову:

1. **Апстрімів два, локацій три.** PostHog віддає статику і ремоут-конфіг з
   `eu-assets.i.posthog.com`, а все інше -- з `eu.i.posthog.com`. Без окремої
   `/ngx-e/array/` події йтимуть, але SDK не отримає конфіг і лишиться без
   запису сесій -- помітно не одразу.
2. **`Host` обов'язковий на кожній локації.** Без нього PostHog віддає 401.
3. **`client_max_body_size 64m`** на api-локації. Глобальні 25m у сніпеті
   розраховані на завантаження медіа; батчі записів сесій більші й
   обрізались би з 413.

Застереження про `set $...` замість буквального хосту в `proxy_pass` діє тут
так само -- див. попередження вище.

**Перевірка:** `curl -sI https://<домен>/ngx-e/static/array.js` -> `200` і
`content-type: application/javascript`.

**Гео працює**, і на відміну від GA-проксі -- коректно: проксі прокидає
`X-Forwarded-For`, а PostHog визначає локацію за ним.

`anonymize_ips: true` у проєкті цьому НЕ заважає, хоч назва й натякає на
протилежне: PostHog резолвить місто ДО того, як відкинути IP. Тобто ви маєте
і геолокацію, і не зберігаєте адреси відвідувачів -- вимикати прапорець не
треба. Перевірено на живих даних 23.08.2026: Київ, Харків, Одеса, Дніпро,
Тернопіль, Хмельницький.

Докладніше -- [docs/integrations/posthog.md](integrations/posthog.md).
