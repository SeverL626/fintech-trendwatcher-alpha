from .generic import RssConnector


class CbrConnector(RssConnector):
    name = "cbr"

    def parse(self, source, config):
        config = {
            **config,
            "text_selectors": [
                "article p",
                "main p",
                ".landing-text p",
                ".news_detail p",
            ],
            "fetch_article_text": False,
        }
        return super().parse(source, config)
