# D11 PHP hosting deployment

The workflow `.github/workflows/deploy-php-infinityfree.yml` deploys the PHP app from branch `php/cricket-importer` to the existing InfinityFree-style FTP hosting account.

## Required GitHub Actions secrets

In GitHub, open **Settings → Secrets and variables → Actions → New repository secret** and add:

- `FTP_HOST`: FTP hostname shown in the hosting account (not the website URL).
- `FTP_USERNAME`: FTP username shown in the hosting account.
- `FTP_PASSWORD`: FTP password shown in the hosting account.
- `FTP_SERVER_DIR`: `/htdocs/` if that is the FTP-visible website directory for this account.

Never commit FTP credentials or put them in PHP source files.

## What the workflow deploys

- `php-site/public/` contents → the configured document root (for example `/htdocs/`).
- `php-site/app/` → `/htdocs/app/`.

The workflow deliberately does not use an FTP delete/mirror-delete option. It excludes `.htaccess` and public uploads, and does not deploy `config/`, `storage/`, `database/`, `migrations/`, tests, or the Python D11 application. This protects the installed MySQL configuration, installation lock, uploaded media, and existing rewrite rules.

## Trigger

A push to `php/cricket-importer` that changes `php-site/app/**` or `php-site/public/**` starts deployment automatically. A manual run is also available under **Actions → Deploy D11 PHP to InfinityFree → Run workflow**.

## First-run checklist

1. Add all four Actions secrets.
2. Confirm `FTP_SERVER_DIR` is the actual directory that currently contains the live site's `index.php` and `admin/` folder.
3. Push a small PHP app change to `php/cricket-importer`.
4. Check the Actions run log for success.
5. Open the website and test the homepage and `/admin/importer/`.

This workflow does not run SQL, run the installer, or change MySQL records. The first run should be monitored. If the hosting provider requires FTPS or a non-default port, adapt the connection settings to the exact FTP details shown in its control panel.
