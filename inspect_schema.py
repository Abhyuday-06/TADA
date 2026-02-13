
from automatic_ass import get_db_connection, get_table_prefix, USER_CONFIG

# Mock config
USER_CONFIG['regno'] = '24BCE5561'

def inspect():
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        prefix = get_table_prefix()
        print(f"\n--- Integirty Check for Prefix: {prefix} ---")
        
        # Get tables
        cur.execute(f"SELECT table_name FROM user_tables WHERE table_name LIKE '{prefix.upper()}%'")
        tables = [row[0] for row in cur.fetchall()]
        
        if not tables:
            print("No tables found!")
            return

        for t in tables:
            print(f"\nTABLE: {t}")
            cur.execute(f"SELECT column_name, data_type, data_length FROM user_tab_columns WHERE table_name = '{t}' ORDER BY column_id")
            for row in cur.fetchall():
                print(f"  - {row[0]} ({row[1]})")
                
        conn.close()
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    inspect()
