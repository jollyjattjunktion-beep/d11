# D11 PHP Cricket Platform (installation-first)

This is a separate lightweight PHP + MySQL application. It does not replace or modify the existing Python D11 application.

## Phase 1 scope
- Shared-hosting-friendly PHP 8.1+ and PDO MySQL.
- Browser installer that creates the MySQL schema and first administrator.
- Cricket data foundation: competitions, series, teams, players, venues, matches, squads, innings, scorecards, commentary, points tables, source registry, import logs and SEO metadata.
- Import-safe external IDs and manual-data protection fields.
- No fantasy engine in this phase.

## Deployment on GoogieHost
1. Create a MySQL database and database user in the hosting control panel.
2. Upload the contents of `php-site/` to a folder outside the public web root where possible.
3. Set the domain/subdomain document root to `php-site/public/`. If the host does not permit a custom document root, upload only the contents of `public/` into `public_html/` and keep `app/`, `config/`, `database/` and `storage/` outside `public_html/`; adjust the bootstrap path accordingly.
4. Open `/install/`, enter the database credentials and create the administrator.
5. After successful installation, the installer writes a lock file and refuses to run again.
6. Remove write permission from configuration and storage directories when installation is complete.

## Requirements
- PHP 8.1 or later
- PDO and pdo_mysql
- MySQL 5.7+ or MariaDB 10.4+
- HTTPS
- PHP sessions

## Safety
- Do not point this app at the production PostgreSQL database.
- Use a new, empty MySQL database for the demo.
- Never commit real database credentials.
- The importer must use licensed/authorised cricket data sources. Do not republish third-party proprietary commentary, images or protected content without permission.
