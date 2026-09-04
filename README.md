# Shipment Axis Dashboard Public Production

Formal public dashboard for model-level and monthly shipment-axis aggregates.

This package publishes only the approved summary fields, monthly history, and model monthly aggregation. It is separate from the synthetic public demo and from the private real-data dashboard.

Run locally:

```powershell
python -m streamlit run app.py
```

Manual update flow:

1. Run the local approved export.
2. Run the public production security scan.
3. Run tests.
4. Commit and push only after every gate passes.
