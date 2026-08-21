from __future__ import annotations

import os
from contextlib import contextmanager

import pyodbc


# ==========================================================
# SQL SERVER CONFIGURATION
# ==========================================================

DB_SERVER = os.getenv(
    "FILLPAC_DB_SERVER",
    r"WS-HDC3C14\SQLEXPRESS",
)

DB_NAME = os.getenv(
    "FILLPAC_DB_NAME",
    "FillPacAI",
)

DB_DRIVER = os.getenv(
    "FILLPAC_DB_DRIVER",
    "SQL Server",
)

DB_TRUSTED_CONNECTION = os.getenv(
    "FILLPAC_DB_TRUSTED_CONNECTION",
    "yes",
)


# ==========================================================
# CONNECTION STRING
# ==========================================================

CONNECTION_STRING = (
    f"DRIVER={{{DB_DRIVER}}};"
    f"SERVER={DB_SERVER};"
    f"DATABASE={DB_NAME};"
    f"Trusted_Connection={DB_TRUSTED_CONNECTION};"
    f"TrustServerCertificate=yes;"
)


# ==========================================================
# CONNECTION
# ==========================================================

def get_connection() -> pyodbc.Connection:
    """
    Create a SQL Server Express connection.
    """

    try:
        return pyodbc.connect(
            CONNECTION_STRING,
            timeout=10,
            autocommit=False,
        )

    except pyodbc.Error as exc:
        raise RuntimeError(
            "\n"
            "========================================\n"
            "SQL SERVER CONNECTION FAILED\n"
            "========================================\n"
            f"Server   : {DB_SERVER}\n"
            f"Database : {DB_NAME}\n"
            f"Driver   : {DB_DRIVER}\n"
            "\n"
            "Check:\n"
            "1. SQL Server Express is installed.\n"
            "2. SQL Server Express service is running.\n"
            "3. Database 'FillPacAI' exists.\n"
            "4. Windows authentication is enabled.\n"
            f"\nOriginal error:\n{exc}\n"
        ) from exc


# ==========================================================
# TRANSACTION CONTEXT
# ==========================================================

@contextmanager
def database_connection():
    """
    Safe SQL Server transaction context.
    """

    conn = get_connection()

    try:
        yield conn
        conn.commit()

    except Exception:
        conn.rollback()
        raise

    finally:
        conn.close()


# ==========================================================
# DATABASE INITIALIZATION
# ==========================================================

def initialize_database() -> None:
    """
    Verify SQL Server connection and selected database.
    """

    with database_connection() as conn:

        cursor = conn.cursor()

        cursor.execute(
            "SELECT @@SERVERNAME, DB_NAME()"
        )

        server_name, database_name = cursor.fetchone()

        if database_name.lower() != DB_NAME.lower():

            raise RuntimeError(
                f"Connected to unexpected database: "
                f"{database_name}. "
                f"Expected: {DB_NAME}"
            )

        print(
            f"SQL Server connected successfully: "
            f"{server_name} / {database_name}"
        )


def get_database_path() -> str:
    """
    Compatibility helper.

    SQL Server does not use a local .db file.
    """

    return (
        f"SQL Server: {DB_SERVER} / "
        f"Database: {DB_NAME}"
    )


DATABASE_PATH = get_database_path()