# D11 PHP Cricket Platform

Separate lightweight PHP + MySQL application. The Python D11 application and production PostgreSQL database are not part of this package.

## Hosting / installation
- PHP 8.1+ with PDO and pdo_mysql
- MySQL 5.7+ / MariaDB 10.4+
- Apache with mod_rewrite and AllowOverride enabled
- HTTPS recommended

Create an empty MySQL database and user in the hosting control panel; shared hosts generally do not allow PHP to create databases or database users automatically. Upload the application, point the domain document root to `php-site/public/` where possible, and visit `/install/`. The installer creates tables, the first administrator, configuration and a lock file. It refuses to run again after successful installation.

If the hosting provider does not allow a custom document root, keep `app/`, `config/`, `database/` and `storage/` above `public_html/`; put only the contents of `public/` inside `public_html/`. Update the bootstrap include path in the public entry points to the actual private application root. Never put database credentials or the schema directory inside the public web root.

## SEO routes
- `/`
- `/live-cricket-score/`
- `/series/`
- `/series/{series-slug}/`
- `/series/{series-slug}/points-table/`
- `/match/{match-slug}/`
- `/team/{team-slug}/`
- `/player/{player-slug}/`
- `/sitemap.xml` (standalone dynamic XML endpoint)
- `/robots.txt` (dynamic robots policy)

The sitemap lists the homepage, live-score page, series, points-table pages and match pages. It is generated independently by `public/sitemap.php` and does not require the front controller.

## Important
- The existing installed MySQL database must not be reinstalled or dropped. This branch changes application files only; it does not run SQL against any database.
- Keep production Python/PostgreSQL untouched.
- Data adapters are a later step and must use sources whose terms permit collection and republication.
