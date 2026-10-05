from database import get_db_connection


connection = get_db_connection()

cursor = connection.cursor()


cursor.execute(
    "SELECT * FROM courses"
)

courses = cursor.fetchall()


print("\nCOURSES")
print("--------------------------------")

for course in courses:

    print(
        course["id"],
        course["name"]
    )


cursor.execute(
    "SELECT * FROM students"
)

students = cursor.fetchall()


print("\nSTUDENTS")
print("--------------------------------")

for student in students:

    print(
        student["id"],
        student["name"],
        student["email"],
        student["course_id"],
        student["status"]
    )


connection.close()
