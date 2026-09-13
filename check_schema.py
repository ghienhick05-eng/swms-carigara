import sqlite3
con = sqlite3.connect('db.sqlite3')

print("--- waste_collection ---")
for r in con.execute("SELECT sql FROM sqlite_master WHERE name='waste_collection'"):
    print(r[0])

print("\n--- waste_actionplan ---")
for r in con.execute("SELECT sql FROM sqlite_master WHERE name='waste_actionplan'"):
    print(r[0])

print("\n--- applied migrations ---")
for r in con.execute("SELECT app, name FROM django_migrations WHERE app='waste' ORDER BY id"):
    print(r)

print("--- collection rows ---")
for r in con.execute("SELECT id, scheduled_date, status, weight_kg, date_collected FROM waste_collection"):
    print(r)