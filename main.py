from fastapi import FastAPI
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
import math

app = FastAPI(
    title="SOHU Maps API",
    version="0.1.0-beta",
    description=(
        "Null-safe, sign-aware mathematical geolocation API. "
        "SOHU Maps validates the mathematical coordinate object, not merely lat/lon as numbers."
    ),
)

EPS = 1e-12
EARTH_RADIUS_M = 6371008.8
WGS84_A = 6378137.0
WGS84_F = 1 / 298.257223563
WGS84_E2 = WGS84_F * (2 - WGS84_F)

class PointRequest(BaseModel):
    lat: Optional[float] = None
    lon: Optional[float] = None
    source: Optional[str] = None

class RouteRequest(BaseModel):
    lat1: Optional[float] = None
    lon1: Optional[float] = None
    lat2: Optional[float] = None
    lon2: Optional[float] = None
    n: int = 17

class TrackPoint(BaseModel):
    lat: Optional[float] = None
    lon: Optional[float] = None
    t: float

class TrackRequest(BaseModel):
    points: List[TrackPoint]
    max_speed_m_s: float = 350.0

class AxisPlaceholderRequest(BaseModel):
    axis: str
    sign: str


def normalize_longitude(lon: float) -> float:
    """Normalize longitude into [-180, 180], preserving explicit +180 when supplied."""
    out = ((float(lon) + 180.0) % 360.0) - 180.0
    if abs(out + 180.0) < EPS and float(lon) > 0:
        out = 180.0
    return out


def valid_latlon(lat, lon) -> bool:
    """Missing coordinates are invalid and are not coerced to (0,0)."""
    if lat is None or lon is None:
        return False
    try:
        lat = float(lat)
        lon = float(lon)
    except Exception:
        return False
    return -90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0


def sign_label(v: float) -> str:
    if abs(v) <= 1e-10:
        return "0"
    return "+" if v > 0 else "-"


def classify_corridor(x: float, y: float, z: float) -> str:
    sx = abs(x) <= 1e-10
    sy = abs(y) <= 1e-10
    sz = abs(z) <= 1e-10
    if sx and sy and not sz:
        return "polar_z_axis_degeneracy"
    if sy and sz and not sx:
        return "equator_x_axis_degeneracy"
    if sx and sz and not sy:
        return "equator_y_axis_degeneracy"
    if sx and not sy and not sz:
        return "x_zero_meridional_transition"
    if sy and not sx and not sz:
        return "y_zero_meridional_transition"
    if sz and not sx and not sy:
        return "z_zero_equatorial_transition"
    if not sx and not sy and not sz:
        return "ordinary_coordinate_sector"
    return "higher_order_coordinate_degeneracy"


def geodetic_to_ecef(lat_deg: float, lon_deg: float, h_m: float = 0.0) -> Dict[str, float]:
    lat = math.radians(lat_deg)
    lon = math.radians(lon_deg)
    sin_lat = math.sin(lat)
    cos_lat = math.cos(lat)
    N = WGS84_A / math.sqrt(1.0 - WGS84_E2 * sin_lat * sin_lat)
    return {
        "x_m": (N + h_m) * cos_lat * math.cos(lon),
        "y_m": (N + h_m) * cos_lat * math.sin(lon),
        "z_m": (N * (1.0 - WGS84_E2) + h_m) * sin_lat,
    }


def calculate_point(lat, lon) -> Dict[str, Any]:
    if not valid_latlon(lat, lon):
        return {
            "valid": False,
            "reason": "missing_or_invalid_coordinate",
            "message": "Coordinate preserved as NULL; not coerced to (0,0).",
        }

    lat = float(lat)
    lon = normalize_longitude(float(lon))
    phi = math.radians(lat)
    lam = math.radians(lon)

    x = math.cos(phi) * math.cos(lam)
    y = math.cos(phi) * math.sin(lam)
    z = math.sin(phi)

    x = 0.0 if abs(x) <= EPS else x
    y = 0.0 if abs(y) <= EPS else y
    z = 0.0 if abs(z) <= EPS else z

    suppressed = [axis for axis, val in zip(["x", "y", "z"], [x, y, z]) if abs(val) <= 1e-10]

    theta = math.radians(lon) % (2.0 * math.pi)
    n3 = x * y * z
    n3_norm = 3.0 * math.sqrt(3.0) * n3
    tri = math.sqrt(1.5 * ((x*x - 1/3)**2 + (y*y - 1/3)**2 + (z*z - 1/3)**2))
    q4 = (x**4 + y**4 + z**4 - 1/3) / (1 - 1/3)
    phi_golden = (1.0 + math.sqrt(5.0)) / 2.0
    rho = phi_golden ** -2
    phase_fraction = theta / (2.0 * math.pi)
    golden_phase_distance = abs(phase_fraction - rho)
    golden_phase_distance = min(golden_phase_distance, 1.0 - golden_phase_distance)
    derr = math.sqrt(0.5 * (tri**2 + (1.0 - abs(n3_norm))**2))

    warnings = []
    if abs(lat) <= 1e-10 and abs(lon) <= 1e-10:
        warnings.append("explicit_0_0_is_positive_x_axis_not_neutral")
    if abs(lat) <= 1e-10 and abs(abs(lon) - 180.0) <= 1e-10:
        warnings.append("explicit_antimeridian_is_negative_x_axis")
    if suppressed:
        warnings.append("coordinate_axis_or_transition_corridor")

    return {
        "valid": True,
        "lat": lat,
        "lon": lon,
        "unit_vector": {"x": x, "y": y, "z": z},
        "ecef_wgs84_m": geodetic_to_ecef(lat, lon),
        "sign_sector": f"{sign_label(x)}{sign_label(y)}{sign_label(z)}",
        "suppressed_axes": suppressed,
        "corridor_class": classify_corridor(x, y, z),
        "metrics": {
            "theta_rad": theta,
            "theta_deg": lon % 360.0,
            "Z2_y_sector": sign_label(y),
            "Tri_residual": tri,
            "phi_golden": phi_golden,
            "rho": rho,
            "golden_phase_distance": golden_phase_distance,
            "N3_xyz": n3,
            "N3_normalized": n3_norm,
            "Q4_concentration": q4,
            "DERR_cubic_augmented": derr,
        },
        "warnings": warnings,
    }


def haversine_distance_m(lat1, lon1, lat2, lon2) -> Optional[float]:
    if not (valid_latlon(lat1, lon1) and valid_latlon(lat2, lon2)):
        return None
    phi1 = math.radians(float(lat1))
    phi2 = math.radians(float(lat2))
    dphi = phi2 - phi1
    lam1 = math.radians(normalize_longitude(float(lon1)))
    lam2 = math.radians(normalize_longitude(float(lon2)))
    dlam = (lam2 - lam1 + math.pi) % (2.0 * math.pi) - math.pi
    a = math.sin(dphi/2)**2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam/2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(max(0.0, 1.0 - a)))
    return EARTH_RADIUS_M * c


def initial_bearing_deg(lat1, lon1, lat2, lon2) -> Optional[float]:
    if not (valid_latlon(lat1, lon1) and valid_latlon(lat2, lon2)):
        return None
    phi1 = math.radians(float(lat1))
    phi2 = math.radians(float(lat2))
    lam1 = math.radians(normalize_longitude(float(lon1)))
    lam2 = math.radians(normalize_longitude(float(lon2)))
    dlam = (lam2 - lam1 + math.pi) % (2.0 * math.pi) - math.pi
    y = math.sin(dlam) * math.cos(phi2)
    x = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(dlam)
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0


def interpolate_route(lat1, lon1, lat2, lon2, n: int = 17) -> List[Dict[str, float]]:
    p1 = calculate_point(lat1, lon1)
    p2 = calculate_point(lat2, lon2)
    if not p1.get("valid") or not p2.get("valid"):
        return []
    a = [p1["unit_vector"]["x"], p1["unit_vector"]["y"], p1["unit_vector"]["z"]]
    b = [p2["unit_vector"]["x"], p2["unit_vector"]["y"], p2["unit_vector"]["z"]]
    dot = max(-1.0, min(1.0, sum(a[i] * b[i] for i in range(3))))
    omega = math.acos(dot)
    n = max(2, int(n))
    points = []
    for i in range(n):
        t = i / (n - 1)
        if abs(omega) < EPS:
            x, y, z = a
        else:
            s1 = math.sin((1 - t) * omega) / math.sin(omega)
            s2 = math.sin(t * omega) / math.sin(omega)
            x = s1 * a[0] + s2 * b[0]
            y = s1 * a[1] + s2 * b[1]
            z = s1 * a[2] + s2 * b[2]
        norm = math.sqrt(x*x + y*y + z*z)
        x, y, z = x / norm, y / norm, z / norm
        lat = math.degrees(math.asin(z))
        lon = normalize_longitude(math.degrees(math.atan2(y, x)))
        points.append({"i": i, "t": t, "lat": lat, "lon": lon, "x": x, "y": y, "z": z})
    return points


def split_antimeridian(points: List[Dict[str, float]]) -> List[List[Dict[str, float]]]:
    if not points:
        return []
    segments = [[points[0]]]
    for prev, cur in zip(points[:-1], points[1:]):
        if abs(cur["lon"] - prev["lon"]) > 180.0:
            segments.append([cur])
        else:
            segments[-1].append(cur)
    return segments


def axis_placeholder(axis: str, sign: str) -> Dict[str, Any]:
    axis = axis.lower().strip()
    sign = sign.strip()
    if axis not in {"x", "y", "z"}:
        return {"valid": False, "reason": "axis_must_be_x_y_or_z"}
    if sign not in {"+", "-"}:
        return {"valid": False, "reason": "sign_must_be_plus_or_minus"}
    s = 1.0 if sign == "+" else -1.0
    x = y = z = 0.0
    if axis == "x":
        x = s
        lat, lon = 0.0, 0.0 if sign == "+" else 180.0
    elif axis == "y":
        y = s
        lat, lon = 0.0, 90.0 if sign == "+" else -90.0
    else:
        z = s
        lat, lon = 90.0 if sign == "+" else -90.0, None
    return {
        "valid": True,
        "placeholder_axis": axis,
        "placeholder_sign": sign,
        "unit_vector": {"x": x, "y": y, "z": z},
        "lat": lat,
        "lon": lon,
        "warning": "Explicit axis placeholder, not an observed coordinate. Prefer NULL for true missing data.",
    }


def speed_sanity_segments(points: List[TrackPoint], max_speed_m_s: float = 350.0) -> List[Dict[str, Any]]:
    rows = []
    for i in range(len(points) - 1):
        a = points[i]
        b = points[i + 1]
        dt = float(b.t) - float(a.t)
        if dt <= 0:
            rows.append({"segment": i, "valid": False, "reason": "non_positive_dt"})
            continue
        d = haversine_distance_m(a.lat, a.lon, b.lat, b.lon)
        if d is None:
            rows.append({"segment": i, "valid": False, "reason": "missing_or_invalid_coordinate"})
            continue
        speed = d / dt
        rows.append({
            "segment": i,
            "valid": True,
            "distance_m": d,
            "dt_s": dt,
            "speed_m_s": speed,
            "is_outlier": speed > max_speed_m_s,
        })
    return rows


@app.get("/")
def root():
    return {
        "name": "SOHU Maps API",
        "status": "ok",
        "version": "0.1.0-beta",
        "rule": "missing coordinates remain NULL, not (0,0)",
        "docs": "/docs",
    }

@app.post("/v1/point/validate")
def validate_point(req: PointRequest):
    result = calculate_point(req.lat, req.lon)
    result["source"] = req.source
    return result

@app.post("/v1/route/validate")
def validate_route(req: RouteRequest):
    d = haversine_distance_m(req.lat1, req.lon1, req.lat2, req.lon2)
    brng = initial_bearing_deg(req.lat1, req.lon1, req.lat2, req.lon2)
    if d is None:
        return {"valid": False, "reason": "missing_or_invalid_coordinate"}
    naive_delta = abs(float(req.lon2) - float(req.lon1))
    wrapped_delta = abs(((float(req.lon2) - float(req.lon1) + 180.0) % 360.0) - 180.0)
    points = interpolate_route(req.lat1, req.lon1, req.lat2, req.lon2, req.n)
    segments = split_antimeridian(points)
    return {
        "valid": True,
        "distance_m": d,
        "distance_km": d / 1000.0,
        "initial_bearing_deg": brng,
        "naive_abs_delta_lon_deg": naive_delta,
        "wrapped_abs_delta_lon_deg": wrapped_delta,
        "crosses_antimeridian_naive": naive_delta > 180.0,
        "display_segment_count": len(segments),
        "route_points": points,
        "display_segments": segments,
    }

@app.post("/v1/track/sanity")
def track_sanity(req: TrackRequest):
    segments = speed_sanity_segments(req.points, req.max_speed_m_s)
    return {
        "valid": True,
        "segment_count": len(segments),
        "outlier_count": sum(1 for s in segments if s.get("is_outlier")),
        "invalid_segment_count": sum(1 for s in segments if not s.get("valid")),
        "segments": segments,
    }

@app.post("/v1/placeholder/axis")
def placeholder_axis(req: AxisPlaceholderRequest):
    return axis_placeholder(req.axis, req.sign)
