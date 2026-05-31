# Runbook: Regime Flip Storm

## Trigger
The `astraeus_reco_regime_label` metric changes more than 3 times in 7 days, or structured logs show repeated `regime_label_committed` events.

## What it means
The HMM regime detector is oscillating between states rapidly. This usually indicates:
- A genuine market regime transition (e.g., entering a crisis)
- Stale or noisy input features
- Model degradation (HMM needs refitting)

The stability filter prevents flip-flopping from reaching downstream stages, but frequent raw flips are a signal that something needs attention.

## Diagnosis

1. **Check recent regime history:**
   ```sql
   SELECT r.run_date, rs.label, rs.probability, rs.model
   FROM regime_state rs
   JOIN recommender_run r ON r.run_id = rs.run_id
   WHERE r.run_date >= CURRENT_DATE - INTERVAL '14 days'
   ORDER BY r.run_date DESC;
   ```

2. **Check stability filter state** in logs:
   ```
   grep "regime_label_committed" /var/log/astraeus/recommender.log | tail -10
   ```

3. **Compare to ground truth:**
   - VIX level: is it in the top tercile (>25)?
   - Has there been a macro event (rate decision, geopolitical shock)?
   - Check if the flip pattern correlates with real market stress

## Resolution

### If flips correlate with real market stress
This is expected behavior. The stability filter is doing its job — holding the committed label until the new regime stabilizes. No action needed unless the committed label is clearly wrong for >5 days.

### If flips are noise (market is calm, VIX normal)
1. **Check input features for staleness:**
   ```sql
   SELECT feature_name, MAX(event_ts) as latest
   FROM feature_price_derived_low_vol_60d
   GROUP BY feature_name;
   ```
   If features are >2 days stale, the feature pipeline has a problem (not a regime problem).

2. **Consider refitting the HMM:**
   The model may have drifted. Trigger a refit with recent data:
   ```python
   from astraeus_regime.fitting import fit_from_market_bars
   await fit_from_market_bars(session, detector, symbols, lookback_days=756)
   ```

3. **Increase stability threshold temporarily:**
   If the storm is transient, bump `stability_threshold_days` from 3 to 5 in config. This makes the filter more conservative.

### If the committed label is wrong
Override the regime manually for the day's run by setting `regime_label` in the pipeline config. This is a temporary measure — file a ticket to investigate why the model is miscalibrating.

## Prevention
- Monthly HMM refit (scheduled task)
- Track regime mis-classification rate vs VIX terciles weekly
- Alert on flip frequency > 3/week
