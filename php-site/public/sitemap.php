<?php
declare(strict_types=1);
$d11Root = is_file(dirname(__DIR__) . '/app/bootstrap.php') ? dirname(__DIR__) : __DIR__;
require $d11Root . '/app/bootstrap.php';

header('Content-Type: application/xml; charset=UTF-8');
header('X-Content-Type-Options: nosniff');

function sitemap_loc(string $path = ''): string {
    return htmlspecialchars(d11_url($path), ENT_XML1 | ENT_COMPAT, 'UTF-8');
}
echo '<?xml version="1.0" encoding="UTF-8"?>' . "\n";
echo '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' . "\n";
$urls = [
    ['', 'daily', '1.0'],
    ['live-cricket-score/', 'minute', '0.9'],
    ['series/', 'daily', '0.8'],
];
try {
    $pdo = d11_db();
    foreach ($pdo->query('SELECT slug,updated_at FROM series ORDER BY id DESC LIMIT 5000')->fetchAll() as $row) {
        $urls[] = ['series/' . rawurlencode((string)$row['slug']) . '/', 'daily', '0.8'];
        $urls[] = ['series/' . rawurlencode((string)$row['slug']) . '/points-table/', 'daily', '0.6'];
    }
    foreach ($pdo->query('SELECT slug,updated_at FROM matches WHERE slug IS NOT NULL AND slug<>"" ORDER BY start_time_utc DESC LIMIT 10000')->fetchAll() as $row) {
        $urls[] = ['match/' . rawurlencode((string)$row['slug']) . '/', 'hourly', '0.8'];
    }
} catch (Throwable $e) {
    error_log('D11 sitemap error: ' . $e->getMessage());
}
foreach ($urls as [$path, $frequency, $priority]) {
    echo "<url><loc>" . sitemap_loc($path) . "</loc><changefreq>{$frequency}</changefreq><priority>{$priority}</priority></url>\n";
}
echo "</urlset>";
