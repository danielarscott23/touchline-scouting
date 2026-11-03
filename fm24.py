"""Read FM24's exported HTML table as data; never execute its HTML/scripts."""
from collections import Counter
from datetime import date, datetime, timezone
from hashlib import sha256
from html.parser import HTMLParser
import json
from pathlib import Path
import re

import pandas as pd

FM_WEIGHTS = {"xa_p90": 0.35, "key_passes_p90": 0.25,
              "progressive_passes_p90": 0.25, "xg_p90": 0.15}
FM_LABELS = {"xa_p90": "Expected assists / 90", "key_passes_p90": "Key passes / 90",
             "progressive_passes_p90": "Progressive passes / 90", "xg_p90": "xG / 90 (includes penalties)"}
METRIC_MAP = {
    "Gls": "goals", "Pens S": "penalty_goals", "Ast": "assists",
    "xG/90": "xg_p90", "Shot/90": "shots_p90", "ShT/90": "shots_on_target_p90",
    "xA/90": "xa_p90", "K Ps/90": "key_passes_p90", "Ch C/90": "chances_created_p90",
    "Ps A/90": "passes_attempted_p90", "Ps C/90": "passes_completed_p90", "Pas %": "pass_completion_pct",
    "Pr passes/90": "progressive_passes_p90", "Drb/90": "dribbles_p90",
    "Crs A/90": "crosses_attempted_p90", "Cr C/90": "crosses_completed_p90",
    "Tck A": "tackles_attempted", "Tck C": "tackles_completed", "Int/90": "interceptions_p90",
    "Blk/90": "blocks_p90", "Clr/90": "clearances_p90", "Aer A/90": "aerial_attempts_p90",
    "Hdrs W/90": "headers_won_p90", "Poss Lost/90": "possession_lost_p90", "Poss Won/90": "possession_won_p90",
}


class FMTableParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tables, self.rows, self.row, self.cell = [], None, None, None

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            if self.rows is not None:
                raise ValueError("Nested tables are not supported.")
            self.rows = []
        elif tag == "tr" and self.rows is not None:
            self.row = []
        elif tag in ("th", "td") and self.row is not None:
            self.cell = []

    def handle_data(self, value):
        if self.cell is not None:
            self.cell.append(value)

    def handle_endtag(self, tag):
        if tag in ("th", "td") and self.cell is not None:
            self.row.append(" ".join("".join(self.cell).split()))
            self.cell = None
        elif tag == "tr" and self.row is not None:
            if self.row:
                self.rows.append(self.row)
            self.row = None
        elif tag == "table" and self.rows is not None:
            self.tables.append(self.rows)
            self.rows = None


def number(value):
    if value.strip() in ("", "-", "–", "—", "N/A"):
        return None
    cleaned = value.replace(",", "").replace("%", "").strip()
    if not re.fullmatch(r"\d+(?:\.\d+)?", cleaned):
        raise ValueError(f"Unexpected numeric cell: {value!r}")
    return float(cleaned)


def appearances(value):
    if value in ("", "-", "–", "—"):
        return None, None, None
    matched = re.fullmatch(r"(\d+)(?:\s*\((\d+)\))?", value)
    if not matched:
        raise ValueError(f"Unexpected appearances: {value!r}")
    starts, subs = int(matched[1]), int(matched[2] or 0)
    return starts, subs, starts + subs


def broad_position(value):
    """Eligibility grouping from listed capabilities, not observed role minutes."""
    groups = set()
    for matched in re.finditer(r"([A-Z]+(?:/[A-Z]+)*)\s*(?:\(([RLC]+)\))?", value):
        roles, sides = matched[1].split("/"), matched[2] or ""
        for role in roles:
            if role == "GK": groups.add("GK")
            elif role == "ST": groups.add("ST")
            elif role == "AM":
                if "C" in sides: groups.add("AM")
                if "L" in sides: groups.add("LW")
                if "R" in sides: groups.add("RW")
            elif role == "M":
                if "C" in sides: groups.add("CM")
                if "L" in sides: groups.add("LW")
                if "R" in sides: groups.add("RW")
            elif role == "DM": groups.add("DM")
            elif role == "WB": groups.add("WB")
            elif role == "D": groups.add("DF")
    priority = ["GK", "AM", "CM", "LW", "RW", "ST", "DM", "WB", "DF"]
    return next((position for position in priority if position in groups), "OTHER")


def parse_fm24(path, season="2023/24"):
    payload = Path(path).read_bytes()
    try:
        html = payload.decode("utf-8-sig")
    except UnicodeDecodeError:
        html = payload.decode("cp1252")
    parser = FMTableParser()
    parser.feed(html)
    candidates = [table for table in parser.tables if table and {"UID", "Name", "Mins", "Apps"}.issubset(table[0])]
    if len(candidates) != 1:
        raise ValueError("Expected exactly one FM24 player table with UID, Name, Mins and Apps.")
    table = candidates[0]
    headers = table[0]
    if len(set(headers)) != len(headers):
        raise ValueError("Duplicate column headings; give each exported column a unique heading.")
    required = {"UID", "Name", "Club", "Division", "Position", "Age", "Mins", "Apps"}
    if not required.issubset(headers):
        raise ValueError(f"Missing identity columns: {sorted(required-set(headers))}")
    rows, blank_rows = [], 0
    for index, values in enumerate(table[1:], 2):
        if all(not value for value in values):
            blank_rows += 1
            continue
        if len(values) != len(headers):
            raise ValueError(f"Row {index} has {len(values)} cells; expected {len(headers)}.")
        raw = dict(zip(headers, values))
        if not raw["UID"].isdigit() or not raw["Name"]:
            raise ValueError(f"Row {index} lacks a valid UID/name.")
        starts, subs, apps = appearances(raw["Apps"])
        name_available = bool(raw["Name"].replace("-", "").strip())
        row = {
            "player_id": raw["UID"], "name": raw["Name"] if name_available else f"Unknown player (FM ID {raw['UID']})",
            "name_raw": raw["Name"], "name_available": name_available, "club": raw["Club"],
            "league": raw["Division"], "season": season,
            "position": broad_position(raw["Position"]), "positions_raw": raw["Position"],
            "age": number(raw["Age"]), "minutes": number(raw["Mins"]),
            "appearances_raw": raw["Apps"], "starts": starts, "sub_appearances": subs,
            "appearances": apps,
        }
        for source, canonical in METRIC_MAP.items():
            if source in raw:
                row[canonical] = number(raw[source])
        # Derive only count-based rates; percentages and existing /90 values stay as supplied.
        for metric in ["goals", "penalty_goals", "assists", "tackles_attempted", "tackles_completed"]:
            if metric in row:
                row[f"{metric}_p90"] = row[metric] / row["minutes"] * 90 if row[metric] is not None and row["minutes"] is not None and row["minutes"] > 0 else None
        rows.append(row)
    frame = pd.DataFrame(rows)
    if frame.empty or frame.duplicated(["player_id", "season"]).any():
        raise ValueError("Empty table or duplicate player-season IDs; cannot safely import.")
    return frame, {
        "source_file": Path(path).name, "source_sha256": sha256(payload).hexdigest(),
        "source_columns": headers, "ignored_columns": [h for h in ("Inf", "Rec", "Information", "Recommendation") if h in headers],
        "blank_footer_rows_skipped": blank_rows,
        "unmapped_columns": [h for h in headers if h not in required and h not in METRIC_MAP and h not in ("Inf", "Rec", "Information", "Recommendation")],
    }


def import_fm24(path, project_root, scope="all competitions", season="2023/24", export_date=None,
                dataset_key="first_draft", dataset_label="First draft"):
    if not re.fullmatch(r"[a-z][a-z0-9_]*", dataset_key):
        raise ValueError("Dataset key must use lowercase letters, numbers and underscores.")
    if export_date is not None:
        date.fromisoformat(export_date)
    frame, metadata = parse_fm24(path, season)
    metrics = list(FM_WEIGHTS)
    missing_metrics = set(metrics) - set(frame.columns)
    if missing_metrics:
        raise ValueError(f"This FM role model needs columns for: {sorted(missing_metrics)}")
    eligible_position = frame["position"].isin(["AM", "CM", "LW", "RW"])
    minutes_ok = frame["minutes"].ge(900)
    complete = frame[metrics].notna().all(axis=1)
    metadata.update({
        "provider": "FM24", "dataset": f"FM24 · {dataset_label} · {season}",
        "season": season, "export_in_game_date": export_date,
        "date_note": "1 January 2024 was the planned export date; actual date is not embedded in this HTML and remains unconfirmed." if export_date is None else "User-supplied date.",
        "competition_scope": scope, "scope_source": "Explicit import setting; user confirmed all-competitions statistics for these draft exports.",
        "imported_at_utc": datetime.now(timezone.utc).isoformat(),
        "player_count": len(frame), "goalkeeper_count": int(frame["position"].eq("GK").sum()),
        "missing_player_names": int((~frame["name_available"]).sum()),
        "division_counts": {str(k): int(v) for k,v in frame["league"].value_counts().items()},
        "missing_by_column": {k: int(v) for k,v in frame.isna().sum().items() if v},
        "eligible_role_players": int((eligible_position & minutes_ok & complete).sum()),
        "role_candidates_with_missing_metrics": int((eligible_position & minutes_ok & ~complete).sum()),
        "role_weights": FM_WEIGHTS,
        "position_note": "Broad role eligibility comes from listed positional capabilities; it does not establish where the recorded minutes were played.",
        "coverage_note": "Exported players only, not complete league populations. Division is the club's league; stats include all competitions. No league-strength adjustment applied.",
        "metric_note": "All /90 fields preserved. Missing dashes remain missing. xG includes penalties; npxG is not estimated. Drb/90 is retained as supplied without assuming attempted/completed meaning.",
    })
    destination = Path(project_root) / "data" / f"fm24_{dataset_key}.csv"
    destination.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(destination, index=False)
    destination.with_suffix(".json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    report = [f"# FM24 {dataset_label}: data audit", "", f"- Players: {len(frame)}", f"- Goalkeepers retained: {metadata['goalkeeper_count']}",
              f"- Complete creative-midfielder candidates with at least 900 minutes: {metadata['eligible_role_players']}",
              f"- Other role candidates excluded for missing model metrics: {metadata['role_candidates_with_missing_metrics']}",
              f"- Scope: **{scope}**.", f"- Season: {season}. In-game export date: {export_date or 'unconfirmed'}.",
              "- Information and Recommendation columns ignored.", "- Dashes preserved as missing, not silently converted to zero.", "", "## Coverage", ""]
    report += [f"- {league}: {count} players" for league, count in metadata["division_counts"].items()]
    report += ["", "This is a selected-player export, not complete coverage of these leagues. Statistics must not be labelled domestic-league-only. No strength adjustment is applied.",
               "", f"**Missing player names: {metadata['missing_player_names']}.** These Name cells contain dash placeholders in the source HTML. Display names use unique FM ID labels; original cells are retained as name_raw. The user has chosen to identify these players by ID, so missing names do not prevent analysis.",
               "", "## Import rules", "", "`20 (5)` → 20 starts + 5 substitute appearances = 25 total appearances. Plain `19` → 19 starts and no substitute appearances. Missing appearances remain missing.",
               "", "Existing /90 fields and percentages are unchanged. Count totals for goals, penalties, assists and tackles receive additional per-90 columns only when minutes are positive. Missing minutes do not become zero.",
               "", "Names retain the exported nationality suffix to avoid guessing where names end. Stable UIDs identify players. Original position strings are retained; broad scoring eligibility uses listed capabilities rather than observed position-specific minutes.",
               "", "## Provisional performance model", "", "xA/90 35%; key passes/90 25%; progressive passes/90 25%; xG/90 15%. These are design choices for testing, not validated recruitment weights. xA and key passes overlap. xG includes penalties. No attributes, current ability or potential ability are used.",
               "", "Missing model metrics exclude a player from scoring; they remain in the full imported table. The score describes this exported reference group only. Small and selective coverage limits cross-league comparisons.",
               "", "## Missing values", ""]
    report += [f"- {field}: {count}" for field, count in metadata["missing_by_column"].items()]
    report_path = Path(project_root) / "docs" / f"fm24_{dataset_key}_audit.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(report)+"\n", encoding="utf-8")
    return destination, metadata
