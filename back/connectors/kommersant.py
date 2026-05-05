from .generic import HtmlConnector


class KommersantConnector(HtmlConnector):
    name = "kommersant"

    def parse(self, source, config):
        config = {
            **config,
            "link_selector": "a[href^='/doc/'], a[href*='/doc/']",
            "url_contains": ["/doc/"],
            "text_selectors": [
                "article p",
                ".article_text_wrapper p",
                ".doc__text p",
                "main p",
            ],
            "max_links": 80,
        }
        return super().parse(source, config)
