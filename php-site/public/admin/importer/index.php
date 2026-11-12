<?php
declare(strict_types=1);
require dirname(__DIR__,3).'/app/bootstrap.php';
require dirname(__DIR__,3).'/app/admin_auth.php';
require dirname(__DIR__,3).'/app/Services/CricketImportService.php';
$admin=d11_require_admin();$pdo=d11_db();$csrf=d11_admin_csrf();$error='';$message='';$summary=null;
$allowed=['competitions','teams','venues','players','series','matches'];
if($_SERVER['REQUEST_METHOD']==='POST'){
 if(!d11_admin_check_csrf())$error='Security token expired. Refresh and retry.';
 else try{
  $raw=(string)($_POST['dataset_json']??'');if(strlen($raw)>1048576)throw new RuntimeException('Maximum JSON size is 1 MB.');
  $data=json_decode($raw,true,64,JSON_THROW_ON_ERROR);if(!is_array($data)||array_is_list($data))throw new RuntimeException('JSON root must be an object containing record arrays.');
  $source=trim((string)($_POST['source_key']??'manual_import'));if(!preg_match('/^[a-z0-9_.-]{2,60}$/i',$source))throw new RuntimeException('Invalid source key.');
  foreach($data as $section=>&$records){if(!in_array($section,$allowed,true)||!is_array($records)||!array_is_list($records))throw new RuntimeException('Allowed sections: '.implode(', ',$allowed));foreach($records as &$record){if(!is_array($record))throw new RuntimeException('Every record must be an object.');$record['external_source']=$source;}unset($record);}unset($records);
  if(($_POST['action']??'')==='import'){
   $totals=(new \D11\Services\CricketImportService($pdo))->importDataset($data);$seen=$created=$updated=0;foreach($totals as $v){$seen+=$v['seen'];$created+=$v['created'];$updated+=$v['updated'];}
   $now=gmdate('Y-m-d H:i:s');$q=$pdo->prepare("INSERT INTO import_logs(source_key,entity_type,status,records_seen,records_created,records_updated,message,started_at,finished_at) VALUES(?,'dataset','success',?,?,?,?,?,?)");$q->execute([$source,$seen,$created,$updated,'Dataset import completed',$now,$now]);$summary=$totals;$message="Import completed: $created created, $updated updated, $seen processed.";
  }else{$summary=[];foreach($data as $k=>$v)$summary[$k]=['seen'=>count($v)];}
 }catch(\Throwable $e){$error='Import failed: '.$e->getMessage();error_log('D11 importer: '.$e->getMessage());try{$now=gmdate('Y-m-d H:i:s');$q=$pdo->prepare("INSERT INTO import_logs(source_key,entity_type,status,message,started_at,finished_at) VALUES(?,'dataset','failed',?,?,?)");$q->execute([substr((string)($_POST['source_key']??'unknown'),0,60),$e->getMessage(),$now,$now]);}catch(\Throwable $ignored){}}
}
$logs=$pdo->query('SELECT id,source_key,entity_type,status,records_seen,records_created,records_updated,message,created_at FROM import_logs ORDER BY id DESC LIMIT 15')->fetchAll();
?><!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>D11 Cricket Importer</title><style>*{box-sizing:border-box}body{margin:0;background:#071522;color:#edf5fb;font:15px/1.5 system-ui}a{color:#b7e56b;text-decoration:none}header{background:#0d2639;padding:18px max(18px,calc((100% - 1080px)/2));display:flex;justify-content:space-between}main{max-width:1080px;margin:28px auto;padding:0 18px}.card{background:#10283b;border:1px solid #28485f;border-radius:13px;padding:18px;margin:14px 0}.muted{color:#9bb1c2}label{display:block;margin:12px 0 5px}input,textarea{width:100%;padding:12px;border:1px solid #36556e;border-radius:8px;background:#091a29;color:white;font:14px/1.5 monospace}textarea{min-height:260px}.btn{padding:11px 16px;border:0;border-radius:8px;background:#b7e56b;color:#10200b;font-weight:800;margin:12px 8px 0 0}.secondary{background:#29485f;color:white}.alert{padding:13px;border-radius:9px;background:#173f2b}.bad{background:#5b2027}.table{width:100%;border-collapse:collapse}.table td,.table th{text-align:left;padding:9px;border-bottom:1px solid #28485f}.scroll{overflow:auto}.pill{display:inline-block;background:#19364d;border-radius:20px;padding:4px 9px;margin:3px}</style></head><body>
<header><strong><span style="color:#b7e56b">D11</span> ADMIN · IMPORTER</strong><a href="/admin/dashboard/">Dashboard</a></header><main><h1>Cricket Data Importer</h1><p class="muted">Import provider-normalised cricket records safely into your existing MySQL database. Re-imports update matching external IDs; manually verified venues are preserved.</p>
<?php if($message):?><p class="alert"><?=d11_e($message)?></p><?php endif;?><?php if($error):?><p class="alert bad"><?=d11_e($error)?></p><?php endif;?>
<section class="card"><h2>Import dataset (JSON)</h2><p class="muted">Preview validates without saving cricket records. Import runs in one transaction. Maximum 500 records per section, 1 MB per request.</p><form method="post"><input type="hidden" name="csrf" value="<?=d11_e($csrf)?>"><label>Source key</label><input name="source_key" required pattern="[A-Za-z0-9_.-]{2,60}" value="<?=d11_e($_POST['source_key']??'manual_import')?>"><label>Dataset JSON</label><textarea name="dataset_json" required spellcheck="false"><?=d11_e($_POST['dataset_json']??'{
  "competitions": [],
  "teams": [],
  "venues": [],
  "players": [],
  "series": [],
  "matches": []
}')?></textarea><button class="btn secondary" name="action" value="preview">Validate / Preview</button><button class="btn" name="action" value="import" onclick="return confirm('Import these records into this D11 MySQL database?');">Import records</button></form></section>
<?php if($summary!==null):?><section class="card"><h2>Dataset summary</h2><?php foreach($summary as $k=>$v):?><span class="pill"><?=d11_e($k)?>: <?=$v['seen']?><?php if(isset($v['created'])):?> · +<?=$v['created']?> / updated <?=$v['updated']?><?php endif;?></span><?php endforeach;?></section><?php endif;?>
<section class="card"><h2>Recent import history</h2><div class="scroll"><table class="table"><thead><tr><th>Date</th><th>Source</th><th>Type</th><th>Status</th><th>Seen</th><th>Created</th><th>Updated</th></tr></thead><tbody><?php foreach($logs as $r):?><tr><td><?=d11_e($r['created_at'])?></td><td><?=d11_e($r['source_key'])?></td><td><?=d11_e($r['entity_type'])?></td><td><?=d11_e($r['status'])?></td><td><?=$r['records_seen']?></td><td><?=$r['records_created']?></td><td><?=$r['records_updated']?></td></tr><?php endforeach;?><?php if(!$logs):?><tr><td colspan="7" class="muted">No import history.</td></tr><?php endif;?></tbody></table></div></section>
<section class="card"><h2>Provider contract</h2><p class="muted">Accepted sections: competitions, teams, venues, players, series, matches. Each record needs external_id; the source key is applied as external_source. Foreign keys must be local D11 IDs. Automatic external discovery is not activated by this manual JSON importer. Connect an official/licensed data feed or provider adapter whose terms permit automated collection and republication.</p></section></main></body></html>
