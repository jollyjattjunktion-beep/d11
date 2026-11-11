<?php
declare(strict_types=1);

function d11_start_admin_session(): void {
    if (session_status() === PHP_SESSION_ACTIVE) return;
    $secure = (!empty($_SERVER['HTTPS']) && $_SERVER['HTTPS'] !== 'off');
    session_name('d11_admin');
    session_set_cookie_params([
        'lifetime' => 0, 'path' => '/', 'secure' => $secure,
        'httponly' => true, 'samesite' => 'Lax'
    ]);
    session_start();
}
function d11_admin_csrf(): string {
    d11_start_admin_session();
    if (empty($_SESSION['d11_csrf'])) $_SESSION['d11_csrf'] = bin2hex(random_bytes(32));
    return $_SESSION['d11_csrf'];
}
function d11_admin_check_csrf(): bool {
    d11_start_admin_session();
    return isset($_POST['csrf'], $_SESSION['d11_csrf'])
        && is_string($_POST['csrf'])
        && hash_equals($_SESSION['d11_csrf'], $_POST['csrf']);
}
function d11_require_admin(): array {
    d11_start_admin_session();
    if (empty($_SESSION['d11_admin_id'])) {
        header('Location: /admin/login/');
        exit;
    }
    return ['id'=>(int)$_SESSION['d11_admin_id'], 'name'=>(string)($_SESSION['d11_admin_name'] ?? 'Administrator'),
        'email'=>(string)($_SESSION['d11_admin_email'] ?? '')];
}
function d11_admin_logout(): void {
    d11_start_admin_session();
    $_SESSION = [];
    if (ini_get('session.use_cookies')) {
        $p=session_get_cookie_params();
        setcookie(session_name(), '', ['expires'=>time()-42000,'path'=>$p['path'],'domain'=>$p['domain'],
            'secure'=>$p['secure'],'httponly'=>$p['httponly'],'samesite'=>'Lax']);
    }
    session_destroy();
}
