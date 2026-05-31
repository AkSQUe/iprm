# Деплой та сервер

## Сервер (VPS)

| Параметр | Значення |
|----------|----------|
| Хост | `173.242.58.186` |
| Користувач | `root` |
| SSH-ключ | `keys/iprm-key` |
| Шлях до проекту | `/var/www/iprm/` |
| Systemd-сервіс | `iprm` |
| WSGI-сервер | gunicorn |

### Підключення до сервера

```bash
ssh -i keys/iprm-key root@173.242.58.186
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
| `VPS_HOST` | `173.242.58.186` |
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
