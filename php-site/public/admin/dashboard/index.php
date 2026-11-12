<?php
declare(strict_types=1);
require dirname(__DIR__, 3) . '/app/bootstrap.php';
require dirname(__DIR__, 3) . '/app/admin_auth.php';
$admin = d11_require_admin();
$pdo = d11_db();
$counts = [];
foreach (['competitions','series','teams','players','venues','matches','import_logs'] as $table) {
    $counts[$table] = (int)$pdo->query("SELECT COUNT(*) FROM `{$table}`")->fetchColumn();
}
if (isset($_GET['logout'])) { d11_admin_logout(); header('Location: ' . d11_url('admin/login/')); exit; }
?><!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>D11 Admin Dashboard</title>
<style>*{box-sizing:border-box}body{margin:0;background:#071522;color:#edf5fb;font:15px/1.5 system-ui}header{background:#0d2639;padding:18px max(18px,calc((100% - 1100px)/2));display:flex;justify-content:space-between;gap:12px;align-items:center;border-bottom:1px solid #28485f}.brand{font-size:23px;font-weight:900}.brand b{color:#b7e56b}a{color:#b7e56b;text-decoration:none}main{max-width:1100px;margin:28px auto;padding:0 18px}.muted{color:#9bb1c2}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:14px}.card{background:#10283b;border:1px solid #28485f;border-radius:13px;padding:18px}.num{font-size:30px;color:#b7e56b;font-weight:850}.links{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:12px;margin-top:20px}.links a{display:block;background:#10283b;border:1px solid #28485f;border-radius:10px;padding:15px;color:#edf5fb}.links a span{display:block;color:#9bb1c2;font-size:13px}</style></head><body>
<header><div class="brand"><b>D11</b> ADMIN</div><div>Welcome, <?=d11_e($admin['name'])?> · <a href="?logout=1">Log out</a></div></header>
<main><h1>Cricket data dashboard</h1><p class="muted">Administrator access confirmed. Installation and existing MySQL records are retained.</p>
<div class="grid"><?php foreach(['competitions'=>'Competitions','series'=>'Series','teams'=>'Teams','players'=>'Players','venues'=>'Venues','matches'=>'Matches','import_logs'=>'Import logs'] as $k=>$label): ?><div class="card"><div class="muted"><?=d11_e($label)?></div><div class="num"><?=number_format($counts[$k])?></div></div><?php endforeach; ?></div>
<h2>Management</h2><div class="links">
<a href="<?=d11_e(d11_url())?>">Public website<span>Open cricket data site</span></a>
<a href="<?=d11_e(d11_url('admin/dashboard/'))?>">Dashboard<span>Overview and database counts</span></a>
<a href="<?=d11_e(d11_url('admin/login/'))?>">Admin login<span>Administrator sign-in</span></a>
<a href="?logout=1">Logout<span>End administrator session</span></a>
</div><p class="muted">Next phase: add protected CRUD screens and authorised cricket data provider importers. This dashboard does not yet perform series discovery or imports.</p></main></body></html>
