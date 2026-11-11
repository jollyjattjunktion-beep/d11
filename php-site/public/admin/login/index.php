<?php
declare(strict_types=1);
require dirname(__DIR__, 3) . '/app/bootstrap.php';
require dirname(__DIR__, 3) . '/app/admin_auth.php';
d11_start_admin_session();
if (!empty($_SESSION['d11_admin_id'])) { header('Location: /admin/dashboard/'); exit; }
$error = '';
if ($_SERVER['REQUEST_METHOD'] === 'POST') {
    if (!d11_admin_check_csrf()) {
        $error = 'Your session expired. Refresh this page and try again.';
    } else {
        $email = strtolower(trim((string)($_POST['email'] ?? '')));
        $password = (string)($_POST['password'] ?? '');
        $q = d11_db()->prepare('SELECT id,name,email,password_hash,role FROM admin_users WHERE email=? AND is_active=1 LIMIT 1');
        $q->execute([$email]); $admin = $q->fetch();
        if ($admin && password_verify($password, $admin['password_hash'])) {
            session_regenerate_id(true);
            $_SESSION['d11_admin_id'] = (int)$admin['id'];
            $_SESSION['d11_admin_name'] = $admin['name'];
            $_SESSION['d11_admin_email'] = $admin['email'];
            $_SESSION['d11_admin_role'] = $admin['role'];
            header('Location: /admin/dashboard/'); exit;
        }
        $error = 'Email or password is incorrect.';
    }
}
?><!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>D11 Admin Login</title>
<style>*{box-sizing:border-box}body{margin:0;min-height:100vh;display:grid;place-items:center;background:#071522;color:#edf5fb;font:15px system-ui;padding:18px}.panel{width:min(420px,100%);background:#10283b;border:1px solid #28485f;border-radius:16px;padding:28px}.brand{font-size:26px;font-weight:900}.brand b{color:#b7e56b}label{display:block;margin:16px 0 6px;color:#c6d5e1}input{width:100%;padding:13px;border-radius:8px;border:1px solid #35536a;background:#091b2b;color:white;font:inherit}.btn{width:100%;margin-top:22px;padding:13px;border:0;border-radius:8px;background:#b7e56b;color:#17220c;font-weight:800;font-size:16px}.error{background:#54252d;padding:11px;border-radius:8px}.muted{color:#9bb1c2}</style></head><body><form class="panel" method="post">
<div class="brand"><b>D11</b> ADMIN</div><p class="muted">Sign in with the administrator account created during installation.</p>
<?php if($error): ?><p class="error"><?=d11_e($error)?></p><?php endif; ?>
<input type="hidden" name="csrf" value="<?=d11_e(d11_admin_csrf())?>">
<label>Email address</label><input type="email" name="email" autocomplete="username" required>
<label>Password</label><input type="password" name="password" autocomplete="current-password" required>
<button class="btn" type="submit">Sign in</button></form></body></html>
