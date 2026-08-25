"""
AMR Guardian Enterprise - FastAPI Application
FastAPI 0.111+ REST API exposing surveillance endpoints, audit trails, metrics, and chat.
"""

from fastapi import FastAPI, HTTPException, Depends, Query, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone
import uuid

from agents.base import PHIGuard, SecurityException, AuditLogger
from agents.models import (
    PatientSchema,
    StewardshipAlertSchema,
    CultureIsolateSchema,
    MedicationOrderSchema,
    AuditEventSchema,
)
from agents.supervisor import AMRSupervisor
from agents.llm_factory import LLMFactory

app = FastAPI(
    title="AMR Guardian Enterprise API",
    description="Production-grade Autonomous Antimicrobial Resistance & Stewardship Intelligence Platform",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global In-Memory Supervisor Instance
supervisor = AMRSupervisor(llm_provider=LLMFactory.get_provider("mock"))


class ChatRequest(BaseModel):
    query: str = Field(..., description="Clinical inquiry string")
    patient_id: Optional[str] = Field(None, description="Optional patient context ID")


class ChatResponse(BaseModel):
    query: str
    context_patient: Optional[str]
    response: str
    status: str
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class AuditResponse(BaseModel):
    patient_id: str
    alerts_count: int
    alerts: List[StewardshipAlertSchema]
    nhsn_summary: Dict[str, Any]


@app.get("/health", tags=["System"])
def health_check():
    """Health check endpoint confirming API liveness and engine readiness."""
    return {
        "status": "HEALTHY",
        "service": "amr-guardian-enterprise",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "registered_patients": len(supervisor.patients),
        "phi_guard": "ACTIVE_ENFORCING",
        "audit_crypto": "HMAC-SHA256_ENABLED"
    }


@app.get("/metrics", tags=["Surveillance Metrics"])
def get_metrics():
    """Returns NHSN Antimicrobial Use & Resistance surveillance metrics and SAAR proxies."""
    return supervisor.calculate_nhsn_metrics()


@app.post("/api/patients", response_model=PatientSchema, status_code=status.HTTP_201_CREATED, tags=["Patients"])
def register_patient(patient: PatientSchema):
    """Registers a new patient with culture isolates and active medication orders."""
    try:
        # Assert no direct PHI in string fields
        PHIGuard.assert_no_phi(patient.anonymous_id)
        PHIGuard.assert_no_phi(patient.location)
        for iso in patient.isolates:
            PHIGuard.assert_no_phi(iso.organism_name)
        for ordr in patient.orders:
            PHIGuard.assert_no_phi(ordr.antibiotic_name)

        supervisor.register_patient(patient)
        return patient
    except SecurityException as se:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(se))


@app.get("/api/patients", response_model=List[PatientSchema], tags=["Patients"])
def list_patients():
    """Retrieves all registered surveillance patients."""
    return list(supervisor.patients.values())


@app.get("/api/patients/{patient_id}", response_model=PatientSchema, tags=["Patients"])
def get_patient(patient_id: str):
    """Retrieves patient details by ID."""
    if patient_id not in supervisor.patients:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Patient not found")
    return supervisor.patients[patient_id]


@app.post("/api/patients/audit", response_model=AuditResponse, tags=["Surveillance Engine"])
def run_patient_audit(patient_id: Optional[str] = Query(None, description="Optional patient ID to audit specifically")):
    """
    Triggers multi-worker AMR surveillance across patients to identify:
    1. Bug-Drug Mismatches
    2. Spectrum De-escalation Opportunities
    3. Renal Dosing & Toxicity Limits
    """
    try:
        alerts = supervisor.run_full_surveillance(patient_id=patient_id)
        metrics = supervisor.calculate_nhsn_metrics()
        return AuditResponse(
            patient_id=patient_id or "ALL",
            alerts_count=len(alerts),
            alerts=alerts,
            nhsn_summary=metrics,
        )
    except SecurityException as se:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Security/PHI Guard Violation: {str(se)}")
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@app.post("/api/chat", response_model=ChatResponse, tags=["Clinical Assistant"])
def chat_clinical_assistant(req: ChatRequest):
    """
    Infectious Diseases conversational decision support endpoint with PHI guard verification.
    """
    try:
        res = supervisor.chat_query(query=req.query, context_patient_id=req.patient_id)
        return ChatResponse(
            query=res["query"],
            context_patient=res["context_patient"],
            response=res["response"],
            status=res["status"],
        )
    except SecurityException as se:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"PHI Blocked: {str(se)}")
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))
