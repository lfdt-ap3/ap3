"""Custom exceptions for AP3 operations layer."""


class OperationError(Exception):
    """Base exception for all operation-related errors."""
    pass


class ProtocolError(OperationError):
    """Raised when a protocol execution error occurs."""
    
    def __init__(self, message: str, round_num: int | None = None):
        self.round_num = round_num
        if round_num is not None:
            super().__init__(f"Protocol error at round {round_num}: {message}")
        else:
            super().__init__(f"Protocol error: {message}")
