"""
AMR Guardian Enterprise - Data Models & SQLAlchemy ORM
Defines Pydantic v2 schemas and SQLAlchemy 2.0 ORM models for antimicrobial stewardship.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Optional, Any
from pydantic import BaseModel, Field, ConfigDict
from sqlalchemy import (
    Column,
    String,
    Float,
    Integer,
    Boolean,
    DateTime,
    Text,
    JSON,
    ForeignKey,
    create_engine,
)
from sqlalchemy.orm import declarative_base, relationship, sessionmaker

Base = declarative_base()


# --- Enums ---

class AlertSeverity(str, Enum):
    INFO = "INFO"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class AlertCategory(str, Enum):
    BUG_DRUG_MISMATCH = "BUG_DRUG_MISMATCH"
    DEESCALATION_OPPORTUNITY = "DEESCALATION_OPPORTUNITY"
    RENAL_DOSE_ADJUSTMENT = "RENAL_DOSE_ADJUSTMENT"
    TOXICITY_LIMIT_EXCEEDED = "TOXICITY_LIMIT_EXCEEDED"
    DUPLICATE_THERAPY = "DUPLICATE_THERAPY"


class SusceptibilityResult(str, Enum):
    SUSCEPTIBLE = "S"
    INTERMEDIATE = "I"
    RESISTANT = "R"
    NOT_TESTED = "NT"


class AlertStatus(str, Enum):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    RESOLVED = "RESOLVED"


# --- SQLAlchemy Database Models ---

class PatientModel(Base):
    __tablename__ = "patients"

    id = Column(String(64), primary_key=True, index=True)
    anonymous_id = Column(String(64), unique=True, index=True)  # Safe Harbor de-identified token
    age = Column(Integer, nullable=False)
    gender = Column(String(16), nullable=False)
    weight_kg = Column(Float, nullable=False)
    serum_creatinine = Column(Float, nullable=False)  # mg/dL
    crcl_ml_min = Column(Float, nullable=False)  # Calculated Cockcroft-Gault
    location = Column(String(64), default="ICU-Main")
    admission_date = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    isolates = relationship("CultureIsolateModel", back_populates="patient", cascade="all, delete-orphan")
    orders = relationship("MedicationOrderModel", back_populates="patient", cascade="all, delete-orphan")
    alerts = relationship("StewardshipAlertModel", back_populates="patient", cascade="all, delete-orphan")


class CultureIsolateModel(Base):
    __tablename__ = "culture_isolates"

    id = Column(String(64), primary_key=True, index=True)
    patient_id = Column(String(64), ForeignKey("patients.id"), nullable=False)
    specimen_source = Column(String(64), nullable=False)  # e.g., Blood, Sputum, Urine
    collection_time = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    organism_name = Column(String(128), nullable=False)  # e.g., Staphylococcus aureus, Pseudomonas aeruginosa
    antibiogram = Column(JSON, default=dict)  # e.g., {"Vancomycin": "S", "Oxacillin": "R", "Meropenem": "S"}
    is_final = Column(Boolean, default=True)

    patient = relationship("PatientModel", back_populates="isolates")


class MedicationOrderModel(Base):
    __tablename__ = "medication_orders"

    id = Column(String(64), primary_key=True, index=True)
    patient_id = Column(String(64), ForeignKey("patients.id"), nullable=False)
    antibiotic_name = Column(String(128), nullable=False)  # e.g., Vancomycin, Meropenem
    dose = Column(String(64), nullable=False)  # e.g., 1000 mg
    frequency = Column(String(64), nullable=False)  # e.g., q12h
    route = Column(String(32), default="IV")
    start_time = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    day_of_therapy = Column(Integer, default=1)
    status = Column(String(32), default="ACTIVE")

    patient = relationship("PatientModel", back_populates="orders")


class StewardshipAlertModel(Base):
    __tablename__ = "stewardship_alerts"

    id = Column(String(64), primary_key=True, index=True)
    patient_id = Column(String(64), ForeignKey("patients.id"), nullable=False)
    category = Column(String(64), nullable=False)
    severity = Column(String(32), default="HIGH")
    headline = Column(String(256), nullable=False)
    rationale = Column(Text, nullable=False)
    recommended_action = Column(Text, nullable=False)
    evidence_basis = Column(JSON, default=dict)
    status = Column(String(32), default="PENDING")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    patient = relationship("PatientModel", back_populates="alerts")


class AuditEventModel(Base):
    __tablename__ = "audit_events"

    id = Column(String(64), primary_key=True, index=True)
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    actor = Column(String(128), nullable=False)
    action = Column(String(128), nullable=False)
    details = Column(Text, nullable=False)
    signature = Column(String(128), nullable=False)


# --- Pydantic v2 Schemas ---

class CultureIsolateSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    patient_id: str
    specimen_source: str
    collection_time: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    organism_name: str
    antibiogram: Dict[str, SusceptibilityResult] = Field(default_factory=dict)
    is_final: bool = True


class MedicationOrderSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    patient_id: str
    antibiotic_name: str
    dose: str
    frequency: str
    route: str = "IV"
    start_time: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    day_of_therapy: int = 1
    status: str = "ACTIVE"


class StewardshipAlertSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    patient_id: str
    category: AlertCategory
    severity: AlertSeverity
    headline: str
    rationale: str
    recommended_action: str
    evidence_basis: Dict[str, Any] = Field(default_factory=dict)
    status: AlertStatus = AlertStatus.PENDING
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class PatientSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    anonymous_id: str
    age: int
    gender: str
    weight_kg: float
    serum_creatinine: float
    crcl_ml_min: float
    location: str = "ICU-Main"
    admission_date: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    isolates: List[CultureIsolateSchema] = Field(default_factory=list)
    orders: List[MedicationOrderSchema] = Field(default_factory=list)
    alerts: List[StewardshipAlertSchema] = Field(default_factory=list)


class AuditEventSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    timestamp: datetime
    actor: str
    action: str
    details: str
    signature: str


# --- Database Engine and Session Factory ---

def get_engine(db_url: str = "sqlite:///:memory:"):
    return create_engine(db_url, connect_args={"check_same_thread": False} if "sqlite" in db_url else {})


def init_db(engine):
    Base.metadata.create_all(bind=engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)
