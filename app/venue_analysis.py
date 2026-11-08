from __future__ import annotations


def _fmt_key(value: str | None) -> str:
    fmt = (value or "").upper().replace("-", "").replace(" ", "")
    if fmt in {"T20", "T20I", "WT20", "WT20I"}:
        return "T20"
    if fmt in {"ODI", "WODI", "ONE DAY", "ONEDAY"}:
        return "ODI"
    if fmt in {"TEST", "WTEST"}:
        return "TEST"
    return fmt


def _safe_float(value):
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def analyse_venue(report: dict, match_format: str) -> dict:
    """Explain format-matched ground trends; no inference is made from missing fields."""
    fmt = _fmt_key(match_format)
    stats = (report.get("formats") or {}).get(fmt)
    proxy_format = None
    # Cricbuzz venue profiles sometimes publish T20 history for T10 grounds,
    # but no T10-only sample. Use it only as an explicitly labelled low-confidence proxy.
    if not stats and fmt in {"T10", "WT10"} and (report.get("formats") or {}).get("T20"):
        stats = (report.get("formats") or {}).get("T20")
        proxy_format = "T20"
    profile = " ".join(str(x or "") for x in (
        report.get("pitch_text"), report.get("profile_text")
    )).casefold()
    if not stats:
        return {
            "format": fmt,
            "available": False,
            "pitch_recommendation": "Insufficient format-specific venue data",
            "toss_recommendation": "No venue-based toss recommendation",
            "strong_team": None,
            "confidence": "low",
            "reasons": [f"No {fmt} statistics were supplied by Cricbuzz for this venue."],
            "stats": None,
        }

    total = _safe_float(stats.get("total_matches"))
    bat_wins = _safe_float(stats.get("matches_won_batting_first"))
    bowl_wins = _safe_float(stats.get("matches_won_bowling_first"))
    first_avg = _safe_float(stats.get("average_first_innings_score"))
    second_avg = _safe_float(stats.get("average_second_innings_score"))
    decided = (bat_wins or 0) + (bowl_wins or 0)
    bat_rate = bat_wins / decided if decided else None
    bowl_rate = bowl_wins / decided if decided else None
    innings_gap_pct = ((first_avg - second_avg) / second_avg * 100) if first_avg is not None and second_avg not in (None, 0) else None

    textual_bat = any(term in profile for term in (
        "favour the bats", "favors the bats", "favours the bats", "batsmen",
        "batters", "good for batting", "batting friendly", "batting-friendly",
        "side with the bats"
    ))
    textual_bowl = any(term in profile for term in (
        "favour the bowl", "favors the bowl", "favours the bowl", "bowling friendly",
        "bowling-friendly", "help the bowl", "assist the bowl", "seam movement",
        "turning track", "turn for the spinner"
    ))

    reasons = []
    if proxy_format:
        reasons.append(f"No T10-only venue sample was published; T20 venue statistics are shown as a proxy for {fmt}, not as T10 results.")
    if total is not None:
        reasons.append(f"{int(total)} {fmt} matches in Cricbuzz venue sample.")
    if bat_rate is not None:
        reasons.append(f"Batting first won {int(bat_wins)} of {int(decided)} decided matches ({bat_rate*100:.1f}%).")
    if bowl_rate is not None:
        reasons.append(f"Bowling first won {int(bowl_wins)} of {int(decided)} decided matches ({bowl_rate*100:.1f}%).")
    if first_avg is not None and second_avg is not None:
        reasons.append(f"Average innings scores: {first_avg:g} first innings and {second_avg:g} second innings ({innings_gap_pct:+.1f}% first-innings difference).")
    if textual_bat:
        reasons.append("Cricbuzz venue profile describes the surface as batting-friendly.")
    if textual_bowl:
        reasons.append("Cricbuzz venue profile describes bowling assistance.")

    bat_score = 0.0
    bowl_score = 0.0
    signal_count = 0
    if textual_bat:
        bat_score += 2.0
        signal_count += 1
    if textual_bowl:
        bowl_score += 2.0
        signal_count += 1
    if innings_gap_pct is not None:
        if innings_gap_pct >= 8:
            bat_score += 1.0
        elif innings_gap_pct <= -8:
            bowl_score += 1.0
        signal_count += 1
    if bat_rate is not None and bowl_rate is not None:
        if bat_rate >= 0.56:
            bat_score += 1.0
        elif bowl_rate >= 0.56:
            bowl_score += 1.0
        signal_count += 1

    if bat_score - bowl_score >= 1.0:
        pitch = "Batting-friendly"
        pitch_type = "batting"
    elif bowl_score - bat_score >= 1.0:
        pitch = "Bowling-friendly"
        pitch_type = "bowling"
    else:
        pitch = "Balanced"
        pitch_type = "balanced"

    # Toss recommendation is deliberately more conservative than pitch type.
    if bat_rate is not None and bat_rate >= 0.58:
        toss = "Bat first"
        toss_key = "bat"
    elif bowl_rate is not None and bowl_rate >= 0.58:
        toss = "Bowl first"
        toss_key = "bowl"
    elif pitch_type == "batting" and bat_rate is not None and bowl_rate is not None and bat_rate > bowl_rate:
        toss = "Slight preference: bat first"
        toss_key = "bat"
    elif pitch_type == "bowling" and bowl_rate is not None and bat_rate is not None and bowl_rate > bat_rate:
        toss = "Slight preference: bowl first"
        toss_key = "bowl"
    else:
        toss = "No strong historical toss preference"
        toss_key = None

    # Sample-size confidence for ground/toss conclusions.
    if proxy_format or total is None or total < 15:
        confidence = "low"
    elif total < 40:
        confidence = "low" if (bat_rate is None or abs(bat_rate - 0.5) < 0.10) else "medium"
    else:
        confidence = "medium" if (bat_rate is None or abs(bat_rate - 0.5) < 0.08) else "high"

    # Recommend a batting-first or chase approach only when the format-specific
    # sample has at least 15 matches and one innings outcome wins >=58%.
    # Otherwise the venue record is not strong enough to preselect either.
    recommended_innings_mode = (
        "first_innings" if total is not None and total >= 15 and bat_rate is not None and bat_rate >= 0.58
        else "chasing" if total is not None and total >= 15 and bowl_rate is not None and bowl_rate >= 0.58
        else "manual"
    )
    recommended_innings_label = {
        "first_innings": "Bat first — venue history favours teams batting first",
        "chasing": "Chase — venue history favours teams bowling first",
        "manual": "No strong first-innings / chasing edge from this sample",
    }[recommended_innings_mode]

    # Optional role-specific venue profile inputs, when a provider/admin has supplied them.
    pace_friendly = _safe_float(stats.get("pace_assistance"))
    spin_friendly = _safe_float(stats.get("spin_assistance"))
    batting_friendly = _safe_float(stats.get("batting_friendly"))
    if pace_friendly is not None:
        reasons.append(f"Imported pace-assistance index: {pace_friendly:g}.")
    if spin_friendly is not None:
        reasons.append(f"Imported spin-assistance index: {spin_friendly:g}.")
    if batting_friendly is not None:
        reasons.append(f"Imported batting-suitability index: {batting_friendly:g}.")

    return {
        "format": fmt,
        "available": True,
        "stats_source_format": proxy_format or fmt,
        "is_format_proxy": bool(proxy_format),
        "pitch_type": pitch_type,
        "recommended_innings_mode": recommended_innings_mode,
        "recommended_innings_label": recommended_innings_label,
        "pitch_recommendation": pitch,
        "toss_recommendation": toss,
        "toss_decision": toss_key,
        "confidence": confidence,
        "pace_friendly": pace_friendly,
        "spin_friendly": spin_friendly,
        "batting_friendly": batting_friendly,
        "confidence_note": "Confidence reflects the available format-specific sample and agreement among venue signals; it is not a match-win probability.",
        "batting_first_win_pct": round(bat_rate * 100, 1) if bat_rate is not None else None,
        "bowling_first_win_pct": round(bowl_rate * 100, 1) if bowl_rate is not None else None,
        "first_innings_average": first_avg,
        "second_innings_average": second_avg,
        "innings_average_gap_pct": round(innings_gap_pct, 1) if innings_gap_pct is not None else None,
        "total_matches": int(total) if total is not None else None,
        "reasons": reasons,
        "stats": stats,
    }


def compare_squad_strength(team_a: str, team_b: str, predictions: list[dict]) -> dict:
    """Compare current player pools by format-matched expected fantasy output, not win odds."""
    result = {}
    for team in (team_a, team_b):
        rows = [
            p for p in predictions
            if p.get("team") == team and p.get("expected_points") is not None
        ]
        result[team] = {
            "players_with_estimates": len(rows),
            "average_expected_fantasy_points": round(
                sum(float(p["expected_points"]) for p in rows) / len(rows), 2
            ) if rows else None,
            "combined_expected_fantasy_points": round(
                sum(float(p["expected_points"]) for p in rows), 2
            ) if rows else None,
            "matches_used_total": sum(int(p.get("matches_used") or 0) for p in rows),
        }
    a = result[team_a]["average_expected_fantasy_points"]
    b = result[team_b]["average_expected_fantasy_points"]
    count_a = result[team_a]["players_with_estimates"]
    count_b = result[team_b]["players_with_estimates"]
    strong_team = None
    edge_pct = None
    confidence = "low"
    note = "Not enough format-matched player history on both sides to name a defensible stronger squad."
    if a is not None and b is not None and count_a >= 5 and count_b >= 5:
        baseline = (a + b) / 2
        edge_pct = ((a - b) / baseline * 100) if baseline else 0
        if edge_pct >= 5:
            strong_team = team_a
        elif edge_pct <= -5:
            strong_team = team_b
        if abs(edge_pct) >= 5:
            confidence = "medium" if min(count_a, count_b) >= 8 and min(result[team_a]["matches_used_total"], result[team_b]["matches_used_total"]) >= 35 else "low"
            note = "Roster-level edge from format-matched, recency-weighted player fantasy estimates. This is not a match-winner probability."
        else:
            note = "The two squads are statistically close on the available player estimates; no strong-team pick is justified."
    return {
        "team_a": result[team_a],
        "team_b": result[team_b],
        "strong_team": strong_team,
        "edge_pct": round(edge_pct, 1) if edge_pct is not None else None,
        "confidence": confidence,
        "basis": "Format-specific recency-weighted expected fantasy points per player",
        "note": note,
    }


def analysis_context_fields(analysis: dict) -> dict:
    pitch_type = analysis.get("pitch_type")
    batting_friendly = {"batting": 0.75, "balanced": 0.5, "bowling": 0.25}.get(pitch_type)
    stats = analysis.get("stats") or {}
    matches = stats.get("total_matches") or 0
    pace_friendly = None
    spin_friendly = None
    # Cricbuzz venue summary pages usually do not expose pace/spin splits.
    return {
        "pitch_type": pitch_type,
        "batting_friendly": batting_friendly,
        "venue_matches": matches,
    }
