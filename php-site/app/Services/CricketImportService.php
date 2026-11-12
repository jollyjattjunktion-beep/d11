<?php
declare(strict_types=1);
namespace D11\Services;
use PDO;
use RuntimeException;

final class CricketImportService {
    public function __construct(private PDO $db) {}
    private function identity(array $r): array {
        $s=trim((string)($r['external_source']??'')); $e=trim((string)($r['external_id']??''));
        if($s===''||$e==='') throw new RuntimeException('external_source and external_id are required.');
        if(!preg_match('/^[a-z0-9_.-]{2,60}$/i',$s)) throw new RuntimeException('Invalid source key.');
        return [$s,$e];
    }
    private function upsert(string $table,array $r,array $allowed):int {
        [$s,$e]=$this->identity($r);$v=array_intersect_key($r,array_flip($allowed));$v['external_source']=$s;$v['external_id']=$e;
        $q=$this->db->prepare("SELECT id FROM `$table` WHERE external_source=? AND external_id=? LIMIT 1");$q->execute([$s,$e]);$id=$q->fetchColumn();
        if($id){$sets=[];$args=[];foreach($v as $k=>$x){if(in_array($k,['external_source','external_id'],true))continue;$sets[]="`$k`=?";$args[]=$x;}if($sets){$args[]=(int)$id;$q=$this->db->prepare("UPDATE `$table` SET ".implode(',',$sets)." WHERE id=?");$q->execute($args);}return(int)$id;}
        $cols=array_keys($v);$colsQ=array_map(static fn($c)=>"`$c`",$cols);$marks=implode(',',array_fill(0,count($cols),'?'));$q=$this->db->prepare("INSERT INTO `$table` (".implode(',',$colsQ).") VALUES ($marks)");$q->execute(array_values($v));return(int)$this->db->lastInsertId();
    }
    public function importCompetition(array $r):int{return $this->upsert('competitions',$r,['name','slug','format','season','gender','status']);}
    public function importTeam(array $r):int{return $this->upsert('teams',$r,['name','short_name','country_id','team_type','logo_path']);}
    public function importVenue(array $r):int{[$s,$e]=$this->identity($r);$q=$this->db->prepare('SELECT id,is_manually_verified FROM venues WHERE external_source=? AND external_id=? LIMIT 1');$q->execute([$s,$e]);$v=$q->fetch(PDO::FETCH_ASSOC);if($v&&(int)$v['is_manually_verified']===1)return(int)$v['id'];return $this->upsert('venues',$r,['name','city','region','country_id','address','timezone','latitude','longitude']);}
    public function importPlayer(array $r):int{return $this->upsert('players',$r,['full_name','display_name','date_of_birth','batting_style','bowling_style','playing_role','country_id','image_path']);}
    public function importSeries(array $r):int{return $this->upsert('series',$r,['competition_id','name','slug','format','start_date','end_date','status','source_url']);}
    public function importMatch(array $r):int{[$s,$e]=$this->identity($r);$q=$this->db->prepare('SELECT id,venue_manually_set,venue_id FROM matches WHERE external_source=? AND external_id=? LIMIT 1');$q->execute([$s,$e]);$m=$q->fetch(PDO::FETCH_ASSOC);if($m&&(int)$m['venue_manually_set']===1)$r['venue_id']=$m['venue_id'];return $this->upsert('matches',$r,['series_id','competition_id','team_a_id','team_b_id','venue_id','match_number','match_title','slug','format','gender','start_time_utc','timezone','status','toss_winner_team_id','toss_decision','result_text','source_url','last_source_sync_at']);}
    public function importDataset(array $data):array {
        $map=['competitions'=>['competitions','importCompetition'],'teams'=>['teams','importTeam'],'venues'=>['venues','importVenue'],'players'=>['players','importPlayer'],'series'=>['series','importSeries'],'matches'=>['matches','importMatch']];
        foreach($data as $k=>$records){if(!isset($map[$k])||!is_array($records)||!array_is_list($records))throw new RuntimeException("Invalid dataset section: $k");if(count($records)>500)throw new RuntimeException("Maximum 500 records per section.");foreach($records as $r){if(!is_array($r))throw new RuntimeException("Records in $k must be objects.");$this->identity($r);}}
        $totals=[];$this->db->beginTransaction();try{foreach($map as $section=>[$table,$method]){$created=0;$updated=0;$records=$data[$section]??[];foreach($records as $r){[$s,$e]=$this->identity($r);$q=$this->db->prepare("SELECT id FROM `$table` WHERE external_source=? AND external_id=? LIMIT 1");$q->execute([$s,$e]);$exists=(bool)$q->fetchColumn();$this->$method($r);$exists?$updated++:$created++;}$totals[$section]=['seen'=>count($records),'created'=>$created,'updated'=>$updated];}$this->db->commit();}catch(\Throwable $e){if($this->db->inTransaction())$this->db->rollBack();throw $e;}return $totals;
    }
}
