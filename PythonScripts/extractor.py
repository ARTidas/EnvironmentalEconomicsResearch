import os
import glob
import re
import mysql.connector
from bs4 import BeautifulSoup
import config

HTML_DIR = '../DataSource/'

def sanitize_name(name):
    name = name.lower()
    name = name.replace('%', 'percentage')
    name = name.replace('$', 'usd')
    name = name.replace('€', 'eur')
    name = name.replace('£', 'gbp')
    name = name.replace('/', '_per_')
    
    name = re.sub(r'[^a-z0-9_]', '_', name)
    name = re.sub(r'_+', '_', name).strip('_')
    
    if not name:
        name = "unknown_metric"
        
    return name

def process_html_files():
    try:
        conn = mysql.connector.connect(**config.DB_CONFIG)
        cursor = conn.cursor()
        print("Successfully connected to the database.")
    except Exception as e:
        print(f"Error connecting to database: {e}")
        return

    file_pattern = os.path.join(HTML_DIR, '*.html')
    html_files = glob.glob(file_pattern)

    if not html_files:
        print("No HTML files found in the directory.")
        return

    for filepath in html_files:
        filename = os.path.basename(filepath)

        with open(filepath, 'r', encoding='utf-8') as f:
            soup = BeautifulSoup(f, 'html.parser')

        country_name = "Unknown_Country"
        raw_table_name = "Unknown_Metric"
        
        h1_tag = soup.find('h1')
        if h1_tag and " - " in h1_tag.text:
            parts = h1_tag.text.strip().split(" - ", 1)
            country_name = parts[0].strip()
            raw_table_name = parts[1].strip()
        else:
            title_tag = soup.find('title')
            if title_tag and title_tag.text:
                title_text = title_tag.text.strip().split('|')[0].strip()
                if " - " in title_text:
                    parts = title_text.split(" - ", 1)
                    country_name = parts[0].strip()
                    raw_table_name = parts[1].strip()
                else:
                    raw_table_name = title_text
                    if title_text.lower().startswith("hungary "):
                        country_name = "Hungary"
                        raw_table_name = title_text[8:]

        # Clean stray words from country name
        country_name = re.sub(r'(?i)\s+(GDP|CPI|National Debt|Government).*', '', country_name).strip()
        raw_table_name = re.sub(r'\s*\d{4}$', '', raw_table_name).strip()
        table_name = "country_metric_" + sanitize_name(raw_table_name)

        print(f"Processing file '{filename}' into table '{table_name}' [Country: {country_name}]...")

        # Smart table selection: get all potential data tables and pick the one with the most rows
        tables = soup.find_all('table', id='tb0') + soup.find_all('table', class_='tabledat')
        if not tables:
            print(f"  -> Warning: No data tables found in {filename}.")
            continue
            
        table = max(tables, key=lambda t: len(t.find_all('tr')))

        thead = table.find('thead')
        if not thead:
            print(f"  -> Warning: Table header (thead) not found in {filename}.")
            continue

        headers = [th.text.strip() for th in thead.find_all('th')]
        
        # Change 'year' to 'period' to support Q1, Q2, etc. safely
        raw_columns = ['country', 'period'] + [sanitize_name(h) for h in headers[1:]]
        
        columns = []
        seen = set()
        for col in raw_columns:
            new_col = col
            counter = 2
            while new_col in seen:
                new_col = f"{col}_{counter}"
                counter += 1
            seen.add(new_col)
            columns.append(new_col)

        col_definitions = [
            "`country` VARCHAR(100)",
            "`period` VARCHAR(50)"
        ] + [f"`{col}` FLOAT" for col in columns[2:]] + [
            "PRIMARY KEY (`country`, `period`)"
        ]
        
        create_table_sql = f"CREATE TABLE IF NOT EXISTS `{table_name}` (\n    " + ",\n    ".join(col_definitions) + "\n);"
        cursor.execute(create_table_sql)

        placeholders = ", ".join(["%s"] * len(columns))
        escaped_cols = ", ".join([f"`{c}`" for c in columns])
        insert_sql = f"REPLACE INTO `{table_name}` ({escaped_cols}) VALUES ({placeholders})"

        tbody = table.find('tbody')
        rows = tbody.find_all('tr') if tbody else table.find_all('tr')[1:]
        rows_inserted = 0

        for tr in rows:
            cells = tr.find_all(['td', 'th'])
            if not cells or len(cells) < 2:
                continue

            # Extract the raw string for the period (e.g., "2026", "2026 Q1")
            period_text = cells[0].text.strip()
            if not period_text:
                continue
            
            row_data = [country_name, period_text]

            for cell in cells[1:]:
                val = cell.get('data-value')
                
                if val is None or val.strip() == '':
                    raw_text = cell.text.replace(',', '').strip()
                    num_match = re.search(r'-?\d+\.?\d*', raw_text)
                    if num_match:
                        val = num_match.group(0)
                
                if val is None or val.strip() == '':
                    row_data.append(None)
                else:
                    try:
                        row_data.append(float(val))
                    except ValueError:
                        row_data.append(None)

            if len(row_data) > len(columns):
                row_data = row_data[:len(columns)]
            elif len(row_data) < len(columns):
                row_data.extend([None] * (len(columns) - len(row_data)))

            cursor.execute(insert_sql, row_data)
            rows_inserted += 1

        conn.commit()
        print(f"  -> Successfully processed and inserted {rows_inserted} rows into `{table_name}`.\n")

    cursor.close()
    conn.close()
    print("Database population process finished.")

if __name__ == '__main__':
    process_html_files()