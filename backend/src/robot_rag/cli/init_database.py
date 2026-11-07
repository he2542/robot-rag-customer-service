from robot_rag.shared.schema import init_database


def main():
    init_database()
    print("PostgreSQL vector schema ready")


if __name__ == "__main__":
    main()
