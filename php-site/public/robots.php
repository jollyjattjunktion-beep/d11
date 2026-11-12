<?php
declare(strict_types=1);
$d11Root = is_file(dirname(__DIR__) . '/app/bootstrap.php') ? dirname(__DIR__) : __DIR__;
require $d11Root . '/app/bootstrap.php';
header('Content-Type: text/plain; charset=UTF-8');
header('X-Content-Type-Options: nosniff');
echo "User-agent: *\n";
echo "Allow: /\n";
echo "Disallow: /admin/\n";
echo "Disallow: /install/\n";
echo "Sitemap: " . d11_url('sitemap.xml') . "\n";
