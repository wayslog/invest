"""Frozen observation plans; cash operations are distinct from strategy validation."""

import re
import tomllib
from dataclasses import dataclass
from datetime import date

from invest.strategies import Candidate


@dataclass(frozen=True)
class Observation:
    name: str
    mode: str
    symbols: tuple[str, ...]
    candidate: str
    start_session: date
    sessions: int
    minimum_fills: int
    max_capture_age_minutes: int

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", self.name):
            raise ValueError("Invalid observation name")
        if self.mode not in {"drill", "cash_observation", "qualified_strategy", "shadow_research"}:
            raise ValueError("Unknown observation mode")
        if len(self.symbols) < 2 or len(set(self.symbols)) != len(self.symbols):
            raise ValueError("Observation requires at least two distinct symbols")
        if type(self.start_session) is not date:
            raise ValueError("start_session must be a TOML date")
        for value in [self.sessions, self.max_capture_age_minutes]:
            if type(value) is not int or value < 1:
                raise ValueError("Observation duration and capture age must be positive integers")
        if type(self.minimum_fills) is not int or self.minimum_fills < 0:
            raise ValueError("minimum_fills must be a nonnegative integer")
        signal = self.signal
        if self.mode == "cash_observation" and (signal.kind != "cash" or self.minimum_fills):
            raise ValueError("Cash observation must use cash and minimum_fills=0")
        if self.mode in {"qualified_strategy", "shadow_research"} and not signal.is_strategy:
            raise ValueError("Qualified observation requires a strategy candidate")

    @property
    def signal(self) -> Candidate:
        if self.candidate == "cash":
            return Candidate("cash")
        match = re.fullmatch(r"(trend|rotation)-([0-9]+)", self.candidate)
        if not match:
            raise ValueError("Use cash, trend-N or rotation-N")
        return Candidate(match[1], int(match[2]))


def parse_observation(body: bytes) -> Observation:
    values = tomllib.loads(body.decode())
    if not isinstance(values.get("symbols"), list):
        raise ValueError("Observation symbols must be an array")
    values["symbols"] = tuple(values["symbols"])
    try:
        return Observation(**values)
    except TypeError as exc:
        raise ValueError("Invalid observation fields") from exc
