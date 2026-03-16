class AppException(Exception):
    """Base exception for all application exceptions."""

    def __init__(self, message: str):
        self.message = message
        super().__init__(self.message)


class NotFoundError(AppException):
    """Exception raised when a resource is not found (HTTP 404)."""

    def __init__(self, message: str = "Resource not found"):
        super().__init__(message)


class ForbiddenError(AppException):
    """Exception raised for HTTP 403 Forbidden errors."""

    def __init__(self, message: str = "Access is denied"):
        super().__init__(message)


class UnauthorizedError(AppException):
    """Exception raised for HTTP 401 Unauthorized errors."""

    def __init__(self, message: str = "Authentication required"):
        super().__init__(message)


class ValidationError(AppException):
    """Exception raised for HTTP 400 Bad Request errors (validation failures)."""

    def __init__(self, message: str = "Validation error"):
        super().__init__(message)


class ConflictError(AppException):
    """Exception raised for HTTP 409 Conflict errors (resource conflicts)."""

    def __init__(self, message: str = "Resource conflict"):
        super().__init__(message)


class UserNotFoundSignupRequiredError(AppException):
    """Exception raised when a user is not found and signup is required.

    For Firebase auth, carries Firebase user info to pre-fill signup form.
    """

    def __init__(
        self,
        message: str = "User not found: Signup is required",
        firebase_email: str | None = None,
        firebase_name: str | None = None,
        firebase_provider: str | None = None,
    ):
        super().__init__(message)
        self.firebase_email = firebase_email
        self.firebase_name = firebase_name
        self.firebase_provider = firebase_provider
