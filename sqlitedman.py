# a script which uses the model file scan all tables in the database
# and print the table names and their columns
# then ask me whether I want to copy the table data into csv files
# or load the csv files into the database

from core import models, database_s as database
from sqlalchemy import text
import pandas as pd

def get_table_info(session_factory):
    with session_factory() as session:
        result = session.execute(text("SELECT name FROM sqlite_master WHERE type='table';"))
        tables = [row[0] for row in result.fetchall()]
        table_columns = {}
        for table in tables:
            result = session.execute(text(f"PRAGMA table_info({table});"))
            columns = [row[1] for row in result.fetchall()]
            table_columns[table] = columns
        return table_columns

def export_tables_to_csv(session_factory, table_columns):
    with session_factory() as session:
        for table, columns in table_columns.items():
            result = session.execute(text(f"SELECT * FROM {table}"))
            rows = result.fetchall()
            df = pd.DataFrame(rows, columns=columns)
            df.to_csv(f"{table}.csv", index=False)
            print(f"Exported {table} to {table}.csv")

def import_csv_to_tables(session_factory, table_columns):
    with session_factory() as session:
        for table, columns in table_columns.items():
            try:
                df = pd.read_csv(f"{table}.csv")
                if not set(columns).issubset(df.columns):
                    print(f"CSV for {table} does not match table columns. Skipping.")
                    continue
                for _, row in df.iterrows():
                    values = ','.join([f':{col}' for col in columns])
                    insert_stmt = text(f"INSERT INTO {table} ({','.join(columns)}) VALUES ({values})")
                    session.execute(insert_stmt, row[columns].to_dict())
                session.commit()
                print(f"Imported {table}.csv into {table}")
            except FileNotFoundError:
                print(f"No CSV found for {table}, skipping.")

def main():
    table_columns = get_table_info(database.SessionLocal)
    print("Tables and columns:")
    for table, columns in table_columns.items():
        print(f"{table}: {columns}")
    action = input("Type 'export' to export tables to CSV, 'import' to import CSVs to tables: ").strip().lower()
    if action == 'export':
        export_tables_to_csv(database.SessionLocal, table_columns)
    elif action == 'import':
        import_csv_to_tables(database.SessionLocal, table_columns)
    else:
        print("No action taken.")

if __name__ == "__main__":
    main()
