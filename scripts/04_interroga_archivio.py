import sqlite3
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

def connetti_db(percorso_db: Path):
    if not percorso_db.exists():
        raise FileNotFoundError(f"Database non trovato in: {percorso_db}. Esegui prima gli script 01, 02 e 03.")
    conn = sqlite3.connect(percorso_db)
    conn.row_factory = sqlite3.Row
    return conn

def elenco_completo_giochi(percorso_db: Path):
    conn = connetti_db(percorso_db)
    cursore = conn.cursor()

    query = """
        SELECT 
            g.id_gioco,
            g.titolo,
            g.sviluppatore,
            g.data_rilascio,
            g.versione_edizione,
            o.percorso_relativo AS eseguibile,
            o.formato_binario,
            a.descrizione AS game_engine
        FROM giochi g
        LEFT JOIN oggetti_digitali o ON g.id_gioco = o.id_gioco
        LEFT JOIN ambienti_eventi a ON g.id_gioco = a.id_gioco 
            AND a.categoria = 'software_environment' 
            AND a.tipo = 'game engine'
        ORDER BY g.titolo ASC;
    """
    cursore.execute(query)
    risultati = cursore.fetchall()
    conn.close()

    print(f"\n=== CATALOGO COMPLETO ({len(risultati)} titoli) ===")
    for r in risultati:
        print(f"[{r['id_gioco']}] {r['titolo']} ({r['data_rilascio']})")
        print(f"   Sviluppatore : {r['sviluppatore']} | Versione: {r['versione_edizione']}")
        print(f"   Engine       : {r['game_engine']}")
        print(f"   Eseguibile   : {r['eseguibile']} -> {r['formato_binario']}")
        print("-" * 60)

def cerca_per_engine_o_architettura(percorso_db: Path, parola_chiave: str):
    conn = connetti_db(percorso_db)
    cursore = conn.cursor()

    query = """
        SELECT DISTINCT
            g.id_gioco,
            g.titolo,
            o.formato_binario,
            a.descrizione AS dettaglio_ambiente
        FROM giochi g
        JOIN oggetti_digitali o ON g.id_gioco = o.id_gioco
        JOIN ambienti_eventi a ON g.id_gioco = a.id_gioco
        WHERE a.descrizione LIKE ? OR o.formato_binario LIKE ?;
    """
    filtro = f"%{parola_chiave}%"
    cursore.execute(query, (filtro, filtro))
    risultati = cursore.fetchall()
    conn.close()

    print(f"\n=== RISULTATI RICERCA PER '{parola_chiave}' ({len(risultati)} trovati) ===")
    for r in risultati:
        print(f"- {r['titolo']} [{r['id_gioco']}] | {r['formato_binario']} | {r['dettaglio_ambiente']}")

def verifica_hash_file(percorso_db: Path, hash_cercato: str):
    conn = connetti_db(percorso_db)
    cursore = conn.cursor()

    query = """
        SELECT 
            g.titolo,
            g.id_gioco,
            o.percorso_relativo,
            o.dimensione_byte,
            o.algoritmo_hash,
            o.valore_hash
        FROM oggetti_digitali o
        JOIN giochi g ON o.id_gioco = g.id_gioco
        WHERE o.valore_hash LIKE ?;
    """
    cursore.execute(query, (f"{hash_cercato}%",))
    risultati = cursore.fetchall()
    conn.close()

    print(f"\n=== VERIFICA IMPRONTA DIGITALE ({hash_cercato}...) ===")
    if not risultati:
        print("Nessun file corrispondente trovato nel database.")
    for r in risultati:
        print(f"Trovato! Appartiene a: {r['titolo']} ({r['id_gioco']})")
        print(f"File       : {r['percorso_relativo']} ({r['dimensione_byte']} byte)")
        print(f"{r['algoritmo_hash']}    : {r['valore_hash']}")

def mostra_storia_preservazione(percorso_db: Path, id_gioco: str):
    conn = connetti_db(percorso_db)
    cursore = conn.cursor()

    cursore.execute("SELECT titolo FROM giochi WHERE id_gioco = ?;", (id_gioco,))
    gioco = cursore.fetchone()
    if not gioco:
        print(f"Nessun gioco trovato con ID {id_gioco}")
        conn.close()
        return

    cursore.execute("""
        SELECT categoria, tipo, descrizione, data_registrazione
        FROM ambienti_eventi
        WHERE id_gioco = ?
        ORDER BY data_registrazione ASC;
    """, (id_gioco,))
    eventi = cursore.fetchall()
    conn.close()

    print(f"\n=== SCHEDA TECNICA E EVENTI PREMIS: {gioco['titolo']} ===")
    for e in eventi:
        print(f"[{e['categoria'].upper()}] {e['tipo']}: {e['descrizione']} (Data: {e['data_registrazione']})")

if __name__ == "__main__":
    FILE_DATABASE = BASE_DIR / "database" / "archivio_giochi.db"

    while True:
        print("\n--- INTERROGAZIONE ARCHIVIO VIDEOLUDICO ---")
        print("1. Mostra catalogo completo (JOIN tra DC, MODS e PREMIS)")
        print("2. Cerca per Game Engine o Architettura (es. Eclipse, Unity, 32-bit)")
        print("3. Verifica un'impronta SHA-256 (anche solo i primi caratteri)")
        print("4. Mostra dettagli ambienti ed eventi PREMIS di un gioco (tramite ID)")
        print("0. Esci")
        
        scelta = input("\nScegli un'opzione: ").strip()
        
        if scelta == "1":
            elenco_completo_giochi(FILE_DATABASE)
        elif scelta == "2":
            termine = input("Inserisci termine da cercare: ").strip()
            cerca_per_engine_o_architettura(FILE_DATABASE, termine)
        elif scelta == "3":
            h = input("Inserisci hash SHA-256 (anche i primi 8 caratteri): ").strip()
            verifica_hash_file(FILE_DATABASE, h)
        elif scelta == "4":
            gid = input("Inserisci ID gioco (es. GOG-1949616134): ").strip()
            mostra_storia_preservazione(FILE_DATABASE, gid)
        elif scelta == "0":
            print("Chiusura programma.")
            break
        else:
            print("Scelta non valida.")
