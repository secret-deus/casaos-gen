"""Custom exception hierarchy for casaos-gen."""


class CasaOSGenError(Exception):
    """Base exception for the casaos-gen package."""


class ComposeParseError(CasaOSGenError, ValueError):
    """Raised when a compose file cannot be parsed or is structurally invalid."""


class ParamsError(CasaOSGenError, ValueError):
    """Raised when params input is invalid."""


class LLMError(CasaOSGenError):
    """Base for LLM-related errors."""


class LLMUnavailableError(LLMError, RuntimeError):
    """Raised when the LLM client cannot be initialized."""


class LLMResponseError(LLMError, ValueError):
    """Raised when the LLM returns an unparseable or invalid response."""


class VersionError(CasaOSGenError):
    """Raised for version management issues (invalid filename, missing file)."""
