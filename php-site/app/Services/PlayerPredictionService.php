<?php
declare(strict_types=1);

namespace D11\Services;

use PDO;
use RuntimeException;

/**
 * PHP port of app/predictor.py (hybrid-context-stat-v2).
 * Historical fantasy points are required before numeric point projections
 * are emitted; AI11 career aggregates remain bounded supporting evidence only.
 */
final class PlayerPredictionService
{
    public const MODEL_VERSION = 'hybrid-pitch-stat-v3';

    public function __construct(private PDO $db) {}

    private static function bounded(float $v, float $low, float $high): float {
        return max($low, min($high, $v));
    }
    private static function number(mixed $v): ?float {
        return is_numeric($v) ? (float)$v : null;
    }
    private static function weightedMean(array $values): float {
        if (!$values) return 0.0;
        $sum = 0.0; $weights = 0.0;
        foreach (array_values($values) as $i => $value) {
            $w = 0.84 ** $i; $sum += (float)$value * $w; $weights += $w;
        }
        return $weights > 0 ? $sum / $weights : 0.0;
    }
    private static function condition(string $role, array $context): array {
        $factor = 1.0; $reasons = [];
        foreach ([
            ['field' => 'batting_friendly', 'roles' => ['BAT','WK','AR'], 'weight' => 0.12, 'positive' => 'Pitch batting suitability positive', 'negative' => 'Pitch batting suitability negative'],
            ['field' => 'pace_friendly', 'roles' => ['BOWL','AR'], 'weight' => 0.08, 'positive' => 'Pace conditions favour seam bowling', 'negative' => 'Pace conditions less favourable to pace'],
            ['field' => 'spin_friendly', 'roles' => ['BOWL','AR'], 'weight' => 0.08, 'positive' => 'Spin conditions favour spin bowling', 'negative' => 'Spin conditions less favourable to spin'],
        ] as $rule) {
            $value = self::number($context[$rule['field']] ?? null);
            if ($value !== null && in_array($role, $rule['roles'], true)) {
                $delta = ($value - 0.5) * $rule['weight'];
                $factor += $delta;
                if (abs($delta) >= 0.015) $reasons[] = $delta > 0 ? $rule['positive'] : $rule['negative'];
            }
        }
        if (($context['dew_likely'] ?? false) === true && in_array($role, ['BOWL','AR'], true)) {
            $factor *= 0.97; $reasons[] = 'Dew may make bowling control more difficult';
        }
        $rain = self::number($context['rain_probability'] ?? null);
        if ($rain !== null && $rain >= 50) { $factor *= 0.96; $reasons[] = 'Rain risk may reduce available playing time'; }
        return [self::bounded($factor, 0.82, 1.18), $reasons];
    }
    private static function form(array $rows, string $format): array {
        $values = [];
        foreach ($rows as $row) if ($row['fantasy_points'] !== null) $values[] = (float)$row['fantasy_points'];
        $baseline = ['T20'=>42.0,'ODI'=>52.0,'TEST'=>60.0][$format] ?? 42.0;
        $mean = $values ? self::weightedMean($values) : null;
        $historyScore = null;
        if ($mean !== null) {
            $raw = self::bounded(50.0 + (($mean / $baseline) - 1.0) * 32.0, 0.0, 100.0);
            $reliability = min(1.0, count($values) / 3.0);
            $historyScore = round(50.0 + ($raw - 50.0) * $reliability, 1);
        }
        if (count($values) < 3) return [
            'expected_points'=>null,'floor_points'=>null,'ceiling_points'=>null,
            'consistency'=>0.0,'upside'=>0.0,'confidence_score'=>0,
            'confidence'=>'insufficient_data','risk'=>'unknown','matches_used'=>count($values),
            'recent_history_score'=>$historyScore,'recent_history_mean'=>$mean === null ? null : round($mean,2),
        ];
        $variance = self::weightedMean(array_map(fn($v) => ($v - $mean) ** 2, $values));
        $sd = sqrt(max($variance, 0.0));
        $expected = max(0.0, $mean);
        $floor = max(0.0, $expected - 0.84 * $sd);
        $ceiling = max($expected, $expected + 1.28 * $sd);
        $coverage = min(1.0, count($values) / 10.0);
        $stability = 1.0 / (1.0 + $sd / max($mean, 1.0));
        $confidenceScore = (int)round(100 * (0.55 * $coverage + 0.45 * $stability));
        $confidence = $confidenceScore >= 75 ? 'high' : ($confidenceScore >= 50 ? 'medium' : 'low');
        $risk = $sd > max($mean * 0.8, 1) ? 'high' : ($sd > max($mean * 0.4, 1) ? 'medium' : 'low');
        return [
            'expected_points'=>$expected,'floor_points'=>$floor,'ceiling_points'=>$ceiling,
            'consistency'=>$stability,'upside'=>$ceiling,'confidence_score'=>$confidenceScore,
            'confidence'=>$confidence,'risk'=>$risk,'matches_used'=>count($values),
            'recent_history_score'=>$historyScore,'recent_history_mean'=>round($mean,2),
        ];
    }
    private static function ai11Adjustment(string $role, string $format, array $profile): array {
        $stats = is_array($profile['ai11_statistics'] ?? null) ? $profile['ai11_statistics'] : [];
        $series = is_array($profile['ai11_series_summary'] ?? null) ? $profile['ai11_series_summary'] : [];
        $sample = $stats['matches'] ?? $stats['batting_innings'] ?? $stats['bowling_innings'] ?? 0;
        if (!is_numeric($sample) || (float)$sample < 3) return [1.0, ['AI11 profile sample too small for a performance adjustment']];
        $signals = []; $role = strtoupper($role);
        if (in_array($role, ['BAT','WK','AR'], true)) {
            $avg = self::number($stats['batting_average'] ?? null);
            if ($avg !== null) { $base = $format === 'ODI' ? 32.0 : ($format === 'T20' ? 25.0 : 35.0); $signals[] = self::bounded(($avg-$base)/$base,-1,1)*0.025; }
            $sr = self::number($stats['batting_strike_rate'] ?? $stats['strike_rate'] ?? null);
            if ($sr !== null) { $base = $format === 'ODI' ? 85.0 : ($format === 'T20' ? 125.0 : 50.0); $signals[] = self::bounded(($sr-$base)/$base,-1,1)*0.015; }
        }
        if (in_array($role, ['BOWL','AR'], true)) {
            $w = self::number($stats['wickets'] ?? null); $inn = self::number($stats['bowling_innings'] ?? $sample);
            if ($w !== null && $inn !== null && $inn > 0) $signals[] = self::bounded(($w/$inn-0.8)/0.8,-1,1)*0.025;
            $eco = self::number($stats['economy'] ?? null);
            if ($eco !== null) { $base = $format === 'ODI' ? 6.0 : ($format === 'T20' ? 8.0 : 3.2); $signals[] = self::bounded(($base-$eco)/$base,-1,1)*0.015; }
        }
        $seriesMatches = self::number($series['series_matches'] ?? null) ?? 0.0;
        $seriesAverage = self::number($series['series_average_points'] ?? null);
        if ($seriesMatches >= 2 && $seriesAverage !== null) $signals[] = self::bounded(($seriesAverage-35.0)/70.0,-1,1)*0.025;
        if (!$signals) return [1.0, []];
        $factor = self::bounded(1.0 + array_sum($signals)/count($signals), 0.95, 1.05);
        return [$factor, [sprintf('AI11 career/series profile used as a small supporting form adjustment (%.3fx)', $factor)]];
    }

    public function predictMatch(int $matchId): array {
        if ($matchId <= 0) throw new RuntimeException('Valid match ID required.');
        $matchQ = $this->db->prepare('SELECT id, format, d11_format, d11_intelligence_json FROM matches WHERE id = ? LIMIT 1');
        $matchQ->execute([$matchId]); $match = $matchQ->fetch(PDO::FETCH_ASSOC);
        if (!$match) return [];
        $format = strtoupper((string)($match['d11_format'] ?: $match['format'] ?: 'T20'));
        $context = json_decode((string)($match['d11_intelligence_json'] ?? '{}'), true);
        if (!is_array($context)) $context = [];

        // Derive evidence-based venue factors once per match, then feed the same
        // normalized factors into every player's bounded condition adjustment.
        $pitch = (new PitchIntelligenceService())->analyse($context, $format);
        $context = array_merge($context, $pitch['adjustments'] ?? []);

        $squadQ = $this->db->prepare(
            'SELECT ms.player_id, ms.role, ms.credits, ms.selection_pct, ms.player_status, ms.team_id,
                    p.full_name, t.name AS team_name
             FROM match_squads ms INNER JOIN players p ON p.id = ms.player_id
             LEFT JOIN teams t ON t.id = ms.team_id WHERE ms.match_id = ?'
        );
        $squadQ->execute([$matchId]); $squads = $squadQ->fetchAll(PDO::FETCH_ASSOC);
        if (!$squads) return [];
        $ids = array_values(array_unique(array_map(fn($s) => (int)$s['player_id'], $squads)));
        $marks = implode(',', array_fill(0, count($ids), '?'));
        $historyQ = $this->db->prepare("SELECT player_id, fantasy_points, match_date, id FROM player_match_stats WHERE player_id IN ({$marks}) AND format = ? AND match_id <> ? AND fantasy_points IS NOT NULL ORDER BY player_id, match_date DESC, id DESC");
        $historyQ->execute([...$ids, $format, $matchId]);
        $history = [];
        foreach ($historyQ->fetchAll(PDO::FETCH_ASSOC) as $row) {
            $pid = (int)$row['player_id'];
            if (!isset($history[$pid])) $history[$pid] = [];
            if (count($history[$pid]) < 12) $history[$pid][] = $row;
        }
        $profileQ = $this->db->prepare("SELECT player_id, source, profile_json FROM player_source_profiles WHERE match_id = ? AND player_id IN ({$marks}) AND source IN ('AI11','TEAM_GENERATION')");
        $profileQ->execute([$matchId, ...$ids]);
        $profiles = [];
        foreach ($profileQ->fetchAll(PDO::FETCH_ASSOC) as $row) {
            $data = json_decode((string)$row['profile_json'], true);
            $profiles[(int)$row['player_id']][$row['source']] = is_array($data) ? $data : [];
        }

        $output = [];
        foreach ($squads as $squad) {
            $pid = (int)$squad['player_id'];
            $ai = $profiles[$pid]['AI11'] ?? [];
            $tg = $profiles[$pid]['TEAM_GENERATION'] ?? [];
            [$aiFactor, $aiReasons] = self::ai11Adjustment((string)($squad['role'] ?? ''), $format, $ai);
            $form = self::form($history[$pid] ?? [], $format);
            [$conditionFactor, $conditionReasons] = self::condition(strtoupper((string)($squad['role'] ?? '')), $context);
            $status = strtolower((string)($squad['player_status'] ?? 'unknown'));
            $confirmedStatuses = ['playing','playing_xi','confirmed'];
            $base = [
                'match_id'=>$matchId,'player_id'=>$pid,'player_name'=>$squad['full_name'],
                'team'=>$squad['team_name'],'role'=>$squad['role'],'status'=>$squad['player_status'],
                'credits'=>$squad['credits'] === null ? null : (float)$squad['credits'],
                'selection_pct'=>$squad['selection_pct'] === null ? null : (float)$squad['selection_pct'],
                'ai11_selection_pct'=>$ai['ai11_selection_pct'] ?? null,
                'ai11_captain_pct'=>$ai['ai11_captain_pct'] ?? null,
                'ai11_vice_captain_pct'=>$ai['ai11_vice_captain_pct'] ?? null,
                'ai11_statistics'=>$ai['ai11_statistics'] ?? [],'ai11_series_summary'=>$ai['ai11_series_summary'] ?? [],
                'ai11_profile_factor'=>round($aiFactor,3),'team_generation_image'=>$tg['image'] ?? null,
                'batting_position'=>$tg['batting_position'] ?? null,'expected_overs'=>$tg['expected_overs'] ?? null,
                'involvement_score'=>$tg['involvement_score'] ?? null,'matchup_score'=>$tg['matchup_score'] ?? null,
                'pitch_intelligence'=>$pitch,
            ];
            if ($form['expected_points'] === null) {
                $reasons = ['Fewer than three imported match-level records; a fantasy-point projection is not available'];
                if (($form['matches_used'] ?? 0) > 0) $reasons[] = sprintf('Recent match-level history: %d record(s), weighted mean %s, provisional form score %s/100', $form['matches_used'], (string)$form['recent_history_mean'], (string)$form['recent_history_score']);
                $warnings = ['Expected/floor/ceiling points remain unavailable until at least three format-matched historical records are imported'];
                if (!$context) $warnings[] = 'No pitch/weather/venue intelligence imported';
                $output[] = $base + $form + [
                    'median_points'=>null,'condition_factor'=>round($conditionFactor,3),
                    'reasons'=>array_merge($reasons, $pitch['reasons'] ?? [], $aiReasons, $conditionReasons),'warnings'=>$warnings,
                    'model_version'=>self::MODEL_VERSION,'prediction_type'=>'provisional_selection_support_only',
                ];
                continue;
            }
            $availability = in_array($status,$confirmedStatuses,true) ? 1.0 : (in_array($status,['probable','likely','available'],true) ? 0.94 : 0.88);
            $expected = max(0.0,(float)$form['expected_points']*$conditionFactor*$availability)*$aiFactor;
            $floor = max(0.0,(float)$form['floor_points']*$conditionFactor*$availability*$aiFactor);
            $ceiling = max($expected,(float)$form['ceiling_points']*$conditionFactor*$availability*$aiFactor);
            $reasons = [sprintf('Format-matched recent form: %d records; recency-weighted mean %.1f',$form['matches_used'],$form['expected_points'])];
            $reasons = array_merge($reasons, $pitch['reasons'] ?? [], $aiReasons, $conditionReasons);
            if (in_array($status,$confirmedStatuses,true)) $reasons[] = 'Playing status confirmed';
            elseif (!in_array($status,['probable','likely','available'],true)) $reasons[] = 'Playing status is not confirmed';
            if (($tg['batting_position'] ?? null) !== null) $reasons[] = 'Imported expected batting position: ' . $tg['batting_position'];
            if (($tg['expected_overs'] ?? null) !== null) $reasons[] = 'Imported expected bowling workload: ' . $tg['expected_overs'] . ' overs';
            $warnings = [];
            if ($form['matches_used'] < 5) $warnings[] = 'Small historical sample';
            if (!$context) $warnings[] = 'No pitch/weather/venue intelligence imported';
            if (!in_array($format,['T20','ODI','TEST'],true)) $warnings[] = 'Unrecognised match format; verify format-specific data';
            $output[] = array_merge($base, $form, [
                'expected_points'=>round($expected,2),'floor_points'=>round($floor,2),
                'median_points'=>round($expected,2),'ceiling_points'=>round($ceiling,2),
                'upside'=>round($ceiling,2),'condition_factor'=>round($conditionFactor,3),
                'reasons'=>$reasons,'warnings'=>$warnings,'model_version'=>self::MODEL_VERSION,
                'prediction_type'=>'format_specific_statistical_estimate',
            ]);
        }
        return $output;
    }

    public function savePredictions(int $matchId): array {
        $predictions = $this->predictMatch($matchId);
        $stmt = $this->db->prepare(
            'INSERT INTO d11_predictions (match_id, player_id, expected_points, floor_points, ceiling_points, consistency, upside, confidence, model_version)
             VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
             ON DUPLICATE KEY UPDATE expected_points = VALUES(expected_points), floor_points = VALUES(floor_points),
             ceiling_points = VALUES(ceiling_points), consistency = VALUES(consistency), upside = VALUES(upside),
             confidence = VALUES(confidence), created_at = CURRENT_TIMESTAMP'
        );
        foreach ($predictions as $p) {
            if ($p['expected_points'] === null) continue;
            $stmt->execute([$matchId,$p['player_id'],$p['expected_points'],$p['floor_points'],$p['ceiling_points'],$p['consistency'],$p['upside'],$p['confidence'],self::MODEL_VERSION]);
        }
        return $predictions;
    }
}
