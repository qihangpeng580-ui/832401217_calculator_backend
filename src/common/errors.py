"""Central error definitions -- the single place in the back-end that decides
which error maps to which HTTP status code.

Why errors are defined in one place:
    1. The front-end gets error codes from a single source, so one meaning can
       never end up with two different codes.
    2. Adding an error means adding one class here; its HTTP status code comes
       for free and no "return 400" is scattered through business code.
    3. The front-end ui.js has a lookup table from error code to display message,
       and the ERROR_CODE values here must stay **in sync** with its keys.

Error codes at a glance (matching the front-end SERVER_ERROR_TEXT):

    INVALID_EXPRESSION    invalid expression (syntax error, illegal character,
                          unbalanced parentheses)  -> 400
    DIVISION_BY_ZERO      division by zero                                    -> 422
    EXPRESSION_TOO_LONG   expression too long                                 -> 413
    RECORD_NOT_FOUND      history record not found                            -> 404
    BAD_REQUEST           malformed request (not valid JSON, missing field)   -> 400
    INTERNAL_ERROR        internal server error                               -> 500
"""

from __future__ import annotations


class CalcError(Exception):
    """Base class for every business error.

    Attributes:
        error_code   machine-readable code for the front-end (it uses it to look up a message)
        message      user-facing explanation
        http_status  HTTP status code this error should be returned with

    Why the status code is attached to the exception instead of being decided
    where the exception is caught:
        Deciding at the catch site means a chain of isinstance checks that has
        to be edited for every new error type; attaching it to the exception
        keeps the mapping one-to-one by construction.
    """

    error_code: str = "INTERNAL_ERROR"
    http_status: int = 500

    def __init__(self, message: str = "") -> None:
        self.message = message or self.__class__.__doc__ or "Internal server error"
        super().__init__(self.message)

    def to_dict(self) -> dict:
        """Convert to the shape of the errors part of a response body (for the controller)."""
        return {"errorCode": self.error_code, "message": self.message}


class InvalidExpressionError(CalcError):
    """Invalid expression."""

    error_code = "INVALID_EXPRESSION"
    http_status = 400


class DivisionByZeroError(CalcError):
    """Division by zero."""

    error_code = "DIVISION_BY_ZERO"
    http_status = 422


class ExpressionTooLongError(CalcError):
    """Expression too long."""

    error_code = "EXPRESSION_TOO_LONG"
    http_status = 413


class RecordNotFoundError(CalcError):
    """History record not found."""

    error_code = "RECORD_NOT_FOUND"
    http_status = 404


class BadRequestError(CalcError):
    """Malformed request."""

    error_code = "BAD_REQUEST"
    http_status = 400
