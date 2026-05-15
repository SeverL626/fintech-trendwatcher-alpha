from .base import NotImplementedConnector
from .generic import HtmlConnector, RssConnector
from .alfabank import AlfabankConnector
from .cbr import CbrConnector, CbrNewsConnector
from .kommersant import KommersantConnector
from .minfin import MinfinConnector
from .moex import MoexConnector
from .nalog import NalogConnector
from .koreaherald import KoreaheraldConnector
from .fedsfm import FedsfmConnector
from .deloitte import DeloitteInsightsConnector
from .rbc import RbcConnector
from .rosstat import RosstatConnector
from .sber import SberConnector
from .tbank import TbankConnector
from .telegram import TelegramConnector
from .vedomosti import VedomostiConnector
from .vtb import VtbConnector


CONNECTORS = {
    "rss": RssConnector,
    "html": HtmlConnector,
    "rbc": RbcConnector,
    "cbr": CbrConnector,
    "cbr_news": CbrNewsConnector,
    "minfin": MinfinConnector,
    "rosstat": RosstatConnector,
    "moex": MoexConnector,
    "alfabank": AlfabankConnector,
    "sber": SberConnector,
    "tbank": TbankConnector,
    "telegram": TelegramConnector,
    "vtb": VtbConnector,
    "vedomosti": VedomostiConnector,
    "kommersant": KommersantConnector,
    "nalog": NalogConnector,
    "koreaherald": KoreaheraldConnector,
    "fedsfm": FedsfmConnector,
    "deloitte_insights": DeloitteInsightsConnector,
}


def get_connector(name):
    connector_factory = CONNECTORS.get(name)
    if not connector_factory:
        return NotImplementedConnector(name)
    return connector_factory()
