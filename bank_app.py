import os
import sqlite3
import hashlib
import secrets
from datetime import datetime
from getpass import getpass

DB_PATH = "bank.db"


def _hash_password(password: str, salt_hex: str) -> str:
    # PBKDF2-HMAC-SHA256 is in stdlib (hashlib)
    salt = bytes.fromhex(salt_hex)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 200_000)
    return dk.hex()


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def db_connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA journal_mode = WAL;")
    return conn


def db_init():
    with db_connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                salt_hex TEXT NOT NULL,
                pass_hash TEXT NOT NULL,
                is_admin INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS accounts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL UNIQUE,
                balance_cents INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                type TEXT NOT NULL,  -- DEPOSIT, WITHDRAW, TRANSFER_IN, TRANSFER_OUT, ADMIN_CREDIT, ADMIN_DEBIT
                amount_cents INTEGER NOT NULL,
                from_user_id INTEGER,
                to_user_id INTEGER,
                description TEXT,
                FOREIGN KEY (from_user_id) REFERENCES users(id),
                FOREIGN KEY (to_user_id) REFERENCES users(id)
            );

            CREATE INDEX IF NOT EXISTS idx_tx_created_at ON transactions(created_at);
            """
        )


def ensure_admin_exists():
    """
    Creates an admin if none exists.
    Default credentials:
      username: admin
      password: admin123
    (You can change after first run by editing the DB or extending the menu.)
    """
    with db_connect() as conn:
        cur = conn.execute("SELECT id FROM users WHERE is_admin = 1 LIMIT 1;")
        row = cur.fetchone()
        if row:
            return

        username = "admin"
        password = "admin123"

        salt_hex = secrets.token_hex(16)
        pass_hash = _hash_password(password, salt_hex)

        conn.execute(
            "INSERT INTO users (username, salt_hex, pass_hash, is_admin, created_at) VALUES (?, ?, ?, 1, ?);",
            (username, salt_hex, pass_hash, _now_iso()),
        )
        admin_id = conn.execute("SELECT id FROM users WHERE username = ?;", (username,)).fetchone()["id"]
        conn.execute(
            "INSERT INTO accounts (user_id, balance_cents, created_at) VALUES (?, 0, ?);",
            (admin_id, _now_iso()),
        )
        print("\n✅ Admin criado (primeira execução):")
        print("   usuário: admin")
        print("   senha:   admin123")
        print("⚠️ Troque isso depois.\n")


def _to_cents(amount_str: str) -> int:
    """
    Accepts values like:
      10
      10.50
      10,50
    """
    s = amount_str.strip().replace(",", ".")
    if not s:
        raise ValueError("Valor vazio.")
    if "." in s:
        whole, frac = s.split(".", 1)
        frac = (frac + "00")[:2]
    else:
        whole, frac = s, "00"
    if whole.startswith("+"):
        whole = whole[1:]
    if not whole.isdigit() or not frac.isdigit():
        raise ValueError("Valor inválido. Use números, ex: 25.50")
    cents = int(whole) * 100 + int(frac)
    return cents


def _fmt_money(cents: int) -> str:
    sign = "-" if cents < 0 else ""
    cents = abs(cents)
    return f"{sign}R$ {cents // 100}.{cents % 100:02d}"


def get_user_by_username(conn, username: str):
    cur = conn.execute("SELECT * FROM users WHERE username = ?;", (username.strip(),))
    return cur.fetchone()


def get_account_by_user_id(conn, user_id: int):
    cur = conn.execute("SELECT * FROM accounts WHERE user_id = ?;", (user_id,))
    return cur.fetchone()


def create_user(conn, username: str, password: str, is_admin: bool = False):
    username = username.strip()
    if len(username) < 3:
        raise ValueError("Username precisa ter pelo menos 3 caracteres.")
    if len(password) < 6:
        raise ValueError("Senha precisa ter pelo menos 6 caracteres.")

    salt_hex = secrets.token_hex(16)
    pass_hash = _hash_password(password, salt_hex)

    conn.execute(
        "INSERT INTO users (username, salt_hex, pass_hash, is_admin, created_at) VALUES (?, ?, ?, ?, ?);",
        (username, salt_hex, pass_hash, 1 if is_admin else 0, _now_iso()),
    )
    user_id = conn.execute("SELECT id FROM users WHERE username = ?;", (username,)).fetchone()["id"]
    conn.execute(
        "INSERT INTO accounts (user_id, balance_cents, created_at) VALUES (?, 0, ?);",
        (user_id, _now_iso()),
    )
    return user_id


def authenticate(conn, username: str, password: str):
    user = get_user_by_username(conn, username)
    if not user:
        return None
    calc = _hash_password(password, user["salt_hex"])
    if secrets.compare_digest(calc, user["pass_hash"]):
        return user
    return None


def deposit(conn, user_id: int, amount_cents: int, description: str = "Depósito"):
    if amount_cents <= 0:
        raise ValueError("Depósito precisa ser maior que zero.")

    conn.execute("BEGIN IMMEDIATE;")
    acc = get_account_by_user_id(conn, user_id)
    if not acc:
        conn.execute("ROLLBACK;")
        raise ValueError("Conta não encontrada.")

    new_bal = acc["balance_cents"] + amount_cents
    conn.execute("UPDATE accounts SET balance_cents = ? WHERE user_id = ?;", (new_bal, user_id))
    conn.execute(
        """
        INSERT INTO transactions (created_at, type, amount_cents, from_user_id, to_user_id, description)
        VALUES (?, 'DEPOSIT', ?, NULL, ?, ?);
        """,
        (_now_iso(), amount_cents, user_id, description),
    )
    conn.execute("COMMIT;")


def withdraw(conn, user_id: int, amount_cents: int, description: str = "Saque"):
    if amount_cents <= 0:
        raise ValueError("Saque precisa ser maior que zero.")

    conn.execute("BEGIN IMMEDIATE;")
    acc = get_account_by_user_id(conn, user_id)
    if not acc:
        conn.execute("ROLLBACK;")
        raise ValueError("Conta não encontrada.")
    if acc["balance_cents"] < amount_cents:
        conn.execute("ROLLBACK;")
        raise ValueError("Saldo insuficiente.")

    new_bal = acc["balance_cents"] - amount_cents
    conn.execute("UPDATE accounts SET balance_cents = ? WHERE user_id = ?;", (new_bal, user_id))
    conn.execute(
        """
        INSERT INTO transactions (created_at, type, amount_cents, from_user_id, to_user_id, description)
        VALUES (?, 'WITHDRAW', ?, ?, NULL, ?);
        """,
        (_now_iso(), amount_cents, user_id, description),
    )
    conn.execute("COMMIT;")


def transfer(conn, from_user_id: int, to_username: str, amount_cents: int, description: str = "Transferência"):
    if amount_cents <= 0:
        raise ValueError("Transferência precisa ser maior que zero.")

    to_user = get_user_by_username(conn, to_username)
    if not to_user:
        raise ValueError("Usuário destino não existe.")
    to_user_id = to_user["id"]
    if to_user_id == from_user_id:
        raise ValueError("Você não pode transferir para você mesmo.")

    conn.execute("BEGIN IMMEDIATE;")

    from_acc = get_account_by_user_id(conn, from_user_id)
    to_acc = get_account_by_user_id(conn, to_user_id)
    if not from_acc or not to_acc:
        conn.execute("ROLLBACK;")
        raise ValueError("Conta origem/destino não encontrada.")

    if from_acc["balance_cents"] < amount_cents:
        conn.execute("ROLLBACK;")
        raise ValueError("Saldo insuficiente.")

    conn.execute(
        "UPDATE accounts SET balance_cents = balance_cents - ? WHERE user_id = ?;",
        (amount_cents, from_user_id),
    )
    conn.execute(
        "UPDATE accounts SET balance_cents = balance_cents + ? WHERE user_id = ?;",
        (amount_cents, to_user_id),
    )

    conn.execute(
        """
        INSERT INTO transactions (created_at, type, amount_cents, from_user_id, to_user_id, description)
        VALUES (?, 'TRANSFER_OUT', ?, ?, ?, ?);
        """,
        (_now_iso(), amount_cents, from_user_id, to_user_id, description),
    )
    conn.execute(
        """
        INSERT INTO transactions (created_at, type, amount_cents, from_user_id, to_user_id, description)
        VALUES (?, 'TRANSFER_IN', ?, ?, ?, ?);
        """,
        (_now_iso(), amount_cents, from_user_id, to_user_id, description),
    )

    conn.execute("COMMIT;")


def admin_credit(conn, admin_id: int, target_username: str, amount_cents: int, description: str = "Crédito admin"):
    if amount_cents == 0:
        raise ValueError("Valor não pode ser zero.")

    target = get_user_by_username(conn, target_username)
    if not target:
        raise ValueError("Usuário alvo não existe.")

    target_id = target["id"]

    conn.execute("BEGIN IMMEDIATE;")
    acc = get_account_by_user_id(conn, target_id)
    if not acc:
        conn.execute("ROLLBACK;")
        raise ValueError("Conta do usuário alvo não encontrada.")

    new_bal = acc["balance_cents"] + amount_cents
    if new_bal < 0:
        conn.execute("ROLLBACK;")
        raise ValueError("Operação deixaria o saldo negativo (bloqueado).")

    conn.execute("UPDATE accounts SET balance_cents = ? WHERE user_id = ?;", (new_bal, target_id))
    tx_type = "ADMIN_CREDIT" if amount_cents > 0 else "ADMIN_DEBIT"
    conn.execute(
        """
        INSERT INTO transactions (created_at, type, amount_cents, from_user_id, to_user_id, description)
        VALUES (?, ?, ?, ?, ?, ?);
        """,
        (_now_iso(), tx_type, abs(amount_cents), admin_id, target_id, description),
    )
    conn.execute("COMMIT;")


def get_balance(conn, user_id: int) -> int:
    acc = get_account_by_user_id(conn, user_id)
    return acc["balance_cents"] if acc else 0


def get_statement(conn, user_id: int, limit: int = 20):
    cur = conn.execute(
        """
        SELECT t.*, fu.username AS from_username, tu.username AS to_username
        FROM transactions t
        LEFT JOIN users fu ON fu.id = t.from_user_id
        LEFT JOIN users tu ON tu.id = t.to_user_id
        WHERE t.from_user_id = ? OR t.to_user_id = ?
        ORDER BY t.id DESC
        LIMIT ?;
        """,
        (user_id, user_id, limit),
    )
    return cur.fetchall()

def prompt_choice(title: str, options: list[str]) -> int:
    print("\n" + title)
    for i, opt in enumerate(options, start=1):
        print(f"  {i}) {opt}")
    while True:
        pick = input("> ").strip()
        if pick.isdigit() and 1 <= int(pick) <= len(options):
            return int(pick)
        print("Escolha inválida.")


def prompt_amount(label: str) -> int:
    while True:
        s = input(f"{label} (ex: 25.50): ").strip()
        try:
            return _to_cents(s)
        except Exception as e:
            print(f"Erro: {e}")


def screen_statement(conn, user):
    limit = 20
    rows = get_statement(conn, user["id"], limit=limit)
    print("\n📄 EXTRATO (últimas 20 transações)")
    if not rows:
        print("  (vazio)")
        return
    for r in rows:
        created = r["created_at"]
        ttype = r["type"]
        amt = r["amount_cents"]
        desc = r["description"] or ""
        fu = r["from_username"] or "-"
        tu = r["to_username"] or "-"
        print(f"  #{r['id']} | {created} | {ttype:<12} | {_fmt_money(amt)} | {fu} -> {tu} | {desc}")


def user_menu(conn, user):
    while True:
        bal = get_balance(conn, user["id"])
        print("\n" + "=" * 45)
        print(f"👤 Logado como: {user['username']}  |  Saldo: {_fmt_money(bal)}")
        print("=" * 45)

        options = [
            "Ver extrato",
            "Depositar",
            "Sacar",
            "Transferir",
        ]
        if user["is_admin"]:
            options += [
                "ADMIN: Criar usuário",
                "ADMIN: Creditar/Debitar saldo de usuário",
            ]
        options += ["Sair"]

        choice = prompt_choice("Menu:", options)

        try:
            if options[choice - 1] == "Ver extrato":
                screen_statement(conn, user)

            elif options[choice - 1] == "Depositar":
                amt = prompt_amount("Valor do depósito")
                desc = input("Descrição (opcional): ").strip() or "Depósito"
                deposit(conn, user["id"], amt, desc)
                print("✅ Depósito realizado.")

            elif options[choice - 1] == "Sacar":
                amt = prompt_amount("Valor do saque")
                desc = input("Descrição (opcional): ").strip() or "Saque"
                withdraw(conn, user["id"], amt, desc)
                print("✅ Saque realizado.")

            elif options[choice - 1] == "Transferir":
                to_user = input("Usuário destino: ").strip()
                amt = prompt_amount("Valor da transferência")
                desc = input("Descrição (opcional): ").strip() or "Transferência"
                transfer(conn, user["id"], to_user, amt, desc)
                print("✅ Transferência realizada.")

            elif options[choice - 1] == "ADMIN: Criar usuário":
                if not user["is_admin"]:
                    raise ValueError("Sem permissão.")
                new_user = input("Novo username: ").strip()
                new_pass = getpass("Nova senha (min 6): ")
                create_user(conn, new_user, new_pass, is_admin=False)
                print("✅ Usuário criado.")

            elif options[choice - 1] == "ADMIN: Creditar/Debitar saldo de usuário":
                if not user["is_admin"]:
                    raise ValueError("Sem permissão.")
                target = input("Username do usuário alvo: ").strip()
                print("Digite valor POSITIVO para creditar, NEGATIVO para debitar.")
                while True:
                    raw = input("Valor (ex: 100.00 ou -50.00): ").strip().replace(",", ".")
                    try:
                        sign = -1 if raw.startswith("-") else 1
                        raw2 = raw[1:] if raw.startswith("-") else raw
                        cents = _to_cents(raw2) * sign
                        break
                    except Exception as e:
                        print(f"Erro: {e}")

                desc = input("Descrição (opcional): ").strip() or "Ajuste admin"
                admin_credit(conn, user["id"], target, cents, desc)
                print("✅ Ajuste admin realizado.")

            elif options[choice - 1] == "Sair":
                print("👋 Logout.")
                return

        except Exception as e:
            print(f"❌ Erro: {e}")


def main():
    db_init()
    ensure_admin_exists()

    while True:
        print("\n" + "-" * 45)
        print("🏦 BANCO (CLI) - Python + SQLite")
        print("-" * 45)
        choice = prompt_choice("Escolha:", ["Login", "Criar conta", "Sair"])

        if choice == 1:
            username = input("Username: ").strip()
            password = getpass("Senha: ")
            with db_connect() as conn:
                user = authenticate(conn, username, password)
                if not user:
                    print("❌ Login inválido.")
                    continue
                user_menu(conn, user)

        elif choice == 2:
            username = input("Novo username: ").strip()
            password = getpass("Senha (min 6): ")
            with db_connect() as conn:
                try:
                    create_user(conn, username, password, is_admin=False)
                    print("✅ Conta criada. Agora faça login.")
                except sqlite3.IntegrityError:
                    print("❌ Esse username já existe.")
                except Exception as e:
                    print(f"❌ Erro: {e}")

        else:
            print("Até mais!")
            break


if __name__ == "__main__":
    main()