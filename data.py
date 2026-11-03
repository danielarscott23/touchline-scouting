"""Source adapters return the same validated player-season table."""

from pathlib import Path
from typing import Protocol
import pandas as pd
from scouting.roles import WEIGHTS

TEXT_COLUMNS = ["player_id", "name", "club", "league", "season", "position"]
NUMBER_COLUMNS = ["age", "minutes", *WEIGHTS]
REQUIRED_COLUMNS = TEXT_COLUMNS + NUMBER_COLUMNS


def validate_players(frame: pd.DataFrame) -> pd.DataFrame:
    """Reject incomplete data rather than silently turning missing values into zero."""
    missing = set(REQUIRED_COLUMNS) - set(frame.columns)
    if missing:
        raise ValueError(f"Missing columns: {', '.join(sorted(missing))}")
    result = frame[REQUIRED_COLUMNS].copy()
    if result.empty:
        raise ValueError("The player table is empty.")
    for column in TEXT_COLUMNS:
        if result[column].isna().any():
            raise ValueError(f"Missing text in {column}.")
        result[column] = result[column].astype(str).str.strip()
        if result[column].eq("").any():
            raise ValueError(f"Blank text in {column}.")
    for column in NUMBER_COLUMNS:
        originally_missing = result[column].isna()
        result[column] = pd.to_numeric(result[column], errors="coerce")
        values = result[column]
        invalid_missing = values.isna() & ~originally_missing if column == "age" else values.isna()
        if invalid_missing.any() or values.isin([float("inf"), -float("inf")]).any():
            raise ValueError(f"{column} must contain finite numbers.")
        if (values < 0).any():
            raise ValueError(f"{column} cannot contain negative numbers.")
    for column in ["age"]:
        if (result[column].dropna() % 1 != 0).any():
            raise ValueError(f"{column} must contain whole numbers.")
    if not (result["age"].isna() | result["age"].between(14, 60)).all():
        raise ValueError("Age must be between 14 and 60.")
    if result.duplicated(["player_id", "season"]).any():
        raise ValueError("Expected one row per player_id and season; aggregate club spells first.")
    return result


class PlayerSource(Protocol):
    """A future provider adapter implements load() and returns the canonical schema."""
    def load(self) -> pd.DataFrame: ...


class CSVPlayerSource:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    def load(self) -> pd.DataFrame:
        frame = pd.read_csv(self.path, dtype={column: str for column in TEXT_COLUMNS})
        return validate_players(frame)
