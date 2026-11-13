import sys
import json
import hashlib
import sqlite3
from pathlib import Path
from datetime import datetime, timezone
from esporta_reports import rigenera_tutti_i_reports

BASE_DIR = Path(__file__).resolve().parent.parent

def calcola_sha256(percorso_file: Path) -> str:
    hasher = hashlib.sha256()
    with open(percorso_file, "rb") as f:
        while blocco := f.read(1048576):
            hasher.update(blocco)
    return hasher.hexdigest()

def trova_cartella_gioco(cartella_libreria: Path, gog_id_clean: str) -> Path:
    for sottocartella in cartella_libreria.iterdir():
        if sottocartella.is_dir():
            if (sottocartella / f"goggame-{gog_id_clean}.info").exists():
                return sottocartella
    return None

def carica_manifest_gioco(cartella_json: Path, id_gioco_completo: str) -> tuple:
    for file_m in cartella_json.glob("*_manifest_sha256.json"):
        with open(file_m, "r", encoding="utf-8") as f:
            dati = json.load(f)
            if dati.get("gog_game_id") == id_gioco_completo:
                return dati, file_m.name, calcola_sha256(file_m)
    return None, None, None

def carica_esclusioni(percorso_config: Path) -> tuple:
    if not percorso_config.exists():
        return set(), set()
    with open(percorso_config, "r", encoding="utf-8") as f:
        dati = json.load(f)
    cartelle = {c.lower() for c in dati.get("cartelle_escluse", [])}
    estensioni = {e.lower() for e in dati.get("estensioni_escluse", [])}
    return cartelle, estensioni

def file_da_ignorare(percorso_file: Path, radice_gioco: Path, cartelle_escluse: set, estensioni_escluse: set) -> bool:
    if percorso_file.suffix.lower() in estensioni_escluse:
        return True
    parti_relative = {p.lower() for p in percorso_file.relative_to(radice_gioco).parts[:-1]}
    return bool(parti_relative.intersection(cartelle_escluse))

def esegui_audit_integrita(modalita: str = "rapido"):
    file_settings = BASE_DIR / "config" / "settings.json"
    file_db = BASE_DIR / "database" / "archivio_giochi.db"
    cartella_json = BASE_DIR / "output_json"

    if not file_settings.exists() or not file_db.exists():
        print("ERRORE: File di configurazione o database mancanti.", flush=True)
        return

    with open(file_settings, "r", encoding="utf-8") as f:
        settings = json.load(f)

    cartella_libreria = Path(settings.get("gog_library_path", ""))
    if not cartella_libreria.exists():
        print(f"ERRORE: Libreria GOG non trovata in '{cartella_libreria}'.", flush=True)
        return

    conn = sqlite3.connect(file_db)
    conn.row_factory = sqlite3.Row
    cursore = conn.cursor()

    cursore.execute("""
        CREATE TABLE IF NOT EXISTS condition_reports (
            id_report INTEGER PRIMARY KEY AUTOINCREMENT,
            id_gioco TEXT NOT NULL,
            data_ispezione TEXT NOT NULL,
            tipo_operazione TEXT NOT NULL,
            agente TEXT NOT NULL,
            stato_integrita TEXT NOT NULL,
            manifest_riferimento TEXT,
            hash_rilevato TEXT,
            note_tecniche TEXT
        );
    """)

    cursore.execute("""
        SELECT g.id_gioco, g.titolo, o.percorso_relativo, o.valore_hash
        FROM giochi g
        JOIN oggetti_digitali o ON g.id_gioco = o.id_gioco
        ORDER BY g.titolo ASC;
    """)
    record_da_verificare = cursore.fetchall()

    print(f"Avvio Fixity Audit [{modalita.upper()}] su {len(record_da_verificare)} opere...", flush=True)
    data_audit = datetime.now(timezone.utc).isoformat()

    for r in record_da_verificare:
        id_gioco = r["id_gioco"]
        gog_id_numerico = id_gioco.replace("GOG-", "")
        titolo = r["titolo"]
        percorso_rel = r["percorso_relativo"]
        hash_atteso = r["valore_hash"]

        cartella_gioco = trova_cartella_gioco(cartella_libreria, gog_id_numerico)
        hash_rilevato = None
        nome_manifest = None

        if not cartella_gioco:
            stato = "MISSING"
            note = "Cartella di installazione non trovata sul disco locale."
            tipo_op = f"Fixity Audit ({modalita.capitalize()})"
        elif modalita == "rapido":
            tipo_op = "Quick Fixity Audit (Main Executable)"
            file_reale = cartella_gioco / percorso_rel
            if not file_reale.exists():
                stato = "MISSING"
                note = f"Eseguibile principale '{percorso_rel}' assente o spostato."
            else:
                hash_rilevato = calcola_sha256(file_reale)
                if hash_rilevato == hash_atteso:
                    stato = "INTACT"
                    note = f"Verifica rapida SHA-256 superata su '{percorso_rel}'."
                else:
                    stato = "CORRUPTED"
                    note = f"ALLARME: Hash modificato su '{percorso_rel}'!"
        else:
            tipo_op = "Deep Package Fixity Audit (Full Manifest)"
            manifest, nome_manifest, hash_manifest = carica_manifest_gioco(cartella_json, id_gioco)
            if not manifest:
                stato = "WARNING"
                note = "Manifest integrale SHA-256 non trovato. Esegui prima la sincronizzazione completa (Modulo 1)."
            else:
                hash_rilevato = hash_manifest
                files_attesi = manifest.get("files", {})
                totale_f = len(files_attesi)
                corrotti = []
                mancanti = []

                print(f"PROGRESSO|0|Audit {titolo}: inizio verifica su {totale_f} file...", flush=True)
                for idx, (rel_path, info_attese) in enumerate(files_attesi.items(), start=1):
                    if idx % 250 == 0 or idx == totale_f:
                        perc = int((idx / totale_f) * 100)
                        print(f"PROGRESSO|{perc}|Audit {titolo}: {idx}/{totale_f} file ({perc}%)", flush=True)
                    f_disco = cartella_gioco / rel_path
                    if not f_disco.exists():
                        mancanti.append(rel_path)
                    else:
                        if calcola_sha256(f_disco) != info_attese["sha256"]:
                            corrotti.append(rel_path)

                cartelle_escl, estensioni_escl = carica_esclusioni(BASE_DIR / "config" / "esclusioni_audit.json")
                files_su_disco = {
                    str(f.relative_to(cartella_gioco)).replace("\\", "/")
                    for f in cartella_gioco.rglob("*")
                    if f.is_file() and not file_da_ignorare(f, cartella_gioco, cartelle_escl, estensioni_escl)
                }
                estranei = sorted(files_su_disco - set(files_attesi.keys()))

                if not corrotti and not mancanti and not estranei:
                    stato = "INTACT"
                    note = f"Verifica integrale superata: tutti i {totale_f} file corrispondono al manifest '{nome_manifest}'."
                elif corrotti or mancanti:
                    stato = "CORRUPTED"
                    dettagli = []
                    if corrotti:
                        dettagli.append(f"{len(corrotti)} corrotti ({', '.join(corrotti[:3])}...)")
                    if mancanti:
                        dettagli.append(f"{len(mancanti)} mancanti ({', '.join(mancanti[:3])}...)")
                    if estranei:
                        dettagli.append(f"{len(estranei)} file aggiunti")
                    note = "ALLARME INTEGRITÀ PACCHETTO: " + "; ".join(dettagli) + "."
                else:
                    stato = "WARNING"
                    note = f"Tutti i {totale_f} file originali sono intatti, ma rilevati {len(estranei)} file aggiuntivi (es. salvataggi/mod: {', '.join(estranei[:3])})."

        print(f"[{stato}] {titolo} -> {note}", flush=True)

        cursore.execute("""
            INSERT INTO condition_reports (
                id_gioco, data_ispezione, tipo_operazione, agente,
                stato_integrita, manifest_riferimento, hash_rilevato, note_tecniche
            ) VALUES (?, ?, ?, 'System Checksum Verifier v2.0', ?, ?, ?, ?);
        """, (id_gioco, data_audit, tipo_op, stato, nome_manifest, hash_rilevato, note))

    conn.commit()
    conn.close()
    rigenera_tutti_i_reports(file_db)
    print("Audit completato e registrato nello storico dei Condition Report!", flush=True)

if __name__ == "__main__":
    modo = "profondo" if "--profondo" in sys.argv else "rapido"
    esegui_audit_integrita(modo)
