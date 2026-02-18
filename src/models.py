import os
from datetime import datetime, timezone

from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, Text, Boolean
from sqlalchemy.orm import declarative_base, sessionmaker

DATABASE_URL = os.environ.get("DATABASE_URL")

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()


class PolymarketTrade(Base):
    __tablename__ = "polymarket_trades"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    market_id = Column(String(256), nullable=False)
    market_description = Column(Text, nullable=True)
    side = Column(String(10), nullable=False)
    amount_usdc = Column(Float, nullable=False)
    price = Column(Float, nullable=False)
    fair_prob = Column(Float, nullable=True)
    tx_hash = Column(String(256), nullable=True)
    status = Column(Text, nullable=False, default="pending")


class AgentBalance(Base):
    __tablename__ = "agent_balances"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    usdc_balance = Column(Float, nullable=False)
    note = Column(Text, nullable=True)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    action = Column(String(100), nullable=False)
    details = Column(Text, nullable=True)
    severity = Column(String(20), nullable=False, default="info")


class TradeHistory(Base):
    __tablename__ = "trade_history"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    market_id = Column(String(256), nullable=False)
    market_description = Column(Text, nullable=True)
    fair_prob = Column(Float, nullable=False)
    market_prob = Column(Float, nullable=False)
    side = Column(String(10), nullable=False)
    amount_usdc = Column(Float, nullable=False)
    edge = Column(Float, nullable=False)
    kelly_fraction = Column(Float, nullable=False)
    outcome = Column(String(20), nullable=True)
    profit = Column(Float, nullable=True)
    resolved = Column(Boolean, default=False)
    ml_adjusted_prob = Column(Float, nullable=True)


class MLModelMeta(Base):
    __tablename__ = "ml_model_meta"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    model_type = Column(String(100), nullable=False)
    n_samples = Column(Integer, nullable=False)
    accuracy = Column(Float, nullable=True)
    mae = Column(Float, nullable=True)
    notes = Column(Text, nullable=True)


def init_db():
    Base.metadata.create_all(engine)


def get_session():
    return SessionLocal()
