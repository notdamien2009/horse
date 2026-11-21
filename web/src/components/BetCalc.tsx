"use client";
import { Calculator } from "lucide-react";
import { useState } from "react";
import { SITE } from "@/lib/site-config";

/** Back / lay returns after commission. Pure arithmetic on what the user types in. */
export function BetCalc() {
  const [side, setSide] = useState<"back" | "lay">("back");
  const [stake, setStake] = useState("10");
  const [price, setPrice] = useState("5.0");
  const [comm, setComm] = useState(String(SITE.commissionPct));
  const s = Number(stake), p = Number(price), c = Number(comm) / 100;
  const ok = s > 0 && p > 1 && c >= 0 && c < 1;
  // back: win +s(p-1)(1-c), lose -s.  lay (backer's stake s): horse loses +s(1-c), horse wins -s(p-1)
  const backWin = s * (p - 1) * (1 - c), backLose = -s;
  const layWin = s * (1 - c), layLose = -s * (p - 1);
  const be = (1 / (1 + (p - 1) * (1 - c))) * 100;
  const gbp = (v: number) => `${v < 0 ? "−" : "+"}£${Math.abs(v).toFixed(2)}`;
  return (
    <div className="mk-panel mk-calc">
      <h3><Calculator size={17} aria-hidden /> Back &amp; lay calculator</h3>
      <div className="mk-seg" role="group" aria-label="Bet type">
        <button type="button" aria-pressed={side === "back"} className={side === "back" ? "on" : ""} onClick={() => setSide("back")}>Back</button>
        <button type="button" aria-pressed={side === "lay"} className={side === "lay" ? "on" : ""} onClick={() => setSide("lay")}>Lay</button>
      </div>
      <div className="mk-fields">
        <label>{side === "back" ? "Stake £" : "Backer's stake £"}<input inputMode="decimal" value={stake} onChange={(e) => setStake(e.target.value)} /></label>
        <label>Price<input inputMode="decimal" value={price} onChange={(e) => setPrice(e.target.value)} /></label>
        <label>Commission %<input inputMode="decimal" value={comm} onChange={(e) => setComm(e.target.value)} /></label>
      </div>
      {ok ? (
        <div className="mk-out">
          <div><span>If the horse wins</span><b className={side === "back" ? "pos" : "neg"}>{gbp(side === "back" ? backWin : layLose)}</b></div>
          <div><span>If the horse loses</span><b className={side === "back" ? "neg" : "pos"}>{gbp(side === "back" ? backLose : layWin)}</b></div>
          <div><span>{side === "back" ? "Win chance needed to break even" : "Your liability"}</span><b>{side === "back" ? `${be.toFixed(1)}%` : `£${(s * (p - 1)).toFixed(2)}`}</b></div>
        </div>
      ) : <p className="mk-fine">Enter a stake above 0 and a price above 1.0.</p>}
    </div>
  );
}