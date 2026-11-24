# Randomized Tactical Formations

Target branch: `feature/randomized-tactical-formations`

## Formation order

All patterns use the explicit role order **WK-BAT-AR-BOWL**:

1. `1-3-4-3`
2. `1-3-3-4`
3. `1-2-4-4`
4. `2-3-3-3`
5. `1-4-3-3`
6. `1-3-2-5`
7. `2-3-2-4`
8. `2-2-4-3`

Each pattern contains exactly 11 players. The generator chooses a fresh random starting offset on each invocation and walks the configured list cyclically. If a pattern conflicts with the locked core, role maximums, credit cap, team limit, or available squad, it skips to the next pattern.

## Non-core variation

- Default variation limit: `±3.2` selection-score points.
- Each completed lineup receives independent random jitter for non-locked players only.
- The applied lineup variation is the average of those non-core jitters; therefore the overall lineup adjustment stays within `[-3.2, +3.2]`, rather than accumulating 3.2 points per player.
- Locked/fixed-core players receive no jitter and are never dropped.
- Set `variation_points` between 0 and 3.2 to tune or disable the variation.

Captain and vice-captain ranking uses the base, unrandomized player score. Random variation only affects non-core lineup selection.

## Preserved constraints

- Exactly 11 selected players.
- Credit cap.
- Maximum players from one real-world team.
- Maximum role counts from caller-supplied `max_role`.
- Any explicit caller-supplied `min_role` is respected by default.
- Locked player IDs remain in every generated team.
- Excluded player IDs cannot be selected.
- Manual captain and vice-captain must be selected players and must differ.

The optimizer's built-in default `min_role` is a composition preference, not an external platform rule. In formation mode, the selected formation supplies exact role counts. For an integration that provides actual platform minimum role constraints, pass those in `rules.min_role`; they are automatically respected. Alternatively set `formationOptions.respect_min_role=true`.

## API use

Existing calls remain compatible. Tactical formations are enabled by default:

```php
$result = $optimizer->generate(
    $players,
    $rules,
    'grand_league',
    $lockedCoreIds,
    $excludedIds,
    null,
    null,
    true,
    $researchHints
);
```

Optional final argument:

```php
[
    'enabled' => true,
    'formations' => [
        '1-3-4-3', '1-3-3-4', '1-2-4-4', '2-3-3-3',
        '1-4-3-3', '1-3-2-5', '2-3-2-4', '2-2-4-3'
    ],
    'rotation_offset' => null, // null = fresh random offset; integer supports tests/replay
    'variation_points' => 3.2,
    'respect_min_role' => false,
    'search_limit_per_formation' => 250000
]
```

Set `enabled=false` for legacy role-minimum behaviour without randomized variation. A fixed `rotation_offset` makes formation order reproducible in tests.

## Diagnostics

The result now includes:

- `formation`
- `formation_role_order`
- `formation_role_counts`
- `base_team_score`
- `diagnostics.formation_rotation_offset`
- `diagnostics.formation_attempt_order`
- `diagnostics.fixed_core_preserved`
- `diagnostics.non_core_variation_points`
- `diagnostics.non_core_variation_limit`
- search-node and truncation information

These are selection-priority scores and variation diagnostics, not guaranteed fantasy points.

## Test

```bash
php -l php-site/app/Services/TeamOptimizerService.php
php php-site/tests/optimizer_test.php
php php-site/tests/tactical_formations_test.php
```

GitHub Actions workflow: `.github/workflows/tactical-formation-tests.yml`
