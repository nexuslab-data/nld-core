from nld.utils import NldStrEnum


class ExecutionFrequency(NldStrEnum):
    """Cadence at which a scheduled asset is intended to be executed.

    This is declared metadata, never inferred from the trigger: a
    flow-triggered asset carries no cron at all, and a cron only says when a
    run fires, not the cadence the asset is meant to deliver to its consumers.
    Reporting therefore reads this attribute, not the schedule syntax.

    ``INTRADAY`` means several runs a day but coarser than hourly (every few
    hours). ``ON_DEMAND`` means no intended cadence: the asset runs when it is
    asked to, so it is excluded from cadence comparisons.
    """

    CONTINUOUS = "continuous"
    HOURLY = "hourly"
    INTRADAY = "intraday"
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    YEARLY = "yearly"
    ON_DEMAND = "on_demand"

    @property
    def cadence_rank(self) -> int | None:
        """Rank ascending from the most frequent cadence, None when cadence-less."""
        return _CADENCE_RANKS.get(self)

    def is_more_frequent_than(self, other: "ExecutionFrequency") -> bool:
        """Whether this cadence delivers more often than another one.

        A cadence-less frequency (``ON_DEMAND``) never compares, so the answer
        is False as soon as either side has no rank.
        """
        own_rank = self.cadence_rank
        other_rank = other.cadence_rank
        if own_rank is None or other_rank is None:
            return False
        return own_rank < other_rank


_CADENCE_RANKS: dict[ExecutionFrequency, int] = {
    ExecutionFrequency.CONTINUOUS: 0,
    ExecutionFrequency.HOURLY: 1,
    ExecutionFrequency.INTRADAY: 2,
    ExecutionFrequency.DAILY: 3,
    ExecutionFrequency.WEEKLY: 4,
    ExecutionFrequency.MONTHLY: 5,
    ExecutionFrequency.QUARTERLY: 6,
    ExecutionFrequency.YEARLY: 7,
}


def coarsest_frequency(
    frequencies: list[ExecutionFrequency],
) -> ExecutionFrequency | None:
    """Return the least frequent cadence of a set, ignoring cadence-less ones."""
    ranked = [
        frequency for frequency in frequencies if frequency.cadence_rank is not None
    ]
    if not ranked:
        return None
    return max(ranked, key=lambda frequency: frequency.cadence_rank or 0)
