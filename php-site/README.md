# D11 PHP Cricket Platform

A separate PHP + MySQL cricket website package. It does not connect to or modify the existing Python D11 application or its PostgreSQL production database.

## InfinityFree installation (recommended package layout)

1. In InfinityFree, create a **new, empty MySQL database** and database user in the control panel. Shared hosting normally does not let an installer create database users.
2. Download the GitHub Actions artifact named `d11-php-infinityfree` and extract the artifact wrapper ZIP once. Inside it is `d11-php-infinityfree.zip`; extract that ZIP on your computer.
3. Upload **the contents** of that inner ZIP directly into `htdocs` using the hosting File Manager or FTP. Do not upload only the `public` folder. The package is flattened for shared hosting: `index.php`, `install/`, `admin/`, `app/`, `config/`, `database/` and `storage/` will sit inside `htdocs`.
4. Confirm the package `.htaccess` is present in `htdocs`. It protects private directories and routes clean URLs to the PHP front controller. If the host has disabled Apache rewrite support, ask the host to enable `mod_rewrite` and `AllowOverride`.
5. Open `https://YOUR-SUBDOMAIN/install/`.
6. Enter the MySQL values exactly as shown in the InfinityFree panel. The database name and database username are separate fields. For the account used while developing this installer, the expected examples are:
   - Host: `sql307.infinityfree.com`
   - Port: `3306`
   - Database name: `if0_43415210_d11`
   - Database username: `if0_43415210`
   - Password: the database password from the hosting panel
7. Enter the website HTTPS URL and create the administrator account. Use a unique password of at least 12 characters.
8. After installation, the installer writes `config/config.php` and `storage/installed.lock`. The lock prevents a second installation. Keep these files private and never commit them to GitHub.
9. Sign in at `https://YOUR-SUBDOMAIN/admin/login/`.

## Alternative layout

If your host supports a custom document root, point it to the package's `public/` directory and keep `app/`, `config/`, `database/` and `storage/` one level above it. The installer and public entry points detect either supported layout.

## Requirements

- PHP 8.1+ with PDO and `pdo_mysql`
- MySQL 5.7+ / MariaDB 10.4+
- HTTPS
- Apache `mod_rewrite` for clean SEO URLs

## Included routes

- `/`
- `/live-cricket-score/`
- `/series/`
- `/series/{series-slug}/`
- `/series/{series-slug}/points-table/`
- `/match/{match-slug}/`
- `/team/{team-slug}/`
- `/player/{player-slug}/`
- `/sitemap.xml`
- `/robots.txt`
- `/admin/login/`
- `/admin/dashboard/`

## Important limitations

This is an installable PHP foundation, not yet the full Cricbuzz-feature replacement. The public pages, initial admin dashboard, normalized import service and core database schema are included. Full provider-specific series discovery, live ball-by-ball feeds, scorecard tabs, player statistics, news publishing and advertising integrations are future development work.

InfinityFree free hosting does not provide persistent workers or normal scheduled cron execution. Use manual admin imports for the demo; genuinely automatic live scores require a permitted external data service or a host with scheduled background execution.

Only use cricket data sources whose terms permit collection and republication. The existing Python/PostgreSQL production system remains separate and untouched.
