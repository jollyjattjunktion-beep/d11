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
        # AI11 career/series aggregates can refine a provisional selection
        # index slightly, but never become expected/floor/ceiling fantasy points.
        try:
            ai11_factor = max(0.97, min(1.03, float(p.get("ai11_profile_factor") or 1.0)))
            base *= ai11_factor
        except (TypeError, ValueError):
            pass
        floor_v, upside, consistency = base * 0.55, base * (1.18 if p.get("role") in {"AR", "WK"} else 1.08), 0.35

    # AI11 performance profiles influence selection in BOTH modes while
    # never being converted into a fantasy-point estimate. Current-series form
    # and the role-specific career score are intentionally more meaningful
    # than public selection/C/VC percentages.
    try:
        role_score = p.get("ai11_role_score")
        recent_score = p.get("ai11_recent_form_score")
        profile_scores = []
        if role_score is not None:
            profile_scores.append((float(role_score), 0.70))
        if recent_score is not None:
            profile_scores.append((float(recent_score), 0.30))
        if profile_scores:
            profile_strength = sum(score * weight for score, weight in profile_scores) / sum(weight for _, weight in profile_scores)
            profile_multiplier = max(0.80, min(1.20, 1.0 + (profile_strength - 50.0) * 0.004))
            base *= profile_multiplier
        if p.get("role") == "AR" and p.get("ai11_two_skill_profile"):
            bat_score = p.get("ai11_batting_score")
            bowl_score = p.get("ai11_bowling_score")
            if bat_score is not None and bowl_score is not None:
                if min(float(bat_score), float(bowl_score)) >= 70:
                    base *= 1.04
                elif min(float(bat_score), float(bowl_score)) >= 60:
                    base *= 1.02
    except (TypeError, ValueError):
        pass

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
    # With no historical fantasy-point sample, retain the predictor's bounded
    # venue/weather adjustment as a selection signal. Historical predictions
    # already include this adjustment, so do not apply it twice.
    if expected is None and p.get("condition_factor") is not None:
        try:
            condition *= max(0.82, min(1.18, float(p["condition_factor"])))
        except (TypeError, ValueError):
            pass
    try:
        if role in {"BAT", "WK", "AR"} and p.get("batting_friendly") is not None:
            condition += (float(p["batting_friendly"]) - 0.5) * 0.12
        if role in {"BOWL", "AR"} and p.get("pace_friendly") is not None:
            condition += (float(p["pace_friendly"]) - 0.5) * 0.08
        if role in {"BOWL", "AR"} and p.get("spin_friendly") is not None:
            condition += (float(p["spin_friendly"]) - 0.5) * 0.08
        # When AI11 provides a source-described pitch but no numerical Cricbuzz
        # pace/spin factor, use the player's imported discipline as a small fit.
        if scenario == "batting_friendly" and role in {"BAT", "WK", "AR"}:
            bat_score = p.get("ai11_batting_score")
            if bat_score is not None:
                condition *= max(0.96, min(1.04, 1.0 + (float(bat_score) - 50.0) * 0.0008))
        if scenario in {"pace_friendly", "bowling_friendly"} and role in {"BOWL", "AR"}:
            bowl_score = p.get("ai11_bowling_score")
            if bowl_score is not None:
                condition *= max(0.96, min(1.04, 1.0 + (float(bowl_score) - 50.0) * 0.0008))
        if scenario == "spin_friendly" and role in {"BOWL", "AR"}:
            bowl_score = p.get("ai11_bowling_score")
            style = p.get("ai11_bowling_style_group")
            if bowl_score is not None:
                style_factor = 1.015 if style == "spin" else 0.99 if style == "pace" else 1.0
                condition *= max(0.96, min(1.04, (1.0 + (float(bowl_score) - 50.0) * 0.0005) * style_factor))
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
        score = 0.62 * signal + 0.30 * floor_component + 0.08 * ceiling_component
    elif strategy == "grand_league":
        score = 0.35 * signal + 0.55 * ceiling_component + 0.10 * _role_opportunity(p) * signal
    else:
        score = 0.52 * signal + 0.30 * ceiling_component + 0.18 * floor_component
    # Imported provider C trends are a secondary signal in provisional mode,
    # useful when this player has no historical fantasy-point estimate.
    try:
        profile_score = p.get("ai11_role_score")
        if profile_score is not None:
            # Reward demonstrated multi-skill/recent-form profile, but keep
            # captaincy tied to the chosen XI and the base contribution signal.
            score *= max(0.88, min(1.12, 1.0 + (float(profile_score) - 50.0) * 0.0028))
        if p.get("role") == "AR" and p.get("ai11_two_skill_profile"):
            bat_score = p.get("ai11_batting_score")
            bowl_score = p.get("ai11_bowling_score")
            if bat_score is not None and bowl_score is not None and min(float(bat_score), float(bowl_score)) >= 65:
                score *= 1.035
    except (TypeError, ValueError):
        pass
    if expected is None:
        try:
            source_c = float(p.get("captain_pct") or p.get("ai11_captain_pct") or 0)
            score += min(100.0, max(0.0, source_c)) * 0.06
        except (TypeError, ValueError):
            pass
    return score


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
        score = 0.68 * signal + 0.25 * floor_component + 0.07 * ceiling_component
    elif strategy == "grand_league":
        score = 0.42 * signal + 0.48 * ceiling_component + 0.10 * _role_opportunity(p) * signal
    else:
        score = 0.58 * signal + 0.27 * ceiling_component + 0.15 * floor_component
    # Provider VC trends support the provisional decision; they never replace
    # the role, availability and involvement assessment.
    try:
        profile_score = p.get("ai11_role_score")
        if profile_score is not None:
            score *= max(0.90, min(1.10, 1.0 + (float(profile_score) - 50.0) * 0.002))
    except (TypeError, ValueError):
        pass
    if expected is None:
        try:
            source_vc = float(p.get("vice_captain_pct") or p.get("ai11_vice_captain_pct") or 0)
            score += min(100.0, max(0.0, source_vc)) * 0.06
        except (TypeError, ValueError):
            pass
    return score


def _portfolio_exposure_score(raw_score, player_id, exposure, strategy, kind="captain"):
    """Reduce repeat C/VC exposure across one generated portfolio, without forcing weak picks."""
    weights = {
        "safe": 0.055,
        "balanced": 0.12,
        "scenario": 0.14,
        "grand_league": 0.18,
    }
    weight = weights.get(strategy, 0.12)
    if kind == "vice":
        weight *= 0.90
    repeat_count = exposure.get(player_id, 0)
    penalty = min(0.36, weight * repeat_count)
    return raw_score * (1.0 - penalty)


def _captaincy_reason(player, strategy, role_label):
    """Build an evidence-aware explanation; provisional scores are never called fantasy points."""
    name = player.get("player_name") or "This player"
    expected = player.get("expected_points")
    floor = player.get("floor_points")
    ceiling = player.get("ceiling_points") or player.get("upside")
    details = []
    if expected is not None:
        details.append(f"modelled expected contribution {float(expected):.1f}")
        if floor is not None:
            details.append(f"floor {float(floor):.1f}")
        if ceiling is not None:
            details.append(f"ceiling {float(ceiling):.1f}")
    else:
        details.append("provisional role/opportunity score; historical fantasy-point estimates are unavailable")
    if player.get("batting_position") is not None:
        details.append(f"expected batting position {player['batting_position']}")
    if player.get("expected_overs") is not None:
        details.append(f"expected bowling workload {float(player['expected_overs']):g} overs")
    if player.get("involvement_score") is not None:
        details.append("imported involvement score available")
    if expected is None and player.get("condition_factor") is not None:
        details.append(f"venue/weather adjustment {float(player['condition_factor']):.2f}x applied to the provisional role score")
    status = str(player.get("status") or "unknown").lower()
    if status in {"playing", "confirmed"}:
        details.append("Playing XI confirmed")
    elif status in {"probable", "likely", "available"}:
        details.append("availability is probable, not confirmed")
    if player.get("selection_pct") is not None and strategy == "grand_league":
        details.append(f"provider selection {float(player['selection_pct']):.1f}% considered only as a differential signal")
    trend_field = "captain_pct" if role_label == "captain" else "vice_captain_pct"
    trend_value = player.get(trend_field) or player.get(
        "ai11_captain_pct" if role_label == "captain" else "ai11_vice_captain_pct"
    )
    if trend_value is not None and expected is None:
        details.append(f"provider {role_label} trend {float(trend_value):.1f}% used as a secondary provisional signal")
    return f"{name} selected as {role_label} for {strategy.replace('_', ' ')}: " + "; ".join(details) + "."


def _score_context_multiplier(p, innings_mode, score_team, scenario_score, match_format):
    """Small role-opportunity preference for an innings scenario, never a points prediction."""
    if innings_mode not in {"first_innings", "chasing"} or not score_team:
        return 1.0
    fmt = str(match_format or "T20").upper()
    high_threshold, low_threshold = {
        "T20": (180, 145),
        "ODI": (280, 230),
        "TEST": (350, 220),
    }.get(fmt, (180, 145))
    high_score = int(scenario_score) >= high_threshold if scenario_score is not None else None
    low_score = int(scenario_score) <= low_threshold if scenario_score is not None else None
    team = p.get("team")
    role = p.get("role")
    batting_roles = {"BAT", "WK", "AR"}
    bowling_roles = {"BOWL", "AR"}
    if innings_mode == "first_innings":
        if team == score_team and role in batting_roles:
            return 1.04 if high_score is True else 1.015 if high_score is None else 0.985
        if team != score_team and role in bowling_roles:
            return 1.035 if high_score is True else 1.02 if low_score is True or low_score is None else 1.0
    else:
        # score_team is the chasing side.
        if team == score_team and role in batting_roles:
            return 1.04 if high_score is True else 1.02 if high_score is None or low_score is False else 1.015
        if team != score_team and role in bowling_roles:
            return 1.035 if high_score is True else 1.02
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
    status = str(p.get("status") or "unknown").strip().lower()
    if status in {"out", "injured", "unavailable", "not_playing"}:
        return False
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
    made, usage, captain_usage, vice_usage, pair_usage = [], Counter(), Counter(), Counter(), Counter()
    # Score each candidate once. A high-quality partial XI is judged by its
    # achievable upper bound, not only its current total; this avoids pruning
    # a strong lineup just because it needs a lower-scoring role to stay legal.
    candidate_scores = {
        p["player_id"]: _player_signal(
            p, strategy, scenario, innings_mode, score_team, scenario_score,
            match_format, provisional=provisional
        )
        for p in pool
    }
    locked_score = sum(candidate_scores.get(p["player_id"], 0.0) for p in locked)
    states = [(locked, locked_score)]
    beam_width = min(5000, max(2000, len(pool) * 200))

    def partial_is_feasible(chosen, remaining_slots):
        counts = Counter(p["role"] for p in chosen)
        available = [p for p in pool if p["player_id"] not in {x["player_id"] for x in chosen}]
        available_roles = Counter(p["role"] for p in available)
        if any(counts[role] + available_roles[role] < minimum
               for role, minimum in rules.min_role.items()):
            return False
        if sum(max(0, minimum - counts[role])
               for role, minimum in rules.min_role.items()) > remaining_slots:
            return False
        if rules.team_a_count is not None:
            selected_a = sum(p["team"] == team_a for p in chosen)
            selected_b = len(chosen) - selected_a
            need_a = rules.team_a_count - selected_a
            need_b = rules.team_size - rules.team_a_count - selected_b
            available_a = sum(p["team"] == team_a for p in available)
            available_b = len(available) - available_a
            if need_a < 0 or need_b < 0 or need_a > available_a or need_b > available_b:
                return False
            if need_a + need_b != remaining_slots:
                return False
        credit_left = rules.max_credits - sum(float(p["credits"]) for p in chosen)
        if credit_left < 0:
            return False
        if remaining_slots:
            cheapest = sorted(float(p["credits"]) for p in available)[:remaining_slots]
            if len(cheapest) < remaining_slots or sum(cheapest) > credit_left + 1e-9:
                return False
        return True

    for _ in range(rules.team_size - len(locked)):
        expanded = {}
        for chosen, score_so_far in states:
            chosen_ids = {p["player_id"] for p in chosen}
            for p in pool:
                pid = p["player_id"]
                if pid in chosen_ids or not _valid(
                    p, chosen, rules, team_a, rules.team_a_count, provisional
                ):
                    continue
                next_chosen = chosen + [p]
                remaining = rules.team_size - len(next_chosen)
                counts = Counter(x["role"] for x in next_chosen)
                deficits = sum(
                    max(0, minimum - counts[role])
                    for role, minimum in rules.min_role.items()
                )
                if deficits > remaining or not partial_is_feasible(next_chosen, remaining):
                    continue

                value = score_so_far + candidate_scores.get(pid, 0.0)
                next_ids = chosen_ids | {pid}
                best_remaining = sorted(
                    (candidate_scores.get(other["player_id"], 0.0)
                     for other in pool if other["player_id"] not in next_ids),
                    reverse=True
                )[:remaining]
                optimistic = value + sum(best_remaining)
                key = tuple(sorted(next_ids))
                previous = expanded.get(key)
                if previous is None or optimistic > previous[2]:
                    expanded[key] = (next_chosen, value, optimistic)

        if not expanded:
            break
        ordered = sorted(expanded.values(), key=lambda entry: entry[2], reverse=True)
        states = [(chosen, value) for chosen, value, _ in ordered[:beam_width]]
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
    # Build a portfolio of strong but meaningfully different lineups. Diversity is
    # preferred only within a strategy-specific quality band; weak differentials are not forced.
    valid.sort(key=lambda x: x[1], reverse=True)
    selected_lineups = []
    remaining_valid = list(valid)
    min_unique_players = {
        "safe": 1,
        "balanced": 2,
        "scenario": 3,
        "grand_league": 3,
    }.get(strategy, 2)
    quality_floor = {
        "safe": 0.90,
        "balanced": 0.84,
        "scenario": 0.82,
        "grand_league": 0.76,
    }.get(strategy, 0.84)
    overlap_weight = {
        "safe": 0.12,
        "balanced": 0.22,
        "scenario": 0.25,
        "grand_league": 0.30,
    }.get(strategy, 0.22)
    captain_pair_weight = {
        "safe": 0.035,
        "balanced": 0.075,
        "scenario": 0.09,
        "grand_league": 0.12,
    }.get(strategy, 0.075)

    for index in range(min(count_teams, len(remaining_valid))):
        if not remaining_valid:
            break
        best_base = max(score for _, score in remaining_valid)
        quality_candidates = [
            entry for entry in remaining_valid
            if entry[1] >= best_base * quality_floor
        ] or remaining_valid

        # Try to keep at least the requested number of players different from each
        # already-built team. Relax only when the candidate pool cannot support it.
        diversity_candidates = []
        for candidate, candidate_score in quality_candidates:
            candidate_ids = {p["player_id"] for p in candidate}
            if all(
                len(candidate_ids & prior_ids) <= rules.team_size - min_unique_players
                for prior_ids in selected_lineups
            ):
                diversity_candidates.append((candidate, candidate_score))
        candidate_pool = diversity_candidates or quality_candidates

        best_entry = None
        best_adjusted = None
        for chosen_candidate, base_score in candidate_pool:
            candidate_ids = {p["player_id"] for p in chosen_candidate}
            overlap_penalty = 0.0
            repeat_penalty = 0.0
            for prior_ids in selected_lineups:
                overlap = len(candidate_ids & prior_ids)
                similarity = overlap / max(1, rules.team_size)
                overlap_penalty += (similarity ** 2) * overlap_weight * max(base_score, 1.0)
            # A small portfolio exposure penalty avoids repeatedly using the same
            # core players when two legal teams are otherwise similarly strong.
            for player in chosen_candidate:
                prior_uses = usage.get(player["player_id"], 0)
                if prior_uses:
                    player_signal = _player_signal(
                        player, strategy, scenario, *score_args,
                        provisional=provisional
                    )
                    repeat_penalty += min(0.045 * prior_uses, 0.18) * player_signal
            adjusted = base_score - overlap_penalty - repeat_penalty
            if best_entry is None or adjusted > best_adjusted:
                best_entry, best_adjusted = (chosen_candidate, base_score), adjusted

        if best_entry is None:
            break
        chosen, score = best_entry
        chosen_ids = {p["player_id"] for p in chosen}
        selected_lineups.append(chosen_ids)
        remaining_valid = [
            (candidate, value) for candidate, value in remaining_valid
            if {p["player_id"] for p in candidate} != chosen_ids
        ]

        cands = [p for p in chosen if not captain_pool or p["player_id"] in captain_pool]
        vcands = [p for p in chosen if not vice_captain_pool or p["player_id"] in vice_captain_pool]
        captain_key = lambda p: _captain_score(p, strategy, scenario, *score_args)
        vice_key = lambda p: _vice_score(p, strategy, scenario, *score_args)
        # Treat captain and vice-captain as one leadership pool so a player is
        # not repeatedly recycled from C to VC (or vice versa) in every lineup.
        leadership_usage = captain_usage + vice_usage

        captain_rank = lambda p: _portfolio_exposure_score(
            captain_key(p), p["player_id"], leadership_usage, strategy, "captain"
        )
        captain = (
            next((p for p in cands if p["player_id"] == manual_captain_id), None)
            or (max(cands, key=captain_rank) if cands else None)
        )

        def vice_rank(p):
            base = _portfolio_exposure_score(
                vice_key(p), p["player_id"], leadership_usage, strategy, "vice"
            )
            if captain is not None:
                pair_key = tuple(sorted((captain["player_id"], p["player_id"]), key=lambda value: str(value)))
                pair_count = pair_usage.get(pair_key, 0)
                base *= 1.0 - min(0.24, captain_pair_weight * pair_count)
            return base

        vice_options = [
            p for p in vcands
            if not captain or p["player_id"] != captain["player_id"]
        ]
        vice = (
            next((p for p in vice_options if p["player_id"] == manual_vice_captain_id), None)
            or (max(vice_options, key=vice_rank) if vice_options else None)
        )
        if not captain or not vice:
            raise ValueError("Captain and vice-captain pools must contain two different selected players.")
        if captain["player_id"] not in chosen_ids or vice["player_id"] not in chosen_ids:
            raise ValueError("Captain and vice-captain must be selected in the team.")

        captain_alternatives = sorted(
            [p for p in chosen if p["player_id"] != captain["player_id"]],
            key=captain_rank,
            reverse=True
        )[:2]
        vice_alternatives = sorted(
            [p for p in chosen if p["player_id"] != vice["player_id"]],
            key=vice_rank,
            reverse=True
        )[:2]

        total = sum(float(p["credits"]) for p in chosen)
        projected = (
            None if provisional else
            round(sum(float(p["expected_points"]) for p in chosen)
                  + float(captain["expected_points"])
                  + 0.5 * float(vice["expected_points"]), 2)
        )

        # Update exposure only after the current XI and its C/VC have been selected.
        for player in chosen:
            usage[player["player_id"]] += 1
        captain_usage[captain["player_id"]] += 1
        vice_usage[vice["player_id"]] += 1
        pair_key = tuple(sorted((captain["player_id"], vice["player_id"]), key=lambda value: str(value)))
        pair_usage[pair_key] += 1

        made.append({
            "generation_mode": mode,
            "portfolio_rank": len(made) + 1,
            "recommendation_tier": "best_ranked_xi" if not made else "diversified_alternative",
            "strategy": strategy,
            "scenario": scenario,
            "score_scenario": {
                "mode": innings_mode, "team": score_team,
                "scenario_score": scenario_score, "format": match_format
            } if innings_mode != "none" else None,
            "players": chosen,
            "captain_id": captain["player_id"],
            "vice_captain_id": vice["player_id"],
            "captain_alternatives": [
                {"player_id": p["player_id"], "player_name": p.get("player_name"),
                 "score": round(captain_rank(p), 2)}
                for p in captain_alternatives
            ],
            "vice_captain_alternatives": [
                {"player_id": p["player_id"], "player_name": p.get("player_name"),
                 "score": round(vice_rank(p), 2)}
                for p in vice_alternatives
            ],
            "captain_reason": _captaincy_reason(captain, strategy, "captain"),
            "vice_captain_reason": _captaincy_reason(vice, strategy, "vice-captain"),
            "team_strength_score": round(score, 2),
            "risk_profile": "high-upside" if strategy == "grand_league" else "lower-variance" if strategy == "safe" else "balanced-risk",
            "total_credits": round(total, 1),
            "projected_points": projected,
            "selection_score": round(score, 2),
            "role_counts": dict(Counter(p["role"] for p in chosen)),
            "team_split": dict(Counter(p["team"] for p in chosen)),
            "points_available": not provisional,
            "score_meaning": "model projected fantasy points including C/VC" if not provisional else "selection-priority score only; not fantasy points",
        })

    # Publish portfolio-level exposure and overlap metrics for the UI and audit.
    portfolio_size = max(1, len(made))
    lineup_exposure = Counter(
        player["player_id"] for team in made for player in team["players"]
    )
    captain_exposure = Counter(team["captain_id"] for team in made)
    vice_exposure = Counter(team["vice_captain_id"] for team in made)
    for team_index, team in enumerate(made):
        team_ids = {player["player_id"] for player in team["players"]}
        previous_overlaps = [
            len(team_ids & {player["player_id"] for player in previous["players"]})
            for previous in made[:team_index]
        ]
        team["lineup_overlap_pct"] = round(
            (max(previous_overlaps) / max(1, rules.team_size)) * 100, 1
        ) if previous_overlaps else 0.0
        team["captain_exposure_pct"] = round(
            captain_exposure[team["captain_id"]] / portfolio_size * 100, 1
        )
        team["vice_captain_exposure_pct"] = round(
            vice_exposure[team["vice_captain_id"]] / portfolio_size * 100, 1
        )
        for player in team["players"]:
            player["portfolio_exposure_pct"] = round(
                lineup_exposure[player["player_id"]] / portfolio_size * 100, 1
            )
        team["portfolio_exposure"] = [
            {
                "player_id": player_id,
                "player_name": next(
                    (p.get("player_name") for p in team["players"]
                     if p["player_id"] == player_id), player_id
                ),
                "teams_selected": count,
                "exposure_pct": round(count / portfolio_size * 100, 1),
            }
            for player_id, count in sorted(
                lineup_exposure.items(), key=lambda item: (-item[1], str(item[0]))
            )
        ]
        team["portfolio_captain_usage"] = [
            {"player_id": player_id, "teams_as_captain": count,
             "exposure_pct": round(count / portfolio_size * 100, 1)}
            for player_id, count in captain_exposure.items()
        ]
        team["portfolio_vice_usage"] = [
            {"player_id": player_id, "teams_as_vice_captain": count,
             "exposure_pct": round(count / portfolio_size * 100, 1)}
            for player_id, count in vice_exposure.items()
        ]
    return made
