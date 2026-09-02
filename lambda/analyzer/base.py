"""
analyzer/base.py

The contract every analyzer has to satisfy. One method, one input, one
output - deliberately small, because the smaller this interface is, the
easier it is to trust that swapping mock -> bedrock changes nothing else
about the system's behavior around it (logging, the policy gate, Slack
formatting all stay identical).
"""
from abc import ABC, abstractmethod

from models import Diagnosis, Incident


class IncidentAnalyzer(ABC):
    @abstractmethod
    def analyze(self, incident: Incident) -> Diagnosis:
        """Given a parsed Incident, return a Diagnosis. Must not raise for a
        pattern it doesn't recognize - return a low-confidence
        manual_investigation Diagnosis instead (see MockAnalyzer's
        _FALLBACK). A crashing analyzer would take down the one thing that's
        supposed to be reliable when everything else is on fire."""
        raise NotImplementedError
