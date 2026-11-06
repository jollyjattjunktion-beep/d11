from collections import Counter

STRATEGY_WEIGHTS = {
    "safe": (0.55, 0.35, 0.10),
    "balanced": (0.65, 0.20, 0.15),
    "grand_league": (0.45, 0.05, 0.50),
    "scenario": (0.60, 0.15, 0.25),
}

def _ownership(p):
    value = p.get("selection_pct")
    try:
        return max(0.0, min(100.0, float(value))) if value is not None else None
    except (TypeError, ValueError):
        return None


def _role_opportunity(p):
    """Modest role prior; source-backed batting position/overs override it."""
    prior = {"WK": 0.62, "BAT": 0.58, "AR": 0.78, "BOWL": 0.55}.get(p.get("role"), 0.5)
    try:
        if p.get("batting_position") is not None:
            prior += max(-0.18, min(0.18, (5 - int(p["batting_position"])) * 0.035))
    except (TypeError, ValueError):
        pass
    try:
        if p.get("expected_overs") is not None:
            prior += max(-0.10, min(0.18, (float(p["expected_overs"]) - 2.0) * 0.06))
    except (TypeError, ValueError):
        pass
    return max(0.25, min(1.0, prior))


def _player_signal(p, strategy, scenario, innings_mode="none", score_team=None,
                   scenario_score=None, match_format="T20", provisional=False):
    """Strategy score from form/range, role opportunity and match context."""
    status = str(p.get("status") or "unknown").lower()
    availability = 1.0 if status in {"playing", "confirmed"} else 0.90 if status in {"probable", "likely", "available"} else 0.72
    ownership = _ownership(p)
    expected = p.get("expected_points")
    floor = p.get("floor_points")
    ceiling = p.get("ceiling_points") or p.get("upside")
    if expected is not None:
        base = float(expected)
        floor_v = float(floor) if floor is not None else base * 0.55
        ceiling_v = float(ceiling) if ceiling is not None else base * 1.35
        consistency = max(0.0, min(1.0, float(p.get("consistency") or 0.0)))
        upside = max(base, ceiling_v)
    else:
        popularity = 50.0 if ownership is None else ownership
        source_c = float(p.get("captain_pct") or p.get("ai11_captain_pct") or 0.0)
        source_vc = float(p.get("vice_captain_pct") or p.get("ai11_vice_captain_pct") or 0.0)
        # Provisional score is a selection-priority index, never fantasy points.
        base = _role_opportunity(p) * 35.0 + popularity * 0.10 + min(source_c, 100) * 0.025 + min(source_vc, 100) * 0.015
        floor_v, upside, consistency = base * 0.55, base * (1.18 if p.get("role") in {"AR", "WK"} else 1.08), 0.35

    role = p.get("role")
    opportunity = _role_opportunity(p)
    try:
        involvement = p.get("involvement_score")
        if involvement is not None:
            n = float(involvement)
            opportunity = max(0.0, min(1.0, n / 100.0 if n > 1 else n))
    except (TypeError, ValueError):
        pass

    condition = 1.0
    try:
        if role in {"BAT", "WK"} and p.get("batting_friendly") is not None:
            condition += (float(p["batting_friendly"]) - 0.5) * 0.12
        if role in {"BOWL", "AR"} and p.get("pace_friendly") is not None:
            condition += (float(p["pace_friendly"]) - 0.5) * 0.08
        if role in {"BOWL", "AR"} and p.get("spin_friendly") is not None:
            condition += (float(p["spin_friendly"]) - 0.5) * 0.08
        if p.get("dew_likely") is True and role in {"BOWL", "AR"}:
            condition *= 0.97
        if p.get("rain_probability") is not None and float(p["rain_probability"]) >= 50:
            condition *= 0.96
    except (TypeError, ValueError):
        pass

    scenario_factor = _score_context_multiplier(p, innings_mode, score_team, scenario_score, match_format)
    try:
        matchup_factor = 1.0 + max(-0.08, min(0.08, float(p.get("matchup_score") or 0) / 1000.0))
    except (TypeError, ValueError):
        matchup_factor = 1.0
    if p.get("toss_batting_team") and p.get("team") == p.get("toss_batting_team") and role in {"BAT", "WK"}:
        scenario_factor *= 1.015

    if strategy == "safe":
        raw = 0.72 * base + 0.22 * floor_v + 0.06 * upside
        raw *= 1.0 + 0.10 * consistency
        if p.get("risk") == "high":
            raw *= 0.86
    elif strategy == "grand_league":
        raw = 0.40 * base + 0.60 * upside
        if p.get("risk") == "high":
            raw *= 1.035
    else:
        raw = 0.62 * base + 0.18 * floor_v + 0.20 * upside
        if p.get("risk") == "high":
            raw *= 0.94

    # Lower ownership helps differentiation only in GL; it never makes a weak player good.
    if strategy == "grand_league" and ownership is not None:
        raw *= 1.0 + max(-0.045, min(0.055, (45.0 - ownership) / 1000.0))
    if scenario == "batting_friendly" and role in {"BAT", "WK"}:
        raw *= 1.035
    if scenario in {"bowling_friendly", "spin_friendly", "pace_friendly"} and role in {"BOWL", "AR"}:
        raw *= 1.03
    raw *= availability * max(0.90, min(1.10, condition)) * scenario_factor * matchup_factor
    raw *= 0.90 + 0.10 * opportunity
    return raw


def _captain_score(p, strategy, scenario, innings_mode, score_team, scenario_score, match_format):
    signal = _player_signal(p, strategy, scenario, innings_mode, score_team, scenario_score, match_format,
                            provisional=p.get("expected_points") is None)
    expected = p.get("expected_points")
    ceiling = p.get("ceiling_points") or p.get("upside")
    if expected is None:
        floor_component = signal * 0.82
        ceiling_component = signal * (1.10 if p.get("role") in {"AR", "WK"} else 1.0)
    else:
        floor_component = float(p.get("floor_points") if p.get("floor_points") is not None else expected * 0.6)
        ceiling_component = float(ceiling if ceiling is not None else expected * 1.25)
    if strategy == "safe":
        return 0.62 * signal + 0.30 * floor_component + 0.08 * ceiling_component
    if strategy == "grand_league":
        return 0.35 * signal + 0.55 * ceiling_component + 0.10 * _role_opportunity(p) * signal
    return 0.52 * signal + 0.30 * ceiling_component + 0.18 * floor_component


def _vice_score(p, strategy, scenario, innings_mode, score_team, scenario_score, match_format):
    signal = _player_signal(p, strategy, scenario, innings_mode, score_team, scenario_score, match_format,
                            provisional=p.get("expected_points") is None)
    expected = p.get("expected_points")
    ceiling = p.get("ceiling_points") or p.get("upside")
    floor = p.get("floor_points")
    if expected is None:
        floor_component, ceiling_component = signal * 0.82, signal * 1.08
    else:
        floor_component = float(floor if floor is not None else expected * 0.6)
        ceiling_component = float(ceiling if ceiling is not None else expected * 1.25)
    if strategy == "safe":
        return 0.68 * signal + 0.25 * floor_component + 0.07 * ceiling_component
    if strategy == "grand_league":
        return 0.42 * signal + 0.48 * ceiling_component + 0.10 * _role_opportunity(p) * signal
    return 0.58 * signal + 0.27 * ceiling_component + 0.15 * floor_component


def _score_context_multiplier(p, innings_mode, score_team, scenario_score, match_format):
    """Small preference adjustment for a user-entered innings scenario, not points."""
    if innings_mode not in {"first_innings", "chasing"} or not score_team or scenario_score is None:
        return 1.0
    fmt = str(match_format or "T20").upper()
    high_threshold, low_threshold = {
        "T20": (180, 145),
        "ODI": (280, 230),
        "TEST": (350, 220),
    }.get(fmt, (180, 145))
    high_score = int(scenario_score) >= high_threshold
    low_score = int(scenario_score) <= low_threshold
    team = p.get("team")
    role = p.get("role")
    batting_roles = {"BAT", "WK"}
    bowling_roles = {"BOWL", "AR"}
    if innings_mode == "first_innings":
        if team == score_team:
            if role in batting_roles:
                return 1.04 if high_score else 1.015 if not low_score else 0.985
        elif role in bowling_roles:
            return 1.035 if high_score else 1.02 if low_score else 1.0
    else:
        # score_team is the chasing side.
        if team == score_team and role in batting_roles:
            return 1.04 if high_score else 1.02
        if team != score_team and role in bowling_roles:
            return 1.035 if high_score else 1.02
    return 1.0


def _provisional_score(p, strategy, scenario, innings_mode="none", score_team=None,
                       scenario_score=None, match_format="T20"):
    """Selection-priority score only; never interpreted as fantasy points."""
    selection = p.get("selection_pct")
    selection = 50.0 if selection is None else max(0.0, min(100.0, float(selection)))
    captain = float(p.get("captain_pct") or p.get("ai11_captain_pct") or 0.0)
    vice = float(p.get("vice_captain_pct") or p.get("ai11_vice_captain_pct") or 0.0)
    # Source ownership and C/VC trends are weak selection signals, not fantasy points.
    value = selection * 0.70 + min(captain, 100.0) * 0.20 + min(vice, 100.0) * 0.10
    status = (p.get("status") or "unknown").lower()
    if status in {"playing", "confirmed"}:
        value += 4.0
    elif status in {"out", "injured", "unavailable", "not_playing"}:
        value -= 20.0
    if strategy == "grand_league" and selection < 25:
        value += 4.0
    if scenario == "batting_friendly" and p.get("role") in {"BAT", "WK"}:
        value += 1.0
    if scenario in {"bowling_friendly", "spin_friendly", "pace_friendly"} and p.get("role") in {"BOWL", "AR"}:
        value += 1.0
    value *= _score_context_multiplier(p, innings_mode, score_team, scenario_score, match_format)
    return value

def _score(p, strategy, scenario, innings_mode="none", score_team=None,
           scenario_score=None, match_format="T20"):
    exp = float(p.get("expected_points") or 0)
    consistency = float(p.get("consistency") or 0)
    upside = float(p.get("upside") or 0)
    a,b,c = STRATEGY_WEIGHTS[strategy]
    value = a*exp + b*consistency*exp + c*upside
    risk = p.get("risk","unknown")
    if strategy == "safe" and risk == "high": value *= 0.88
    if strategy == "balanced" and risk == "high": value *= 0.95
    if scenario == "batting_friendly" and p.get("role") in {"BAT","WK"}: value *= 1.04
    if scenario == "bowling_friendly" and p.get("role") in {"BOWL","AR"}: value *= 1.04
    if scenario == "spin_friendly" and p.get("role") in {"BOWL","AR"}: value *= 1.03
    if scenario == "pace_friendly" and p.get("role") in {"BOWL","AR"}: value *= 1.03
    if strategy == "grand_league" and p.get("selection_pct") is not None:
        value *= 1.08 if p["selection_pct"] < 25 else 0.97 if p["selection_pct"] > 75 else 1.0
    value *= _score_context_multiplier(p, innings_mode, score_team, scenario_score, match_format)
    return value

def _valid(p, chosen, rules, team_a, team_a_count, allow_missing_expected=False):
    if p.get("credits") is None or (not allow_missing_expected and p.get("expected_points") is None):
        return False
    if rules.playing_xi_only and (p.get("status") or "").lower() not in {"playing","confirmed"}:
        return False
    if sum(float(x["credits"]) for x in chosen) + float(p["credits"]) > rules.max_credits:
        return False
    if sum(x["team"] == p["team"] for x in chosen) >= rules.max_from_one_team:
        return False
    if sum(x["role"] == p["role"] for x in chosen) >= rules.max_role.get(p["role"], rules.team_size):
        return False
    if team_a_count is not None and team_a and p["team"] == team_a and sum(x["team"] == team_a for x in chosen) >= team_a_count:
        return False
    if team_a_count is not None and team_a and p["team"] != team_a and sum(x["team"] != team_a for x in chosen) >= rules.team_size-team_a_count:
        return False
    return True

def build_teams(players, strategy, rules, count_teams=1, scenario="neutral",
                team_a=None, locked_ids=None, excluded_ids=None,
                captain_pool=None, vice_captain_pool=None,
                manual_captain_id=None, manual_vice_captain_id=None,
                mode="ai_prediction", innings_mode="none", score_team=None,
                scenario_score=None, match_format="T20"):
    if mode not in {"ai_prediction", "provisional"}:
        raise ValueError("Unknown team generation mode.")
    provisional = mode == "provisional"
    locked_ids, excluded_ids = set(locked_ids or []), set(excluded_ids or [])
    captain_pool, vice_captain_pool = set(captain_pool or []), set(vice_captain_pool or [])
    by_id = {p["player_id"]:dict(p) for p in players}
    if locked_ids & excluded_ids: raise ValueError("A player cannot be both locked and excluded.")
    if not locked_ids.issubset(by_id): raise ValueError("A locked player is not in this match squad.")
    if manual_captain_id and manual_captain_id not in by_id: raise ValueError("Manual captain is not in the squad.")
    if manual_vice_captain_id and manual_vice_captain_id not in by_id: raise ValueError("Manual vice-captain is not in the squad.")
    if manual_captain_id and manual_captain_id == manual_vice_captain_id:
        raise ValueError("Captain and vice-captain must be different.")
    if manual_captain_id and captain_pool and manual_captain_id not in captain_pool:
        raise ValueError("Manual captain must be included in the captain pool.")
    if manual_vice_captain_id and vice_captain_pool and manual_vice_captain_id not in vice_captain_pool:
        raise ValueError("Manual vice-captain must be included in the vice-captain pool.")
    pool = [p for p in players if p["player_id"] not in excluded_ids]
    if not provisional and any(p.get("expected_points") is None for p in pool):
        raise ValueError("AI Prediction Mode requires expected fantasy points for every eligible squad player.")
    if any(by_id[x].get("credits") is None for x in locked_ids):
        raise ValueError("A locked player has unknown credits.")
    if len(locked_ids) > rules.team_size: raise ValueError("More locked players than team size.")
    if rules.team_a_count is not None and not team_a: raise ValueError("team_a is required when team_a_count is set.")
    for pid in locked_ids:
        p=by_id[pid]
        if rules.playing_xi_only and (p.get("status") or "").lower() not in {"playing","confirmed"}:
            raise ValueError(f"Locked player {p.get('player_name')} is not confirmed in the Playing XI.")
    # Validate locked players before search; locks must not bypass Dream11 limits.
    locked = list(by_id[x] for x in locked_ids)
    locked_counts = Counter(p["role"] for p in locked)
    if sum(float(p["credits"]) for p in locked) > rules.max_credits:
        raise ValueError("Locked players exceed the maximum credits.")
    if any(n > rules.max_role.get(role, rules.team_size) for role,n in locked_counts.items()):
        raise ValueError("Locked players exceed a role maximum.")
    if any(sum(p["team"] == t for p in locked) > rules.max_from_one_team for t in {p["team"] for p in locked}):
        raise ValueError("Locked players exceed the maximum from one team.")
    if rules.team_a_count is not None:
        a_count=sum(p["team"] == team_a for p in locked)
        if a_count > rules.team_a_count or len(locked)-a_count > rules.team_size-rules.team_a_count:
            raise ValueError("Locked players conflict with the required team split.")
    made, usage = [], Counter()
    states = [(locked, 0.0)]
    score_args = (innings_mode, score_team, scenario_score, match_format)
    for _ in range(rules.team_size-len(locked)):
        expanded=[]
        for chosen,_score_so_far in states:
            chosen_ids={p["player_id"] for p in chosen}
            for p in pool:
                if p["player_id"] in chosen_ids or not _valid(p,chosen,rules,team_a,rules.team_a_count,provisional):
                    continue
                next_chosen=chosen+[p]
                counts=Counter(x["role"] for x in next_chosen)
                remaining=rules.team_size-len(next_chosen)
                deficits=sum(max(0,n-counts[r]) for r,n in rules.min_role.items())
                if deficits > remaining: continue
                value=sum(_player_signal(x,strategy,scenario,*score_args,provisional=provisional) - usage[x["player_id"]]*max(2.5, _player_signal(x,strategy,scenario,*score_args,provisional=provisional)*0.10) for x in next_chosen)
                expanded.append((next_chosen,value))
        if not expanded: break
        unique={}
        for chosen_set, value in expanded:
            key=tuple(sorted(p["player_id"] for p in chosen_set))
            if key not in unique or value > unique[key][1]:
                unique[key]=(chosen_set,value)
        expanded=list(unique.values())
        expanded.sort(key=lambda x:x[1], reverse=True)
        # Keep a diverse beam so later teams are not limited to one near-identical branch.
        diverse=[]
        beam_ids=[]
        for candidate, candidate_score in expanded:
            candidate_ids={p["player_id"] for p in candidate}
            if any(len(candidate_ids & prior) >= rules.team_size-1 for prior in beam_ids):
                continue
            diverse.append((candidate,candidate_score))
            beam_ids.append(candidate_ids)
            if len(diverse)>=350:
                break
        states=diverse or expanded[:350]
    valid=[]
    for chosen,score in states:
        counts=Counter(p["role"] for p in chosen)
        team_counts=Counter(p["team"] for p in chosen)
        if len(chosen)!=rules.team_size or any(counts[r]<n for r,n in rules.min_role.items()): continue
        if any(counts[r]>rules.max_role.get(r,rules.team_size) for r in counts): continue
        if any(n>rules.max_from_one_team for n in team_counts.values()): continue
        if sum(float(p["credits"]) for p in chosen)>rules.max_credits: continue
        if rules.team_a_count is not None and team_counts[team_a]!=rules.team_a_count: continue
        valid.append((chosen,score))
    if not valid:
        raise ValueError("No legal team found. Check credits, roles, confirmed XI, locked players and team split.")
    valid.sort(key=lambda x:x[1],reverse=True)
    # Select different lineups by player identity, not merely the next sorted result.
    selected_lineups = []
    remaining_valid = list(valid)
    for index in range(min(count_teams, len(remaining_valid))):
        best_entry = None
        best_adjusted = None
        for chosen_candidate, base_score in remaining_valid:
            candidate_ids = {p["player_id"] for p in chosen_candidate}
            overlap_penalty = 0.0
            for prior_ids in selected_lineups:
                overlap = len(candidate_ids & prior_ids)
                similarity = overlap / max(1, rules.team_size)
                # Push later teams toward genuinely different constructions.
                overlap_penalty += (similarity ** 2) * (0.10 if strategy != "grand_league" else 0.15) * max(base_score, 1.0)
            adjusted = base_score - overlap_penalty
            if best_entry is None or adjusted > best_adjusted:
                best_entry, best_adjusted = (chosen_candidate, base_score), adjusted
        if best_entry is None:
            break
        chosen, score = best_entry
        chosen_ids = {p["player_id"] for p in chosen}
        selected_lineups.append(chosen_ids)
        remaining_valid = [(c, s) for c, s in remaining_valid if {p["player_id"] for p in c} != chosen_ids]
        ids = chosen_ids
        cands = [p for p in chosen if not captain_pool or p["player_id"] in captain_pool]
        vcands = [p for p in chosen if not vice_captain_pool or p["player_id"] in vice_captain_pool]
        captain_key = lambda p: _captain_score(p, strategy, scenario, *score_args)
        captain = next((p for p in cands if p["player_id"] == manual_captain_id), None) or (sorted(cands, key=captain_key, reverse=True)[0] if cands else None)
        vice_key = lambda p: _vice_score(p, strategy, scenario, *score_args)
        vice = next((p for p in vcands if p["player_id"] == manual_vice_captain_id), None) or (sorted([p for p in vcands if not captain or p["player_id"] != captain["player_id"]], key=vice_key, reverse=True)[0] if vcands else None)
        if not captain or not vice:
            raise ValueError("Captain and vice-captain pools must contain two different selected players.")
        if captain["player_id"] not in ids or vice["player_id"] not in ids:
            raise ValueError("Captain and vice-captain must be selected in the team.")
        for p in chosen:
            usage[p["player_id"]] += 1
        total = sum(float(p["credits"]) for p in chosen)
        projected = None if provisional else round(sum(float(p["expected_points"]) for p in chosen) + float(captain["expected_points"]) + 0.5 * float(vice["expected_points"]), 2)
        captain_alternatives = sorted([p for p in chosen if p["player_id"] != captain["player_id"]], key=captain_key, reverse=True)[:2]
        vice_alternatives = sorted([p for p in chosen if p["player_id"] != vice["player_id"]], key=vice_key, reverse=True)[:2]
        made.append({"generation_mode":mode,"strategy":strategy,"scenario":scenario,
            "score_scenario":{"mode":innings_mode,"team":score_team,"scenario_score":scenario_score,"format":match_format} if innings_mode != "none" else None,
            "players":chosen,
            "captain_id":captain["player_id"],"vice_captain_id":vice["player_id"],
            "captain_alternatives":[{"player_id":p["player_id"],"player_name":p.get("player_name"),"score":round(captain_key(p),2)} for p in captain_alternatives],
            "vice_captain_alternatives":[{"player_id":p["player_id"],"player_name":p.get("player_name"),"score":round(vice_key(p),2)} for p in vice_alternatives],
            "captain_reason":"Strategy-weighted ranking of expected contribution, ceiling, floor and role opportunity; popularity is not the deciding factor.",
            "vice_captain_reason":"Independently ranked for vice-captain balance of expected contribution, floor and ceiling.",
            "team_strength_score":round(score,2),
            "risk_profile":"high-upside" if strategy=="grand_league" else "lower-variance" if strategy=="safe" else "balanced-risk",
            "total_credits":round(total,1),"projected_points":projected,
            "selection_score":round(score,2),"role_counts":dict(Counter(p["role"] for p in chosen)),
            "team_split":dict(Counter(p["team"] for p in chosen)),
            "points_available":not provisional,
            "score_meaning":"model projected fantasy points including C/VC" if not provisional else "selection-priority score only; not fantasy points"})
    return made
