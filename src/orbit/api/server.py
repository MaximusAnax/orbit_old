"""Dashboard API.

Serves the operator interface: PnL, positions, risk utilisation, per-strategy
performance, data-coverage health, and the kill switch.

Security posture: this endpoint can halt trading and reveals the full position
book, so every route requires a bearer token and the server refuses to start
without one. It binds to localhost by default — exposing it publicly should be
done through a reverse proxy with TLS, not by changing the bind address.

Deposits and withdrawals are deliberately **not** automated. The API reports
balances and tells you exactly what to do, but moving money remains a manual
action taken by a human on the venue's own site. An API key that can move funds
off the platform is a much larger blast radius than one that can only trade,
and no amount of convenience justifies it for an unattended process.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from fastapi import Depends, FastAPI, Header, HTTPException, status
from fastapi.responses import HTMLResponse

if TYPE_CHECKING:
    from orbit.config import Settings
    from orbit.data.recorder import Recorder
    from orbit.engine.runner import TradingRunner


class AppState:
    """Live objects the API reports on. Set once at startup."""

    def __init__(self) -> None:
        self.runner: TradingRunner | None = None
        self.recorder: Recorder | None = None
        self.settings: Settings | None = None
        self.started_at = datetime.now(UTC)


state = AppState()


def _auth(authorization: str = Header(default="")) -> None:
    """Bearer-token check applied to every route."""
    settings = state.settings
    expected = settings.api_token if settings else ""
    if not expected:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "API token not configured"
        )
    supplied = authorization.removeprefix("Bearer ").strip()
    # Constant-time compare: a token check that leaks length or prefix through
    # timing is a token check that can be brute-forced.
    import hmac

    if not hmac.compare_digest(supplied, expected):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid token")


def create_app() -> FastAPI:
    app = FastAPI(
        title="Orbit",
        description="Prediction-market trading system",
        version="0.1.0",
        # No unauthenticated schema surface: the OpenAPI document enumerates
        # every route including the kill switch, so it is disabled along with
        # the docs UIs rather than left as the one open endpoint.
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    @app.get("/health")
    def health() -> dict[str, Any]:
        """Unauthenticated liveness only. Deliberately reveals nothing."""
        return {"status": "ok", "uptime_s": (
            datetime.now(UTC) - state.started_at
        ).total_seconds()}

    @app.get("/api/status", dependencies=[Depends(_auth)])
    def get_status() -> dict[str, Any]:
        """Everything the dashboard renders in one call."""
        settings = state.settings
        out: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "uptime_s": (datetime.now(UTC) - state.started_at).total_seconds(),
            "config": settings.describe() if settings else {},
        }
        if state.runner is not None:
            out.update(state.runner.status())
        if state.recorder is not None:
            out["recorder"] = state.recorder.status()
        return out

    @app.get("/api/positions", dependencies=[Depends(_auth)])
    def get_positions() -> dict[str, Any]:
        if state.runner is None:
            return {"positions": []}
        risk = state.runner.risk
        return {
            "positions": [
                {
                    "market_key": key,
                    "size": pos.size,
                    "avg_price_cents": (
                        pos.avg_price_pips / 100 if pos.avg_price_pips else None
                    ),
                    "collateral_usd": pos.collateral_pips() / 10_000,
                    "realized_pnl_usd": pos.realized_pnl_pips / 10_000,
                    "fees_paid_usd": pos.fees_paid_pips / 10_000,
                }
                for key, pos in risk.state.positions.items()
                if not pos.is_flat
            ],
            "totals": risk.snapshot(),
        }

    @app.get("/api/trades", dependencies=[Depends(_auth)])
    def get_trades(limit: int = 100) -> dict[str, Any]:
        if state.runner is None:
            return {"trades": []}
        return {"trades": state.runner.trade_log[-limit:]}

    @app.get("/api/opportunities", dependencies=[Depends(_auth)])
    def get_opportunities() -> dict[str, Any]:
        """Violations visible right now, whether or not they were traded.

        Scans fresh rather than serving the last loop's cache: the question
        this endpoint answers is "what does the strategy see at this instant",
        and a stale answer to that is worse than none. The scan is read-only
        and never places an order.

        Useful on day one, before there is any PnL curve to look at: it shows
        whether the strategy is finding anything at all.
        """
        if state.runner is None:
            return {"opportunities": []}
        runner = state.runner
        return {
            "opportunities": [
                {
                    "constraint": o.constraint_name,
                    "profit_usd": o.worst_case_profit_pips / 10_000,
                    "capital_usd": o.capital_pips / 10_000,
                    "return_on_capital": (
                        None if o.return_on_capital == float("inf")
                        else o.return_on_capital
                    ),
                    "legs": len(o.legs),
                    "execution_risk": o.execution_risk,
                    "rationale": o.rationale,
                }
                for o in runner.scanner.scan(runner.books)
            ]
        }

    @app.post("/api/kill", dependencies=[Depends(_auth)])
    async def kill(reason: str = "manual") -> dict[str, Any]:
        """Halt trading immediately and pull every resting order."""
        if state.runner is None:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "no runner")
        state.runner.risk.kill.trip(f"manual: {reason}")
        canceled = await state.runner.executor.cancel_all()
        return {
            "killed": True,
            "orders_canceled": canceled,
            "kill_switch": state.runner.risk.kill.as_dict(),
        }

    @app.post("/api/resume", dependencies=[Depends(_auth)])
    def resume(acknowledged_by: str) -> dict[str, Any]:
        """Re-arm trading. Requires naming who is taking responsibility."""
        if state.runner is None:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "no runner")
        if not acknowledged_by.strip():
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, "acknowledged_by is required"
            )
        state.runner.risk.kill.reset(acknowledged_by=acknowledged_by)
        return {"resumed": True, "by": acknowledged_by}

    @app.get("/api/funding", dependencies=[Depends(_auth)])
    def funding() -> dict[str, Any]:
        """Balances and manual instructions for moving money.

        Intentionally advisory. Automating withdrawals would mean holding a
        credential that can move funds off-venue inside an unattended process,
        which is a far worse trade than clicking a button yourself.
        """
        settings = state.settings
        risk = state.runner.risk if state.runner else None
        return {
            "configured_bankroll_usd": settings.bankroll_usd if settings else 0,
            "tracked_bankroll_usd": (
                risk.state.bankroll_pips / 10_000 if risk else 0
            ),
            "deployed_usd": risk.state.deployed_pips() / 10_000 if risk else 0,
            "free_usd": (
                (risk.state.bankroll_pips - risk.state.deployed_pips()) / 10_000
                if risk
                else 0
            ),
            "instructions": {
                "deposit": [
                    "Kalshi: fund by ACH or wire at kalshi.com; funds settle to "
                    "your trading balance, no action needed here.",
                    "Polymarket: send USDC.e on Polygon to your funder address, "
                    "then confirm the balance shows on the dashboard.",
                    "After depositing, update ORBIT_BANKROLL_USD and restart so "
                    "risk limits scale to the new capital.",
                ],
                "withdraw": [
                    "Halt trading first (POST /api/kill) so nothing opens a new "
                    "position against capital you are removing.",
                    "Wait for open positions to settle, or close them manually — "
                    "collateral is locked until settlement.",
                    "Withdraw on the venue's own site, then lower "
                    "ORBIT_BANKROLL_USD and restart.",
                ],
            },
            "open_positions_block_withdrawal": (
                sum(1 for p in risk.state.positions.values() if not p.is_flat)
                if risk
                else 0
            ),
        }

    @app.get("/", response_class=HTMLResponse)
    def dashboard() -> str:
        return DASHBOARD_HTML

    return app


DASHBOARD_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Orbit</title>
<style>
  :root {
    --bg: #0b0e14; --panel: #141922; --line: #232a36; --text: #e6e9ef;
    --muted: #8b95a7; --good: #3fb950; --bad: #f85149; --warn: #d29922;
    --accent: #58a6ff;
  }
  @media (prefers-color-scheme: light) {
    :root {
      --bg: #f6f8fa; --panel: #fff; --line: #d8dee4; --text: #1f2328;
      --muted: #656d76; --accent: #0969da;
    }
  }
  * { box-sizing: border-box; }
  body { margin:0; background:var(--bg); color:var(--text);
    font:14px/1.5 ui-sans-serif,-apple-system,"Segoe UI",sans-serif; padding:24px; }
  h1 { font-size:20px; margin:0 0 4px; letter-spacing:-.01em; }
  .sub { color:var(--muted); font-size:13px; margin-bottom:20px; }
  .grid { display:grid; gap:14px; grid-template-columns:repeat(auto-fit,minmax(210px,1fr)); }
  .card { background:var(--panel); border:1px solid var(--line); border-radius:10px; padding:14px 16px; }
  .label { color:var(--muted); font-size:11px; text-transform:uppercase;
    letter-spacing:.06em; margin-bottom:6px; }
  .value { font-size:24px; font-weight:600; font-variant-numeric:tabular-nums; }
  .good { color:var(--good); } .bad { color:var(--bad); } .warn { color:var(--warn); }
  section { margin-top:26px; }
  h2 { font-size:14px; text-transform:uppercase; letter-spacing:.06em;
    color:var(--muted); margin:0 0 10px; }
  .scroll { overflow-x:auto; }
  table { width:100%; border-collapse:collapse; font-variant-numeric:tabular-nums; }
  th,td { text-align:left; padding:8px 10px; border-bottom:1px solid var(--line);
    white-space:nowrap; }
  th { color:var(--muted); font-weight:500; font-size:12px; }
  .bar { height:6px; background:var(--line); border-radius:3px; overflow:hidden; margin-top:6px; }
  .bar > div { height:100%; background:var(--accent); }
  button { background:var(--bad); color:#fff; border:0; padding:9px 16px;
    border-radius:7px; font-weight:600; cursor:pointer; font-size:13px; }
  button.ghost { background:var(--line); color:var(--text); }
  input { background:var(--bg); border:1px solid var(--line); color:var(--text);
    padding:8px 10px; border-radius:7px; width:260px; }
  .row { display:flex; gap:10px; align-items:center; flex-wrap:wrap; }
  .pill { display:inline-block; padding:2px 9px; border-radius:999px; font-size:11px;
    font-weight:600; background:var(--line); }
  .empty { color:var(--muted); padding:14px 0; }
</style>
</head>
<body>
<h1>Orbit</h1>
<div class="sub" id="sub">connecting…</div>

<div class="row" style="margin-bottom:18px">
  <input id="tok" type="password" placeholder="API token" />
  <button class="ghost" onclick="save()">Connect</button>
  <button onclick="kill()">KILL SWITCH</button>
</div>

<div class="grid" id="tiles"></div>

<section><h2>Risk utilisation</h2><div id="risk"></div></section>
<section><h2>Live opportunities</h2><div class="scroll" id="opps"></div></section>
<section><h2>Positions</h2><div class="scroll" id="pos"></div></section>
<section><h2>Recent trades</h2><div class="scroll" id="trades"></div></section>

<script>
const $ = id => document.getElementById(id);
let token = localStorage.getItem('orbit_token') || '';
$('tok').value = token;
function save(){ token = $('tok').value; localStorage.setItem('orbit_token', token); load(); }

async function api(path, opts={}){
  const r = await fetch(path, {...opts, headers:{Authorization:'Bearer '+token}});
  if(!r.ok) throw new Error(r.status===401?'bad token':'error '+r.status);
  return r.json();
}
async function kill(){
  if(!confirm('Halt all trading and cancel every resting order?')) return;
  try { const r = await api('/api/kill?reason=dashboard',{method:'POST'});
    alert('Trading halted. Orders cancelled: '+r.orders_canceled); load(); }
  catch(e){ alert(e.message); }
}
const usd = n => (n<0?'-':'')+'$'+Math.abs(n||0).toFixed(2);
const pct = n => ((n||0)*100).toFixed(1)+'%';

function tile(label, value, cls){
  return `<div class="card"><div class="label">${label}</div>
          <div class="value ${cls||''}">${value}</div></div>`;
}
function table(rows, cols){
  if(!rows.length) return '<div class="empty">Nothing yet.</div>';
  return '<table><tr>'+cols.map(c=>`<th>${c[0]}</th>`).join('')+'</tr>'+
    rows.map(r=>'<tr>'+cols.map(c=>`<td>${c[1](r)}</td>`).join('')+'</tr>').join('')+'</table>';
}

async function load(){
  if(!token){ $('sub').textContent='Enter your API token to connect.'; return; }
  try {
    const s = await api('/api/status');
    const st = s.strategy||{}, risk = s.risk||{}, ks = risk.kill_switch||{};
    const live = (s.config||{}).effective || '';
    $('sub').innerHTML = `<span class="pill">${(s.config||{}).mode||'?'}</span> `+
      `${live} · uptime ${Math.floor((s.uptime_s||0)/60)}m`+
      (ks.tripped?` · <span class="bad">KILLED: ${ks.reason}</span>`:'');

    const net = st.net_pnl_usd||0;
    $('tiles').innerHTML =
      tile('Net PnL', usd(net), net>=0?'good':'bad')+
      tile('Bankroll', usd(risk.bankroll_usd))+
      tile('Deployed', usd(risk.deployed_usd))+
      tile('Trades', (st.trades_completed||0)+' / '+(st.trades_attempted||0))+
      tile('Fill rate', pct(st.fill_rate))+
      tile('Fees paid', usd(st.fees_usd))+
      tile('Drawdown', pct(risk.drawdown_fraction), (risk.drawdown_fraction||0)>0.05?'warn':'')+
      tile('Opportunities', st.opportunities_seen||0);

    const u = [
      ['Capital deployed', risk.deployed_fraction, risk.deployed_limit],
      ['Daily loss', risk.daily_loss_fraction, risk.daily_loss_limit],
      ['Drawdown', risk.drawdown_fraction, risk.drawdown_limit],
    ];
    $('risk').innerHTML = '<div class="grid">'+u.map(([n,v,l])=>{
      const f = l ? Math.min(1,(v||0)/l) : 0;
      return `<div class="card"><div class="label">${n}</div>
        <div class="value">${pct(v)} <span style="font-size:12px;color:var(--muted)">of ${pct(l)}</span></div>
        <div class="bar"><div style="width:${f*100}%;background:${f>0.8?'var(--bad)':f>0.5?'var(--warn)':'var(--accent)'}"></div></div></div>`;
    }).join('')+'</div>';

    $('opps').innerHTML = table(s.recent_opportunities||[], [
      ['Constraint', r=>r.constraint], ['Legs', r=>r.legs],
      ['Profit', r=>`<span class="good">${usd(r.profit_usd)}</span>`],
      ['Capital', r=>usd(r.capital_usd)],
      ['Return', r=>r.return_on_capital==null?'self-funding':pct(r.return_on_capital)],
      ['Execution risk', r=>r.execution_risk]]);

    const p = await api('/api/positions');
    $('pos').innerHTML = table(p.positions||[], [
      ['Market', r=>r.market_key], ['Size', r=>r.size],
      ['Avg', r=>r.avg_price_cents?r.avg_price_cents.toFixed(1)+'c':'—'],
      ['Collateral', r=>usd(r.collateral_usd)],
      ['Realised', r=>`<span class="${r.realized_pnl_usd>=0?'good':'bad'}">${usd(r.realized_pnl_usd)}</span>`]]);

    $('trades').innerHTML = table((s.recent_trades||[]).slice().reverse(), [
      ['Time', r=>(r.timestamp||'').slice(11,19)],
      ['Constraint', r=>r.constraint], ['Legs', r=>r.legs],
      ['Expected', r=>usd(r.expected_profit_usd)],
      ['Status', r=>r.completed?'<span class="good">filled</span>'
        :`<span class="bad">${r.error||'failed'}</span>`]]);
  } catch(e){ $('sub').innerHTML = `<span class="bad">${e.message}</span>`; }
}
load(); setInterval(load, 5000);
</script>
</body>
</html>
"""
