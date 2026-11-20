<?php
declare(strict_types=1);

define('D11_ROOT', dirname(__DIR__, 2));
$lockFile = D11_ROOT . '/storage/installed.lock';
$configFile = D11_ROOT . '/config/config.php';
$error = '';
$success = false;
$defaultBaseUrl = 'https://example.com';

if (is_file($lockFile) || is_file($configFile)) {
    http_response_code(403);
    exit('D11 is already installed. The installer is locked.');
}

if (session_status() !== PHP_SESSION_ACTIVE) {
    $secure = (!empty($_SERVER['HTTPS']) && $_SERVER['HTTPS'] !== 'off');
    session_set_cookie_params(['httponly' => true, 'secure' => $secure, 'samesite' => 'Strict']);
    session_start();
}
if (empty($_SESSION['d11_install_csrf'])) {
    $_SESSION['d11_install_csrf'] = bin2hex(random_bytes(32));
}

function install_h(string $value): string {
    return htmlspecialchars($value, ENT_QUOTES | ENT_SUBSTITUTE, 'UTF-8');
}

function install_requirements(): array {
    $checks = [
        'PHP 8.1 or newer' => version_compare(PHP_VERSION, '8.1.0', '>='),
        'PDO extension' => extension_loaded('pdo'),
        'PDO MySQL extension' => extension_loaded('pdo_mysql'),
        'JSON extension' => extension_loaded('json'),
        'Writable config directory' => is_dir(D11_ROOT . '/config') && is_writable(D11_ROOT . '/config'),
        'Writable storage directory' => is_dir(D11_ROOT . '/storage') && is_writable(D11_ROOT . '/storage'),
        'Database schema present' => is_file(D11_ROOT . '/database/schema.sql') && is_readable(D11_ROOT . '/database/schema.sql'),
        'Migrations directory present' => is_dir(D11_ROOT . '/database/migrations') && is_readable(D11_ROOT . '/database/migrations'),
    ];
    return $checks;
}

if ($_SERVER['REQUEST_METHOD'] === 'POST') {
    $host = trim((string)($_POST['db_host'] ?? 'localhost'));
    $port = (int)($_POST['db_port'] ?? 3306);
    $database = trim((string)($_POST['db_name'] ?? ''));
    $username = trim((string)($_POST['db_user'] ?? ''));
    $password = (string)($_POST['db_password'] ?? '');
    $adminName = trim((string)($_POST['admin_name'] ?? ''));
    $adminEmail = strtolower(trim((string)($_POST['admin_email'] ?? '')));
    $adminPassword = (string)($_POST['admin_password'] ?? '');
    $baseUrl = rtrim(trim((string)($_POST['base_url'] ?? '')), '/');
    $csrf = (string)($_POST['csrf_token'] ?? '');

    $failedChecks = array_keys(array_filter(install_requirements(), static fn($ok) => !$ok));
    if (!hash_equals((string)$_SESSION['d11_install_csrf'], $csrf)) {
        $error = 'Your installation session expired. Refresh this page and try again.';
    } elseif ($failedChecks) {
        $error = 'Server requirements are not met: ' . implode(', ', $failedChecks) . '.';
    } elseif (!filter_var($adminEmail, FILTER_VALIDATE_EMAIL)) {
        $error = 'Enter a valid administrator email address.';
    } elseif (strlen($adminPassword) < 12) {
        $error = 'Administrator password must contain at least 12 characters.';
    } elseif ($database === '' || $username === '' || $adminName === '' || $baseUrl === '') {
        $error = 'Complete all required fields.';
    } elseif (!preg_match('#^https://[^/]+(?:/[^?#]*)?$#i', $baseUrl)) {
        $error = 'Enter the full HTTPS website URL without query parameters.';
    } elseif ($port < 1 || $port > 65535 || preg_match('/[;\\s]/', $host . $database . $username)) {
        $error = 'Check the database host, name, username and port.';
    } else {
        try {
            require_once D11_ROOT . '/app/Database/MigrationRunner.php';
            $dsn = sprintf('mysql:host=%s;port=%d;dbname=%s;charset=utf8mb4', $host, $port, $database);
            $pdo = new PDO($dsn, $username, $password, [
                PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION,
                PDO::ATTR_DEFAULT_FETCH_MODE => PDO::FETCH_ASSOC,
                PDO::ATTR_EMULATE_PREPARES => false,
            ]);

            // Do not adopt an existing D11 database or overwrite an existing admin account.
            $tableCheck = $pdo->prepare("SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = DATABASE() AND table_name = 'admin_users'");
            $tableCheck->execute();
            if ((int)$tableCheck->fetchColumn() > 0) {
                $adminCount = (int)$pdo->query('SELECT COUNT(*) FROM admin_users')->fetchColumn();
                if ($adminCount > 0) {
                    throw new RuntimeException('This database already contains an administrator. Choose a new, empty database.');
                }
            }

            $schema = file_get_contents(D11_ROOT . '/database/schema.sql');
            if ($schema === false) throw new RuntimeException('Could not read the database schema.');
            foreach (\\D11\\Database\\MigrationRunner::splitSql($schema) as $statement) {
                $pdo->exec($statement);
            }

            $runner = new \\D11\\Database\\MigrationRunner($pdo, D11_ROOT . '/database/migrations');
            $runner->run();

            $config = [
                'app_name' => 'D11 Cricket',
                'base_url' => $baseUrl,
                'timezone' => 'Asia/Kolkata',
                'installed' => true,
                'db' => [
                    'host' => $host,
                    'port' => $port,
                    'database' => $database,
                    'username' => $username,
                    'password' => $password,
                    'charset' => 'utf8mb4',
                ],
            ];
            $configPhp = "<?php\\ndeclare(strict_types=1);\\nreturn " . var_export($config, true) . ";\\n";
            $configTemp = $configFile . '.tmp-' . bin2hex(random_bytes(6));
            $lockTemp = $lockFile . '.tmp-' . bin2hex(random_bytes(6));

            $pdo->beginTransaction();
            try {
                $stmt = $pdo->prepare('INSERT INTO admin_users (name, email, password_hash, role) VALUES (?, ?, ?, ?)');
                $stmt->execute([$adminName, $adminEmail, password_hash($adminPassword, PASSWORD_DEFAULT), 'super_admin']);

                if (file_put_contents($configTemp, $configPhp, LOCK_EX) === false) {
                    throw new RuntimeException('Could not write config file. Check config/ folder permissions.');
                }
                @chmod($configTemp, 0600);
                if (file_put_contents($lockTemp, 'installed ' . gmdate('c'), LOCK_EX) === false) {
                    throw new RuntimeException('Could not create installer lock. Check storage/ folder permissions.');
                }
                if (!rename($configTemp, $configFile)) {
                    throw new RuntimeException('Could not activate config file.');
                }
                if (!rename($lockTemp, $lockFile)) {
                    @unlink($configFile);
                    throw new RuntimeException('Could not activate installer lock.');
                }
                $pdo->commit();
                $success = true;
                unset($_SESSION['d11_install_csrf']);
            } catch (Throwable $e) {
                if ($pdo->inTransaction()) $pdo->rollBack();
                @unlink($configTemp);
                @unlink($lockTemp);
                throw $e;
            }
        } catch (Throwable $e) {
            error_log('D11 installer: ' . $e->getMessage());
            $error = 'Installation could not be completed. Check the database credentials, database permissions, and config/storage folder permissions. Server details were written to the PHP error log.';
        }
    }
}

$requirements = install_requirements();
?><!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>D11 Cricket — Installation</title>
<style>
:root{color-scheme:dark;--panel:#102337;--line:#29435a;--muted:#9eb2c4;--accent:#a6d64f}
*{box-sizing:border-box}body{margin:0;background:linear-gradient(135deg,#081522,#102a3e);font:15px/1.5 system-ui;color:#eef5fb;min-height:100vh;padding:28px 14px}
main{max-width:760px;margin:auto}.brand{font-size:30px;font-weight:800;letter-spacing:1px}.brand span{color:var(--accent)}.sub{color:var(--muted);margin:4px 0 22px}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:18px;padding:22px;margin:14px 0;box-shadow:0 18px 45px #0003}
h2{font-size:18px;margin:0 0 14px}label{display:block;color:#c8d7e4;font-size:13px;margin:12px 0 5px}
input{width:100%;padding:12px;border:1px solid var(--line);border-radius:9px;background:#091a29;color:white;font:inherit}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:0 14px}.btn{background:var(--accent);color:#13220a;border:0;border-radius:10px;padding:14px 18px;font-weight:800;font-size:16px;width:100%;margin-top:18px}
.note{color:var(--muted);font-size:13px}.error{background:#5b2027;padding:12px;border-radius:9px}.ok{background:#183f2b;padding:16px;border-radius:10px}
.checks{display:grid;grid-template-columns:1fr 1fr;gap:7px 12px}.check{font-size:13px;color:var(--muted)}.pass{color:#bce98c}.fail{color:#ffb1b1}
@media(max-width:600px){.grid,.checks{grid-template-columns:1fr}.panel{padding:17px}}
</style></head>
<body><main>
<div class="brand"><span>D11</span> CRICKET</div><div class="sub">New installation · PHP 8.1+ · MySQL / MariaDB</div>
<section class="panel"><h2>Server requirements</h2><div class="checks"><?php foreach($requirements as $label=>$ok): ?><div class="check <?= $ok?'pass':'fail' ?>"><?= $ok?'✓':'✕' ?> <?=install_h($label)?></div><?php endforeach; ?></div><p class="note">Set your domain document root to the php-site/public folder. Keep config/ and storage/ outside the public web root.</p></section>
<?php if ($success): ?>
<div class="panel"><div class="ok"><h2>Installation completed</h2><p>D11 database tables and the administrator account were created. The installer is locked.</p><a href="../../" style="color:#d6f5a1">Open D11 website</a></div></div>
<?php else: ?>
<?php if ($error !== ''): ?><div class="panel error"><?=install_h($error)?></div><?php endif; ?>
<form method="post" class="panel" autocomplete="off">
<input type="hidden" name="csrf_token" value="<?=install_h((string)$_SESSION['d11_install_csrf'])?>">
<h2>1. MySQL database connection</h2>
<div class="grid">
<div><label>Database host</label><input name="db_host" value="<?=install_h((string)($_POST['db_host'] ?? 'localhost'))?>" required></div>
<div><label>Database port</label><input name="db_port" type="number" min="1" max="65535" value="<?=install_h((string)($_POST['db_port'] ?? '3306'))?>" required></div>
<div><label>Database name</label><input name="db_name" value="<?=install_h((string)($_POST['db_name'] ?? ''))?>" required></div>
<div><label>Database username</label><input name="db_user" value="<?=install_h((string)($_POST['db_user'] ?? ''))?>" required></div>
</div>
<label>Database password</label><input name="db_password" type="password" autocomplete="new-password" required>
<p class="note">Create a new, empty MySQL database and user in your hosting panel. Do not use production database credentials.</p>
<h2 style="margin-top:24px">2. Website settings</h2>
<label>Website HTTPS URL</label><input name="base_url" type="url" placeholder="https://your-domain.com" value="<?=install_h((string)($_POST['base_url'] ?? ''))?>" required>
<h2 style="margin-top:24px">3. Administrator account</h2>
<label>Administrator name</label><input name="admin_name" value="<?=install_h((string)($_POST['admin_name'] ?? ''))?>" required>
<label>Administrator email</label><input name="admin_email" type="email" value="<?=install_h((string)($_POST['admin_email'] ?? ''))?>" required>
<label>Administrator password (minimum 12 characters)</label><input name="admin_password" type="password" minlength="12" autocomplete="new-password" required>
<button class="btn" type="submit" <?=in_array(false,$requirements,true)?'disabled':''?>>Install D11 Cricket</button>
</form>
<?php endif; ?>
<p class="note">D11 PHP installer · Python D11 and production PostgreSQL are not modified.</p>
</main></body></html>
