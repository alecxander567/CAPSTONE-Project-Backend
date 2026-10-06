"""
Seed script for event normalization (St. Peter's College of Toril).

Uses the official Calendar of Activities. All dates are in 2026 because the
schema forbids events in the past.

Idempotent -- safe to re-run:
  - Titles and locations are reused by name if they already exist.
  - Events are skipped if (title, location, start_date) already exists.
  - Events with a start_date in the past are skipped with a warning.

Usage (from backend/):
    python seed_events.py
"""

from datetime import date, time, timedelta
from sqlalchemy.orm import Session

from app.core.database import SessionLocal, engine, Base
from app.models import (
    Event,
    EventDay,
    EventTitle,
    Location,
    User,
    UserRole,
)


# -------------------------------------------------------------
# EVENT TITLES  (from the official Calendar of Activities)
# -------------------------------------------------------------
EVENT_TITLES = [
    "Enrollment 4th year",
    "Enrollment 3rd year",
    "Enrollment 2nd year",
    "Enrollment 1st year",
    "Enrollment for transferees and late enrollees",
    "Start of Class",
    "Major and Minor Clubs Listing and Election of Officers",
    "Orientation of Students",
    "Leadership Training",
    "Symposium on Gender and Development (GAD)",
    "Basketball Try Out for Varsity",
    "Volleyball Try Out for Varsity",
    "Table Tennis Try Out for Varsity",
    "Badminton Try Out for Varsity",
    "Chess Try Out for Varsity",
    "Symposium on Violence Against Women and Children (VAWC)",
    "Symposium on RA No. 11313: Safe Spaces Act (Bawal Bastos Law)",
    "Buwang ng Wika Culmination",
    "Launching of the Vocation Month",
    "HUMSERV Activity",
    "Launching of the Holy Rosary Month",
    "Clean Up Drive (CEM club)",
    "Feast of Sto. Rosario Parish",
    "BSBA Activity",
    "2nd Term Prelim Exam",
    "Symposium on Mental Health",
    "Intramurals",
    "ASEP Activity",
    "2nd Prelim Final Exam",
]


# -------------------------------------------------------------
# LOCATIONS
# -------------------------------------------------------------
LOCATIONS = [
    "Gymnasium",
    "Covered Court",
    "University Oval",
    "AVR (Audio-Visual Room)",
    "Main Auditorium",
    "Field Grounds",
    "Library Hall",
    "Multi-Purpose Hall",
    "Open Grounds",
    "Computer Laboratory",
    "Function Hall",
    "Quadrangle",
]


# -------------------------------------------------------------
# CALENDAR OF ACTIVITIES
# Each entry: (title, location, description, [(date, start, end)])
# All dates in 2026.
# -------------------------------------------------------------
def _build_calendar():
    def d(month: int, day: int) -> date:
        return date(2026, month, day)

    def range_days(start: date, count: int, s: time, e: time):
        return [(start + timedelta(days=i), s, e) for i in range(count)]

    # Common time windows
    FULL_DAY  = (time(8, 0),  time(17, 0))
    MORNING   = (time(8, 0),  time(10, 0))
    AFTERNOON = (time(13, 0), time(17, 0))

    def one(day: date, window=FULL_DAY):
        return [(day, window[0], window[1])]

    return [
        # -- JUNE 2026 --
        {
            "title": "Enrollment 4th year",
            "location": "AVR (Audio-Visual Room)",
            "description": "Enrollment for 4th year students.",
            "days": one(d(6, 9)),
        },
        {
            "title": "Enrollment 3rd year",
            "location": "AVR (Audio-Visual Room)",
            "description": "Enrollment for 3rd year students.",
            "days": one(d(6, 10)),
        },
        {
            "title": "Enrollment 2nd year",
            "location": "AVR (Audio-Visual Room)",
            "description": "Enrollment for 2nd year students.",
            "days": one(d(6, 11)),
        },
        {
            "title": "Enrollment 1st year",
            "location": "AVR (Audio-Visual Room)",
            "description": "Enrollment for 1st year students.",
            "days": one(d(6, 12)),
        },
        {
            "title": "Enrollment for transferees and late enrollees",
            "location": "AVR (Audio-Visual Room)",
            "description": "Enrollment for transferees and late enrollees (1st batch).",
            "days": range_days(d(6, 13), 2, *FULL_DAY),  # Jun 13-14
        },
        {
            "title": "Enrollment for transferees and late enrollees",
            "location": "AVR (Audio-Visual Room)",
            "description": "Enrollment for transferees and late enrollees (2nd batch).",
            "days": range_days(d(6, 16), 2, *FULL_DAY),  # Jun 16-17
        },
        {
            "title": "Start of Class",
            "location": "Quadrangle",
            "description": "Official start of classes for the first semester.",
            "days": one(d(6, 18), MORNING),
        },
        {
            "title": "Major and Minor Clubs Listing and Election of Officers",
            "location": "Function Hall",
            "description": "Clubs listing and election of officers.",
            "days": one(d(6, 19)),
        },
        {
            "title": "Orientation of Students",
            "location": "Main Auditorium",
            "description": "Orientation for all students.",
            "days": one(d(6, 20)),
        },
        {
            "title": "Leadership Training",
            "location": "Function Hall",
            "description": "Leadership training for student officers.",
            "days": one(d(6, 21)),
        },

        # -- JULY 2026 --
        {
            "title": "Symposium on Gender and Development (GAD)",
            "location": "Main Auditorium",
            "description": "Symposium on Gender and Development.",
            "days": one(d(7, 5)),
        },
        {
            "title": "Basketball Try Out for Varsity",
            "location": "Gymnasium",
            "description": "Basketball varsity tryouts.",
            "days": range_days(d(7, 7), 5, *AFTERNOON),  # Jul 7-11
        },
        {
            "title": "Volleyball Try Out for Varsity",
            "location": "Gymnasium",
            "description": "Volleyball varsity tryouts.",
            "days": range_days(d(7, 14), 5, *AFTERNOON),  # Jul 14-18
        },
        {
            "title": "Table Tennis Try Out for Varsity",
            "location": "Covered Court",
            "description": "Table tennis varsity tryouts.",
            "days": range_days(d(7, 21), 2, *AFTERNOON),  # Jul 21-22
        },
        {
            "title": "Badminton Try Out for Varsity",
            "location": "Covered Court",
            "description": "Badminton varsity tryouts.",
            "days": range_days(d(7, 23), 2, *AFTERNOON),  # Jul 23-24
        },
        {
            "title": "Chess Try Out for Varsity",
            "location": "Library Hall",
            "description": "Chess varsity tryouts.",
            "days": one(d(7, 25), AFTERNOON),
        },

        # -- AUGUST 2026 --
        {
            "title": "Symposium on Violence Against Women and Children (VAWC)",
            "location": "Main Auditorium",
            "description": "Symposium on VAWC.",
            "days": one(d(8, 8)),
        },
        {
            "title": "Symposium on RA No. 11313: Safe Spaces Act (Bawal Bastos Law)",
            "location": "Main Auditorium",
            "description": "Symposium on RA 11313 Safe Spaces Act.",
            "days": one(d(8, 8)),
        },
        {
            "title": "Buwang ng Wika Culmination",
            "location": "Covered Court",
            "description": "Buwan ng Wika culmination program.",
            "days": one(d(8, 29)),
        },

        # -- SEPTEMBER 2026 --
        {
            "title": "Launching of the Vocation Month",
            "location": "Covered Court",
            "description": "Launching of the Vocation Month.",
            "days": one(d(9, 1), MORNING),
        },
        {
            "title": "HUMSERV Activity",
            "location": "Function Hall",
            "description": "Human Services activity.",
            "days": one(d(9, 12)),
        },
        {
            "title": "Leadership Training",
            "location": "Function Hall",
            "description": "Second leadership training session.",
            "days": one(d(9, 19)),
        },

        # -- OCTOBER 2026 --
        {
            "title": "Launching of the Holy Rosary Month",
            "location": "Covered Court",
            "description": "Launching of the Holy Rosary Month.",
            "days": one(d(10, 1), MORNING),
        },
        {
            "title": "Clean Up Drive (CEM club)",
            "location": "Open Grounds",
            "description": "Clean-up drive organized by the CEM club.",
            "days": one(d(10, 3), MORNING),
        },
        {
            "title": "Feast of Sto. Rosario Parish",
            "location": "Covered Court",
            "description": "Feast of Sto. Rosario Parish.",
            "days": one(d(10, 7), MORNING),
        },
        {
            "title": "BSBA Activity",
            "location": "Function Hall",
            "description": "BSBA department activity.",
            "days": one(d(10, 10)),
        },
        {
            "title": "2nd Term Prelim Exam",
            "location": "Main Auditorium",
            "description": "2nd Term preliminary examinations.",
            "days": range_days(d(10, 16), 2, *FULL_DAY),  # Oct 16-17
        },
        {
            "title": "Symposium on Mental Health",
            "location": "Main Auditorium",
            "description": "Symposium on mental health awareness.",
            "days": one(d(10, 23)),
        },
        {
            "title": "Intramurals",
            "location": "Gymnasium",
            "description": (
                "Annual intramural sports competition. "
                "Day 1: Opening and track events. "
                "Day 2: Ball games. "
                "Day 3: Finals and closing ceremony."
            ),
            "days": range_days(d(10, 28), 3, *FULL_DAY),  # Oct 28-30
        },

        # -- NOVEMBER 2026 --
        {
            "title": "ASEP Activity",
            "location": "Function Hall",
            "description": "ASEP activity.",
            "days": one(d(11, 7)),
        },
        {
            "title": "2nd Prelim Final Exam",
            "location": "Main Auditorium",
            "description": "2nd preliminary final examinations.",
            "days": range_days(d(11, 11), 2, *FULL_DAY),  # Nov 11-12
        },
    ]


# -------------------------------------------------------------
# SEED
# -------------------------------------------------------------
def seed():
    Base.metadata.create_all(bind=engine)

    db: Session = SessionLocal()
    try:
        today = date.today()

        # ---------- Titles ----------
        print("Seeding event titles...")
        titles_map = {}
        for name in EVENT_TITLES:
            existing = db.query(EventTitle).filter(EventTitle.name == name).first()
            if existing:
                titles_map[name] = existing.id
                continue
            t = EventTitle(name=name)
            db.add(t)
            db.flush()
            titles_map[name] = t.id
            print(f"  + {name}")
        db.commit()

        # ---------- Locations ----------
        print("\nSeeding locations...")
        locations_map = {}
        for name in LOCATIONS:
            existing = db.query(Location).filter(Location.name == name).first()
            if existing:
                locations_map[name] = existing.id
                continue
            l = Location(name=name)
            db.add(l)
            db.flush()
            locations_map[name] = l.id
            print(f"  + {name}")
        db.commit()

        # ---------- Admin ----------
        admin = db.query(User).filter(User.role == UserRole.ADMIN).first()
        if not admin:
            print("\nNo admin user found. Create one first.")
            return
        print(f"\nUsing admin: {admin.email} (id={admin.id})")

        # ---------- Events ----------
        print("\nSeeding events...")
        calendar = _build_calendar()
        skipped_past = 0
        added = 0
        reused = 0

        for entry in calendar:
            title_id = titles_map[entry["title"]]
            location_id = locations_map[entry["location"]]
            days = entry["days"]
            start_date = days[0][0]
            end_date = days[-1][0]

            # Past-date guard
            if start_date < today:
                print(f"  [skip past] {entry['title']} @ {start_date}")
                skipped_past += 1
                continue

            # Idempotency check
            existing = (
                db.query(Event)
                .filter(
                    Event.title_id == title_id,
                    Event.location_id == location_id,
                    Event.start_date == start_date,
                )
                .first()
            )
            if existing:
                print(f"  [exists]    {entry['title']} @ {start_date}")
                reused += 1
                continue

            new_event = Event(
                title_id=title_id,
                location_id=location_id,
                description=entry["description"],
                start_date=start_date,
                end_date=end_date,
                program_id=None,
                created_by=admin.id,
            )
            db.add(new_event)
            db.flush()

            for day_date, s, e in days:
                db.add(
                    EventDay(
                        event_id=new_event.id,
                        day_date=day_date,
                        start_time=s,
                        end_time=e,
                    )
                )

            print(
                f"  [added]     {entry['title']} @ {entry['location']}  "
                f"({start_date} -> {end_date})"
            )
            added += 1

        db.commit()
        print(
            f"\nDone.  added={added}  reused={reused}  "
            f"skipped_past={skipped_past}"
        )

    except Exception as e:
        db.rollback()
        print(f"\nError during seeding: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    seed()