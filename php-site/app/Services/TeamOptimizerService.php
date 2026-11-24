<?php
declare(strict_types=1);

namespace D11\Services;

use InvalidArgumentException;
use RuntimeException;

/**
 * Constraint-safe PHP team builder with randomized tactical formations.
 *
 * Formation order is WK-BAT-AR-BOWL. A fresh random offset determines which
 * feasible formation is attempted first. Fixed/locked players are never
 * randomized or removed. The bounded variation is the average jitter over
 * non-core players in a completed XI, so the total lineup adjustment stays
 * within +/- variation_points (default 3.2).
 */
final class TeamOptimizerService
{
    private const STRATEGIES = ['strongest','safe','balanced','grand_league'];
    private const ROLE_ORDER = ['WK','BAT','AR','BOWL'];
    private const DEFAULT_FORMATIONS = [
        '1-3-4-3',
        '1-3-3-4',
        '1-2-4-4',
        '2-3-3-3',
        '1-4-3-3',
        '1-3-2-5',
        '2-3-2-4',
        '2-2-4-3',
    ];

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

        $low = 0; $known = 0;
        foreach ($chosen as $player) {
            $owned = $player['selection_pct'] ?? null;
            if (!is_numeric($owned)) return 0.0;
            $known++;
            if ((float)$owned < 50.0) $low++;
        }
        if ($known !== 11) return 0.0;

        $pattern = $low . '-' . (11 - $low);
        $frequency = 0.0; $maxFrequency = 0.0;
        foreach ($patterns as $row) {
            if (!is_array($row)) continue;
            $pct = self::num($row['pct'] ?? null);
            $maxFrequency = max($maxFrequency, $pct);
            if ((string)($row['pattern'] ?? '') === $pattern) $frequency = $pct;
        }
        if ($frequency <= 0.0 || $maxFrequency <= 0.0) return 0.0;

        // Small advisory tie-breaker; it cannot replace player evidence.
        return max(0.0, $baseScore) * 0.015 * min(1.0, $frequency / $maxFrequency);
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
        if ($strategy === 'grand_league') $value *= 1.0 + max(-0.012, min(0.012, (45.0-$ownership)/2000.0));
        $status = strtolower((string)($p['status'] ?? 'unknown'));
        $availability = in_array($status, ['playing','playing_xi','confirmed'], true) ? 1.0
            : (in_array($status, ['probable','likely','available'], true) ? 0.90 : 0.72);
        return $value * $availability * (0.90 + 0.10*$opportunity);
    }

    /** @return array{0:string,1:array<string,int>} */
    private static function normalizeFormation(mixed $raw): array
    {
        if (is_string($raw)) {
            $parts = explode('-', trim($raw));
            if (count($parts) !== 4) throw new InvalidArgumentException('Formation strings must use WK-BAT-AR-BOWL, e.g. 1-3-4-3.');
            $values = array_map(static fn($v) => filter_var($v, FILTER_VALIDATE_INT), $parts);
            if (in_array(false, $values, true)) throw new InvalidArgumentException('Formation counts must be integers.');
            $counts = array_combine(self::ROLE_ORDER, $values);
        } elseif (is_array($raw)) {
            $counts = [];
            foreach (self::ROLE_ORDER as $role) {
                $value = filter_var($raw[$role] ?? null, FILTER_VALIDATE_INT);
                if ($value === false || $value < 0) throw new InvalidArgumentException('Formation requires non-negative WK, BAT, AR and BOWL counts.');
                $counts[$role] = $value;
            }
        } else {
            throw new InvalidArgumentException('Each formation must be a WK-BAT-AR-BOWL string or role-count object.');
        }

        if (array_sum($counts) !== 11) throw new InvalidArgumentException('Every tactical formation must contain exactly 11 players.');
        return [implode('-', array_values($counts)), $counts];
    }

    /**
     * @param array $players normalized squad predictions
     * @param array $rules team_size,max_credits,max_from_one_team,min_role,max_role
     * @param array $researchHints optional TeamGeneration aggregate research hints
     * @param array $formationOptions enabled,formations,rotation_offset,variation_points,
     *        respect_min_role,search_limit_per_formation
     */
    public function generate(array $players, array $rules = [], string $strategy = 'balanced',
        array $lockedIds = [], array $excludedIds = [], ?string $manualCaptainId = null,
        ?string $manualViceCaptainId = null, bool $allowProvisional = true,
        array $researchHints = [], array $formationOptions = []): array
    {
        if (!in_array($strategy, self::STRATEGIES, true)) throw new InvalidArgumentException('Unknown optimizer strategy.');
        $rules = array_replace([
            'team_size'=>11, 'max_credits'=>100.0, 'max_from_one_team'=>7,
            'min_role'=>['WK'=>1,'BAT'=>3,'AR'=>1,'BOWL'=>3],
            'max_role'=>['WK'=>4,'BAT'=>6,'AR'=>4,'BOWL'=>6],
            'team_a'=>null, 'team_a_count'=>null, 'playing_xi_only'=>false,
        ], $rules);

        if ((int)$rules['team_size'] !== 11) {
            throw new InvalidArgumentException('The supplied tactical formations are for an 11-player team.');
        }

        $byId = [];
        foreach ($players as $p) {
            $id = (string)($p['player_id'] ?? '');
            if ($id === '' || isset($byId[$id])) throw new InvalidArgumentException('Every player needs a unique player_id.');
            $role = strtoupper((string)($p['role'] ?? ''));
            if (!in_array($role, self::ROLE_ORDER, true)) throw new InvalidArgumentException("Unsupported player role for {$id}.");
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
        if (count($lockedRows) > 11) throw new InvalidArgumentException('More locked players than team size.');
        foreach ($lockedRows as $p) {
            if (!empty($rules['playing_xi_only']) && !in_array(strtolower((string)($p['status'] ?? '')), ['playing','playing_xi','confirmed'], true)) {
                throw new InvalidArgumentException('Locked player is not confirmed in Playing XI.');
            }
        }

        $options = array_replace([
            'enabled'=>true,
            'formations'=>self::DEFAULT_FORMATIONS,
            'rotation_offset'=>null,
            'variation_points'=>3.2,
            'respect_min_role'=>false,
            'search_limit_per_formation'=>250000,
        ], $formationOptions);

        $formationEnabled = (bool)$options['enabled'];
        $variationLimit = self::num($options['variation_points'], 3.2);
        if ($variationLimit < 0.0 || $variationLimit > 3.2) {
            throw new InvalidArgumentException('variation_points must be between 0 and 3.2.');
        }
        $searchLimit = filter_var($options['search_limit_per_formation'], FILTER_VALIDATE_INT);
        if ($searchLimit === false || $searchLimit < 1) throw new InvalidArgumentException('search_limit_per_formation must be a positive integer.');

        $formations = [];
        if ($formationEnabled) {
            $rawFormations = $options['formations'];
            if (!is_array($rawFormations) || !$rawFormations) throw new InvalidArgumentException('At least one tactical formation is required.');
            foreach ($rawFormations as $rawFormation) $formations[] = self::normalizeFormation($rawFormation);
        } else {
            $formations[] = [null, null];
        }

        $offset = 0;
        if ($formationEnabled) {
            if ($options['rotation_offset'] === null) {
                $offset = random_int(0, count($formations) - 1);
            } else {
                $providedOffset = filter_var($options['rotation_offset'], FILTER_VALIDATE_INT);
                if ($providedOffset === false || $providedOffset < 0 || $providedOffset >= count($formations)) {
                    throw new InvalidArgumentException('rotation_offset must be between zero and the number of configured formations minus one.');
                }
                $offset = $providedOffset;
            }
        }

        $attemptedFormations = [];
        $totalNodes = 0;
        $best = null;
        $bestScore = -INF;
        $bestBaseScore = 0.0;
        $bestVariation = 0.0;
        $bestResearchBonus = 0.0;
        $selectedFormation = null;
        $selectedFormationCounts = null;
        $selectedNodes = 0;
        $selectedTruncated = false;
        $lockedSet = array_fill_keys($locked, true);
        $lockedCredits = array_sum(array_map(fn($p)=>(float)$p['credits'], $lockedRows));
        if ($lockedCredits > (float)$rules['max_credits']) throw new InvalidArgumentException('Locked players exceed maximum credits.');

        $attemptOrder = [];
        for ($i=0; $i<count($formations); $i++) {
            $attemptOrder[] = ($offset + $i) % count($formations);
        }

        foreach ($attemptOrder as $formationIndex) {
            [$formationLabel, $targetCounts] = $formations[$formationIndex];
            $attemptedFormations[] = $formationLabel ?? 'legacy-role-rules';

            $formationRules = $rules;
            if ($formationEnabled) {
                $lockedCounts = array_fill_keys(self::ROLE_ORDER, 0);
                foreach ($lockedRows as $row) $lockedCounts[$row['role']]++;
                $maxRole = is_array($rules['max_role'] ?? null) ? $rules['max_role'] : [];
                $minRole = is_array($rules['min_role'] ?? null) ? $rules['min_role'] : [];

                $compatible = true;
                foreach (self::ROLE_ORDER as $role) {
                    $maximum = (int)($maxRole[$role] ?? 11);
                    if ($targetCounts[$role] > $maximum || $lockedCounts[$role] > $targetCounts[$role]) {
                        $compatible = false;
                        break;
                    }
                    if (!empty($options['respect_min_role']) && $targetCounts[$role] < (int)($minRole[$role] ?? 0)) {
                        $compatible = false;
                        break;
                    }
                }
                if (!$compatible) continue;

                // A formation is an exact role-count target. It supersedes the
                // engine's default composition preference minimums; platform
                // maximum role limits remain enforced above.
                $formationRules['min_role'] = $targetCounts;
                $formationRules['max_role'] = $targetCounts;
            }

            $formationBest = null;
            $formationBestScore = -INF;
            $formationBaseScore = 0.0;
            $formationVariation = 0.0;
            $formationResearchBonus = 0.0;
            $nodes = 0;
            $limit = (int)$searchLimit;
            $search = function(int $start, array $chosen, float $credits, float $score) use (
                &$search, &$formationBest, &$formationBestScore, &$formationBaseScore,
                &$formationVariation, &$formationResearchBonus, &$nodes, $limit,
                $pool, $lockedRows, $lockedSet, $formationRules, $strategy,
                $researchHints, $variationLimit
            ): void {
                if (++$nodes > $limit) return;
                $need = (int)$formationRules['team_size'] - count($chosen);
                if ($need === 0) {
                    $counts = []; $teams = [];
                    foreach ($chosen as $p) {
                        $counts[$p['role']] = ($counts[$p['role']] ?? 0) + 1;
                        $teamKey = (string)($p['team'] ?? '');
                        $teams[$teamKey] = ($teams[$teamKey] ?? 0) + 1;
                    }
                    foreach ($formationRules['min_role'] as $role=>$minimum) {
                        if (($counts[$role] ?? 0) < (int)$minimum) return;
                    }
                    foreach ($formationRules['max_role'] as $role=>$maximum) {
                        if (($counts[$role] ?? 0) > (int)$maximum) return;
                    }
                    if ($teams && max($teams) > (int)$formationRules['max_from_one_team']) return;
                    if ($formationRules['team_a_count'] !== null &&
                        ($teams[(string)($formationRules['team_a'] ?? '')] ?? 0) !== (int)$formationRules['team_a_count']) return;

                    $nonCoreJitter = [];
                    foreach ($chosen as $player) {
                        if (!isset($lockedSet[$player['player_id']]) && $variationLimit > 0.0) {
                            $nonCoreJitter[] = random_int(
                                (int)round(-$variationLimit * 1000),
                                (int)round($variationLimit * 1000)
                            ) / 1000.0;
                        }
                    }
                    $variation = $nonCoreJitter ? array_sum($nonCoreJitter) / count($nonCoreJitter) : 0.0;
                    $researchBonus = self::researchOwnershipBonus($chosen, $researchHints, $strategy, $score);
                    $candidateScore = $score + $variation + $researchBonus;
                    if ($candidateScore > $formationBestScore) {
                        $formationBest = $chosen;
                        $formationBestScore = $candidateScore;
                        $formationBaseScore = $score;
                        $formationVariation = $variation;
                        $formationResearchBonus = $researchBonus;
                    }
                    return;
                }
                if ($start >= count($pool) || count($pool) - $start < $need) return;

                for ($i=$start; $i<=count($pool)-$need; $i++) {
                    $player = $pool[$i];
                    if (in_array($player['player_id'], array_column($chosen, 'player_id'), true)) continue;
                    $newCredits = $credits + (float)$player['credits'];
                    if ($newCredits > (float)$formationRules['max_credits']) continue;

                    $roleCount = 0; $teamCount = 0;
                    foreach ($chosen as $selected) {
                        if ($selected['role'] === $player['role']) $roleCount++;
                        if ((string)($selected['team'] ?? '') === (string)($player['team'] ?? '')) $teamCount++;
                    }
                    if ($roleCount >= (int)($formationRules['max_role'][$player['role']] ?? $formationRules['team_size'])) continue;
                    if ($teamCount >= (int)$formationRules['max_from_one_team']) continue;

                    $search($i+1, [...$chosen, $player], $newCredits, $score + self::score($player, $strategy));
                    if ($nodes > $limit) return;
                }
            };

            $search(0, $lockedRows, $lockedCredits, array_sum(array_map(fn($p)=>self::score($p,$strategy), $lockedRows)));
            $totalNodes += $nodes;
            if ($formationBest !== null) {
                $best = $formationBest;
                $bestScore = $formationBestScore;
                $bestBaseScore = $formationBaseScore;
                $bestVariation = $formationVariation;
                $bestResearchBonus = $formationResearchBonus;
                $selectedFormation = $formationLabel;
                $selectedFormationCounts = $targetCounts;
                $selectedNodes = $nodes;
                $selectedTruncated = $nodes > $limit;
                break;
            }
        }

        if ($best === null) {
            throw new RuntimeException(
                'No legal XI could be built from the configured tactical formations. Check locked core roles, squad depth, credits, team limits, and search budget.'
            );
        }

        $bestIds = array_column($best, 'player_id');
        if ($manualCaptainId !== null && !in_array($manualCaptainId, $bestIds, true)) throw new InvalidArgumentException('Manual captain must be in the selected XI.');
        if ($manualViceCaptainId !== null && !in_array($manualViceCaptainId, $bestIds, true)) throw new InvalidArgumentException('Manual vice-captain must be in the selected XI.');

        // C/VC ranking deliberately uses the unrandomized player score.
        $ranked = $best;
        usort($ranked, fn($a,$b)=>self::score($b,$strategy)<=>self::score($a,$strategy));
        $captain = $manualCaptainId !== null ? $byId[$manualCaptainId] : $ranked[0];
        $viceCandidates = array_values(array_filter($ranked, fn($p)=>$p['player_id'] !== $captain['player_id']));
        if ($manualViceCaptainId !== null) {
            $vice = current(array_filter($viceCandidates, fn($p)=>$p['player_id'] === $manualViceCaptainId));
            if (!$vice) throw new InvalidArgumentException('Manual vice-captain must be in the selected XI.');
        } else {
            $vice = $viceCandidates[0] ?? null;
        }
        if (!$vice) throw new RuntimeException('Could not select distinct captain and vice-captain.');

        $roleCounts = []; $teamCounts = [];
        foreach ($best as $p) {
            $roleCounts[$p['role']] = ($roleCounts[$p['role']] ?? 0) + 1;
            $teamKey = (string)($p['team'] ?? '');
            $teamCounts[$teamKey] = ($teamCounts[$teamKey] ?? 0) + 1;
        }
        $totalCredits = array_sum(array_map(fn($p)=>(float)$p['credits'], $best));

        return [
            'strategy'=>$strategy,
            'players'=>$best,
            'captain_id'=>$captain['player_id'],
            'vice_captain_id'=>$vice['player_id'],
            'total_credits'=>round($totalCredits,2),
            'team_strength_score'=>round($bestScore,3),
            'base_team_score'=>round($bestBaseScore,3),
            'role_counts'=>$roleCounts,
            'team_split'=>$teamCounts,
            'formation'=>$selectedFormation,
            'formation_role_order'=>'WK-BAT-AR-BOWL',
            'formation_role_counts'=>$selectedFormationCounts,
            'diagnostics'=>[
                'search_nodes'=>$selectedNodes,
                'total_search_nodes'=>$totalNodes,
                'search_limit_per_formation'=>$limit,
                'search_truncated'=>$selectedTruncated,
                'formation_rotation_offset'=>$offset,
                'formation_attempt_order'=>$attemptedFormations,
                'selected_formation'=>$selectedFormation,
                'locked_player_ids'=>$locked,
                'excluded_player_ids'=>$excluded,
                'fixed_core_preserved'=>true,
                'non_core_variation_points'=>round($bestVariation,3),
                'non_core_variation_limit'=>round($variationLimit,3),
                'research_ownership_prior_applied'=>$bestResearchBonus > 0.0,
                'research_ownership_prior_bonus'=>round($bestResearchBonus,4),
                'research_hint_sample_matches'=>(int)($researchHints['sample_matches'] ?? 0),
                'provisional'=>count(array_filter($best,fn($p)=>($p['expected_points']??null)===null))>0,
                'score_meaning'=>'selection-priority score; not a guaranteed fantasy-points outcome',
            ],
        ];
    }
}
