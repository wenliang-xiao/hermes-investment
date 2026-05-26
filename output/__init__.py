import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def get_feishu_writer():
    from investment_system.output.report_v6 import FeishuWriter
    return FeishuWriter()


def create_report_doc(title: str) -> str:
    w = get_feishu_writer()
    return w.create_doc(title)
