"""Exception types raised by SkillBench."""


class SkillBenchError(Exception):
    """Base class for all SkillBench errors with a user-facing message."""


class SuiteLoadError(SkillBenchError):
    """Raised when a test suite file cannot be loaded or validated."""


class AdapterError(SkillBenchError):
    """Raised when a model adapter fails (missing config, network, bad response)."""
