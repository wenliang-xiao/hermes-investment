"""Tests for chain_evidence — 链定位 + Nick四问"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from research.chain_evidence import (
    guess_chain, get_chain_position, get_chain_map, get_nick_four,
    CHAINS, STOCK_CHAIN,
)


class TestGuessChain:
    def test_known_stock(self):
        assert guess_chain("300502") == "算力-AI"
        assert guess_chain("600519") == "消费"
        assert guess_chain("300750") == "新能源"

    def test_unknown_stock(self):
        assert guess_chain("999999") == ""

    def test_chain_count(self):
        assert len(CHAINS) >= 8


class TestChainPosition:
    def test_known_returns_position(self):
        pos = get_chain_position("300502")
        assert pos["chain"] == "算力-AI"
        assert pos["chain_name"] == "算力/AI基础设施"
        assert isinstance(pos["segment"], str)
        assert pos["segment"] in ["芯片", "光模块", "服务器", "PCB", "液冷"]
        assert pos["perez_stage"] == "expansion"

    def test_unknown_returns_empty(self):
        pos = get_chain_position("999999")
        assert pos["chain"] == ""

    def test_perez_label_exists(self):
        pos = get_chain_position("300502")
        assert "×" in pos["perez_label"]


class TestChainMap:
    def test_contains_all_chains(self):
        m = get_chain_map()
        assert set(m.keys()) == set(CHAINS.keys())

    def test_each_chain_has_stocks(self):
        m = get_chain_map()
        for cid, info in m.items():
            assert "stocks" in info
            assert "profit_pool" in info


class TestNickFour:
    def test_known_stock_returns_four_questions(self):
        nf = get_nick_four("300502", "新易盛")
        assert "q1_why_now" in nf
        assert "q2_why_company" in nf
        assert "q3_why_price" in nf
        assert "q4_when_wrong" in nf
        assert nf["chain"] == "算力-AI"
        assert "为什么是现在" in nf["q1_why_now"]["question"]
        assert len(nf["q4_when_wrong"]["risk_factors"]) > 0

    def test_unknown_returns_empty(self):
        nf = get_nick_four("999999")
        assert "error" in nf
        assert nf["error"] == "未知产业链"
