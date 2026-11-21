<?php
declare(strict_types=1);

namespace D11\Services;

/**
 * Format-aware, evidence-only venue/pitch analysis.
 *
 * Expected context contract (all fields optional):
 * venue_history: {
 *   total_matches, matches_won_batting_first, matches_won_bowling_first,
 *   average_first_innings_score, average_second_innings_score,
 *   tournament_average_first_innings, pace_wickets, spin_wickets,
 *   total_bowling_wickets, recent_matches: [{runs,wickets,innings,pace_wickets,spin_wickets}]
 * }
 * Match context may also provide batting_friendly, pace_friendly,
 * spin_friendly, dew_likely, rain_probability, toss, weather.
 *
 * Missing evidence stays null; no pace/spin conclusion is fabricated.
 */
final class PitchIntelligenceService
{
    private static function num(mixed $value): ?float
    {
        return is_numeric($value) ? (float)$value : null;
    }

    private static function clamp(float $value, float $min = 0.0, float $max = 1.0): float
    {
        return max($min, min($max, $value));
    }

    private static function fmt(string $format): string
    {
        $f = strtoupper(str_replace(['-', ' '], '', $format));
        if (in_array($f, ['T20I','WT20','WT20I'], true)) return 'T20';
        if (in_array($f, ['WODI','ONEDAY'], true)) return 'ODI';
        if ($f === 'WTEST') return 'TEST';
        return $f;
    }

    /** @return array<string,mixed> */
    public function analyse(array $context, string $format): array
    {
        $format = self::fmt($format);
        $venue = is_array($context['venue_history'] ?? null) ? $context['venue_history'] : [];
        $total = self::num($venue['total_matches'] ?? null);
        $batWins = self::num($venue['matches_won_batting_first'] ?? null);
        $bowlWins = self::num($venue['matches_won_bowling_first'] ?? null);
        $firstAvg = self::num($venue['average_first_innings_score'] ?? null);
        $secondAvg = self::num($venue['average_second_innings_score'] ?? null);
        $decided = max(0.0, ($batWins ?? 0.0) + ($bowlWins ?? 0.0));
        $sample = $total !== null ? max(0.0, $total) : $decided;

        // Beta(4,4) shrinkage prevents a 12-match sample from becoming a strong toss signal.
        $batRate = $decided > 0 ? ($batWins + 4.0) / ($decided + 8.0) : null;
        $bowlRate = $decided > 0 ? ($bowlWins + 4.0) / ($decided + 8.0) : null;
        $gapPct = ($firstAvg !== null && $secondAvg !== null && $secondAvg > 0)
            ? (($firstAvg - $secondAvg) / $secondAvg) * 100.0 : null;

        $reliability = $sample > 0 ? self::clamp($sample / 30.0, 0.0, 1.0) : 0.0;
        $confidence = $sample < 15 ? 'low' : ($sample < 30 ? 'medium' : 'high');
        $reasons = [];
        if ($sample > 0) $reasons[] = sprintf('%d format-matched venue matches in the supplied sample.', (int)$sample);
        if ($firstAvg !== null && $secondAvg !== null) {
            $reasons[] = sprintf('Average innings scores: %.1f first innings and %.1f second innings (%.1f%% gap).', $firstAvg, $secondAvg, $gapPct ?? 0.0);
        }
        if ($batWins !== null && $bowlWins !== null) {
            $reasons[] = sprintf('Batting-first wins: %d; bowling-first wins: %d. Win-rate signal is sample-shrunk.', (int)$batWins, (int)$bowlWins);
        }

        // A batting suitability index is only calculated against a supplied format/competition baseline.
        $baseline = self::num($venue['tournament_average_first_innings'] ?? $venue['format_average_first_innings'] ?? null);
        $batting = self::num($context['batting_friendly'] ?? null);
        if ($batting === null && $firstAvg !== null && $baseline !== null && $baseline > 0) {
            // 15% above/below baseline maps to the full 0..1 scale; blend towards neutral by sample reliability.
            $raw = self::clamp(0.5 + (($firstAvg / $baseline) - 1.0) / 0.30);
            $batting = 0.5 + (($raw - 0.5) * $reliability);
            $reasons[] = sprintf('First-innings scoring compared with the supplied %s baseline (%.1f).', $format, $baseline);
        } elseif ($batting !== null) {
            $batting = self::clamp($batting);
        }

        // Pace/spin are inferred only from actual wicket split data.
        $pace = self::num($context['pace_friendly'] ?? null);
        $spin = self::num($context['spin_friendly'] ?? null);
        $paceW = self::num($venue['pace_wickets'] ?? null);
        $spinW = self::num($venue['spin_wickets'] ?? null);
        $allW = self::num($venue['total_bowling_wickets'] ?? null);
        if ($allW !== null && $allW > 0) {
            if ($pace === null && $paceW !== null) $pace = self::clamp(0.5 + (($paceW / $allW) - 0.5) * $reliability);
            if ($spin === null && $spinW !== null) $spin = self::clamp(0.5 + (($spinW / $allW) - 0.5) * $reliability);
            if ($paceW !== null || $spinW !== null) $reasons[] = 'Pace/spin suitability uses imported wicket shares, reliability-adjusted for sample size.';
        }

        // Recent sample is descriptive only unless it contains enough complete score rows.
        $recent = is_array($venue['recent_matches'] ?? null) ? array_slice($venue['recent_matches'], 0, 5) : [];
        $recentRuns = []; $recentPace = 0.0; $recentSpin = 0.0; $recentWickets = 0.0;
        foreach ($recent as $row) {
            if (!is_array($row)) continue;
            $runs = self::num($row['runs'] ?? $row['first_innings_runs'] ?? null);
            if ($runs !== null) $recentRuns[] = $runs;
            $recentPace += self::num($row['pace_wickets'] ?? null) ?? 0.0;
            $recentSpin += self::num($row['spin_wickets'] ?? null) ?? 0.0;
            $recentWickets += self::num($row['total_wickets'] ?? null) ?? 0.0;
        }
        $recentAvg = $recentRuns ? array_sum($recentRuns) / count($recentRuns) : null;
        if ($recentAvg !== null) $reasons[] = sprintf('Recent first-innings average across %d supplied matches: %.1f.', count($recentRuns), $recentAvg);

        $tossKey = null;
        if ($batRate !== null && $bowlRate !== null && $sample >= 15) {
            if ($batRate >= 0.60) $tossKey = 'bat';
            elseif ($bowlRate >= 0.60) $tossKey = 'bowl';
        }
        $pitchType = 'insufficient_data';
        if ($batting !== null) {
            $pitchType = $batting >= 0.58 ? 'batting' : ($batting <= 0.42 ? 'bowling' : 'balanced');
        } elseif ($gapPct !== null) {
            $pitchType = abs($gapPct) >= 8.0 ? ($gapPct > 0 ? 'batting' : 'bowling') : 'balanced';
        }

        $adjustments = [];
        if ($batting !== null) $adjustments['batting_friendly'] = round($batting, 4);
        if ($pace !== null) $adjustments['pace_friendly'] = round(self::clamp($pace), 4);
        if ($spin !== null) $adjustments['spin_friendly'] = round(self::clamp($spin), 4);

        return [
            'format'=>$format, 'available'=>($sample > 0 || $batting !== null || $pace !== null || $spin !== null),
            'pitch_type'=>$pitchType, 'confidence'=>$confidence, 'confidence_score'=>(int)round(100.0 * $reliability),
            'total_matches'=>$sample > 0 ? (int)$sample : null,
            'batting_first_win_pct'=>$batRate !== null ? round($batRate * 100, 1) : null,
            'bowling_first_win_pct'=>$bowlRate !== null ? round($bowlRate * 100, 1) : null,
            'first_innings_average'=>$firstAvg, 'second_innings_average'=>$secondAvg,
            'innings_average_gap_pct'=>$gapPct !== null ? round($gapPct, 2) : null,
            'recent_first_innings_average'=>$recentAvg !== null ? round($recentAvg, 2) : null,
            'pace_friendly'=>$pace, 'spin_friendly'=>$spin, 'batting_friendly'=>$batting,
            'toss_recommendation'=>$tossKey, 'adjustments'=>$adjustments, 'reasons'=>$reasons,
            'notes'=>[
                'A small venue sample is shrunk towards neutral; 12 matches cannot justify a strong toss/pitch claim.',
                'Pace/spin suitability remains unavailable without bowler-type wicket splits.',
                'Absolute scoring labels require a format/competition baseline; raw averages alone are not compared across competitions.',
                'Weather, dew and toss are match-day inputs, not permanent venue characteristics.'
            ],
        ];
    }
}
