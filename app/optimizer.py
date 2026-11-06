from collections import Counter

STRATEGY_WEIGHTS = {
    "safe": (0.55, 0.35, 0.10),
    "balanced": (0.65, 0.20, 0.15),
    "grand_league": (0.45, 0.05, 0.50),
    "scenario": (0.60, 0.15, 0.25),
}

def _score(p, strategy, scenario):
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
    return value

def _valid(p, chosen, rules, team_a, team_a_count):
    if p.get("credits") is None or p.get("expected_points") is None: return False
    if rules.playing_xi_only and (p.get("status") or "").lower() not in {"playing","confirmed"}: return False
    if sum(float(x["credits"]) for x in chosen) + float(p["credits"]) > rules.max_credits: return False
    if sum(x["team"] == p["team"] for x in chosen) >= rules.max_from_one_team: return False
    if sum(x["role"] == p["role"] for x in chosen) >= rules.max_role.get(p["role"], rules.team_size): return False
    if team_a_count is not None and team_a and p["team"] == team_a and sum(x["team"] == team_a for x in chosen) >= team_a_count: return False
    if team_a_count is not None and team_a and p["team"] != team_a and sum(x["team"] != team_a for x in chosen) >= rules.team_size-team_a_count: return False
    return True

def build_teams(players, strategy, rules, count_teams=1, scenario="neutral",
                team_a=None, locked_ids=None, excluded_ids=None,
                captain_pool=None, vice_captain_pool=None,
                manual_captain_id=None, manual_vice_captain_id=None):
    locked_ids, excluded_ids = set(locked_ids or []), set(excluded_ids or [])
    captain_pool, vice_captain_pool = set(captain_pool or []), set(vice_captain_pool or [])
    by_id = {p["player_id"]:dict(p) for p in players}
    if locked_ids & excluded_ids: raise ValueError("A player cannot be both locked and excluded.")
    if not locked_ids.issubset(by_id): raise ValueError("A locked player is not in this match squad.")
    if manual_captain_id and manual_captain_id not in by_id: raise ValueError("Manual captain is not in the squad.")
    if manual_vice_captain_id and manual_vice_captain_id not in by_id: raise ValueError("Manual vice-captain is not in the squad.")
    if manual_captain_id and manual_captain_id == manual_vice_captain_id: raise ValueError("Captain and vice-captain must be different.")
    pool = [p for p in players if p["player_id"] not in excluded_ids]
    if any(by_id[x].get("credits") is None for x in locked_ids): raise ValueError("A locked player has unknown credits.")
    if len(locked_ids) > rules.team_size: raise ValueError("More locked players than team size.")
    if rules.team_a_count is not None and not team_a: raise ValueError("team_a is required when team_a_count is set.")
    for pid in locked_ids:
        p=by_id[pid]
        if rules.playing_xi_only and (p.get("status") or "").lower() not in {"playing","confirmed"}:
            raise ValueError(f"Locked player {p.get('player_name')} is not confirmed in the Playing XI.")
    made, usage = [], Counter()
    # Beam search explores alternatives instead of committing to a single greedy pick.
    states = [(list(by_id[x] for x in locked_ids), 0.0)]
    for _ in range(rules.team_size-len(locked_ids)):
        expanded=[]
        for chosen,_score_so_far in states:
            chosen_ids={p["player_id"] for p in chosen}
            for p in pool:
                if p["player_id"] in chosen_ids or not _valid(p,chosen,rules,team_a,rules.team_a_count):
                    continue
                next_chosen=chosen+[p]
                counts=Counter(x["role"] for x in next_chosen)
                remaining=rules.team_size-len(next_chosen)
                deficits=sum(max(0,n-counts[r]) for r,n in rules.min_role.items())
                if deficits > remaining: continue
                value=sum(_score(x,strategy,scenario) - usage[x["player_id"]]*1.5 for x in next_chosen)
                expanded.append((next_chosen,value))
        if not expanded: break
        # Deduplicate the same XI reached through different selection orders.
        unique={}
        for chosen_set, value in expanded:
            key=tuple(sorted(p["player_id"] for p in chosen_set))
            if key not in unique or value > unique[key][1]:
                unique[key]=(chosen_set,value)
        expanded=list(unique.values())
        expanded.sort(key=lambda x:x[1], reverse=True)
        # Keep a broad beam so later constraints and alternatives remain visible.
        states=expanded[:350]
    valid=[]
    for chosen,score in states:
        counts=Counter(p["role"] for p in chosen)
        if len(chosen)!=rules.team_size or any(counts[r]<n for r,n in rules.min_role.items()): continue
        if rules.team_a_count is not None and sum(p["team"]==team_a for p in chosen)!=rules.team_a_count: continue
        valid.append((chosen,score))
    if not valid:
        raise ValueError("No legal team found. Check credits, roles, confirmed XI, locked players and team split.")
    valid.sort(key=lambda x:x[1],reverse=True)
    for index in range(min(count_teams,len(valid))):
        chosen,score=valid[index]
        ids={p["player_id"] for p in chosen}
        cands=[p for p in chosen if not captain_pool or p["player_id"] in captain_pool]
        vcands=[p for p in chosen if not vice_captain_pool or p["player_id"] in vice_captain_pool]
        captain=next((p for p in cands if p["player_id"]==manual_captain_id),None) or (sorted(cands,key=lambda p:_score(p,strategy,scenario),reverse=True)[0] if cands else None)
        vice=next((p for p in vcands if p["player_id"]==manual_vice_captain_id),None) or (sorted([p for p in vcands if not captain or p["player_id"]!=captain["player_id"]],key=lambda p:_score(p,strategy,scenario),reverse=True)[0] if vcands else None)
        if not captain or not vice: raise ValueError("Captain and vice-captain pools must contain two different selected players.")
        if captain["player_id"] not in ids or vice["player_id"] not in ids: raise ValueError("Captain and vice-captain must be selected in the team.")
        for p in chosen: usage[p["player_id"]]+=1
        total=sum(float(p["credits"]) for p in chosen)
        projected=sum(float(p["expected_points"]) for p in chosen)+float(captain["expected_points"])+0.5*float(vice["expected_points"])
        made.append({"strategy":strategy,"scenario":scenario,"players":chosen,
            "captain_id":captain["player_id"],"vice_captain_id":vice["player_id"],
            "total_credits":round(total,1),"projected_points":round(projected,2),
            "selection_score":round(score,2),"role_counts":dict(Counter(p["role"] for p in chosen)),
            "team_split":dict(Counter(p["team"] for p in chosen))})
    return made
