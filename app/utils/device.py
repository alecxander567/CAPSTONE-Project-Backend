from app.models.device import DeviceState


def get_device_state(db):
    state = db.query(DeviceState).first()

    if not state:
        state = DeviceState()
        db.add(state)
        db.commit()
        db.refresh(state)

    return state
