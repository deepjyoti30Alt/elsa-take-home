"""Domain errors translated to API errors by the delivery layer."""


class DomainError(Exception):
    """Base class for expected business-rule failures."""


class InvalidJoinError(DomainError):
    """Raised when a guest display name or idempotency key is invalid."""


class QuizNotFoundError(DomainError):
    """Raised when a requested quiz does not exist."""


class QuizUnavailableError(DomainError):
    """Raised when a quiz no longer accepts new participants."""
