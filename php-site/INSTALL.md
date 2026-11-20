# D11 PHP installation

This is a separate PHP/MySQL implementation. It does not connect to or migrate the Python/PostgreSQL production application.

## Hosting requirements

- PHP 8.1 or newer (PHP 8.3 recommended)
- PDO and PDO MySQL extensions
- MySQL 8.0 or MariaDB 10.4+
- Apache with `mod_rewrite` and `.htaccess` support, or equivalent rewrite rules
- HTTPS enabled for the domain
- Writable `config/` and `storage/` directories during installation

## Directory layout

The recommended domain document root is **`php-site/public/`**. Keep `app/`, `config/`, `database/`, and `storage/` outside the public web root.

Do not expose `config/config.php`, database migrations, logs, or application source files to web requests. The included `public/.htaccess` contains portable rewrite and deny rules for shared hosting.

## Install steps

1. Create a **new, empty MySQL database** and a dedicated database user in DirectAdmin/cPanel.
2. Grant that user all privileges on only that database.
3. Upload the complete `php-site/` directory to your account.
4. Point the domain document root to `php-site/public/`.
5. Ensure PHP can write to `config/` and `storage/` during installation. Use the narrowest permissions supported by your host; do not make the entire project world-writable.
6. Enable HTTPS.
7. Open `https://your-domain.example/install/`.
8. Enter the database host, port, database name, username, password, website HTTPS URL, and initial administrator account.
9. After the success screen, verify the installer is locked and open the website.
10. Remove or rename `public/install/` after confirming installation. Keep `storage/installed.lock`.

## Installation behaviour

- Checks PHP version, required extensions, schema files and directory permissions.
- Uses the migration runner's SQL-aware parser for the base schema.
- Records versioned migrations in `d11_schema_migrations`.
- Hashes the initial administrator password with PHP's password hashing.
- Writes configuration to `config/config.php` and the lock to `storage/installed.lock`.
- Does not drop, truncate, or reset tables.
- Requires an empty database and refuses to adopt a database that already contains an administrator.

## If the host only permits `public_html`

The recommended setup requires the domain document root to point at `php-site/public/`. Some shared hosts do not permit changing the document root. Do not work around this by making the whole project publicly accessible. Confirm whether the host permits a custom document root or supports placing private application folders above `public_html` before installing.

## Scope warning

The installer creates the PHP schema and initial administrator account. It does **not** mean the PHP application has full feature parity with Python D11. Prediction, optimizer, strategy, importer, admin, public-page and regression work remains in progress. Do not use this branch as a production replacement.
