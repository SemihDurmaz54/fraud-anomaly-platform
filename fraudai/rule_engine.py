"""Configurable Rule Engine (Adım 7).

Kurallar JSON veya YAML dosyasından yüklenir, çalışma anında eklenip çıkarılabilir.
Her kural bir if-then yapısıdır:

    - id: R002
      name: Velocity burst
      priority: 20                 # küçük sayı = yüksek öncelik
      if:   {<koşul, bkz. conditions.py>}
      then: {action: REVIEW, score_delta: 15, reason: "Son 1 saatte {uid_tx_last_1h} işlem"}

Aksiyonlar ve ciddiyet: BLOCK(4) > REVIEW(3) > FLAG(2) > ALLOW(1).
FLAG karar vermez, yalnızca skoru ayarlar. Karar veren aksiyonlar arasındaki çatışma
`settings.conflict_resolution` ile çözülür: "priority" (en yüksek öncelikli kural kazanır) veya
"severity" (en ciddi aksiyon kazanır). Hiçbir karar kuralı tetiklenmezse karar AI skoruna göre verilir.
"""
from __future__ import annotations

import json
import string
from copy import deepcopy
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

from . import conditions as C

SEVERITY = {"BLOCK": 4, "REVIEW": 3, "FLAG": 2, "ALLOW": 1}
DECISIVE = {"BLOCK", "REVIEW", "ALLOW"}
DECISION_LABEL = {"BLOCK": "BLOCK", "REVIEW": "REVIEW", "ALLOW": "APPROVE"}


class _SafeDict(dict):
    def __missing__(self, key):
        return "?"


class _Fmt(string.Formatter):
    def format_field(self, value, spec):
        try:
            return super().format_field(value, spec)
        except (ValueError, TypeError):
            return str(value)


def render(template: str, record: dict) -> str:
    rec = {k: (None if isinstance(v, (float, np.floating)) and np.isnan(v) else v) for k, v in record.items()}
    return _Fmt().vformat(template, (), _SafeDict(rec))


class RuleEngine:
    def __init__(self, config: dict):
        self.settings = {"conflict_resolution": "priority", "score_field": "adjusted_score",
                         "max_total_delta": 30, "review_threshold": 90, **config.get("settings", {})}
        self.rules: list[dict] = []
        for r in config.get("rules", []):
            self.add_rule(r)

    # ------------------------------------------------------------------ yükleme / yönetim
    @classmethod
    def from_file(cls, path: str | Path) -> "RuleEngine":
        text = Path(path).read_text(encoding="utf-8")
        cfg = json.loads(text) if str(path).endswith(".json") else yaml.safe_load(text)
        return cls(cfg)

    @staticmethod
    def validate_rule(rule: dict) -> dict:
        r = deepcopy(rule)
        for k in ("id", "name", "if", "then"):
            if k not in r:
                raise ValueError(f"Kuralda '{k}' alanı zorunlu: {rule}")
        C.validate(r["if"], f"{r['id']}.if")
        act = r["then"].get("action")
        if act not in SEVERITY:
            raise ValueError(f"{r['id']}: geçersiz aksiyon '{act}' (geçerli: {list(SEVERITY)})")
        r.setdefault("priority", 100)
        r.setdefault("enabled", True)
        r["then"].setdefault("score_delta", 0)
        r["then"].setdefault("reason", r["name"])
        return r

    def add_rule(self, rule: dict, replace: bool = True) -> None:
        r = self.validate_rule(rule)
        if any(x["id"] == r["id"] for x in self.rules):
            if not replace:
                raise ValueError(f"{r['id']} zaten var")
            self.remove_rule(r["id"])
        self.rules.append(r)
        self.rules.sort(key=lambda x: (x["priority"], -SEVERITY[x["then"]["action"]]))

    def remove_rule(self, rule_id: str) -> None:
        self.rules = [r for r in self.rules if r["id"] != rule_id]

    def set_enabled(self, rule_id: str, enabled: bool) -> None:
        for r in self.rules:
            if r["id"] == rule_id:
                r["enabled"] = enabled

    @property
    def active_rules(self) -> list[dict]:
        return [r for r in self.rules if r["enabled"]]

    def documentation(self) -> pd.DataFrame:
        return pd.DataFrame([{"öncelik": r["priority"], "id": r["id"], "ad": r["name"],
                              "IF": C.describe(r["if"]), "THEN": r["then"]["action"],
                              "skor_Δ": r["then"]["score_delta"], "etiketler": ", ".join(r.get("tags", []))}
                             for r in self.rules])

    # ------------------------------------------------------------------ toplu değerlendirme
    def evaluate_frame(self, df: pd.DataFrame) -> pd.DataFrame:
        rules = self.active_rules
        n = len(df)
        base = df[self.settings["score_field"]].to_numpy(dtype=float)
        M = np.column_stack([C.evaluate(r["if"], df).to_numpy() for r in rules]) if rules else np.zeros((n, 0), bool)
        deltas = np.array([r["then"]["score_delta"] for r in rules], dtype=float)
        lim = self.settings["max_total_delta"]
        final = np.clip(base + np.clip(M @ deltas, -lim, lim), 0, 100)

        decision = np.full(n, "", dtype=object)
        decided_by = np.full(n, "", dtype=object)
        sev_now = np.zeros(n)
        for j, r in enumerate(rules):  # öncelik sırasıyla
            act = r["then"]["action"]
            if act not in DECISIVE:
                continue
            if self.settings["conflict_resolution"] == "priority":
                m = M[:, j] & (decision == "")
            else:  # severity
                m = M[:, j] & (SEVERITY[act] > sev_now)
                sev_now[m] = SEVERITY[act]
            decision[m] = DECISION_LABEL[act]
            decided_by[m] = r["id"]
        ai = decision == ""
        decision[ai] = np.where(final[ai] >= self.settings["review_threshold"], "REVIEW", "APPROVE")
        decided_by[ai] = "AI_SCORE"
        ids = np.array([r["id"] for r in rules])
        return pd.DataFrame({"final_risk_score": final.round(2), "decision": decision, "decided_by": decided_by,
                             "fired_rules": [",".join(ids[row]) for row in M], "n_fired": M.sum(axis=1)},
                            index=df.index)

    # ------------------------------------------------------------------ tek kayıt + explainability
    def evaluate(self, record: dict[str, Any], ai_reasons: dict | None = None) -> dict:
        data = pd.DataFrame([record])
        base = float(record.get(self.settings["score_field"], 0) or 0)
        fired, not_fired = [], []
        for r in self.active_rules:
            if bool(C.evaluate(r["if"], data).iloc[0]):
                fired.append({
                    "id": r["id"], "name": r["name"], "priority": r["priority"],
                    "action": r["then"]["action"], "score_delta": r["then"]["score_delta"],
                    "message": render(r["then"]["reason"], record),
                    "condition": C.describe(r["if"]),
                    "evidence": {f: _py(record.get(f)) for f in sorted(C.fields_of(r["if"]))},
                    "tags": r.get("tags", []),
                })
            else:
                not_fired.append(r["id"])
        lim = self.settings["max_total_delta"]
        delta = float(np.clip(sum(f["score_delta"] for f in fired), -lim, lim))
        final = float(np.clip(base + delta, 0, 100))

        decisive = [f for f in fired if f["action"] in DECISIVE]
        if decisive:
            if self.settings["conflict_resolution"] == "priority":
                winner = decisive[0]
            else:
                winner = max(decisive, key=lambda f: (SEVERITY[f["action"]], -f["priority"]))
            decision, decided_by = DECISION_LABEL[winner["action"]], winner["id"]
            rationale = f"{winner['id']} ({winner['name']}) kuralı karar verdi: {winner['message']}"
        else:
            winner = None
            decision = "REVIEW" if final >= self.settings["review_threshold"] else "APPROVE"
            decided_by = "AI_SCORE"
            rationale = (f"Karar kuralı tetiklenmedi; nihai risk skoru {final:.1f}, eşik "
                         f"{self.settings['review_threshold']} → {decision}")
        conflicts = [{"overridden": f["id"], "overridden_action": f["action"], "by": winner["id"],
                      "by_action": winner["action"],
                      "explanation": f"{f['id']} ({f['action']}, öncelik {f['priority']}) → {winner['id']} "
                                     f"({winner['action']}, öncelik {winner['priority']}) tarafından geçersiz kılındı "
                                     f"[strateji: {self.settings['conflict_resolution']}]"}
                     for f in decisive if winner and f["id"] != winner["id"] and f["action"] != winner["action"]]
        return {
            "decision": decision, "decided_by": decided_by, "rationale": rationale,
            "base_score": round(base, 2), "rule_score_delta": delta, "final_risk_score": round(final, 2),
            "fired_rules": fired, "conflicts": conflicts, "n_rules_evaluated": len(self.active_rules),
            "not_fired": not_fired, "ai_layer_reasons": ai_reasons or {},
        }


def _py(v):
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating, float)):
        return None if np.isnan(v) else round(float(v), 4)
    return v
