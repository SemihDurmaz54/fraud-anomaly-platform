"""JSON/YAML tabanlı koşul dili (context ve rule engine tarafından ortak kullanılır).

Bir koşul ya bir *karşılaştırma* ya da bir *mantıksal grup*tur:

    {"field": "TransactionAmt", "op": "gt", "value": 500}
    {"all": [ <koşul>, <koşul>, ... ]}      # VE
    {"any": [ <koşul>, ... ]}               # VEYA
    {"not": <koşul>}                        # DEĞİL

Değer olarak başka bir alan da verilebilir: {"field": "a", "op": "gt", "value_field": "b"}.
eval kullanılmaz; yalnızca tanımlı operatörler çalışır (güvenli).
Değerlendirme hem tek kayıt (dict) hem de pandas DataFrame (vektörize, toplu) üzerinde çalışır.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

OPS = {
    "eq": lambda s, v: s == v,
    "ne": lambda s, v: s != v,
    "gt": lambda s, v: s > v,
    "gte": lambda s, v: s >= v,
    "lt": lambda s, v: s < v,
    "lte": lambda s, v: s <= v,
    "between": lambda s, v: (s >= v[0]) & (s <= v[1]),
    "in": lambda s, v: s.isin(v),
    "not_in": lambda s, v: ~s.isin(v),
    "is_null": lambda s, v: s.isna(),
    "not_null": lambda s, v: s.notna(),
    "contains": lambda s, v: s.astype(str).str.contains(str(v), case=False, na=False),
}


class ConditionError(ValueError):
    pass


def validate(cond: dict, path: str = "condition") -> None:
    """Koşulun yapısını kontrol eder; hatalı kuralların sisteme eklenmesini engeller."""
    if not isinstance(cond, dict):
        raise ConditionError(f"{path}: koşul bir sözlük olmalı")
    if "all" in cond or "any" in cond:
        key = "all" if "all" in cond else "any"
        if not isinstance(cond[key], list) or not cond[key]:
            raise ConditionError(f"{path}.{key}: boş olmayan bir liste olmalı")
        for i, c in enumerate(cond[key]):
            validate(c, f"{path}.{key}[{i}]")
    elif "not" in cond:
        validate(cond["not"], f"{path}.not")
    else:
        if "field" not in cond or "op" not in cond:
            raise ConditionError(f"{path}: 'field' ve 'op' zorunlu")
        if cond["op"] not in OPS:
            raise ConditionError(f"{path}: bilinmeyen operatör '{cond['op']}' (geçerli: {sorted(OPS)})")
        if cond["op"] not in ("is_null", "not_null") and "value" not in cond and "value_field" not in cond:
            raise ConditionError(f"{path}: '{cond['op']}' için 'value' veya 'value_field' gerekli")


def fields_of(cond: dict) -> set[str]:
    """Koşulda kullanılan alan adları (explainability'de kanıt olarak raporlanır)."""
    if "all" in cond or "any" in cond:
        return set().union(*(fields_of(c) for c in cond.get("all", cond.get("any"))))
    if "not" in cond:
        return fields_of(cond["not"])
    out = {cond["field"]}
    if "value_field" in cond:
        out.add(cond["value_field"])
    return out


def evaluate(cond: dict, data: pd.DataFrame) -> pd.Series:
    """Koşulu DataFrame üzerinde vektörize değerlendirir → boolean Series.
    Eksik alan veya NaN değer → False (kural tetiklenmez); is_null hariç."""
    if "all" in cond:
        m = pd.Series(True, index=data.index)
        for c in cond["all"]:
            m &= evaluate(c, data)
        return m
    if "any" in cond:
        m = pd.Series(False, index=data.index)
        for c in cond["any"]:
            m |= evaluate(c, data)
        return m
    if "not" in cond:
        return ~evaluate(cond["not"], data)

    field, op = cond["field"], cond["op"]
    s = data[field] if field in data.columns else pd.Series(np.nan, index=data.index)
    if op in ("is_null", "not_null"):
        return OPS[op](s, None).fillna(False).astype(bool)
    v = data[cond["value_field"]] if "value_field" in cond else cond["value"]
    try:
        res = OPS[op](s, v)
    except TypeError:  # tip uyuşmazlığı (ör. string > sayı) → tetiklenmez
        return pd.Series(False, index=data.index)
    return pd.Series(res, index=data.index).fillna(False).astype(bool) & (s.notna() | (op == "ne"))


def evaluate_one(cond: dict, record: dict[str, Any]) -> bool:
    """Tek bir kayıt (dict) için değerlendirme."""
    return bool(evaluate(cond, pd.DataFrame([record])).iloc[0])


def describe(cond: dict) -> str:
    """Koşulun insan tarafından okunabilir hâli (dokümantasyon ve explainability için)."""
    sym = {"eq": "=", "ne": "≠", "gt": ">", "gte": "≥", "lt": "<", "lte": "≤", "in": "∈", "not_in": "∉"}
    if "all" in cond:
        return " VE ".join(f"({describe(c)})" if ("any" in c) else describe(c) for c in cond["all"])
    if "any" in cond:
        return " VEYA ".join(describe(c) for c in cond["any"])
    if "not" in cond:
        return f"DEĞİL({describe(cond['not'])})"
    f, op = cond["field"], cond["op"]
    rhs = cond.get("value_field", cond.get("value"))
    if op == "between":
        return f"{rhs[0]} ≤ {f} ≤ {rhs[1]}"
    if op in ("is_null", "not_null"):
        return f"{f} {'boş' if op == 'is_null' else 'dolu'}"
    if op == "contains":
        return f"{f} '{rhs}' içerir"
    return f"{f} {sym.get(op, op)} {rhs}"
