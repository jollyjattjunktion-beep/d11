<?php
declare(strict_types=1);

/**
 * Copy to config.php and fill using values from your hosting control panel.
 * Keep this file outside the public web root. Never commit real credentials.
 */
return [
    'app_name' => 'D11 Cricket',
    'base_url' => 'https://example.com',
    'timezone' => 'Asia/Kolkata',
    'installed' => false,
    'db' => [
        'host' => 'localhost',
        'port' => 3306,
        'database' => 'd11_cricket_demo',
        'username' => 'YOUR_MYSQL_USER',
        'password' => 'CHANGE_THIS',
        'charset' => 'utf8mb4',
    ],
];
