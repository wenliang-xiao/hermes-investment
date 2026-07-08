# Bridge — use news/ module instead (replaced deprecated _archive/news_engine.py)
# For backward compat, this still works but prefer: from news.pipeline import NewsPipeline
from _archive.news_engine import *
from _archive.news_engine import get_news_with_impact, _calc_sentiment_score, classify_impact
