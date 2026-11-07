"""Cricsheet T20 JSON parser and compact match-level aggregates.

No delivery-level rows are persisted. Source archives are parsed in memory and
reduced to one player aggregate per match plus innings-phase summaries.
"""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections import defaultdict
from datetime import date
from typing import Any


PHASES = ((1, 6, "powerplay"), (7, 15, "middle"), (16, 20, "death"))


def _slug(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", str(value or ""))
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii").casefold()
    return re.sub(r"[^a-z0-9]+", "-", ascii_value).strip("-") or "unknown"


def _as_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _phase(over_number: int) -> str:
    for start, end, name in PHASES:
        if start <= over_number <= end:
            return name
    return "extra"


def _empty_player(name: str, registry: dict[str, str], team: str) -> dict:
    registry_id = registry.get(name)
    key = "cricsheet:" + registry_id if registry_id else "cricsheet-name:" + _slug(name)
    return {
        "player_key": key, "player_name": name, "team": team,
        "runs": 0, "balls_faced": 0, "fours": 0, "sixes": 0,
        "wickets": 0, "bowling_legal_balls": 0, "runs_conceded": 0,
        "maidens": 0, "catches": 0, "stumpings": 0, "run_outs": 0,
        "batting_innings": 0, "bowling_innings": 0,
        "batting_phases": {p: {"runs": 0, "balls": 0, "fours": 0, "sixes": 0} for p in ("powerplay", "middle", "death")},
        "bowling_phases": {p: {"legal_balls": 0, "runs_conceded": 0, "wickets": 0} for p in ("powerplay", "middle", "death")},
    }


def parse_t20_match(document: dict, source_file: str) -> dict:
    """Validate and aggregate one Cricsheet JSON match; reject non-T20 inputs."""
    if not isinstance(document, dict) or not isinstance(document.get("info"), dict):
        raise ValueError("Match JSON must contain an info object.")
    info = document["info"]
    match_type = str(info.get("match_type") or "").upper()
    overs_limit = _as_int(info.get("overs", 0))
    if match_type != "T20" or (overs_limit and overs_limit != 20):
        raise ValueError("Only T20 matches with a 20-over limit are accepted.")
    teams = info.get("teams") or []
    if len(teams) != 2:
        raise ValueError("T20 match must contain exactly two teams.")
    registry = (info.get("registry") or {}).get("people") or {}
    if not isinstance(registry, dict):
        registry = {}
    players: dict[str, dict] = {}
    for team, names in (info.get("players") or {}).items():
        for name in names or []:
            players[name] = _empty_player(name, registry, team)

    innings_rows = []
    innings_list = document.get("innings") or []
    if not innings_list:
        raise ValueError("Match has no innings data.")
    for innings_index, innings in enumerate(innings_list):
        batting_team = innings.get("team")
        if batting_team not in teams:
            raise ValueError("Innings references a team not listed in match info.")
        innings_runs = 0
        innings_wickets = 0
        innings_balls = 0
        batters_seen: set[str] = set()
        over_runs: dict[int, int] = defaultdict(int)
        over_legal: dict[int, int] = defaultdict(int)
        for over in innings.get("overs") or []:
            over_number = _as_int(over.get("over")) + 1
            phase = _phase(over_number)
            for delivery in over.get("deliveries") or []:
                batter = delivery.get("batter")
                bowler = delivery.get("bowler")
                if not batter or not bowler:
                    raise ValueError("Delivery is missing batter or bowler.")
                if batter not in players:
                    players[batter] = _empty_player(batter, registry, batting_team)
                bowling_team = teams[1] if batting_team == teams[0] else teams[0]
                if bowler not in players:
                    players[bowler] = _empty_player(bowler, registry, bowling_team)
                non_striker = delivery.get("non_striker")
                if non_striker and non_striker not in players:
                    players[non_striker] = _empty_player(non_striker, registry, batting_team)

                runs = delivery.get("runs") or {}
                extras = delivery.get("extras") or {}
                batter_runs = _as_int(runs.get("batter"))
                total_runs = _as_int(runs.get("total"))
                wides = _as_int(extras.get("wides"))
                no_balls = _as_int(extras.get("noballs"))
                byes = _as_int(extras.get("byes"))
                legbyes = _as_int(extras.get("legbyes"))
                penalty = _as_int(extras.get("penalty"))
                legal = wides == 0 and no_balls == 0
                innings_runs += total_runs
                over_runs[over_number] += total_runs
                if legal:
                    innings_balls += 1
                    over_legal[over_number] += 1

                batters_seen.add(batter)
                if non_striker:
                    batters_seen.add(non_striker)
                bat = players[batter]
                bat["runs"] += batter_runs
                bat["fours"] += int(batter_runs == 4)
                bat["sixes"] += int(batter_runs == 6)
                if wides == 0:
                    bat["balls_faced"] += 1
                if phase in bat["batting_phases"]:
                    item = bat["batting_phases"][phase]
                    item["runs"] += batter_runs
                    if wides == 0:
                        item["balls"] += 1
                    item["fours"] += int(batter_runs == 4)
                    item["sixes"] += int(batter_runs == 6)

                bowl = players[bowler]
                bowl["runs_conceded"] += total_runs - byes - legbyes - penalty
                if legal:
                    bowl["bowling_legal_balls"] += 1
                if phase in bowl["bowling_phases"]:
                    item = bowl["bowling_phases"][phase]
                    item["runs_conceded"] += total_runs - byes - legbyes - penalty
                    if legal:
                        item["legal_balls"] += 1

                for wicket in delivery.get("wickets") or []:
                    innings_wickets += 1
                    kind = str(wicket.get("kind") or "").lower().replace(" ", "_")
                    dismissed = wicket.get("player_out")
                    if kind not in {"run_out", "retired_hurt", "obstructing_the_field", "retired_out"}:
                        bowl["wickets"] += 1
                        if phase in bowl["bowling_phases"]:
                            bowl["bowling_phases"][phase]["wickets"] += 1
                    if kind == "run_out":
                        for fielder in wicket.get("fielders") or []:
                            fname = fielder.get("name") if isinstance(fielder, dict) else fielder
                            if fname:
                                if fname not in players:
                                    players[fname] = _empty_player(fname, registry, bowling_team)
                                players[fname]["run_outs"] += 1
                    for fielder in wicket.get("fielders") or []:
                        fname = fielder.get("name") if isinstance(fielder, dict) else fielder
                        if fname not in players:
                            players[fname] = _empty_player(fname, registry, bowling_team)
                        if kind == "caught":
                            players[fname]["catches"] += 1
                        elif kind == "stumped":
                            players[fname]["stumpings"] += 1

        # Count batting/bowling participation once per innings.
        for name in batters_seen:
            players[name]["batting_innings"] += 1
        for name in {d.get("bowler") for over in innings.get("overs") or [] for d in over.get("deliveries") or [] if d.get("bowler")}:
            players[name]["bowling_innings"] += 1
        innings_rows.append({"team": batting_team, "runs": innings_runs, "wickets": innings_wickets,
                             "legal_balls": innings_balls, "overs": len(innings.get("overs") or [])})

    dates = info.get("dates") or []
    match_date = str(dates[0]) if dates else None
    try:
        if match_date:
            date.fromisoformat(match_date)
    except ValueError:
        raise ValueError("Match date must be an ISO date.")
    outcome = info.get("outcome") or {}
    toss = info.get("toss") or {}
    venue = str(info.get("venue") or "").strip()
    if not venue:
        raise ValueError("Match venue is missing.")
    raw = json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return {
        "source_match_id": "cricsheet:" + _slug(source_file.rsplit("/", 1)[-1].rsplit(".", 1)[0]),
        "source_file": source_file,
        "source_sha256": hashlib.sha256(raw).hexdigest(),
        "match_date": match_date,
        "season": str(info.get("season") or ""),
        "competition": str((info.get("event") or {}).get("name") or ""),
        "venue": venue,
        "city": info.get("city"),
        "team_a": teams[0],
        "team_b": teams[1],
        "toss_winner": toss.get("winner"),
        "toss_decision": toss.get("decision"),
        "winner": (outcome.get("by") or {}).get("runs") and outcome.get("winner") or outcome.get("winner"),
        "result_method": "runs" if (outcome.get("by") or {}).get("runs") is not None else "wickets" if (outcome.get("by") or {}).get("wickets") is not None else outcome.get("method"),
        "innings": innings_rows,
        "players": list(players.values()),
    }


def parse_t20_json_bytes(raw: bytes, source_file: str) -> dict:
    try:
        document = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Invalid Cricsheet JSON: " + str(exc)) from exc
    return parse_t20_match(document, source_file)
