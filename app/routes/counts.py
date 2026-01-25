from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.models import User, Program, UserRole

router = APIRouter(prefix="/programs", tags=["Programs"])


# ------------------- COUNTS PROGRAMS -------------------
@router.get("/counts")
def get_program_counts(db: Session = Depends(get_db)):
    result = []
    for prog in Program:
        count = (
            db.query(User)
            .filter(User.program == prog, User.role == UserRole.STUDENT)
            .count()
        )
        result.append({"code": prog.value, "name": prog.name, "students": count})
    return result


# ------------------- FILTER STUDENTS BY PROGRAM -------------------
@router.get("/{program_code}/students")
def get_students_by_program(program_code: str, db: Session = Depends(get_db)):
    try:
        program_enum = Program(program_code)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid program code")

    students = (
        db.query(User)
        .filter(
            User.program == program_enum,
            User.role == UserRole.STUDENT,
        )
        .all()
    )

    return [
        {
            "id": s.id,
            "student_id_no": s.student_id_no,
            "first_name": s.first_name,
            "last_name": s.last_name,
            "program": s.program.value,
            "email": s.email,
            "fingerprint_status": s.status,  
        }
        for s in students
    ]
