"""Engine service implementation (flattened, deduplicated)."""
import os, sys
from typing import Any, Dict, List, Optional

try:
    from framework.services.template import (
        start_template_service as _framework_start_template_service,
    )  # type: ignore
except Exception:  # pragma: no cover
    def _framework_start_template_service(*args, **kwargs):  # type: ignore
        print("[fks_engine._impl] framework.services.template missing - noop fallback")


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


def _custom_endpoints():  # noqa: C901
    try:
        import requests
        from flask import jsonify, request

        urls = _service_urls()

        def _ollama_generate(prompt: str, model: Optional[str] = None, timeout_sec: float = 8.0) -> Optional[str]:
            try:
                model_name = model or os.getenv("OLLAMA_MODEL", "gpt-oss:20b")
                r = requests.post(
                    f"{urls['ollama']}/api/generate",
                    json={"model": model_name, "prompt": prompt, "stream": False},
                    timeout=timeout_sec,
                )
                if r.ok:
                    j = r.json()
                    return str(j.get("response") or j.get("content") or "")
            except Exception:
                pass
            return None

        def backtest():  # simplified copy of original
            symbol = request.args.get("symbol", "GC=F")
            period = request.args.get("period", "2y")
            with_llm = str(request.args.get("with_llm", "0")).lower() in ("1", "true", "yes")
            params = {"symbol": symbol, "period": period}
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
            dates = [x.get("date") for x in rows]
            def sma(series, w):
                out=[];s=0.0
                for i,v in enumerate(series):
                    s+=v
                    if i>=w: s-=series[i-w]
                    out.append(s / w if i>=w-1 else None)
                return out
            fast, slow = sma(closes,10), sma(closes,20)
            pos=0; equity=1.0; trades=0; last_price=closes[0]; signals=[]
            for i in range(len(closes)):
                f, s = fast[i], slow[i]
                price = closes[i]
                if f is None or s is None: continue
                if pos <=0 and f> s: pos=1; trades+=1; signals.append({"date":dates[i],"action":"BUY","price":price})
                elif pos >=0 and f< s: pos=-1; trades+=1; signals.append({"date":dates[i],"action":"SELL","price":price})
                ret=(price-last_price)/last_price if last_price else 0.0
                equity *= (1 + pos*ret)
                last_price=price
            result={"ok":True,"symbol":symbol,"trades":trades,"equity":equity,"n":len(rows),"last_date":rows[-1].get("date"),"signals_tail":signals[-5:]}
            _last_signals[symbol]={"signals":signals,"summary":result}
            if with_llm:
                txt=_ollama_generate(f"Symbol {symbol} Trades {trades} Equity {equity:.3f} Provide brief neutral summary.")
                if txt: result["llm_comment"]=txt.strip()
            return jsonify(result)

        def signals():
            from flask import request
            sym=request.args.get("symbol")
            if sym:
                entry=_last_signals.get(sym)
                if not entry:
                    return jsonify({"ok":False,"error":"no signals","symbol":sym}),404
                sig=entry.get("signals", [])[-5:]
                summ=entry.get("summary", {})
                return jsonify({"ok":True,"symbol":sym,"signals":sig,"summary":summ})
            out={k:{"signals":v.get("signals", [])[-5:],"summary":v.get("summary", {})} for k,v in _last_signals.items()}
            return jsonify(out)

        return {"/backtest": backtest, "/signals": signals}
    except Exception:
        return {}


def start_engine(service_name: str | None = None, service_port: int | str | None = None):
    if service_name:
        os.environ["ENGINE_SERVICE_NAME"] = str(service_name)
    if service_port is not None:
        os.environ["ENGINE_SERVICE_PORT"] = str(service_port)
    name = os.getenv("ENGINE_SERVICE_NAME", "engine")
    # Prefer explicit ENGINE_SERVICE_PORT, then generic SERVICE_PORT, fallback 8003
    port = int(os.getenv("ENGINE_SERVICE_PORT") or os.getenv("SERVICE_PORT", "8003"))
    start_template_service(service_name=name, service_port=port)


def start_template_service(service_name: str | None = None, service_port: int | str | None = None):
    if service_name:
        os.environ["ENGINE_SERVICE_NAME"] = str(service_name)
    if service_port is not None:
        os.environ["ENGINE_SERVICE_PORT"] = str(service_port)
    name = os.getenv("ENGINE_SERVICE_NAME", "engine")
    port = int(os.getenv("ENGINE_SERVICE_PORT") or os.getenv("SERVICE_PORT", "8003"))
    _framework_start_template_service(
        service_name=name, service_port=port, custom_endpoints=_custom_endpoints()
    )


def main():
    start_engine()
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
