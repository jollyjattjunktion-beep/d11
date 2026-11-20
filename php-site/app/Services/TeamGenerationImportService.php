<?php
declare(strict_types=1);

namespace D11\\Services;

use DateTimeImmutable;
use DateTimeZone;
use RuntimeException;

/** Converts the authenticated TeamGeneration response into the existing PHP sync contract. */
final class TeamGenerationImportService
{
    public function __construct(
        private TeamGenerationApiClient $client,
        private TeamGenerationSyncService $sync
    ) {}

    private function teamId(array $team, string $side): string
    {
        foreach (['id', 'teamId', 'code'] as $key) {
            if (isset($team[$key]) && trim((string)$team[$key]) !== '') return trim((string)$team[$key]);
        }
        $name = trim((string)($team['name'] ?? ''));
        if ($name === '') throw new RuntimeException('TeamGeneration ' . $side . ' team has no stable ID or name.');
        return 'name-' . substr(hash('sha256', strtolower($name)), 0, 24);
    }

    private function format(string $series): string
    {
        $s = strtoupper($series);
        if (str_contains($s, 'TEST')) return 'TEST';
        if (str_contains($s, 'ODI') || str_contains($s, 'ONE DAY')) return 'ODI';
        if (str_contains($s, 'T20')) return 'T20';
        return 'T20';
    }

    private function startTime(mixed $value): ?string
    {
        if (!is_string($value) || trim($value) === '') return null;
        try {
            return (new DateTimeImmutable($value))->setTimezone(new DateTimeZone('UTC'))->format('Y-m-d H:i:s');
        } catch (\\Throwable) {
            return null;
        }
    }

    public function import(string $matchId): array
    {
        $payload = $this->client->getMatch($matchId);
        $match = $payload['match'] ?? null;
        $detail = $payload['detail'] ?? null;
        if (!is_array($match) || !is_array($detail) || !isset($detail['players']) || !is_array($detail['players']) || !array_is_list($detail['players'])) {
            throw new RuntimeException('TeamGeneration response must contain match, detail and detail.players.');
        }
        if ((string)($match['id'] ?? '') !== $matchId) {
            throw new RuntimeException('TeamGeneration returned a different fixture ID.');
        }
        $left = is_array($match['left'] ?? null) ? $match['left'] : [];
        $right = is_array($match['right'] ?? null) ? $match['right'] : [];
        $leftName = trim((string)($left['name'] ?? $left['code'] ?? ''));
        $rightName = trim((string)($right['name'] ?? $right['code'] ?? ''));
        if ($leftName === '' || $rightName === '') throw new RuntimeException('TeamGeneration response is missing one or both team names.');
        $series = trim((string)($match['series'] ?? 'Cricket'));
        $venue = $match['venue'] ?? $match['ground'] ?? null;
        $venueName = is_array($venue) ? ($venue['name'] ?? null) : (is_string($venue) ? $venue : ($match['venueName'] ?? null));

        $fixture = [
            'external_id' => $matchId,
            'title' => $leftName . ' vs ' . $rightName . ' - ' . $series,
            'format' => $this->format($series),
            'status' => $this->status((string)($match['status'] ?? 'scheduled')),
            'start_time_utc' => $this->startTime($match['startTime'] ?? null),
            'team_a' => ['external_id' => $this->teamId($left, 'left'), 'name' => $leftName, 'short_name' => $left['code'] ?? null],
            'team_b' => ['external_id' => $this->teamId($right, 'right'), 'name' => $rightName, 'short_name' => $right['code'] ?? null],
        ];

        $lineupStatus = strtolower((string)($detail['lineupStatus'] ?? $match['lineupStatus'] ?? 'unknown'));
        $notAnnounced = preg_match('/not[_ ]announced|unannounced|pending/', $lineupStatus) === 1;
        $playingCounts = [0 => 0, 1 => 0];
        foreach ($detail['players'] as $p) {
            if (!is_array($p)) continue;
            $team = filter_var($p['team'] ?? null, FILTER_VALIDATE_INT);
            if ((int)($p['playing'] ?? 0) === 1 && isset($playingCounts[$team])) $playingCounts[$team]++;
        }
        $completeXI = $playingCounts[0] === 11 && $playingCounts[1] === 11;
        $confirmed = (!$notAnnounced && preg_match('/announc|confirm|complete|final/', $lineupStatus) === 1) || $completeXI;

        $roles = [0 => 'WK', 1 => 'BAT', 2 => 'AR', 3 => 'BOWL'];
        $squads = [];
        $skipped = [];
        foreach ($detail['players'] as $index => $p) {
            if (!is_array($p) || !isset($p['playerId']) || trim((string)($p['name'] ?? '')) === '') {
                $skipped[] = ['index' => $index, 'reason' => 'missing_player_id_or_name'];
                continue;
            }
            $teamCode = filter_var($p['team'] ?? null, FILTER_VALIDATE_INT);
            if (!in_array($teamCode, [0, 1], true)) {
                $skipped[] = ['name' => (string)$p['name'], 'reason' => 'unknown_team_code'];
                continue;
            }
            $roleCode = filter_var($p['role'] ?? null, FILTER_VALIDATE_INT);
            $role = $roles[$roleCode] ?? 'BAT';
            $credit = is_numeric($p['credits'] ?? null) ? (float)$p['credits'] : null;
            if ($credit !== null && ($credit <= 0 || $credit > 20)) $credit = null;
            $selection = is_numeric($p['ownership'] ?? null) ? (float)$p['ownership'] : null;
            if ($selection !== null && ($selection < 0 || $selection > 100)) $selection = null;
            $playing = (int)($p['playing'] ?? 0) === 1;
            $status = !$confirmed ? 'probable' : ($playing ? 'playing_xi' : 'announced');
            $squads[] = [
                'team_external_id' => $teamCode === 0 ? $fixture['team_a']['external_id'] : $fixture['team_b']['external_id'],
                'player' => [
                    'external_id' => (string)$p['playerId'],
                    'name' => trim((string)$p['name']),
                    'display_name' => trim((string)$p['name']),
                    'role' => $role,
                ],
                'role' => $role,
                'credits' => $credit,
                'selection_pct' => $selection,
                'status' => $status,
                'source_player_id' => (string)$p['playerId'],
                'source_url' => 'https://teamgeneration.in/match/' . rawurlencode($matchId),
                'image' => $p['image'] ?? null,
                'fantasy_ids' => $p['fantasyIds'] ?? [],
                'captain_pct' => $p['captainPct'] ?? null,
                'vice_captain_pct' => $p['viceCaptainPct'] ?? null,
                'batting_position' => $p['battingOrder'] ?? null,
                'expected_overs' => null,
                'player_type' => $p['playerType'] ?? null,
                'lineup_order' => $p['lineupOrder'] ?? null,
                'last_play' => $p['lastPlay'] ?? null,
                'in_dream_team' => $p['inDreamTeam'] ?? null,
                'points' => $p['points'] ?? ($p['fantasyPoints'] ?? null),
            ];
        }
        if (!$squads) throw new RuntimeException('TeamGeneration returned no valid squad players.');

        $sync = $this->sync->sync($fixture, $squads);
        return [
            'source' => 'TeamGeneration',
            'external_match_id' => $matchId,
            'match_id' => $sync['match_id'],
            'match_title' => $fixture['title'],
            'series' => $series,
            'format' => $fixture['format'],
            'venue_from_source' => $venueName,
            'players_received' => count($detail['players']),
            'players_importable' => count($squads),
            'players_skipped' => $skipped,
            'players_without_credits' => count(array_filter($squads, static fn(array $p): bool => $p['credits'] === null)),
            'lineup_status' => $lineupStatus,
            'lineup_confirmed' => $confirmed,
            'sync' => $sync,
        ];
    }

    private function status(string $value): string
    {
        $v = strtolower(trim($value));
        return match (true) {
            str_contains($v, 'live') => 'live',
            str_contains($v, 'inning') => 'innings_break',
            str_contains($v, 'complete'), str_contains($v, 'result'), str_contains($v, 'finished') => 'completed',
            str_contains($v, 'abandon') => 'abandoned',
            str_contains($v, 'postpon') => 'postponed',
            str_contains($v, 'cancel') => 'cancelled',
            str_contains($v, 'schedul'), str_contains($v, 'upcoming'), $v === '' => 'scheduled',
            default => 'unknown',
        };
    }
}
