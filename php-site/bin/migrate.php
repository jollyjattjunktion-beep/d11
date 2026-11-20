<?php
declare(strict_types=1);

require dirname(__DIR__) . '/app/bootstrap.php';
require D11_ROOT . '/app/Database/MigrationRunner.php';

$runner = new \\D11\\Database\\MigrationRunner(
    d11_db(),
    D11_ROOT . '/database/migrations'
);

try {
    $result = $runner->run();
    echo 'Applied: ' . ($result['applied'] ? implode(', ', $result['applied']) : 'none') . PHP_EOL;
    echo 'Already applied: ' . ($result['skipped'] ? implode(', ', $result['skipped']) : 'none') . PHP_EOL;
} catch (Throwable $e) {
    fwrite(STDERR, 'Migration failed: ' . $e->getMessage() . PHP_EOL);
    exit(1);
}
