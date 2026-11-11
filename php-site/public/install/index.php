<?php
declare(strict_types=1);

define('D11_ROOT', dirname(__DIR__, 2));
$lockFile = D11_ROOT . '/storage/installed.lock';
$configFile = D11_ROOT . '/config/config.php';
$error = '';
$success = false;

if (is_file($lockFile)) {
    http_response_code(403);
    exit('D11 is already installed. Installer is locked.');
}

function install_h(string $value): string {
    return htmlspecialchars($value, ENT_QUOTES | ENT_SUBSTITUTE, 'UTF-8');
}

if ($_SERVER['REQUEST_METHOD'] === 'POST') {
    $host = trim((string)($_POST['db_host'] ?? 'localhost'));
    $port = (int)($_POST['db_port'] ?? 3306);
    $database = trim((string)($_POST['db_name'] ?? ''));
    $username = trim((string)($_POST['db_user'] ?? ''));
    $password = (string)($_POST['db_password'] ?? '');
    $adminName = trim((string)($_POST['admin_name'] ?? ''));
    $adminEmail = trim((string)($_POST['admin_email'] ?? ''));
    $adminPassword = (string)($_POST['admin_password'] ?? '');
    $baseUrl = rtrim(trim((string)($_POST['base_url'] ?? '')), '/');

    if (!filter_var($adminEmail, FILTER_VALIDATE_EMAIL)) {
        $error = 'Enter a valid administrator email address.';
    } elseif (strlen($adminPassword) < 12) {
        $error = 'Administrator password must contain at least 12 characters.';
    } elseif ($database === '' || $username === '' || $adminName === '' || $baseUrl === '') {
        $error = 'Complete all required fields.';
    } elseif (!preg_match('#^https://#i', $baseUrl)) {
        $error = 'Use the HTTPS website URL.';
    } else {
        try {
            $dsn = sprintf('mysql:host=%s;port=%d;dbname=%s;charset=utf8mb4', $host, $port, $database);
            $pdo = new PDO($dsn, $username, $password, [
                PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION,
                PDO::ATTR_EMULATE_PREPARES => false,
            ]);

            $schemaPath = D11_ROOT . '/database/schema.sql';
            if (!is_file($schemaPath)) throw new RuntimeException('Database schema file is missing.');
            $schema = file_get_contents($schemaPath);
            $schema = preg_replace('/^\s*--.*$/m', '', $schema);
            foreach (array_filter(array_map('trim', explode(';', (string)$schema))) as $statement) {
                $pdo->exec($statement);
            }

            $stmt = $pdo->prepare('INSERT INTO admin_users (name, email, password_hash, role) VALUES (?, ?, ?, ?)');
            $stmt->execute([$adminName, strtolower($adminEmail), password_hash($adminPassword, PASSWORD_DEFAULT), 'super_admin']);

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

            $configDir = D11_ROOT . '/config';
            $storageDir = D11_ROOT . '/storage';
            if (!is_dir($configDir)) mkdir($configDir, 0750, true);
            if (!is_dir($storageDir)) mkdir($storageDir, 0750, true);
            $configPhp = "<?php\ndeclare(strict_types=1);\nreturn " . var_export($config, true) . ";\n";
            if (file_put_contents($configFile, $configPhp, LOCK_EX) === false) {
                throw new RuntimeException('Could not write config/config.php. Check folder permissions.');
            }
            if (file_put_contents($lockFile, 'installed ' . gmdate('c'), LOCK_EX) === false) {
                throw new RuntimeException('Could not create installer lock file.');
            }
            $success = true;
        } catch (Throwable $e) {
            $error = 'Installation failed: ' . $e->getMessage();
        }
    }
}
?><!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>D11 Cricket — Installation</title>
<style>
:root{color-scheme:dark;--bg:#081522;--panel:#102337;--line:#29435a;--muted:#9eb2c4;--accent:#a6d64f}
*{box-sizing:border-box}body{margin:0;background:linear-gradient(135deg,#081522,#102a3e);font:15px/1.5 system-ui;color:#eef5fb;min-height:100vh;padding:28px 14px}
main{max-width:760px;margin:auto}.brand{font-size:30px;font-weight:800;letter-spacing:1px}.brand span{color:var(--accent)}.sub{color:var(--muted);margin:4px 0 22px}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:18px;padding:22px;margin:14px 0;box-shadow:0 18px 45px #0003}
h2{font-size:18px;margin:0 0 14px}label{display:block;color:#c8d7e4;font-size:13px;margin:12px 0 5px}
input{width:100%;padding:12px;border:1px solid var(--line);border-radius:9px;background:#091a29;color:white;font:inherit}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:0 14px}.btn{background:var(--accent);color:#13220a;border:0;border-radius:10px;padding:14px 18px;font-weight:800;font-size:16px;width:100%;margin-top:18px}
.note{color:var(--muted);font-size:13px}.error{background:#5b2027;padding:12px;border-radius:9px}.ok{background:#183f2b;padding:16px;border-radius:10px}
@media(max-width:600px){.grid{grid-template-columns:1fr}.panel{padding:17px}}
</style></head>
<body><main>
<div class="brand"><span>D11</span> CRICKET</div><div class="sub">New installation · PHP + MySQL</div>
<?php if ($success): ?>
<div class="panel"><div class="ok"><h2>Installation completed</h2><p>Your D11 MySQL tables and administrator account have been created. The installer is now locked.</p><a href="../" style="color:#d6f5a1">Open D11 website</a></div></div>
<?php else: ?>
<?php if ($error !== ''): ?><div class="panel error"><?=install_h($error)?></div><?php endif; ?>
<form method="post" class="panel" autocomplete="off">
<h2>1. MySQL database connection</h2>
<div class="grid">
<div><label>Database host</label><input name="db_host" value="<?=install_h($_POST['db_host'] ?? 'localhost')?>" required></div>
<div><label>Database port</label><input name="db_port" type="number" value="<?=install_h($_POST['db_port'] ?? '3306')?>" required></div>
<div><label>Database name</label><input name="db_name" value="<?=install_h($_POST['db_name'] ?? '')?>" required></div>
<div><label>Database username</label><input name="db_user" value="<?=install_h($_POST['db_user'] ?? '')?>" required></div>
</div>
<label>Database password</label><input name="db_password" type="password" required>
<p class="note">Create a new, empty MySQL database in GoogieHost first. Do not use the production PostgreSQL database.</p>
<h2 style="margin-top:24px">2. Website settings</h2>
<label>Website HTTPS URL</label><input name="base_url" type="url" placeholder="https://your-domain.com" value="<?=install_h($_POST['base_url'] ?? '')?>" required>
<h2 style="margin-top:24px">3. Administrator account</h2>
<label>Administrator name</label><input name="admin_name" value="<?=install_h($_POST['admin_name'] ?? '')?>" required>
<label>Administrator email</label><input name="admin_email" type="email" value="<?=install_h($_POST['admin_email'] ?? '')?>" required>
<label>Administrator password (minimum 12 characters)</label><input name="admin_password" type="password" minlength="12" required>
<button class="btn" type="submit">Install D11 Cricket</button>
</form>
<?php endif; ?>
<p class="note">D11 PHP installer · Existing Python application and production database are not modified.</p>
</main></body></html>
