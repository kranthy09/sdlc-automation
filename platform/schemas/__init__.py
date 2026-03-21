"""
platform.schemas — public API for all Layer 1 schema types.

Import from here in tests and in agents/modules/api layers.
Never import directly from sub-modules outside of platform/schemas/ itself.
"""

from .base import PlatformModel
from .errors import ParseError, RetrievalError, UnsupportedFormatError
from .events import (
    ClassificationEvent,
    CompleteEvent,
    ErrorEvent,
    PhaseStartEvent,
    ProgressEvent,
    StepProgressEvent,
)
from .fitment import (
    ClassificationResult,
    FitLabel,
    MatchResult,
    RouteLabel,
    ValidatedFitmentBatch,
)
from .guardrails import FileValidationResult, InjectionScanResult
from .product import ProductConfig
from .requirement import (
    D365Module,
    FlaggedAtom,
    RawUpload,
    RequirementAtom,
    ValidatedAtom,
)
from .retrieval import (
    AssembledContext,
    DocReference,
    PriorFitment,
    RankedCapability,
    RetrievalQuery,
)

__all__ = [
    # base
    "PlatformModel",
    # errors
    "ParseError",
    "RetrievalError",
    "UnsupportedFormatError",
    # guardrails
    "FileValidationResult",
    "InjectionScanResult",
    # events
    "ClassificationEvent",
    "CompleteEvent",
    "ErrorEvent",
    "PhaseStartEvent",
    "ProgressEvent",
    "StepProgressEvent",
    # fitment
    "ClassificationResult",
    "FitLabel",
    "MatchResult",
    "RouteLabel",
    "ValidatedFitmentBatch",
    # product
    "ProductConfig",
    # requirement
    "D365Module",
    "FlaggedAtom",
    "RawUpload",
    "RequirementAtom",
    "ValidatedAtom",
    # retrieval
    "AssembledContext",
    "DocReference",
    "PriorFitment",
    "RankedCapability",
    "RetrievalQuery",
]
