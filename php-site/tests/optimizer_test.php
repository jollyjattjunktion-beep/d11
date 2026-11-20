<?php
declare(strict_types=1);
require dirname(__DIR__).'/app/Services/TeamOptimizerService.php';
use D11\Services\TeamOptimizerService;

$players=[];
$roles=['WK','WK','BAT','BAT','BAT','BAT','BAT','BAT','BAT','BAT','AR','AR','AR','AR','BOWL','BOWL','BOWL','BOWL','BOWL','BOWL','BOWL','BOWL'];
foreach ($roles as $i=>$role) {
    $players[]=['player_id'=>'P'.($i+1),'player_name'=>'Player '.($i+1),'team'=>$i%2?'B':'A',
        'role'=>$role,'credits'=>($i%3===0?9.5:8.5),'expected_points'=>35+($i*2),
        'floor_points'=>20+($i*1.2),'ceiling_points'=>55+($i*2),'consistency'=>0.6,
        'status'=>'playing_xi','selection_pct'=>45];
}
$engine=new TeamOptimizerService();
foreach (['strongest','safe','balanced','grand_league'] as $strategy) {
    $team=$engine->generate($players,[],$strategy,['P1'],['P22']);
    if (count($team['players'])!==11) throw new RuntimeException('Team size regression: '.$strategy);
    if (!in_array('P1',array_column($team['players'],'player_id'),true)) throw new RuntimeException('Locked player omitted.');
    if (in_array('P22',array_column($team['players'],'player_id'),true)) throw new RuntimeException('Excluded player selected.');
    if ($team['captain_id']===$team['vice_captain_id']) throw new RuntimeException('C/VC must differ.');
    if ($team['total_credits']>100.0) throw new RuntimeException('Credit cap exceeded.');
    foreach ($team['role_counts'] as $role=>$count) {
        if ($count>(['WK'=>4,'BAT'=>6,'AR'=>4,'BOWL'=>6][$role]??11)) throw new RuntimeException('Role maximum exceeded.');
    }
    if (max($team['team_split'])>7) throw new RuntimeException('Team maximum exceeded.');
}
$failed=false;
try { $engine->generate($players,[],'balanced',['P1'],['P1']); } catch (InvalidArgumentException) { $failed=true; }
if (!$failed) throw new RuntimeException('Lock/exclude conflict must fail.');
$failed=false;
try { $engine->generate($players,[],'balanced',[],[], 'P22'); } catch (InvalidArgumentException|RuntimeException) { $failed=true; }
if (!$failed) throw new RuntimeException('Invalid manual captain must fail.');
$failed=false;
try { $engine->generate($players,[],'balanced',[],[],null,null,false); } catch (InvalidArgumentException) { $failed=true; }
if (!$failed) throw new RuntimeException('AI mode must reject provisional candidates.');
echo "PHP optimizer tests passed.\n";
