"""Behavioral + BIDS event-generation pipeline for r01network."""
from network_events.identity import AuditResult, BehaviorException, RunIdentity, audit_dataset

__version__ = "0.1.0"

__all__ = ["AuditResult", "BehaviorException", "RunIdentity", "audit_dataset"]
