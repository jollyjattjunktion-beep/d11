<?php
declare(strict_types=1);
require dirname(__DIR__) . '/app/bootstrap.php';

$path = (string)(parse_url($_SERVER['REQUEST_URI'] ?? '/', PHP_URL_PATH) ?? '/');
$basePath = d11_base_path();
if ($basePath !== '' && str_starts_with($path, $basePath)) {
    $path = substr($path, strlen($basePath));
}
$path = '/' . trim(rawurldecode($path), '/');
if ($path === '//') $path = '/';
$parts = array_values(array_filter(explode('/', trim($path, '/')), 'strlen'));

$title = 'D11 Cricket — Live Cricket Scores, Fixtures & Series';
$description = 'Follow live cricket scores, ball-by-ball match updates, fixtures, series, teams and player profiles on D11 Cricket.';
$canonical = d11_url($path === '/' ? '' : ltrim($path, '/'));
$rows = [];
$contentTitle = 'Cricket, scores and match centre';
$intro = 'Live scores, upcoming fixtures, tournaments and cricket information.';
$kind = 'home';

try {
    $pdo = d11_db();
    $route = $parts[0] ?? '';

    if ($route === 'live-cricket-score') {
        $kind = 'matches';
        $contentTitle = 'Live Cricket Scores';
        $title = 'Live Cricket Score & Ball-by-Ball Updates | D11';
        $description = 'Latest live cricket scores, match status and ball-by-ball match centre.';
        $stmt = $pdo->query("SELECT id,match_title,slug,status,start_time_utc,format FROM matches WHERE status IN ('live','innings_break') ORDER BY start_time_utc DESC LIMIT 50");
        $rows = $stmt->fetchAll();
        $intro = 'Live and innings-break matches currently recorded in D11.';
    } elseif ($route === 'series' && count($parts) === 1) {
        $kind = 'series';
        $contentTitle = 'Cricket Series & Tournaments';
        $title = 'Cricket Series, Cups & Tournament Fixtures | D11';
        $description = 'Browse cricket series, cups, leagues, tournament schedules and match fixtures.';
        $rows = $pdo->query('SELECT id,name,slug,format,season,status,start_date,end_date FROM series ORDER BY start_date DESC LIMIT 100')->fetchAll();
    } elseif ($route === 'series' && count($parts) >= 2) {
        $slug = $parts[1];
        $stmt = $pdo->prepare('SELECT * FROM series WHERE slug = ? LIMIT 1');
        $stmt->execute([$slug]);
        $item = $stmt->fetch();
        if (!$item) {
            http_response_code(404);
            $kind = 'notfound';
            $contentTitle = 'Series not found';
        } elseif (($parts[2] ?? '') === 'points-table') {
            $kind = 'points';
            $contentTitle = $item['name'] . ' — Points Table';
            $title = $contentTitle . ' | D11 Cricket';
            $description = 'Current standings and points table for ' . $item['name'] . '.';
            $stmt = $pdo->prepare('SELECT p.*,t.name AS team_name,t.short_name FROM points_tables p JOIN teams t ON t.id=p.team_id WHERE p.series_id=? ORDER BY p.group_name,p.points DESC,p.net_run_rate DESC');
            $stmt->execute([$item['id']]);
            $rows = $stmt->fetchAll();
        } else {
            $kind = 'series-detail';
            $contentTitle = $item['name'];
            $title = $item['name'] . ' Schedule, Fixtures & Points Table | D11';
            $description = 'Get ' . $item['name'] . ' fixtures, match schedule, results and points table.';
            $stmt = $pdo->prepare('SELECT m.*,a.name AS team_a_name,b.name AS team_b_name FROM matches m LEFT JOIN teams a ON a.id=m.team_a_id LEFT JOIN teams b ON b.id=m.team_b_id WHERE m.series_id=? ORDER BY m.start_time_utc ASC LIMIT 200');
            $stmt->execute([$item['id']]);
            $rows = $stmt->fetchAll();
        }
    } elseif ($route === 'match' && isset($parts[1])) {
        $kind = 'match-detail';
        $stmt = $pdo->prepare('SELECT m.*,a.name AS team_a_name,b.name AS team_b_name,v.name AS venue_name,s.name AS series_name FROM matches m LEFT JOIN teams a ON a.id=m.team_a_id LEFT JOIN teams b ON b.id=m.team_b_id LEFT JOIN venues v ON v.id=m.venue_id LEFT JOIN series s ON s.id=m.series_id WHERE m.slug=? LIMIT 1');
        $stmt->execute([$parts[1]]);
        $item = $stmt->fetch();
        if (!$item) {
            http_response_code(404);
            $kind = 'notfound';
            $contentTitle = 'Match not found';
        } else {
            $contentTitle = $item['match_title'];
            $title = $item['match_title'] . ' — Live Score, Scorecard & Commentary | D11';
            $description = 'Follow ' . $item['match_title'] . ' live score, match status, venue and scorecard on D11 Cricket.';
        }
    } elseif ($route === 'team' && isset($parts[1])) {
        $kind = 'team-detail';
        $all = $pdo->query('SELECT * FROM teams ORDER BY name LIMIT 3000')->fetchAll();
        $item = null;
        foreach ($all as $candidate) if (d11_slug((string)$candidate['name']) === $parts[1] || d11_slug((string)$candidate['short_name']) === $parts[1]) { $item = $candidate; break; }
        if (!$item) { http_response_code(404); $kind='notfound'; $contentTitle='Team not found'; }
        else {
            $contentTitle = $item['name'];
            $title = $item['name'] . ' Cricket Team, Matches & Players | D11';
            $description = 'Cricket team profile, fixtures and match information for ' . $item['name'] . '.';
            $stmt = $pdo->prepare('SELECT match_title,slug,status,start_time_utc FROM matches WHERE team_a_id=? OR team_b_id=? ORDER BY start_time_utc DESC LIMIT 50');
            $stmt->execute([$item['id'],$item['id']]); $rows=$stmt->fetchAll();
        }
    } elseif ($route === 'player' && isset($parts[1])) {
        $kind = 'player-detail';
        $all = $pdo->query('SELECT * FROM players ORDER BY full_name LIMIT 5000')->fetchAll();
        $item = null;
        foreach ($all as $candidate) if (d11_slug((string)$candidate['full_name']) === $parts[1] || d11_slug((string)$candidate['display_name']) === $parts[1]) { $item = $candidate; break; }
        if (!$item) { http_response_code(404); $kind='notfound'; $contentTitle='Player not found'; }
        else {
            $contentTitle = $item['full_name'];
            $title = $item['full_name'] . ' Cricket Profile, Stats & Records | D11';
            $description = 'Cricket player profile, batting style, bowling style and playing role for ' . $item['full_name'] . '.';
        }
    } elseif ($route === '' || $route === 'index.php') {
        $kind = 'home';
        $rows = $pdo->query("SELECT m.*,a.name AS team_a_name,b.name AS team_b_name FROM matches m LEFT JOIN teams a ON a.id=m.team_a_id LEFT JOIN teams b ON b.id=m.team_b_id ORDER BY CASE WHEN m.status='live' THEN 0 ELSE 1 END,m.start_time_utc DESC LIMIT 30")->fetchAll();
    } else {
        http_response_code(404);
        $kind = 'notfound';
        $contentTitle = 'Page not found';
    }
} catch (Throwable $e) {
    http_response_code(503);
    $kind = 'error';
    $contentTitle = 'D11 is temporarily unavailable';
    $intro = 'The website could not connect to its MySQL database. Check the hosting database host, name, username, password and PHP PDO MySQL extension.';
    error_log('D11 frontend error: ' . $e->getMessage());
}

function d11_match_link(array $row): string {
    return d11_url('match/' . rawurlencode((string)$row['slug']) . '/');
}
?><!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title><?=d11_e($title)?></title><meta name="description" content="<?=d11_e($description)?>">
<link rel="canonical" href="<?=d11_e($canonical)?>">
<meta property="og:type" content="website"><meta property="og:title" content="<?=d11_e($title)?>"><meta property="og:description" content="<?=d11_e($description)?>"><meta property="og:url" content="<?=d11_e($canonical)?>">
<meta name="robots" content="<?=http_response_code()===404?'noindex,follow':'index,follow'?>">
<style>
*{box-sizing:border-box}body{margin:0;background:#071522;color:#edf5fb;font:15px/1.55 system-ui}a{color:#b8e878;text-decoration:none}a:hover{text-decoration:underline}header{background:#0c263a;border-bottom:1px solid #29465d;padding:17px max(18px,calc((100% - 1080px)/2));display:flex;justify-content:space-between;align-items:center;gap:12px}.logo{font-size:24px;font-weight:900}.logo b{color:#b7e56b}nav{display:flex;gap:16px;flex-wrap:wrap}main{max-width:1080px;margin:28px auto;padding:0 18px}.hero,.panel,.item{background:#10283b;border:1px solid #29465d;border-radius:14px;padding:20px}.hero{margin-bottom:18px}.muted{color:#9eb3c3}.list{display:grid;gap:10px}.item{display:flex;justify-content:space-between;gap:12px;align-items:center}.item strong{display:block}.tag{color:#c6e89a;font-size:12px;text-transform:uppercase}.empty{padding:24px;text-align:center;color:#9eb3c3}.table-wrap{overflow:auto}table{width:100%;border-collapse:collapse}td,th{text-align:left;padding:11px;border-bottom:1px solid #29465d;white-space:nowrap}footer{max-width:1080px;margin:35px auto;padding:0 18px 30px;color:#8fa7b9}@media(max-width:650px){header{align-items:flex-start;flex-direction:column}.item{align-items:flex-start;flex-direction:column}}
</style></head><body>
<header><a class="logo" href="<?=d11_e(d11_url())?>"><b>D11</b> CRICKET</a><nav><a href="<?=d11_e(d11_url('live-cricket-score/'))?>">Live Scores</a><a href="<?=d11_e(d11_url('series/'))?>">Series</a></nav></header>
<main><section class="hero"><div class="tag">D11 Cricket Centre</div><h1><?=d11_e($contentTitle)?></h1><p class="muted"><?=d11_e($intro)?></p></section>
<?php if ($kind==='match-detail' && !empty($item)): ?>
<section class="panel"><h2><?=d11_e(($item['team_a_name']??'TBC').' vs '.($item['team_b_name']??'TBC'))?></h2><p>Status: <?=d11_e($item['status'])?> · Format: <?=d11_e($item['format']??'Cricket')?></p><p>Venue: <?=d11_e($item['venue_name']??'Venue TBC')?></p><p>Series: <?=d11_e($item['series_name']??'')?></p><p><?=d11_e($item['result_text']??'')?></p></section>
<?php elseif ($kind==='team-detail' && !empty($item)): ?><section class="panel"><h2><?=d11_e($item['name'])?></h2><p><?=d11_e($item['short_name']??'')?></p></section><h2>Matches</h2>
<?php elseif ($kind==='player-detail' && !empty($item)): ?><section class="panel"><h2><?=d11_e($item['full_name'])?></h2><p>Role: <?=d11_e($item['playing_role']??'Not available')?> · Batting: <?=d11_e($item['batting_style']??'Not available')?> · Bowling: <?=d11_e($item['bowling_style']??'Not available')?></p></section>
<?php elseif ($kind==='points'): ?><div class="panel table-wrap"><table><thead><tr><th>Team</th><th>Played</th><th>Won</th><th>Lost</th><th>Points</th><th>NRR</th></tr></thead><tbody><?php foreach($rows as $r): ?><tr><td><?=d11_e($r['team_name'])?></td><td><?=$r['played']?></td><td><?=$r['won']?></td><td><?=$r['lost']?></td><td><?=$r['points']?></td><td><?=d11_e((string)$r['net_run_rate'])?></td></tr><?php endforeach; ?></tbody></table><?php if(!$rows): ?><p class="empty">Points table data is not available yet.</p><?php endif; ?></div>
<?php elseif ($kind==='error' || $kind==='notfound'): ?><div class="panel"><p><?=d11_e($intro)?></p></div>
<?php else: ?><section class="list">
<?php foreach($rows as $r): ?>
<article class="item"><div><strong><?php if(!empty($r['slug'])): ?><a href="<?=d11_e(d11_match_link($r))?>"><?=d11_e($r['match_title']??$r['name']??'')?></a><?php else: ?><?=d11_e($r['name']??'') ?><?php endif; ?></strong><span class="muted"><?=d11_e(($r['team_a_name']??'').' '.($r['team_b_name']??''))?> <?=d11_e($r['format']??'')?></span></div><span class="tag"><?=d11_e($r['status']??'')?></span></article>
<?php endforeach; ?>
<?php if(!$rows): ?><div class="panel empty">No records are available yet. Import cricket series and fixtures to populate this page.</div><?php endif; ?>
</section><?php endif; ?>
</main><footer>D11 Cricket · <a href="<?=d11_e(d11_url('sitemap.xml'))?>">Sitemap</a></footer></body></html>
