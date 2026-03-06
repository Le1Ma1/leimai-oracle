from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
from typing import Any
import warnings

import numpy as np
import pandas as pd
from sklearn.exceptions import ConvergenceWarning
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score


EPS = 1e-12


@dataclass(frozen=True)
class MetaLabelConfig:
    enabled: bool
    model: str
    objective: str
    penalty: str
    c: float
    max_iter: int
    class_weight: str
    tp_mult: float
    sl_mult: float
    vertical_horizon_bars: int
    vol_window: int
    min_events: int
    threshold_min: float
    threshold_max: float
    threshold_step: float
    precision_floor: float
    threshold_objective: str
    prob_threshold_fallback: float
    feature_cap: int
    feature_allowlist: tuple[str, ...]
    cpcv_splits: int
    cpcv_test_groups: int
    cpcv_purge_bars: int
    cpcv_embargo_bars: int
    cpcv_max_combinations: int


def _safe_float(value: object, default: float = 0.0) -> float:
    try:
        out = float(value)
    except Exception:
        return default
    if not np.isfinite(out):
        return default
    return out


def _safe_int(value: object, default: int = 0) -> int:
    try:
        out = int(value)
    except Exception:
        return default
    return out


def _coerce_bool_series(value: object, index: pd.DatetimeIndex) -> pd.Series:
    if isinstance(value, pd.Series):
        return value.reindex(index).fillna(False).astype(bool)
    return pd.Series(np.asarray(value, dtype=bool), index=index, dtype=bool)


def _prepare_features(
    feature_df: pd.DataFrame,
    allowlist: tuple[str, ...],
    feature_cap: int,
) -> tuple[pd.DataFrame, list[str]]:
    if feature_df.empty:
        return pd.DataFrame(index=feature_df.index.copy()), []

    numeric_cols = [
        column
        for column in feature_df.columns
        if pd.api.types.is_numeric_dtype(feature_df[column])
    ]
    if not numeric_cols:
        return pd.DataFrame(index=feature_df.index.copy()), []

    selected: list[str] = []
    for column in allowlist:
        if column in numeric_cols and column not in selected:
            selected.append(column)
    if feature_cap <= 0:
        cap = len(selected) if selected else min(3, len(numeric_cols))
    else:
        cap = min(feature_cap, len(numeric_cols))
    if len(selected) < cap:
        for column in numeric_cols:
            if column in selected:
                continue
            selected.append(column)
            if len(selected) >= cap:
                break

    if not selected:
        selected = numeric_cols[: min(3, len(numeric_cols))]
    selected = selected[:cap] if cap > 0 else selected

    out = feature_df[selected].copy()
    out = out.replace([np.inf, -np.inf], np.nan).fillna(0.0).astype("float64")
    return out, selected


def _atr_ratio(
    close: pd.Series,
    high: pd.Series,
    low: pd.Series,
    window: int,
) -> pd.Series:
    c = pd.to_numeric(close, errors="coerce").astype("float64")
    h = pd.to_numeric(high, errors="coerce").astype("float64")
    l = pd.to_numeric(low, errors="coerce").astype("float64")
    prev = c.shift(1)
    tr_1 = (h - l).abs()
    tr_2 = (h - prev).abs()
    tr_3 = (l - prev).abs()
    tr = pd.concat([tr_1, tr_2, tr_3], axis=1).max(axis=1)
    scale = prev.abs().replace(0.0, np.nan)
    atr_ratio = (tr / (scale + EPS)).rolling(window=max(2, int(window)), min_periods=max(2, int(window // 2))).mean()
    return atr_ratio.shift(1).replace([np.inf, -np.inf], np.nan)


def _build_triple_barrier_events(
    close: pd.Series,
    high: pd.Series,
    low: pd.Series,
    entry: pd.Series,
    *,
    friction_bps: int,
    tp_mult: float,
    sl_mult: float,
    vertical_horizon_bars: int,
    vol_window: int,
) -> list[dict[str, Any]]:
    close_s = pd.to_numeric(close, errors="coerce").astype("float64")
    high_s = pd.to_numeric(high, errors="coerce").astype("float64")
    low_s = pd.to_numeric(low, errors="coerce").astype("float64")
    entry_s = _coerce_bool_series(entry, close_s.index)
    if close_s.empty:
        return []

    atr_ratio = _atr_ratio(close_s, high_s, low_s, window=vol_window)
    entry_idx = np.flatnonzero(entry_s.to_numpy(dtype=bool, copy=False))
    if entry_idx.size == 0:
        return []

    close_arr = close_s.to_numpy(dtype="float64", copy=False)
    high_arr = high_s.to_numpy(dtype="float64", copy=False)
    low_arr = low_s.to_numpy(dtype="float64", copy=False)
    atr_arr = atr_ratio.to_numpy(dtype="float64", copy=False)
    friction_rt = float(max(int(friction_bps), 0)) / 10_000.0

    out: list[dict[str, Any]] = []
    bars = close_arr.shape[0]
    fallback_vol = float(np.nanmedian(atr_arr))
    if not np.isfinite(fallback_vol) or fallback_vol <= 0.0:
        fallback_vol = 0.001

    for start_i in entry_idx.tolist():
        if start_i >= bars - 2:
            continue
        px0 = float(close_arr[start_i])
        if not np.isfinite(px0) or px0 <= 0.0:
            continue

        vol = float(atr_arr[start_i]) if np.isfinite(atr_arr[start_i]) else fallback_vol
        if not np.isfinite(vol) or vol <= 0.0:
            vol = fallback_vol
        vol = max(1e-6, float(vol))

        tp_ret = float(max(tp_mult, 0.05)) * vol
        sl_ret = float(max(sl_mult, 0.05)) * vol
        upper = px0 * (1.0 + tp_ret)
        lower = px0 * max(0.01, (1.0 - sl_ret))
        end_i = min(bars - 1, start_i + max(1, int(vertical_horizon_bars)))

        hit_i = end_i
        provenance = "vertical_nonpos"
        label = 0
        touched = False

        for j in range(start_i + 1, end_i + 1):
            hi = float(high_arr[j])
            lo = float(low_arr[j])
            tp_hit = bool(np.isfinite(hi) and hi >= upper)
            sl_hit = bool(np.isfinite(lo) and lo <= lower)
            if tp_hit and sl_hit:
                # Conservative tie-breaker: assume stop-loss hit first.
                hit_i = j
                provenance = "sl_first"
                label = 0
                touched = True
                break
            if tp_hit:
                hit_i = j
                provenance = "tp_first"
                label = 1
                touched = True
                break
            if sl_hit:
                hit_i = j
                provenance = "sl_first"
                label = 0
                touched = True
                break

        exit_px = float(close_arr[hit_i]) if np.isfinite(close_arr[hit_i]) else px0
        gross_return = float((exit_px / (px0 + EPS)) - 1.0)
        net_return = gross_return - (2.0 * friction_rt)

        if not touched:
            if net_return > 0.0:
                provenance = "vertical_pos"
                label = 1
            else:
                provenance = "vertical_nonpos"
                label = 0

        out.append(
            {
                "entry_idx": int(start_i),
                "exit_idx": int(hit_i),
                "horizon_bars": int(end_i - start_i),
                "hold_bars": int(hit_i - start_i),
                "label": int(label),
                "provenance": provenance,
                "entry_price": px0,
                "exit_price": exit_px,
                "volatility_ref": vol,
                "tp_ret": tp_ret,
                "sl_ret": sl_ret,
                "gross_return": gross_return,
                "net_return": net_return,
            }
        )
    return out


def _compute_uniqueness_weights(events: list[dict[str, Any]], bars_count: int) -> np.ndarray:
    if not events:
        return np.zeros(0, dtype="float64")

    concurrency = np.zeros(int(bars_count), dtype="float64")
    for event in events:
        start_i = max(0, int(event["entry_idx"]) + 1)
        end_i = min(int(bars_count) - 1, int(event["exit_idx"]))
        if end_i < start_i:
            continue
        concurrency[start_i : end_i + 1] += 1.0

    weights = np.ones(len(events), dtype="float64")
    for idx, event in enumerate(events):
        start_i = max(0, int(event["entry_idx"]) + 1)
        end_i = min(int(bars_count) - 1, int(event["exit_idx"]))
        if end_i < start_i:
            weights[idx] = 1.0
            continue
        local = concurrency[start_i : end_i + 1]
        valid = local > 0.0
        if not valid.any():
            weights[idx] = 1.0
            continue
        weights[idx] = float(np.mean(1.0 / local[valid]))

    mean_w = float(np.mean(weights))
    if np.isfinite(mean_w) and mean_w > 1e-12:
        weights = weights / mean_w
    weights = np.nan_to_num(weights, nan=1.0, posinf=1.0, neginf=1.0)
    return weights.astype("float64")


def _confusion_counts(y_true: np.ndarray, y_pred: np.ndarray) -> tuple[int, int, int, int]:
    y_t = y_true.astype(int, copy=False)
    y_p = y_pred.astype(int, copy=False)
    tp = int(np.sum((y_t == 1) & (y_p == 1)))
    fp = int(np.sum((y_t == 0) & (y_p == 1)))
    fn = int(np.sum((y_t == 1) & (y_p == 0)))
    tn = int(np.sum((y_t == 0) & (y_p == 0)))
    return tp, fp, fn, tn


def _fbeta(precision: float, recall: float, beta: float) -> float:
    if precision <= 0.0 or recall <= 0.0:
        return 0.0
    b2 = beta * beta
    return float((1.0 + b2) * precision * recall / (b2 * precision + recall + EPS))


def _scan_thresholds(
    y_true: np.ndarray,
    y_prob: np.ndarray,
    *,
    precision_floor: float,
    threshold_min: float,
    threshold_max: float,
    threshold_step: float,
    objective: str,
) -> tuple[dict[str, float] | None, int]:
    if y_true.size == 0 or y_prob.size == 0:
        return None, 0

    lo = float(max(0.0, min(1.0, threshold_min)))
    hi = float(max(0.0, min(1.0, threshold_max)))
    if hi < lo:
        lo, hi = hi, lo
    step = max(float(threshold_step), 1e-3)
    thresholds = np.arange(lo, hi + step * 0.5, step, dtype="float64")
    if thresholds.size == 0:
        thresholds = np.asarray([0.5], dtype="float64")

    best: dict[str, float] | None = None
    valid_count = 0
    for threshold in thresholds.tolist():
        y_pred = (y_prob >= threshold).astype(int)
        tp, fp, fn, _ = _confusion_counts(y_true, y_pred)
        precision = float(tp / (tp + fp)) if (tp + fp) > 0 else 0.0
        recall = float(tp / (tp + fn)) if (tp + fn) > 0 else 0.0
        if precision < precision_floor:
            continue
        valid_count += 1
        f1 = _fbeta(precision, recall, beta=1.0)
        f05 = _fbeta(precision, recall, beta=0.5)
        score = f1 if objective == "f1" else f05
        candidate = {
            "threshold": float(threshold),
            "precision": precision,
            "recall": recall,
            "f1": f1,
            "f05": f05,
            "objective_score": score,
        }
        if best is None:
            best = candidate
            continue
        if candidate["objective_score"] > best["objective_score"] + 1e-12:
            best = candidate
            continue
        if abs(candidate["objective_score"] - best["objective_score"]) <= 1e-12:
            if candidate["precision"] > best["precision"] + 1e-12:
                best = candidate
                continue
            if abs(candidate["precision"] - best["precision"]) <= 1e-12 and candidate["threshold"] > best["threshold"]:
                best = candidate
    return best, valid_count


def _classification_metrics(
    y_true: np.ndarray,
    y_prob: np.ndarray,
    y_pred: np.ndarray,
) -> dict[str, float]:
    tp, fp, fn, tn = _confusion_counts(y_true, y_pred)
    precision = float(tp / (tp + fp)) if (tp + fp) > 0 else 0.0
    recall = float(tp / (tp + fn)) if (tp + fn) > 0 else 0.0
    f1 = _fbeta(precision, recall, beta=1.0)
    f05 = _fbeta(precision, recall, beta=0.5)
    try:
        if len(np.unique(y_true)) < 2:
            pr_auc = 0.0
        else:
            pr_auc = float(average_precision_score(y_true, y_prob))
    except Exception:
        pr_auc = 0.0
    return {
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "f05": f05,
        "pr_auc": pr_auc,
        "tp": float(tp),
        "fp": float(fp),
        "fn": float(fn),
        "tn": float(tn),
        "positive_pred_rate": float(np.mean(y_pred.astype("float64"))) if y_pred.size > 0 else 0.0,
        "positive_true_rate": float(np.mean(y_true.astype("float64"))) if y_true.size > 0 else 0.0,
    }


def _fit_logreg(
    X_train: np.ndarray,
    y_train: np.ndarray,
    sample_weight: np.ndarray,
    *,
    penalty: str,
    c: float,
    max_iter: int,
    class_weight: str,
) -> LogisticRegression | None:
    penalty_norm = str(penalty).strip().lower()
    if penalty_norm not in {"l1", "l2"}:
        penalty_norm = "l2"

    attempts: list[tuple[str, str]] = []
    if penalty_norm == "l1":
        attempts.append(("l1", "saga"))
    else:
        attempts.append(("l2", "lbfgs"))
        attempts.append(("l2", "saga"))

    for pen, solver in attempts:
        try:
            class_weight_arg: str | dict[int, float] | None
            if str(class_weight).strip().lower() == "balanced":
                class_weight_arg = "balanced"
            else:
                class_weight_arg = None
            model = LogisticRegression(
                penalty=pen,
                C=float(max(c, 1e-6)),
                solver=solver,
                class_weight=class_weight_arg,
                max_iter=int(max(200, max_iter)),
                random_state=42,
            )
            with warnings.catch_warnings():
                warnings.filterwarnings("ignore", category=ConvergenceWarning)
                model.fit(X_train, y_train, sample_weight=sample_weight)
            return model
        except Exception:
            continue
    return None


def _standardize_train_test(
    X_train: np.ndarray,
    X_test: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    mean = np.nanmean(X_train, axis=0)
    std = np.nanstd(X_train, axis=0)
    std = np.where(std < 1e-9, 1.0, std)
    x_train_s = (X_train - mean) / std
    x_test_s = (X_test - mean) / std
    x_train_s = np.nan_to_num(x_train_s, nan=0.0, posinf=0.0, neginf=0.0)
    x_test_s = np.nan_to_num(x_test_s, nan=0.0, posinf=0.0, neginf=0.0)
    return x_train_s.astype("float64"), x_test_s.astype("float64")


def _build_cpcv_splits(
    entry_positions: np.ndarray,
    *,
    n_splits: int,
    test_groups: int,
    purge_bars: int,
    embargo_bars: int,
    max_combinations: int,
) -> list[tuple[np.ndarray, np.ndarray, tuple[int, ...]]]:
    n_events = int(entry_positions.shape[0])
    if n_events < 4:
        return []

    groups_n = max(3, min(int(n_splits), n_events))
    group_indices = [arr.astype(int) for arr in np.array_split(np.arange(n_events, dtype=int), groups_n) if arr.size > 0]
    if len(group_indices) < 3:
        return []

    t_groups = max(1, min(int(test_groups), len(group_indices) - 1))
    combos = list(combinations(range(len(group_indices)), t_groups))
    if len(combos) > max_combinations:
        step = max(1, len(combos) // max_combinations)
        combos = combos[::step][:max_combinations]

    out: list[tuple[np.ndarray, np.ndarray, tuple[int, ...]]] = []
    gap = max(0, int(purge_bars)) + max(0, int(embargo_bars))
    for combo in combos:
        test_idx = np.concatenate([group_indices[idx] for idx in combo]).astype(int)
        if test_idx.size == 0:
            continue
        test_min = int(np.min(entry_positions[test_idx]))
        test_max = int(np.max(entry_positions[test_idx]))

        train_mask = np.ones(n_events, dtype=bool)
        train_mask[test_idx] = False
        leak_band = (entry_positions >= (test_min - gap)) & (entry_positions <= (test_max + gap))
        train_mask[leak_band] = False
        train_idx = np.flatnonzero(train_mask).astype(int)
        if train_idx.size < 10:
            continue
        out.append((train_idx, test_idx, combo))
    return out


def run_meta_label_veto(
    *,
    close: pd.Series,
    high: pd.Series,
    low: pd.Series,
    entry: pd.Series,
    feature_df: pd.DataFrame,
    friction_bps: int,
    cfg: MetaLabelConfig,
) -> dict[str, Any]:
    index = close.index
    fallback_entry = pd.Series(False, index=index, dtype=bool)
    if not cfg.enabled:
        return {
            "enabled": False,
            "entry_meta": fallback_entry,
            "meta_model": {"name": "disabled"},
            "events_total": 0,
            "labels_positive": 0,
            "labels_negative": 0,
            "label_provenance": {},
            "weights": {"avg": 0.0, "min": 0.0, "max": 0.0},
            "threshold": {
                "precision_floor": float(cfg.precision_floor),
                "objective": cfg.threshold_objective,
                "selected": None,
                "valid_threshold_count": 0,
                "failsafe_veto_all": False,
            },
            "classification": {},
            "cpcv": {
                "splits_total": 0,
                "splits_used": 0,
                "precision_floor_compliance_rate": 0.0,
                "veto_all_rate": 0.0,
                "folds": [],
            },
            "feature_columns": [],
            "coefficients": {},
            "reason": "meta_label_disabled",
        }

    events = _build_triple_barrier_events(
        close=close,
        high=high,
        low=low,
        entry=entry,
        friction_bps=friction_bps,
        tp_mult=cfg.tp_mult,
        sl_mult=cfg.sl_mult,
        vertical_horizon_bars=cfg.vertical_horizon_bars,
        vol_window=cfg.vol_window,
    )
    if len(events) < max(2, int(cfg.min_events)):
        return {
            "enabled": True,
            "entry_meta": fallback_entry,
            "meta_model": {"name": "logreg"},
            "events_total": len(events),
            "labels_positive": 0,
            "labels_negative": len(events),
            "label_provenance": {},
            "weights": {"avg": 0.0, "min": 0.0, "max": 0.0},
            "threshold": {
                "precision_floor": float(cfg.precision_floor),
                "objective": cfg.threshold_objective,
                "selected": None,
                "valid_threshold_count": 0,
                "failsafe_veto_all": True,
            },
            "classification": {
                "precision": 0.0,
                "recall": 0.0,
                "f1": 0.0,
                "f05": 0.0,
                "pr_auc": 0.0,
                "positive_pred_rate": 0.0,
                "positive_true_rate": 0.0,
            },
            "cpcv": {
                "splits_total": 0,
                "splits_used": 0,
                "precision_floor_compliance_rate": 0.0,
                "veto_all_rate": 1.0,
                "folds": [],
            },
            "feature_columns": [],
            "coefficients": {},
            "reason": "insufficient_events",
        }

    features, feature_columns = _prepare_features(
        feature_df=feature_df.reindex(index).fillna(0.0),
        allowlist=cfg.feature_allowlist,
        feature_cap=cfg.feature_cap,
    )
    if features.empty:
        return {
            "enabled": True,
            "entry_meta": fallback_entry,
            "meta_model": {"name": "logreg"},
            "events_total": len(events),
            "labels_positive": 0,
            "labels_negative": len(events),
            "label_provenance": {},
            "weights": {"avg": 0.0, "min": 0.0, "max": 0.0},
            "threshold": {
                "precision_floor": float(cfg.precision_floor),
                "objective": cfg.threshold_objective,
                "selected": None,
                "valid_threshold_count": 0,
                "failsafe_veto_all": True,
            },
            "classification": {
                "precision": 0.0,
                "recall": 0.0,
                "f1": 0.0,
                "f05": 0.0,
                "pr_auc": 0.0,
                "positive_pred_rate": 0.0,
                "positive_true_rate": 0.0,
            },
            "cpcv": {
                "splits_total": 0,
                "splits_used": 0,
                "precision_floor_compliance_rate": 0.0,
                "veto_all_rate": 1.0,
                "folds": [],
            },
            "feature_columns": [],
            "coefficients": {},
            "reason": "no_features",
        }

    entry_positions = np.asarray([int(event["entry_idx"]) for event in events], dtype=int)
    labels = np.asarray([int(event["label"]) for event in events], dtype=int)
    sample_weight = _compute_uniqueness_weights(events, bars_count=len(index))

    X = features.iloc[entry_positions].to_numpy(dtype="float64", copy=False)
    X = np.nan_to_num(X, nan=0.0, posinf=0.0, neginf=0.0)

    splits = _build_cpcv_splits(
        entry_positions=entry_positions,
        n_splits=cfg.cpcv_splits,
        test_groups=cfg.cpcv_test_groups,
        purge_bars=cfg.cpcv_purge_bars,
        embargo_bars=cfg.cpcv_embargo_bars,
        max_combinations=max(4, int(cfg.cpcv_max_combinations)),
    )
    if not splits:
        splits = [(np.arange(0, max(1, len(events) - 1), dtype=int), np.asarray([len(events) - 1], dtype=int), (0,))]

    oof_probs: list[list[float]] = [[] for _ in range(len(events))]
    fold_payloads: list[dict[str, Any]] = []
    precision_compliant = 0
    veto_all_count = 0
    splits_used = 0

    for train_idx, test_idx, combo in splits:
        y_train = labels[train_idx]
        y_test = labels[test_idx]
        if len(np.unique(y_train)) < 2 or len(np.unique(y_test)) < 2:
            continue
        x_train = X[train_idx]
        x_test = X[test_idx]
        w_train = sample_weight[train_idx]

        x_train_s, x_test_s = _standardize_train_test(x_train, x_test)
        model = _fit_logreg(
            X_train=x_train_s,
            y_train=y_train,
            sample_weight=w_train,
            penalty=cfg.penalty,
            c=cfg.c,
            max_iter=cfg.max_iter,
            class_weight=cfg.class_weight,
        )
        if model is None:
            continue

        probs = model.predict_proba(x_test_s)[:, 1].astype("float64")
        for local_i, event_i in enumerate(test_idx.tolist()):
            oof_probs[event_i].append(float(probs[local_i]))

        threshold_pick, valid_count = _scan_thresholds(
            y_true=y_test,
            y_prob=probs,
            precision_floor=cfg.precision_floor,
            threshold_min=cfg.threshold_min,
            threshold_max=cfg.threshold_max,
            threshold_step=cfg.threshold_step,
            objective=cfg.threshold_objective,
        )
        splits_used += 1
        if threshold_pick is None:
            veto_all_count += 1
            fold_pred = np.zeros_like(y_test, dtype=int)
            fold_metrics = _classification_metrics(y_test, probs, fold_pred)
            fold_payloads.append(
                {
                    "combo": list(combo),
                    "samples": int(len(test_idx)),
                    "threshold": None,
                    "valid_threshold_count": int(valid_count),
                    "failsafe_veto_all": True,
                    **fold_metrics,
                }
            )
            continue

        precision_compliant += 1
        threshold = float(threshold_pick["threshold"])
        fold_pred = (probs >= threshold).astype(int)
        fold_metrics = _classification_metrics(y_test, probs, fold_pred)
        fold_payloads.append(
            {
                "combo": list(combo),
                "samples": int(len(test_idx)),
                "threshold": threshold,
                "valid_threshold_count": int(valid_count),
                "failsafe_veto_all": False,
                **fold_metrics,
            }
        )

    probs_mean = np.asarray(
        [
            float(np.mean(values)) if values else np.nan
            for values in oof_probs
        ],
        dtype="float64",
    )
    finite_mask = np.isfinite(probs_mean)
    if not finite_mask.any():
        finite_mask = np.ones_like(probs_mean, dtype=bool)
        probs_mean = np.nan_to_num(probs_mean, nan=0.0, posinf=0.0, neginf=0.0)

    global_pick, valid_count_global = _scan_thresholds(
        y_true=labels[finite_mask],
        y_prob=probs_mean[finite_mask],
        precision_floor=cfg.precision_floor,
        threshold_min=cfg.threshold_min,
        threshold_max=cfg.threshold_max,
        threshold_step=cfg.threshold_step,
        objective=cfg.threshold_objective,
    )

    failsafe_veto_all = global_pick is None
    if failsafe_veto_all:
        y_pred_global = np.zeros_like(labels, dtype=int)
        threshold_value: float | None = None
    else:
        threshold_value = float(global_pick["threshold"])
        y_pred_global = (probs_mean >= threshold_value).astype(int)

    clf_metrics = _classification_metrics(
        y_true=labels.astype(int),
        y_prob=np.nan_to_num(probs_mean, nan=0.0, posinf=0.0, neginf=0.0),
        y_pred=y_pred_global.astype(int),
    )

    entry_meta = pd.Series(False, index=index, dtype=bool)
    if not failsafe_veto_all:
        accepted = np.flatnonzero(y_pred_global.astype(bool))
        if accepted.size > 0:
            accepted_entries = entry_positions[accepted]
            entry_meta.iloc[accepted_entries] = True

    label_provenance: dict[str, int] = {}
    for event in events:
        key = str(event.get("provenance", "unknown"))
        label_provenance[key] = int(label_provenance.get(key, 0)) + 1

    compliance_rate = float(precision_compliant / max(1, splits_used))
    veto_all_rate = float(veto_all_count / max(1, splits_used))

    coef_map: dict[str, float] = {}
    if len(np.unique(labels)) >= 2:
        x_all = np.nan_to_num(X, nan=0.0, posinf=0.0, neginf=0.0)
        x_all_s, _ = _standardize_train_test(x_all, x_all)
        model_all = _fit_logreg(
            X_train=x_all_s,
            y_train=labels,
            sample_weight=sample_weight,
            penalty=cfg.penalty,
            c=cfg.c,
            max_iter=cfg.max_iter,
            class_weight=cfg.class_weight,
        )
        if model_all is not None and hasattr(model_all, "coef_"):
            for col, coef in zip(feature_columns, model_all.coef_[0].tolist()):
                coef_map[str(col)] = float(coef)

    return {
        "enabled": True,
        "entry_meta": entry_meta,
        "meta_model": {
            "name": "logreg",
            "penalty": cfg.penalty,
            "c": cfg.c,
            "max_iter": cfg.max_iter,
            "class_weight": cfg.class_weight,
            "objective": cfg.objective,
        },
        "events_total": int(len(events)),
        "labels_positive": int(np.sum(labels == 1)),
        "labels_negative": int(np.sum(labels == 0)),
        "label_provenance": label_provenance,
        "weights": {
            "avg": float(np.mean(sample_weight)) if sample_weight.size > 0 else 0.0,
            "min": float(np.min(sample_weight)) if sample_weight.size > 0 else 0.0,
            "max": float(np.max(sample_weight)) if sample_weight.size > 0 else 0.0,
        },
        "threshold": {
            "precision_floor": float(cfg.precision_floor),
            "objective": cfg.threshold_objective,
            "selected": threshold_value,
            "valid_threshold_count": int(valid_count_global),
            "failsafe_veto_all": bool(failsafe_veto_all),
        },
        "classification": clf_metrics,
        "cpcv": {
            "splits_total": int(len(splits)),
            "splits_used": int(splits_used),
            "precision_floor_compliance_rate": compliance_rate,
            "veto_all_rate": veto_all_rate,
            "folds": fold_payloads,
            "n_splits": int(cfg.cpcv_splits),
            "test_groups": int(cfg.cpcv_test_groups),
            "purge_bars": int(cfg.cpcv_purge_bars),
            "embargo_bars": int(cfg.cpcv_embargo_bars),
        },
        "feature_columns": feature_columns,
        "coefficients": coef_map,
        "reason": "ok" if not failsafe_veto_all else "precision_floor_unmet_global",
    }
