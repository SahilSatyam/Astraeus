"""Stress scenario framework.

Provides the StressScenario ABC and four concrete scenarios:
- GFC2008Scenario: 2008 Global Financial Crisis (Sep 1 – Nov 30, 2008)
- COVID2020Scenario: COVID-19 crash (Feb 19 – Mar 23, 2020)
- RateShockScenario: +200bps parallel rate move
- FlashCrashScenario: May 6, 2010 Flash Crash (14:42–14:47 ET)
"""

from .base import StressContext, StressScenario
from .covid_2020 import COVID2020Scenario
from .flash_crash import FlashCrashScenario
from .gfc_2008 import GFC2008Scenario
from .rate_shock import RateShockScenario

__all__ = [
    "COVID2020Scenario",
    "FlashCrashScenario",
    "GFC2008Scenario",
    "RateShockScenario",
    "StressContext",
    "StressScenario",
]
