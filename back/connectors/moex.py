from .generic import MoexStatsConnector


class MoexConnector(MoexStatsConnector):
    name = "moex"

    def parse_market_stats(self, source, config):
        config = {
            **config,
            "max_items": 200,
        }
        return super().parse_market_stats(source, config)
