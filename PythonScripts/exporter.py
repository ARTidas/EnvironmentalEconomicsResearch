import pandas as pd
import mysql.connector
import re
import warnings
import config

# Pandas figyelmeztetések elrejtése a natív MySQL csatlakozó használata miatt
warnings.filterwarnings('ignore', category=UserWarning)

def export_database_to_csv():
    try:
        conn = mysql.connector.connect(**config.DB_CONFIG)
        print("Adatbázis kapcsolat sikeres. Táblák beolvasása...")
    except Exception as e:
        print(f"Hiba az adatbázis-kapcsolat során: {e}")
        return

    # Az összes tábla nevének lekérdezése dinamikusan
    cursor = conn.cursor()
    cursor.execute("SHOW TABLES")
    tables = [row[0] for row in cursor.fetchall()]
    
    dfs = []
    
    for table in tables:
        # Csak a megfelelő előtagú táblákat olvassuk be
        if not table.startswith('country_metric_'):
            continue
            
        query = f"SELECT * FROM `{table}`"
        df = pd.read_sql(query, conn)
        
        if df.empty:
            print(f"  -> Üres tábla kihagyva: {table}")
            continue
            
        print(f"  -> Tábla feldolgozása: {table} ({len(df)} sor)")
        
        # Oszlopok átnevezése, hogy az egyesítésnél azonosítható legyen, melyik metrikához tartoznak
        metric_prefix = table.replace('country_metric_', '')
        rename_mapping = {}
        for col in df.columns:
            if col not in ['country', 'period']:
                # Ha a tábla neve és az oszlop neve már hasonló, elkerüljük a dupla megnevezéseket
                clean_col = col.replace(metric_prefix + "_", "") 
                rename_mapping[col] = f"{metric_prefix}_{clean_col}"
                
        df = df.rename(columns=rename_mapping)
        
        # A period oszlopot stringgé alakítjuk a stabil összekapcsolás (merge) érdekében
        df['period'] = df['period'].astype(str)
        dfs.append(df)
        
    if not dfs:
        print("Nem található exportálható adat.")
        return
        
    print("\nTáblák egyesítése (Merge)...")
    master_df = dfs[0]
    for i, df in enumerate(dfs[1:]):
        # Külső illesztés a country és period oszlopokon
        master_df = pd.merge(master_df, df, on=['country', 'period'], how='outer')

    # Évszám kinyerése a period-ből (pl. "2026 Q1" -> 2026) a szűréshez
    master_df['year_numeric'] = master_df['period'].str.extract(r'(\d{4})').astype(float)
    
    # Szűrés az 1950 és 2026 közötti időszakra
    initial_rows = len(master_df)
    master_df = master_df[(master_df['year_numeric'] >= 1950) & (master_df['year_numeric'] <= 2026)]
    filtered_rows = len(master_df)
    
    print(f"Időszak szűrése (1950-2026): {initial_rows} sorból {filtered_rows} maradt.")
    
    # Rendezzük a táblát országok és időszak szerint csökkenő sorrendbe (legfrissebb elöl)
    master_df = master_df.drop(columns=['year_numeric'])
    master_df = master_df.sort_values(by=['country', 'period'], ascending=[True, False])
    
    # Exportálás CSV formátumba
    export_filename = "../DataSource/Hungary_Full_Macroeconomic_Database_1950_2026.csv"
    master_df.to_csv(export_filename, index=False, encoding='utf-8')
    
    print(f"\nSikeres exportálás! A fájl elmentve: {export_filename}")
    print(f"Végleges adathalmaz mérete: {master_df.shape[0]} sor, {master_df.shape[1]} oszlop.")

    cursor.close()
    conn.close()

if __name__ == '__main__':
    export_database_to_csv()