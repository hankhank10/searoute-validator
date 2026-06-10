"""Sea Route Validator application package.

Core functions are importable directly::

    from searoute_validator import validate_leg, validate_route, is_on_land
"""
from .api import LegResult, is_on_land, validate_leg, validate_route

__all__ = ["validate_leg", "validate_route", "is_on_land", "LegResult"]
