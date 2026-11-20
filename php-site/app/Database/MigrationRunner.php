<?php
declare(strict_types=1);

namespace D11\\Database;

use PDO;
use PDOException;
use RuntimeException;
use Throwable;

/**
 * Small shared-hosting-compatible SQL migration runner.
 * Migrations are applied in filename order and recorded only after every
 * statement succeeds. Duplicate-column errors are ignored so an interrupted
 * multi-statement migration can safely resume on the next run.
 */
final class MigrationRunner
{
    public function __construct(
        private PDO $db,
        private string $directory
    ) {}

    /** @return list<string> */
    public static function splitSql(string $sql): array
    {
        $sql = preg_replace('/^\\s*--.*$/m', '', $sql) ?? $sql;
        $statements = [];
        $buffer = '';
        $quote = null;
        $escaped = false;
        $length = strlen($sql);

        for ($i = 0; $i < $length; $i++) {
            $char = $sql[$i];
            if ($quote !== null) {
                $buffer .= $char;
                if ($escaped) {
                    $escaped = false;
                } elseif ($char === '\\\\') {
                    $escaped = true;
                } elseif ($char === $quote) {
                    if ($i + 1 < $length && $sql[$i + 1] === $quote) {
                        $buffer .= $sql[++$i];
                    } else {
                        $quote = null;
                    }
                }
                continue;
            }

            if ($char === "'" || $char === '"' || $char === "`") {
                $quote = $char;
                $buffer .= $char;
            } elseif ($char === ';') {
                $statement = trim($buffer);
                if ($statement !== '') $statements[] = $statement;
                $buffer = '';
            } else {
                $buffer .= $char;
            }
        }

        $tail = trim($buffer);
        if ($tail !== '') $statements[] = $tail;
        return $statements;
    }

    /** @return array{applied:list<string>, skipped:list<string>} */
    public function run(): array
    {
        if (!is_dir($this->directory) || !is_readable($this->directory)) {
            throw new RuntimeException('Migration directory is missing or unreadable.');
        }

        $this->db->exec(
            'CREATE TABLE IF NOT EXISTS d11_schema_migrations (
                version VARCHAR(120) NOT NULL PRIMARY KEY,
                applied_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4'
        );

        $files = glob(rtrim($this->directory, DIRECTORY_SEPARATOR) . DIRECTORY_SEPARATOR . '*.sql') ?: [];
        sort($files, SORT_STRING);
        $applied = [];
        $skipped = [];

        foreach ($files as $file) {
            $version = basename($file);
            $check = $this->db->prepare('SELECT 1 FROM d11_schema_migrations WHERE version = ? LIMIT 1');
            $check->execute([$version]);
            if ($check->fetchColumn()) {
                $skipped[] = $version;
                continue;
            }

            $sql = file_get_contents($file);
            if ($sql === false) throw new RuntimeException('Could not read migration: ' . $version);

            foreach (self::splitSql($sql) as $statement) {
                try {
                    $this->db->exec($statement);
                } catch (PDOException $e) {
                    $driverCode = (int)($e->errorInfo[1] ?? 0);
                    // MySQL 1060 = duplicate column. Safe only because each
                    // ADD COLUMN is a standalone statement in our migrations.
                    if ($driverCode === 1060 && preg_match('/^ALTER\\s+TABLE\\b/i', ltrim($statement))) {
                        continue;
                    }
                    throw new RuntimeException(
                        'Migration ' . $version . ' failed: ' . $e->getMessage(),
                        0,
                        $e
                    );
                }
            }

            $record = $this->db->prepare('INSERT INTO d11_schema_migrations (version) VALUES (?)');
            $record->execute([$version]);
            $applied[] = $version;
        }

        return ['applied' => $applied, 'skipped' => $skipped];
    }
}
