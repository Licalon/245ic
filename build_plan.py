#!/usr/bin/env python3
"""Pobiera plan z wme.amw.gdynia.pl (Plansoft), odczytuje tabelę i generuje stronę HTML.
Użycie:  python build_plan.py --out site/index.html            (pobiera z internetu)
         python build_plan.py --src plan.html --out out.html   (z zapisanego pliku)"""
import argparse, datetime as dt, json, re, sys, time, urllib.request
from pathlib import Path
from bs4 import BeautifulSoup

URL = "https://www.wme.amw.gdynia.pl/xml/245IC_.htm"
DAYS = ["pon.", "wt.", "śr.", "czw.", "pt."]
ROMAN = {"I": 1, "II": 2, "III": 3, "IV": 4, "V": 5, "VI": 6, "VII": 7, "VIII": 8, "IX": 9, "X": 10, "XI": 11, "XII": 12}
DATE_RE = re.compile(r"(\d\d) (I|II|III|IV|V|VI|VII|VIII|IX|X|XI|XII)")
norm = lambda td: re.sub(r"\s+", " ", td.get_text(" ", strip=True))

def load(src):
    if re.match(r"https?://", src):
        last = None
        for i in range(3):                                   # 3 próby, bo serwery uczelni bywają kapryśne
            try:
                req = urllib.request.Request(src, headers={"User-Agent": "Mozilla/5.0 plan-builder"})
                raw = urllib.request.urlopen(req, timeout=30).read(); break
            except Exception as e:
                last = e; time.sleep(5 * (i + 1))
        else:
            sys.exit(f"Nie udało się pobrać planu: {last}")
    else:
        raw = Path(src).read_bytes()
    for enc in ("utf-8", "cp1250"):
        try: return raw.decode(enc)
        except UnicodeDecodeError: pass
    return raw.decode("utf-8", "replace")

def span(td, name):
    try: return max(1, int(td.get(name, 1)))
    except (TypeError, ValueError): return 1

def grid(soup):
    tables = [t for t in soup.find_all("table") if not t.find_parent("table")]
    table = max(tables, key=lambda t: len(t.find_all("td")), default=None)
    if table is None: sys.exit("Na stronie nie ma tabeli z planem.")
    occ, cells = set(), []
    for r, tr in enumerate(table.find_all("tr")):
        c = 0
        for td in tr.find_all(["td", "th"], recursive=False):
            while (r, c) in occ: c += 1
            rs, cs = span(td, "rowspan"), span(td, "colspan")
            for dr in range(rs):
                for dc in range(cs): occ.add((r + dr, c + dc))
            cells.append(dict(r=r, c=c, rs=rs, cs=cs, td=td)); c += cs
    return table, cells

def pretty(name):  # "dr hab. inż. ŻAK Andrzej" -> "dr hab. inż. Andrzej Żak"
    tok = name.split(); i = next((k for k, t in enumerate(tok) if t.isupper()), None)
    if i is None or i + 1 >= len(tok): return name
    fam = "-".join(p.capitalize() for p in tok[i].split("-"))
    return " ".join(tok[:i] + [" ".join(tok[i + 1:]), fam])

def parts(td):  # kolejne linie komórki; każdy fragment tekstu osobno, białe znaki wewnątrz sklejone
    return [re.sub(r"\s+", " ", s).strip() for s in td.stripped_strings]

def iso_dates(labels, weekday, ref):
    """['28 IX', ...] -> ['2026-09-28', ...]; rok dobrany tak, by pierwszy dzień wypadał we właściwy dzień tygodnia."""
    d0, m0 = int(labels[0][:2]), ROMAN[labels[0][3:]]
    cand = []
    for y in (ref.year - 1, ref.year, ref.year + 1):
        try: x = dt.date(y, m0, d0)
        except ValueError: continue
        if x.weekday() == weekday: cand.append(x)
    if not cand: sys.exit(f"Data {labels[0]} nie pasuje do dnia tygodnia – zmienił się układ strony?")
    cur = min(cand, key=lambda x: abs((x - ref).days)); out = []; pm = m0
    for s in labels:
        d, m = int(s[:2]), ROMAN[s[3:]]
        if m < pm: cur = cur.replace(year=cur.year + 1)
        pm = m
        out.append(cur.replace(month=m, day=d).isoformat())
    return out

def extract(html):
    soup = BeautifulSoup(html, "lxml"); table, cells = grid(soup)
    um = re.search(r"Data aktualizacji:\s*(\d\d)\.(\d\d)\.(\d{4}) (\d\d:\d\d)", html)
    ref = dt.date(int(um.group(3)), int(um.group(2)), int(um.group(1))) if um else dt.date.today()
    upd = f"{um.group(1)}.{um.group(2)}.{um.group(3)} {um.group(4)}" if um else "brak daty"
    head = [re.sub(r"\s+", " ", s).strip() for s in reversed(list(table.find_all_previous(string=True)))
            if type(s).__name__ == "NavigableString" and s.parent.name not in ("script", "style", "title") and s.strip()]
    head = [h for h in head if h][:3]
    group = (head[0] if head else "plan").rstrip("_ ")
    meta = dict(h1=f"Plan zajęć {group}", sub=" · ".join(head[1:]) if len(head) > 1 else "", dates=[None] * 5, nr=[0] * 5, upd=upd)
    events = []
    for dc in cells:
        if dc["c"] == 0 and norm(dc["td"]) in DAYS:
            d, r0, nr = DAYS.index(norm(dc["td"])), dc["r"], dc["rs"] - 1
            hdr = sorted((x for x in cells if x["r"] == r0 and DATE_RE.fullmatch(norm(x["td"]))), key=lambda x: x["c"])
            if not hdr: continue
            wcols = [x["c"] for x in hdr]
            meta["dates"][d] = iso_dates([norm(x["td"]) for x in hdr], d, ref); meta["nr"][d] = nr
            for x in cells:
                if not (r0 < x["r"] <= r0 + nr and x["c"] >= 3 and x["td"].find("b")): continue
                weeks = [i for i, wc in enumerate(wcols) if x["c"] <= wc < x["c"] + x["cs"]]
                if not weeks: continue
                code = norm(x["td"].find("b"))
                p = [q for q in parts(x["td"]) if q]
                p = p[1:] + ["", "", "", ""] if p and p[0] == code else p + ["", "", "", ""]   # pomiń linię z kodem
                who, room, grp = p[0], p[1], p[2]
                if code.startswith("SPOTKANIE"): code, who, room, grp = "SPOTKANIE", "", p[0], p[1]
                events.append([d, weeks[0], weeks[-1], x["r"] - r0, x["r"] - r0 + x["rs"] - 1, code, who, room, grp])
    if not events or any(v is None for v in meta["dates"]) or any(n < 1 for n in meta["nr"]):
        sys.exit("Nie znaleziono zajęć albo dni tygodnia – zmienił się układ strony?")
    lc = max(x["c"] for x in cells) - 1                     # kolumna z legendą po prawej (kody), obok niej nazwy
    def partner(x):
        return next((y for y in cells if y["c"] == x["c"] + 1 and y["r"] <= x["r"] < y["r"] + y["rs"] and norm(y["td"])), None)
    names, subj = {}, {}
    for x in cells:
        if x["c"] != lc: continue
        t, y = norm(x["td"]), partner(x)
        m = re.match(r"^(\S+) (?:lab|wy|pr|ćw|ćw\.|ćw\.) \d+$", t)
        bg = re.search(r"background-color:\s*(#[0-9A-Fa-f]{3,6})", x["td"].get("style", "") or "")
        if m and y: names[m.group(1)] = pretty(norm(y["td"]))
        elif bg and y and re.fullmatch(r"\S+", t): subj[t] = dict(n=norm(y["td"]), c=bg.group(1))
    meta["names"], meta["subj"] = names, subj
    return events, meta

def apply_overrides(events, meta, path):
    """Ręczne korekty z overrides.json: "remove" (odwołane zajęcia danego dnia) i "add" (nowe/przeniesione zajęcia)."""
    if not path.exists(): return events
    ov = json.loads(path.read_text(encoding="utf-8"))
    where = {iso: (d, w) for d, row in enumerate(meta["dates"]) for w, iso in enumerate(row)}
    for r in ov.get("remove", []):
        for iso in r["dates"]:
            if iso not in where: print(f"UWAGA: data {iso} spoza planu – pomijam usunięcie"); continue
            d, w = where[iso]; out = []; hit = False
            for e in events:
                if e[0] == d and e[1] <= w <= e[2] and e[5].startswith(r["code"]) and (not r.get("hours") or e[3] <= r["hours"][1] and e[4] >= r["hours"][0]):
                    hit = True
                    if e[1] <= w - 1: out.append(e[:2] + [w - 1] + e[3:])
                    if w + 1 <= e[2]: out.append([e[0], w + 1] + e[2:])
                else: out.append(e)
            events = out
            if not hit: print(f"UWAGA: {iso} {r['code']} – nie ma takich zajęć w planie (już usunięte przez uczelnię?)")
    for a in ov.get("add", []):
        if a["date"] not in where: print(f"UWAGA: data {a['date']} spoza planu – pomijam dodanie"); continue
        d, w = where[a["date"]]; r1, r2 = a["hours"]
        clash = [e for e in events if e[0] == d and e[1] <= w <= e[2] and e[3] <= r2 and e[4] >= r1]
        if any(e[5] == a["code"] for e in clash):
            print(f"INFO: {a['date']} {a['code']} – uczelnia już ma takie zajęcia w tym terminie, pomijam korektę"); continue
        if clash: print(f"UWAGA: {a['date']} godz. {r1}-{r2} nakłada się na: {[e[5] for e in clash]}")
        events.append([d, w, w, r1, r2, a["code"], a.get("who", ""), a.get("room", ""), a.get("grp", ""), a.get("note", "Zmiana ręczna")])
    return events

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--src", default=URL); ap.add_argument("--out", required=True)
    a = ap.parse_args()
    ev, meta = extract(load(a.src))
    ev = apply_overrides(ev, meta, Path(__file__).parent / "overrides.json")
    t = (Path(__file__).parent / "template.html").read_text(encoding="utf-8")
    dump = lambda o: json.dumps(o, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    t = t.replace("__EVENTS__", dump(ev)).replace("__META__", dump(meta)).replace("__UPD__", meta["upd"])
    Path(a.out).parent.mkdir(parents=True, exist_ok=True); Path(a.out).write_text(t, encoding="utf-8")
    print(f"OK: {len(ev)} zajęć, stan planu: {meta['upd']} -> {a.out}")

if __name__ == "__main__": main()
