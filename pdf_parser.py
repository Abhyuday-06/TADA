"""
PDF Parser Module for DBMS Lab Exercises
Extracts the full text from exercise PDFs and identifies the practice section
(tables + questions) for AI processing.
"""

import pdfplumber
import os
import re
import glob


def extract_full_text(pdf_path: str) -> str:
    """
    Extract all text from a PDF file, page by page.
    """
    full_text = ""
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if text:
                full_text += text + "\n\n"
    return full_text.strip()


def extract_practice_section(full_text: str) -> str:
    """
    Extract only the PRACTICE section from the full PDF text.
    This includes practice tables and practice questions.
    The practice section typically starts with:
    - "PRACTICE DATABASE" or "PRACTICE QUESTIONS" or "EXERCISE:" 
    """
    # Common markers for the start of the practice portion
    practice_markers = [
        r'(?:\d+\.\s*)?PRACTICE\s+DATABASE',
        r'(?:\d+\.\s*)?PRACTICE\s+QUESTIONS',
        r'EXERCISE\s*:',          # e.g., "EXERCISE: SQL OPERATORS (PRACTICE QUESTIONS)"
    ]
    
    # Try each marker to find where the practice section starts
    earliest_pos = len(full_text)
    for marker in practice_markers:
        match = re.search(marker, full_text, re.IGNORECASE)
        if match and match.start() < earliest_pos:
            earliest_pos = match.start()
    
    if earliest_pos == len(full_text):
        # If no practice section is found, return the full text
        # (best-effort for unusual PDF formats)
        return full_text
    
    practice_text = full_text[earliest_pos:]
    
    # Clean up: remove repeated headers like "SCHOOL OF COMPUTER SCIENCE..."
    header_pattern = r'SCHOOL OF COMPUTER SCIENCE AND ENGINEERING\s*\n.*?BCSE302P.*?\n.*?Semester.*?Faculty.*?\n'
    practice_text = re.sub(header_pattern, '', practice_text)
    
    return practice_text.strip()


def parse_exercise_metadata(pdf_path: str, full_text: str) -> dict:
    """
    Extract exercise number and title from the filename and/or text.
    """
    filename = os.path.basename(pdf_path)
    
    # Try to extract from filename: "Ex 4. SQL Operators.pdf" or "Ex4. SQL Operators.pdf"
    match = re.match(r'Ex\s*(\d+)[\.\s\-]+(.+?)\.pdf', filename, re.IGNORECASE)
    if match:
        return {
            "exercise_number": match.group(1),
            "exercise_title": match.group(2).strip()
        }
    
    # Fallback: try to extract from text
    match = re.search(r'EXERCISE\s+(\d+)\s*\n\s*Title\s*:\s*(.+)', full_text, re.IGNORECASE)
    if match:
        return {
            "exercise_number": match.group(1),
            "exercise_title": match.group(2).strip()
        }
    
    return {
        "exercise_number": "0",
        "exercise_title": filename.replace('.pdf', '')
    }


def parse_exercise_pdf(pdf_path: str) -> dict:
    """
    Main entry point. Parses an exercise PDF and returns structured data.
    
    Returns:
        {
            "exercise_number": str,
            "exercise_title": str,
            "full_text": str,           # Complete PDF text
            "practice_section": str,    # Just the practice portion (tables + questions)
            "pdf_path": str             # Original file path
        }
    """
    full_text = extract_full_text(pdf_path)
    practice_section = extract_practice_section(full_text)
    metadata = parse_exercise_metadata(pdf_path, full_text)
    
    return {
        **metadata,
        "full_text": full_text,
        "practice_section": practice_section,
        "pdf_path": pdf_path
    }


def find_exercise_pdfs(directory: str) -> list:
    """
    Find all exercise PDFs in a directory.
    Matches files like "Ex 4. SQL Operators.pdf", "Ex4. SQL Operators.pdf", etc.
    Excludes student output files like "24BCE5561_ex4.pdf".
    """
    pdfs = []
    for file in os.listdir(directory):
        if file.lower().endswith('.pdf') and file.lower().startswith('ex'):
            pdfs.append(os.path.join(directory, file))
    
    # Sort by exercise number
    def extract_num(path):
        fname = os.path.basename(path)
        match = re.search(r'(\d+)', fname)
        return int(match.group(1)) if match else 0
    
    pdfs.sort(key=extract_num)
    return pdfs


# ==========================================
#              TEST / DEMO
# ==========================================
if __name__ == "__main__":
    import json
    
    test_dir = r"E:\VIT\Sem 4\DBMS\Lab-Exercises"
    
    print("=== Finding Exercise PDFs ===")
    pdfs = find_exercise_pdfs(test_dir)
    for p in pdfs:
        print(f"  Found: {os.path.basename(p)}")
    
    if pdfs:
        print(f"\n=== Parsing: {os.path.basename(pdfs[0])} ===")
        result = parse_exercise_pdf(pdfs[0])
        print(f"Exercise #{result['exercise_number']}: {result['exercise_title']}")
        print(f"\n--- Practice Section (first 500 chars) ---")
        print(result['practice_section'][:500])
