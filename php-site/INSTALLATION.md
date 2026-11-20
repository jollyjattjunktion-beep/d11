# D11 PHP installer — deployment guide

This package is the separate PHP + MySQL application in `php-site/`. It does not install, migrate, or connect to the Python D11 PostgreSQL database.

## Hosting requirements

- PHP 8.1 or newer (PHP 8.3 is used in CI).
- PHP extensions: PDO, PDO MySQL, JSON. Enable mbstring when available for full Unicode slug handling.
- MySQL 8.0 or MariaDB 10.4+ with InnoDB and utf8mb4 support.
- HTTPS enabled for the domain.
- Ability to set the website document root to the package's `public/` directory.
- Writable `config/` and `storage/` directories, which must remain outside the public document root.

## Install from the GitHub Actions ZIP

1. Open the repository's Actions page and select the latest successful **D11 PHP checks** run for branch `php/d11-complete-engine`.
2. Download the `d11-php-installer` artifact and extract it on the hosting account.
3. Configure the domain's document root to the extracted package's `public/` directory. Do not expose the package root, `app/`, `config/`, `database/`, or `storage/` directly to the web.
4. In the hosting control panel, create a brand-new, empty MySQL database and a dedicated database user. Grant that user privileges on this database only.
5. Make `config/` and `storage/` writable by the PHP process. Keep the directories themselves outside the public document root.
6. Visit `https://your-domain.example/install/`.
7. Enter the MySQL connection details, the full HTTPS website URL, and the first administrator account. Use a unique administrator password of at least 12 characters.
8. After the installer reports success, open `/admin/login/` and sign in.
9. Confirm that `config/config.php` and `storage/installed.lock` exist. The installer refuses to run again once either file exists.
10. Keep a private backup of the MySQL database and the private config file. Never commit either file to GitHub.

## Important database safety

- The installer refuses any database that already contains tables. Use a new empty database.
- Do not use PostgreSQL credentials or the production D11 database.
- Do not delete the installer lock to attempt a reinstall on an existing database.
- For a fresh reinstall, provision a separate empty database and a clean application directory, then follow the steps again.
- Schema migrations are additive/versioned; nevertheless, back up the PHP MySQL database before future upgrades.

## Shared-hosting document-root limitation

The application expects the domain document root to point to `public/`. If the hosting provider only permits a fixed `public_html/` document root and does not allow changing it (or setting a symlink/alias), do not upload the whole package into `public_html/` as-is. That would expose private application files or break relative paths. Ask the host to set the document root to `public/` before installation.

## What this PHP package currently includes

The PHP branch contains the importer foundation, admin interface, additive schema migration, TeamGeneration-normalised-data sync service, AI11 squad enrichment service, historical-statistics and match-intelligence services, and the initial format-matched prediction service.

It is not yet full Python D11 feature parity. Automatic TeamGeneration/AI11 URL adapters, CREX/Cricbuzz provider adapters, all optimizer strategies, captain/vice-captain portfolio selection, player lock/rotation UI, complete public live-score/scorecard/commentary APIs, and golden-output parity tests remain separate implementation gates. Do not market this package as a complete replacement for the Python engine until those gates are implemented and tested.
