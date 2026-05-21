from .generic import MoexStatsConnector


class MoexConnector(MoexStatsConnector):
    name = "moex"

    def parse_market_instruments(self, source, config):
        config = {
            **config,
            "max_items": int(config.get("max_items") or 200),
        }
        return super().parse_market_instruments(source, config)

    def parse_market_stats(self, source, config):
        config = {
            **config,
            "max_items": int(config.get("max_items") or 200),
        }
        return super().parse_market_stats(source, config)
