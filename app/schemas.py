from pydantic import BaseModel, Field
from typing import Literal

Role = Literal["WK", "BAT", "AR", "BOWL"]

class MatchIn(BaseModel):
    id: str
    name: str
    format: str = "T20"
    start_time: str | None = None
    venue: str | None = None
    team_a: str
    team_b: str
    status: str = "upcoming"
    source: str | None = None

class PlayerIdentityIn(BaseModel):
    id: str
    name: str

class PlayerIn(BaseModel):
    id: str
    name: str
    team: str
    role: Role
    credits: float | None = Field(default=None, ge=0, le=20)
    selection_pct: float | None = Field(default=None, ge=0, le=100)
    status: str = "unknown"
    source: str | None = None

class SquadImport(BaseModel):
    players: list[PlayerIn]

class StatsIn(BaseModel):
    match_id: str
    player_id: str
    format: str = "T20"
    fantasy_points: float | None = None
    runs: int = 0
    balls: int = 0
    fours: int = 0
    sixes: int = 0
    wickets: int = 0
    overs: float = 0
    runs_conceded: int = 0
    maidens: int = 0
    catches: int = 0
    stumpings: int = 0
    run_outs: int = 0
    match_date: str | None = None
    source: str | None = None

class StatsImport(BaseModel):
    records: list[StatsIn]

class TeamRules(BaseModel):
    team_size: int = Field(default=11, ge=1, le=11)
    max_from_one_team: int = Field(default=7, ge=1, le=11)
    max_credits: float = Field(default=100, gt=0)
    min_role: dict[str, int] = Field(default_factory=lambda: {"WK": 1, "BAT": 3, "AR": 1, "BOWL": 3})
    max_role: dict[str, int] = Field(default_factory=lambda: {"WK": 4, "BAT": 6, "AR": 4, "BOWL": 6})
    playing_xi_only: bool = False

class TeamRequest(BaseModel):
    strategies: list[Literal["safe", "balanced", "grand_league", "scenario"]] = Field(
        default_factory=lambda: ["safe", "balanced", "grand_league", "scenario"]
    )
    teams_per_strategy: int = Field(default=1, ge=1, le=20)
    rules: TeamRules = Field(default_factory=TeamRules)
    scenario: Literal["neutral", "batting_friendly", "bowling_friendly", "spin_friendly", "pace_friendly"] = "neutral"
