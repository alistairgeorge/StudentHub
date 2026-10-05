import sqlite3


DATABASE = "studenthub.db"

COURSES = (
    ("BCA",),
    ("BSc IT",),
    ("MCA",),
    ("BTech Computer Science",),
    ("BBA",),
    ("MCom",),
)


def get_db_connection():

    connection = sqlite3.connect(DATABASE)

    connection.row_factory = sqlite3.Row

    connection.execute(
        "PRAGMA foreign_keys = ON"
    )

    return connection


def initialize_database():
    connection = get_db_connection()
    try:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS courses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE
            );

            CREATE TABLE IF NOT EXISTS students (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE,
                phone TEXT,
                gender TEXT,
                course_id INTEGER NOT NULL,
                date_of_birth TEXT,
                enrollment_date TEXT DEFAULT CURRENT_DATE,
                status TEXT NOT NULL DEFAULT 'Active',
                FOREIGN KEY (course_id) REFERENCES courses(id)
            );

            CREATE TABLE IF NOT EXISTS admins (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS teachers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE,
                phone TEXT,
                course_id INTEGER NOT NULL,
                qualification TEXT,
                hire_date TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'Active',
                FOREIGN KEY (course_id) REFERENCES courses(id)
            );

            CREATE TABLE IF NOT EXISTS timetable (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                course_id INTEGER NOT NULL,
                teacher_id INTEGER NOT NULL,
                subject TEXT NOT NULL,
                weekday TEXT NOT NULL
                    CHECK (weekday IN ('Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday')),
                period INTEGER NOT NULL CHECK (period BETWEEN 1 AND 6),
                FOREIGN KEY (course_id) REFERENCES courses(id) ON DELETE RESTRICT,
                FOREIGN KEY (teacher_id) REFERENCES teachers(id) ON DELETE RESTRICT,
                UNIQUE (course_id, weekday, period),
                UNIQUE (teacher_id, weekday, period)
            );

            CREATE TABLE IF NOT EXISTS timetable_seed (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                seeded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        connection.execute("BEGIN IMMEDIATE")
        existing_courses = {
            row["name"] for row in connection.execute("SELECT name FROM courses")
        }
        connection.executemany(
            "INSERT INTO courses (name) VALUES (?)",
            (course for course in COURSES if course[0] not in existing_courses),
        )
        connection.commit()
    finally:
        connection.close()
