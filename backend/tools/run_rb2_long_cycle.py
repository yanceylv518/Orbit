"""Generate RB-2 v3 long-trend, smoothness and 1/3/10-day diagnostics."""
from __future__ import annotations

import argparse, json, math, sqlite3, statistics, sys
from bisect import bisect_right
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]; PROJECT_ROOT = BACKEND_ROOT.parent
sys.path.insert(0, str(BACKEND_ROOT / "src"))

from orbit.application.rb1_oversold import verify_context  # noqa: E402
from orbit.application.rb2_long_cycle import aggregate_completed_4h, future_extrema, horizon_summary, path_metrics, trend_at, trend_series  # noqa: E402
from orbit.application.rb2_opportunity_profile import identifiability_by_metric  # noqa: E402
from screen_r0_shortline import _market_loader, _prepare_universe, _write_exclusive  # noqa: E402

ROOT=PROJECT_ROOT/"var/calibration/shortline-data-v1"; CPS=PROJECT_ROOT/"var/research/r0-diag2-reproduction-checkpoints"
RB2=PROJECT_ROOT/"config/research/rb2_opportunity_profile.v1.json"; RB1=PROJECT_ROOT/"config/research/rb1_oversold.v1.json"; R0=PROJECT_ROOT/"config/research/r0_shortline_screen.v2.json"
BASE=PROJECT_ROOT/"docs/evidence/r0/r0_training_v2_20260812.json"
HORIZONS=(96,288,960); SCHEMA="""create table events(parameter_id text,family text,symbol text,signal_ms integer,net real,final_r real,smooth real,trend text,ma_dev real,ret20 real,ret60 real,duration real,btc_trend text,features text,h96 text,h288 text,h960 text)"""

def q(values,p):
    values=sorted(values); pos=(len(values)-1)*p; lo=math.floor(pos); hi=math.ceil(pos)
    return values[lo] if lo==hi else values[lo]+(values[hi]-values[lo])*(pos-lo)

def dist(values):
    values=list(values)
    return {"event_count":len(values),"mean":statistics.fmean(values),"p50":q(values,.5),"p75":q(values,.75),"p90":q(values,.9),"p95":q(values,.95),"p99":q(values,.99)} if values else {"event_count":0}

def trend_groups(rows):
    result={}
    for state in ("UP","RANGE","DOWN"):
        group=[r for r in rows if r["trend"]==state]
        if not group: result[state]={"event_count":0}; continue
        positive=sum(max(0,r["net"]) for r in group); ordered=sorted((max(0,r["net"]) for r in group),reverse=True)
        result[state]={"event_count":len(group),"final_return_r":dist(r["final_r"] for r in group),"smoothness":dist(r["smooth"] for r in group),"positive_profit_top_10_share":sum(ordered[:max(1,math.ceil(len(group)*.1))])/positive if positive else None,"signals_per_calendar_day":len(group)/((max(r["signal_ms"] for r in group)-min(r["signal_ms"] for r in group))/86400000+1)}
    return result

def grouped_outcomes(rows, group_getter, labels):
    result={}
    for label in labels:
        group=[r for r in rows if group_getter(r)==label]
        if not group: result[label]={"event_count":0}; continue
        result[label]={"event_count":len(group),"final_return_r":dist(r["final_r"] for r in group),"smoothness":dist(r["smooth"] for r in group)}
    return result

def long_trend_feature_summary(rows):
    characteristics={}
    for state in ("UP","RANGE","DOWN"):
        group=[r for r in rows if r["trend"]==state]
        characteristics[state]={
            "event_count":len(group),
            "ma50_deviation_pct":dist(r["ma_dev"] for r in group if r["ma_dev"] is not None),
            "return_20d_pct":dist(r["ret20"] for r in group if r["ret20"] is not None),
            "return_60d_pct":dist(r["ret60"] for r in group if r["ret60"] is not None),
            "trend_duration_4h_bars":dist(r["duration"] for r in group if r["duration"] is not None),
        }
    return {
        "local_state_characteristics":characteristics,
        "direction_alignment_groups":grouped_outcomes(
            rows,
            lambda r:"ALIGNED" if r["features"].get("direction_aligned_with_long_trend") else "NOT_ALIGNED",
            ("ALIGNED","NOT_ALIGNED"),
        ),
        "btc_long_trend_groups":grouped_outcomes(rows,lambda r:r["btc_trend"],("UP","RANGE","DOWN")),
    }

def main():
    ap=argparse.ArgumentParser(description=__doc__); ap.add_argument("--out",required=True); ap.add_argument("--db",required=True); ap.add_argument("--summarize-existing",action="store_true"); args=ap.parse_args()
    spec=json.loads(RB2.read_text()); end=int(spec["training_end_ms"])
    if end>=int(spec["lockbox_start_ms"]) or spec["discipline"]["lockbox_access"]!="PROHIBITED": raise RuntimeError("lockbox boundary")
    context=verify_context(RB1,R0,ROOT); symbols,_=_prepare_universe(ROOT,context["contract"],maximum_time_ms=end); loader=_market_loader(ROOT,minimum_time_ms=None,maximum_time_ms=end)
    baseline=json.loads(BASE.read_text()); selected=[x for x in baseline["parameter_reports"] if x["definition_id"]=="B1_DONCHIAN_VOLUME" or (x["definition_id"]=="S1_DROP_STABILIZATION" and x["parameters"]["minimum_drop_fraction"]=="0.10")]
    selected_ids={x["parameter_id"]:x for x in selected}; btc,_=loader("BTCUSDT"); btc_series=trend_series(aggregate_completed_4h(btc)); btc_times=[x.close_time_ms for x in btc]
    db=Path(args.db)
    if args.summarize_existing:
        if not db.exists(): raise RuntimeError("v3 sqlite does not exist")
        conn=sqlite3.connect(db)
    else:
        if db.exists(): raise RuntimeError("v3 sqlite already exists")
        conn=sqlite3.connect(db); conn.execute(SCHEMA)
    for symbol in (() if args.summarize_existing else sorted(symbols)):
        cp=CPS/f"{symbol}.json"
        if not cp.exists(): raise RuntimeError(f"missing checkpoint {symbol}")
        payload=json.loads(cp.read_text()); chosen=[]
        for pid,param in selected_ids.items():
            idx=payload["parameter_ids"].index(pid); events=payload["event_sets"][idx]
            if events: chosen.append((pid,param,events))
        if not chosen: continue
        candles,_=loader(symbol); open_idx={x.open_time_ms:i for i,x in enumerate(candles)}; close_idx={x.close_time_ms:i for i,x in enumerate(candles)}
        extrema={h:future_extrema(candles,h) for h in (8,16,32,96,288,960)}; local_trend=trend_series(aggregate_completed_4h(candles))
        batch=[]
        for pid,param,events in chosen:
            family=param["family_id"]; p=param["parameters"]; hold=int(p["holding_candles"]); look=int(p.get("return_lookback_candles",p.get("channel_lookback_candles",96)))
            for event in events:
                entry_i=open_idx[int(event["entry_time_ms"])]; signal_i=close_idx[int(event["signal_time_ms"])]; direction=event["direction"]; initial_r=2*float(event["atr14"])
                base=path_metrics(candles,entry_i,direction,float(event["entry_price"]),initial_r,hold,extrema[hold])
                if base is None: continue
                lt=trend_at(local_trend,int(event["signal_time_ms"])); bt=trend_at(btc_series,int(event["signal_time_ms"])); signal=candles[signal_i]
                vols=[x.quote_volume for x in candles[max(0,signal_i-96):signal_i]]; rel=signal.quote_volume/statistics.median(vols) if vols and statistics.median(vols)>0 else None
                ref=candles[signal_i-look].close if signal_i>=look else None; btc_i=bisect_right(btc_times,int(event["signal_time_ms"]))-1; btc_ret=None if btc_i<look else (btc[btc_i].close/btc[btc_i-look].close-1)*100
                features={"drop_depth_pct":(1-signal.close/ref)*100 if family=="OVERSOLD_REBOUND" and ref else None,"relative_quote_volume":rel,"volume_trend_3d":event["volume_trend_3d"],"btc_same_window_return_pct":btc_ret,"tier":event["tier"],"utc_hour":int(event["signal_time_ms"]//3600000%24),"listing_age":event["listing_age"],"atr_relative_pct":float(event["atr14"])/float(event["entry_price"])*100,"ma50_deviation_pct":lt.get("ma50_deviation_pct") if lt else None,"return_20d_pct":lt.get("return_20d_pct") if lt else None,"return_60d_pct":lt.get("return_60d_pct") if lt else None,"trend_duration_4h_bars":lt.get("duration_4h_bars") if lt else None,"direction_aligned_with_long_trend":bool(lt and ((direction=="LONG" and lt["state"]=="UP") or (direction=="SHORT" and lt["state"]=="DOWN"))),"btc_long_trend_state":bt.get("state") if bt else None}
                hs={h:path_metrics(candles,entry_i,direction,float(event["entry_price"]),initial_r,h,extrema[h]) for h in HORIZONS}
                batch.append((pid,family,symbol,int(event["signal_time_ms"]),float(event["net_return_pct"]),(float(event["net_return_pct"])/100*float(event["entry_price"]))/initial_r,base["smoothness"],lt.get("state") if lt else None,lt.get("ma50_deviation_pct") if lt else None,lt.get("return_20d_pct") if lt else None,lt.get("return_60d_pct") if lt else None,lt.get("duration_4h_bars") if lt else None,bt.get("state") if bt else None,json.dumps(features,separators=(",",":")),*(json.dumps(hs[h],separators=(",",":")) if hs[h] else None for h in HORIZONS)))
        conn.executemany("insert into events values(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",batch); conn.commit()
    reports=[]
    conn.row_factory=sqlite3.Row
    for pid,param in selected_ids.items():
        rows=[dict(x) for x in conn.execute("select * from events where parameter_id=?",(pid,))]
        for r in rows: r["features"]=json.loads(r["features"]); r["symbol"]=r["symbol"]; r["signal_time_ms"]=r["signal_ms"]
        horizons={}
        for h in HORIZONS:
            vals=[json.loads(r[f"h{h}"]) for r in rows if r[f"h{h}"]]
            horizons[str(h)]=horizon_summary(vals)
        reports.append({"parameter_id":pid,"family_id":param["family_id"],"parameters":param["parameters"],"event_count":len(rows),"long_horizons":horizons,"smoothness_identifiability":identifiability_by_metric(rows,"smooth"),"long_trend_groups":trend_groups(rows),"long_trend_features":{"uses_completed_4h_bars_only":True,"states":["UP","RANGE","DOWN"]},"long_trend_feature_summary":long_trend_feature_summary(rows)})
    event_count_total,symbol_count=conn.execute("select count(*),count(distinct symbol) from events").fetchone()
    report={"protocol":"ORBIT_RB2_LONG_CYCLE_REPORT_V1","contract_sha256":__import__("hashlib").sha256(RB2.read_bytes()).hexdigest(),"dataset_fingerprint":context["manifest"]["dataset_fingerprint"],"training_end_ms":end,"lockbox_opened":False,"lockbox_data_read":False,"selection_or_gate_effect":"NONE","horizons_candles":list(HORIZONS),"event_count_total":event_count_total,"symbol_count":symbol_count,"parameter_reports":reports,"honesty_boundary":["LONG_HORIZONS_ARE_COUNTERFACTUAL_PATHS_NOT_EXECUTED_RETURNS","SMOOTHNESS_AND_TREND_SLICES_REQUIRE_INDEPENDENT_VALIDATION","NO_LOCKBOX_DATA_READ"]}
    _write_exclusive(Path(args.out),report); conn.close(); print(json.dumps({"output":args.out,"parameters":len(reports)}))

if __name__=="__main__": main()
