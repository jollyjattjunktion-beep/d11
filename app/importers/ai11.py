import json
import re
from urllib.parse import urlparse
import httpx
from bs4 import BeautifulSoup

ALLOWED_HOSTS = {"ai11.in", "www.ai11.in"}
HEADERS = {"User-Agent":"PreetFantasyAI/0.3 (+match analytics; contact admin)"}

def validate_ai11_url(value: str) -> str:
    parsed=urlparse(value)
    if parsed.scheme != "https" or parsed.hostname not in ALLOWED_HOSTS or parsed.username or parsed.password:
        raise ValueError("Only HTTPS URLs on www.ai11.in or ai11.in are accepted.")
    if parsed.port not in (None,443):
        raise ValueError("Non-standard URL ports are not allowed.")
    return value

def fetch_page(url: str) -> str:
    validate_ai11_url(url)
    with httpx.Client(timeout=20, follow_redirects=False, headers=HEADERS, trust_env=False) as client:
        response=client.get(url)
        if response.is_redirect:
            location=response.headers.get("location","")
            validate_ai11_url(str(httpx.URL(url).join(location)))
            response=client.get(str(httpx.URL(url).join(location)))
        response.raise_for_status()
        if len(response.content)>5_000_000:
            raise ValueError("AI11 page is larger than the 5 MB import limit.")
        return response.text

def _number(value):
    value=(value or "").strip().replace("%","").replace(",","")
    if not value or value in {"-","—","N/A"}: return None
    try: return float(value)
    except ValueError: return None

def _role(value):
    v=(value or "").strip().upper()
    if v in {"WK","BAT","AR","ALL","BOWL"}:
        return "AR" if v=="ALL" else v
    return None

def _player_id(name):
    return re.sub(r"[^a-z0-9]+","-",name.lower()).strip("-")[:110]

def parse_analysis(html: str):
    soup=BeautifulSoup(html,"html.parser")
    title=soup.title.get_text(" ",strip=True) if soup.title else "AI11 match"
    text=soup.get_text(" ",strip=True)
    fmt="TEST" if re.search(r"\btest\b",title+" "+text[:500],re.I) else "T20" if re.search(r"\bT20\b",title+" "+text[:500],re.I) else "ODI"
    venue=None
    m=re.search(r"(?:Pitch Report:\s*[^ ]+\s*)?([A-Z][A-Za-z .'-]+ Stadium)",text)
    if m: venue=m.group(1).strip()
    # Team names are read from page's team labels / title, with short-code fallback.
    teams=[]
    for node in soup.select("img[alt]"):
        alt=node.get("alt","").strip()
        if alt and alt.lower() not in {"image","logo"} and alt not in teams:
            teams.append(alt)
    if len(teams)<2:
        m=re.search(r"([A-Za-z ]+)\s+vs\s+([A-Za-z ]+)",title,re.I)
        if m: teams=[m.group(1).strip(),m.group(2).strip()]
    team_a,team_b=(teams[0],teams[1]) if len(teams)>=2 else ("TEAM_A","TEAM_B")
    match_name=re.sub(r"\s*\|\s*AI11.*$","",title).strip()
    match_id=_player_id(match_name) or "ai11-match"
    players=[]
    profiles=[]
    # Find the detailed player table by its header row; map columns by header labels.
    for table in soup.find_all("table"):
        rows=table.find_all("tr")
        if len(rows)<2: continue
        header=[c.get_text(" ",strip=True).lower() for c in rows[0].find_all(["th","td"])]
        if not any(x in header for x in ("name","player")) or not any("s%" in x for x in header):
            continue
        for row in rows[1:]:
            cells=[c.get_text(" ",strip=True) for c in row.find_all(["td","th"])]
            if len(cells)<10: continue
            name=cells[0].strip()
            if not name or name.lower() in {"name","player"}: continue
            # AI11's published detailed table uses: Name, team, role, lineup,
            # matches, batting..., bowling..., ... P, S%, C, VC.
            role=_role(cells[2] if len(cells)>2 else "")
            if not role: continue
            team=cells[1].strip() if cells[1].strip() else "UNKNOWN"
            selection=_number(cells[-3] if len(cells)>=3 else None)
            captain_pct=_number(cells[-2] if len(cells)>=2 else None)
            vice_pct=_number(cells[-1] if cells else None)
            lineup=(cells[3].strip().lower() if len(cells)>3 else "")
            status="confirmed" if "✓" in lineup or "confirmed" in lineup else "unknown"
            pid=_player_id(name)
            players.append({"id":pid,"name":name,"team":team,"role":role,
                            "credits":None,"selection_pct":selection,"status":status,
                            "source":"AI11"})
            profiles.append({"player_id":pid,"player_name":name,"team":team,"role":role,
                "format":fmt,"ai11_captain_pct":captain_pct,"ai11_vice_captain_pct":vice_pct,
                "ai11_selection_pct":selection,"ai11_row":cells,"source":"AI11"})
    intelligence={}
    def find_num(pattern):
        match=re.search(pattern,text,re.I)
        return _number(match.group(1)) if match else None
    intelligence["average_first_innings"]=find_num(r"average first[- ]innings score[^0-9]{0,50}(\d{2,3})")
    intelligence["rain_probability"]=find_num(r"Chance of rain\s*(\d+(?:\.\d+)?)\s*%?")
    intelligence["humidity"]=find_num(r"Humidity\s*(\d+(?:\.\d+)?)\s*%?")
    intelligence["wind_kmh"]=find_num(r"Wind\s*(\d+(?:\.\d+)?)\s*km/h")
    if venue: intelligence["venue_name"]=venue
    pitch_match=re.search(r"pitch (?:favou?rs?|is) ([^.]+)",text,re.I)
    if pitch_match: intelligence["pitch_notes"]=pitch_match.group(0).strip()
    form_match=re.search(r"Recent Form(.*?)(?:Head to Head|Pitch Report)",text,re.I)
    if form_match: intelligence["recent_form_source_text"]=form_match.group(1).strip()[:500]
    h2h_match=re.search(r"Head to Head \(last 5\)(.*?)(?:Pitch Report|Weather)",text,re.I)
    if h2h_match: intelligence["h2h_source_text"]=h2h_match.group(1).strip()[:500]
    weather_match=re.search(r"Weather:.*?(?:Dew is likely[^.]*\.)?",text,re.I)
    if weather_match: intelligence["weather_summary"]=weather_match.group(0)[:500]
    return {"title":match_name,"format":fmt,"team_a":team_a,"team_b":team_b,
            "venue":venue,"players":players,"profiles":profiles,
            "intelligence":intelligence,"player_count":len(players)}

def parse_fantasy(html: str):
    soup=BeautifulSoup(html,"html.parser")
    text=soup.get_text(" ",strip=True)
    # Credit values are often rendered client-side; only extract explicitly labelled
    # player-credit pairs. Never infer a credit value from role or selection.
    credits={}
    for node in soup.select("[data-credit], [data-credits]"):
        name=node.get("data-player-name") or node.get("data-name")
        value=_number(node.get("data-credit") or node.get("data-credits"))
        if name and value is not None: credits[_player_id(name)]=value
    for script in soup.find_all("script"):
        raw=script.string or script.get_text()
        if not raw or len(raw)>2_000_000: continue
        for match in re.finditer(r'"(?:name|playerName)"\s*:\s*"([^"]+)"[^{}]{0,500}?"(?:credits|credit)\s*:\s*([0-9]+(?:\.[0-9]+)?)',raw,re.I):
            credits[_player_id(match.group(1))]=float(match.group(2))
    return {"credits":credits,"credits_found":len(credits),
            "dynamic_content_may_require_browser":len(credits)==0}
