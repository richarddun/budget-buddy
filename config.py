"""
Global configuration for the Budget Buddy app.

Set BASE_PATH to the subpath where the app is served behind a reverse proxy
(e.g., '/budget-buddy'). Leave it as an empty string for root deployment ('/').

This module centralizes configuration instead of relying solely on env vars.
"""

# Example: BASE_PATH = "/budget-buddy"
BASE_PATH = "/budget-buddy"

# Feature flags
# Optional Monte Carlo forecast endpoint; disabled by default.
MONTE_CARLO_ENABLED = False

# Monte Carlo defaults/limits when enabled
MONTE_CARLO_MAX_ITER = 2000
MONTE_CARLO_DEFAULT_ITER = 300
MONTE_CARLO_DEFAULT_SEED = 1337

# Currency settings
# Default currency symbol for UI formatting
CURRENCY_SYMBOL = "€"

# Optional salary detection heuristics (not yet wired in UI)
# Day of month for salary (1-31). If set to 0, disabled.
SALARY_DOM = 28
# Minimum inflow in cents to consider a salary checkpoint.
SALARY_MIN_CENTS = 200000
