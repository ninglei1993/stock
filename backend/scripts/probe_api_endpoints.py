#!/usr/bin/env python3
"""
接口探测工具：快速区分「代理层问题」与「后端接口逻辑问题」。

用途：
1) 同时请求 web 入口（默认 http://localhost:3000）和 api 直连（默认 http://localhost:8000）
2) 可扫描前后端代码，自动收集项目中使用到的接口
3) 对同一批接口做对照测试（回测）
4) 输出每个接口的状态码、耗时、错误类型和自动诊断结论

运行示例：
  python3 backend/scripts/probe_api_endpoints.py
  python3 backend/scripts/probe_api_endpoints.py --timeout 12
  python3 backend/scripts/probe_api_endpoints.py --endpoint /api/health --endpoint /api/dashboard
  python3 backend/scripts/probe_api_endpoints.py --scan-code
  python3 backend/scripts/probe_api_endpoints.py --scan-code --include-write
"""

from __future__ import annotations

import argparse
import json
import re
import socket
import sys
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any


_BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))


DEFAULT_ENDPOINTS = [
    "/api/health",
    "/api/system/status",
    "/api/tasks/scan",
    "/api/dashboard",
]


@dataclass
class ProbeResult:
    target: str
    method: str
    endpoint: str
    url: str
    ok: bool
    reachable: bool
    status: int | None
    elapsed_ms: int
    error_type: str | None
    error_message: str | None
    body_preview: str


@dataclass(frozen=True)
class EndpointCase:
    method: str
    endpoint: str
    source: str


@dataclass
class TushareProbeResult:
    endpoint: str
    ok: bool
    elapsed_ms: int
    rows: int | None
    sample_preview: str
    error: str | None


_ROUTER_PATTERN = re.compile(r'@router\.(get|post|put|delete|patch)\(\s*"([^"]+)"')
_FETCHJSON_PATTERN = re.compile(
    r'fetchJson<[^>]*>\(\s*([`"])(.+?)\1',
    re.DOTALL,
)
_VAR_EXPR_PATTERN = re.compile(r"\$\{[^}]+\}")
_PATH_PARAM_PATTERN = re.compile(r"\{([a-zA-Z0-9_]+)\}")


def _normalize_base_url(base: str) -> str:
    b = (base or "").strip().rstrip("/")
    if not b:
        raise ValueError("base URL 不能为空")
    if not (b.startswith("http://") or b.startswith("https://")):
        raise ValueError(f"base URL 必须以 http:// 或 https:// 开头: {base}")
    return b


def _classify_url_error(reason: Any) -> tuple[str, str]:
    if isinstance(reason, socket.timeout):
        return "timeout", "请求超时"
    if isinstance(reason, ConnectionRefusedError):
        return "connection_refused", "连接被拒绝"
    if isinstance(reason, socket.gaierror):
        return "dns_error", "DNS 解析失败"
    msg = str(reason)
    lower = msg.lower()
    if "timed out" in lower:
        return "timeout", msg
    if "refused" in lower:
        return "connection_refused", msg
    if "name or service not known" in lower or "nodename nor servname provided" in lower:
        return "dns_error", msg
    return "network_error", msg


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _normalize_scanned_path(path: str) -> str:
    p = (path or "").strip()
    if not p:
        return ""
    p = _VAR_EXPR_PATTERN.sub("X", p)
    p = p.replace("`", "").replace('"', "").replace("'", "")
    p = p.split("?", 1)[0].strip()
    if not p:
        return ""
    if not p.startswith("/"):
        p = f"/{p}"
    if p.startswith("/api/"):
        pass
    elif p == "/api":
        pass
    else:
        p = f"/api{p}"
    while "//" in p:
        p = p.replace("//", "/")
    return p


def _fill_path_params(path: str) -> str:
    def repl(match: re.Match[str]) -> str:
        key = match.group(1).lower()
        if "date" in key:
            return "2026-05-20"
        if key.endswith("id") or "_id" in key:
            return "1"
        if "sector" in key and "code" in key:
            return "BK0001"
        if "stock" in key and "code" in key:
            return "000001.SZ"
        if "code" in key:
            return "TEST"
        return "1"

    return _PATH_PARAM_PATTERN.sub(repl, path)


def _discover_backend_endpoints(root: Path) -> list[EndpointCase]:
    out: list[EndpointCase] = []
    backend_dir = root / "backend"
    if not backend_dir.exists():
        return out
    for py_file in backend_dir.rglob("*.py"):
        try:
            text = py_file.read_text(encoding="utf-8")
        except Exception:
            continue
        for method, raw_path in _ROUTER_PATTERN.findall(text):
            endpoint = _normalize_scanned_path(raw_path)
            endpoint = _fill_path_params(endpoint)
            if not endpoint:
                continue
            out.append(
                EndpointCase(
                    method=method.upper(),
                    endpoint=endpoint,
                    source=str(py_file.relative_to(root)),
                )
            )
    return out


def _discover_frontend_endpoints(root: Path) -> list[EndpointCase]:
    out: list[EndpointCase] = []
    frontend_dir = root / "frontend"
    if not frontend_dir.exists():
        return out
    for ts_file in list(frontend_dir.rglob("*.ts")) + list(frontend_dir.rglob("*.tsx")):
        try:
            text = ts_file.read_text(encoding="utf-8")
        except Exception:
            continue
        for _, raw_path in _FETCHJSON_PATTERN.findall(text):
            # 跳过复杂模板字符串，避免把表达式片段误识别为非法路径；
            # 这些动态路由会由后端 @router 扫描补齐。
            if "${" in raw_path:
                continue
            endpoint = _normalize_scanned_path(raw_path)
            endpoint = _fill_path_params(endpoint)
            if not endpoint:
                continue
            out.append(
                EndpointCase(
                    method="GET",
                    endpoint=endpoint,
                    source=str(ts_file.relative_to(root)),
                )
            )
    return out


def _build_cases(
    explicit_endpoints: list[str],
    scan_code: bool,
    include_write: bool,
) -> tuple[list[EndpointCase], dict[str, int]]:
    cases: list[EndpointCase] = []
    stats = {
        "explicit": 0,
        "backend_scanned": 0,
        "frontend_scanned": 0,
        "write_skipped": 0,
    }

    for ep in explicit_endpoints:
        endpoint = _fill_path_params(_normalize_scanned_path(ep))
        if not endpoint:
            continue
        cases.append(EndpointCase(method="GET", endpoint=endpoint, source="cli"))
        stats["explicit"] += 1

    if scan_code:
        root = _repo_root()
        backend_cases = _discover_backend_endpoints(root)
        frontend_cases = _discover_frontend_endpoints(root)
        stats["backend_scanned"] = len(backend_cases)
        stats["frontend_scanned"] = len(frontend_cases)
        cases.extend(backend_cases)
        cases.extend(frontend_cases)

    if not explicit_endpoints and not scan_code:
        for ep in DEFAULT_ENDPOINTS:
            cases.append(EndpointCase(method="GET", endpoint=ep, source="default"))
    else:
        # 无论是否扫描代码，始终保留一组稳定基线接口用于快速判定。
        for ep in DEFAULT_ENDPOINTS:
            cases.append(EndpointCase(method="GET", endpoint=ep, source="default"))

    dedup: dict[tuple[str, str], EndpointCase] = {}
    for c in cases:
        method = c.method.upper()
        if method != "GET" and not include_write:
            stats["write_skipped"] += 1
            continue
        dedup[(method, c.endpoint)] = c
    return sorted(dedup.values(), key=lambda x: (x.endpoint, x.method)), stats


def _probe_once(target: str, base_url: str, case: EndpointCase, timeout_sec: float) -> ProbeResult:
    endpoint = case.endpoint if case.endpoint.startswith("/") else f"/{case.endpoint}"
    method = case.method.upper()
    url = f"{base_url}{endpoint}"
    data = None
    headers = {}
    if method in {"POST", "PUT", "PATCH"}:
        data = b"{}"
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url=url, method=method, data=data, headers=headers)
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
            body = resp.read(400).decode("utf-8", errors="replace")
            elapsed = int((time.perf_counter() - started) * 1000)
            status = int(getattr(resp, "status", 200))
            return ProbeResult(
                target=target,
                method=method,
                endpoint=endpoint,
                url=url,
                ok=200 <= status < 300,
                reachable=status < 500,
                status=status,
                elapsed_ms=elapsed,
                error_type=None if 200 <= status < 300 else "http_error",
                error_message=None if 200 <= status < 300 else f"HTTP {status}",
                body_preview=body.replace("\n", " ")[:180],
            )
    except urllib.error.HTTPError as exc:
        elapsed = int((time.perf_counter() - started) * 1000)
        body = ""
        try:
            body = exc.read(400).decode("utf-8", errors="replace")
        except Exception:
            body = ""
        return ProbeResult(
            target=target,
            method=method,
            endpoint=endpoint,
            url=url,
            ok=False,
            reachable=int(exc.code) < 500,
            status=int(exc.code),
            elapsed_ms=elapsed,
            error_type="http_error",
            error_message=f"HTTP {exc.code}",
            body_preview=body.replace("\n", " ")[:180],
        )
    except urllib.error.URLError as exc:
        elapsed = int((time.perf_counter() - started) * 1000)
        err_type, err_msg = _classify_url_error(getattr(exc, "reason", exc))
        return ProbeResult(
            target=target,
            method=method,
            endpoint=endpoint,
            url=url,
            ok=False,
            reachable=False,
            status=None,
            elapsed_ms=elapsed,
            error_type=err_type,
            error_message=err_msg,
            body_preview="",
        )
    except TimeoutError as exc:
        elapsed = int((time.perf_counter() - started) * 1000)
        return ProbeResult(
            target=target,
            method=method,
            endpoint=endpoint,
            url=url,
            ok=False,
            reachable=False,
            status=None,
            elapsed_ms=elapsed,
            error_type="timeout",
            error_message=str(exc),
            body_preview="",
        )
    except Exception as exc:  # pragma: no cover - 最后一层兜底
        elapsed = int((time.perf_counter() - started) * 1000)
        return ProbeResult(
            target=target,
            method=method,
            endpoint=endpoint,
            url=url,
            ok=False,
            reachable=False,
            status=None,
            elapsed_ms=elapsed,
            error_type="unknown_error",
            error_message=str(exc),
            body_preview="",
        )


def _format_status(r: ProbeResult) -> str:
    if r.status is not None:
        return str(r.status)
    return "-"


def _format_error(r: ProbeResult) -> str:
    if r.error_type is None:
        return "-"
    msg = r.error_message or ""
    short = msg[:52] + "..." if len(msg) > 55 else msg
    return f"{r.error_type}:{short}" if short else r.error_type


def _diagnose(web: ProbeResult, api: ProbeResult) -> str:
    if web.ok and api.ok:
        return "OK（网关与后端都正常）"
    if (not web.reachable) and api.reachable:
        return "疑似代理/网关问题（web 异常但 api 直连正常）"
    if web.reachable and (not api.reachable):
        return "疑似直连地址或后端实例问题（web 正常但 api 直连异常）"
    if web.status == 502 and (api.status is not None and api.status < 500):
        return "疑似代理层转发异常（web=502，api 非 5xx）"
    if (api.status is not None and api.status >= 500) and (web.status is not None and web.status >= 500):
        return "疑似后端逻辑异常（两侧均 5xx）"
    if (not web.reachable) and (not api.reachable):
        return "疑似服务不可达/超时（两侧均不可达）"
    if web.reachable and api.reachable:
        return "接口可达（可能是业务校验 4xx）"
    return "需人工进一步排查"


def _is_failure(r: ProbeResult) -> bool:
    if not r.reachable:
        return True
    return (r.status or 0) >= 500


def _print_human_report(
    paired: list[tuple[EndpointCase, ProbeResult, ProbeResult]],
    stats: dict[str, int],
) -> None:
    print("\n=== API Endpoint Probe ===")
    print(
        "method".ljust(8),
        "endpoint".ljust(38),
        "web".ljust(6),
        "api".ljust(6),
        "latency(ms)".ljust(18),
        "diagnosis",
    )
    print("-" * 124)
    for case, web, api in paired:
        latency = f"{web.elapsed_ms}/{api.elapsed_ms}"
        print(
            case.method.ljust(8),
            web.endpoint.ljust(28),
            _format_status(web).ljust(6),
            _format_status(api).ljust(6),
            latency.ljust(18),
            _diagnose(web, api),
        )
    print("\n=== Scan Stats ===")
    print(
        f"explicit={stats['explicit']}, backend_scanned={stats['backend_scanned']}, "
        f"frontend_scanned={stats['frontend_scanned']}, write_skipped={stats['write_skipped']}, "
        f"final_cases={len(paired)}"
    )

    print("\n=== Error Details ===")
    has_error = False
    for case, web, api in paired:
        if not (_is_failure(web) or _is_failure(api)):
            continue
        has_error = True
        print(f"\n[{case.method} {web.endpoint}]  source={case.source}")
        print(f"  web: status={_format_status(web)}, err={_format_error(web)}, url={web.url}")
        if web.body_preview:
            print(f"       body={web.body_preview}")
        print(f"  api: status={_format_status(api)}, err={_format_error(api)}, url={api.url}")
        if api.body_preview:
            print(f"       body={api.body_preview}")
    if not has_error:
        print("全部接口探测通过。")


def _run_probe(
    web_base: str,
    api_base: str,
    cases: list[EndpointCase],
    timeout_sec: float,
    show_progress: bool,
) -> list[tuple[EndpointCase, ProbeResult, ProbeResult]]:
    paired: list[tuple[EndpointCase, ProbeResult, ProbeResult]] = []
    total = len(cases)
    for idx, case in enumerate(cases, start=1):
        if show_progress:
            print(
                f"[{idx}/{total}] probing {case.method} {case.endpoint} (source={case.source}) ...",
                flush=True,
            )
        web_res = _probe_once("web", web_base, case, timeout_sec)
        api_res = _probe_once("api", api_base, case, timeout_sec)
        if show_progress:
            web_mark = f"{web_res.status}" if web_res.status is not None else web_res.error_type or "err"
            api_mark = f"{api_res.status}" if api_res.status is not None else api_res.error_type or "err"
            print(
                f"         -> web={web_mark} ({web_res.elapsed_ms}ms), "
                f"api={api_mark} ({api_res.elapsed_ms}ms)",
                flush=True,
            )
        paired.append((case, web_res, api_res))
    return paired


def _probe_tushare_calls(show_progress: bool, preview_rows: int) -> list[TushareProbeResult]:
    """
    直接验证关键 Tushare 接口可用性（不依赖前端/网关）。
    """
    try:
        from app.adapters.factory import get_adapter  # type: ignore
    except Exception as exc:
        return [
            TushareProbeResult(
                endpoint="bootstrap",
                ok=False,
                elapsed_ms=0,
                rows=None,
                sample_preview="",
                error=f"无法导入后端运行环境: {exc}",
            )
        ]

    try:
        adapter = get_adapter()
    except Exception as exc:
        return [
            TushareProbeResult(
                endpoint="get_adapter",
                ok=False,
                elapsed_ms=0,
                rows=None,
                sample_preview="",
                error=f"初始化适配器失败: {exc}",
            )
        ]

    if not hasattr(adapter, "_call"):
        return [
            TushareProbeResult(
                endpoint="adapter",
                ok=False,
                elapsed_ms=0,
                rows=None,
                sample_preview="",
                error=f"当前适配器不支持 _call: {adapter.__class__.__name__}",
            )
        ]

    # 预留 3 天窗口，避免节假日只有空数据。
    end = date.today()
    start = end - timedelta(days=3)
    trade_date = end.strftime("%Y%m%d")
    start_date = start.strftime("%Y%m%d")
    end_date = end.strftime("%Y%m%d")

    call_specs: list[tuple[str, dict[str, Any]]] = [
        ("trade_cal", {"exchange": "SSE", "start_date": start_date, "end_date": end_date, "is_open": "1"}),
        ("daily", {"trade_date": trade_date, "fields": "ts_code,trade_date,close,pre_close,amount"}),
        ("moneyflow_dc", {"trade_date": trade_date}),
        ("moneyflow", {"trade_date": trade_date}),
        ("stk_limit", {"trade_date": trade_date, "fields": "ts_code,trade_date,up_limit,down_limit"}),
        ("index_daily", {"ts_code": "000300.SH", "start_date": start_date, "end_date": end_date}),
    ]

    out: list[TushareProbeResult] = []
    total = len(call_specs)
    for idx, (endpoint, kwargs) in enumerate(call_specs, start=1):
        if show_progress:
            print(f"[tushare {idx}/{total}] probing {endpoint} ...", flush=True)
        started = time.perf_counter()
        try:
            df = adapter._call(endpoint, **kwargs)  # type: ignore[attr-defined]
            elapsed = int((time.perf_counter() - started) * 1000)
            rows = None
            if df is not None:
                try:
                    rows = int(getattr(df, "shape", [0])[0] or 0)
                except Exception:
                    rows = None
            preview = ""
            if df is not None and rows and rows > 0:
                try:
                    sample = df.head(max(preview_rows, 1)).to_dict(orient="records")
                    preview = json.dumps(sample, ensure_ascii=False, separators=(",", ":"))
                except Exception:
                    preview = ""
            out.append(
                TushareProbeResult(
                    endpoint=endpoint,
                    ok=True,
                    elapsed_ms=elapsed,
                    rows=rows,
                    sample_preview=preview,
                    error=None,
                )
            )
            if show_progress:
                msg = f"             -> ok rows={rows} ({elapsed}ms)"
                if preview:
                    short = preview[:200] + ("..." if len(preview) > 200 else "")
                    msg += f" sample={short}"
                print(msg, flush=True)
        except Exception as exc:
            elapsed = int((time.perf_counter() - started) * 1000)
            out.append(
                TushareProbeResult(
                    endpoint=endpoint,
                    ok=False,
                    elapsed_ms=elapsed,
                    rows=None,
                    sample_preview="",
                    error=str(exc),
                )
            )
            if show_progress:
                print(f"             -> failed ({elapsed}ms): {exc}", flush=True)
    return out


def _print_tushare_report(results: list[TushareProbeResult]) -> None:
    print("\n=== Tushare Endpoint Probe ===")
    print("endpoint".ljust(18), "ok".ljust(6), "rows".ljust(8), "latency(ms)".ljust(12), "error")
    print("-" * 100)
    for r in results:
        print(
            r.endpoint.ljust(18),
            ("yes" if r.ok else "no").ljust(6),
            (str(r.rows) if r.rows is not None else "-").ljust(8),
            str(r.elapsed_ms).ljust(12),
            (r.error or "-")[:80],
        )
    print("\n=== Tushare Sample Data ===")
    has_sample = False
    for r in results:
        if not r.sample_preview:
            continue
        has_sample = True
        short = r.sample_preview[:1200]
        if len(r.sample_preview) > 1200:
            short += "...(truncated)"
        print(f"\n[{r.endpoint}]")
        print(short)
    if not has_sample:
        print("暂无可展示样本（可能 rows=0 或接口失败）。")


def main() -> int:
    parser = argparse.ArgumentParser(description="探测 API 接口可达性并定位代理层问题。")
    parser.add_argument("--web-base", default="http://localhost:3000", help="前端网关地址（默认: http://localhost:3000）")
    parser.add_argument("--api-base", default="http://localhost:8000", help="后端直连地址（默认: http://localhost:8000）")
    parser.add_argument("--timeout", type=float, default=8.0, help="单个请求超时秒数（默认: 8）")
    parser.add_argument(
        "--endpoint",
        action="append",
        default=[],
        help="要探测的接口路径，可重复传参；不传则使用内置默认接口列表",
    )
    parser.add_argument("--scan-code", action="store_true", help="扫描前后端代码，自动收集接口")
    parser.add_argument("--include-write", action="store_true", help="包含 POST/PUT/PATCH/DELETE（可能触发副作用）")
    parser.add_argument("--scan-tushare", action="store_true", help="额外验证关键 Tushare 接口（daily/moneyflow 等）")
    parser.add_argument("--tushare-preview-rows", type=int, default=3, help="Tushare 样本数据打印条数（默认: 3）")
    parser.add_argument("--max-cases", type=int, default=300, help="最多探测多少个接口用例（默认: 300）")
    parser.add_argument("--quiet", action="store_true", help="关闭逐条进度输出，只保留最终汇总")
    parser.add_argument("--json", action="store_true", help="以 JSON 输出完整结果")
    args = parser.parse_args()

    try:
        web_base = _normalize_base_url(args.web_base)
        api_base = _normalize_base_url(args.api_base)
    except ValueError as exc:
        print(f"参数错误: {exc}")
        return 2

    cases, stats = _build_cases(args.endpoint, args.scan_code, args.include_write)
    if args.max_cases > 0:
        cases = cases[: args.max_cases]
    paired = _run_probe(
        web_base,
        api_base,
        cases,
        args.timeout,
        show_progress=not args.quiet,
    )
    tushare_results = (
        _probe_tushare_calls(show_progress=not args.quiet, preview_rows=max(1, args.tushare_preview_rows))
        if args.scan_tushare
        else []
    )

    if args.json:
        payload = [
            {
                "method": case.method,
                "endpoint": case.endpoint,
                "source": case.source,
                "diagnosis": _diagnose(web, api),
                "web": asdict(web),
                "api": asdict(api),
            }
            for case, web, api in paired
        ]
        print(
            json.dumps(
                {
                    "stats": stats,
                    "results": payload,
                    "tushare_results": [asdict(x) for x in tushare_results],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        _print_human_report(paired, stats)
        if args.scan_tushare:
            _print_tushare_report(tushare_results)
        else:
            print("\n提示：未启用 Tushare 接口检测。如需验证 daily/moneyflow 等，请加 --scan-tushare")

    has_fail = any(_is_failure(web) or _is_failure(api) for _, web, api in paired)
    if args.scan_tushare:
        has_fail = has_fail or any(not x.ok for x in tushare_results)
    return 0 if not has_fail else 1


if __name__ == "__main__":
    raise SystemExit(main())
