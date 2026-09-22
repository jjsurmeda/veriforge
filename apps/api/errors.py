"""Domain error shape (docs/conventions/python.md): one base, typed per package.

Every domain error carries the wire body {"error_code", "message", "detail"};
FastAPI exception handlers in main.py do the JSON translation once.
"""


class AppError(Exception):
    status_code = 400

    def __init__(
        self,
        error_code: str,
        message: str,
        detail: object = None,
        *,
        status_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.message = message
        self.detail = detail
        if status_code is not None:
            self.status_code = status_code
