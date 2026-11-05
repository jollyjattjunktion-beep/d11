from app.scoring import calculate_t20_points

def test_batting_points_starter_config():
    assert calculate_t20_points({"runs":50,"balls":30,"fours":4,"sixes":2}) == 50 + 4 + 4 + 8

def test_wicket_points_starter_config():
    assert calculate_t20_points({"wickets":3}) == 75 + 4
