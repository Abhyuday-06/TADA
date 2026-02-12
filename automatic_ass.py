import oracledb
import pandas as pd
from PIL import Image, ImageDraw, ImageFont
from fpdf import FPDF
import os
import glob
import sys
import platform

# ==========================================
#              CONFIGURATION
# ==========================================
DB_CONFIG = {
    "user": "system",          # Usually 'system' or 'sys'
    "password": "Metsu#$1234", # <--- CHANGE THIS
    "service_name": "xe",      # Usually 'xe' for Express Edition or 'orcl'
    "host": "localhost",
    "port": 1521
}

# List your queries here. 
# (Later, you can replace this list with the output from your AI agent)
ASSIGNMENTS = [
    {
        "q": "1. Retrieve details of all employees in Department 10.",
        "sql": "SELECT * FROM EMP WHERE DEPTNO = 10"
    },
    {
        "q": "2. List the name and salary of employees who are CLERKS.",
        "sql": "SELECT ENAME, SAL FROM EMP WHERE JOB = 'CLERK'"
    },
    {
        "q": "3. Find the department with the highest average salary.",
        "sql": "SELECT DEPTNO, AVG(SAL) FROM EMP GROUP BY DEPTNO ORDER BY AVG(SAL) DESC FETCH FIRST 1 ROWS ONLY"
    }
]

# Create tables or insert data here (will run before assignments)
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
    {
        "q": "Setup: Insert sample data",
        "sql": "INSERT INTO EMP VALUES (7369, 'SMITH', 'CLERK', 7902, TO_DATE('17-DEC-1980', 'DD-MON-YYYY'), 800, NULL, 20)"
    }
]

# ==========================================
#        PART 1: SMART CONNECTION
# ==========================================
def find_oracle_home():
    """
    Searches common Windows paths for the Oracle Client libraries (oci.dll).
    Used only if the standard network connection fails.
    """
    print("   > Searching for Oracle Home directory...")
    
    # Common paths for Oracle XE and Enterprise on Windows
    search_patterns = [
        r"C:\app\*\product\*\dbhomeXE\bin",
        r"C:\oraclexe\app\oracle\product\*\server\bin",
        r"C:\app\*\product\*\client_*\bin",
        r"C:\app\*\product\*\dbhome_*\bin"
    ]
    
    for pattern in search_patterns:
        matches = glob.glob(pattern)
        if matches:
            # Return the first valid bin directory found
            return matches[0]
            
    return None

def get_db_connection():
    """
    Tries to connect via Network (Thin mode). 
    If that fails due to Listener errors, switches to Direct (Thick mode).
    """
    user = DB_CONFIG["user"]
    pwd = DB_CONFIG["password"]
    dsn_str = f"{DB_CONFIG['host']}:{DB_CONFIG['port']}/{DB_CONFIG['service_name']}"

    # Attempt 1: Standard Network Connection (Thin Mode)
    try:
        print(f"[*] Attempting network connection to {dsn_str}...")
        conn = oracledb.connect(user=user, password=pwd, dsn=dsn_str)
        print("    [+] Success! Connected via Network.")
        return conn
    except oracledb.Error as e:
        error_msg = str(e)
        # Check for specific "Listener Refused" or "Connection Failed" errors
        if "DP-1010" in error_msg or "10061" in error_msg or "12541" in error_msg:
            print(f"    [-] Network failed (Listener issue). Attempting Direct Connection...")
        else:
            # If it's a password error (ORA-01017), don't try the other method.
            print(f"    [!] Connection failed: {error_msg}")
            raise e

    # Attempt 2: Direct "Thick" Connection (Bypasses Listener)
    oracle_bin = find_oracle_home()
    if not oracle_bin:
        raise Exception("Could not find Oracle installation directory automatically. Please fix Listener or add path manually.")

    print(f"    [+] Found Oracle Binaries at: {oracle_bin}")
    
    try:
        # Initialize the C libraries
        oracledb.init_oracle_client(lib_dir=oracle_bin)
        
        # Connect using the local driver (Bequeath connection)
        # Note: We do NOT pass 'dsn' here, relying on local OS auth or SID
        os.environ["ORACLE_SID"] = DB_CONFIG["service_name"]
        
        conn = oracledb.connect(user=user, password=pwd)
        print("    [+] Success! Connected via Direct Driver (Thick Mode).")
        return conn
    except Exception as e:
        print(f"    [!] Direct connection also failed: {e}")
        raise e

# ==========================================
#        PART 2: FAKE SCREENSHOT GEN
# ==========================================
def create_terminal_screenshot(query, result_text, filename):
    """
    Renders text onto a black image using a monospace font.
    """
    # 1. Setup Canvas
    bg_color = (12, 12, 12)  # VS Code Terminal Black
    text_color = (204, 204, 204) # Light Gray
    cmd_color = (255, 255, 255) # White for the command
    prompt_color = (0, 255, 0) # Green for "SQL>" prompt
    
    font_size = 15
    padding = 30
    
    # 2. Load Font (Try Consolas for Windows, else default)
    try:
        if platform.system() == "Windows":
            font = ImageFont.truetype("consola.ttf", font_size)
        elif platform.system() == "Darwin": # Mac
            font = ImageFont.truetype("Menlo.ttc", font_size) 
        else:
            font = ImageFont.truetype("DejaVuSansMono.ttf", font_size)
    except:
        # Fallback if system fonts aren't found
        font = ImageFont.load_default()

    # 3. Construct Text
    # We pretend we are in SQL Plus or VS Code
    header = f"SQL> {query};\n"
    body = f"\n{result_text}\n"
    footer = "\nSQL> _"
    
    full_text = header + body + footer

    # 4. Measure Text to size the image
    dummy_img = Image.new('RGB', (1, 1))
    draw = ImageDraw.Draw(dummy_img)
    
    bbox = draw.textbbox((0, 0), full_text, font=font)
    text_width = bbox[2]
    text_height = bbox[3]
    
    width = text_width + (padding * 2)
    height = text_height + (padding * 2)

    # 5. Draw the actual image
    img = Image.new('RGB', (width, height), color=bg_color)
    d = ImageDraw.Draw(img)
    
    # Draw logic is slightly complex to handle colors, 
    # but for simplicity, we just draw standard text:
    d.text((padding, padding), full_text, font=font, fill=text_color)
    
    img.save(filename)
    return filename

# ==========================================
#        PART 3: MAIN EXECUTION
# ==========================================
def execute_sql_safely(conn, sql):
    """
    Handles both SELECT (returning a DataFrame string)
    and DDL/DML (returning a status message).
    """
    clean_sql = sql.strip().upper()
    try:
        # 1. SELECT queries -> Use Pandas for pretty table
        if clean_sql.startswith("SELECT") or clean_sql.startswith("WITH"):
            df = pd.read_sql(sql, conn)
            if df.empty:
                return "no rows selected"
            return df.to_string(index=False)
        
        # 2. DDL / DML -> Use Cursor
        else:
            with conn.cursor() as cursor:
                cursor.execute(sql)
                # Mimic SQL*Plus feedback
                if clean_sql.startswith("CREATE"): return "Table created."
                if clean_sql.startswith("DROP"): return "Table dropped."
                if clean_sql.startswith("ALTER"): return "Table altered."
                if clean_sql.startswith("INSERT"): return "1 row created."
                if clean_sql.startswith("UPDATE"): return f"{cursor.rowcount} rows updated."
                if clean_sql.startswith("DELETE"): return f"{cursor.rowcount} rows deleted."
                return "Command executed successfully."
                
    except Exception as e:
        return f"ERROR at line 1:\n{e}"

def generate_assignment_pdf(output_filename="DBMS_Assignment.pdf"):
    print("--- Starting Assignment Auto-Solver ---")
    
    # 1. Connect to DB
    try:
        conn = get_db_connection()
    except Exception as e:
        print("Fatal Error: Could not connect to database.")
        return

    # 2. Setup PDF
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page() # Start with one page
    
    # Combine lists: Setup first, then Assignments
    # We label them to help the user identify in logs
    all_tasks = SETUP_QUERIES + ASSIGNMENTS 
    
    # 3. Process Queries
    print(f"\nProcessing {len(all_tasks)} queries (Setup + Assignments)...")
    
    for i, item in enumerate(all_tasks):
        print(f"  > Processing Query {i+1}...")
        
        # A. Execute SQL
        result_str = execute_sql_safely(conn, item['sql'])
        
        # B. Create Image
        img_name = f"temp_q{i}.png"
        create_terminal_screenshot(item['sql'], result_str, img_name)
        
        # C. Add to PDF (Continuous Flow)
        
        # Get Image Dimensions to calculate space needed
        with Image.open(img_name) as im:
            px_w, px_h = im.size
            
        # FPDF default DPI is often 72 or user defined units. 
        # When using pdf.image(w=190), we effectively force width to 190mm.
        # We need to calculate the proportional height in mm.
        aspect_ratio = px_h / px_w
        display_w = 190
        display_h = display_w * aspect_ratio
        
        # Estimate vertical space needed (Header + Image + Spacing)
        needed_h = 15 + display_h + 10 # 15 for text, 10 buffer
        
        # Check if we need a page break
        current_y = pdf.get_y()
        page_h = 297 # A4 Height
        margin = 20 # Bottom margin safety
        
        if current_y + needed_h > (page_h - margin):
            pdf.add_page()
            
        # Title (Question)
        pdf.set_font("Arial", 'B', 11)
        # Use simple numbering or prompt text
        q_text = item.get('q', f'Task {i+1}')
        pdf.multi_cell(0, 8, q_text)
        
        # Image (Screenshot)
        # pdf.image automatically puts it at current Y if x/y not specified? 
        # Actually safer to provide exact coords or rely on ln.
        # FPDF 1.7.2 .image() places at current position if x=None/y=None, 
        # but usage in original code was specific. 
        # We will use flow logic.
        
        pdf.image(img_name, x=10, w=display_w)
        
        # Move cursor down manually because image() might not update flow cursor fully
        # depending on FPDF version/settings.
        pdf.ln(display_h + 5) 
        
        # Cleanup temp file
        if os.path.exists(img_name):
            try:
                os.remove(img_name)
            except: 
                pass

    # 4. Finish
    conn.close()
    pdf.output(output_filename)
    print(f"\nSuccess! PDF generated: {output_filename}")

if __name__ == "__main__":
    generate_assignment_pdf()