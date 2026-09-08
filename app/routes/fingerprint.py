from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Request,
    WebSocket,
    WebSocketDisconnect,
)
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from app.core.database import get_db, SessionLocal
from app.models.user import User, FingerprintStatus, EnrollmentStep
from fastapi.responses import PlainTextResponse
import random
from pydantic import BaseModel
from datetime import datetime, timedelta
from app.models.attendance import Attendance, AttendanceStatus
from app.models.events import Event
from app.models.device import DeviceState
from app.utils.device import (
    get_device_state,
    get_all_device_states,
    get_online_devices,
    set_mode_on_all_devices,
    set_system_target_device,
    clear_system_target_device,
    get_system_target_device,
    set_active_event_on_all_devices,
    ensure_all_devices_free,
    is_device_online,
    DEFAULT_DEVICE_ID,
)
import pytz
import asyncio
import threading
from typing import Dict, Optional
import time

router = APIRouter(prefix="/fingerprints", tags=["Fingerprints"])

ph_tz = pytz.timezone("Asia/Manila")

PENDING_DELETE_TIMEOUT_SECONDS = 300

_device_state_cache = {}
_device_state_cache_time = {}
CACHE_TTL_SECONDS = 1


class EnrollmentRequest(BaseModel):
    user_id: int
    target_device: Optional[str] = None


class StartAttendanceRequest(BaseModel):
    event_id: int


class DeviceSelectionRequest(BaseModel):
    device_id: str


def log_request(endpoint: str, client_ip: str, extra: str = ""):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] {endpoint} | {client_ip} {extra}")


def _finger_ids_in_flight(db: Session) -> set[int]:
    now = datetime.utcnow()
    stale_cutoff = now - timedelta(seconds=PENDING_DELETE_TIMEOUT_SECONDS)
    in_flight = set()
    for s in get_all_device_states(db):
        if s.pending_delete_id is not None:
            if (
                s.pending_delete_updated_at
                and s.pending_delete_updated_at < stale_cutoff
            ):
                continue
            in_flight.add(s.pending_delete_id)
    return in_flight


# WEBSOCKET MANAGER
class DeviceConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}
        self.device_modes: Dict[str, str] = {}
        self.loop: asyncio.AbstractEventLoop | None = None

    def set_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self.loop = loop

    def schedule(self, coro) -> None:
        try:
            asyncio.get_running_loop()
            asyncio.create_task(coro)
        except RuntimeError:
            if self.loop is not None and self.loop.is_running():
                asyncio.run_coroutine_threadsafe(coro, self.loop)
            else:
                coro.close()
                print("[WS] Dropped scheduled task: no event loop available yet")

    async def connect(self, websocket: WebSocket, device_id: str):
        await websocket.accept()
        self.active_connections[device_id] = websocket
        print(f"[WS] Device {device_id} connected")

        db = SessionLocal()
        try:
            state = get_device_state(db, device_id)

            # Update last_seen
            state.last_seen = datetime.utcnow()
            db.commit()

            await websocket.send_text(f"mode:{state.mode}")
            self.device_modes[device_id] = state.mode
            print(f"[WS] Sent initial mode '{state.mode}' to {device_id}")
        except Exception as e:
            print(f"[WS] Error sending initial mode: {e}")
        finally:
            db.close()

    def disconnect(self, device_id: str):
        self.active_connections.pop(device_id, None)
        self.device_modes.pop(device_id, None)
        print(f"[WS] Device {device_id} disconnected")

    async def send_mode_update(self, device_id: str, mode: str):
        if device_id in self.active_connections:
            try:
                await self.active_connections[device_id].send_text(f"mode:{mode}")
                self.device_modes[device_id] = mode
                print(f"[WS] Sent mode '{mode}' to device {device_id}")
                return True
            except Exception as e:
                print(f"[WS] Error sending to {device_id}: {e}")
                self.disconnect(device_id)
        else:
            print(f"[WS] Device {device_id} not connected")
        return False

    async def broadcast_mode(self, mode: str):
        """Send mode to ALL connected devices"""
        if not self.active_connections:
            print(f"[WS] No devices connected, cannot broadcast '{mode}'")
            return

        print(f"[WS] Broadcasting '{mode}' to {len(self.active_connections)} device(s)")

        for device_id, websocket in list(self.active_connections.items()):
            try:
                await websocket.send_text(f"mode:{mode}")
                self.device_modes[device_id] = mode
                print(f"[WS] Sent mode '{mode}' to device {device_id}")
            except Exception as e:
                print(f"[WS] Error broadcasting to {device_id}: {e}")
                self.disconnect(device_id)


ws_manager = DeviceConnectionManager()


# WEBSOCKET ENDPOINT
@router.websocket("/ws/{device_id}")
async def websocket_endpoint(websocket: WebSocket, device_id: str):
    await ws_manager.connect(websocket, device_id)
    try:
        while True:
            data = await websocket.receive_text()

            if data == "ping":
                await websocket.send_text("pong")
            elif data.startswith("mode:"):
                mode = data.split(":")[1]
                ws_manager.device_modes[device_id] = mode
                print(f"[WS] Device {device_id} reported mode: {mode}")

            # Update last_seen periodically
            db = SessionLocal()
            try:
                state = get_device_state(db, device_id)
                state.last_seen = datetime.utcnow()
                db.commit()
            finally:
                db.close()

    except WebSocketDisconnect:
        ws_manager.disconnect(device_id)
    except Exception as e:
        print(f"[WS] Error with {device_id}: {e}")
        ws_manager.disconnect(device_id)


# WEBSOCKET STATUS ENDPOINT - FOR DEBUGGING
@router.get("/ws-status")
def ws_status():
    return {
        "connected_devices": list(ws_manager.active_connections.keys()),
        "device_modes": ws_manager.device_modes,
        "total": len(ws_manager.active_connections),
    }


# Get online devices for admin selection
@router.get("/online-devices")
def get_online_devices_endpoint(db: Session = Depends(get_db)):
    """Get list of online devices for admin to select"""
    devices = get_all_device_states(db)
    return {
        "online_devices": [
            {
                "device_id": d.device_id,
                "mode": d.mode,
                "last_seen": d.last_seen,
                "is_online": is_device_online(d),
            }
            for d in devices
        ],
        "total": len(devices),
    }


# Set system-wide target device
@router.post("/set-target-device")
async def set_target_device_endpoint(
    request: DeviceSelectionRequest, db: Session = Depends(get_db)
):
    """Admin sets which device should handle the next enrollment(s)"""
    device_id = request.device_id

    # Verify device exists and is online
    state = get_device_state(db, device_id)
    if not is_device_online(state):
        raise HTTPException(status_code=400, detail=f"Device {device_id} is not online")

    # Set system target device
    set_system_target_device(db, device_id)

    return {
        "message": f"Target device set to {device_id}",
        "device_id": device_id,
        "is_online": True,
    }


# Clear system-wide target device
@router.post("/clear-target-device")
async def clear_target_device_endpoint(db: Session = Depends(get_db)):
    """Clear the system-wide target device selection - fallback to any device"""
    clear_system_target_device(db)
    return {"message": "Target device cleared - will use any available device"}


# Get current system-wide target device
@router.get("/target-device")
def get_target_device_endpoint(db: Session = Depends(get_db)):
    """Get the currently selected system-wide target device"""
    target_device = get_system_target_device(db)

    if target_device:
        state = get_device_state(db, target_device)
        return {
            "target_device": target_device,
            "is_set": True,
            "is_online": is_device_online(state),
        }
    else:
        return {"target_device": None, "is_set": False, "is_online": False}


# START ENROLLMENT - FIXED
@router.post("/start-enrollment")
async def start_enrollment(
    request: EnrollmentRequest,
    req: Request,
    db: Session = Depends(get_db),
):
    client_ip = req.client.host
    target_device = request.target_device

    # If no specific target device, check system-wide target
    if not target_device:
        target_device = get_system_target_device(db)

    log_request(
        "START-ENROLLMENT",
        client_ip,
        f"| user_id={request.user_id} | target_device={target_device or 'ANY'}",
    )

    user = db.query(User).filter(User.id == request.user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Check if target device is valid and online
    if target_device:
        target_state = get_device_state(db, target_device)
        if not is_device_online(target_state):
            raise HTTPException(
                status_code=400, detail=f"Target device {target_device} is not online"
            )

        # Check if target device is free
        try:
            ensure_all_devices_free(db, "enroll", target_device=target_device)
        except HTTPException as e:
            raise HTTPException(
                status_code=409,
                detail=f"Target device {target_device} is busy: {e.detail}",
            )

        # CRITICAL FIX: Only set the TARGET device to enroll mode
        target_state.mode = "enroll"
        target_state.mode_updated_at = datetime.utcnow()
        db.commit()
    else:
        # Broadcast to all devices (original behavior - only if NO target specified)
        ensure_all_devices_free(db, "enroll")
        set_mode_on_all_devices(db, "enroll")

    if user.status != FingerprintStatus.NOT_ENROLLED:
        user.finger_id = None
        user.enroll_status = EnrollmentStep.NOT_ENROLLED
        user.status = FingerprintStatus.NOT_ENROLLED

    existing_ids = {u.finger_id for u in db.query(User.finger_id).all() if u.finger_id}
    existing_ids |= _finger_ids_in_flight(db)

    if len(existing_ids) > 1000:
        raise HTTPException(status_code=400, detail="Fingerprint storage is full")

    finger_id = random.randint(1, 1000)
    while finger_id in existing_ids:
        finger_id = random.randint(1, 1000)

    user.finger_id = finger_id
    user.enroll_status = EnrollmentStep.PENDING
    user.status = FingerprintStatus.PENDING
    user.target_device = target_device  # Store which device should handle this

    try:
        db.commit()
        db.refresh(user)
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

    # CRITICAL FIX: Only send mode to the selected device, NOT broadcast
    if target_device:
        ws_manager.schedule(ws_manager.send_mode_update(target_device, "enroll"))
    else:
        ws_manager.schedule(ws_manager.broadcast_mode("enroll"))

    return {
        "message": "Enrollment started",
        "finger_id": finger_id,
        "status": user.status.value,
        "step": "pending",
        "target_device": target_device or "ANY",
    }


# CHECK ENROLLMENT - FIXED
_last_check_enrollment_result = None
_last_check_enrollment_time = 0
_CHECK_ENROLLMENT_CACHE_MS = 100


@router.get("/check-enrollment")
def check_enrollment(
    req: Request,
    device_id: str = DEFAULT_DEVICE_ID,
    db: Session = Depends(get_db),
):
    global _last_check_enrollment_result, _last_check_enrollment_time

    client_ip = req.client.host

    current_time = time.time() * 1000
    if (current_time - _last_check_enrollment_time) < _CHECK_ENROLLMENT_CACHE_MS:
        if _last_check_enrollment_result:
            return PlainTextResponse(str(_last_check_enrollment_result))

    state = get_device_state(db, device_id)

    # CRITICAL FIX: Only look for users that are targeted to THIS device
    user = (
        db.query(User)
        .filter(User.status == FingerprintStatus.PENDING)
        .filter(User.enroll_status == EnrollmentStep.PENDING)
        .filter(User.claimed_by_device.is_(None))
        .filter((User.target_device == device_id) | (User.target_device.is_(None)))
        .order_by(User.target_device == device_id, User.id.asc())
        .first()
    )

    if user:
        if user.target_device and user.target_device != device_id:
            _last_check_enrollment_result = None
            _last_check_enrollment_time = current_time
            return PlainTextResponse("none")

        user.claimed_by_device = device_id
        try:
            db.commit()
        except Exception:
            db.rollback()
            _last_check_enrollment_result = None
            _last_check_enrollment_time = current_time
            return PlainTextResponse("none")

        log_request(
            "CHECK-ENROLLMENT",
            client_ip,
            f"| Found finger_id={user.finger_id} for device={device_id} | target_device={user.target_device}",
        )
        _last_check_enrollment_result = user.finger_id
        _last_check_enrollment_time = current_time
        return PlainTextResponse(str(user.finger_id))

    # Check for resuming user on this device
    user = (
        db.query(User)
        .filter(User.status == FingerprintStatus.PENDING)
        .filter(
            User.enroll_status.in_(
                [
                    EnrollmentStep.PLACE_FINGER,
                    EnrollmentStep.REMOVE_FINGER,
                    EnrollmentStep.PLACE_AGAIN,
                ]
            )
        )
        .filter(User.claimed_by_device == device_id)
        .order_by(User.id.asc())
        .first()
    )

    if user:
        log_request(
            "CHECK-ENROLLMENT",
            client_ip,
            f"| Resuming finger_id={user.finger_id} on device={device_id}",
        )
        _last_check_enrollment_result = user.finger_id
        _last_check_enrollment_time = current_time
        return PlainTextResponse(str(user.finger_id))

    if state.mode == "enroll":
        pending_count = (
            db.query(User)
            .filter(User.status == FingerprintStatus.PENDING)
            .filter(User.claimed_by_device.is_(None))
            .filter((User.target_device == device_id) | (User.target_device.is_(None)))
            .count()
        )

        if pending_count == 0:
            log_request(
                "CHECK-ENROLLMENT",
                client_ip,
                f"| device={device_id} | no pending work -> returning to idle",
            )
            state.mode = "idle"
            db.commit()
            ws_manager.schedule(ws_manager.send_mode_update(device_id, "idle"))

    _last_check_enrollment_result = None
    _last_check_enrollment_time = current_time
    return PlainTextResponse("none")


# UPDATE ENROLLMENT
@router.get("/update-enrollment")
def update_enrollment(
    req: Request,
    id: int,
    status: str,
    device_id: str = DEFAULT_DEVICE_ID,
    db: Session = Depends(get_db),
):
    client_ip = req.client.host
    log_request(
        "UPDATE-ENROLLMENT",
        client_ip,
        f"| finger_id={id} | status={status} | device={device_id}",
    )

    if id == 0:
        return PlainTextResponse("invalid_id")

    user = db.query(User).filter(User.finger_id == id).first()
    if not user:
        return PlainTextResponse("error")

    if status in ("place_finger", "remove_finger", "place_again", "success", "error"):
        if user.status != FingerprintStatus.PENDING:
            log_request(
                "UPDATE-ENROLLMENT",
                client_ip,
                f"| finger_id={id} | IGNORED stale enroll callback "
                f"(user status={user.status.value})",
            )
            return PlainTextResponse("stale_ignored")

    status_map = {
        "place_finger": (EnrollmentStep.PLACE_FINGER, FingerprintStatus.PENDING),
        "remove_finger": (EnrollmentStep.REMOVE_FINGER, FingerprintStatus.PENDING),
        "place_again": (EnrollmentStep.PLACE_AGAIN, FingerprintStatus.PENDING),
        "success": (EnrollmentStep.SUCCESS, FingerprintStatus.ENROLLED),
        "error": (EnrollmentStep.ERROR, FingerprintStatus.FAILED),
        "delete_success": (EnrollmentStep.NOT_ENROLLED, FingerprintStatus.NOT_ENROLLED),
        "delete_error": (None, None),
    }

    if status not in status_map:
        return PlainTextResponse("invalid_status")

    enroll_step, fingerprint_status = status_map[status]

    if status == "delete_success":
        matching_state = (
            db.query(DeviceState)
            .filter_by(pending_delete_id=id, pending_delete_user_id=user.id)
            .first()
        )

        if matching_state is None:
            log_request(
                "UPDATE-ENROLLMENT",
                client_ip,
                f"| finger_id={id} | IGNORED stale delete_success "
                f"(no matching pending_delete for user_id={user.id})",
            )
            for s in get_all_device_states(db):
                if s.pending_delete_id == id:
                    s.pending_delete_id = None
                    s.pending_delete_user_id = None
                    s.pending_delete_updated_at = None
            db.commit()
            return PlainTextResponse("stale_ignored")

        user.enroll_status = enroll_step
        user.status = fingerprint_status
        user.finger_id = None
        user.claimed_by_device = None
        user.target_device = None

        matching_state.pending_delete_id = None
        matching_state.pending_delete_user_id = None
        matching_state.pending_delete_updated_at = None

    elif status == "delete_error":
        for s in get_all_device_states(db):
            if s.pending_delete_id == id:
                s.pending_delete_id = None
                s.pending_delete_user_id = None
                s.pending_delete_updated_at = None
        log_request(
            "UPDATE-ENROLLMENT",
            client_ip,
            f"| finger_id={id} | delete_error cleared pending_delete",
        )
    else:
        user.enroll_status = enroll_step
        user.status = fingerprint_status

        if status in ("success", "error"):
            user.claimed_by_device = None
            user.target_device = None

    try:
        db.commit()
    except Exception as e:
        db.rollback()
        return PlainTextResponse("error")

    if status in ["success", "error", "delete_success", "delete_error"]:
        set_mode_on_all_devices(db, "idle")
        ws_manager.schedule(ws_manager.broadcast_mode("idle"))

    return PlainTextResponse("updated")


# GET STATUS
_get_status_call_count = 0


@router.get("/get-status")
def get_status(
    req: Request,
    finger_id: int,
    db: Session = Depends(get_db),
):
    global _get_status_call_count

    client_ip = req.client.host
    _get_status_call_count += 1

    if _get_status_call_count % 20 == 1:
        log_request("GET-STATUS", client_ip, f"| finger_id={finger_id}")

    user = db.query(User).filter(User.finger_id == finger_id).first()

    if not user:
        return {"status": "failed", "step": "error", "message": "User not found"}

    step = user.enroll_status.value if user.enroll_status else "pending"

    return {
        "status": user.status.value,
        "step": step,
    }


# RESET ENROLLMENT
@router.post("/reset-enrollment/{user_id}")
async def reset_enrollment(user_id: int, req: Request, db: Session = Depends(get_db)):
    client_ip = req.client.host
    log_request("RESET-ENROLLMENT", client_ip, f"| user_id={user_id}")

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    for s in get_all_device_states(db):
        if s.pending_delete_user_id == user.id:
            s.pending_delete_id = None
            s.pending_delete_user_id = None
            s.pending_delete_updated_at = None

    user.finger_id = None
    user.enroll_status = EnrollmentStep.NOT_ENROLLED
    user.status = FingerprintStatus.NOT_ENROLLED
    user.claimed_by_device = None
    user.target_device = None

    set_mode_on_all_devices(db, "idle")
    ws_manager.schedule(ws_manager.broadcast_mode("idle"))

    try:
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

    return {"message": "Enrollment reset successfully"}


# CANCEL OPERATION
@router.post("/cancel-operation")
async def cancel_operation(db: Session = Depends(get_db)):
    log_request("CANCEL-OPERATION", "dashboard")

    for d in get_all_device_states(db):
        d.mode = "idle"
        d.pending_delete_id = None
        d.pending_delete_user_id = None
        d.pending_delete_updated_at = None
        d.recognition_target_id = None
        d.recognition_finger_id = None
        d.recognition_matched = None
        d.active_event_id = None
        d.target_device_id = None

    pending_users = (
        db.query(User).filter(User.status == FingerprintStatus.PENDING).all()
    )
    for u in pending_users:
        u.finger_id = None
        u.enroll_status = EnrollmentStep.NOT_ENROLLED
        u.status = FingerprintStatus.NOT_ENROLLED
        u.claimed_by_device = None
        u.target_device = None

    try:
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

    ws_manager.schedule(ws_manager.broadcast_mode("idle"))

    return {"message": "All devices reset to idle; operation cancelled"}


# UNENROLL FINGERPRINT
@router.post("/unenroll-fingerprint/{user_id}")
async def unenroll_fingerprint(
    user_id: int, req: Request, db: Session = Depends(get_db)
):
    client_ip = req.client.host
    log_request("UNENROLL-FINGERPRINT", client_ip, f"| user_id={user_id}")

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.status != FingerprintStatus.ENROLLED:
        raise HTTPException(status_code=400, detail="User is not enrolled")
    if not user.finger_id:
        raise HTTPException(status_code=400, detail="User has no finger_id")

    if not any(is_device_online(s) for s in get_all_device_states(db)):
        raise HTTPException(
            status_code=400,
            detail="No ESP32 device is online. Cannot unenroll fingerprint.",
        )

    ensure_all_devices_free(db, "delete")

    now = datetime.utcnow()
    devices = get_all_device_states(db)
    for d in devices:
        d.pending_delete_id = user.finger_id
        d.pending_delete_user_id = user.id
        d.pending_delete_updated_at = now
        d.mode = "delete"

    try:
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

    ws_manager.schedule(ws_manager.broadcast_mode("delete"))

    return {"message": "Unenrollment started", "finger_id": user.finger_id}


# CHECK DELETE
_last_check_delete_result = None
_last_check_delete_time = 0
_CHECK_DELETE_CACHE_MS = 100


@router.get("/check-delete")
def check_delete(
    req: Request,
    device_id: str = DEFAULT_DEVICE_ID,
    db: Session = Depends(get_db),
):
    global _last_check_delete_result, _last_check_delete_time

    client_ip = req.client.host

    current_time = time.time() * 1000
    if (current_time - _last_check_delete_time) < _CHECK_DELETE_CACHE_MS:
        if _last_check_delete_result:
            return PlainTextResponse(str(_last_check_delete_result))

    state = get_device_state(db, device_id)

    if state.pending_delete_id is not None:
        now = datetime.utcnow()
        stale_cutoff = now - timedelta(seconds=PENDING_DELETE_TIMEOUT_SECONDS)
        if (
            state.pending_delete_updated_at
            and state.pending_delete_updated_at < stale_cutoff
        ):
            log_request(
                "CHECK-DELETE",
                client_ip,
                f"| device={device_id} | CLEARING stale pending_delete_id={state.pending_delete_id}",
            )
            state.pending_delete_id = None
            state.pending_delete_user_id = None
            state.pending_delete_updated_at = None
            state.mode = "idle"
            db.commit()
            ws_manager.schedule(ws_manager.send_mode_update(device_id, "idle"))
            _last_check_delete_result = None
            _last_check_delete_time = current_time
            return PlainTextResponse("none")

        finger_id = state.pending_delete_id
        log_request(
            "CHECK-DELETE",
            client_ip,
            f"| device={device_id} | Found finger_id={finger_id}",
        )
        db.commit()
        _last_check_delete_result = finger_id
        _last_check_delete_time = current_time
        return PlainTextResponse(str(finger_id))

    if state.mode == "delete":
        log_request(
            "CHECK-DELETE",
            client_ip,
            f"| device={device_id} | no pending delete -> returning to idle",
        )
        state.mode = "idle"
        db.commit()
        ws_manager.schedule(ws_manager.send_mode_update(device_id, "idle"))

    _last_check_delete_result = None
    _last_check_delete_time = current_time
    return PlainTextResponse("none")


# DEVICE STATUS
@router.get("/device-status")
def device_status(db: Session = Depends(get_db)):
    connected = any(is_device_online(s) for s in get_all_device_states(db))
    return {"connected": connected}


# START ATTENDANCE
@router.post("/start-attendance")
async def start_attendance(
    request: StartAttendanceRequest,
    db: Session = Depends(get_db),
):
    print(f"[ATTENDANCE] Starting attendance for event {request.event_id}")

    event = db.query(Event).filter(Event.id == request.event_id).first()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")

    ensure_all_devices_free(db, "attendance")
    set_mode_on_all_devices(db, "attendance")
    set_active_event_on_all_devices(db, request.event_id)

    ws_manager.schedule(ws_manager.broadcast_mode("attendance"))

    return {"message": "Attendance mode started", "event_id": request.event_id}


# STOP ATTENDANCE
@router.post("/stop-attendance")
async def stop_attendance(db: Session = Depends(get_db)):
    print("[ATTENDANCE] Stopping attendance")

    set_mode_on_all_devices(db, "idle")
    set_active_event_on_all_devices(db, None)

    ws_manager.schedule(ws_manager.broadcast_mode("idle"))

    return {"message": "Attendance mode stopped"}


# MARK ATTENDANCE
@router.get("/mark-attendance")
def mark_attendance(
    req: Request,
    finger_id: int,
    device_id: str = DEFAULT_DEVICE_ID,
    db: Session = Depends(get_db),
):
    client_ip = req.client.host
    log_request(
        "MARK-ATTENDANCE", client_ip, f"| device={device_id} | finger_id={finger_id}"
    )

    user = db.query(User).filter(User.finger_id == finger_id).first()
    if not user:
        return PlainTextResponse("user_not_found")
    if user.status != FingerprintStatus.ENROLLED:
        return PlainTextResponse("not_enrolled")

    state = get_device_state(db, device_id)
    if not state.active_event_id:
        return PlainTextResponse("no_active_event")

    ongoing_event = db.query(Event).filter(Event.id == state.active_event_id).first()
    if not ongoing_event:
        return PlainTextResponse("no_active_event")

    ph_tz_local = pytz.timezone("Asia/Manila")
    ph_now_aware = datetime.now(ph_tz_local)

    event_start = datetime.combine(ongoing_event.event_date, ongoing_event.start_time)
    event_end = datetime.combine(ongoing_event.event_date, ongoing_event.end_time)
    event_start = ph_tz_local.localize(event_start)
    event_end = ph_tz_local.localize(event_end)

    if ph_now_aware < event_start or ph_now_aware > event_end:
        log_request(
            "MARK-ATTENDANCE",
            client_ip,
            f"| device={device_id} | finger_id={finger_id} | event not in progress",
        )
        return PlainTextResponse("event_not_active")

    if ongoing_event.program_id is not None:
        if user.program_id != ongoing_event.program_id:
            return PlainTextResponse("wrong_program")

    new_attendance = Attendance(
        user_id=user.id,
        event_id=ongoing_event.id,
        status=AttendanceStatus.PRESENT,
        attendance_time=datetime.now(ph_tz).replace(tzinfo=None),
    )
    db.add(new_attendance)

    try:
        db.commit()
        db.refresh(new_attendance)
        log_request(
            "MARK-ATTENDANCE",
            client_ip,
            f"| device={device_id} | finger_id={finger_id} | SUCCESS attendance recorded",
        )
        return PlainTextResponse("attendance_marked")
    except IntegrityError:
        db.rollback()
        log_request(
            "MARK-ATTENDANCE",
            client_ip,
            f"| device={device_id} | finger_id={finger_id} | ALREADY MARKED",
        )
        return PlainTextResponse("already_marked")
    except Exception as e:
        db.rollback()
        log_request(
            "MARK-ATTENDANCE",
            client_ip,
            f"| device={device_id} | finger_id={finger_id} | DATABASE ERROR: {e}",
        )
        return PlainTextResponse("database_error")


# DEVICE MODE
_mode_cache = {}
_mode_cache_time = {}


@router.get("/device-mode")
def get_device_mode(
    device_id: str = DEFAULT_DEVICE_ID,
    db: Session = Depends(get_db),
):
    import time

    cache_key = f"mode_{device_id}"

    if cache_key in _mode_cache:
        cached_time, cached_mode = _mode_cache[cache_key]
        if time.time() - cached_time < 0.5:
            return PlainTextResponse(cached_mode)

    state = get_device_state(db, device_id)
    mode = state.mode

    _mode_cache[cache_key] = (time.time(), mode)

    return PlainTextResponse(mode)


# START RECOGNITION - FIXED
@router.post("/start-recognition/{user_id}")
async def start_recognition(user_id: int, db: Session = Depends(get_db)):
    """Start recognition on the device where the fingerprint is enrolled"""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.status != FingerprintStatus.ENROLLED:
        raise HTTPException(status_code=400, detail="User not enrolled")
    if not user.finger_id:
        raise HTTPException(status_code=400, detail="User has no fingerprint")

    # Determine which device should handle recognition
    target_device = None

    # 1. Check if user has a target_device stored
    if user.target_device:
        target_device = user.target_device
        print(f"[RECOGNIZE] Using user's target_device: {target_device}")

    # 2. Check system-wide target
    if not target_device:
        target_device = get_system_target_device(db)
        if target_device:
            print(f"[RECOGNIZE] Using system target_device: {target_device}")

    # 3. Check if user was claimed by a device during enrollment
    if not target_device and user.claimed_by_device:
        target_device = user.claimed_by_device
        print(f"[RECOGNIZE] Using claimed_by_device: {target_device}")

    # 4. Fallback to any online device
    if not target_device:
        online_devices = get_online_devices(db)
        if online_devices:
            target_device = online_devices[0].device_id
            print(f"[RECOGNIZE] Using first online device: {target_device}")
        else:
            raise HTTPException(
                status_code=503, detail="No online devices available for recognition"
            )

    # Verify target device is online
    state = get_device_state(db, target_device)
    if not is_device_online(state):
        raise HTTPException(
            status_code=503, detail=f"Target device {target_device} is not online"
        )

    # Clear recognition targets from all devices first
    devices = get_all_device_states(db)
    for d in devices:
        d.recognition_target_id = None
        d.recognition_finger_id = None
        d.recognition_matched = None
        d.recognition_updated_at = None

        if d.device_id == target_device:
            # Set target device to recognize mode
            d.mode = "recognize"
            d.mode_updated_at = datetime.utcnow()
            d.recognition_target_id = user.finger_id
            d.recognition_updated_at = datetime.utcnow()
            print(
                f"[RECOGNIZE] Set device {target_device} to recognize mode for finger_id {user.finger_id}"
            )
        else:
            # Ensure other devices are not in recognize mode
            if d.mode == "recognize":
                d.mode = "idle"
                d.mode_updated_at = datetime.utcnow()
                print(f"[RECOGNIZE] Reset device {d.device_id} from recognize to idle")

    try:
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

    # CRITICAL FIX: Only send to the TARGET device, NOT broadcast
    ws_manager.schedule(ws_manager.send_mode_update(target_device, "recognize"))

    return {
        "message": f"Recognition test started on device {target_device}",
        "target_finger_id": user.finger_id,
        "target_device": target_device,
        "user_name": f"{user.first_name} {user.last_name}",
    }


# RECOGNITION RESULT - FIXED
@router.get("/recognition-result")
def recognition_result(
    finger_id: int,
    matched: bool,
    device_id: str = DEFAULT_DEVICE_ID,
    db: Session = Depends(get_db),
):
    state = get_device_state(db, device_id)

    if state.recognition_target_id is None:
        print(f"[RECOGNIZE] Device {device_id} has no active recognition target")
        return PlainTextResponse("no_active_recognition")

    # Verify this device is the one that should be doing recognition
    if state.mode != "recognize":
        print(
            f"[RECOGNIZE] Device {device_id} is not in recognize mode (mode={state.mode})"
        )
        return PlainTextResponse("device_not_in_recognition_mode")

    print(
        f"[RECOGNIZE] Device {device_id} processing recognition: finger_id={finger_id}, matched={matched}"
    )

    from sqlalchemy import update

    stmt = (
        update(DeviceState)
        .where(DeviceState.device_id == device_id)
        .where(DeviceState.recognition_matched.is_(None))
        .values(
            recognition_matched=matched and (finger_id == state.recognition_target_id),
            recognition_finger_id=finger_id,
            recognition_target_id=None,
        )
    )
    result = db.execute(stmt)

    if result.rowcount == 0:
        print(f"[RECOGNIZE] Device {device_id} already processed")
        return PlainTextResponse("already_processed")

    # Clear recognition target from all devices
    for s in get_all_device_states(db):
        s.recognition_target_id = None

    # Set this device back to idle
    state.mode = "idle"
    state.mode_updated_at = datetime.utcnow()

    try:
        db.commit()
    except Exception as e:
        db.rollback()
        print(f"[RECOGNIZE] Error committing result: {e}")
        return PlainTextResponse("error")

    # Only send idle to the specific device, not broadcast
    ws_manager.schedule(ws_manager.send_mode_update(device_id, "idle"))

    return PlainTextResponse("ok")


# GET RECOGNITION RESULT - FIXED
@router.get("/get-recognition-result")
def get_recognition_result(
    finger_id: int,
    device_id: str = DEFAULT_DEVICE_ID,
    db: Session = Depends(get_db),
):
    now = datetime.utcnow()
    stale_cutoff = now - timedelta(seconds=60)

    state = get_device_state(db, device_id)

    # Only check if this device is in recognition mode
    if state.mode != "recognize":
        return {"status": "not_in_recognition_mode"}

    if (
        state.mode == "recognize"
        and state.recognition_target_id is not None
        and state.recognition_updated_at
        and state.recognition_updated_at < stale_cutoff
    ):
        state.recognition_target_id = None
        state.recognition_matched = None
        state.recognition_finger_id = None
        state.recognition_updated_at = None
        state.mode = "idle"
        db.commit()
        ws_manager.schedule(ws_manager.send_mode_update(device_id, "idle"))
        return {"status": "timeout"}

    if state.recognition_matched is not None:
        matched = state.recognition_matched
        scanned_id = state.recognition_finger_id
        state.recognition_finger_id = None
        state.recognition_matched = None
        state.recognition_updated_at = None
        state.mode = "idle"
        db.commit()
        ws_manager.schedule(ws_manager.send_mode_update(device_id, "idle"))
        return {
            "status": "done",
            "matched": matched,
            "scanned_finger_id": scanned_id,
        }

    return {"status": "pending"}


# DEBUG ENDPOINTS
@router.get("/debug/all-enrolled")
def debug_all_enrolled(db: Session = Depends(get_db)):
    users = db.query(User).filter(User.status == FingerprintStatus.ENROLLED).all()
    return [
        {
            "user_id": u.id,
            "student_id_no": u.student_id_no,
            "name": f"{u.first_name} {u.last_name}",
            "finger_id": u.finger_id,
            "status": u.status.value,
            "enroll_status": u.enroll_status.value if u.enroll_status else None,
            "target_device": u.target_device,
            "claimed_by_device": u.claimed_by_device,
        }
        for u in users
    ]


@router.get("/debug/device-state")
def debug_device_state(db: Session = Depends(get_db)):
    db.expire_all()
    states = get_all_device_states(db)
    pending_users = (
        db.query(User).filter(User.status == FingerprintStatus.PENDING).all()
    )
    return {
        "devices": [
            {
                "device_id": s.device_id,
                "mode": s.mode,
                "recognition_target_id": s.recognition_target_id,
                "recognition_finger_id": s.recognition_finger_id,
                "recognition_matched": s.recognition_matched,
                "pending_delete_id": s.pending_delete_id,
                "pending_delete_user_id": s.pending_delete_user_id,
                "pending_delete_updated_at": s.pending_delete_updated_at,
                "active_event_id": s.active_event_id,
                "last_seen": s.last_seen,
                "online": is_device_online(s),
                "target_device_id": s.target_device_id,
            }
            for s in states
        ],
        "pending_enrollments": [
            {
                "user_id": u.id,
                "finger_id": u.finger_id,
                "status": u.status.value,
                "enroll_status": u.enroll_status.value if u.enroll_status else None,
                "claimed_by_device": u.claimed_by_device,
                "target_device": u.target_device,
            }
            for u in pending_users
        ],
    }


@router.get("/pending-enrollments")
def get_pending_enrollments(db: Session = Depends(get_db)):
    users = db.query(User).filter(User.status == FingerprintStatus.PENDING).all()
    return [
        {
            "user_id": u.id,
            "student_id_no": u.student_id_no,
            "name": f"{u.first_name} {u.last_name}",
            "finger_id": u.finger_id,
            "enroll_status": u.enroll_status.value if u.enroll_status else None,
            "claimed_by_device": u.claimed_by_device,
            "target_device": u.target_device,
        }
        for u in users
    ]


@router.post("/clear-pending-enrollments")
async def clear_pending_enrollments(db: Session = Depends(get_db)):
    pending_users = (
        db.query(User).filter(User.status == FingerprintStatus.PENDING).all()
    )

    if not pending_users:
        return {"message": "No pending enrollments to clear", "cleared": 0}

    for u in pending_users:
        u.finger_id = None
        u.enroll_status = EnrollmentStep.NOT_ENROLLED
        u.status = FingerprintStatus.NOT_ENROLLED
        u.claimed_by_device = None
        u.target_device = None

    for d in get_all_device_states(db):
        if d.mode == "enroll":
            d.mode = "idle"

    try:
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

    ws_manager.schedule(ws_manager.broadcast_mode("idle"))

    return {
        "message": f"Cleared {len(pending_users)} pending enrollment(s)",
        "cleared": len(pending_users),
    }


@router.get("/ping")
def ping():
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}
