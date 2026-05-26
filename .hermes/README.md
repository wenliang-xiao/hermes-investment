# Hermes Investment System - Persistent Data Cache

This directory stores downloaded data (backtest results, factor score snapshots,
macro gate history) that can be reused across sessions by Sonnet 4.6.

## Contents

- backtest_results/ — JSON outputs from backtest runs
- factor_scores/ — Score snapshots saved by run_weekly.py (for future real-score backtests)
- macro_gate_history.json — Dual-gate state history

## Usage

Backtest loads from factor_scores/ first, fallback to D-lite+ reconstruction.
Macro gate loads from macro_gate_history.json first, fallback to CPI/PMI reconstruction.

