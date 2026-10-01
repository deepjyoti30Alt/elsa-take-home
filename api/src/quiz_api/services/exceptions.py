"""Domain errors translated to API errors by the delivery layer."""


class DomainError(Exception):
    """Base class for expected business-rule failures."""


class InvalidJoinError(DomainError):
    """Raised when a guest display name or idempotency key is invalid."""


class QuizNotFoundError(DomainError):
    """Raised when a requested quiz does not exist."""


class QuizUnavailableError(DomainError):
    """Raised when a quiz no longer accepts new participants."""


class ParticipantNotFoundError(DomainError):
    """Raised when a quiz-scoped participant does not exist."""


class RoundNotFoundError(DomainError):
    """Raised when a requested round does not belong to a quiz."""


class RoundNotOpenError(DomainError):
    """Raised when an answer arrives outside a round's open window."""


class DuplicateAnswerError(DomainError):
    """Raised when a participant has already answered a quiz round."""
