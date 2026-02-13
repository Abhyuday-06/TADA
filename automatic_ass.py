"""
TADA - The Automatic DBMS Assignment solver
============================================
Automates DBMS lab exercises:
  1. Parse exercise PDFs → extract tables + practice questions
  2. Use AI (Gemini) to generate SQL queries
  3. Execute against Oracle DB
  4. Generate formatted Word + PDF documents with terminal screenshots
"""

import oracledb
import pandas as pd
from PIL import Image, ImageDraw, ImageFont
import os
import re
import glob
import sys
import platform
import warnings
import argparse
from dotenv import load_dotenv

load_dotenv()

from pdf_parser import parse_exercise_pdf, find_exercise_pdfs
from ai_solver import generate_all, configure_gemini
from export import generate_docx, convert_to_pdf

# Suppress pandas UserWarning about raw DB connections
warnings.filterwarnings('ignore', message='.*pandas only supports SQLAlchemy connectable.*')

# ==========================================
#              CONFIGURATION
# ==========================================
DB_CONFIG = {
    "user": os.getenv("DB_USER", "system"),
    "password": os.getenv("DB_PASSWORD", ""),
    "service_name": os.getenv("DB_SERVICE", "xe"),
    "host": os.getenv("DB_HOST", "localhost"),
    "port": int(os.getenv("DB_PORT", "1521"))
}

USER_CONFIG = {
    "regno": "",
    "name": "",
    "labNo": "0",
    "labTitle": "Practice Exercise",
    "faculty": os.getenv("FACULTY", "Dr.S.Geetha"),
    "slot": os.getenv("LAB_SLOT", "L19+20"),
    "classNo": os.getenv("CLASS_NO", "2025260503021")
}

DEFAULT_INPUT_DIR = os.getenv("LAB_DIR", r"E:\VIT\Sem 4\DBMS\Lab-Exercises")

# ==========================================
#        SMART DB CONNECTION
# ==========================================
def find_oracle_home():
    """Searches for Oracle Client libraries via registry, env vars, and common paths."""
    # Check ORACLE_HOME env var first
    env_home = os.getenv("ORACLE_HOME")
    if env_home:
        bin_path = os.path.join(env_home, "bin")
        if os.path.exists(bin_path):
            return bin_path

    # Check Windows registry
    if platform.system() == "Windows":
        try:
            import winreg
            oracle_key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\ORACLE")
            i = 0
            while True:
                try:
                    subkey_name = winreg.EnumKey(oracle_key, i)
                    if subkey_name.startswith("KEY_"):
                        subkey = winreg.OpenKey(oracle_key, subkey_name)
                        try:
                            home, _ = winreg.QueryValueEx(subkey, "ORACLE_HOME")
                            if home and os.path.exists(os.path.join(home, "bin")):
                                return os.path.join(home, "bin")
                        except FileNotFoundError:
                            pass
                        winreg.CloseKey(subkey)
                    i += 1
                except OSError:
                    break
            winreg.CloseKey(oracle_key)
        except Exception:
            pass

    # Glob search common install locations
    search_patterns = [
        r"C:\Oracle\app\*\product\*\dbhomeXE\bin",
        r"C:\app\*\product\*\dbhomeXE\bin",
        r"C:\oraclexe\app\oracle\product\*\server\bin",
        r"C:\app\*\product\*\client_*\bin",
        r"C:\app\*\product\*\dbhome_*\bin",
        r"C:\Oracle\app\*\product\*\dbhome_*\bin",
    ]
    for pattern in search_patterns:
        matches = glob.glob(pattern)
        if matches:
            return matches[0]
    return None


_thick_initialized = False

def get_db_connection():
    """
    Tries Network (Thin) mode first, falls back to Direct (Thick/Bequeath) mode.
    """
    global _thick_initialized
    user = DB_CONFIG["user"]
    pwd = DB_CONFIG["password"]
    dsn_str = f"{DB_CONFIG['host']}:{DB_CONFIG['port']}/{DB_CONFIG['service_name']}"

    # Attempt 1: Thin Mode (network via listener)
    try:
        print(f"[*] Attempting network connection to {dsn_str}...")
        conn = oracledb.connect(user=user, password=pwd, dsn=dsn_str)
        print("    [+] Success! Connected via Network.")
        return conn
    except oracledb.Error as e:
        error_msg = str(e)
        if any(code in error_msg for code in ["6005", "10061", "12514", "12541", "12170"]):
            print(f"    [-] Network failed. Attempting Direct Connection...")
        else:
            print(f"    [!] Connection failed: {error_msg}")
            raise e

    # Attempt 2: Thick Mode (bequeath, no listener needed)
    oracle_bin = find_oracle_home()
    if not oracle_bin:
        raise Exception("Could not find Oracle installation. Set ORACLE_HOME in .env or system environment.")

    print(f"    [+] Found Oracle at: {oracle_bin}")
    try:
        if not _thick_initialized:
            oracledb.init_oracle_client(lib_dir=oracle_bin)
            _thick_initialized = True
        os.environ["ORACLE_SID"] = "XE"
        os.environ["ORACLE_HOME"] = os.path.dirname(oracle_bin)  # parent of bin/
        conn = oracledb.connect(user=user, password=pwd)
        print("    [+] Success! Connected via Direct Driver (bequeath).")
        return conn
    except Exception as e:
        print(f"    [!] Direct connection also failed: {e}")
        raise e


def drop_tables_by_prefix(conn, prefix):
    """Drop all tables starting with the given prefix."""
    try:
        with conn.cursor() as cur:
            # Oracle
            try:
                cur.execute(f"SELECT table_name FROM user_tables WHERE table_name LIKE '{prefix.upper()}%'")
                tables = [row[0] for row in cur.fetchall()]
                for table in tables:
                    try:
                        cur.execute(f"DROP TABLE {table} CASCADE CONSTRAINTS")
                        print(f"    Dropped existing table: {table}")
                    except Exception as e:
                        print(f"    [!] Failed to drop {table}: {e}")
            except Exception as e:
                pass # Might not be Oracle or other error
    except Exception as e:
        print(f"  [!] Error during table cleanup: {e}")


# ==========================================
#        TERMINAL SCREENSHOT GENERATOR
# ==========================================
def _wrap_text(text, max_chars=100):
    """Wrap lines longer than max_chars."""
    lines = text.split('\n')
    wrapped = []
    for line in lines:
        while len(line) > max_chars:
            # Try to break at a space
            break_at = line.rfind(' ', 0, max_chars)
            if break_at == -1:
                break_at = max_chars
            wrapped.append(line[:break_at])
            line = '  ' + line[break_at:].lstrip()
        wrapped.append(line)
    return '\n'.join(wrapped)


def create_terminal_screenshot(query, result_text, filename):
    """Renders SQL query + output onto a black terminal-style image."""
    bg_color = (12, 12, 12)
    text_color = (204, 204, 204)
    font_size = 15
    padding = 30
    max_width = 900  # Max image width in pixels

    try:
        if platform.system() == "Windows":
            font = ImageFont.truetype("consola.ttf", font_size)
        elif platform.system() == "Darwin":
            font = ImageFont.truetype("Menlo.ttc", font_size)
        else:
            font = ImageFont.truetype("DejaVuSansMono.ttf", font_size)
    except:
        font = ImageFont.load_default()

    # Wrap long lines
    wrapped_query = _wrap_text(query, max_chars=95)
    wrapped_result = _wrap_text(result_text, max_chars=95)

    header = f"SQL> {wrapped_query};\n"
    body = f"\n{wrapped_result}\n"
    footer = "\nSQL> _"
    full_text = header + body + footer

    dummy_img = Image.new('RGB', (1, 1))
    draw = ImageDraw.Draw(dummy_img)
    bbox = draw.textbbox((0, 0), full_text, font=font)
    
    width = min(bbox[2] + (padding * 2), max_width)
    # If content is wider than max, re-wrap with fewer chars
    if bbox[2] + (padding * 2) > max_width:
        wrapped_query = _wrap_text(query, max_chars=80)
        wrapped_result = _wrap_text(result_text, max_chars=80)
        header = f"SQL> {wrapped_query};\n"
        body = f"\n{wrapped_result}\n"
        full_text = header + body + footer
        bbox = draw.textbbox((0, 0), full_text, font=font)
        width = bbox[2] + (padding * 2)
    
    height = bbox[3] + (padding * 2)

    img = Image.new('RGB', (width, height), color=bg_color)
    d = ImageDraw.Draw(img)
    d.text((padding, padding), full_text, font=font, fill=text_color)
    
    img.save(filename)
    return filename


# ==========================================
#        SQL EXECUTION
# ==========================================
def execute_sql_safely(conn, sql):
    """
    Executes SQL and returns result text.
    SELECT → pretty DataFrame; DDL/DML → status message.
    """
    clean_sql = sql.strip().upper()
    try:
        if clean_sql.startswith("SELECT") or clean_sql.startswith("WITH"):
            df = pd.read_sql(sql, conn)
            if df.empty:
                return "no rows selected"
            return df.to_string(index=False)
        else:
            with conn.cursor() as cursor:
                cursor.execute(sql)
                if clean_sql.startswith("CREATE"): return "Table created."
                if clean_sql.startswith("DROP"): return "Table dropped."
                if clean_sql.startswith("ALTER"): return "Table altered."
                if clean_sql.startswith("INSERT"): return "1 row created."
                if clean_sql.startswith("UPDATE"): return f"{cursor.rowcount} rows updated."
                if clean_sql.startswith("DELETE"): return f"{cursor.rowcount} rows deleted."
                return "Command executed successfully."
    except Exception as e:
        return f"ERROR at line 1:\n{e}"


# ==========================================
#        USER CONFIG INPUT
# ==========================================
def set_user_config():
    """Ask for name and registration number."""
    print("\n--- Student Details ---")
    name = input("Name: ").strip()
    regno = input("Registration No.: ").strip()

    if name:
        USER_CONFIG["name"] = name
    if regno:
        USER_CONFIG["regno"] = regno


def get_table_prefix():
    """Derive table prefix from registration number (e.g., 24BCE5561 -> bce5561_)."""
    regno = USER_CONFIG["regno"]
    # Extract the alphanumeric suffix (e.g., BCE5561 from 24BCE5561)
    match = re.search(r'(\d{2})([A-Z]+\d+)', regno, re.IGNORECASE)
    if match:
        return match.group(2).lower() + "_"
    return regno.lower().replace(" ", "") + "_"


# ==========================================
#    MAIN: PROCESS EXERCISE FROM PDF
# ==========================================
def process_exercise(
    pdf_path: str,
    output_dir: str = None,
    db_type: str = "oracle",
    skip_db: bool = False,
    font_name: str = "Calibri"
):
    """
    Full pipeline: Parse PDF → AI solve → DB execute → Generate docs.
    
    Args:
        pdf_path: Path to the exercise PDF
        output_dir: Where to save output (default: same as PDF directory)
        db_type: "oracle" or "mysql"
        skip_db: If True, generate docs without executing SQL
    """
    print(f"\n{'='*60}")
    print(f"  Processing: {os.path.basename(pdf_path)}")
    print(f"{'='*60}")
    
    # 1. Check database connectivity first (unless skipping DB)
    conn = None
    if not skip_db:
        print("\n[1/5] Checking database connectivity...")
        try:
            conn = get_db_connection()
            print("  [+] Database connection successful")
        except Exception as e:
            print(f"  [!] Cannot connect to database: {e}")
            print("  [!] Fix your DB settings in .env or use --skip-db")
            return
    else:
        print("\n[1/5] Skipping database check (--skip-db)")
    
    # 2. Parse PDF
    print("\n[2/5] Parsing exercise PDF...")
    parsed = parse_exercise_pdf(pdf_path)
    print(f"  Exercise #{parsed['exercise_number']}: {parsed['exercise_title']}")
    
    # 3. Generate SQL with AI
    print("\n[3/5] Generating SQL with AI (Gemini)...")
    table_prefix = get_table_prefix()
    ai_result = generate_all(parsed['practice_section'], table_prefix, db_type)
    
    setup_items = ai_result['setup']
    query_items = ai_result['queries']
    
    if not setup_items and not query_items:
        print("  [!] AI returned no results. Check your API key and try again.")
        if conn:
            conn.close()
        return
    
    print(f"  Generated: {len(setup_items)} setup + {len(query_items)} query statements")
    
    # 4. Execute SQL against database
    all_items = setup_items + query_items
    
    if not skip_db and conn:
        print("\n[4/5] Executing SQL against database...")
        try:
            # Drop existing tables first (aggressive cleanup)
            print("  Cleaning up existing tables...")
            table_prefix = get_table_prefix()
            drop_tables_by_prefix(conn, table_prefix)
            
            # (Old cleanup Logic removed/redundant but harmless if kept, but let's replace it to be cleaner)
             # Execute setup (CREATE + INSERT)
            for i, item in enumerate(setup_items):
                result = execute_sql_safely(conn, item['sql'])
                item['result'] = result
                status = "+" if "ERROR" not in result else "x"
                print(f"    [{status}] {item['q'][:60]}")
            
            conn.commit()
            
            # Execute practice queries
            for i, item in enumerate(query_items):
                result = execute_sql_safely(conn, item['sql'])
                item['result'] = result
                status = "+" if "ERROR" not in result else "x"
                print(f"    [{status}] {item['q'][:60]}")
            
        except Exception as e:
            print(f"  [!] Database error during execution: {e}")
            print("  [!] Aborting. Fix your database and try again.")
            conn.close()
            return
    else:
        print("\n[4/5] Skipping database execution (--skip-db)")
        for item in all_items:
            item['result'] = "(DB execution skipped)"
    
    # 5. Generate screenshots (only for practice queries, not setup)
    print("\n[5/5] Generating screenshots and documents...")
    output_dir = output_dir or os.path.dirname(pdf_path)
    img_dir = os.path.join(output_dir, "assignment_images")
    os.makedirs(img_dir, exist_ok=True)
    
    image_paths = []
    ex_num = parsed['exercise_number']
    for i, item in enumerate(query_items):
        img_filename = os.path.join(img_dir, f"ex{ex_num}_q{i}.png")
        create_terminal_screenshot(
            item['sql'],
            item.get('result', ''),
            img_filename
        )
        image_paths.append(img_filename)
    
    print(f"  Generated {len(image_paths)} screenshots (practice queries only)")
    
    # Output filenames: ex6_24BCE5561.docx
    regno = USER_CONFIG['regno']
    base_name = f"ex{ex_num}_{regno}"
    docx_path = os.path.join(output_dir, f"{base_name}.docx")
    pdf_path_out = os.path.join(output_dir, f"{base_name}.pdf")
    
    generate_docx(
        user_config=USER_CONFIG,
        exercise_info=parsed,
        setup_items=setup_items,
        query_items=query_items,
        image_paths=image_paths,
        output_path=docx_path,
        font_name=font_name
    )
    
    # Convert to PDF
    convert_to_pdf(docx_path, pdf_path_out)
    
    # Cleanup
    if conn:
        conn.close()
    
    print(f"\n{'='*60}")
    print(f"  [+] Done! Files saved to: {output_dir}")
    print(f"    Word: {os.path.basename(docx_path)}")
    print(f"    PDF:  {os.path.basename(pdf_path_out)}")
    print(f"{'='*60}\n")


# ==========================================
#    LEGACY: MANUAL ASSIGNMENT MODE
# ==========================================

# Kept for backward compatibility — use when you have handwritten queries
ASSIGNMENTS = [
    {
        "q": "1. Retrieve details of all employees in Department 10.",
        "sql": "SELECT * FROM EMP WHERE DEPTNO = 10"
    },
]

SETUP_QUERIES = [
    {
        "q": "Setup: Create EMP Table",
        "sql": """CREATE TABLE EMP (
    EMPNO NUMBER(4) NOT NULL,
    ENAME VARCHAR2(10),
    JOB VARCHAR2(9),
    MGR NUMBER(4),
    HIREDATE DATE,
    SAL NUMBER(7, 2),
    COMM NUMBER(7, 2),
    DEPTNO NUMBER(2)
)"""
    },
]


def generate_assignment_markdown(output_filename="DBMS_Assignment.md"):
    """Legacy markdown mode — kept for backward compatibility."""
    print("--- Starting Assignment Auto-Solver (Markdown Mode) ---")
    
    try:
        conn = get_db_connection()
    except Exception:
        print("Fatal Error: Could not connect to database.")
        return

    img_dir = "assignment_images"
    os.makedirs(img_dir, exist_ok=True)

    md_content = f"""
# Database Management Systems - BCSE302P
**Name:** {USER_CONFIG["name"]}
**Reg. No. :** {USER_CONFIG['regno']}
**Slot :** {USER_CONFIG['slot']}
**Faculty :** {USER_CONFIG['faculty']}

***Lab {USER_CONFIG["labNo"]} - {USER_CONFIG['labTitle']}***

---
"""
    
    all_tasks = SETUP_QUERIES + ASSIGNMENTS
    
    for i, item in enumerate(all_tasks):
        result_str = execute_sql_safely(conn, item['sql'])
        img_filename = os.path.join(img_dir, f"q{i}.png")
        create_terminal_screenshot(item['sql'], result_str, img_filename)
        img_web_path = img_filename.replace("\\", "/")
        q_text = item.get('q', f'Task {i+1}')
        
        block = f"""
<div style="page-break-inside: avoid; margin-bottom: 30px; padding-bottom: 10px;">
    <h6>{q_text}</h6>
    <img src="{img_web_path}" alt="Output for {q_text}" style="border: 1px solid #333; max-width: 100%;">
</div>
"""
        md_content += block

    with open(output_filename, "w", encoding="utf-8") as f:
        f.write(md_content)

    conn.close()
    print(f"\nSuccess! Generated '{output_filename}'")


# ==========================================
#              CLI ENTRY POINT
# ==========================================
def main():
    parser = argparse.ArgumentParser(
        description="TADA - The Automatic DBMS Assignment Solver",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Process a specific exercise
  python automatic_ass.py --exercise 4
  
  # Process all exercises
  python automatic_ass.py --exercise all
  
  # Process without database (just generate docs)
  python automatic_ass.py --exercise 4 --skip-db
  
  # Use custom input directory
  python automatic_ass.py --exercise 4 --input-dir "C:\\path\\to\\pdfs"
  
  # Legacy mode (manual queries in markdown)
  python automatic_ass.py --legacy
        """
    )
    
    parser.add_argument(
        '--exercise', '-e',
        type=str,
        help='Exercise number to process (e.g., "4") or "all" for all exercises'
    )
    parser.add_argument(
        '--input-dir', '-i',
        type=str,
        default=DEFAULT_INPUT_DIR,
        help=f'Directory containing exercise PDFs (default: {DEFAULT_INPUT_DIR})'
    )
    parser.add_argument(
        '--output-dir', '-o',
        type=str,
        default=None,
        help='Output directory (default: same as input)'
    )
    parser.add_argument(
        '--skip-db',
        action='store_true',
        help='Skip database execution (generate docs with placeholder results)'
    )
    parser.add_argument(
        '--db-type',
        type=str,
        choices=['oracle', 'mysql'],
        default='oracle',
        help='Target database type (default: oracle)'
    )
    parser.add_argument(
        '--legacy',
        action='store_true',
        help='Use legacy markdown mode with manual queries'
    )
    parser.add_argument(
        '--no-config',
        action='store_true',
        help='Skip interactive user config prompt (use defaults)'
    )
    parser.add_argument(
        '--font',
        type=str,
        default='Calibri',
        help='Font name for Word document (default: Calibri)'
    )
    
    args = parser.parse_args()
    
    # Legacy mode
    if args.legacy:
        if not args.no_config:
            set_user_config()
        generate_assignment_markdown()
        return
    
    # Interactive config
    if not args.no_config:
        set_user_config()
    
    # If no exercise specified, show help
    if not args.exercise:
        parser.print_help()
        print("\n[!] Please specify an exercise number with --exercise")
        return
    
    # Find exercise PDFs
    all_pdfs = find_exercise_pdfs(args.input_dir)
    
    if not all_pdfs:
        print(f"[!] No exercise PDFs found in: {args.input_dir}")
        return
    
    if args.exercise.lower() == 'all':
        pdfs_to_process = all_pdfs
    else:
        # Find the specific exercise
        target_num = args.exercise
        pdfs_to_process = [
            p for p in all_pdfs
            if re.search(rf'Ex\s*{target_num}[\.\s\-]', os.path.basename(p), re.IGNORECASE)
        ]
        
        if not pdfs_to_process:
            print(f"[!] Exercise {target_num} not found. Available exercises:")
            for p in all_pdfs:
                print(f"    {os.path.basename(p)}")
            return
    
    # Process each exercise
    output_dir = args.output_dir or args.input_dir
    
    for pdf_path in pdfs_to_process:
        try:
            process_exercise(
                pdf_path=pdf_path,
                output_dir=output_dir,
                db_type=args.db_type,
                skip_db=args.skip_db,
                font_name=args.font
            )
        except Exception as e:
            print(f"\n[!] Error processing {os.path.basename(pdf_path)}: {e}")
            import traceback
            traceback.print_exc()
            continue
    
    print("\n[+] All done!")


if __name__ == "__main__":
    main()