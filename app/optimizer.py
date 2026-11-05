from collections import Counter
from itertools import count
import random

STRATEGY_WEIGHTS = {
    "safe": (0.55, 0.35, 0.10),
    "balanced": (0.65, 0.20, 0.15),
    "grand_league": (0.45, 0.05, 0.50),
    "scenario": (0.60, 0.15, 0.25),
}

def _score(p, strategy, scenario):
    exp, consistency, upside = p["expected_points"], p["consistency"], p["upside"]
    a, b, c = STRATEGY_WEIGHTS[strategy]
    value = a*exp + b*consistency*exp + c*upside
    role = p["role"]
    if scenario == "batting_friendly" and role in {"BAT", "WK"}: value *= 1.08
    if scenario == "bowling_friendly" and role == "BOWL": value *= 1.10
    if scenario == "spin_friendly" and role == "BOWL": value *= 1.04
    if scenario == "pace_friendly" and role == "BOWL": value *= 1.04
    if strategy == "grand_league" and p.get("selection_pct") is not None:
        value *= 1.12 if p["selection_pct"] < 25 else 0.96 if p["selection_pct"] > 70 else 1.0
    return value

def _valid_add(p, chosen, rules):
    if rules.playing_xi_only and p["status"].lower() not in {"playing", "confirmed"}: return False
    if p.get("credits") is None: return False
    if sum(x["credits"] for x in chosen) + p["credits"] > rules.max_credits: return False
    if sum(1 for x in chosen if x["team"] == p["team"]) >= rules.max_from_one_team: return False
    role_count = sum(1 for x in chosen if x["role"] == p["role"])
    if role_count >= rules.max_role.get(p["role"], rules.team_size): return False
    return True

def build_teams(players, strategy, rules, count_teams=1, scenario="neutral"):
    if len(players) < rules.team_size:
        raise ValueError("Not enough eligible players. Import both squads and player credits first.")
    if any(p.get("credits") is None for p in players):
        raise ValueError("Some players have unknown credits. Add verified credits before generating teams.")
    made, usage = [], Counter()
    rng = random.Random(20261105)
    for _ in range(count_teams):
        pool = [dict(p) for p in players]
        chosen = []
        # Greedy constrained selection with strategy-dependent diversity for multiple teams.
        while len(chosen) < rules.team_size:
            candidates = []
            for p in pool:
                if not _valid_add(p, chosen, rules): continue
                role = p["role"]
                need = max(0, rules.min_role.get(role, 0) - sum(x["role"] == role for x in chosen))
                base = _score(p, strategy, scenario) - usage[p["player_id"]]*2.0
                # Prioritise filling minimum role requirements before optional picks.
                candidates.append((base + (1000 if need and sum(x["role"] == role for x in chosen) < rules.min_role.get(role,0) else 0) + rng.random()*0.01, p))
            if not candidates: break
            candidates.sort(key=lambda x: x[0], reverse=True)
            chosen.append(candidates[0][1])
            pool.remove(candidates[0][1])
        counts = Counter(p["role"] for p in chosen)
        if len(chosen) != rules.team_size or any(counts[r] < n for r,n in rules.min_role.items()):
            raise ValueError("Could not satisfy team constraints. Check role counts, credits, and player eligibility.")
        ranked = sorted(chosen, key=lambda p: _score(p, strategy, scenario), reverse=True)
        captain, vice = ranked[0], ranked[1]
        for p in chosen: usage[p["player_id"]] += 1
        made.append({
            "strategy": strategy, "scenario": scenario,
            "players": chosen, "captain_id": captain["player_id"],
            "vice_captain_id": vice["player_id"],
            "total_credits": round(sum(p["credits"] for p in chosen), 1),
            "projected_points": round(sum(p["expected_points"] for p in chosen)
                + captain["expected_points"] + 0.5*vice["expected_points"], 2),
            "role_counts": dict(counts),
        })
    return made
