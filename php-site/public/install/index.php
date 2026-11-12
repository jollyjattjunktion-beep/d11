<?php
declare(strict_types=1);

define('D11_ROOT', dirname(__DIR__, 2));
$configDir = D11_ROOT . '/config';
$storageDir = D11_ROOT . '/storage';
$configFile = $configDir . '/config.php';
$lockFile = $storageDir . '/installed.lock';

if (is_file($lockFile)) {
    http_response_code(403);
    exit('D11 is already installed. The installer is locked.');
}

function install_h(string $value): string {
    return htmlspecialchars($value, ENT_QUOTES | ENT_SUBSTITUTE, 'UTF-8');
}

if (session_status() !== PHP_SESSION_ACTIVE) {
    $secure = !empty($_SERVER['HTTPS']) && $_SERVER['HTTPS'] !== 'off';
    session_set_cookie_params(['httponly'=>true, 'secure'=>$secure, 'samesite'=>'Lax']);
    session_start();
}
if (empty($_SESSION['d11_install_csrf'])) {
    $_SESSION['d11_install_csrf'] = bin2hex(random_bytes(32));
}

$hostHeader = preg_replace('/[^A-Za-z0-9.:-]/', '', (string)($_SERVER['HTTP_HOST'] ?? 'localhost'));
$installPath = str_replace('\\\\', '/', dirname(dirname((string)($_SERVER['SCRIPT_NAME'] ?? '/install/index.php'))));
$defaultBaseUrl = 'https://' . ($hostHeader ?: 'localhost') . rtrim($installPath, '/');
$error = '';
$success = false;

if ($_SERVER['REQUEST_METHOD'] === 'POST') {
    $host = trim((string)($_POST['db_host'] ?? 'sql307.infinityfree.com'));
    $port = (int)($_POST['db_port'] ?? 3306);
    $database = trim((string)($_POST['db_name'] ?? 'if0_43415210_d11'));
    $username = trim((string)($_POST['db_user'] ?? 'if0_43415210'));
    $password = (string)($_POST['db_password'] ?? '');
    $baseUrl = rtrim(trim((string)($_POST['base_url'] ?? $defaultBaseUrl)), '/');
    $adminName = trim((string)($_POST['admin_name'] ?? ''));
    $adminEmail = strtolower(trim((string)($_POST['admin_email'] ?? '')));
    $adminPassword = (string)($_POST['admin_password'] ?? '');
    $csrf = (string)($_POST['csrf'] ?? '');
    $url = filter_var($baseUrl, FILTER_VALIDATE_URL) ? parse_url($baseUrl) : false;

    if (!hash_equals((string)$_SESSION['d11_install_csrf'], $csrf)) {
        $error = 'The form expired. Refresh this page and try again.';
    } elseif (!preg_match('/^[A-Za-z0-9.-]+$/', $host) || $port < 1 || $port > 65535) {
        $error = 'Check the MySQL host and port from your hosting control panel.';
    } elseif (!preg_match('/^[A-Za-z0-9_]+$/', $database) || !preg_match('/^[A-Za-z0-9_]+$/', $username)) {
        $error = 'Database name and username may contain letters, numbers and underscores only.';
    } elseif ($password === '') {
        $error = 'Enter your MySQL password.';
    } elseif ($adminName === '' || !filter_var($adminEmail, FILTER_VALIDATE_EMAIL)) {
        $error = 'Enter a valid administrator name and email.';
    } elseif (strlen($adminPassword) < 12) {
        $error = 'Administrator password must be at least 12 characters.';
    } elseif (!$url || strtolower((string)($url['scheme'] ?? '')) !== 'https' || empty($url['host'])) {
        $error = 'Enter the complete HTTPS website URL, including its subfolder if applicable.';
    } else {
        try {
            foreach ([$configDir, $storageDir] as $dir) {
                if (!is_dir($dir) && !mkdir($dir, 0755, true) && !is_dir($dir)) {
                    throw new RuntimeException('Could not create the ' . basename($dir) . ' directory.');
                }
                if (!is_writable($dir)) {
                    throw new RuntimeException('The ' . basename($dir) . ' directory is not writable. Check hosting file permissions.');
                }
            }

            $dsn = sprintf('mysql:host=%s;port=%d;dbname=%s;charset=utf8mb4', $host, $port, $database);
            $pdo = new PDO($dsn, $username, $password, [
                PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION,
                PDO::ATTR_DEFAULT_FETCH_MODE => PDO::FETCH_ASSOC,
                PDO::ATTR_EMULATE_PREPARES => false,
                PDO::ATTR_TIMEOUT => 15,
            ]);

            $schemaFile = D11_ROOT . '/database/schema.sql';
            if (!is_file($schemaFile) || !is_readable($schemaFile)) {
                throw new RuntimeException('database/schema.sql is missing. Upload the complete D11 package, not only the public folder.');
            }
            $schema = file_get_contents($schemaFile);
            if ($schema === false) throw new RuntimeException('Could not read the database schema.');

            preg_match_all('/CREATE\\s+TABLE\\s+IF\\s+NOT\\s+EXISTS\\s+`?([A-Za-z0-9_]+)`?/i', $schema, $matches);
            $ownedTables = array_fill_keys($matches[1] ?? [], true);
            if (!$ownedTables) throw new RuntimeException('The database schema has no recognized D11 tables.');

            $existingTables = $pdo->query('SHOW TABLES')->fetchAll(PDO::FETCH_COLUMN);
            foreach ($existingTables as $table) {
                if (!isset($ownedTables[$table])) {
                    throw new RuntimeException('The selected database is not empty (found table: ' . $table . '). Choose a separate empty D11 demo database. No unrelated tables were changed.');
                }
            }

            $schema = preg_replace('/^\\s*--.*$/m', '', $schema);
            foreach (array_filter(array_map('trim', explode(';', (string)$schema))) as $statement) {
                $pdo->exec($statement);
            }

            $findAdmin = $pdo->prepare('SELECT id FROM admin_users WHERE email = ? LIMIT 1');
            $findAdmin->execute([$adminEmail]);
            $adminId = $findAdmin->fetchColumn();
            $hash = password_hash($adminPassword, PASSWORD_DEFAULT);
            if ($adminId) {
                $saveAdmin = $pdo->prepare('UPDATE admin_users SET name=?, password_hash=?, role=? WHERE id=?');
                $saveAdmin->execute([$adminName, $hash, 'super_admin', (int)$adminId]);
            } else {
                $saveAdmin = $pdo->prepare('INSERT INTO admin_users (name,email,password_hash,role) VALUES (?,?,?,?)');
                $saveAdmin->execute([$adminName, $adminEmail, $hash, 'super_admin']);
            }

            $config = [
                'app_name'=>'D11 Cricket',
                'base_url'=>$baseUrl,
                'timezone'=>'Asia/Kolkata',
                'installed'=>true,
                'db'=>['host'=>$host,'port'=>$port,'database'=>$database,'username'=>$username,'password'=>$password,'charset'=>'utf8mb4'],
            ];
            $configText = "<?php\ndeclare(strict_types=1);\nreturn " . var_export($config, true) . ";\n";
            $tempFile = $configFile . '.tmp';
            if (file_put_contents($tempFile, $configText, LOCK_EX) === false || !rename($tempFile, $configFile)) {
                @unlink($tempFile);
                throw new RuntimeException('Could not write config/config.php. Check the config folder permissions.');
            }
            if (file_put_contents($lockFile, 'installed ' . gmdate('c'), LOCK_EX) === false) {
                throw new RuntimeException('Could not lock the installer. Do not reinstall; check storage folder permissions.');
            }
            $success = true;
        } catch (PDOException $e) {
            error_log('D11 installer database error: ' . $e->getMessage());
            if (stripos($e->getMessage(), 'Access denied') !== false) {
                $error = 'MySQL access denied. Check the separate database username and password. InfinityFree username is not the same as the full database name.';
            } elseif (stripos($e->getMessage(), 'Unknown database') !== false) {
                $error = 'Database not found. Copy the exact database name from the InfinityFree control panel.';
            } else {
                $error = 'MySQL connection/setup failed. Verify host, port, database, username, password and PDO MySQL support. See the hosting PHP error log for details.';
            }
        } catch (Throwable $e) {
            error_log('D11 installer error: ' . $e->getMessage());
            $error = $e->getMessage();
        }
    }
}
?><!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>D11 Cricket — Installation</title>
<style>
:root{color-scheme:dark;--panel:#102337;--line:#29435a;--muted:#9eb2c4;--accent:#b7e56b}
*{box-sizing:border-box}body{margin:0;background:radial-gradient(ellipse at top,#173b50 0,#071522 58%);font:15px/1.55 system-ui;color:#eef5fb;min-height:100vh;padding:28px 14px}
main{max-width:760px;margin:auto}.brand{font-size:30px;font-weight:900;letter-spacing:1px}.brand span{color:var(--accent)}.sub{color:var(--muted);margin:4px 0 22px}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:18px;padding:22px;margin:14px 0;box-shadow:0 18px 45px #0003}
h2{font-size:18px;margin:0 0 14px}label{display:block;color:#c8d7e4;font-size:13px;margin:12px 0 5px}
input{width:100%;padding:12px;border:1px solid var(--line);border-radius:9px;background:#091a29;color:white;font:inherit}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:0 14px}.btn{background:var(--accent);color:#13220a;border:0;border-radius:10px;padding:14px 18px;font-weight:850;font-size:16px;width:100%;margin-top:18px;cursor:pointer}
.note{color:var(--muted);font-size:13px}.error{background:#5b2027;border:1px solid #8e3c47;padding:12px;border-radius:9px}.ok{background:#183f2b;border:1px solid #36764c;padding:16px;border-radius:10px}.hint{background:#0a1b2a;border:1px solid #29435a;padding:12px;border-radius:9px;color:#b7c9d8;font-size:13px}
@media(max-width:600px){.grid{grid-template-columns:1fr}.panel{padding:17px}}
</style></head>
<body><main>
<div class="brand"><span>D11</span> CRICKET</div><div class="sub">Secure first-time installation · PHP + MySQL</div>
<?php if ($success): ?>
<div class="panel"><div class="ok"><h2>Installation completed</h2><p>D11 database tables and administrator account are ready. The installer has been locked.</p><a href="<?=install_h($baseUrl)?>/" style="color:#d6f5a1">Open D11 Cricket</a></div></div>
<?php else: ?>
<?php if ($error !== ''): ?><div class="panel error"><?=install_h($error)?></div><?php endif; ?>
<form method="post" class="panel" autocomplete="off">
<input type="hidden" name="csrf" value="<?=install_h((string)$_SESSION['d11_install_csrf'])?>">
<h2>1. MySQL database connection</h2>
<div class="grid">
<div><label>Database host</label><input name="db_host" value="<?=install_h($_POST['db_host'] ?? 'sql307.infinityfree.com')?>" required></div>
<div><label>Database port</label><input name="db_port" type="number" value="<?=install_h($_POST['db_port'] ?? '3306')?>" required></div>
<div><label>Database name</label><input name="db_name" value="<?=install_h($_POST['db_name'] ?? 'if0_43415210_d11')?>" required></div>
<div><label>Database username</label><input name="db_user" value="<?=install_h($_POST['db_user'] ?? 'if0_43415210')?>" required></div>
</div>
<label>Database password</label><input name="db_password" type="password" required autocomplete="new-password">
<div class="hint" style="margin-top:12px">InfinityFree: the database name and database username are different fields. Use the username displayed in your hosting panel. Use a dedicated empty demo database, never production credentials.</div>
<h2 style="margin-top:24px">2. Website settings</h2>
<label>Website HTTPS URL</label><input name="base_url" type="url" value="<?=install_h($_POST['base_url'] ?? $defaultBaseUrl)?>" required>
<p class="note">The folder path is detected automatically. Keep it if D11 is installed inside a subfolder.</p>
<h2 style="margin-top:24px">3. Administrator account</h2>
<label>Administrator name</label><input name="admin_name" value="<?=install_h($_POST['admin_name'] ?? '')?>" required>
<label>Administrator email</label><input name="admin_email" type="email" value="<?=install_h($_POST['admin_email'] ?? '')?>" required>
<label>Administrator password (minimum 12 characters)</label><input name="admin_password" type="password" minlength="12" required autocomplete="new-password">
<button class="btn" type="submit">Test connection & Install D11</button>
</form>
<?php endif; ?>
<p class="note">D11 PHP installer · Python D11 and production PostgreSQL remain separate and untouched.</p>
</main></body></html>