from .generic import RssConnector


class VedomostiConnector(RssConnector):
    name = "vedomosti"

    def parse(self, source, config):
        config = {
            **config,
            "text_selectors": [
                "article p",
                ".article__content p",
                ".box-paragraph__text",
            ],
            "fetch_article_text": True,
        }
        return super().parse(source, config)
