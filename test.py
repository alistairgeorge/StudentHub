from database import get_db_connection

connection = get_db_connection()
cursor = connection.cursor()

cursor.execute("""
SELECT
    students.id,
    students.name,
    students.email,
    courses.name AS course,
    students.status
FROM students
INNER JOIN courses
    ON students.course_id = courses.id
""")

cursor.execute("""
SELECT COUNT(*) AS total_students
FROM students
""")

result = cursor.fetchone()

print("Total Students:", result["total_students"])

cursor.execute("""
SELECT COUNT(*) AS inactive_students
FROM students
WHERE status = 'Inactive'
""")

result = cursor.fetchone()

print("Inactive Students:", result["inactive_students"])

cursor.execute("""
SELECT COUNT(*) AS total_courses
FROM courses
""")

result = cursor.fetchone()

print("Total Courses:", result["total_courses"])

cursor.execute("""
SELECT
    courses.name AS course,
    COUNT(students.id) AS total_students
FROM courses
LEFT JOIN students
    ON courses.id = students.course_id
GROUP BY courses.id, courses.name
ORDER BY total_students DESC
""")

results = cursor.fetchall()

for row in results:
    print(row["course"], row["total_students"])


students = cursor.fetchall()

for student in students:
    print(
        student["id"],
        student["name"],
        student["email"],
        student["course"],
        student["status"]
    )

connection.close()