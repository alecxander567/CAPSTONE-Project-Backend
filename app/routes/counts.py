from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.models import User, Program, UserRole
from app.core.security import get_current_user

router = APIRouter(prefix="/programs", tags=["Programs"])


# ------------------- COUNTS PROGRAMS -------------------
@router.get("/counts")
def get_program_counts(db: Session = Depends(get_db)):
    programs = db.query(Program).filter(Program.code != "OSA").all()

    result = []
    for prog in programs:
        count = (
            db.query(User)
            .filter(User.program_id == prog.id, User.role == UserRole.STUDENT)
            .count()
        )
        result.append(
            {"id": prog.id, "code": prog.code, "name": prog.name, "students": count}
        )

    return result


# ------------------- FILTER STUDENTS BY PROGRAM -------------------
@router.get("/{program_code}/students")
def get_students_by_program(program_code: str, db: Session = Depends(get_db)):

    program = db.query(Program).filter(Program.code == program_code).first()

    if not program:
        raise HTTPException(status_code=400, detail="Invalid program code")

    students = (
        db.query(User)
        .filter(User.program_id == program.id, User.role == UserRole.STUDENT)
        .all()
    )

    return [
        {
            "id": s.id,
            "student_id_no": s.student_id_no,
            "first_name": s.first_name,
            "last_name": s.last_name,
            "program": program.code,
            "mobile_phone": s.mobile_phone,
            "fingerprint_status": s.status.value,
        }
        for s in students
    ]


# ------------------- CREATE NEW PROGRAM -------------------
from pydantic import BaseModel


class ProgramCreate(BaseModel):
    code: str
    name: str


@router.post("/")
def create_program(
    payload: ProgramCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Only admins can add new programs")

    existing = db.query(Program).filter(Program.code == payload.code.upper()).first()
    if existing:
        raise HTTPException(status_code=400, detail="Program already exists")

    new_program = Program(code=payload.code.upper(), name=payload.name)
    db.add(new_program)
    db.commit()
    db.refresh(new_program)

    return new_program


# ------------------- UPDATE PROGRAM -------------------
class ProgramUpdate(BaseModel):
    code: str
    name: str


@router.put("/{program_id}")
def update_program(
    program_id: int,
    payload: ProgramUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Only admins can edit programs")

    program = db.query(Program).filter(Program.id == program_id).first()
    if not program:
        raise HTTPException(status_code=404, detail="Program not found")

    # Check code uniqueness excluding current program
    existing = (
        db.query(Program)
        .filter(Program.code == payload.code.upper(), Program.id != program_id)
        .first()
    )
    if existing:
        raise HTTPException(status_code=400, detail="Program code already exists")

    program.code = payload.code.upper()
    program.name = payload.name
    db.commit()
    db.refresh(program)

    return program


# ------------------- DELETE PROGRAM -------------------
@router.delete("/{program_id}")
def delete_program(
    program_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Only admins can delete programs")

    program = db.query(Program).filter(Program.id == program_id).first()
    if not program:
        raise HTTPException(status_code=404, detail="Program not found")

    if program.code == "OSA":
        raise HTTPException(status_code=400, detail="Cannot delete OSA program")

    db.delete(program)
    db.commit()

    return {"message": "Program deleted successfully"}
