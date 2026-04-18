import logging
import os
import threading
import time
import importlib
import json
import hashlib
from pathlib import Path
from typing import Any, Dict, List, Optional

import cv2
import numpy as np
import requests
from ultralytics import YOLO

logger = logging.getLogger("CVModule")

# Set this to your Android camera stream URL (Tailscale IP)
ANDROID_CAMERA_URL = os.getenv("ANDROID_CAMERA_URL", "http://100.64.88.85:8080/stream")

# Roboflow settings (free account key/model)
ROBOFLOW_API_KEY = os.getenv("ROBOFLOW_API_KEY", "REPLACE_WITH_ROBOFLOW_API_KEY")
ROBOFLOW_API_URL = os.getenv("ROBOFLOW_API_URL", "https://serverless.roboflow.com")
ROBOFLOW_MODEL_ID = os.getenv("ROBOFLOW_MODEL_ID", "")
ROBOFLOW_MIN_CONFIDENCE = float(os.getenv("ROBOFLOW_MIN_CONFIDENCE", "0.35"))
ROBOFLOW_MODEL_URL = os.getenv(
    "ROBOFLOW_MODEL_URL",
    "https://detect.roboflow.com/REPLACE_WITH_MODEL_NAME/1",
)
YOLO_MODEL_PATH = os.getenv("YOLO_MODEL_PATH", "models/yolov8n.pt")

CV_POLL_INTERVAL_SECONDS = float(os.getenv("CV_POLL_INTERVAL_SECONDS", "0.25"))
CV_CAMERA_STALE_GRABS = int(os.getenv("CV_CAMERA_STALE_GRABS", "2"))
CV_READ_FAILURE_RESET_THRESHOLD = int(os.getenv("CV_READ_FAILURE_RESET_THRESHOLD", "3"))
CV_ANALYZE_INTERVAL_SECONDS = float(os.getenv("CV_ANALYZE_INTERVAL_SECONDS", "2.5"))
CV_RESULT_CACHE_SECONDS = float(os.getenv("CV_RESULT_CACHE_SECONDS", "120"))
TRAFFIC_LIGHT_RED_THRESHOLD = float(os.getenv("TRAFFIC_LIGHT_RED_THRESHOLD", "0.18"))
CV_PRELOAD_YOLO = os.getenv("CV_PRELOAD_YOLO", "false").strip().lower() in {"1", "true", "yes", "on"}
ROBOFLOW_MAX_DIMENSION = int(os.getenv("ROBOFLOW_MAX_DIMENSION", "640"))
ROAD_DAMAGE_REPORTS_ENABLED = os.getenv("ROAD_DAMAGE_REPORTS_ENABLED", "true").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
ROAD_DAMAGE_SNAPSHOT_MIN_INTERVAL_SECONDS = float(
    os.getenv("ROAD_DAMAGE_SNAPSHOT_MIN_INTERVAL_SECONDS", "8.0")
)
ROAD_DAMAGE_DEDUP_WINDOW_SECONDS = float(
    os.getenv("ROAD_DAMAGE_DEDUP_WINDOW_SECONDS", "180.0")
)
ROAD_DAMAGE_MIN_COUNT_FOR_REPORT = int(os.getenv("ROAD_DAMAGE_MIN_COUNT_FOR_REPORT", "1"))
ROAD_DAMAGE_REPORTS_DIR = Path(os.getenv("ROAD_DAMAGE_REPORTS_DIR", "reports")).resolve()
REVERSE_GEOCODE_ENABLED = os.getenv("REVERSE_GEOCODE_ENABLED", "true").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
REVERSE_GEOCODE_API_URL = os.getenv("REVERSE_GEOCODE_API_URL", "https://nominatim.openstreetmap.org/reverse")
REVERSE_GEOCODE_TIMEOUT_SECONDS = float(os.getenv("REVERSE_GEOCODE_TIMEOUT_SECONDS", "4.0"))
REVERSE_GEOCODE_USER_AGENT = os.getenv(
    "REVERSE_GEOCODE_USER_AGENT",
    "CivicBotRoadDamageReporter/1.0 (OpenStreetMap Nominatim)",
)

_lock = threading.Lock()
_running = False
_thread: Optional[threading.Thread] = None
_latest_context: Dict[str, Any] = {
    "updated_at": 0,
    "summary": "CV offline: not started yet.",
    "road_damage_count": 0,
    "road_damage_labels": [],
    "last_report_path": None,
    "location": None,
}

_yolo_model: Optional[YOLO] = None
_video_capture: Optional[cv2.VideoCapture] = None
_roboflow_client: Optional[Any] = None
_roboflow_client_failed = False
_inference_http_client_cls: Optional[Any] = None
_last_report_saved_at = 0.0
_geocode_cache: Dict[str, Dict[str, str]] = {}
_last_inference_signature: Optional[str] = None
_last_inference_result: Optional[Dict[str, Any]] = None
_last_inference_at = 0.0
_last_detection_fingerprint: Optional[str] = None
_last_detection_fingerprint_at = 0.0


def _update_summary(summary: str) -> None:
    with _lock:
        _latest_context["updated_at"] = int(time.time())
        _latest_context["summary"] = summary


def _update_road_damage_state(count: int, labels: List[str]) -> None:
    with _lock:
        _latest_context["road_damage_count"] = int(count)
        _latest_context["road_damage_labels"] = list(labels)


def update_location(latitude: float, longitude: float, source: str = "unknown") -> None:
    with _lock:
        _latest_context["location"] = {
            "latitude": float(latitude),
            "longitude": float(longitude),
            "source": source,
            "updated_at": int(time.time()),
        }


def get_context_payload() -> Dict[str, Any]:
    with _lock:
        return {
            "updated_at": _latest_context.get("updated_at", 0),
            "summary": _latest_context.get("summary", "CV context unavailable."),
            "road_damage_count": _latest_context.get("road_damage_count", 0),
            "road_damage_labels": list(_latest_context.get("road_damage_labels", [])),
            "last_report_path": _latest_context.get("last_report_path"),
            "location": _latest_context.get("location"),
            "min_confidence": float(ROBOFLOW_MIN_CONFIDENCE),
        }


def update_runtime_config(min_confidence: Optional[float] = None) -> Dict[str, Any]:
    global ROBOFLOW_MIN_CONFIDENCE

    if min_confidence is not None:
        bounded = max(0.0, min(1.0, float(min_confidence)))
        ROBOFLOW_MIN_CONFIDENCE = bounded
        logger.info("[CV] Updated ROBOFLOW_MIN_CONFIDENCE=%s", ROBOFLOW_MIN_CONFIDENCE)

    return {
        "min_confidence": float(ROBOFLOW_MIN_CONFIDENCE),
    }


def _reverse_geocode(location: Optional[Dict[str, Any]]) -> Dict[str, str]:
    if not REVERSE_GEOCODE_ENABLED or not location:
        return {"state": "unknown", "place": "unknown"}

    lat = location.get("latitude")
    lon = location.get("longitude")
    if lat is None or lon is None:
        return {"state": "unknown", "place": "unknown"}

    try:
        lat_f = float(lat)
        lon_f = float(lon)
    except (TypeError, ValueError):
        return {"state": "unknown", "place": "unknown"}

    # Coarse cache key keeps requests low while driving around nearby points.
    cache_key = f"{lat_f:.4f},{lon_f:.4f}"
    cached = _geocode_cache.get(cache_key)
    if cached is not None:
        return cached

    try:
        response = requests.get(
            REVERSE_GEOCODE_API_URL,
            params={
                "format": "jsonv2",
                "lat": lat_f,
                "lon": lon_f,
                "zoom": 14,
                "addressdetails": 1,
            },
            headers={"User-Agent": REVERSE_GEOCODE_USER_AGENT},
            timeout=REVERSE_GEOCODE_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        payload = response.json() if response.content else {}
        address = payload.get("address", {}) if isinstance(payload, dict) else {}

        state = str(address.get("state") or address.get("state_district") or "unknown")
        place = str(
            address.get("city")
            or address.get("town")
            or address.get("village")
            or address.get("suburb")
            or address.get("municipality")
            or address.get("county")
            or "unknown"
        )
        result = {"state": state, "place": place}
        _geocode_cache[cache_key] = result
        return result
    except Exception as exc:
        logger.warning("[CV] Reverse geocode failed: %s", exc)
        return {"state": "unknown", "place": "unknown"}


def _build_maps_link(location: Optional[Dict[str, Any]]) -> str:
    if not location:
        return "unknown"

    lat = location.get("latitude")
    lon = location.get("longitude")
    if lat is None or lon is None:
        return "unknown"

    return f"https://www.google.com/maps?q={lat},{lon}"


def _write_sidecar_text_report(
    image_path: Path,
    labels: List[str],
    count: int,
    location: Optional[Dict[str, Any]],
) -> Optional[str]:
    txt_path = image_path.with_suffix(".txt")
    geo = _reverse_geocode(location)
    maps_link = _build_maps_link(location)

    primary_problem = labels[0] if labels else "damaged road"
    problems = ", ".join(labels) if labels else "damaged road"

    lines = [
        f"screenshot_file={image_path.name}",
        f"problem={primary_problem}",
        f"problem_labels={problems}",
        f"problem_count={int(count)}",
        f"map_link={maps_link}",
        f"state={geo.get('state', 'unknown')}",
        f"place={geo.get('place', 'unknown')}",
    ]

    if location:
        lines.append(f"latitude={location.get('latitude', 'unknown')}")
        lines.append(f"longitude={location.get('longitude', 'unknown')}")
        lines.append(f"location_source={location.get('source', 'unknown')}")

    try:
        txt_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return str(txt_path)
    except Exception as exc:
        logger.warning("[CV] Failed to write sidecar text report: %s", exc)
        return None


def _maybe_save_road_damage_report(
    frame: np.ndarray,
    road_damage: Dict[str, Any],
    frame_signature: str,
) -> Optional[str]:
    global _last_report_saved_at, _last_detection_fingerprint, _last_detection_fingerprint_at

    if not ROAD_DAMAGE_REPORTS_ENABLED:
        return None

    count = int(road_damage.get("count", 0))
    if count < ROAD_DAMAGE_MIN_COUNT_FOR_REPORT:
        return None

    now = time.time()
    if (now - _last_report_saved_at) < ROAD_DAMAGE_SNAPSHOT_MIN_INTERVAL_SECONDS:
        return None

    timestamp = int(now)
    report_dir = ROAD_DAMAGE_REPORTS_DIR
    snapshots_dir = report_dir / "snapshots"
    snapshots_dir.mkdir(parents=True, exist_ok=True)
    events_path = report_dir / "events.jsonl"

    image_path = snapshots_dir / f"road_damage_{timestamp}.jpg"
    ok = cv2.imwrite(str(image_path), frame)
    if not ok:
        return None

    with _lock:
        location = _latest_context.get("location")

    labels = list(road_damage.get("labels", []))
    detection_fingerprint = _compute_detection_fingerprint(labels, frame_signature, location)

    if (
        _last_detection_fingerprint == detection_fingerprint
        and (now - _last_detection_fingerprint_at) < ROAD_DAMAGE_DEDUP_WINDOW_SECONDS
    ):
        logger.info(
            "[CV] Duplicate road-damage event suppressed (fingerprint match within %.1fs)",
            ROAD_DAMAGE_DEDUP_WINDOW_SECONDS,
        )
        return None

    event = {
        "timestamp": timestamp,
        "road_damage_count": count,
        "labels": labels,
        "snapshot_path": str(image_path),
        "location": location,
    }

    text_report_path = _write_sidecar_text_report(
        image_path=image_path,
        labels=labels,
        count=count,
        location=location,
    )
    event["text_report_path"] = text_report_path

    with events_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")

    _last_report_saved_at = now
    _last_detection_fingerprint = detection_fingerprint
    _last_detection_fingerprint_at = now
    with _lock:
        _latest_context["last_report_path"] = str(image_path)

    logger.info(
        "[CV] Report saved snapshot=%s text=%s gps=%s",
        image_path,
        text_report_path or "none",
        location or "none",
    )
    return str(image_path)


def _load_models() -> None:
    global _yolo_model
    if _yolo_model is None:
        model_path = Path(YOLO_MODEL_PATH)
        if model_path.parent and str(model_path.parent) not in {"", "."}:
            model_path.parent.mkdir(parents=True, exist_ok=True)

        # Auto-downloads once when missing; persists if folder is bind-mounted.
        _yolo_model = YOLO(str(model_path))
        logger.info("Loaded YOLO model from %s.", model_path)


def _open_camera() -> bool:
    global _video_capture
    if _video_capture is not None and _video_capture.isOpened():
        return True

    _video_capture = cv2.VideoCapture(ANDROID_CAMERA_URL)
    # Prefer freshest frame from MJPEG stream to reduce perceived detection delay.
    try:
        _video_capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    except Exception:
        pass

    opened = _video_capture.isOpened()
    if not opened:
        logger.warning("Unable to open Android camera stream at %s", ANDROID_CAMERA_URL)
    return opened


def _reset_camera_capture(reason: str) -> None:
    global _video_capture

    logger.warning("[CV] Resetting camera capture: %s", reason)
    try:
        if _video_capture is not None:
            _video_capture.release()
    except Exception:
        pass
    _video_capture = None


def _prepare_roboflow_frame(frame: np.ndarray) -> np.ndarray:
    h, w = frame.shape[:2]
    max_dim = max(h, w)
    if max_dim <= ROBOFLOW_MAX_DIMENSION or ROBOFLOW_MAX_DIMENSION <= 0:
        return frame

    scale = float(ROBOFLOW_MAX_DIMENSION) / float(max_dim)
    new_w = max(1, int(w * scale))
    new_h = max(1, int(h * scale))
    return cv2.resize(frame, (new_w, new_h), interpolation=cv2.INTER_LINEAR)


def _compute_frame_signature(frame: np.ndarray) -> str:
    tiny = cv2.resize(frame, (32, 18), interpolation=cv2.INTER_AREA)
    gray = cv2.cvtColor(tiny, cv2.COLOR_BGR2GRAY)
    return hashlib.sha1(gray.tobytes()).hexdigest()


def _compute_detection_fingerprint(
    labels: List[str],
    frame_signature: str,
    location: Optional[Dict[str, Any]],
) -> str:
    sorted_labels = ",".join(sorted(labels)) if labels else "none"
    lat_val = location.get("latitude") if location else None
    lon_val = location.get("longitude") if location else None
    if lat_val is not None and lon_val is not None:
        try:
            lat = round(float(lat_val), 4)
            lon = round(float(lon_val), 4)
            geo = f"{lat},{lon}"
        except Exception:
            geo = "unknown"
    else:
        geo = "unknown"

    raw = f"{sorted_labels}|{geo}|{frame_signature[:20]}"
    return hashlib.sha1(raw.encode("utf-8", errors="ignore")).hexdigest()


def _get_roboflow_client() -> Optional[Any]:
    global _roboflow_client, _roboflow_client_failed, _inference_http_client_cls

    if _roboflow_client is not None:
        return _roboflow_client
    if _roboflow_client_failed:
        return None

    if not ROBOFLOW_API_KEY or ROBOFLOW_API_KEY == "REPLACE_WITH_ROBOFLOW_API_KEY":
        return None
    if not ROBOFLOW_MODEL_ID:
        return None

    if _inference_http_client_cls is None:
        try:
            inference_sdk_module = importlib.import_module("inference_sdk")
            _inference_http_client_cls = getattr(inference_sdk_module, "InferenceHTTPClient", None)
        except Exception:
            _inference_http_client_cls = None

    if _inference_http_client_cls is None:
        return None

    try:
        _roboflow_client = _inference_http_client_cls(
            api_url=ROBOFLOW_API_URL,
            api_key=ROBOFLOW_API_KEY,
        )
        logger.info("Roboflow inference_sdk client initialized for model_id=%s", ROBOFLOW_MODEL_ID)
        return _roboflow_client
    except Exception as exc:
        _roboflow_client_failed = True
        logger.warning("Failed to initialize Roboflow inference_sdk client: %s", exc)
        return None


def _is_traffic_light_red(frame: np.ndarray, xyxy: List[float]) -> bool:
    h, w = frame.shape[:2]
    x1, y1, x2, y2 = [int(v) for v in xyxy]
    x1 = max(0, min(x1, w - 1))
    y1 = max(0, min(y1, h - 1))
    x2 = max(0, min(x2, w))
    y2 = max(0, min(y2, h))

    if x2 <= x1 or y2 <= y1:
        return False

    crop = frame[y1:y2, x1:x2]
    if crop.size == 0:
        return False

    top_h = max(1, int(crop.shape[0] * 0.4))
    top_crop = crop[:top_h, :]

    hsv = cv2.cvtColor(top_crop, cv2.COLOR_BGR2HSV)
    lower_red_1 = np.array([0, 90, 90])
    upper_red_1 = np.array([10, 255, 255])
    lower_red_2 = np.array([160, 90, 90])
    upper_red_2 = np.array([180, 255, 255])

    mask1 = cv2.inRange(hsv, lower_red_1, upper_red_1)
    mask2 = cv2.inRange(hsv, lower_red_2, upper_red_2)
    red_mask = cv2.bitwise_or(mask1, mask2)

    red_ratio = float(np.count_nonzero(red_mask)) / float(red_mask.size)
    return red_ratio >= TRAFFIC_LIGHT_RED_THRESHOLD


def _run_roboflow(frame: np.ndarray, frame_signature: str) -> Dict[str, Any]:
    global _last_inference_signature, _last_inference_result, _last_inference_at

    now = time.time()
    if (
        _last_inference_result is not None
        and _last_inference_signature == frame_signature
        and (now - _last_inference_at) <= CV_RESULT_CACHE_SECONDS
    ):
        cached = dict(_last_inference_result)
        cached["cached"] = True
        return cached

    if not ROBOFLOW_API_KEY or ROBOFLOW_API_KEY == "REPLACE_WITH_ROBOFLOW_API_KEY":
        return {"enabled": False, "count": 0, "labels": []}

    try:
        client = _get_roboflow_client()
        if client is not None and ROBOFLOW_MODEL_ID:
            # Live camera stream support: infer directly on the current frame.
            rf_frame = _prepare_roboflow_frame(frame)
            payload = client.infer(rf_frame, model_id=ROBOFLOW_MODEL_ID)
            predictions_raw = payload.get("predictions", []) or []
            predictions = [
                p for p in predictions_raw
                if float(p.get("confidence", 1.0)) >= ROBOFLOW_MIN_CONFIDENCE
            ]
            labels = [p.get("class", "unknown") for p in predictions]
            result = {
                "enabled": True,
                "count": len(predictions),
                "labels": labels[:8],
            }
            _last_inference_signature = frame_signature
            _last_inference_result = dict(result)
            _last_inference_at = now
            return result

        ok, encoded = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
        if not ok:
            return {"enabled": True, "count": 0, "labels": []}

        # Fallback for legacy detect endpoint (kept for compatibility).
        response = requests.post(
            ROBOFLOW_MODEL_URL,
            params={"api_key": ROBOFLOW_API_KEY},
            data=encoded.tobytes(),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=8,
        )
        response.raise_for_status()
        payload = response.json()
        predictions_raw = payload.get("predictions", []) or []
        predictions = [
            p for p in predictions_raw
            if float(p.get("confidence", 1.0)) >= ROBOFLOW_MIN_CONFIDENCE
        ]
        labels = [p.get("class", "unknown") for p in predictions]
        result = {
            "enabled": True,
            "count": len(predictions),
            "labels": labels[:8],
        }
        _last_inference_signature = frame_signature
        _last_inference_result = dict(result)
        _last_inference_at = now
        return result
    except Exception as exc:
        logger.warning("Roboflow inference failed: %s", exc)
        return {"enabled": True, "count": 0, "labels": []}


def _analyze_frame(frame: np.ndarray) -> str:
    if _yolo_model is None:
        try:
            _load_models()
        except Exception as exc:
            logger.warning("YOLO lazy init failed: %s", exc)
            return f"CV offline: YOLO model unavailable ({exc})."

    if _yolo_model is None:
        return "CV offline: YOLO model unavailable after initialization attempt."

    yolo_result = _yolo_model(frame, verbose=False)[0]
    names = yolo_result.names
    classes = yolo_result.boxes.cls.tolist() if yolo_result.boxes is not None else []

    detected_labels: List[str] = []
    traffic_light_boxes: List[List[float]] = []

    for i, cls_id in enumerate(classes):
        cls_name = names.get(int(cls_id), str(cls_id))
        detected_labels.append(cls_name)
        if cls_name == "traffic light" and yolo_result.boxes is not None:
            xyxy = yolo_result.boxes.xyxy[i].tolist()
            traffic_light_boxes.append(xyxy)

    red_light = any(_is_traffic_light_red(frame, box) for box in traffic_light_boxes)
    frame_signature = _compute_frame_signature(frame)
    road_damage = _run_roboflow(frame, frame_signature)
    _update_road_damage_state(road_damage.get("count", 0), road_damage.get("labels", []))
    report_path = _maybe_save_road_damage_report(frame, road_damage, frame_signature)

    if road_damage.get("enabled"):
        labels = road_damage.get("labels", []) or []
        logger.info(
            "[CV] RoadDamage count=%s labels=%s cached=%s",
            road_damage.get("count", 0),
            ",".join(labels) if labels else "none",
            str(road_damage.get("cached", False)).lower(),
        )
    else:
        logger.info("[CV] RoadDamage disabled (missing key/model).")

    key_targets = [
        l for l in detected_labels if l in {"person", "car", "motorcycle", "traffic light"}
    ]

    parts = [
        f"YOLO key detections: {', '.join(key_targets[:8]) if key_targets else 'none'}.",
        f"Traffic light status: {'RED' if red_light else 'not red/unknown'}.",
    ]

    if road_damage.get("enabled"):
        labels = road_damage.get("labels", [])
        if labels:
            parts.append(
                f"Road damage model: {road_damage.get('count', 0)} findings ({', '.join(labels)})."
            )
        else:
            parts.append("Road damage model: no findings.")
    else:
        parts.append("Road damage model disabled (set ROBOFLOW_API_KEY).")

    if report_path:
        parts.append("Road damage report saved.")

    return " ".join(parts)


def _worker() -> None:
    global _running
    logger.info("CV worker started.")
    consecutive_read_failures = 0
    last_analyze_at = 0.0

    if CV_PRELOAD_YOLO:
        try:
            _load_models()
        except Exception as exc:
            _update_summary(f"CV failed to initialize models: {exc}")
            logger.exception("CV model init failed")
            _running = False
            return

    while _running:
        try:
            if not _open_camera():
                _update_summary("CV waiting for Android camera stream...")
                time.sleep(CV_POLL_INTERVAL_SECONDS)
                continue

            assert _video_capture is not None

            # Drain a few queued frames so inference uses the newest image.
            for _ in range(max(0, CV_CAMERA_STALE_GRABS)):
                _video_capture.grab()

            ok, frame = _video_capture.read()
            if not ok or frame is None:
                consecutive_read_failures += 1
                _update_summary("CV could not read frame from camera stream.")

                if consecutive_read_failures >= max(1, CV_READ_FAILURE_RESET_THRESHOLD):
                    _reset_camera_capture(
                        f"{consecutive_read_failures} consecutive frame read failures"
                    )
                    consecutive_read_failures = 0

                time.sleep(CV_POLL_INTERVAL_SECONDS)
                continue

            consecutive_read_failures = 0

            now = time.time()
            if (now - last_analyze_at) < max(0.05, CV_ANALYZE_INTERVAL_SECONDS):
                continue
            last_analyze_at = now

            summary = _analyze_frame(frame)
            _update_summary(summary)
            logger.info("[CV] %s", summary)
        except Exception as exc:
            logger.warning("CV loop error: %s", exc)
            _update_summary(f"CV temporary error: {exc}")
            _reset_camera_capture(f"loop exception: {exc}")
            consecutive_read_failures = 0
        finally:
            time.sleep(CV_POLL_INTERVAL_SECONDS)

    logger.info("CV worker stopped.")


def start() -> None:
    global _running, _thread
    if _running:
        return

    _running = True
    _thread = threading.Thread(target=_worker, daemon=True, name="cv-module-thread")
    _thread.start()


def get_context() -> str:
    with _lock:
        updated_at = _latest_context.get("updated_at", 0)
        summary = _latest_context.get("summary", "CV context unavailable.")

    if updated_at:
        age = int(time.time()) - int(updated_at)
        return f"{summary} (updated {age}s ago)"
    return summary
