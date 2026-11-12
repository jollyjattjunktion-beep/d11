# D11 PHP hosting deployment

The GitHub Actions workflow `.github/workflows/deploy-php-infinityfree.yml` deploys selected PHP code from branch `php/cricket-importer` to the existing InfinityFree-style FTP hosting account.

## Required GitHub Actions secrets

Open **GitHub repository → Settings → Secrets and variables → Actions → New repository secret** and add:

- `FTP_HOST`: FTP hostname shown in the hosting control panel (not the website URL).
- `FTP_USERNAME`: FTP username shown in the hosting control panel.
- `FTP_PASSWORD`: FTP password shown in the hosting control panel.
- `FTP_SERVER_DIR`: the FTP-visible directory containing the live `app/` and `admin/` folders; based on the current File Manager screenshots this is expected to be `/htdocs/`. Confirm it in the FTP account before the first run.

Never commit FTP credentials or put them in PHP source files.

## What the workflow deploys

- `php-site/app/` → `/htdocs/app/`
- `php-site/public/admin/` → `/htdocs/admin/`

The admin PHP bootstrap paths are aligned for this layout. The workflow does not use an FTP delete option, and does not upload the public homepage, `.htaccess`, `config/`, `storage/`, `database/`, `migrations/`, uploads, or the Python D11 application. It does not run SQL or the installer.

## Trigger

A push to `php/cricket-importer` that changes `php-site/app/**` or `php-site/public/admin/**` starts deployment automatically. A manual run is also available under **Actions → Deploy D11 PHP to InfinityFree → Run workflow**.

## First-run checklist

1. Add all four Actions secrets.
2. Verify the FTP directory value is the one containing the live `app/` and `admin/` folders.
3. Open **Actions** and inspect the workflow run. The first deployment should be monitored.
4. Test the homepage, admin login, dashboard, and `/admin/importer/`.

The workflow only uploads app/admin code. It does not alter MySQL data, installed configuration, installation lock, rewrite rules, uploaded media, or the separate Python/PostgreSQL production app.
