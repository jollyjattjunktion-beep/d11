from app.config import SCORING

def calculate_t20_points(s: dict, rules: dict | None = None) -> float:
    """Calculate starter fantasy points. Update SCORING after checking the target contest rules."""
    p = {**SCORING, **(rules or {})}
    runs, balls = int(s.get("runs", 0)), int(s.get("balls", 0))
    wickets = int(s.get("wickets", 0))
    points = runs * p["run"] + int(s.get("fours", 0)) * p["four_bonus"] + int(s.get("sixes", 0)) * p["six_bonus"]
    if runs >= 100: points += p["century_bonus"]
    elif runs >= 50: points += p["half_century_bonus"]
    elif runs >= 30: points += p["thirty_bonus"]
    if runs == 0 and balls > 0: points += p["duck_penalty"]
    points += wickets * p["wicket"]
    if wickets >= 5: points += p["five_wicket_bonus"]
    elif wickets >= 4: points += p["four_wicket_bonus"]
    elif wickets >= 3: points += p["three_wicket_bonus"]
    points += int(s.get("maidens", 0)) * p["maiden_over"]
    points += int(s.get("catches", 0)) * p["catch"]
    points += int(s.get("stumpings", 0)) * p["stumping"]
    points += int(s.get("run_outs", 0)) * p["run_out"]
    return float(points)
