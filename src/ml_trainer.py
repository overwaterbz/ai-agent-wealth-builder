import os
import joblib
import numpy as np
from datetime import datetime, timezone
from sklearn.ensemble import RandomForestRegressor
from sklearn.model_selection import cross_val_score
from sklearn.metrics import mean_absolute_error

from src.models import get_session, TradeHistory, MLModelMeta

MODEL_PATH = "models/fair_prob_model.pkl"
MIN_SAMPLES_FOR_TRAINING = 50
RETRAIN_THRESHOLD = 50

_model = None
_model_accuracy = None


def ensure_model_dir():
    os.makedirs("models", exist_ok=True)


def log_trade_for_ml(market_id, market_description, fair_prob, market_prob,
                     side, amount_usdc, edge, kelly_fraction, ml_adjusted_prob=None):
    try:
        session = get_session()
        entry = TradeHistory(
            timestamp=datetime.now(timezone.utc),
            market_id=market_id,
            market_description=market_description,
            fair_prob=fair_prob,
            market_prob=market_prob,
            side=side,
            amount_usdc=amount_usdc,
            edge=edge,
            kelly_fraction=kelly_fraction,
            ml_adjusted_prob=ml_adjusted_prob,
        )
        session.add(entry)
        session.commit()
        session.close()
    except Exception as e:
        print(f"[ML] Error logging trade history: {e}")


def update_trade_outcome(market_id, outcome, profit):
    try:
        session = get_session()
        trades = (
            session.query(TradeHistory)
            .filter(TradeHistory.market_id == market_id, TradeHistory.resolved == False)
            .all()
        )
        for t in trades:
            t.outcome = outcome
            t.profit = profit
            t.resolved = True
        session.commit()
        session.close()
        return len(trades)
    except Exception as e:
        print(f"[ML] Error updating outcomes: {e}")
        return 0


def get_training_data():
    try:
        session = get_session()
        resolved = (
            session.query(TradeHistory)
            .filter(TradeHistory.resolved == True)
            .all()
        )
        session.close()

        if not resolved:
            return None, None

        X = []
        y = []

        for t in resolved:
            features = [
                t.fair_prob,
                t.market_prob,
                t.edge,
                t.kelly_fraction,
                1.0 if t.side == "buy_yes" else 0.0,
            ]
            X.append(features)

            actual_outcome = 1.0 if t.outcome == "yes" else 0.0
            y.append(actual_outcome)

        return np.array(X), np.array(y)

    except Exception as e:
        print(f"[ML] Error getting training data: {e}")
        return None, None


def train_model():
    global _model, _model_accuracy

    X, y = get_training_data()

    if X is None or len(X) < MIN_SAMPLES_FOR_TRAINING:
        n = 0 if X is None else len(X)
        print(f"[ML] Not enough resolved trades for training ({n}/{MIN_SAMPLES_FOR_TRAINING})")
        return None

    print(f"[ML] Training model on {len(X)} resolved trades...")

    model = RandomForestRegressor(
        n_estimators=100,
        max_depth=5,
        min_samples_split=5,
        random_state=42,
    )

    if len(X) >= 10:
        cv_folds = min(5, len(X) // 2)
        scores = cross_val_score(model, X, y, cv=cv_folds, scoring="neg_mean_absolute_error")
        mae = -scores.mean()
        print(f"[ML] Cross-validation MAE: {mae:.4f}")
    else:
        mae = None

    model.fit(X, y)

    y_pred = model.predict(X)
    train_mae = mean_absolute_error(y, y_pred)
    accuracy = 1.0 - train_mae

    _model = model
    _model_accuracy = accuracy

    ensure_model_dir()
    joblib.dump(model, MODEL_PATH)
    print(f"[ML] Model saved to {MODEL_PATH} (accuracy: {accuracy:.4f})")

    try:
        session = get_session()
        meta = MLModelMeta(
            timestamp=datetime.now(timezone.utc),
            model_type="RandomForestRegressor",
            n_samples=len(X),
            accuracy=accuracy,
            mae=mae or train_mae,
            notes=f"Features: fair_prob, market_prob, edge, kelly_fraction, side_is_yes",
        )
        session.add(meta)
        session.commit()
        session.close()
    except Exception as e:
        print(f"[ML] Error logging model meta: {e}")

    return model


def load_model():
    global _model, _model_accuracy

    if _model is not None:
        return _model

    if os.path.exists(MODEL_PATH):
        try:
            _model = joblib.load(MODEL_PATH)
            print(f"[ML] Model loaded from {MODEL_PATH}")
            return _model
        except Exception as e:
            print(f"[ML] Error loading model: {e}")

    return None


def predict_adjusted_prob(fair_prob, market_prob, edge, kelly_fraction, side):
    model = load_model()
    if model is None:
        return None

    try:
        features = np.array([[
            fair_prob,
            market_prob,
            edge,
            kelly_fraction,
            1.0 if side == "buy_yes" else 0.0,
        ]])

        prediction = model.predict(features)[0]
        prediction = max(0.01, min(0.99, prediction))
        return round(prediction, 4)

    except Exception as e:
        print(f"[ML] Prediction error: {e}")
        return None


def get_model_stats():
    stats = {
        "model_loaded": _model is not None,
        "model_accuracy": _model_accuracy,
        "model_path": MODEL_PATH,
        "model_exists": os.path.exists(MODEL_PATH),
    }

    try:
        session = get_session()
        total_history = session.query(TradeHistory).count()
        resolved = session.query(TradeHistory).filter(TradeHistory.resolved == True).count()
        unresolved = total_history - resolved

        latest_meta = (
            session.query(MLModelMeta)
            .order_by(MLModelMeta.id.desc())
            .first()
        )
        session.close()

        stats["total_trades_logged"] = total_history
        stats["resolved_trades"] = resolved
        stats["unresolved_trades"] = unresolved
        stats["ready_to_train"] = resolved >= MIN_SAMPLES_FOR_TRAINING
        stats["min_samples"] = MIN_SAMPLES_FOR_TRAINING

        if latest_meta:
            stats["last_trained"] = latest_meta.timestamp.strftime("%Y-%m-%d %H:%M")
            stats["last_accuracy"] = latest_meta.accuracy
            stats["last_mae"] = latest_meta.mae
            stats["last_n_samples"] = latest_meta.n_samples

    except Exception as e:
        stats["error"] = str(e)

    return stats


def should_retrain():
    try:
        session = get_session()
        resolved = session.query(TradeHistory).filter(TradeHistory.resolved == True).count()
        session.close()
        return resolved >= RETRAIN_THRESHOLD
    except Exception:
        return False
