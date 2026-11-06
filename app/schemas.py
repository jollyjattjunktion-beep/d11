from pydantic import BaseModel, Field, model_validator
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
    player_name: str | None = None
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

class MatchIntelligenceIn(BaseModel):
    venue: str | None = Field(default=None, max_length=200)
    pitch_type: str | None = None
    pitch_notes: str | None = None
    batting_friendly: float | None = Field(default=None, ge=0, le=1)
    pace_friendly: float | None = Field(default=None, ge=0, le=1)
    spin_friendly: float | None = Field(default=None, ge=0, le=1)
    average_first_innings: float | None = Field(default=None, ge=0)
    venue_matches: int = Field(default=0, ge=0)
    weather_summary: str | None = None
    rain_probability: float | None = Field(default=None, ge=0, le=100)
    humidity: float | None = Field(default=None, ge=0, le=100)
    wind_kmh: float | None = Field(default=None, ge=0)
    dew_likely: bool | None = None
    h2h_summary: str | None = None
    team_a_recent_form: str | None = None
    team_b_recent_form: str | None = None
    source_urls: list[str] = Field(default_factory=list)
    strong_team: str | None = None
    toss_completed: bool | None = None
    toss_winner: str | None = None
    toss_decision: Literal["bat", "bowl"] | None = None
    fixed_player_ids: list[str] = Field(default_factory=list, max_length=5)
    lineup_confirmed: bool | None = None
    lineup_selected_player_ids: list[str] = Field(default_factory=list, max_length=30)

class SquadPlayerEdit(BaseModel):
    credits: float | None = Field(default=None, ge=0, le=20)
    selection_pct: float | None = Field(default=None, ge=0, le=100)
    status: str | None = None
    role: Role | None = None
    team: str | None = None

class TeamRules(BaseModel):
    team_size: int = Field(default=11, ge=1, le=11)
    max_from_one_team: int = Field(default=7, ge=1, le=11)
    max_credits: float = Field(default=100, gt=0)
    min_role: dict[str, int] = Field(default_factory=lambda: {"WK": 1, "BAT": 3, "AR": 1, "BOWL": 3})
    max_role: dict[str, int] = Field(default_factory=lambda: {"WK": 4, "BAT": 6, "AR": 4, "BOWL": 6})
    playing_xi_only: bool = False
    team_a_count: int | None = Field(default=None, ge=0, le=11)

    @model_validator(mode="after")
    def validate_role_bounds(self):
        for role, minimum in self.min_role.items():
            if minimum > self.max_role.get(role, self.team_size):
                raise ValueError(f"Minimum {role} count cannot exceed its maximum")
        if sum(self.min_role.values()) > self.team_size:
            raise ValueError("Minimum role counts exceed team size")
        if self.team_a_count is not None and self.team_a_count > self.team_size:
            raise ValueError("team_a_count cannot exceed team_size")
        return self

class TeamRequest(BaseModel):
    strategies: list[Literal["safe", "balanced", "grand_league", "scenario"]] = Field(
        default_factory=lambda: ["balanced"]
    )
    teams_per_strategy: int = Field(default=1, ge=1, le=20)
    rules: TeamRules = Field(default_factory=TeamRules)
    scenario: Literal["neutral", "batting_friendly", "bowling_friendly", "spin_friendly", "pace_friendly"] = "neutral"
    locked_player_ids: list[str] = Field(default_factory=list)
    excluded_player_ids: list[str] = Field(default_factory=list)
    captain_pool: list[str] = Field(default_factory=list)
    vice_captain_pool: list[str] = Field(default_factory=list)
    manual_captain_id: str | None = None
    manual_vice_captain_id: str | None = None
    team_mode: Literal["manual", "automatic"] = "automatic"
    generation_mode: Literal["both", "ai_prediction", "provisional"] = "both"

class AI11ImportRequest(BaseModel):
    analysis_url: str
    fantasy_url: str | None = None

class HistoricalBatchImport(BaseModel):
    records: list[StatsIn] = Field(min_length=1, max_length=10000)
    source: str = "external_scorecards"


class ManualCreditUpdate(BaseModel):
    player_id: str = Field(min_length=1, max_length=120)
    credits: float = Field(gt=0, le=20)
    source_label: str = Field(default="Admin verified manual entry", min_length=2, max_length=120)
    source_url: str | None = Field(default=None, max_length=1000)


class PlayingXIUpdate(BaseModel):
    selected_player_ids: list[str] = Field(default_factory=list, max_length=30)
    confirmed: bool = True


class VenueUrlImportRequest(BaseModel):
    url: str = Field(min_length=12, max_length=1000)


class CricbuzzVenueImportRequest(BaseModel):
    url: str = Field(min_length=20, max_length=1200)


class CricbuzzSeriesImportRequest(BaseModel):
    url: str = Field(min_length=20, max_length=1200)
