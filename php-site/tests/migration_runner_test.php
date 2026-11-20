<?php
declare(strict_types=1);

require dirname(__DIR__) . '/app/Database/MigrationRunner.php';

use D11\Database\MigrationRunner;

function d11_assert(bool $condition, string $message): void {
    if (!$condition) {
        fwrite(STDERR, "FAIL: {$message}\n");
        exit(1);
    }
}

$parts = MigrationRunner::splitSql("CREATE TABLE t (v VARCHAR(20) DEFAULT 'a;b');\n-- ignored ; comment\nINSERT INTO t VALUES ('x;y');");
d11_assert(count($parts) === 2, 'SQL splitter must preserve semicolons inside quoted strings.');
d11_assert(str_contains($parts[0], "DEFAULT 'a;b'"), 'First statement must retain quoted semicolon.');
d11_assert(str_contains($parts[1], "'x;y'"), 'Second statement must retain quoted semicolon.');

$migration = file_get_contents(dirname(__DIR__) . '/database/migrations/001_complete_engine_parity.sql');
d11_assert($migration !== false, 'Parity migration must exist.');
d11_assert(!preg_match('/\b(DROP\s+TABLE|TRUNCATE\s+TABLE|DELETE\s+FROM)\b/i', $migration), 'Parity migration must not contain destructive data statements.');
d11_assert(substr_count($migration, 'ALTER TABLE players ADD COLUMN') === 3, 'Player ALTERs must be split for resumable execution.');
d11_assert(substr_count($migration, 'ALTER TABLE matches ADD COLUMN') === 5, 'Match ALTERs must be split for resumable execution.');
d11_assert(substr_count($migration, 'ALTER TABLE match_squads ADD COLUMN') === 5, 'Squad ALTERs must be split for resumable execution.');

echo "PHP migration runner tests passed.\n";
