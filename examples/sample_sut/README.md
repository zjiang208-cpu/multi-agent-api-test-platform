# Standalone FastAPI Sample SUT

Run from the repository root:

```powershell
python -m uvicorn examples.sample_sut.main:app --host 127.0.0.1 --port 18281
```

The platform can use its generated OpenAPI document at
`http://127.0.0.1:18281/openapi.json` when remote source loading is explicitly
enabled, or use the checked-in generic `examples/requirements/sample-openapi.yaml`
contract.

