<?php
declare(strict_types=1);

define('D11_ROOT', dirname(__DIR__));
$configFile = D11_ROOT . '/config/config.php';
$lockFile = D11_ROOT . '/storage/installed.lock';

if (!is_file($configFile) || !is_file($lockFile)) {
    http_response_code(503);
    exit('D11 is not installed. Open /install/ to complete setup.');
}

$config = require $configFile;
date_default_timezone_set($config['timezone'] ?? 'Asia/Kolkata');

function d11_db(): PDO
{
    static $pdo = null;
    global $config;
    if ($pdo instanceof PDO) return $pdo;

    $db = $config['db'];
    $dsn = sprintf(
        'mysql:host=%s;port=%d;dbname=%s;charset=%s',
        $db['host'],
        (int)($db['port'] ?? 3306),
        $db['database'],
        $db['charset'] ?? 'utf8mb4'
    );
    $pdo = new PDO($dsn, $db['username'], $db['password'], [
        PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION,
        PDO::ATTR_DEFAULT_FETCH_MODE => PDO::FETCH_ASSOC,
        PDO::ATTR_EMULATE_PREPARES => false,
    ]);
    return $pdo;
}

function d11_e(?string $value): string
{
    return htmlspecialchars($value ?? '', ENT_QUOTES | ENT_SUBSTITUTE, 'UTF-8');
}
