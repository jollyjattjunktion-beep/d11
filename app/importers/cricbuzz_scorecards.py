"""Manual, bounded Cricbuzz series scorecard importer for D11.

Only public HTTPS Cricbuzz pages are fetched. Match/player linking is conservative:
the caller selects an existing D11 match and every scorecard player must match an
existing squad member by an unambiguous normalized name. No match/player is created.
"""
import re
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

HOSTS={"cricbuzz.com","www.cricbuzz.com","m.cricbuzz.com"}
HEADERS={"User-Agent":"Mozilla/5.0 (compatible; D11ScorecardTest/1.0)","Accept":"text/html,application/xhtml+xml"}
MAX_BYTES=5_000_000
SERIES=re.compile(r"^/cricket-series/(\d+)/[^/]+/matches/?$")
SCORECARD=re.compile(r"^/live-cricket-scorecard/(\d+)/[^/]+/?$")


def _validate(url, pattern):
    p=urlparse(url)
    if p.scheme!="https" or p.hostname not in HOSTS or p.username or p.password or p.port not in (None,443):
        raise ValueError("Only public HTTPS Cricbuzz URLs are allowed.")
    if not pattern.fullmatch(p.path):
        raise ValueError("URL is not a supported Cricbuzz series Matches or scorecard page.")
    return p


def validate_series_url(url):
    _validate(url,SERIES)
    return url


def validate_scorecard_url(url):
    _validate(url,SCORECARD)
    return url


def _fetch(url, validator):
    validator(url)
    with httpx.Client(timeout=25,follow_redirects=False,headers=HEADERS,trust_env=False) as client:
        response=client.get(url)
        if response.is_redirect:
            target=str(httpx.URL(url).join(response.headers.get("location","")))
            validator(target)
            response=client.get(target)
        response.raise_for_status()
        if len(response.content)>MAX_BYTES:
            raise ValueError("Cricbuzz page exceeds the 5 MB limit.")
        if "html" not in response.headers.get("content-type","").lower() and not response.text.lstrip().lower().startswith(("<!doctype html","<html")):
            raise ValueError("Cricbuzz did not return HTML.")
        return response.text


def fetch_series(url):
    return _fetch(url,validate_series_url)


def fetch_scorecard(url):
    return _fetch(url,validate_scorecard_url)


def parse_series_scorecards(html,url):
    validate_series_url(url)
    soup=BeautifulSoup(html,"html.parser")
    found={}
    for a in soup.find_all("a",href=True):
        href=a["href"]
        path=urlparse(href).path
        if SCORECARD.fullmatch(path):
            full=urljoin(url,href)
            if urlparse(full).hostname in HOSTS:
                found[full.split("?")[0]]=True
    if not found:
        raise ValueError("No public Cricbuzz scorecard links found on this series page.")
    return list(found)[:60]


def _norm(value):
    return re.sub(r"[^a-z0-9]+","",str(value or "").casefold())


def _int(value):
    m=re.search(r"-?\d+",str(value or "").replace(",",""))
    return int(m.group()) if m else 0


def _float(value):
    m=re.search(r"\d+(?:\.\d+)?",str(value or ""))
    return float(m.group()) if m else 0.0


def parse_scorecard(html,url):
    validate_scorecard_url(url)
    soup=BeautifulSoup(html,"html.parser")
    title=soup.title.get_text(" ",strip=True) if soup.title else ""
    text=re.sub(r"\s+"," ",soup.get_text(" ",strip=True))
    fmt="T20" if re.search(r"\bT20|Twenty20|WBBL|WPL|IPL|BBL\b",title+" "+text[:2000],re.I) else "ODI" if re.search(r"\bODI|One Day\b",title+" "+text[:2000],re.I) else "TEST" if re.search(r"\bTest\b",title+" "+text[:2000],re.I) else "UNKNOWN"
    records={}
    for table in soup.find_all("table"):
        rows=[]
        for tr in table.find_all("tr"):
            cells=[c.get_text(" ",strip=True) for c in tr.find_all(["th","td"])]
            if cells: rows.append(cells)
        if len(rows)<2: continue
        headers=[re.sub(r"[^a-z0-9]+","",x.casefold()) for x in rows[0]]
        is_bat=any(x in headers for x in ("r","runs")) and any(x in headers for x in ("b","balls")) and any(x in headers for x in ("4s","fours"))
        is_bowl=any(x in headers for x in ("o","overs")) and any(x in headers for x in ("w","wkts","wickets")) and any(x in headers for x in ("r","runs"))
        if not (is_bat or is_bowl): continue
        for row in rows[1:]:
            if len(row)!=len(headers) or not row[0].strip(): continue
            name=re.sub(r"\s*\(.*?\)\s*$","",row[0]).strip()
            if not name or name.casefold() in {"extras","total","did not bat","fall of wickets"}: continue
            rec=records.setdefault(_norm(name),{"name":name,"runs":0,"balls":0,"fours":0,"sixes":0,"wickets":0,"overs":0.0,"runs_conceded":0,"maidens":0,"catches":0,"stumpings":0,"run_outs":0})
            values=dict(zip(headers,row))
            if is_bat:
                rec.update(runs=_int(values.get("r",values.get("runs"))),balls=_int(values.get("b",values.get("balls"))),fours=_int(values.get("4s",values.get("fours"))),sixes=_int(values.get("6s",values.get("sixes"))))
            if is_bowl:
                rec.update(overs=_float(values.get("o",values.get("overs"))),maidens=_int(values.get("m",values.get("maidens"))),runs_conceded=_int(values.get("r",values.get("runs"))),wickets=_int(values.get("w",values.get("wkts",values.get("wickets")))))
    if not records:
        raise ValueError("No recognizable batting or bowling scorecard tables were found.")
    date=re.search(r"\b(20\d{2}-\d{2}-\d{2})\b",text)
    return {"url":url,"title":title[:250],"format":fmt,"match_date":date.group(1) if date else None,"players":list(records.values())}
