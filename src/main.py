"""
ENGINE Service Entry Point

Provides simple backtesting and orchestration over data and transformer services.
Endpoints:
  - /backtest: run a minimal MA-crossover backtest on daily data (default GC=F)
  - /signals: return last computed signals
"""

import os
import sys
from typing import Any, Dict, List, Optional

try:
	from framework.services.template import (
		start_template_service as _framework_start_template_service,
	)  # type: ignore
except Exception:  # pragma: no cover
	def _framework_start_template_service(*args, **kwargs):  # type: ignore
		print("[fks_engine.main] framework.services.template missing - starting simple Flask app")
		# Start a simple Flask app as fallback
		from flask import Flask, jsonify
		app = Flask(__name__)
		
		@app.route('/health', methods=['GET'])
		def health():
			return jsonify({"status": "healthy", "service": "fks-engine"})
		
		# Register custom endpoints
		custom_endpoints = _custom_endpoints()
		for route, func in custom_endpoints.items():
			app.add_url_rule(route, view_func=func, methods=['GET', 'POST'])
		
		port = int(os.getenv("ENGINE_SERVICE_PORT", "8003"))
		app.run(host="0.0.0.0", port=port, debug=False)


def _service_urls() -> Dict[str, str]:
	data_host = os.getenv("DATA_HOST", "data")
	data_port = os.getenv("DATA_PORT", "9001")
	transformer_host = os.getenv("TRANSFORMER_HOST", "transformer")
	transformer_port = os.getenv("TRANSFORMER_PORT", "8089")
	ollama_host = os.getenv("OLLAMA_HOST", "ollama")
	ollama_port = os.getenv("OLLAMA_PORT", "11434")
	api_host = os.getenv("API_HOST", "api")
	api_port = os.getenv("API_PORT", "8000")
	return {
		"data": f"http://{data_host}:{data_port}",
		"transformer": f"http://{transformer_host}:{transformer_port}",
		"ollama": f"http://{ollama_host}:{ollama_port}",
		"api": f"http://{api_host}:{api_port}",
	}


_last_signals: Dict[str, Any] = {}


def _custom_endpoints():
	try:
		import requests
		from flask import jsonify, request

		urls = _service_urls()

		def _ollama_generate(prompt: str, model: Optional[str] = None, timeout_sec: float = 8.0) -> Optional[str]:
			"""Call local Ollama generate endpoint directly for low-latency commentary.
			Returns generated text or None on error/timeout.
			"""
			try:
				model_name = model or os.getenv("OLLAMA_MODEL", "gpt-oss:20b")
				r = requests.post(
					f"{urls['ollama']}/api/generate",
					json={"model": model_name, "prompt": prompt, "stream": False},
					timeout=timeout_sec,
				)
				if r.ok:
					j = r.json()
					# Ollama returns { response: str, ... }
					txt = j.get("response") or j.get("content") or ""
					return str(txt)
			except Exception:
				pass
			return None

		def backtest():
			symbol = request.args.get("symbol", "GC=F")
			period = request.args.get("period", "2y")
			start = request.args.get("start")
			end = request.args.get("end")
			provider = request.args.get("provider")  # optional: yfinance|polygon|alpha|rithmic
			with_llm = str(request.args.get("with_llm", "0")).lower() in ("1", "true", "yes")

			# Fetch daily OHLCV from data service
			params = {"symbol": symbol}
			if start or end:
				if start:
					params["start"] = start
				if end:
					params["end"] = end
			else:
				params["period"] = period
			if provider:
				params["provider"] = provider

			try:
				r = requests.get(f"{urls['data']}/daily", params=params, timeout=15)
				r.raise_for_status()
				payload = r.json()
			except Exception as e:
				return jsonify({"ok": False, "error": f"data_service: {e}"}), 502

			rows: List[Dict[str, Any]] = payload.get("data") or []
			if not rows:
				return jsonify({"ok": False, "error": "no data"}), 400

			# Minimal MA crossover strategy
			closes = [float(x.get("close", 0)) for x in rows]
			dates = [x.get("date") for x in rows]

			def sma(series, w):
				out = []
				s = 0.0
				for i, v in enumerate(series):
					s += v
					if i >= w:
						s -= series[i - w]
					out.append(s / w if i >= w - 1 else None)
				return out

			fast, slow = sma(closes, 10), sma(closes, 20)
			pos = 0
			equity = 1.0
			trades = 0
			last_price = closes[0]
			signals = []
			for i in range(len(closes)):
				f, s = fast[i], slow[i]
				price = closes[i]
				date = dates[i]
				if f is None or s is None:
					continue
				# Crossovers
				if pos <= 0 and f > s:
					pos = 1
					trades += 1
					signals.append({"date": date, "action": "BUY", "price": price})
				elif pos >= 0 and f < s:
					pos = -1
					trades += 1
					signals.append({"date": date, "action": "SELL", "price": price})
				# Mark equity (very naive: mark-to-market long/short)
				ret = (price - last_price) / last_price if last_price else 0.0
				equity *= (1 + pos * ret)
				last_price = price

			# Call transformer predict with the close series
			tf_ok = False
			tf_info: Dict[str, Any] = {}
			try:
				payload_in = {"series": closes}
				tf = requests.post(
					f"{urls['transformer']}/predict",
					json=payload_in,
					timeout=20,
				)
				if tf.ok:
					j = tf.json()
					tf_ok = True
					tf_info = {
						"ok": bool(j.get("ok", False)),
						"shape": j.get("shape"),
						"window_used": j.get("window"),
						"horizon_pred": j.get("horizon_pred"),
						"device": j.get("device"),
						"y_tail": j.get("y_tail", [])[-3:],
						"regime_states_tail": j.get("regime_states_tail", []),
						"regime_last": j.get("regime_last"),
						"confidence": j.get("confidence"),
					}
				else:
					tf_ok = False
			except Exception:
				tf_ok = False

			result = {
				"ok": True,
				"symbol": symbol,
				"trades": trades,
				"equity": equity,
				"tf_ok": tf_ok,
				"transformer": tf_info,
				"n": len(rows),
				"last_date": rows[-1].get("date"),
				"signals_tail": signals[-5:],
			}

			_last_signals[symbol] = {"signals": signals, "summary": result}

			if with_llm:
				# Build a compact situational prompt to avoid latency
				regime = tf_info.get("regime_last") if isinstance(tf_info, dict) else None
				conf = tf_info.get("confidence") if isinstance(tf_info, dict) else None
				hc = tf_info.get("horizon_pred") if isinstance(tf_info, dict) else None
				prompt = (
					f"You are a concise trading assistant. Symbol {symbol}. "
					f"MA-crossover trades: {trades}. Equity multiple: {equity:.3f}. "
					f"Transformer ok: {tf_ok}. Regime(last): {regime}, confidence: {conf}. "
					f"Horizon pred: {hc}. In one short paragraph, provide a neutral risk-aware summary (no advice)."
				)
				txt = _ollama_generate(prompt)
				if txt:
					result["llm_comment"] = txt.strip()
			return jsonify(result)

		def forecast():
			"""Return transformer prediction info for a symbol using recent data."""
			symbol = request.args.get("symbol", "GC=F")
			period = request.args.get("period", "6mo")
			try:
				window = int(request.args.get("window", 64))
			except Exception:
				window = 64
			window = max(16, min(256, window))
			start = request.args.get("start")
			end = request.args.get("end")
			provider = request.args.get("provider")
			with_llm = str(request.args.get("with_llm", "0")).lower() in ("1", "true", "yes")

			# Build params for data service
			params = {"symbol": symbol}
			if start or end:
				if start:
					params["start"] = start
				if end:
					params["end"] = end
			else:
				params["period"] = period
			if provider:
				params["provider"] = provider

			try:
				r = requests.get(f"{urls['data']}/daily", params=params, timeout=15)
				r.raise_for_status()
				payload = r.json()
			except Exception as e:
				return jsonify({"ok": False, "error": f"data_service: {e}"}), 502

			rows: List[Dict[str, Any]] = payload.get("data") or []
			if not rows:
				return jsonify({"ok": False, "error": "no data"}), 400

			closes = [float(x.get("close", 0)) for x in rows]
			# Call transformer with a normalized summary similar to /backtest
			tf_ok = False
			tf_info: Dict[str, Any] = {}
			resp: Dict[str, Any] = {}
			try:
				tf = requests.post(
					f"{urls['transformer']}/predict",
					json={"series": closes, "window": window},
					timeout=20,
				)
				if tf.ok:
					j = tf.json()
					resp = j
					tf_ok = True
					# Extract a compact summary for downstream consumers
					tf_info = {
						"ok": bool(j.get("ok", False)),
						"shape": j.get("shape"),
						"window_used": j.get("window"),
						"horizon_pred": j.get("horizon_pred"),
						"device": j.get("device"),
						"y_tail": j.get("y_tail", [])[-3:],
						"regime_states_tail": j.get("regime_states_tail", []),
						"regime_last": j.get("regime_last"),
						"confidence": j.get("confidence"),
					}
				else:
					resp = {"ok": False, "status": tf.status_code}
			except Exception as e:
				resp = {"ok": False, "error": str(e)}

			result = {
				"ok": bool(resp.get("ok", False)),
				"symbol": symbol,
				"n": len(rows),
				"last_date": rows[-1].get("date"),
				"window": window,
				"tf_ok": tf_ok,
				"transformer": tf_info,
				"transformer_raw": resp,
			}

			# Cache minimal signals context for quick retrieval
			_last_signals[symbol] = {
				"signals": [],
				"summary": result,
			}

			if with_llm:
				regime = tf_info.get("regime_last") if isinstance(tf_info, dict) else None
				conf = tf_info.get("confidence") if isinstance(tf_info, dict) else None
				hc = tf_info.get("horizon_pred") if isinstance(tf_info, dict) else None
				prompt = (
					f"You are a concise trading assistant. Symbol {symbol}. Recent window: {window}. "
					f"Transformer ok: {tf_ok}. Regime(last): {regime}, confidence: {conf}. "
					f"Horizon pred: {hc}. Provide a brief risk-aware summary in 2-3 sentences."
				)
				txt = _ollama_generate(prompt)
				if txt:
					result["llm_comment"] = txt.strip()

			return jsonify(result)


		def signals():
			"""Return last computed signals; supports ?symbol= and ?limit= for concise views."""
			from flask import request
			sym = request.args.get("symbol")
			try:
				limit = int(request.args.get("limit", 10))
			except Exception:
				limit = 10
			limit = max(1, min(1000, limit))

			if sym:
				entry = _last_signals.get(sym)
				if not entry:
					return jsonify({"ok": False, "error": "no signals for symbol", "symbol": sym}), 404
				# Build compact view with tail and transformer summary
				signals_tail = entry.get("signals", [])[-limit:]
				summary = entry.get("summary", {})
				tf = summary.get("transformer", {}) if isinstance(summary, dict) else {}
				resp = {
					"ok": True,
					"symbol": sym,
					"signals_tail": signals_tail,
					"trades": summary.get("trades"),
					"equity": summary.get("equity"),
					"last_date": summary.get("last_date"),
					"n": summary.get("n"),
					"transformer": {
						"ok": bool(tf.get("ok", False)),
						"shape": tf.get("shape"),
						"horizon_pred": tf.get("horizon_pred"),
						"device": tf.get("device"),
						"window_used": tf.get("window_used"),
						"regime_last": tf.get("regime_last"),
						"confidence": tf.get("confidence"),
					},
				}
				return jsonify(resp)
			else:
				# Full map; but trim tails for each symbol for readability
				out: Dict[str, Any] = {}
				for k, v in _last_signals.items():
					vv = dict(v)
					vv["signals"] = vv.get("signals", [])[-limit:]
					out[k] = vv
				return jsonify(out)

		return {"/backtest": backtest, "/signals": signals, "/forecast": forecast}
	except Exception:
		return {}


def start_engine(service_name: str | None = None, service_port: int | str | None = None):
	print("[fks_engine.main] start_engine called")
	if service_name:
		os.environ["ENGINE_SERVICE_NAME"] = str(service_name)
	if service_port is not None:
		os.environ["ENGINE_SERVICE_PORT"] = str(service_port)

	name = os.getenv("ENGINE_SERVICE_NAME", "engine")
	port = int(os.getenv("ENGINE_SERVICE_PORT", "4300"))
	print(f"[fks_engine.main] Starting {name} on port {port}")
	start_template_service(service_name=name, service_port=port)


def start_template_service(
	service_name: str | None = None, service_port: int | str | None = None
):
	"""Wrapper to register custom endpoints when the runner calls template function.

	The enhanced runner often finds a function named 'start_template_service' in the
	service module and calls it with (service_name, service_port). If we imported the
	framework function directly, custom endpoints would be lost. This wrapper forwards
	to the framework with our _custom_endpoints.
	"""
	if service_name:
		os.environ["ENGINE_SERVICE_NAME"] = str(service_name)
	if service_port is not None:
		os.environ["ENGINE_SERVICE_PORT"] = str(service_port)

	name = os.getenv("ENGINE_SERVICE_NAME", "engine")
	port = int(os.getenv("ENGINE_SERVICE_PORT", "9010"))
	_framework_start_template_service(
		service_name=name, service_port=port, custom_endpoints=_custom_endpoints()
	)


def main():
	print("[fks_engine.main] Starting fks_engine service...")
	start_engine()
	return 0


if __name__ == "__main__":
	sys.exit(main())
