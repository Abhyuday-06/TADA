# TADA - Automated DBMS Lab Exercise Solver

TADA is a Python-based automation tool designed to solve DBMS lab exercises. It parses exercise PDFs, generates SQL queries using AI, executes them against an Oracle database, and produces formatted Word and PDF reports.

## Features

- **PDF Parsing**: Extracts tables and questions from lab exercise PDFs.
- **AI-Powered SQL Generation**: Uses Google Gemini to generate CREATE TABLE, INSERT, and SELECT statements.
- **Database Integration**: Connects to Oracle Database to execute generated SQL and capture results.
- **Report Generation**: Creates professional Word (.docx) and PDF reports with:
    - Student details
    - Setup SQL queries
    - Practice queries with captured terminal-style screenshots
- **Robust Error Handling**: Includes retry logic for API rate limits and database connection fallback (Thin/Thick modes).

## Prerequisites

- Python 3.10+
- Oracle Database (Express Edition recommended)
- Google Gemini API Key

## Installation

1. Clone the repository:
   ```bash
   git clone <repository-url>
   ```

2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

3. Configure Environment:
   - Copy `.env.example` to `.env`.
   - Add your Gemini API key to the `.env` file.
   - Configure database credentials if different from defaults.

## Usage

Run the main script from the command line:

```bash
# Process a specific exercise (e.g., Exercise 9)
python automatic_ass.py --exercise 9

# Process all exercises in the input directory
python automatic_ass.py --exercise all

# Run without database execution (generates docs with placeholder results)
python automatic_ass.py --exercise 9 --skip-db

# Specify a custom font for the output document
python automatic_ass.py --exercise 9 --font "Times New Roman"
```

## Configuration

The tool asks for student details (Name, Registration Number) on the first run. These can also be configured in the script or passed via arguments in future updates.

## Project Structure

- `automatic_ass.py`: Main entry point and orchestration logic.
- `pdf_parser.py`: module for extracting text and structure from PDFs.
- `ai_solver.py`: Interaction with Google Gemini API for SQL generation.
- `export.py`: Handles generation of Word and PDF documents.
- `requirements.txt`: List of Python dependencies.

## License

This project is for educational purposes.
