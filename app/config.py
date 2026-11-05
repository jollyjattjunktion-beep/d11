import os
from dotenv import load_dotenv

load_dotenv()

APP_ENV = os.getenv("APP_ENV", "development")
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./preet_fantasy.db")
MODEL_VERSION = "baseline-t20-v1"

# These are starter defaults, not a guarantee of the current rules of any contest platform.
# Verify and update this configuration against the contest's official scoring rules.
SCORING = {
    "run": 1, "four_bonus": 1, "six_bonus": 2, "thirty_bonus": 4,
    "half_century_bonus": 8, "century_bonus": 16, "duck_penalty": -2,
    "wicket": 25, "three_wicket_bonus": 4, "four_wicket_bonus": 8,
    "five_wicket_bonus": 12, "maiden_over": 12, "catch": 8,
    "stumping": 12, "run_out": 6, "captain_multiplier": 2.0,
    "vice_captain_multiplier": 1.5,
}
