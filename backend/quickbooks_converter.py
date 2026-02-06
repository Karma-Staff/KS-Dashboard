"""
QuickBooks P&L Report Converter (AI-Powered)

Uses Gemini AI to intelligently parse QuickBooks Profit & Loss reports 
(PDF, Excel, CSV) and convert to the dashboard's flat format.
Includes preview/confirmation flow for user verification.
"""

import io
import os
import re
import json
import json5  # Lenient JSON parser for AI responses
import pandas as pd
from typing import Dict, List, Optional, Any
from datetime import datetime

# Try to import optional dependencies
try:
    import fitz  # PyMuPDF
    PYMUPDF_AVAILABLE = True
except ImportError:
    PYMUPDF_AVAILABLE = False

try:
    from google import genai
    from google.genai import types
    GEMINI_AVAILABLE = True
except ImportError:
    GEMINI_AVAILABLE = False


# Month abbreviations for validation
MONTH_NAMES = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 
               'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

# Valid categories
VALID_CATEGORIES = ['Income', 'Cost of Goods Sold', 'Expenses']

# Debug output folder (relative to this file's directory)
DEBUG_OUTPUT_DIR = os.path.join(os.path.dirname(__file__), 'training_data', 'outputs')


def save_debug_output(filename: str, ai_result: Dict[str, Any], 
                      validated_data: List[Dict] = None) -> str:
    """
    Save AI extraction results for debugging and training purposes.
    Returns the path to the saved CSV file.
    """
    os.makedirs(DEBUG_OUTPUT_DIR, exist_ok=True)
    
    # Create a safe filename from the original
    base_name = os.path.splitext(os.path.basename(filename))[0]
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    output_prefix = f"{base_name}_{timestamp}"
    
    # Save the raw AI JSON response
    json_path = os.path.join(DEBUG_OUTPUT_DIR, f"{output_prefix}_raw.json")
    with open(json_path, 'w', encoding='utf-8') as f:
        # Remove internal data arrays to keep JSON readable
        ai_copy = {k: v for k, v in ai_result.items() if k != 'data'}
        ai_copy['data_row_count'] = len(ai_result.get('data', []))
        json.dump(ai_copy, f, indent=2, ensure_ascii=False)
    
    # Save the extracted data as CSV
    csv_path = os.path.join(DEBUG_OUTPUT_DIR, f"{output_prefix}_extracted.csv")
    if validated_data:
        df = pd.DataFrame(validated_data)
    elif ai_result.get('data'):
        df = pd.DataFrame(ai_result['data'])
    else:
        df = pd.DataFrame()
    
    if len(df) > 0:
        df.to_csv(csv_path, index=False)
    
    print(f"[DEBUG] Saved extraction output to: {csv_path}")
    return csv_path


def detect_file_type(filename: str, content: bytes) -> str:
    """Detect the file type from filename and content."""
    filename_lower = filename.lower()
    if filename_lower.endswith('.pdf'):
        return 'pdf'
    elif filename_lower.endswith('.xlsx') or filename_lower.endswith('.xls'):
        return 'excel'
    elif filename_lower.endswith('.csv'):
        return 'csv'
    else:
        if content[:4] == b'%PDF':
            return 'pdf'
        elif content[:2] == b'PK':
            return 'excel'
        return 'csv'


def extract_text_from_file(content: bytes, filename: str, file_type: str) -> str:
    """Extract text content from any file type for AI processing."""
    
    if file_type == 'pdf':
        if not PYMUPDF_AVAILABLE:
            raise ImportError("PyMuPDF required for PDF. Install: pip install pymupdf")
        
        pdf_doc = fitz.open(stream=content, filetype="pdf")
        full_text = ""
        for page in pdf_doc:
            full_text += page.get_text()
        pdf_doc.close()
        return full_text
    
    elif file_type == 'excel':
        df = pd.read_excel(io.BytesIO(content), header=None)
        return df.to_string(index=False, header=False)
    
    else:  # CSV
        df = pd.read_csv(io.BytesIO(content), header=None)
        return df.to_string(index=False, header=False)


def convert_with_gemini(text_content: str, api_key: str) -> Dict[str, Any]:
    """
    Use Gemini AI to parse financial data and return structured result with preview info.
    Uses CSV format for data to be more token-efficient and prevent truncation.
    """
    
    if not GEMINI_AVAILABLE:
        raise ImportError("google-genai required. Install: pip install google-genai")
    
    # Create client with API key
    client = genai.Client(api_key=api_key)
    
    prompt = f"""You are an expert at parsing QuickBooks and financial reports. Analyze this financial report and extract all data.

TASK: Convert this financial report to a structured format. 

OUTPUT FORMAT - Return a valid JSON object with this exact structure:
{{
    "company_name": "Extracted Company Name",
    "year": 2024,
    "detected_months": ["Jan", "Feb", "Mar", ...],
    "column_mapping": {{
        "Account": "Column 1",
        "Category": "Derived from sections",
        "Months": ["Jan", "Feb", ...]
    }},
    "csv_data": "Account|Category|Jan|Feb|Mar|...\\nMitigation Revenue|Income|1000.00|2000.00|1500.00|..."
}}

CATEGORY RULES:
1. Category MUST be exactly one of: "Income", "Cost of Goods Sold", or "Expenses"
2. "Other Income" section items (like Cash Back Reward, Earned Interest, Late Fee Income) → categorize as "Income"
3. "Other Expenses" section items → categorize as "Expenses"
4. Main "Income" section items → "Income"
5. "Cost of Goods Sold" section items → "Cost of Goods Sold"
6. "Expenses" section items → "Expenses"

RULES FOR csv_data:
1. Use '|' (pipe) as the delimiter.
2. Headers MUST be: Account|Category|LIST_OF_PERIODS_FOUND
3. For monthly reports: Use month columns in chronological order (Jan, Feb, Mar...)
4. For YTD/annual reports (no monthly breakdown): Use a single "Total" column
   - Example header: Account|Category|Total
   - Example row: REV - Water Emergency|Income|656822.37

WHAT TO SKIP (and ONLY these):
- Skip ONLY final category summary rows: "Total Income", "Total Other Income", "Total Cost of Goods Sold", "Total Expenses", "Total Other Expenses"
- Skip calculation rows: "Gross Profit", "Net Operating Income", "Net Other Income", "Net Income"
- Skip percentage rows (% of income) and completely blank rows

WHAT TO KEEP (CRITICAL - preserve these accounts):
- Keep ALL individual account line items with data, even if they have "Total" in the name
- Example: "TOTAL COST OF GOODS SOLD" as an ACCOUNT NAME (not the category total) must be KEPT
- Keep parent account rows that have their own data values
- Keep sub-account totals that are NOT the final category total
- When in doubt, KEEP the row

NESTED STRUCTURE EXAMPLE:
If you see:
  Cost of Goods Sold (header)
    Cost of Goods Sold     22211.85  12784.92  <- KEEP (account with data)
    TOTAL COST OF GOODS SOLD  2350  14971.22  <- KEEP (different account)
      Contractors COGS       320    3550     <- KEEP
      Purchases              4770   11080    <- KEEP
    Total TOTAL COST OF GOODS SOLD  43112    <- SKIP (it's sum of above)
  Total Cost of Goods Sold  65324  74363     <- SKIP (final category total)

10. Remove account codes like "4000 · " from account names.
11. Include ALL months found. Use 0.00 for empty months.
12. One row per account only, with amounts for all months in that same row.

Here is the financial report to parse:

{text_content}

Return ONLY the JSON object.
"""
    
    # Use the new SDK syntax with structured output and increased token limit
    response = client.models.generate_content(
        model="gemini-2.0-flash",
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            max_output_tokens=65536  # Allow large responses for full data extraction
        )
    )
    response_text = response.text.strip()
    
    # Clean up response - remove markdown code blocks if present
    if response_text.startswith('```'):
        # Find the first newline and the last ```
        first_newline = response_text.find('\n')
        if first_newline != -1:
            response_text = response_text[first_newline+1:]
        if response_text.endswith('```'):
            response_text = response_text[:-3].strip()
    
    # Additional cleanup for common JSON issues
    # Remove trailing commas before closing brackets
    response_text = re.sub(r',\s*}', '}', response_text)
    response_text = re.sub(r',\s*]', ']', response_text)
    
    # Parse JSON using json5 for lenient parsing
    try:
        result = json5.loads(response_text)
    except Exception as e:
        # Try to find JSON in the response
        json_match = re.search(r'\{[\s\S]*\}', response_text)
        if json_match:
            try:
                result = json5.loads(json_match.group())
            except Exception:
                # One more attempt - try to extract just the data array
                raise ValueError(f"Failed to parse AI response as JSON: {e}\nResponse preview: {response_text[:500]}...")
        else:
            raise ValueError(f"No JSON found in AI response: {e}")
            
    # Convert csv_data wide format to list of flat dicts
    if 'csv_data' in result:
        data_rows = []
        csv_lines = result['csv_data'].strip().split('\n')
        if len(csv_lines) >= 1:
            # Check if first line is a header or data row
            first_line_parts = [h.strip() for h in csv_lines[0].split('|')]
            
            # Detect if it's a header row (contains Account/Category/Month names)
            first_col_lower = first_line_parts[0].lower() if first_line_parts else ''
            has_header = first_col_lower in ['account', 'distribution account', 'name', 'description']
            
            if has_header and len(csv_lines) > 1:
                headers = first_line_parts
                data_start = 1
            else:
                # No header row - assume 3-column format: Account|Category|Amount
                headers = ['Account', 'Category', 'Total']
                data_start = 0
            
            # Robust month/period mapping
            month_indices = {}
            for i, h in enumerate(headers):
                h_clean = h.strip().rstrip('.').capitalize()
                # Check for standard 3-letter codes
                if h_clean in MONTH_NAMES:
                    month_indices[h_clean] = i
                # Check for YTD/Total column (for reports without monthly breakdown)
                elif h_clean in ['Total', 'Ytd', 'Year', 'Annual', 'Amount']:
                    month_indices['YTD'] = i
                # Check for full names
                else:
                    for std_m in MONTH_NAMES:
                        if h_clean.startswith(std_m):
                            month_indices[std_m] = i
                            break
                        # Handle Sept/Sep
                        if std_m == 'Sep' and h_clean.startswith('Sept'):
                            month_indices['Sep'] = i
                            break
            
            # If still no month indices found but we have 3+ columns, assume column 2+ are amounts
            if not month_indices and len(headers) >= 3:
                month_indices['YTD'] = 2  # Third column is the amount
            
            for line in csv_lines[data_start:]:
                parts = [p.strip() for p in line.split('|')]
                if len(parts) >= 3:
                    account = parts[0]
                    category = parts[1]
                    
                    # For each month column, create a flat row
                    for month, idx in month_indices.items():
                        if idx < len(parts):
                            amt_str = parts[idx]
                            # Basic cleaning
                            try:
                                # Clean amount string - handle $ ( ) , and -
                                amt_str = amt_str.replace(',', '').replace('$', '').replace('(', '-').replace(')', '').strip()
                                if not amt_str or amt_str == '-' or amt_str == '—':
                                    amount = 0.0
                                else:
                                    amount = float(amt_str)
                                
                                if amount != 0:
                                    data_rows.append({
                                        'Account': account,
                                        'Category': category,
                                        'Month': month,
                                        'Amount': amount
                                    })
                            except:
                                continue
        result['data'] = data_rows
        
        # Create a sample preview if not provided
        if 'sample_preview' not in result:
            result['sample_preview'] = data_rows[:5]
    
    return result


def validate_and_format_data(ai_result: Dict[str, Any], company_override: str = None, 
                              year_override: int = None) -> List[Dict[str, Any]]:
    """
    Validate AI-extracted data and format for dashboard.
    Allows user overrides for company name and year.
    """
    
    company = company_override or ai_result.get('company_name', 'Unknown Company')
    year = year_override or ai_result.get('year', datetime.now().year)
    
    validated_data = []
    
    # Summary patterns to filter out (prevent double-counting)
    summary_patterns = [
        'total income', 'total expenses', 'total cost of goods sold', 
        'total cogs', 'total other income', 'total other expenses',
        'net income', 'net other income', 'net operating income', 
        'gross profit', 'net profit'
    ]
    
    def is_summary_row(account):
        if not account:
            return False
        account_lower = str(account).strip().lower()
        # Check exact match to summary patterns
        if account_lower in summary_patterns:
            return True
        # Check if it starts with "Total " or "Total for"
        if account_lower.startswith('total ') or account_lower.startswith('total for '):
            return True
        return False
    
    for item in ai_result.get('data', []):
        # Skip summary rows
        account_name = item.get('Account', '')
        if is_summary_row(account_name):
            continue
        
        # Validate category
        category = item.get('Category', 'Expenses')
        if category not in VALID_CATEGORIES:
            # Try to match closest
            category_lower = category.lower()
            if 'income' in category_lower or 'revenue' in category_lower:
                category = 'Income'
            elif 'cost' in category_lower or 'cogs' in category_lower:
                category = 'Cost of Goods Sold'
            else:
                category = 'Expenses'
        
        # Validate month/period (allow YTD for year-to-date reports)
        month = item.get('Month', 'Jan')
        valid_periods = MONTH_NAMES + ['YTD']
        if month not in valid_periods:
            # Try to match
            month_lower = month.lower()[:3].capitalize()
            if month_lower in MONTH_NAMES:
                month = month_lower
            elif month.lower() in ['total', 'ytd', 'year', 'annual']:
                month = 'YTD'
            else:
                continue  # Skip invalid month/period
        
        # Validate amount
        try:
            amount = float(item.get('Amount', 0))
        except (ValueError, TypeError):
            continue
        
        if amount == 0:
            continue
        
        validated_data.append({
            'Account': str(item.get('Account', '')).strip(),
            'Category': category,
            'Amount': amount,
            'Company': company,
            'Month': month,
            'Year': int(year)
        })
    
    return validated_data


def get_conversion_preview(content: bytes, filename: str, api_key: str = None) -> Dict[str, Any]:
    """
    Get a preview of the conversion for user confirmation.
    Returns metadata and sample data for user to verify before creating dashboard.
    """
    
    if not api_key:
        api_key = os.environ.get('GEMINI_API_KEY')
    if not api_key:
        raise ValueError("Gemini API key required. Set GEMINI_API_KEY environment variable.")
    
    # Detect file type
    file_type = detect_file_type(filename, content)
    
    # Extract text
    text_content = extract_text_from_file(content, filename, file_type)
    
    # Get AI parsing
    ai_result = convert_with_gemini(text_content, api_key)
    
    # Build preview response
    preview = {
        'success': True,
        'file_type': file_type,
        'detected_info': {
            'company_name': ai_result.get('company_name', 'Unknown'),
            'year': ai_result.get('year', datetime.now().year),
            'months_found': ai_result.get('detected_months', []),
            'total_rows': len(ai_result.get('data', []))
        },
        'column_mapping': ai_result.get('column_mapping', {}),
        'sample_data': ai_result.get('sample_preview', ai_result.get('data', [])[:5]),
        'categories_found': list(set(item.get('Category') for item in ai_result.get('data', []))),
        # Store raw result for final conversion
        '_raw_ai_result': ai_result
    }
    
    return preview


def finalize_conversion(ai_result: Dict[str, Any], user_adjustments: Dict[str, Any] = None) -> pd.DataFrame:
    """
    Finalize the conversion after user confirmation.
    User can optionally provide adjustments to company name, year, or category mappings.
    """
    
    adjustments = user_adjustments or {}
    
    # Get validated data with any user overrides
    validated_data = validate_and_format_data(
        ai_result,
        company_override=adjustments.get('company_name'),
        year_override=adjustments.get('year')
    )
    
    # Apply any category remapping from user
    category_remap = adjustments.get('category_remap', {})
    if category_remap:
        for item in validated_data:
            if item['Account'] in category_remap:
                item['Category'] = category_remap[item['Account']]
    
    # Convert to DataFrame
    df = pd.DataFrame(validated_data)
    
    if len(df) == 0:
        raise ValueError("No valid data rows after conversion")
    
    # Ensure correct column order
    column_order = ['Account', 'Category', 'Amount', 'Company', 'Month', 'Year']
    df = df[column_order]
    
    return df


def convert_quickbooks_file(content: bytes, filename: str, api_key: str = None) -> pd.DataFrame:
    """
    Direct conversion without preview (for backward compatibility).
    Saves debug output for visibility into AI extraction.
    """
    
    if not api_key:
        api_key = os.environ.get('GEMINI_API_KEY')
    if not api_key:
        raise ValueError("Gemini API key required.")
    
    file_type = detect_file_type(filename, content)
    text_content = extract_text_from_file(content, filename, file_type)
    ai_result = convert_with_gemini(text_content, api_key)
    
    # Get validated data
    df = finalize_conversion(ai_result)
    
    # Save debug output for training/visibility
    try:
        validated_list = df.to_dict('records') if len(df) > 0 else []
        save_debug_output(filename, ai_result, validated_list)
    except Exception as e:
        print(f"[DEBUG] Warning: Could not save debug output: {e}")
    
    return df


# Test function
if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1:
        test_file = sys.argv[1]
        print(f"Testing AI conversion of: {test_file}")
        
        try:
            with open(test_file, 'rb') as f:
                content = f.read()
            filename = os.path.basename(test_file)
            
            # Test preview
            print("\n=== Getting Preview ===")
            preview = get_conversion_preview(content, filename)
            
            print(f"Company: {preview['detected_info']['company_name']}")
            print(f"Year: {preview['detected_info']['year']}")
            print(f"Months: {preview['detected_info']['months_found']}")
            print(f"Total rows: {preview['detected_info']['total_rows']}")
            print(f"Categories: {preview['categories_found']}")
            
            print("\n=== Sample Data ===")
            for row in preview['sample_data'][:5]:
                print(row)
            
            # Test final conversion
            print("\n=== Final Conversion ===")
            df = finalize_conversion(preview['_raw_ai_result'])
            print(f"Generated {len(df)} rows")
            print(df.head(10).to_string(index=False))
            
        except Exception as e:
            print(f"Error: {e}")
            import traceback
            traceback.print_exc()
    else:
        print("Usage: python quickbooks_converter.py <path_to_file>")
