"""Evaluate regime conditions as of a knowledge instant."""

from __future__ import annotations

import operator
from dataclasses import dataclass
from datetime import datetime

import psycopg

from srm.indicators import age_in_months, current_version, indicator_series, metric

OPS = {">": operator.gt, ">=": operator.ge, "<": operator.lt, "<=": operator.le}


@dataclass(frozen=True)
class ConditionResult:
    regime: str
    key: str
    role: str
    indicator: str
    metric: str
    comparator: str
    threshold: float
    value: float | None
    latest_period: str | None
    reference_period: str | None
    age_months: int | None
    met: bool | None  # None = not evaluable with data known at that instant
    rationale: str


def evaluate(
    conn: psycopg.Connection, at: datetime, model_version_id: int | None = None
) -> list[ConditionResult]:
    mv = model_version_id or current_version(conn)
    rows = conn.execute(
        """SELECT n.code, rc.condition_key, rc.role, i.code, rc.metric, rc.comparator, rc.threshold,
                  rc.rationale
           FROM model.regime_condition rc
           JOIN model.node n ON n.node_id = rc.regime_node
           JOIN model.indicator i ON i.indicator_id = rc.indicator_id
           WHERE rc.model_version_id = %s ORDER BY n.code, rc.role DESC, rc.condition_key""",
        (mv,),
    ).fetchall()
    cache: dict[str, list] = {}
    out = []
    for regime, key, role, ind, met_name, op, thr, rationale in rows:
        if ind not in cache:
            cache[ind] = indicator_series(conn, ind, at, mv)
        m = metric(cache[ind], met_name)
        value, latest, ref = m if m else (None, None, None)
        out.append(
            ConditionResult(
                regime,
                key,
                role,
                ind,
                met_name,
                op,
                float(thr),
                value,
                latest,
                ref,
                age_in_months(latest, at) if latest else None,
                None if value is None else OPS[op](value, float(thr)),
                rationale,
            )
        )
    return out
