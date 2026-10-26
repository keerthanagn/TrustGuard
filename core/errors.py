"""Error hierarchy. System errors are kept distinct from factual verification failures."""


class TrustGuardError(Exception):
    """Base class for technical (system) failures."""

    component = "system"


class LLMUnavailableError(TrustGuardError):
    component = "llm"


class RetrievalError(TrustGuardError):
    component = "retrieval"


class VerifierError(TrustGuardError):
    component = "verification"


class SafetyError(TrustGuardError):
    component = "safety"


class InputValidationError(ValueError):
    """User-supplied input (question or file) failed validation."""
