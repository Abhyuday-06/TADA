"""
AI Solver Module for DBMS Lab Exercises
Uses Google Gemini to generate SQL queries for practice questions.
Supports multiple models and API keys for fallback on rate limits.
"""

import os
import re
import json
import time
import google.generativeai as genai
from dotenv import load_dotenv

load_dotenv()

# ==========================================
#              CONFIGURATION
# ==========================================

# Models to try in order (free tier rate limits are per-model)
FALLBACK_MODELS = [
    "gemini-2.0-flash",
    "gemini-2.0-flash-lite",
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
    "gemini-2.5-pro",
    "gemini-3-flash-preview",
    "gemini-2.5-flash-preview-09-2025",
    "gemini-2.5-flash-lite-preview-09-2025",
]

def _get_api_keys() -> list[str]:
    """
    Collect all API keys from env.
    Supports GEMINI_API_KEY, GEMINI_API_KEY_2, GEMINI_API_KEY_3, etc.
    """
    keys = []
    primary = os.getenv("GEMINI_API_KEY")
    if primary:
        keys.append(primary)
    
    # Check for additional numbered keys
    for i in range(2, 10):
        key = os.getenv(f"GEMINI_API_KEY_{i}")
        if key:
            keys.append(key)
    
    if not keys:
        raise ValueError(
            "GEMINI_API_KEY not found. Set it in .env file or pass it directly.\n"
            "Get a free key at: https://aistudio.google.com/app/apikey"
        )
    return keys


def configure_gemini(api_key: str = None):
    """Configure the Gemini API with the given key."""
    key = api_key or _get_api_keys()[0]
    genai.configure(api_key=key)


# ==========================================
#          QUERY GENERATION
# ==========================================

def generate_setup_sql(practice_section: str, table_prefix: str = "", db_type: str = "oracle") -> list[dict]:
    """
    Use Gemini to generate CREATE TABLE + INSERT statements from the practice section.
    
    Args:
        practice_section: The text containing table definitions and data
        table_prefix: Prefix for table names (e.g., "bce5561_")
        db_type: Target database type ("oracle" or "mysql")
    
    Returns:
        List of {"q": description, "sql": sql_statement}
    """
    configure_gemini()
    
    db_notes = ""
    if db_type == "oracle":
        db_notes = """
- Use Oracle SQL syntax (VARCHAR2 instead of VARCHAR, NUMBER instead of INT, etc.)
- Use TO_DATE('YYYY-MM-DD', 'YYYY-MM-DD') for date values
- Use sequences or direct values for auto-increment simulation
- Do NOT use CREATE DATABASE or USE statements
- Use NUMBER for integer types, VARCHAR2 for strings
- For CHECK constraints, use Oracle syntax
"""
    else:
        db_notes = """
- Use standard MySQL syntax
- Use INT, VARCHAR, DATE, DECIMAL as appropriate
- Use AUTO_INCREMENT if needed
"""
    
    prompt = f"""You are a SQL expert. Given the following text extracted from a DBMS lab exercise PDF, 
generate the CREATE TABLE and INSERT statements needed to set up the practice database.

CRITICAL RULES:
1. Return ONLY valid JSON - no markdown, no code fences, no explanation
2. Table names MUST be prefixed with "{table_prefix}" (e.g., "{table_prefix}employee")
3. Column names MUST exactly match what is shown in the PDF tables - do NOT invent or rename columns
4. For each table generate exactly 2 entries:
   a) One CREATE TABLE statement
   b) One PL/SQL BEGIN...END block containing ALL INSERT statements for that table
5. Group ALL inserts for a table into a single BEGIN...END; block
6. Maintain referential integrity (create parent tables before child tables)
7. ALL SQL must be completely lowercase (keywords, table names, column names, everything)
8. Do NOT include any comments (-- or /* */) in the SQL
9. Do NOT use any emojis or special unicode characters
10. DOUBLE CHECK every column name against the table definition before generating queries
{db_notes}

TEXT FROM PDF:
{practice_section}

Return a JSON array with this exact format:
[
    {{"q": "Create {table_prefix}employee table", "sql": "create table {table_prefix}employee (emp_id number, emp_name varchar2(30))"}},
    {{"q": "Insert data into {table_prefix}employee", "sql": "begin\\ninsert into {table_prefix}employee values (1, 'Anand');\\ninsert into {table_prefix}employee values (2, 'Bhavya');\\ncommit;\\nend;"}},
    ...
]

IMPORTANT: Return ONLY the JSON array, nothing else. No markdown fencing.
"""
    
    response = _call_with_retry(prompt)
    return _parse_json_response(response.text)


def generate_practice_queries(practice_section: str, table_prefix: str, db_type: str = "oracle", setup_sql_items: list = None) -> list[dict]:
    """
    Use Gemini to generate SQL queries for all practice questions.
    
    Args:
        practice_section: The text containing tables and practice questions
        table_prefix: Prefix for table names
        db_type: Target database type
        setup_sql_items: Optional list of setup items (CREATE/INSERT) to provide schema context
    """
    configure_gemini()
    
    db_notes = ""
    if db_type == "oracle":
        db_notes = """
- Use Oracle SQL syntax
- Use FETCH FIRST N ROWS ONLY instead of LIMIT
- Use NVL() instead of IFNULL()
- Use || for string concatenation
- Use SUBSTR instead of SUBSTRING
- Use ROWNUM or FETCH FIRST for limiting results
- Use MOD() instead of %
"""
    else:
        db_notes = "- Use standard MySQL syntax\n"
    
    # improved schema context
    schema_context = ""
    if setup_sql_items:
        create_stmts = [item['sql'] for item in setup_sql_items if item['sql'].strip().lower().startswith('create')]
        schema_context = "\nDATABASE SCHEMA (The following tables exist - use EXACTLY these column names):\n" + "\n".join(create_stmts) + "\n"

    prompt = f"""You are a SQL expert. Given the following text from a DBMS lab exercise PDF containing 
table definitions and practice questions, generate the SQL query for EACH practice question.

CRITICAL RULES:
1. Return ONLY valid JSON - no markdown, no code fences, no explanation
2. Use table names prefixed with "{table_prefix}" (e.g., "{table_prefix}employee")
3. Column names MUST exactly match the column names in the table definitions or schema context - do NOT guess
4. DOUBLE CHECK every column name in your queries against the provided schema
5. Answer EVERY numbered question in the practice section
6. Keep the original question text exactly as-is
7. Write clean, correct, executable SQL for each question
8. ALL SQL must be completely lowercase (keywords, table names, column names, everything)
9. Do NOT include any comments (-- or /* */) in the SQL
10. Do NOT use any emojis or special unicode characters anywhere
11. If the schema context is provided, prioritize it over the PDF text for column names
{db_notes}

{schema_context}

TEXT FROM PDF:
{practice_section}

Return a JSON array of objects:
[
    {{"q": "1. [original question text]", "sql": "select ..."}},
    {{"q": "2. [original question text]", "sql": "select ..."}},
    ...
]

If there are section letters (A, B, C...), use them as prefix: "A1.", "B3.", "C10."
If there are no section letters, just use question numbers: "1.", "2.", "3."
Return ONLY the JSON array. No markdown. No explanation.
"""
    
    response = _call_with_retry(prompt)
    return _parse_json_response(response.text)


def generate_all(practice_section: str, table_prefix: str = "", db_type: str = "oracle") -> dict:
    """
    Generate both setup SQL and practice queries.
    
    Returns:
        {
            "setup": [...],     # CREATE TABLE + INSERT statements
            "queries": [...]    # Practice question SQL
        }
    """
    print("  [AI] Generating CREATE TABLE + INSERT statements...")
    setup = generate_setup_sql(practice_section, table_prefix, db_type)
    print(f"  [AI] Generated {len(setup)} setup statements")
    
    # Small delay to avoid rate limiting
    time.sleep(1)
    
    print("  [AI] Generating practice query solutions...")
    queries = generate_practice_queries(practice_section, table_prefix, db_type, setup_sql_items=setup)
    print(f"  [AI] Generated {len(queries)} practice queries")
    
    return {
        "setup": setup,
        "queries": queries
    }


# ==========================================
#          HELPER FUNCTIONS
# ==========================================

def _call_with_retry(prompt, max_retries_per_model=2):
    """
    Call Gemini with model and API key fallback on rate limit errors.
    Cycles through all models for each key before moving to the next key.
    """
    api_keys = _get_api_keys()
    last_error = None
    
    for key_idx, api_key in enumerate(api_keys):
        genai.configure(api_key=api_key)
        key_label = f"key {key_idx + 1}/{len(api_keys)}"
        
        for model_name in FALLBACK_MODELS:
            model = genai.GenerativeModel(model_name)
            
            for attempt in range(max_retries_per_model):
                try:
                    response = model.generate_content(prompt)
                    if attempt > 0 or model_name != FALLBACK_MODELS[0] or key_idx > 0:
                        print(f"  [AI] Success with {model_name} ({key_label})")
                    return response
                except Exception as e:
                    last_error = e
                    error_str = str(e)
                    is_rate_limit = (
                        "429" in error_str or
                        "quota" in error_str.lower() or
                        "rate" in error_str.lower() or
                        "ResourceExhausted" in error_str
                    )
                    
                    if is_rate_limit:
                        if attempt < max_retries_per_model - 1:
                            wait = 5 * (attempt + 1)
                            print(f"  [AI] {model_name} ({key_label}) rate limited, retrying in {wait}s...")
                            time.sleep(wait)
                        else:
                            print(f"  [AI] {model_name} ({key_label}) exhausted, trying next model...")
                    else:
                        # Non-rate-limit error: skip this model entirely
                        print(f"  [AI] {model_name} error: {error_str[:100]}. Trying next model...")
                        break
    
    raise Exception(
        f"All models and API keys exhausted. Last error: {last_error}\n"
        f"Add more API keys in .env (GEMINI_API_KEY_2, GEMINI_API_KEY_3, etc.)\n"
        f"Get free keys at: https://aistudio.google.com/app/apikey"
    )

def _parse_json_response(text: str) -> list[dict]:
    """
    Parse JSON from Gemini's response, handling markdown fencing and other artifacts.
    """
    # Strip markdown code fences if present
    text = text.strip()
    if text.startswith("```"):
        # Remove opening fence (```json or ```)
        text = re.sub(r'^```\w*\n?', '', text)
        # Remove closing fence
        text = re.sub(r'\n?```$', '', text)
    
    text = text.strip()
    
    try:
        result = json.loads(text)
        if isinstance(result, list):
            return result
        else:
            return [result]
    except json.JSONDecodeError as e:
        # Try to find JSON array in the text
        match = re.search(r'\[.*\]', text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass
        
        print(f"  [!] Failed to parse AI response as JSON: {e}")
        print(f"  [!] Raw response (first 500 chars): {text[:500]}")
        return []


# ==========================================
#              TEST / DEMO
# ==========================================
if __name__ == "__main__":
    # Quick test with a sample
    test_text = """
TABLE 1: EMPLOYEE
emp_id emp_name dept salary age
1 Anand IT 45000 28
2 Bhavya HR 38000 32

PRACTICE QUESTIONS
A. ARITHMETIC OPERATORS
1. Display employee salary after adding a bonus of 5000.
2. Show employee salary after deducting 2000 as tax.
"""
    
    print("=== Testing AI Solver ===")
    try:
        result = generate_all(test_text, table_prefix="test_", db_type="oracle")
        print(f"\nSetup statements: {len(result['setup'])}")
        for item in result['setup']:
            print(f"  {item['q']}: {item['sql'][:80]}...")
        print(f"\nPractice queries: {len(result['queries'])}")
        for item in result['queries']:
            print(f"  {item['q']}: {item['sql'][:80]}...")
    except Exception as e:
        print(f"Error: {e}")
