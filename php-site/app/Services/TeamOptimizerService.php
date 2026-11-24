<?php
declare(strict_types=1);

namespace D11\Services;

use InvalidArgumentException;
use RuntimeException;

/**
 * Constraint-safe PHP team builder.
 *
 * This is a deterministic first implementation of the optimizer contract.
 * It intentionally exposes strategy scoring and diagnostics separately from
 * provider ingestion. Python golden parity is a release gate, not implied here.
 */
final class TeamOptimizerService
{
    private const STRATEGIES = ['strongest','safe','balanced','grand_league'];

    private static function num(mixed $v, float $default = 0.0): float
    {
        return is_numeric($v) ? (float)$v : $default;
    }

    /**
     * Tiny portfolio-level tie-breaker for Grand League only.
     * percentageSplitFreq is interpreted as low-owned/high-owned because the
     * same payload explicitly reports avgLowOwned and avgHighOwned.
     * It is ignored unless every selected player has a selection percentage.
     */
    private static function researchOwnershipBonus(array $chosen, array $researchHints, string $strategy, float $baseScore): float
    {
        if ($strategy !== 'grand_league' || count($chosen) !== 11) return 0.0;
        if ((int)($researchHints['sample_matches'] ?? 0) < 30) return 0.0;
        $patterns = $researchHints['ownership_percentage_split_frequency'] ?? [];
        if (!is_array($patterns) || !$patterns) return 0.0;

        $low = 0; $high = 0; $known = 0;
        foreach ($chosen as $player) {
            $owned = $player['selection_pct'] ?? null;
            if (!is_numeric($owned)) return 0.0;
            $known++;
            if ((float)$owned < 50.0) $low++;
            else $high++;
        }
        if ($known !== 11) return 0.0;

        $pattern = $low . '-' . $high;
        $frequency = 0.0; $maxFrequency = 0.0;
        foreach ($patterns as $row) {
            if (!is_array($row)) continue;
            $pct = self::num($row['pct'] ?? null);
            $maxFrequency = max($maxFrequency, $pct);
            if ((string)($row['pattern'] ?? '') === $pattern) $frequency = $pct;
        }
        if ($frequency <= 0.0 || $maxFrequency <= 0.0) return 0.0;

        // Maximum +0.5% of the lineup score: a tie-breaker, never a substitute
        // for expected points, role constraints, availability or player evidence.
        return max(0.0, $baseScore) * 0.005 * min(1.0, $frequency / $maxFrequency);
    }

    private static function score(array $p, string $strategy): float
    {
        $expected = $p['expected_points'] ?? null;
        $ownership = max(0.0, min(100.0, self::num($p['selection_pct'] ?? null, 50.0)));
        $rolePrior = 0.60;
        $position = (int)($p['batting_position'] ?? 0);
        if ($position > 0) $rolePrior += max(-0.18, min(0.18, (5 - $position) * 0.035));
        $overs = self::num($p['expected_overs'] ?? null, 2.0);
        $rolePrior += max(-0.10, min(0.18, ($overs - 2.0) * 0.06));
        $opportunity = max(0.25, min(1.0, $rolePrior));
        if ($expected === null) {
            $roleScore = self::num($p['ai11_role_score'] ?? null, 50.0);
            $recent = self::num($p['ai11_recent_form_score'] ?? $p['recent_history_score'] ?? null, 50.0);
            $base = 34.0 + 0.66 * (0.7 * $roleScore + 0.3 * $recent) + 10.0 * $opportunity;
            $floor = $base * 0.55;
            $ceiling = $base * (($p['role'] ?? '') === 'AR' && !empty($p['ai11_two_skill_profile']) ? 1.12 : 1.08);
            $consistency = 0.35;
        } else {
            $base = max(0.0, self::num($expected));
            $floor = max(0.0, self::num($p['floor_points'] ?? null, $base * 0.55));
            $ceiling = max($base, self::num($p['ceiling_points'] ?? $p['upside'] ?? null, $base * 1.35));
            $consistency = max(0.0, min(1.0, self::num($p['consistency'] ?? null)));
        }
        $upside = max($base, $ceiling);
        $value = match ($strategy) {
            'strongest' => 0.78*$base + 0.08*$floor + 0.14*$upside,
            'safe' => (0.72*$base + 0.22*$floor + 0.06*$upside) * (1.0 + 0.10*$consistency),
            'grand_league' => 0.40*$base + 0.60*$upside,
            default => 0.62*$base + 0.18*$floor + 0.20*$upside,
        };
        if (($p['risk'] ?? '') === 'high') {
            $value *= $strategy === 'safe' ? 0.86 : ($strategy === 'grand_league' ? 1.035 : ($strategy === 'strongest' ? 0.97 : 0.94));
        }
        if ($strategy === 'grand_league') $value *= 1.0 + max(-0.045, min(0.055, (45.0-$ownership)/1000.0));
        $status = strtolower((string)($p['status'] ?? 'unknown'));
        $availability = in_array($status, ['playing','playing_xi','confirmed'], true) ? 1.0
            : (in_array($status, ['probable','likely','available'], true) ? 0.90 : 0.72);
        return $value * $availability * (0.90 + 0.10*$opportunity);
    }

    /**
     * @param array $players normalized squad predictions
     * @param array $rules team_size,max_credits,max_from_one_team,min_role,max_role
     */
    public function generate(array $players, array $rules = [], string $strategy = 'balanced',
        array $lockedIds = [], array $excludedIds = [], ?string $manualCaptainId = null,
        ?string $manualViceCaptainId = null, bool $allowProvisional = true,
        array $researchHints = []): array
    {
        if (!in_array($strategy, self::STRATEGIES, true)) throw new InvalidArgumentException('Unknown optimizer strategy.');
        $rules = array_replace([
            'team_size'=>11, 'max_credits'=>100.0, 'max_from_one_team'=>7,
            'min_role'=>['WK'=>1,'BAT'=>3,'AR'=>1,'BOWL'=>3],
            'max_role'=>['WK'=>4,'BAT'=>6,'AR'=>4,'BOWL'=>6],
            'team_a'=>null, 'team_a_count'=>null, 'playing_xi_only'=>false,
        ], $rules);
        $byId = [];
        foreach ($players as $p) {
            $id = (string)($p['player_id'] ?? '');
            if ($id === '' || isset($byId[$id])) throw new InvalidArgumentException('Every player needs a unique player_id.');
            $role = strtoupper((string)($p['role'] ?? ''));
            if (!in_array($role, ['WK','BAT','AR','BOWL'], true)) throw new InvalidArgumentException("Unsupported player role for {$id}.");
            if (!is_numeric($p['credits'] ?? null) || (float)$p['credits'] <= 0) throw new InvalidArgumentException("Missing/invalid credits for {$id}.");
            if (!$allowProvisional && ($p['expected_points'] ?? null) === null) throw new InvalidArgumentException('AI Prediction mode requires numeric expected points for every candidate.');
            $p['role'] = $role; $p['player_id'] = $id; $byId[$id] = $p;
        }
        $locked = array_values(array_unique(array_map('strval', $lockedIds)));
        $excluded = array_values(array_unique(array_map('strval', $excludedIds)));
        if (array_intersect($locked, $excluded)) throw new InvalidArgumentException('A player cannot be both locked and excluded.');
        foreach ($locked as $id) if (!isset($byId[$id])) throw new InvalidArgumentException('Locked player is not in the match squad.');
        if ($manualCaptainId !== null && $manualCaptainId === $manualViceCaptainId) throw new InvalidArgumentException('Captain and vice-captain must be different.');
        foreach ([$manualCaptainId,$manualViceCaptainId] as $id) if ($id !== null && !isset($byId[$id])) throw new InvalidArgumentException('Manual leadership choice is not in the squad.');

        $pool = array_values(array_filter($byId, fn($p) => !in_array($p['player_id'], $excluded, true)));
        $lockedRows = array_map(fn($id) => $byId[$id], $locked);
        if (count($lockedRows) > (int)$rules['team_size']) throw new InvalidArgumentException('More locked players than team size.');
        foreach ($lockedRows as $p) {
            if (!empty($rules['playing_xi_only']) && !in_array(strtolower((string)($p['status'] ?? '')), ['playing','playing_xi','confirmed'], true)) throw new InvalidArgumentException('Locked player is not confirmed in Playing XI.');
        }
        $best = null; $bestScore = -INF; $bestResearchBonus = 0.0; $nodes = 0; $limit = 250000;
        $search = function(int $start, array $chosen, float $credits, float $score) use (&$search,&$best,&$bestScore,&$bestResearchBonus,&$nodes,$limit,$pool,$lockedRows,$rules,$strategy,$researchHints): void {
            if (++$nodes > $limit) return;
            $need = (int)$rules['team_size'] - count($chosen);
            if ($need === 0) {
                $counts=[]; $teams=[];
                foreach ($chosen as $p) { $counts[$p['role']]=($counts[$p['role']]??0)+1; $teams[$p['team']??'']=($teams[$p['team']??'']??0)+1; }
                foreach ($rules['min_role'] as $r=>$n) if (($counts[$r]??0)<$n) return;
                foreach ($rules['max_role'] as $r=>$n) if (($counts[$r]??0)>$n) return;
                if ($teams && max($teams)>(int)$rules['max_from_one_team']) return;
                if ($rules['team_a_count'] !== null && ($teams[$rules['team_a']??'']??0)!==(int)$rules['team_a_count']) return;
                $researchBonus = self::researchOwnershipBonus($chosen, $researchHints, $strategy, $score);
                $candidateScore = $score + $researchBonus;
                if ($candidateScore>$bestScore) {
                    $best=$chosen; $bestScore=$candidateScore; $bestResearchBonus=$researchBonus;
                }
                return;
            }
            if ($start >= count($pool) || count($pool)-$start < $need) return;
            for ($i=$start; $i<=count($pool)-$need; $i++) {
                $p=$pool[$i];
                if (in_array($p['player_id'], array_column($chosen,'player_id'), true)) continue;
                $newCredits=$credits+(float)$p['credits'];
                if ($newCredits>(float)$rules['max_credits']) continue;
                $roleCount=0; $teamCount=0;
                foreach ($chosen as $q) { if ($q['role']===$p['role']) $roleCount++; if (($q['team']??'')===($p['team']??'')) $teamCount++; }
                if ($roleCount >= (int)($rules['max_role'][$p['role']] ?? $rules['team_size'])) continue;
                if ($teamCount >= (int)$rules['max_from_one_team']) continue;
                $search($i+1, [...$chosen,$p], $newCredits, $score+self::score($p,$strategy));
                if ($nodes>$limit) return;
            }
        };
        $lockedCredits=array_sum(array_map(fn($p)=>(float)$p['credits'],$lockedRows));
        if ($lockedCredits>(float)$rules['max_credits']) throw new InvalidArgumentException('Locked players exceed maximum credits.');
        $lockedScore=array_sum(array_map(fn($p)=>self::score($p,$strategy),$lockedRows));
        $search(0,$lockedRows,$lockedCredits,$lockedScore);
        if ($best===null) throw new RuntimeException('No legal XI found within search limit; verify squad depth and constraints.');
        $bestIds=array_column($best,'player_id');
        if ($manualCaptainId !== null && !in_array($manualCaptainId,$bestIds,true)) throw new InvalidArgumentException('Manual captain must be in the selected XI.');
        if ($manualViceCaptainId !== null && !in_array($manualViceCaptainId,$bestIds,true)) throw new InvalidArgumentException('Manual vice-captain must be in the selected XI.');
        $ranked=$best;
        usort($ranked, fn($a,$b)=>self::score($b,$strategy)<=>self::score($a,$strategy));
        $captain = $manualCaptainId !== null ? $byId[$manualCaptainId] : $ranked[0];
        $viceCandidates=array_values(array_filter($ranked,fn($p)=>$p['player_id']!==$captain['player_id']));
        if ($manualViceCaptainId !== null) {
            $vice = current(array_filter($viceCandidates,fn($p)=>$p['player_id']===$manualViceCaptainId));
            if (!$vice) throw new InvalidArgumentException('Manual vice-captain must be in the selected XI.');
        } else { $vice=$viceCandidates[0]??null; }
        if (!$vice) throw new RuntimeException('Could not select distinct captain and vice-captain.');
        $roleCounts=[]; $teamCounts=[];
        foreach ($best as $p) { $roleCounts[$p['role']]=($roleCounts[$p['role']]??0)+1; $teamCounts[$p['team']??'']=($teamCounts[$p['team']??'']??0)+1; }
        return [
            'strategy'=>$strategy,'players'=>$best,'captain_id'=>$captain['player_id'],'vice_captain_id'=>$vice['player_id'],
            'total_credits'=>round($lockedCredits + array_sum(array_map(fn($p)=>(float)$p['credits'],array_filter($best,fn($p)=>!in_array($p['player_id'],$locked,true)))),2),
            'team_strength_score'=>round($bestScore,3),'role_counts'=>$roleCounts,'team_split'=>$teamCounts,
            'diagnostics'=>['search_nodes'=>$nodes,'search_limit'=>$limit,'search_truncated'=>$nodes>$limit,
                'locked_player_ids'=>$locked,'excluded_player_ids'=>$excluded,'provisional'=>count(array_filter($best,fn($p)=>($p['expected_points']??null)===null))>0,
                'research_ownership_prior_applied'=>$bestResearchBonus > 0.0,
                'research_ownership_prior_bonus'=>round($bestResearchBonus,4),
                'research_hint_sample_matches'=>(int)($researchHints['sample_matches'] ?? 0),
                'score_meaning'=> 'selection-priority score; not a guaranteed fantasy-points outcome']
        ];
    }
}
