<?php
declare(strict_types=1);
$d11Root = is_file(dirname(__DIR__, 2) . '/app/bootstrap.php') ? dirname(__DIR__, 2) : dirname(__DIR__);
require $d11Root . '/app/bootstrap.php';
header('Location: ' . d11_url('admin/dashboard/'));
exit;
