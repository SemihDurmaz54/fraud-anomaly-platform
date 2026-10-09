"""Online (tek işlem) anomali skorlama servisi.

Notebook'taki toplu (batch) skorlama mantığının (Adım 3–5) gerçek zamanlı karşılığıdır.
Notebook'ta üretilen iki artefakt kullanılır:

* ``scoring_bundle.joblib``: modeller (Isolation Forest, PCA, ölçekleyiciler), kolon istatistikleri,
  frekans tabloları, katman ağırlıkları ve ECDF referans dağılımları (rank normalizasyonu için).
* ``entity_state.joblib``: kullanıcı (uid), cihaz ve kart bazında geçmiş durum
  (işlem sayısı, tutar toplamları, son işlem zamanları, görülen cihaz/e-postalar).

Skorlanan her işlem durumu günceller (``update=True``); böylece velocity ve "yeni cihaz" gibi
sinyaller akış (stream) hâlinde çalışır.

Batch ile farklar (bilinçli yaklaşıklıklar):
* ``segment_volume_spike`` bileşeni online modda hesaplanmaz (0 kabul edilir).
* Frekans tabloları ve cihaz-paylaşım sayıları eğitim verisinden gelir, yeni işlemlerle güncellenir.
"""
from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field
from typing import Any

import joblib
import numpy as np
import pandas as pd

LAYERS = ("column", "multivariate", "entity", "temporal")


def _nan(v) -> bool:
    if v is None or v is pd.NA or v is pd.NaT:
        return True
    return isinstance(v, (float, np.floating)) and math.isnan(v)


def _f(v, default=np.nan) -> float:
    try:
        return default if _nan(v) else float(v)
    except (TypeError, ValueError):
        return default


def ecdf(ref: np.ndarray, v: float) -> float:
    """Sıralı referans dağılımında yüzdelik sıra (ortalama rank, batch'teki rank(pct=True) karşılığı)."""
    lo, hi = np.searchsorted(ref, v, "left"), np.searchsorted(ref, v, "right")
    return float((lo + hi) / 2 / len(ref))


def tail(ref_pos: np.ndarray, v: float) -> float:
    """Batch `tail_score` karşılığı: 0 = olağan; pozitif değerlerin yüzdelik sırası."""
    v = _f(v, 0.0)
    return 0.0 if v <= 0 else ecdf(ref_pos, v)


def uid_key(card1, addr1, d1, day) -> str:
    d1n = "nan" if _nan(d1) else str(float(day - float(d1)))
    return f"{_f(card1)}|{_f(addr1)}|{d1n}"


def device_key(rec: dict) -> str | None:
    if _nan(rec.get("DeviceInfo")) and _nan(rec.get("id_31")):
        return None
    return "|".join("nan" if _nan(rec.get(c)) else str(rec.get(c)) for c in ("DeviceInfo", "id_30", "id_31", "id_33"))


@dataclass
class UidState:
    cnt: int = 0
    s: float = 0.0
    sq: float = 0.0
    first_ts: float = np.nan
    last_ts: float = np.nan
    recent: deque = field(default_factory=lambda: deque(maxlen=2000))
    devices: set = field(default_factory=set)
    emails: set = field(default_factory=set)
    sin_sum: float = 0.0
    cos_sum: float = 0.0


class OnlineScorer:
    def __init__(self, bundle: dict, state: dict):
        self.b = bundle
        self.uids: dict[str, UidState] = state["uids"]
        self.dev_uids: dict[str, set] = state["device_uids"]
        self.card1_recent: dict[float, deque] = state["card1_recent"]

    @classmethod
    def load(cls, bundle_path, state_path) -> "OnlineScorer":
        return cls(joblib.load(bundle_path), joblib.load(state_path))

    # ------------------------------------------------------------------ feature üretimi
    def features(self, rec: dict) -> dict:
        b = self.b
        t = _f(rec["TransactionDT"])
        amt = _f(rec["TransactionAmt"])
        day = t // 86400
        dt = pd.Timestamp(b["start_date"]) + pd.to_timedelta(t, unit="s")
        hour = dt.hour
        uk = uid_key(rec.get("card1"), rec.get("addr1"), rec.get("D1"), day)
        u = self.uids.get(uk) or UidState()
        dk = device_key(rec)
        email = rec.get("P_emaildomain")
        email = None if _nan(email) else email

        f: dict[str, Any] = {"uid_key": uk, "device_key": dk, "hour": hour, "day_of_week": dt.dayofweek,
                             "is_weekend": int(dt.dayofweek >= 5),
                             "local_hour": (hour - b["local_hour_offset"]) % 24,
                             "hour_sin": math.sin(2 * math.pi * hour / 24), "hour_cos": math.cos(2 * math.pi * hour / 24)}
        # entity (geçmişe dayalı)
        cnt = u.cnt
        mean = u.s / cnt if cnt > 0 else np.nan
        std = math.sqrt(max(u.sq / cnt - mean ** 2, 0)) if cnt > 1 else np.nan
        recent = [x for x in u.recent if x < t]
        f.update(
            uid_tx_count_past=cnt, uid_avg_amount_past=mean, uid_std_amount_past=std,
            amt_to_uid_avg_past=amt / mean if cnt > 0 and mean else np.nan,
            amt_zscore_uid_past=(amt - mean) / (std + 1) if cnt >= 2 else np.nan,
            uid_secs_since_prev=t - u.last_ts if cnt > 0 else np.nan,
            uid_tx_last_1h=sum(1 for x in recent if x >= t - 3600),
            uid_tx_last_24h=sum(1 for x in recent if x >= t - 86400),
            uid_age_days=(t - u.first_ts) / 86400 if cnt > 0 else 0.0,
            card_age_days=_f(rec.get("D1")),
        )
        c1 = _f(rec.get("card1"))
        f["card1_tx_last_1h"] = sum(1 for x in self.card1_recent.get(c1, ()) if t - 3600 <= x < t)
        new_dev = int(dk is not None and dk not in u.devices and cnt > 0)
        new_em = int(email is not None and email not in u.emails and cnt > 0)
        devs = u.devices | ({dk} if dk else set())
        ems = u.emails | ({email} if email else set())
        f.update(is_new_device_for_uid=new_dev, is_new_email_for_uid=new_em,
                 uid_n_devices=len(devs), uid_n_emails=len(ems),
                 uid_n_devices_past=len(devs), uid_n_emails_past=len(ems))
        if dk is None:
            f["device_n_uids"] = np.nan
        else:
            s = self.dev_uids.get(dk, set())
            f["device_n_uids"] = len(s | {uk})
        # relational / context
        fq = b["freq"]
        for c in ("card1", "addr1", "P_emaildomain"):
            v = rec.get(c)
            f[f"{c}_freq"] = np.nan if _nan(v) else fq[c].get(v if c == "P_emaildomain" else _f(v), 0.0)
        f["card1_n_addr1"] = b["card1_n_addr1"].get(c1, 0)
        pe, re_ = rec.get("P_emaildomain"), rec.get("R_emaildomain")
        f["email_match"] = np.nan if (_nan(pe) or _nan(re_)) else float(pe == re_)
        f["amt_log"] = math.log1p(amt)
        f["amt_cents"] = (round(amt * 1000) % 1000) / 1000
        f["amt_to_product_median"] = amt / b["product_median"].get(rec.get("ProductCD"), b["global_median_amt"])
        f["has_identity"] = int(any(not _nan(rec.get(c)) for c in b["identity_cols"]))
        # batch'te türetilmiş D1n ve device_fp kolonları da eksik sayılıyordu → aynı tanım
        f["n_missing_row"] = (sum(1 for c in b["raw_columns"] if _nan(rec.get(c)))
                              + int(_nan(rec.get("D1"))) + int(dk is None))
        return f

    # ------------------------------------------------------------------ katmanlar
    def _column(self, rec):
        b = self.b["column"]
        vals, raw = [], []
        for c in b["num"]:
            x = _f(rec.get(c))
            p = b["num_params"][c]
            if not math.isnan(x) and p["log"]:
                x = math.log1p(max(x, 0))
            d = (x - p["med"]) / p["scale"] if not math.isnan(x) else 0.0
            z = max(d, 0) if c.startswith("C") else abs(d)
            raw.append(z); vals.append(tail(b["ref_pos"][c], z))
        for c in b["cat"]:
            v = rec.get(c)
            if _nan(v):
                z = 0.0
            else:
                key = v if isinstance(v, str) else _f(v)
                fr = b["cat_freq"][c].get(key, b["unseen_freq"])
                z = -math.log10(fr)
            raw.append(z); vals.append(tail(b["ref_pos"][c], z))
        names = b["num"] + b["cat"]
        S = np.array(vals)
        score = float(np.sort(S)[-3:].mean())
        j = int(S.argmax())
        return score, (f"{names[j]}={raw[j]:.3g}" if S[j] > 0 else "—")

    def _multivariate(self, rec, f):
        b = self.b["mv"]
        row = {c: f.get(c, np.nan) for c in b["feats"]}
        row.update({c: _f(rec.get(c)) for c in b["raw"]})
        for c in b["log_cols"]:
            v = _f(row[c])
            row[c] = np.nan if math.isnan(v) else math.log1p(max(v, 0))
        row["is_credit"] = float(rec.get("card6") == "credit")
        row["is_mobile"] = float(rec.get("DeviceType") == "mobile")
        for p in "WCRHS":
            row[f"product_{p}"] = float(rec.get("ProductCD") == p)
        x = np.array([_f(row[c], b["medians"][c]) for c in b["base_names"]], dtype=float)
        v = np.array([_f(rec.get(c)) for c in b["v_reps"]], dtype=float)
        v = np.sign(v) * np.log1p(np.abs(v))
        v = np.where(np.isnan(v), -1.0, v)
        vp = b["v_pca"].transform(b["v_scaler"].transform(v.reshape(1, -1)))
        X = np.clip(b["scaler"].transform(np.hstack([x.reshape(1, -1), vp])), -10, 10)
        if_s = float(-b["iso"].score_samples(X)[0])
        recon = b["pca"].inverse_transform(b["pca"].transform(X))
        contrib = ((X - recon) ** 2)[0]
        err = float(contrib.sum())
        score = (ecdf(b["ref_if"], if_s) + ecdf(b["ref_pca"], err)) / 2
        top = np.argsort(-contrib)[:2]
        return score, f"{b['names'][top[0]]} + {b['names'][top[1]]}"

    def _entity(self, f):
        b = self.b["entity"]
        z = f["amt_zscore_uid_past"]
        comp = {
            "amount_deviation": min(abs(z), 50) if not _nan(z) else 0.0,
            "velocity_24h": f["uid_tx_last_24h"],
            "rapid_succession": 1 / (1 + f["uid_secs_since_prev"] / 60) if not _nan(f["uid_secs_since_prev"]) else 0.0,
            "new_device": f["is_new_device_for_uid"],
            "new_email": f["is_new_email_for_uid"],
            "shared_device": max(_f(f["device_n_uids"], 1) - 1, 0),
            "multi_device_email": (max(f["uid_n_devices"], 1) - 1) + (max(f["uid_n_emails"], 1) - 1),
            "new_card": 1 / (1 + f["card_age_days"]) if not _nan(f["card_age_days"]) else 0.0,
        }
        return self._topk(comp, b["ref_pos"], 2)

    def _temporal(self, rec, f):
        b = self.b["temporal"]
        u = self.uids.get(f["uid_key"])
        hour = f["hour"]
        hour_dev = 0.0
        if u is not None and u.cnt >= 3:
            mh = (math.atan2(u.sin_sum, u.cos_sum) % (2 * math.pi)) * 24 / (2 * math.pi)
            d = abs(hour - mh); hour_dev = min(d, 24 - d)
        rate = self.b["card1_rate_h"].get(_f(rec.get("card1")), 0.0)
        comp = {
            "hour_rarity": b["hour_rarity"][hour],
            "hour_deviation_uid": hour_dev,
            "burst_1h_uid": f["uid_tx_last_1h"],
            "burst_1h_card1": f["card1_tx_last_1h"] / (rate + 1e-3),
            "segment_volume_spike": 0.0,
        }
        return self._topk(comp, b["ref_pos"], 2)

    @staticmethod
    def _topk(comp, refs, k):
        S = {n: tail(refs[n], v) for n, v in comp.items()}
        vals = np.array(list(S.values()))
        best = max(S, key=S.get)
        reason = f"{best}={comp[best]:.3g}" if S[best] > 0 else "—"
        return float(np.sort(vals)[-k:].mean()), reason

    # ------------------------------------------------------------------ ana giriş noktası
    def score(self, rec: dict, update: bool = True) -> dict:
        f = self.features(rec)
        layers, reasons = {}, {}
        layers["column"], reasons["column"] = self._column(rec)
        layers["multivariate"], reasons["multivariate"] = self._multivariate(rec, f)
        layers["entity"], reasons["entity"] = self._entity(f)
        layers["temporal"], reasons["temporal"] = self._temporal(rec, f)
        w = self.b["weights"]
        norm = {k: ecdf(self.b["layer_ref"][k], v) for k, v in layers.items()}
        contrib = {k: w[k] * norm[k] for k in LAYERS}
        out = {
            "raw_anomaly_score": round(100 * sum(contrib.values()), 2),
            "dominant_layer": max(contrib, key=contrib.get),
            "layer_scores": {k: round(norm[k], 4) for k in LAYERS},
            "layer_reasons": reasons,
            "weights": w,
            "features": {k: (None if _nan(v) else v) for k, v in f.items()},
        }
        if update:
            self.update(rec, f)
        return out

    def update(self, rec: dict, f: dict | None = None) -> None:
        f = f or self.features(rec)
        t, amt = _f(rec["TransactionDT"]), _f(rec["TransactionAmt"])
        u = self.uids.setdefault(f["uid_key"], UidState())
        if u.cnt == 0:
            u.first_ts = t
        u.cnt += 1; u.s += amt; u.sq += amt * amt; u.last_ts = t
        u.recent.append(t)
        ang = 2 * math.pi * f["hour"] / 24
        u.sin_sum += math.sin(ang); u.cos_sum += math.cos(ang)
        if f["device_key"]:
            u.devices.add(f["device_key"])
            self.dev_uids.setdefault(f["device_key"], set()).add(f["uid_key"])
        if not _nan(rec.get("P_emaildomain")):
            u.emails.add(rec["P_emaildomain"])
        self.card1_recent.setdefault(_f(rec.get("card1")), deque(maxlen=500)).append(t)
