# SOHU Maps API

SOHU Maps API is a null-safe, sign-aware mathematical geolocation API.

Core rule:

```text
missing coordinate != (0,0) != (+1,0,0)
```

It validates the mathematical coordinate object rather than treating latitude/longitude as merely two numbers.

## Endpoints

- `GET /`
- `POST /v1/point/validate`
- `POST /v1/route/validate`
- `POST /v1/track/sanity`
- `POST /v1/placeholder/axis`

## Local run

```bash
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8000
```

Then open:

```text
http://127.0.0.1:8000/docs
```

## Render deployment

Build command:

```bash
pip install -r requirements.txt
```

Start command:

```bash
uvicorn main:app --host 0.0.0.0 --port $PORT
```
