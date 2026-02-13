import os
import sys
from pathlib import Path
import psycopg2

# Adicionar o diretório raiz ao PYTHONPATH
ROOT_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT_DIR))

# Agora pode importar
from api.config import Config


def setup_tables():
    """Cria as tabelas necessárias no banco de dados"""
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
        print("Lendo arquivo SQL...")

        sql_file = Path(__file__).parent / "create_tables.sql"

        if not sql_file.exists():
            raise FileNotFoundError(f"Arquivo SQL não encontrado: {sql_file}")

        with open(sql_file, "r") as f:
            sql = f.read()

        print("Executando criação de tabelas...")
        cur = conn.cursor()
        cur.execute(sql)
        conn.commit()

        print("=" * 50)
        print("✓ TABELAS CRIADAS COM SUCESSO!")
        print("=" * 50)

        # Listar tabelas criadas
        cur.execute(
            """
            SELECT tablename
            FROM pg_tables
            WHERE schemaname = 'public'
            AND tablename IN ('logistica_status', 'tickets', 'conhecimento_ips')
        """
        )

        tabelas = cur.fetchall()
        print("\nTabelas criadas:")
        for tabela in tabelas:
            print(f"  - {tabela[0]}")

        cur.close()
        conn.close()

        return 0

    except Exception as e:
        print("=" * 50)
        print(f"✗ ERRO AO CRIAR TABELAS")
        print("=" * 50)
        print(f"Erro: {e}")
        import traceback

        traceback.print_exc()
        return 1


if __name__ == "__main__":
    exit_code = setup_tables()
    sys.exit(exit_code)
