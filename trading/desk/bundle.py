"""Everything the agents may look at, gathered once. Agents never fetch data
themselves, so every run is reproducible from the bundle's inputs."""

import datetime
from dataclasses import dataclass, field

from sim.vendor_bridge import news as vendor_news


@dataclass
class Bundle:
    plan: dict                  # normalized plan (vendor shape)
    market: object              # sim.data.Market
    sim: dict                   # sim.run.run_sim document
    trader_cfg: dict            # risk / budget limits (trader/config.json)
    desk_cfg: dict
    now_utc: datetime.datetime  # naive UTC, the run's clock
    news: list = None           # vendor news items, None = could not be read
    news_error: str = None
    extras: dict = field(default_factory=dict)

    @property
    def long(self):
        return self.plan["side"] == "buy"

    @property
    def now_aware(self):
        return self.now_utc.replace(tzinfo=datetime.timezone.utc)


def load_news(symbol, now_utc, hours, rss_bytes=None, fetch=False):
    """(items, error). Items are vendor-tagged headlines published in (now - hours, now]."""
    nm = vendor_news()
    try:
        if rss_bytes is None:
            if not fetch:
                return None, "haber kaynağı verilmedi"
            rss_bytes = nm.Fetcher().get(nm.YAHOO % nm.yahoo_symbol(symbol), "yahoo-%s.xml" % symbol)
        items = nm.tag(nm.parse_rss(rss_bytes, symbol), {symbol: None})
    except nm.NewsError as e:
        return None, str(e)
    now = now_utc.replace(tzinfo=datetime.timezone.utc)
    lo = now - datetime.timedelta(hours=hours)
    keep = [it for it in items if it["time"] is not None and lo < it["time"] <= now]
    keep.sort(key=lambda it: it["time"], reverse=True)
    return keep, None
