"""Retrieval domain errors (python.md: typed exceptions in the owning package)."""

from errors import AppError


class RetrievalTimeout(AppError):
    status_code = 504

    def __init__(self) -> None:
        super().__init__(
            "retrieval_timeout",
            "The retrieval query exceeded its statement timeout",
        )
