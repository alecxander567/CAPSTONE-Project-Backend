# ARA Biometric Attendance System Backend

Backend API for the ARA Attendance System, a biometric attendance platform for managing students, programs, events, fingerprint enrollment, ESP32 devices, attendance records, notifications, and attendance analytics.

The service is built with FastAPI and SQLAlchemy and is designed to work with a web dashboard and one or more ESP32 fingerprint devices.

## What the System Does

### Authentication and account management

- Creates administrator and student accounts with role-based rules.
- Allows only one administrator account. The first registered account must be an administrator; after that, public registration is limited to students.
- Authenticates users with student ID and password.
- Hashes passwords with bcrypt.
- Issues 24-hour JWT bearer access tokens.
- Supports logout through token blacklisting.
- Provides password reset requests with short-lived reset tokens and email delivery through Resend.
- Returns the authenticated user's profile and supports profile updates.
- Supports profile picture upload and deletion through Cloudinary.

### Student and program management

- Stores student identity, student ID, name, email, program, year level, role, profile image, and fingerprint state.
- Tracks fingerprint status as `not_enrolled`, `pending`, `enrolled`, or `failed`.
- Supports the enrollment steps `pending`, `place_finger`, `remove_finger`, `place_again`, `success`, and `error`.
- Lists students by program, including their fingerprint status and assigned fingerprint ID.
- Creates, edits, and deletes programs for administrators.
- Provides student counts per program.
- Reserves the `OSA` program for the administrator account and excludes it from student program counts.

### Event management

- Creates, lists, retrieves, updates, and deletes attendance events.
- Stores an event title, description, date, start time, end time, location, creator, and optional target program.
- Rejects events dated in the past.
- Validates that an event's end time is after its start time.
- Calculates event status as `upcoming`, `ongoing`, or `done` using Asia/Manila time.
- Provides calendar data and a total event count.
- Can target an event to a specific program or make it available without a program restriction.

### Fingerprint enrollment and deletion

- Starts enrollment for a selected user and assigns an available fingerprint ID from 1 to 1000.
- Coordinates enrollment work across connected devices.
- Allows an ESP32 device to claim a pending enrollment so two devices cannot enroll the same user simultaneously.
- Reports enrollment progress and final success or failure.
- Resets a user's enrollment state when an operation is cancelled or fails.
- Unenrolls an existing fingerprint after confirming that an ESP32 device is online.
- Coordinates fingerprint deletion and handles stale or failed deletion callbacks.
- Prevents conflicting device operations and automatically clears stale non-attendance device modes.

### ESP32 device coordination

- Tracks device heartbeat, last-seen time, current mode, active event, pending deletion, and recognition state.
- Considers a device online when its last heartbeat is no more than 15 seconds old.
- Supports the device modes `idle`, `enroll`, `delete`, `attendance`, and `recognize`.
- Sends mode changes to connected devices over WebSockets.
- Responds to device WebSocket `ping` messages with `pong`.
- Provides individual and dashboard-wide device status endpoints.
- Runs a background watchdog that resets stale enrollment and deletion operations while preserving active attendance and recognition modes.
- Starts a background notification loop when the application starts.

### Live attendance

- Starts and stops attendance mode for a selected event.
- Associates the active event with all known devices.
- Accepts fingerprint marks from ESP32 devices only when:
  - the user exists and has an enrolled fingerprint;
  - the device has an active event;
  - the event is currently in progress in Asia/Manila time; and
  - the student belongs to the event's target program, when one is configured.
- Prevents duplicate attendance records for the same student and event.
- Supports attendance marking through the API using a student's ID as well as fingerprint device callbacks.
- Returns attendance updates for the current or selected event.

### Recognition testing

- Starts a recognition test for a selected enrolled user.
- Sends the recognition mode to online devices.
- Records whether the scanned fingerprint matches the selected user's fingerprint.
- Exposes the recognition result and returns devices to idle mode after processing.

### Attendance reporting and analytics

- Lists attendance records for a specific event.
- Produces attendance totals per event, optionally filtered by year.
- Produces attendance totals and percentages per program for the latest event.
- Provides an all-students attendance summary with present count, absence count, and total events.
- Identifies at-risk students based on repeated absences.
- Lists students per program for dashboard filtering.

### Notifications

- Creates event notifications for users shortly before events begin.
- Stores notifications in the database with title, message, type, read state, event, and timestamp.
- Sends Firebase Cloud Messaging push notifications when a user has a registered device token.
- Retrieves notifications for the authenticated user.
- Marks individual notifications as read.
- Deletes one notification or all notifications belonging to the authenticated user.
- Avoids duplicate event notifications for the same user and event.

### Health and availability

- Provides a lightweight `/ping` endpoint supporting `GET`, `POST`, and `HEAD`.
- Provides a database keep-alive endpoint that executes `SELECT 1`.
- Serves uploaded files from `/uploads`.
- Enables CORS for the configured ARA frontend deployments and local development on port 5173.

## Technology Stack

- Python 3
- FastAPI and Uvicorn
- SQLAlchemy 2
- PostgreSQL via `psycopg2-binary`
- Alembic database migrations
- Pydantic 2 request and response validation
- JWT and bcrypt authentication
- WebSockets for ESP32 device mode updates
- Firebase Admin SDK for push notifications
- Cloudinary for profile images
- Resend for password reset email delivery

## Project Layout

```text
app/
	main.py                  FastAPI application, middleware, startup tasks, and routers
	core/
		config.py              Environment-backed configuration values
		database.py            SQLAlchemy engine and database session management
		security.py            Password hashing, JWT, and token blacklist handling
	models/                  SQLAlchemy models for users, events, attendance, devices, and notifications
	routes/                  HTTP and WebSocket API endpoints
	schemas/                 Pydantic request and response schemas
	services/                Firebase and event notification services
	utils/                   Device state and stale-operation handling
alembic/
	versions/                Database migration history
uploads/
	profile_pictures/        Local upload directory used by the application
requirements.txt           Python dependencies
alembic.ini                Alembic configuration
```

## Requirements

- Python 3.10 or newer is recommended because the codebase uses modern type annotations.
- A PostgreSQL database. PostgreSQL URLs are automatically configured with `sslmode=require` when no SSL mode is already present.
- Credentials for the external services used by the enabled features.

## Installation

From the backend directory:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

Create a `.env` file in the backend directory before starting the API. Do not commit this file or service credentials.

## Environment Variables

### Required database and authentication variables

```env
DATABASE_URL=postgresql://username:password@host:5432/database
SECRET_KEY=replace-with-a-long-random-secret
ALGORITHM=HS256
```

`DATABASE_URL` is required when the application imports the database module. `SECRET_KEY` and `ALGORITHM` are required for JWT creation and validation.

### Required account and media service variables

The authentication module initializes these services at import time, so they must be present even if the related feature is not being tested:

```env
CLOUDINARY_CLOUD_NAME=your-cloud-name
CLOUDINARY_API_KEY=your-api-key
CLOUDINARY_API_SECRET=your-api-secret
RESEND_API_KEY=your-resend-api-key
ADMIN_NOTIFICATION_EMAIL=admin@example.com
```

Optional email settings:

```env
RESEND_FROM_EMAIL=onboarding@resend.dev
FRONTEND_URL=https://ara-system-app.vercel.app
```

### Firebase push notification variables

Use either a base64-encoded JSON credential or a credential file path:

```env
FIREBASE_CREDENTIALS_JSON=base64-encoded-service-account-json
```

or:

```env
FIREBASE_CREDENTIALS_PATH=app/core/firebase-adminsdk.json
```

The repository contains a default credential path. Keep production credentials outside source control and prefer a secret-managed environment variable.

### Legacy or optional configuration values

These values are read by `app/core/config.py` and may be used by deployment-specific integrations:

```env
DB_HOST=localhost
DB_USER=postgres
DB_PASSWORD=your-password
DB_NAME=ara_attendance
DB_PORT=5432
TEXTBELT_API_KEY=your-textbelt-key
```

## Running the API

Start the development server from the backend directory:

```powershell
uvicorn app.main:app --reload
```

The API is available at `http://127.0.0.1:8000`.

Interactive API documentation is available at:

- Swagger UI: `http://127.0.0.1:8000/docs`
- ReDoc: `http://127.0.0.1:8000/redoc`

The application creates missing tables on startup and starts its notification and device-watchdog background tasks. Use Alembic for versioned schema changes:

```powershell
alembic upgrade head
```

## API Reference

All protected endpoints use the header:

```text
Authorization: Bearer <access-token>
```

### Authentication: `/auth`

| Method | Endpoint                       | Purpose                                       |
| ------ | ------------------------------ | --------------------------------------------- |
| POST   | `/auth/register`               | Register the first administrator or a student |
| POST   | `/auth/login`                  | Authenticate with student ID and password     |
| POST   | `/auth/logout`                 | Blacklist the current bearer token            |
| POST   | `/auth/forgot-password`        | Request a password reset link                 |
| POST   | `/auth/reset-password`         | Set a new password using a valid reset token  |
| GET    | `/auth/profile`                | Get the current user's profile                |
| PUT    | `/auth/profile`                | Update the current user's profile             |
| POST   | `/auth/profile/upload-picture` | Upload a profile image, maximum 5 MB          |
| DELETE | `/auth/profile/delete-picture` | Remove the current profile image              |
| GET    | `/auth/admin-exists`           | Check whether an administrator account exists |

### Programs: `/programs`

| Method | Endpoint                            | Purpose                              |
| ------ | ----------------------------------- | ------------------------------------ |
| GET    | `/programs/`                        | List programs                        |
| POST   | `/programs/`                        | Create a program, administrator only |
| PUT    | `/programs/{program_id}`            | Update a program, administrator only |
| DELETE | `/programs/{program_id}`            | Delete a program, administrator only |
| GET    | `/programs/counts`                  | Return student totals by program     |
| GET    | `/programs/{program_code}/students` | List students in a program           |

### Events: `/events`

| Method | Endpoint             | Purpose                             |
| ------ | -------------------- | ----------------------------------- |
| POST   | `/events/`           | Create an event, administrator only |
| GET    | `/events/`           | List events in chronological order  |
| GET    | `/events/count`      | Count all events                    |
| GET    | `/events/calendar`   | Return calendar-oriented event data |
| GET    | `/events/{event_id}` | Retrieve one event                  |
| PUT    | `/events/{event_id}` | Update an event, administrator only |
| DELETE | `/events/{event_id}` | Delete an event, administrator only |

### Attendance: `/attendance`

| Method | Endpoint                              | Purpose                                           |
| ------ | ------------------------------------- | ------------------------------------------------- |
| POST   | `/attendance/update-status`           | Mark a student's attendance for the current event |
| GET    | `/attendance/updates`                 | Get attendance for the active event or `event_id` |
| GET    | `/attendance/by-event/{event_id}`     | Get detailed attendance for an event              |
| GET    | `/attendance/per-event`               | Get present totals per event, optionally by year  |
| GET    | `/attendance/per-program`             | Get latest-event attendance by program            |
| GET    | `/attendance/all-students-attendance` | Get each enrolled student's attendance summary    |
| GET    | `/attendance/at-risk`                 | Get students meeting the absence risk threshold   |
| GET    | `/attendance/students-per-program`    | Get attendance-oriented program student data      |

### Fingerprints and device operations: `/fingerprints`

| Method    | Endpoint                                       | Purpose                                     |
| --------- | ---------------------------------------------- | ------------------------------------------- |
| WebSocket | `/fingerprints/ws/{device_id}`                 | Connect an ESP32 and receive mode updates   |
| GET       | `/fingerprints/ws-status`                      | Inspect active WebSocket connections        |
| POST      | `/fingerprints/start-enrollment`               | Begin fingerprint enrollment                |
| GET       | `/fingerprints/check-enrollment`               | Poll for enrollment work from a device      |
| GET       | `/fingerprints/update-enrollment`              | Submit an enrollment step or result         |
| GET       | `/fingerprints/get-status`                     | Read enrollment status for a fingerprint ID |
| POST      | `/fingerprints/reset-enrollment/{user_id}`     | Reset a user's enrollment state             |
| POST      | `/fingerprints/cancel-operation`               | Reset pending device operations             |
| POST      | `/fingerprints/unenroll-fingerprint/{user_id}` | Begin fingerprint deletion                  |
| GET       | `/fingerprints/check-delete`                   | Poll for fingerprint deletion work          |
| GET       | `/fingerprints/device-status`                  | Check whether any device is online          |
| POST      | `/fingerprints/start-attendance`               | Start attendance mode for an event          |
| POST      | `/fingerprints/stop-attendance`                | Stop attendance mode                        |
| GET       | `/fingerprints/mark-attendance`                | Record a device fingerprint scan            |
| GET       | `/fingerprints/device-mode`                    | Read a device's current mode                |
| POST      | `/fingerprints/start-recognition/{user_id}`    | Start a recognition test                    |
| GET       | `/fingerprints/recognition-result`             | Submit a recognition result from a device   |
| GET       | `/fingerprints/get-recognition-result`         | Read the recognition result                 |

The device polling endpoints use the default device ID `esp32-default` when `device_id` is omitted. A deployment with multiple ESP32 units should provide a unique device ID for each unit.

### Device monitoring

| Method | Endpoint             | Purpose                                      |
| ------ | -------------------- | -------------------------------------------- |
| GET    | `/device/heartbeat`  | Update a device's last-seen time             |
| GET    | `/device/status`     | Check one device's online state              |
| GET    | `/device/status-all` | List all devices, modes, and last-seen times |

### Notifications: `/notifications`

| Method | Endpoint                                | Purpose                                 |
| ------ | --------------------------------------- | --------------------------------------- |
| GET    | `/notifications/`                       | List notifications for the current user |
| PATCH  | `/notifications/{notification_id}/read` | Mark one notification as read           |
| DELETE | `/notifications/{notification_id}`      | Delete one notification                 |
| DELETE | `/notifications/`                       | Delete all current-user notifications   |
| POST   | `/notifications/save-token`             | Save a Firebase device token            |

### Health

| Method | Endpoint         | Purpose                                         |
| ------ | ---------------- | ----------------------------------------------- |
| GET    | `/ping`          | Confirm that the API process is responding      |
| POST   | `/ping`          | Confirm that the API process is responding      |
| HEAD   | `/ping`          | Lightweight availability check                  |
| GET    | `/keep-alive-db` | Confirm that the database connection is working |

## Typical Workflows

### Administrator setup

1. Check `/auth/admin-exists`.
2. Register the first account with role `admin` when no administrator exists.
3. Log in through `/auth/login` and retain the returned bearer token.
4. Create programs for the student population.
5. Register students or allow student accounts to register with a program and year level.

### Fingerprint enrollment

1. Select a student who is not enrolled.
2. Call `/fingerprints/start-enrollment` with the student's user ID.
3. The ESP32 polls `/fingerprints/check-enrollment` and receives a fingerprint ID.
4. The ESP32 reports each enrollment step through `/fingerprints/update-enrollment`.
5. The dashboard polls `/fingerprints/get-status` until the status is `enrolled` or `failed`.

### Running an attendance event

1. Create an event with `/events/`.
2. Start attendance with `/fingerprints/start-attendance` and the event ID.
3. Devices scan enrolled fingerprints and call `/fingerprints/mark-attendance`.
4. The dashboard reads `/attendance/updates` or `/attendance/by-event/{event_id}`.
5. Stop attendance with `/fingerprints/stop-attendance`.

### Recognition test

1. Confirm that the target user has an enrolled fingerprint.
2. Call `/fingerprints/start-recognition/{user_id}`.
3. The device scans a fingerprint and reports `/fingerprints/recognition-result`.
4. Read the outcome from `/fingerprints/get-recognition-result`.

## Time Zone and Data Rules

- Event scheduling and attendance-window checks use Asia/Manila time.
- Events cannot be created or updated to a date in the past.
- An attendance record is unique per student and event.
- Only enrolled fingerprints can mark attendance.
- Program-restricted events reject scans from students outside the target program.
- Device heartbeats older than 15 seconds are treated as offline.

## Database Migrations

The repository includes Alembic migrations for the initial schema and later changes such as device state, fingerprint recognition, token blacklisting, nullable student fields, event programs, and attendance uniqueness.

```powershell
alembic upgrade head
```

To create a migration after changing SQLAlchemy models:

```powershell
alembic revision --autogenerate -m "describe schema change"
```

Review generated migrations before applying them to a shared or production database.

## Operational Notes

- The application creates missing tables at startup, but Alembic remains the source of truth for reproducible schema upgrades.
- The notification and device watchdog tasks run for the lifetime of the application process.
- The built-in watchdog can reset stale enrollment and deletion operations. It intentionally leaves attendance and recognition modes running.
- Profile image uploads are limited to JPG, JPEG, PNG, GIF, and WebP files and are limited to 5 MB.
- Keep `firebase-adminsdk.json`, `.env`, Cloudinary credentials, Resend credentials, and JWT secrets out of version control.
- The default CORS configuration allows the deployed ARA frontend URLs and `http://localhost:5173`. Update `app/main.py` when adding an approved frontend origin.
