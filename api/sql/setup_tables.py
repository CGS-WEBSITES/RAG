import sys
from pathlib import Path

import psycopg2

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT_DIR))

from api.config import Config

SQL_DIR = Path(__file__).parent


def _execute_sql_file(cur, path: Path) -> None:
    print(f"Executando {path.name}...")
    with open(path, "r") as f:
        sql = f.read()
    cur.execute(sql)


def setup_tables():
    print("=" * 50)
    print("SETUP DE TABELAS")
    print("=" * 50)
    print(f"Conectando ao banco: {Config.DB_HOST}:{Config.DB_PORT}/{Config.DB_NAME}")

    try:
        conn = psycopg2.connect(
            host=Config.DB_HOST,
            port=Config.DB_PORT,
            dbname=Config.DB_NAME,
            user=Config.DB_USER,
            password=Config.DB_PASSWORD,
        )
        print("✓ Conexão estabelecida")

        cur = conn.cursor()

        create_file = SQL_DIR / "create_tables.sql"
        if not create_file.exists():
            raise FileNotFoundError(f"Arquivo não encontrado: {create_file}")
        _execute_sql_file(cur, create_file)

        migrations_file = SQL_DIR / "migrations.sql"
        if migrations_file.exists():
            _execute_sql_file(cur, migrations_file)
        else:
            print("Nenhum arquivo migrations.sql encontrado, pulando.")

        conn.commit()

        print("=" * 50)
        print("✓ TABELAS CRIADAS/ATUALIZADAS COM SUCESSO!")
        print("=" * 50)

        cur.execute(
            """
            SELECT tablename
            FROM pg_tables
            WHERE schemaname = 'public'
            AND tablename IN ('documents', 'chat_history', 'logistica_status', 'tickets', 'conhecimento_ips')
            ORDER BY tablename
            """
        )
        print("\nTabelas disponíveis:")
        for (tablename,) in cur.fetchall():
            print(f"  - {tablename}")

        cur.close()
        conn.close()
        return 0

    except Exception as e:
        print("=" * 50)
        print("✗ ERRO AO CRIAR TABELAS")
        print("=" * 50)
        print(f"Erro: {e}")
        import traceback

        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(setup_tables())
